"""A transcrição de uma conversa: o que a tela desenha, montado no servidor a partir dos mesmos eventos do turno.

O histórico do modelo (`AgentLoop.history`) serve para o modelo continuar; a transcrição serve para a pessoa reler.
Elas divergem de propósito: o aparo tira turnos antigos do que o modelo lê, mas a transcrição guarda tudo, e ela traz o
que o modelo nunca vê (o raciocínio, o aviso de aparo, a resposta interrompida). A tela desenha a transcrição salva e o
turno ao vivo com os mesmos componentes, então cada entrada tem a forma dos itens da conversa (`kind` e os campos).

Tudo aqui é puro: recebe eventos, devolve dados. Ler e gravar em disco é do repositório de conversas.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

# Tamanhos que cabem numa linha e num bloco de resultado da tela; o resultado inteiro de uma ferramenta pode ser longo.
DETAIL_LIMIT = 160
RESULT_LIMIT = 800

TOOL_RUNNING = "running"
TOOL_DONE = "done"
TOOL_ERROR = "error"
TOOL_BLOCKED = "blocked"
TOOL_INTERRUPTED = "interrupted"  # a ferramenta estava rodando quando o DMaker foi fechado

CONFIRMATION_PENDING = "pending"
CONFIRMATION_APPROVED = "approved"
CONFIRMATION_REFUSED = "refused"
CONFIRMATION_UNCONFIRMED = "unconfirmed"  # a pergunta ficou sem resposta: a pessoa não confirmou nada

RESTART_NOTICE = "Esta resposta não terminou porque o DMaker foi fechado no meio dela."
STOPPED_BEFORE_START_NOTICE = "Você parou a resposta antes de ela começar."
_OPEN_KINDS = frozenset(
    {"user", "kits", "thinking", "tool", "confirmation"}
)  # o turno acaba em answer ou notice


def utc_now() -> str:
    """O instante atual em ISO 8601 UTC, com milissegundos (ordena como texto, e a tela converte para o horário local)."""
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def first_line(text: str, limit: int = DETAIL_LIMIT) -> str:
    """A primeira linha útil de um texto, cortada para caber numa linha da conversa."""
    line = (text.splitlines() or [""])[0].strip()
    return line if len(line) <= limit else line[: limit - 1] + "…"


def short_result(text: str, limit: int = RESULT_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class TranscriptBuilder:
    """Acumula as entradas da transcrição conforme os eventos do turno chegam."""

    def __init__(self, entries: Sequence[Mapping[str, Any]] = (), clock: Callable[[], str] = utc_now) -> None:
        self.entries: list[dict[str, Any]] = [dict(entry) for entry in entries]
        self._clock = clock
        self._counter = max((self._number(entry.get("id")) for entry in self.entries), default=0)

    @staticmethod
    def _number(entry_id: object) -> int:
        digits = str(entry_id or "")[1:]
        return int(digits) if digits.isdigit() else 0

    def _add(self, kind: str, **fields: Any) -> dict[str, Any]:
        self._counter += 1
        entry = {"kind": kind, "id": f"e{self._counter}", **fields}
        self.entries.append(entry)
        return entry

    def snapshot(self) -> list[dict[str, Any]]:
        """Uma cópia das entradas, segura para serializar enquanto o turno continua escrevendo nelas."""
        return copy.deepcopy(self.entries)

    def add_user(self, text: str, attachments: Sequence[Mapping[str, Any]] = ()) -> None:
        """A mensagem da pessoa. Os anexos entram como fichas (só a referência, nunca a imagem nem o texto extraído)."""
        fields: dict[str, Any] = {"text": text, "at": self._clock()}
        if attachments:
            fields["attachments"] = [dict(item) for item in attachments]
        self._add("user", **fields)

    def add_notice(self, level: str, code: str, text: str) -> None:
        self._add("notice", level=level, code=code, text=text)

    def _last_open_tool(self, name: str) -> dict[str, Any] | None:
        for entry in reversed(self.entries):
            if entry["kind"] == "tool" and entry["name"] == name and entry["state"] == TOOL_RUNNING:
                return entry
        return None

    def apply(self, kind: str, data: Mapping[str, Any]) -> None:
        """Um evento do turno. Os que a tela só usa ao vivo (trechos, etapas, progresso) não entram na transcrição."""
        handler = self._HANDLERS.get(kind)
        if handler is not None:
            handler(self, data)

    def _on_triage(self, data: Mapping[str, Any]) -> None:
        self._add("kits", kits=list(data.get("kits", [])), method=str(data.get("method", "")))

    def _on_thinking(self, data: Mapping[str, Any]) -> None:
        if text := str(data.get("text") or "").strip():
            self._add("thinking", text=text)

    def _on_tool_call(self, data: Mapping[str, Any]) -> None:
        self._add(
            "tool",
            name=data["name"],
            arguments=dict(data.get("arguments") or {}),
            state=TOOL_RUNNING,
            detail="",
            result="",
        )

    def _on_tool_blocked(self, data: Mapping[str, Any]) -> None:
        if (tool := self._last_open_tool(data["name"])) is not None:
            tool["state"] = TOOL_BLOCKED
            tool["detail"] = first_line(str(data.get("reason") or ""))

    def _on_tool_result(self, data: Mapping[str, Any]) -> None:
        result = str(data.get("result") or "")
        tool = self._last_open_tool(data["name"])
        if (
            tool is None
        ):  # o resultado de uma chamada barrada chega depois do `tool_blocked`: ela já saiu de "running"
            tool = next(
                (e for e in reversed(self.entries) if e["kind"] == "tool" and e["name"] == data["name"]), None
            )
            if tool is None or tool["state"] != TOOL_BLOCKED:
                return
        tool["result"] = short_result(result)
        if tool["state"] != TOOL_BLOCKED:
            tool["state"] = TOOL_ERROR if result.startswith("erro:") else TOOL_DONE
            tool["detail"] = first_line(result)

    def _on_confirmation_request(self, data: Mapping[str, Any]) -> None:
        self._add(
            "confirmation",
            confirmation_id=data["id"],
            tool=data["tool"],
            question=data["question"],
            type=data.get("type", "action"),
            state=CONFIRMATION_PENDING,
        )

    def _on_confirmation_answered(self, data: Mapping[str, Any]) -> None:
        for entry in self.entries:
            if entry["kind"] == "confirmation" and entry["confirmation_id"] == data["id"]:
                entry["state"] = CONFIRMATION_APPROVED if data.get("approved") else CONFIRMATION_REFUSED

    def _on_answer(self, data: Mapping[str, Any]) -> None:
        text = str(data.get("text") or "")
        interrupted = bool(data.get("interrupted"))
        if interrupted and not text.strip():
            self.add_notice("info", "interrupted", STOPPED_BEFORE_START_NOTICE)
            return
        self._add("answer", text=text, interrupted=interrupted)

    def _on_history_trimmed(self, data: Mapping[str, Any]) -> None:
        self.add_notice("info", "history_trimmed", str(data.get("text") or ""))

    _HANDLERS: dict[str, Callable[[TranscriptBuilder, Mapping[str, Any]], None]] = {
        "triage": _on_triage,
        "thinking": _on_thinking,
        "tool_call": _on_tool_call,
        "tool_blocked": _on_tool_blocked,
        "tool_result": _on_tool_result,
        "confirmation_request": _on_confirmation_request,
        "confirmation_answered": _on_confirmation_answered,
        "answer": _on_answer,
        "history_trimmed": _on_history_trimmed,
    }

    def settle(self) -> bool:
        """Fecha o que ficou aberto quando o DMaker foi fechado no meio de um turno; devolve se mudou algo.

        Uma confirmação sem resposta vira "não confirmada" (o botão morreu junto com o processo), uma ferramenta que
        estava rodando vira "interrompida" e o turno incompleto ganha um aviso. Só se aplica a uma conversa lida do
        disco: numa conversa viva, esses estados são verdadeiros.
        """
        changed = False
        for entry in self.entries:
            if entry["kind"] == "confirmation" and entry["state"] == CONFIRMATION_PENDING:
                entry["state"] = CONFIRMATION_UNCONFIRMED
                changed = True
            elif entry["kind"] == "tool" and entry["state"] == TOOL_RUNNING:
                entry["state"] = TOOL_INTERRUPTED
                entry["detail"] = "Interrompida porque o DMaker foi fechado."
                changed = True
        if self.entries and self.entries[-1]["kind"] in _OPEN_KINDS:
            self.add_notice("warning", "unfinished", RESTART_NOTICE)
            changed = True
        return changed
