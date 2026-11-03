"""Audiograma: contas puras sobre a spec (que áudio a animação segue e que tamanho o desenho tem).

Nada aqui executa ffmpeg nem toca o disco: o grafo que desenha vive em `filtergraph/audiogram.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .spec import AudiogramOverlay, ClipSegment, Project, VideoOverlay

Follow = Literal["voice", "mix"]

# Proporção largura/altura do desenho de cada estilo quando a spec não dá `height`: a onda é uma faixa baixa,
# as barras precisam de mais altura para as mais altas não baterem no teto, e o círculo é um quadrado
STYLE_ASPECT: dict[str, float] = {"wave": 5.0, "bars": 4.0, "circle": 1.0}


def project_has_voice(project: Project, clip_has_audio: Sequence[bool] | None = None) -> bool:
    """O projeto tem alguma voz no barramento de voz (clipes, PiP, faixas externas, narração ou voiceover)?

    `clip_has_audio` diz, por trecho da linha do tempo, se a fonte tem áudio; sem ele, todo clipe conta como
    tendo. É a pergunta que decide o `follow: "auto"`: com voz, a animação segue a voz; sem ela (só música),
    segue a mistura."""
    audio = project.audio
    if any(clip.volume > 0 for clip in audio.voiceover) or any(n.volume > 0 for n in audio.narration):
        return True
    if any(track.volume > 0 for track in audio.tracks):
        return True
    if any(isinstance(ov, VideoOverlay) and ov.volume > 0 for ov in project.overlays):
        return True
    if audio.mute_clips:
        return False
    for index, segment in enumerate(project.timeline):
        if not isinstance(segment, ClipSegment) or segment.mute or segment.volume <= 0:
            continue
        if clip_has_audio is None or index >= len(clip_has_audio) or clip_has_audio[index]:
            return True
    return False


def resolve_follow(follow: str, has_voice: bool) -> Follow:
    """`auto` vira `voice` quando há voz e `mix` quando não há; `voice` e `mix` ficam como pedidos."""
    if follow == "auto":
        return "voice" if has_voice else "mix"
    return "voice" if follow == "voice" else "mix"


# Barras do espectro: 24 faixas de frequência espelhadas, as graves no meio (barras) ou no topo (círculo).
# Vinte e quatro faixas sobre 0 a 2 kHz dão ~83 Hz por barra: largas o bastante para a voz não piscar entre
# harmônicos vizinhos e estreitas o bastante para a fala preencher o desenho todo.
BARS_PER_HALF = 24
BAR_COUNT = 2 * BARS_PER_HALF
GAP_RATIO = 0.3  # fração do passo de cada barra que é vão entre ela e a vizinha
MIN_BAR_PX = 2  # altura da barra em repouso (um traço), para o desenho não sumir no silêncio
RING_MARGIN_PX = 1  # folga entre a ponta da barra mais alta e a borda do quadrado do círculo


@dataclass(frozen=True)
class BarsLayout:
    """Geometria do estilo `bars`: `pitch` px por barra (barra + vão), `gap` px de vão, e a largura real do
    desenho (um múltiplo de BAR_COUNT, para cada barra ter um número inteiro de colunas)."""

    pitch: int
    gap: int
    height: int

    @property
    def width(self) -> int:
        return self.pitch * BAR_COUNT

    @property
    def half_height(self) -> float:
        return self.height / 2

    @property
    def rest_fraction(self) -> float:
        """Altura de repouso como fração da meia altura (o que o `lut` das alturas usa como piso)."""
        return min(MIN_BAR_PX / self.half_height, 1.0)


def bars_layout(width: int, height: int) -> BarsLayout:
    pitch = max(width // BAR_COUNT, 2)
    return BarsLayout(pitch=pitch, gap=max(1, round(pitch * GAP_RATIO)), height=height)


@dataclass(frozen=True)
class RingLayout:
    """Geometria do estilo `circle`: quadrado de lado `size`, barras entre o raio interno e o externo."""

    size: int
    inner_radius: float  # fração do raio externo

    @property
    def outer(self) -> float:
        return self.size / 2 - RING_MARGIN_PX

    @property
    def inner(self) -> float:
        return self.outer * self.inner_radius

    @property
    def span(self) -> float:
        """Comprimento da maior barra, em px."""
        return self.outer - self.inner

    @property
    def rest_fraction(self) -> float:
        return min(MIN_BAR_PX / self.span, 1.0)


def _even(value: float) -> int:
    """O par mais próximo (o ffmpeg quer dimensões pares); arredonda em vez de truncar, porque a fração do quadro
    `0.7222` de uma região vira 779,97 px e o desenho não deve perder dois pixels por isso."""
    return max(2, round(value / 2) * 2)


def audiogram_size(overlay: AudiogramOverlay, frame_width: int, frame_height: int) -> tuple[int, int]:
    """Largura e altura (px, pares) do desenho. O círculo é um quadrado do menor lado da caixa pedida."""
    width = _even(frame_width * overlay.width)
    if overlay.height is not None:
        height = _even(frame_height * overlay.height)
    else:
        height = _even(width / STYLE_ASPECT[overlay.style])
    if overlay.style == "circle":
        side = min(width, height) if overlay.height is not None else width
        return side, side
    return width, height
