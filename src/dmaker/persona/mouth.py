"""As formas de boca do personagem ilustrado: os 15 visemas agrupados em 9 formas (função pura).

O 2D não precisa de 15 bocas: visemas que o olho não distingue num desenho dividem a mesma forma. A tabela dos
parâmetros de cada forma (abertura, largura, dentes) mora na página (`assets/html/persona/2d/index.html`); aqui só
fica o agrupamento, que o teste confere contra o conjunto completo de visemas.
"""

from __future__ import annotations

from collections.abc import Sequence

from .visemes import VISEMES, VisemeSpan

MOUTH_SHAPES = ("rest", "closed", "fv", "mid", "teeth", "open", "smile", "round", "pucker")

# `sil` é a boca em repouso (fechada, com o sorriso da expressão); `PP` aperta os lábios (b, p, m); `FF` apoia os
# dentes de cima no lábio de baixo; consoantes de língua (d, t, n, l, r, k, g, th) abrem pouco; `SS` e `CH` mostram
# os dentes; as vogais abrem (a), esticam (e, i), arredondam (o) e projetam (u).
VISEME_TO_MOUTH = {
    "sil": "rest",
    "PP": "closed",
    "FF": "fv",
    "TH": "mid",
    "DD": "mid",
    "kk": "mid",
    "nn": "mid",
    "RR": "mid",
    "CH": "teeth",
    "SS": "teeth",
    "aa": "open",
    "E": "smile",
    "I": "smile",
    "O": "round",
    "U": "pucker",
}
assert set(VISEME_TO_MOUTH) == set(VISEMES)


def mouth_timeline(visemes: Sequence[VisemeSpan]) -> list[tuple[float, float, str]]:
    """A linha do tempo de formas de boca `(início, fim, forma)`: os visemas trocados pela forma e os vizinhos que
    caíram na mesma forma fundidos (a página lê menos intervalos)."""
    timeline: list[tuple[float, float, str]] = []
    for span in visemes:
        shape = VISEME_TO_MOUTH[span.viseme]
        if timeline and timeline[-1][2] == shape:
            timeline[-1] = (timeline[-1][0], span.end, shape)
        else:
            timeline.append((span.start, span.end, shape))
    return timeline
