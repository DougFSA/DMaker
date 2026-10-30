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
from collections.abc import Callable, Iterable, Mapping, Sequence
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


def flag_is_on(arguments: Mapping[str, Any], flag: str) -> bool:
    """A flag de sobrescrita ligada de fato (`true`): um texto ou um número que o modelo mandou não conta."""
    return arguments.get(flag) is True


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
    ConfirmationRule("edit_project", "apagar um trecho ou uma sobreposição do projeto", _removes_content),
    ConfirmationRule("pronunciation", "apagar uma pronúncia cadastrada", _removes_pronunciation),
    ConfirmationRule(
        "clone_voice",
        "clonar uma voz: confirme que o dono da voz autorizou o uso dela",
        kind="voice_consent",
    ),
)

# Ferramentas que refazem um projeto pelo nome e, com a flag de sobrescrita ligada, apagam o corte anterior:
# ferramenta -> (argumento do nome, argumento da flag). Sem a flag o próprio servidor recusa o nome que já existe
# (`AutoCutService.validate`); com ela, `overwrite=true` num nome livre é inofensivo. A pergunta exige então as duas
# coisas, a flag ligada e o projeto de fato no disco: uma pergunta à toa ensina a pessoa a dizer sim sem ler.
REDOES_EXISTING_PROJECT: dict[str, tuple[str, str]] = {
    "autocut": ("name", "overwrite"),
    "cut_pauses_and_caption": ("name", "overwrite"),
}
# Ferramentas que criam um projeto pelo nome e, se ele já existe, escrevem por cima: confirmam nesse caso.
PROJECT_NAME_ARGUMENT: dict[str, str] = {"new_from_template": "name", "build_explainer_video": "name"}
# Ferramentas que gravam um arquivo e, se ele já existe, o substituem: confirmam nesse caso. O destino é o `out` ou
# o `out_dir` da chamada ou, sem eles, o padrão de cada ferramenta (`DEFAULT_OUTPUTS`, abaixo).
OVERWRITES_EXISTING_OUTPUT = (
    "synthesize_speech",
    "fix_speech",
    "convert_voice",
    "isolate_vocals",
    "dub_render",
    "dub_stems",
)
# Ferramentas que gravam o projeto de dublagem (`.dub.json`) e, se ele já existe, o substituem inteiro, com as
# traduções que a pessoa revisou: confirmam só nesse caso.
REPLACES_EXISTING_DUB_PROJECT = frozenset({"dub_prepare"})


# ---------- destino padrão ----------
#
# Sem `out`, a ferramenta grava num lugar que ela mesma escolhe. Cada função abaixo devolve esses arquivos chamando
# as funções que o servidor MCP usa (importadas aqui dentro para o gate continuar leve, e lendo o `config` na hora),
# então nenhuma regra de nome é copiada: se o servidor mudar a pasta ou o nome, a pergunta acompanha. Ficam de fora
# `dub_render` e `dub_stems`, cujo destino sai do conteúdo do `.dub.json` (o vídeo e o idioma), que o gate não lê.


