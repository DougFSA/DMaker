"""Tradução das falas de uma dublagem por um modelo local do Ollama.

`Translator` é o protocolo que o pipeline usa; `OllamaTranslator` o implementa conversando com `OllamaChat`
(injetável, para testar sem um Ollama no ar). O modelo recebe o roteiro inteiro em JSON, com ids, para
traduzir cada fala com o contexto das vizinhas, e responde em JSON com os mesmos ids; o que vier fora disso
é recusado e o lote é pedido de novo.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .. import config
from ..agent.llm import OllamaChat, Reply, ollama_url

LANGUAGE_NAMES = {
    "pt": "Brazilian Portuguese",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
}
BATCH_LINES = 10  # falas por pedido: lotes maiores fazem o modelo perder o fio e esquecer ids na CPU
CONTEXT_LINES = (
    40  # roteiros maiores que isto mandam só uma janela em volta do lote (cabe no contexto do modelo)
)
MAX_ATTEMPTS = 3
TRANSLATION_TEMPERATURE = 0.2  # baixa: tradução pede fidelidade, não criatividade
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class TranslationError(RuntimeError):
    """Falha ao traduzir (Ollama fora do ar, modelo ausente ou respostas inválidas); a mensagem vai ao usuário."""


@dataclass(frozen=True)
class Line:
    """Uma fala a traduzir. `known` já traduzida (travada): entra só como contexto e volta como está."""

    id: str
    text: str
    seconds: float
    known: str | None = None


class Translator(Protocol):
    model: str

    def translate(
        self,
        lines: Sequence[Line],
        source: str,
        target: str,
        glossary: Sequence[str] = (),
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[str]:
        """Uma tradução por fala, na mesma ordem de `lines`."""


class TranslationChat(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> Reply: ...

    def is_alive(self) -> bool: ...

    def has_model(self) -> bool: ...


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code.split("-")[0].lower(), code)


def system_prompt(source: str, target: str, glossary: Sequence[str]) -> str:
    """Instruções do tradutor: fala natural, tamanho parecido com o original, termos fixos e formato da resposta."""
    rules = [
        f"You are a professional dubbing translator. Translate spoken dialogue from {language_name(source)} "
        f"to {language_name(target)}; a voice actor will read your lines aloud over the original video.",
        "Write natural, idiomatic spoken language, not literal text. Keep the meaning, tone, names and numbers.",
        "Each line must take about as long to say as the original: every line has its original duration in "
        "seconds. Prefer the shorter wording when in doubt, and never pad.",
        "Do not add, drop or explain anything. Do not merge or split lines: one translation per id.",
        "Do not use dashes as punctuation; use commas or periods.",
        "Lines that carry a translation field are already final: use them only as context.",
    ]
    if glossary:
        terms = ", ".join(f'"{term}"' for term in glossary)
        rules.append(f"Keep these terms exactly as written, never translate or inflect them: {terms}.")
    rules.append(
        'Reply with JSON only, no commentary: {"translations": [{"id": "...", "text": "..."}]} containing '
        "exactly the ids listed in translate_ids."
    )
    return "\n".join(f"- {rule}" if index else rule for index, rule in enumerate(rules))


def _script_entry(line: Line, done: dict[str, str]) -> dict[str, Any]:
    entry: dict[str, Any] = {"id": line.id, "seconds": round(line.seconds, 1), "text": line.text}
    translation = line.known if line.known is not None else done.get(line.id)
    if translation is not None:
        entry["translation"] = translation
    return entry


def build_request(lines: Sequence[Line], batch: Sequence[Line], done: dict[str, str]) -> str:
    """Pedido de um lote: o roteiro (inteiro, ou a janela em volta do lote se for longo) e os ids a traduzir."""
    first = lines.index(batch[0])
    last = lines.index(batch[-1])
    if len(lines) > CONTEXT_LINES:
        margin = (CONTEXT_LINES - len(batch)) // 2
        window = lines[max(0, first - margin) : last + 1 + margin]
    else:
        window = lines
    payload = {
        "script": [_script_entry(line, done) for line in window],
        "translate_ids": [line.id for line in batch],
    }
    return json.dumps(payload, ensure_ascii=False)


def parse_translations(content: str, expected_ids: Sequence[str]) -> dict[str, str]:
    """Lê a resposta do modelo e confere que tem exatamente os ids pedidos, cada um com texto; senão, ValueError."""
    text = _FENCE.sub("", content.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("a resposta não é um JSON")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON inválido ({exc.msg})") from exc
    items = data.get("translations") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError('faltou a lista "translations"')
    found: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict) or "id" not in item or not isinstance(item.get("text"), str):
            raise ValueError('cada item precisa de "id" e "text"')
        found[str(item["id"])] = " ".join(item["text"].split())
    missing = [i for i in expected_ids if i not in found]
    extra = [i for i in found if i not in expected_ids]
    if missing or extra or len(items) != len(expected_ids):
        raise ValueError(
            f"ids errados (pedidos {len(expected_ids)}, recebidos {len(items)}; faltam {missing}, sobram {extra})"
        )
    empty = [i for i in expected_ids if not found[i]]
    if empty:
        raise ValueError(f"tradução vazia para {empty}")
    return found


def default_chat(model: str) -> OllamaChat:
    """Cliente do Ollama para traduzir: temperatura baixa, resposta em JSON e raciocínio curto nos modelos que o têm."""
    return OllamaChat(
        model=model,
        base_url=ollama_url(),
        temperature=TRANSLATION_TEMPERATURE,
        response_format="json",
        think="low" if "gpt-oss" in model else None,
    )


class OllamaTranslator:
    def __init__(
        self,
        model: str | None = None,
        chat: TranslationChat | None = None,
        batch_lines: int = BATCH_LINES,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self.model = model or config.TRANSLATE_MODEL
        self.chat = chat or default_chat(self.model)
        self.batch_lines = batch_lines
        self.max_attempts = max_attempts

    def check(self) -> None:
        """Falha cedo, em português, se o Ollama não responde ou não tem o modelo (antes de gastar minutos)."""
        if not self.chat.is_alive():
            url = getattr(self.chat, "base_url", ollama_url())
            raise TranslationError(
                f"Não consegui falar com o Ollama em {url}. Abra o aplicativo do Ollama (ou rode `ollama serve`) "
                "e tente de novo."
            )
        if not self.chat.has_model():
            raise TranslationError(
                f"O modelo {self.model} não está instalado no Ollama. Rode `ollama pull {self.model}` ou escolha "
                "outro em DMAKER_TRANSLATE_MODEL."
            )

    def translate(
        self,
        lines: Sequence[Line],
        source: str,
        target: str,
        glossary: Sequence[str] = (),
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[str]:
        pending = [line for line in lines if line.known is None and line.text.strip()]
        done: dict[str, str] = {}
        if pending:
            self.check()
        system = system_prompt(source, target, glossary)
        for at in range(0, len(pending), self.batch_lines):
            if on_progress:
                on_progress(at, len(pending))
            batch = pending[at : at + self.batch_lines]
            done.update(self._translate_batch(system, list(lines), batch, done))
        if on_progress and pending:
            on_progress(len(pending), len(pending))
        return [line.known if line.known is not None else done.get(line.id, "") for line in lines]

    def _translate_batch(
        self, system: str, lines: list[Line], batch: list[Line], done: dict[str, str]
    ) -> dict[str, str]:
        ids = [line.id for line in batch]
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": build_request(lines, batch, done)},
        ]
        problem = ""
        for _ in range(self.max_attempts):
            try:
                reply = self.chat.chat(messages, [])
            except OSError as exc:
                raise TranslationError(
                    f"A conversa com o Ollama falhou ({exc}). Confira se ele está aberto e se o modelo "
                    f"{self.model} carregou."
                ) from exc
            try:
                return parse_translations(reply.content, ids)
            except ValueError as exc:
                problem = str(exc)
                messages += [
                    {"role": "assistant", "content": reply.content},
                    {
                        "role": "user",
                        "content": f"Invalid answer: {problem}. Reply again with JSON only, with exactly these "
                        f"ids: {json.dumps(ids)}.",
                    },
                ]
        raise TranslationError(
            f"O modelo {self.model} não devolveu uma tradução válida para as falas {', '.join(ids)} depois de "
            f"{self.max_attempts} tentativas ({problem})."
        )
