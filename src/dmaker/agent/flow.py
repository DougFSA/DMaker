"""O que a tela vê enquanto o modelo responde em fluxo: trechos agrupados e a etapa em que o agente está.

O cliente do modelo entrega um trecho por token (dezenas por segundo numa GPU), e cada evento do job fica guardado e é
reenviado a quem reconecta. Por isso os trechos são agrupados em poucos eventos por segundo. As etapas (`status`) são
o texto que substitui o "Pensando..." fixo: carregando o modelo, lendo o pedido, pensando, escrevendo ou chamando
uma ferramenta.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .transport import DeltaKind

# Os trechos do mesmo tipo juntam-se por este tempo; 0,25 s dá os 4 eventos por segundo que a tela precisa para
# parecer fluida, sem inundar o job.
DELTA_INTERVAL_S = 0.25

DELTA_EVENTS: dict[DeltaKind, str] = {"answer": "answer_delta", "thinking": "thinking_delta"}

STAGE_LABELS = {
    "loading_model": "Carregando o modelo",
    "reading": "Lendo o pedido",
    "thinking": "Pensando",
    "writing": "Escrevendo a resposta",
}
TOOL_STAGE = "tool"


def stage_label(stage: str, tool: str = "") -> str:
    """O texto da etapa para a tela; a chamada de ferramenta diz qual."""
    if stage == TOOL_STAGE:
        return f"Chamando a ferramenta {tool}" if tool else "Chamando uma ferramenta"
    return STAGE_LABELS.get(stage, stage)


class DeltaBatcher:
    """Junta trechos curtos em eventos maiores: o primeiro sai na hora, os seguintes a cada `interval` segundos.

    Trechos de tipos diferentes nunca se misturam: ao trocar de raciocínio para resposta, o que estava guardado sai
    antes. O que sobra no fim precisa de `flush()`; o relógio entra por parâmetro para o teste não esperar.
    """

    def __init__(
        self,
        emit: Callable[[DeltaKind, str], None],
        interval: float = DELTA_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._emit = emit
        self._interval = interval
        self._clock = clock
        self._kind: DeltaKind | None = None
        self._parts: list[str] = []
        self._last_flush: float | None = None  # None até o primeiro envio: ele não espera

    def add(self, kind: DeltaKind, text: str) -> None:
        if self._kind is not None and kind != self._kind:
            self.flush()
        self._kind = kind
        self._parts.append(text)
        if self._last_flush is None or self._clock() - self._last_flush >= self._interval:
            self.flush()

    def flush(self) -> None:
        if self._kind is not None and self._parts:
            self._emit(self._kind, "".join(self._parts))
        self._parts = []
        self._kind = None
        self._last_flush = self._clock()
