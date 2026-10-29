"""Proteções do agente local: confere a chamada antes de executar e pede confirmação ao usuário.

Um modelo pequeno erra argumento, inventa caminho e, se ninguém segurar, renderiza o vídeo final ou
sobrescreve um projeto sem perguntar. Aqui ficam as três barreiras, todas funções puras sobre dados, com o
disco e a pessoa entrando por injeção: o esquema da ferramenta (erro em português simples de volta ao modelo),
o caminho de arquivo que não existe (o modelo deve perguntar, não chutar) e a confirmação do que é longo ou
difícil de desfazer. A lista do que precisa de confirmação é dado (`CONFIRMATION_RULES`).
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from jsonschema import Draft202012Validator

ConfirmationKind = Literal["action", "voice_consent"]

_TYPE_NAMES = {
    "string": "texto",
    "integer": "número inteiro",
    "number": "número",
    "boolean": "sim ou não (true ou false)",
    "array": "lista",
    "object": "objeto",
    "null": "vazio",
}
_PYTHON_TYPE_NAMES = {
    str: "texto",
    bool: "sim ou não",
    int: "número inteiro",
    float: "número",
    list: "lista",
    dict: "objeto",
    type(None): "vazio",
}

# Argumentos que apontam para um arquivo que já deve existir. `output`, `out` e `out_dir` ficam de fora: são
# o destino, criado pela ferramenta.
PATH_ARGUMENTS = frozenset(
    {
        "src",
        "source",
        "path",
        "paths",
        "video",
        "master",
        "others",
        "reference_audio",
        "file_path",
        "music",
        "sheet",
    }
)
OUTPUT_ARGUMENTS = ("out", "out_dir")
MEDIA_EXTENSIONS = frozenset(
    {
        ".mp4",
        ".mov",
        ".mkv",
        ".webm",
        ".avi",
        ".m4v",
        ".wav",
        ".mp3",
        ".m4a",
        ".flac",
        ".aac",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".csv",
        ".xlsx",
        ".srt",
        ".txt",
    }
)
_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


# ---------- esquema ----------


def _type_label(expected: Any) -> str:
    options = expected if isinstance(expected, list) else [expected]
    return " ou ".join(dict.fromkeys(_TYPE_NAMES.get(name, str(name)) for name in options if name != "null"))


def _argument_name(path: Iterable[Any]) -> str:
    return ".".join(str(part) for part in path) or "argumentos"


def _error_message(error: Any) -> str:
    where = _argument_name(error.path)
    if error.validator == "required":
        missing = [name for name in error.validator_value if name not in error.instance]
        return "falta o argumento " + ", ".join(f"'{name}'" for name in missing)
    if error.validator == "type":
        got = _PYTHON_TYPE_NAMES.get(type(error.instance), type(error.instance).__name__)
        return f"o argumento '{where}' deve ser {_type_label(error.validator_value)}, mas veio {got}"
    if error.validator == "enum":
        options = ", ".join(str(value) for value in error.validator_value)
        return f"o argumento '{where}' deve ser um destes valores: {options}"
    if error.validator in {"anyOf", "oneOf"}:
        return f"o argumento '{where}' tem um tipo que a ferramenta não aceita"
    return f"o argumento '{where}' tem um valor fora do permitido ({error.message})"


def validate_arguments(schema: Mapping[str, Any], arguments: Mapping[str, Any]) -> list[str]:
    """Os problemas da chamada contra o esquema da ferramenta, em português simples (vazio quando está certa)."""
    problems: list[str] = []
    allowed = set((schema.get("properties") or {}).keys())
    for name in arguments:
        if allowed and name not in allowed:
            problems.append(
                f"o argumento '{name}' não existe nesta ferramenta (aceitos: {', '.join(sorted(allowed))})"
            )
    for error in Draft202012Validator(dict(schema)).iter_errors(dict(arguments)):
        problems.append(_error_message(error))
    return list(dict.fromkeys(problems))


# ---------- caminhos ----------

# Argumentos cujo valor é um mapa de parâmetros livres (os do template, os assuntos do explicativo): ali um
# texto só conta como caminho se parece um (unidade, barra inicial ou extensão de mídia).
LOOSE_PATH_ARGUMENTS = frozenset({"params", "subjects"})
# Argumentos estruturados (a spec e a operação de edição): só `src` e caminhos absolutos contam.
STRUCTURED_ARGUMENTS = frozenset({"spec", "op"})


def _walk(value: Any, key: str) -> Iterable[tuple[str, str]]:
    """Cada texto dentro de um valor de argumento, com o nome da chave mais próxima (em qualquer nível)."""
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, Mapping):
        for name, item in value.items():
            yield from _walk(item, str(name))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item, key)


def is_absolute_path(text: str) -> bool:
    stripped = text.strip()
    return bool(_DRIVE_PATH.match(stripped)) or stripped.startswith(("/", "\\\\"))


def looks_like_file_path(text: str) -> bool:
    """Texto que parece o caminho de um arquivo ou pasta: com unidade (C:), barra inicial ou extensão de mídia."""
    stripped = text.strip()
    if not stripped or "\n" in stripped or len(stripped) > 400:
        return False
    return is_absolute_path(stripped) or os.path.splitext(stripped)[1].lower() in MEDIA_EXTENSIONS


_SEPARATORS = re.compile(r"[\\/]+")


def _normalize_path_text(text: str) -> str:
    """Barras de qualquer tipo viram uma só e maiúsculas somem: o caminho dentro de um JSON (barras duplas)
    e o digitado pela pessoa passam a ser o mesmo texto."""
    return _SEPARATORS.sub("/", text).casefold().strip()


@dataclass
class KnownPaths:
    """Caminhos que o modelo pode usar mesmo sem existir: os que a pessoa escreveu e os que uma ferramenta listou.

    Evita rejeitar o que não foi inventado. O manual do kit fica de fora de propósito: os caminhos dos exemplos
    dele (`C:/videos/gravacao.mp4`) são justamente os que um modelo pequeno copia sem perguntar.
    """

    _texts: list[str] = field(default_factory=list)

    def remember(self, text: str) -> None:
        self._texts.append(_normalize_path_text(text))

    def contains(self, path: str) -> bool:
        wanted = _normalize_path_text(path)
        return any(wanted in text for text in self._texts)


def input_paths(arguments: Mapping[str, Any]) -> list[str]:
    """Os caminhos que a chamada espera já existentes: os argumentos de entrada e os arquivos citados dentro deles."""
    found: list[str] = []
    for name, value in arguments.items():
        for key, text in _walk(value, name):
            if name in PATH_ARGUMENTS:
                found.append(text)
            elif name in LOOSE_PATH_ARGUMENTS and looks_like_file_path(text):
                found.append(text)
            elif name in STRUCTURED_ARGUMENTS and (
                is_absolute_path(text) or (key == "src" and looks_like_file_path(text))
            ):
                found.append(text)
    return list(dict.fromkeys(found))


def missing_paths(
    arguments: Mapping[str, Any], exists: Callable[[str], bool], known: KnownPaths
) -> list[str]:
    """Caminhos de entrada que não existem e não vieram da pessoa nem de uma listagem."""
    return [text for text in input_paths(arguments) if not exists(text) and not known.contains(text)]


def ask_user_about_paths(paths: list[str]) -> str:
    listed = ", ".join(f"'{path}'" for path in paths)
    return (
        f"erro: não encontrei {listed}, e esse caminho não veio do usuário nem de uma listagem. "
        "Não invente caminhos: pergunte ao usuário onde o arquivo está e espere a resposta."
    )


# ---------- confirmação ----------


@dataclass(frozen=True)
class ConfirmationRequest:
    """O que a pessoa precisa decidir: a ferramenta, os argumentos, a pergunta e o tipo (ação ou autorização de voz)."""

    tool: str
    arguments: Mapping[str, Any]
    question: str
    kind: ConfirmationKind = "action"


class ConfirmationPolicy(Protocol):
    """Quem responde à confirmação: a CLI pergunta no terminal, a interface mostra um botão."""

    def confirm(self, request: ConfirmationRequest) -> bool: ...


class DenyAll:
    """Sem ninguém para perguntar, nada que exige confirmação acontece."""

    def confirm(self, request: ConfirmationRequest) -> bool:
        return False


class ConfirmationDeferred(Exception):  # noqa: N818 - não é um erro: é o aviso de que a resposta virá na próxima mensagem
    """A política não responde na hora: a pergunta vai para a pessoa e a resposta vem na próxima mensagem."""


class ConversationalConfirmation:
    """A confirmação por conversa, para quem não tem botão nem terminal: adia a chamada até a pessoa responder.

    Em vez de bloquear esperando um sim, devolve o controle ao laço, que guarda a chamada pendente
    (`ToolGate.pending`) e deixa o modelo fazer a pergunta; só um "sim" claro na mensagem seguinte executa a
    chamada guardada, exatamente como foi confirmada.
    """

    def __init__(self) -> None:
        self.asked: list[str] = []

    def confirm(self, request: ConfirmationRequest) -> bool:
        self.asked.append(request.tool)
        raise ConfirmationDeferred(request.question)


@dataclass(frozen=True)
class PendingCall:
    """A chamada que espera o sim da pessoa: a ferramenta, os argumentos e a pergunta que foi feita."""

    tool: str
    arguments: Mapping[str, Any]
    question: str


_AFFIRMATIVE_STARTS = frozenset(
    {
        "sim",
        "confirmo",
        "confirmado",
        "pode",
        "claro",
        "ok",
        "okay",
        "isso",
        "vai",
        "manda",
        "autorizo",
        "autorizado",
        "positivo",
        "certo",
        "combinado",
        "fechado",
        "bora",
    }
)
# Palavras que fazem uma resposta deixar de ser um "sim" limpo: negação, ressalva ou mudança de pedido.
_BLOCKERS = frozenset(
    {
        "nao",
        "nunca",
        "jamais",
        "cancela",
        "cancelar",
        "pare",
        "para",
        "espera",
        "aguarda",
        "antes",
        "mas",
        "porem",
        "so",
        "somente",
        "apenas",
        "troca",
        "trocar",
        "muda",
        "mudar",
        "altera",
        "alterar",
        "depois",
    }
)
MAX_AFFIRMATIVE_WORDS = 14  # um "sim" é curto; texto longo costuma trazer um pedido novo junto


def is_affirmative(message: str) -> bool:
    """Um sim claro: começa por uma palavra de concordância, é curto e não traz negação, ressalva nem pergunta."""
    text = unicodedata.normalize("NFKD", message.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    if "?" in text:
        return False
    words = re.findall(r"[a-z]+", text)
    if not words or len(words) > MAX_AFFIRMATIVE_WORDS or words[0] not in _AFFIRMATIVE_STARTS:
        return False
    return not any(word in _BLOCKERS for word in words)


class ApproveAll:
    """Só para a bateria de avaliação e testes: aprova tudo e registra o que foi perguntado."""

    def __init__(self) -> None:
        self.asked: list[ConfirmationRequest] = []

    def confirm(self, request: ConfirmationRequest) -> bool:
        self.asked.append(request)
        return True


def _always(arguments: Mapping[str, Any]) -> bool:
    return True


def _unless_preview(arguments: Mapping[str, Any]) -> bool:
    return arguments.get("preview") is not True


def _unless_draft(arguments: Mapping[str, Any]) -> bool:
    return arguments.get("draft") is not True


def _overwrite_requested(arguments: Mapping[str, Any]) -> bool:
    return arguments.get("overwrite") is True or arguments.get("replace") is True


def _removes_content(arguments: Mapping[str, Any]) -> bool:
    op = arguments.get("op")
    return isinstance(op, Mapping) and op.get("type") in {"remove", "overlay_remove"}


def _removes_pronunciation(arguments: Mapping[str, Any]) -> bool:
    return arguments.get("action") == "remove"


@dataclass(frozen=True)
class ConfirmationRule:
    """Uma ferramenta que pede confirmação, o motivo (dito à pessoa) e quando vale (`applies`)."""

    tool: str
    reason: str
    applies: Callable[[Mapping[str, Any]], bool] = _always
    kind: ConfirmationKind = "action"


# Preparar a dublagem (transcrever e traduzir) não está aqui: gera um projeto editável e, num vídeo novo, só o
# `dub_render`, que produz o vídeo, pede o sim; pedir nos dois obrigaria a pessoa a confirmar duas vezes o mesmo
# pedido. O caso que muda é refazer a dublagem de um vídeo que já tem projeto: aí o `dub_prepare` escreve por cima
# e perde as traduções revisadas, e quem pergunta é `REPLACES_EXISTING_DUB_PROJECT` (abaixo), não esta lista.
CONFIRMATION_RULES: tuple[ConfirmationRule, ...] = (
    ConfirmationRule("render_project", "gerar o vídeo final (leva alguns minutos)", _unless_preview),
    ConfirmationRule("quick_edit", "gerar o vídeo final (leva alguns minutos)", _unless_preview),
    ConfirmationRule("export_project", "exportar o projeto em vários formatos (leva vários minutos)"),
    ConfirmationRule("run_batch", "gerar todos os vídeos da planilha (pode levar muito tempo)"),
    ConfirmationRule("resume_batch", "retomar o lote e gerar os vídeos que faltam (pode levar muito tempo)"),
    ConfirmationRule("dub_render", "gerar o vídeo dublado (leva vários minutos)", _unless_draft),
    ConfirmationRule("dub_stems", "gerar as trilhas separadas da dublagem (leva vários minutos)"),
    ConfirmationRule(
        "autocut", "refazer um projeto que já existe, apagando o corte anterior", _overwrite_requested
    ),
    ConfirmationRule(
        "cut_pauses_and_caption",
        "refazer um projeto que já existe, apagando o corte anterior",
        _overwrite_requested,
    ),
    ConfirmationRule("edit_project", "apagar um trecho ou uma sobreposição do projeto", _removes_content),
    ConfirmationRule("pronunciation", "apagar uma pronúncia cadastrada", _removes_pronunciation),
    ConfirmationRule(
        "clone_voice",
        "clonar uma voz: confirme que o dono da voz autorizou o uso dela",
        kind="voice_consent",
    ),
)

# Ferramentas que criam um projeto pelo nome e, se ele já existe, escrevem por cima: confirmam nesse caso.
PROJECT_NAME_ARGUMENT: dict[str, str] = {"new_from_template": "name", "build_explainer_video": "name"}
OVERWRITES_EXISTING_OUTPUT = (
    "synthesize_speech",
    "convert_voice",
    "isolate_vocals",
    "dub_render",
    "dub_stems",
)
# Ferramentas que gravam o projeto de dublagem (`.dub.json`) e, se ele já existe, o substituem inteiro, com as
# traduções que a pessoa revisou: confirmam só nesse caso.
REPLACES_EXISTING_DUB_PROJECT = frozenset({"dub_prepare"})


def dub_project_target(arguments: Mapping[str, Any]) -> str | None:
    """Onde `dub_prepare` grava o projeto: o `project` da chamada ou o padrão do servidor (`None` se a chamada não diz)."""
    project = arguments.get("project")
    if isinstance(project, str) and project:
        return project
    path, language = arguments.get("path"), arguments.get("target_language")
    if isinstance(path, str) and path and isinstance(language, str) and language:
        # Importado aqui para o gate continuar leve; é a mesma função do servidor MCP, que lê o `config` na hora.
        from ..pipeline.dubbing import default_project_path

        return str(default_project_path(Path(path), language))
    return None


def dub_overwrite_question(target: str, arguments: Mapping[str, Any]) -> str:
    language = arguments.get("target_language")
    for_language = f" para {language}" if isinstance(language, str) and language else ""
    return (
        f"Já existe uma dublagem deste vídeo{for_language} ({target}), e refazê-la apaga as traduções "
        "revisadas. Posso refazê-la por cima?"
    )


def consent_question(tool: str, arguments: Mapping[str, Any]) -> str:
    name = arguments.get("name") or "esta voz"
    return (
        f"Vou clonar a voz '{name}' a partir de uma gravação. A pessoa dona dessa voz autorizou o uso dela? "
        "Só continue se a autorização for explícita."
    )


def path_exists(path: str) -> bool:
    return Path(path).exists()


def no_project(name: str) -> bool:
    """O padrão sem disco: nenhum projeto existe (quem usa de verdade injeta `projects.project_path`)."""
    return False


@dataclass
class ToolGate:
    """Junta as três barreiras. `check` devolve `None` quando a chamada pode seguir, ou o texto que volta ao modelo.

    O disco (`exists`, `project_exists`) e a pessoa (`policy`) entram por injeção, para o teste não tocar nada real.
    """

    schemas: Mapping[str, Mapping[str, Any]]
    policy: ConfirmationPolicy = field(default_factory=DenyAll)
    known_paths: KnownPaths = field(default_factory=KnownPaths)
    exists: Callable[[str], bool] = path_exists
    project_exists: Callable[[str], bool] = no_project
    rules: tuple[ConfirmationRule, ...] = CONFIRMATION_RULES
    pending: PendingCall | None = None  # a chamada que a política adiou, à espera do sim da pessoa

    def check(self, tool: str, arguments: Mapping[str, Any]) -> str | None:
        schema = self.schemas.get(tool)
        if schema is not None:
            problems = validate_arguments(schema, arguments)
            if problems:
                return (
                    "erro: a chamada está errada: "
                    + "; ".join(problems)
                    + ". Corrija os argumentos e chame de novo."
                )
        absent = missing_paths(arguments, self.exists, self.known_paths)
        if absent:
            return ask_user_about_paths(absent)
        for request in self.confirmations(tool, arguments):
            try:
                approved = self.policy.confirm(request)
            except ConfirmationDeferred:
                self.pending = PendingCall(tool, dict(arguments), request.question)
                return (
                    f"Aguardando o sim do usuário: {request.question} "
                    "Faça essa pergunta a ele, curta, e espere a resposta; não chame a ferramenta de novo agora."
                )
            if not approved:
                return (
                    f"O usuário não autorizou: {request.question} "
                    "Não execute esta ação nem tente de outro jeito; diga o que ficou sem fazer e pergunte como seguir."
                )
        return None

    def confirmations(self, tool: str, arguments: Mapping[str, Any]) -> list[ConfirmationRequest]:
        """Tudo que precisa de um sim da pessoa antes desta chamada, na ordem em que será perguntado."""
        requests = []
        for rule in self.rules:
            if rule.tool == tool and rule.applies(arguments):
                question = (
                    consent_question(tool, arguments)
                    if rule.kind == "voice_consent"
                    else f"Posso {rule.reason}?"
                )
                requests.append(ConfirmationRequest(tool, arguments, question, rule.kind))
        name_argument = PROJECT_NAME_ARGUMENT.get(tool)
        if name_argument and self.project_exists(str(arguments.get(name_argument, ""))):
            question = f"O projeto '{arguments[name_argument]}' já existe. Posso sobrescrevê-lo?"
            requests.append(ConfirmationRequest(tool, arguments, question))
        if tool in OVERWRITES_EXISTING_OUTPUT:
            for name in OUTPUT_ARGUMENTS:
                target = arguments.get(name)
                if isinstance(target, str) and target and self.exists(target):
                    question = f"O arquivo '{target}' já existe. Posso sobrescrevê-lo?"
                    requests.append(ConfirmationRequest(tool, arguments, question))
        if tool in REPLACES_EXISTING_DUB_PROJECT:
            target = dub_project_target(arguments)
            if target and self.exists(target):
                requests.append(
                    ConfirmationRequest(tool, arguments, dub_overwrite_question(target, arguments))
                )
        return requests
