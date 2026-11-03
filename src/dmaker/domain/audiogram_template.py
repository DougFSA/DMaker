"""Preparação do modelo "audiograma" (`templates/audiograma.json`): confere os parâmetros e deriva o que o JSON
do template não calcula sozinho (o trecho de fundo e onde o desenho se encaixa, conforme o estilo).

O modelo é o formato de divulgação de um corte de podcast, entrevista ou áudio de WhatsApp: a foto ou capa
num círculo no meio, a onda ou as barras animadas no ritmo da fala, o título no alto e a legenda automática
embaixo. Tudo aqui é puro: recebe dados, devolve dados.
"""

from __future__ import annotations

from typing import Any

from .explainer import background_segment

STYLES = ("circle", "bars", "wave")
# nomes de estilo que o pedido pode usar em português
STYLE_ALIASES = {"circulo": "circle", "barras": "bars", "onda": "wave"}
# desfoque da capa de fundo: a imagem é reduzida 10x, desfocada e ampliada de novo, o que borra como um
# desfoque grande a uma fração do custo (um gblur direto em 1080x1920 levaria minutos num áudio de 30 s)
BLURRED_COVER_FILTER = "scale=iw/10:ih/10,gblur=sigma=3,scale=iw*10:ih*10:flags=bicubic,eq=brightness=-0.12"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def cover_background(cover: str, duration: float) -> dict:
    """Trecho de fundo com a própria capa, cortada para preencher o quadro e desfocada."""
    return {
        "type": "image",
        "src": cover,
        "duration": duration,
        "motion": "none",
        "reframe": {"mode": "crop"},
        "color": {"extra": BLURRED_COVER_FILTER},
        "label": "fundo",
    }


def prepare_audiogram(params: dict[str, Any]) -> dict[str, Any]:
    """Preparador do template "audiograma": valida `estilo` e `duracao`, monta o trecho de fundo (`fundo`) e
    diz se o desenho vai em volta da foto (`em_volta`, o círculo) ou embaixo dela (`embaixo`, a onda e as
    barras)."""
    style = str(params.get("estilo") or "circle").lower()
    style = STYLE_ALIASES.get(style, style)
    if style not in STYLES:
        raise ValueError(f"`estilo` desconhecido: {params.get('estilo')!r} (use circle, bars ou wave)")
    duration = params.get("duracao")
    if not _is_number(duration) or duration <= 0:
        raise ValueError(
            "`duracao` é a duração do áudio em segundos, maior que zero (omitida, vale a do arquivo de áudio)"
        )
    background = str(params.get("fundo") or "escuro")
    if background.lower() == "capa":
        segment = cover_background(str(params["capa"]), float(duration))
    else:
        segment = background_segment(background, float(duration), "fundo")
    return {
        **params,
        "estilo": style,
        "duracao": float(duration),
        "fundo_segmento": segment,
        "em_volta": style == "circle",
        "embaixo": style != "circle",
    }
