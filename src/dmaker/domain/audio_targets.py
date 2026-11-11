"""O item de áudio que uma operação de edição de onda mexe, e a conta entre o tempo da linha do tempo e o tempo do
item. Puro: quem olha para as fontes e calcula as janelas é `pipeline.audio_targets`.

O usuário (ou o agente, ou a interface) fala em tempo da linha do tempo final, o mesmo de `start` e `end` dos itens da
vista. Os efeitos de áudio falam em tempo do item (segundos do sinal que entra neles). Cada alvo tem uma ou mais
janelas que ligam um ao outro: um clipe é uma janela só (com a velocidade como escala); uma faixa externa tem uma
janela por clipe em que ela soa; a música tem uma por janela de `spans`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .edits import EditError

TargetKind = Literal["clip", "pip", "voiceover", "narration", "music", "track", "master"]

# o instante pedido pode cair 1 ms fora de uma janela (os cortes são gravados em milissegundos)
TOLERANCE = 0.001
# menos que isto não é um trecho de som, é arredondamento
MIN_INTERVAL = 0.001

# onde cada alvo se escreve na spec: o caminho que `edit_project` usa em `target`
TARGET_FORMS = "timeline.N, overlays.N, audio.voiceover.N, audio.narration.N, audio.tracks.N, audio.music ou audio.master"
_INDEXED = {
    "timeline": "clip",
    "overlays": "pip",
    "audio.voiceover": "voiceover",
    "audio.narration": "narration",
    "audio.tracks": "track",
}
_SINGLE = {"audio.music": "music", "audio.master": "master"}

# os alvos presos à imagem ou à edição: a duração do item não pode mudar. Voz gravada e música são livres.
PINNED_KINDS = frozenset({"clip", "pip", "narration", "track", "master"})
KIND_NAMES = {
    "clip": "o som do clipe",
    "pip": "o som do PiP",
    "voiceover": "a voz gravada",
    "narration": "a narração",
    "music": "a música",
    "track": "a faixa externa",
    "master": "a mistura inteira",
}


def parse_target(target: object) -> tuple[TargetKind, int | None]:
    """O tipo e a posição de um alvo escrito como o caminho dele na spec (`timeline.2`, `audio.voiceover.0`,
    `audio.music`...). Qualquer outra coisa é erro que lista as formas aceitas."""
    if isinstance(target, str):
        if target in _SINGLE:
            return _SINGLE[target], None  # type: ignore[return-value]
        prefix, _, raw = target.rpartition(".")
        if prefix in _INDEXED and raw.isdigit():
            return _INDEXED[prefix], int(raw)  # type: ignore[return-value]
    raise EditError(f"alvo de áudio inválido: {target!r}. Use {TARGET_FORMS}")


@dataclass(frozen=True)
class Window:
    """Um pedaço do item que soa na linha do tempo: de `start` a `end` (segundos da linha do tempo), o item corre a
    partir de `item_in` (segundos do item) e anda `scale` segundos de item por segundo de linha do tempo (a
    velocidade do clipe)."""

    start: float
    end: float
    item_in: float = 0.0
    scale: float = 1.0

    def covers(self, instant: float) -> bool:
        return self.start - TOLERANCE <= instant <= self.end + TOLERANCE

    def item_time(self, instant: float) -> float:
        return self.item_in + (instant - self.start) * self.scale


@dataclass(frozen=True)
class AudioTarget:
    """Um item de áudio da spec: o caminho dele (`path`), o tipo, um nome para as mensagens e as janelas que ligam
    o tempo da linha do tempo ao tempo dele. `length` é a duração do item em segundos de item, quando se sabe."""

    path: str
    kind: TargetKind
    index: int | None
    label: str
    windows: tuple[Window, ...]
    length: float | None = None
    # por que o item não aceita operação por intervalo (uma fonte em várias partes é processada parte a parte, e o
    # tempo do item recomeça em cada uma); a operação que só mexe no item inteiro segue valendo
    blocker: str | None = None

    @property
    def pinned(self) -> bool:
        """Se a duração do item é presa (à imagem ou à edição): então um corte completa o fim com silêncio."""
        return self.kind in PINNED_KINDS

    @property
    def name(self) -> str:
        return KIND_NAMES[self.kind]

    def where(self) -> str:
        """Onde o item soa, para a mensagem de recusa: `de 2 a 9 s`."""
        first, last = self.windows[0], self.windows[-1]
        return f"de {first.start:g} a {last.end:g} s"

    def require_intervals(self) -> None:
        """Recusa, com o motivo, a operação por intervalo num item que não a aceita."""
        if self.blocker:
            raise EditError(f"{self.path}: {self.blocker}")

    def item_time(self, instant: float) -> float:
        """O instante da linha do tempo como tempo do item. Fora de todas as janelas é erro que diz onde o item soa."""
        self.require_intervals()
        for window in self.windows:
            if window.covers(instant):
                return max(window.item_time(instant), 0.0)
        raise EditError(
            f"o instante {instant:g} s está fora de {self.name} {self.path}, que soa {self.where()}"
        )

    def item_intervals(self, start: float, end: float) -> list[tuple[float, float]]:
        """O intervalo `[start, end)` da linha do tempo como intervalos do item: um por janela que ele pega, juntando
        os que se encostam. Erro se nenhum pedaço dele cai onde o item soa."""
        self.require_intervals()
        if end - start < MIN_INTERVAL:
            raise EditError(f"o intervalo precisa ter ao menos 1 ms (de {start:g} a {end:g} s)")
        pieces: list[tuple[float, float]] = []
        for window in self.windows:
            low, high = max(start, window.start), min(end, window.end)
            if high - low < MIN_INTERVAL:
                continue
            first, last = window.item_time(low), window.item_time(high)
            if pieces and abs(pieces[-1][1] - first) <= TOLERANCE:
                pieces[-1] = (pieces[-1][0], last)
            else:
                pieces.append((first, last))
        if not pieces:
            raise EditError(
                f"o intervalo de {start:g} a {end:g} s não pega {self.name} {self.path}, que soa {self.where()}"
            )
        return pieces

    def single_interval(self, start: float, end: float) -> tuple[float, float]:
        """Como `item_intervals`, para a operação que só vale num intervalo contínuo do item."""
        pieces = self.item_intervals(start, end)
        if len(pieces) > 1:
            raise EditError(
                f"o intervalo de {start:g} a {end:g} s passa por {len(pieces)} trechos separados de {self.name}; "
                "faça a operação em cada trecho"
            )
        return pieces[0]
