"""Nomes das transições aceitas e o que cada uma faz. Dados puros: quem monta o grafo é `filtergraph.transitions`.

Os 48 tipos do `xfade` do FFmpeg entram como estão; as de movimento (zoom de passagem, chicote, desfoque
deslizando, queima de filme e vazamento de luz) são montadas pelo próprio DMaker. O registro de construtores em
`filtergraph.transitions` e o catálogo daqui precisam listar os mesmos nomes (há teste para isso).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

XFADE_TYPES = {
    "fade",
    "fadeblack",
    "fadewhite",
    "dissolve",
    "wipeleft",
    "wiperight",
    "wipeup",
    "wipedown",
    "slideleft",
    "slideright",
    "slideup",
    "slidedown",
    "smoothleft",
    "smoothright",
    "smoothup",
    "smoothdown",
    "circleopen",
    "circleclose",
    "circlecrop",
    "rectcrop",
    "radial",
    "pixelize",
    "distance",
    "zoomin",
    "fadegrays",
    "squeezev",
    "squeezeh",
    "hlslice",
    "hrslice",
    "vuslice",
    "vdslice",
    "diagtl",
    "diagtr",
    "diagbl",
    "diagbr",
    "hblur",
    "wipetl",
    "wipetr",
    "wipebl",
    "wipebr",
    "coverleft",
    "coverright",
    "coverup",
    "coverdown",
    "revealleft",
    "revealright",
    "revealup",
    "revealdown",
}

# o que cada transição de movimento faz, em uma frase (guia, galeria da interface e mensagens)
MOTION_TRANSITIONS: dict[str, str] = {
    "crosszoom": (
        "Zoom de passagem: a imagem amplia e desfoca, e a próxima entra do mesmo zoom e assenta no enquadramento."
    ),
    "whippan": (
        "Chicote: o quadro corre para a esquerda com borrão de movimento e a próxima imagem para no lugar."
    ),
    "blurslide": (
        "Desfoque deslizando: a próxima imagem sobe empurrando a anterior, com as duas desfocadas no meio."
    ),
    "filmburn": (
        "Queima de filme: um clarão laranja e branco queima a imagem anterior e a próxima emerge dele."
    ),
    "lightleak": (
        "Vazamento de luz: uma faixa de luz colorida cruza o quadro e a troca acontece embaixo dela."
    ),
}

_DIRECTIONS = {"left": "esquerda", "right": "direita", "up": "cima", "down": "baixo"}
_CORNERS = {"tl": "do canto superior esquerdo", "tr": "do canto superior direito"}
_CORNERS |= {"bl": "do canto inferior esquerdo", "br": "do canto inferior direito"}

# descrição dos tipos do xfade que não seguem um padrão de nome (os com direção saem de `_directional`)
_XFADE_SUMMARIES = {
    "fade": "A imagem anterior se dissolve suavemente na próxima.",
    "fadeblack": "Escurece até o preto e a próxima imagem surge do preto.",
    "fadewhite": "Clareia até o branco e a próxima imagem surge do branco.",
    "dissolve": "Troca por grãos aleatórios; costuma parecer pixelado, prefira fade ou fadeblack.",
    "circleopen": "A próxima imagem abre de dentro para fora, num círculo.",
    "circleclose": "A imagem anterior fecha num círculo e revela a próxima.",
    "circlecrop": "Um círculo cresce a partir do centro e leva a próxima imagem junto.",
    "rectcrop": "Um retângulo cresce a partir do centro e leva a próxima imagem junto.",
    "radial": "Varredura em giro, como o ponteiro de um relógio.",
    "pixelize": "As imagens viram blocos grandes e a próxima surge dos blocos.",
    "distance": "Mistura pela diferença de cor entre as duas imagens.",
    "zoomin": "A próxima imagem surge ampliando-se de dentro da anterior.",
    "fadegrays": "As duas imagens passam por tons de cinza durante a troca.",
    "squeezev": "A imagem anterior é espremida na vertical e some, revelando a próxima.",
    "squeezeh": "A imagem anterior é espremida na horizontal e some, revelando a próxima.",
    "hlslice": "Fatias horizontais correm para a esquerda e trazem a próxima imagem.",
    "hrslice": "Fatias horizontais correm para a direita e trazem a próxima imagem.",
    "vuslice": "Fatias verticais sobem e trazem a próxima imagem.",
    "vdslice": "Fatias verticais descem e trazem a próxima imagem.",
    "hblur": "Mistura com desfoque horizontal.",
}


def _directional(name: str) -> str | None:
    for prefix, text in (
        ("wipe", "Uma cortina corre para {d} e revela a próxima imagem."),
        ("slide", "A próxima imagem empurra a anterior para {d}."),
        ("smooth", "Cortina de borda suave que corre para {d}."),
        ("cover", "A próxima imagem desliza por cima da anterior, que fica parada ({d})."),
        ("reveal", "A imagem anterior desliza para fora e revela a próxima, que fica parada ({d})."),
    ):
        direction = _DIRECTIONS.get(name.removeprefix(prefix)) if name.startswith(prefix) else None
        if direction:
            return text.format(d=direction)
    if name.startswith("wipe") and name[4:] in _CORNERS:
        return f"Cortina diagonal {_CORNERS[name[4:]]} que revela a próxima imagem."
    if name.startswith("diag") and name[4:] in _CORNERS:
        return f"Varredura diagonal {_CORNERS[name[4:]]}."
    return None


@dataclass(frozen=True)
class TransitionInfo:
    name: str
    kind: Literal["motion", "xfade"]
    summary: str


def catalog() -> list[TransitionInfo]:
    """Todas as transições (menos o corte seco): as de movimento primeiro, depois as do xfade em ordem alfabética."""
    motion = [TransitionInfo(name, "motion", summary) for name, summary in MOTION_TRANSITIONS.items()]
    xfade = [
        TransitionInfo(name, "xfade", _XFADE_SUMMARIES.get(name) or _directional(name) or "")
        for name in sorted(XFADE_TYPES)
    ]
    return motion + xfade


def all_transition_names() -> set[str]:
    """Os nomes que `Transition.type` aceita, fora o corte seco."""
    return XFADE_TYPES | set(MOTION_TRANSITIONS)
