"""O crossfade de som no corte entre dois clipes vizinhos (o J-cut e o L-cut do vídeo): quanto dura de verdade.

A imagem continua trocando no quadro exato do corte; o som cruza por `duration` segundos, metade antes do corte e
metade depois, e cada lado vem da sobra da fonte além do ponto de entrada (o clipe que entra, antes do corte) e do de
saída (o clipe que sai, depois do corte). Quando a fonte não tem sobra o bastante, o crossfade encurta para o que
houver. Tudo aqui é conta pura: quem olha para as fontes e monta o grafo está em `pipeline.audio_crossfade` e
`filtergraph.crossfade`.
"""

from __future__ import annotations

from dataclasses import dataclass

# Menos que isto de cada lado (5 ms) não é um crossfade, é arredondamento: o corte fica seco
MIN_HALF_SECONDS = 0.005
# A conta é feita em milissegundos: o mesmo corte dá sempre o mesmo valor, e a chave de cache não oscila
HALF_PRECISION = 3


@dataclass(frozen=True)
class CutSide:
    """Um dos dois clipes de um corte, como o crossfade precisa vê-lo.

    `audible` diz se o som dele entra no trecho (tem áudio, não está mudo nem a volume zero). `room` é quanto som a
    fonte tem do lado do corte, em segundos da linha do tempo: para o clipe que sai, o que sobra no arquivo depois do
    ponto de saída; para o que entra, o que existe no arquivo antes do ponto de entrada. `length` é a duração do
    clipe. `blocked` é o motivo de o crossfade não valer neste clipe (som isolado, som deslocado)."""

    audible: bool
    room: float
    length: float
    blocked: str | None = None


@dataclass(frozen=True)
class CutPlan:
    """O que sai da conta: `half` segundos de cada lado do corte (0 = corte seco) e a nota para o usuário quando o
    crossfade não saiu como pedido."""

    half: float
    note: str | None = None

    @property
    def width(self) -> float:
        """A duração total do cruzamento."""
        return 2.0 * self.half


def plan_cut(requested: float, leaving: CutSide, entering: CutSide, where: str) -> CutPlan:
    """Quanto dura o crossfade do corte entre o clipe que sai (`leaving`) e o que entra (`entering`). `where` abre a nota
    ("timeline[3]"). Cada lado pode dar no máximo a metade pedida, a sobra da fonte e a duração do próprio clipe."""
    for side, name in ((leaving, "anterior"), (entering, "seguinte")):
        if side.blocked:
            return CutPlan(0.0, f"{where}: o crossfade de som não vale no trecho {name}: {side.blocked}.")
        if not side.audible:
            return CutPlan(0.0, f"{where}: o trecho {name} está sem som ou mudo, não há o que cruzar.")
    wanted = requested / 2.0
    half = round(min(wanted, leaving.room, entering.room, leaving.length, entering.length), HALF_PRECISION)
    if half < MIN_HALF_SECONDS:
        return CutPlan(
            0.0,
            f"{where}: o crossfade de som de {requested:g} s não coube: a fonte não tem som além do corte "
            "(o trecho anterior acaba no fim do arquivo ou o seguinte começa no início dele).",
        )
    if half < wanted - 0.5 * 10**-HALF_PRECISION:
        return CutPlan(
            half,
            f"{where}: o crossfade de som de {requested:g} s encurtou para {2 * half:.2f} s, que é o som que a fonte "
            "tem além do corte.",
        )
    return CutPlan(half)