def _float_or_none(value: Any) -> float | None:
    """Um tempo em segundos como o servidor o recebe: o número do modelo chega como `float` (o `5` vira `5.0`)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"tempo inválido: {value!r}")
    return float(value)


def _text_argument(arguments: Mapping[str, Any], name: str) -> str | None:
    value = arguments.get(name)
    return value if isinstance(value, str) and value.strip() else None


def _narration_outputs(arguments: Mapping[str, Any]) -> list[str]:
    text = _text_argument(arguments, "text")
    if text is None:
        return []
    from ..pipeline.voices import default_narration_path

    return [str(default_narration_path(text))]


def _suffix_candidates(source: Path) -> list[str]:
    """As extensões que o arquivo corrigido pode ter: depende de o original ter imagem, que só o `probe` do servidor
    sabe, então vale cada resposta possível (quase sempre uma só existe no disco)."""
    from ..filtergraph.speech_edit import corrected_suffix

    return list(dict.fromkeys(corrected_suffix(source.suffix, has_video) for has_video in (True, False)))


def _speech_fix_outputs(arguments: Mapping[str, Any]) -> list[str]:
    path = _text_argument(arguments, "path")
    if path is None:
        return []
    from ..pipeline.speech_fix import default_output_path

    source = Path(path)
    return [str(default_output_path(source, suffix)) for suffix in _suffix_candidates(source)]


def _voice_conversion_outputs(arguments: Mapping[str, Any]) -> list[str]:
    path, voice = _text_argument(arguments, "path"), _text_argument(arguments, "voice")
    if path is None or voice is None:
        return []
    from ..pipeline.voice_conversion import ConversionRequest, default_output_path

    try:
        request = ConversionRequest(
            Path(path), voice, _float_or_none(arguments.get("start")), _float_or_none(arguments.get("end"))
        )
    except (TypeError, ValueError):
        return []  # pedido inválido: a ferramenta o recusa sozinha, antes de gravar
    return [str(default_output_path(request, suffix)) for suffix in _suffix_candidates(request.src)]


def _isolation_outputs(arguments: Mapping[str, Any]) -> list[str]:
    path = _text_argument(arguments, "path")
    if path is None:
        return []
    from ..pipeline.isolation import DEFAULT_EXPORT_FORMAT, EXPORT_ROLES, default_export_dir, export_name

    try:
        start, end = _float_or_none(arguments.get("start")), _float_or_none(arguments.get("end"))
    except TypeError:
        return []
    audio_format = str(arguments.get("format") or DEFAULT_EXPORT_FORMAT)
    folder = default_export_dir()
    return [str(folder / export_name(Path(path), role, audio_format, start, end)) for role, _ in EXPORT_ROLES]


# Ferramenta -> os arquivos que ela grava quando a chamada não traz o `out` nem o `out_dir`.
DEFAULT_OUTPUTS: dict[str, Callable[[Mapping[str, Any]], list[str]]] = {
    "synthesize_speech": _narration_outputs,
    "fix_speech": _speech_fix_outputs,
    "convert_voice": _voice_conversion_outputs,
    "isolate_vocals": _isolation_outputs,
}


def output_targets(tool: str, arguments: Mapping[str, Any]) -> list[str]:
    """Onde a ferramenta grava: o `out` ou o `out_dir` da chamada ou, sem eles, o destino padrão dela."""
    given = [value for name in OUTPUT_ARGUMENTS if isinstance(value := arguments.get(name), str) and value]
    if given:
        return given
    default_outputs = DEFAULT_OUTPUTS.get(tool)
    return default_outputs(arguments) if default_outputs else []


def overwrite_question(existing: Sequence[str]) -> str:
    if len(existing) == 1:
        return f"O arquivo '{existing[0]}' já existe. Posso sobrescrevê-lo?"
    listed = ", ".join(f"'{path}'" for path in existing)
    return f"Os arquivos {listed} já existem. Posso sobrescrevê-los?"


def redo_project_question(name: str) -> str:
    return f'Posso refazer o projeto "{name}", apagando o corte anterior?'


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


@dataclass
class ToolGate:
    """Junta as três barreiras. `check` devolve `None` quando a chamada pode seguir, ou o texto que volta ao modelo.

    O disco (`exists`, `project_exists`) e a pessoa (`policy`) entram por injeção, para o teste não tocar nada real.
    Sem `project_exists` o gate não sabe quais projetos existem: a pergunta de refazer um corte então sai sempre.
    """

    schemas: Mapping[str, Mapping[str, Any]]
    policy: ConfirmationPolicy = field(default_factory=DenyAll)
    known_paths: KnownPaths = field(default_factory=KnownPaths)
    exists: Callable[[str], bool] = path_exists
    project_exists: Callable[[str], bool] | None = None
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

    def project_may_exist(self, name: str) -> bool:
        """Se o projeto existe; sem `project_exists` não há como saber, e supor que sim é o lado seguro."""
        return self.project_exists is None or self.project_exists(name)

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
        redo = REDOES_EXISTING_PROJECT.get(tool)
        if redo:
            redo_name, redo_flag = redo
            project = arguments.get(redo_name)
            if (
                flag_is_on(arguments, redo_flag)
                and isinstance(project, str)
                and project
                and self.project_may_exist(project)
            ):
                requests.append(ConfirmationRequest(tool, arguments, redo_project_question(project)))
        name_argument = PROJECT_NAME_ARGUMENT.get(tool)
        if (
            name_argument
            and self.project_exists is not None
            and self.project_exists(str(arguments.get(name_argument, "")))
        ):
            question = f"O projeto '{arguments[name_argument]}' já existe. Posso sobrescrevê-lo?"
            requests.append(ConfirmationRequest(tool, arguments, question))
        if tool in OVERWRITES_EXISTING_OUTPUT:
            existing = [target for target in output_targets(tool, arguments) if self.exists(target)]
            if existing:
                requests.append(ConfirmationRequest(tool, arguments, overwrite_question(existing)))
        if tool in REPLACES_EXISTING_DUB_PROJECT:
            target = dub_project_target(arguments)
            if target and self.exists(target):
                requests.append(
                    ConfirmationRequest(tool, arguments, dub_overwrite_question(target, arguments))
                )
        return requests
