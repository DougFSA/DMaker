"""Preparação do modelo "explicativo" (`templates/explicativo.json`): confere a lista de assuntos e deriva
o que o JSON do template não calcula sozinho (duração de cada assunto, tom do fundo, o trecho de fundo).

Cada assunto vira um trecho de fundo na linha do tempo e, se tiver imagem, uma sobreposição na região
"topo". A gravação do apresentador é uma sobreposição só, contínua: por isso os assuntos precisam ser
contíguos e a troca de fundo nunca corta a fala. Tudo aqui é puro: recebe dados, devolve dados.
"""

from __future__ import annotations

import re
from typing import Any

# nomes de fundo que o pedido pode usar no lugar de um hex: (cor, tom). Tom é o do fundo, que decide a
# cor de texto sobre ele (claro pede texto escuro).
NAMED_BACKGROUNDS: dict[str, tuple[str, str]] = {
    "escuro": ("#0F172A", "dark"),
    "claro": ("#F8FAFC", "light"),
    "bege": ("#F1E8D8", "light"),
}
# quando o assunto não diz o fundo, alterna: a troca de cor é o que marca a virada de assunto
DEFAULT_CYCLE = ("escuro", "bege", "claro")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
TOPIC_FIELDS = {"inicio", "fim", "fundo", "imagem"}
CONTIGUITY_TOLERANCE = 0.005  # s: abaixo disso uma emenda entre assuntos é só arredondamento
_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def hex_tone(color: str) -> str:
    """`light` ou `dark` pela luminância percebida (Rec. 601) de uma cor #RRGGBB."""
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return "light" if (0.299 * r + 0.587 * g + 0.114 * b) / 255 >= 0.5 else "dark"


def background_segment(background: str, duration: float, label: str) -> dict:
    """Trecho de fundo para o `fundo` pedido: nome (escuro, claro, bege), hex, chave do tema ou caminho de
    imagem. Cor vira cartão de cor lisa; imagem vira trecho de imagem cortado para preencher a tela."""
    if background.lower().endswith(tuple(IMAGE_EXTENSIONS)):
        return {
            "type": "image",
            "src": background,
            "duration": duration,
            "motion": "none",
            "reframe": {"mode": "crop"},
            "label": label,
        }
    named = NAMED_BACKGROUNDS.get(background.lower())
    if named:
        color, tone = named
    elif _HEX_RE.fullmatch(background):
        color, tone = background, hex_tone(background)
    else:  # chave do tema (primary, accent...): a cor só se conhece na hora de renderizar
        color, tone = background, ""
    segment = {
        "type": "card",
        "flat": True,
        "logo": False,
        "motion": "none",
        "background": color,
        "duration": duration,
        "label": label,
    }
    if tone:
        segment["variant"] = tone
    return segment


def plan_topics(raw: Any) -> list[dict]:
    """Assuntos conferidos e completos. Aceita `inicio`, `fim`, `fundo` e `imagem`; o início de cada um é
    o fim do anterior (e 0 para o primeiro), e dizê-lo é opcional. Levanta ValueError dizendo qual
    assunto e o que está errado."""
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            "`assuntos` precisa ser uma lista com pelo menos um assunto (inicio, fim, fundo, imagem)"
        )
    topics: list[dict] = []
    previous_end = 0.0
    for position, item in enumerate(raw):
        number = position + 1
        if not isinstance(item, dict):
            raise ValueError(f"assunto {number}: esperava um objeto com inicio, fim, fundo e imagem")
        unknown = sorted(set(item) - TOPIC_FIELDS)
        if unknown:
            raise ValueError(
                f"assunto {number}: campo(s) desconhecido(s): {', '.join(unknown)} "
                f"(use {', '.join(sorted(TOPIC_FIELDS))})"
            )
        end = item.get("fim")
        if not _is_number(end):
            raise ValueError(f"assunto {number}: `fim` é obrigatório e precisa ser um número em segundos")
        start = item.get("inicio", previous_end)
        if not _is_number(start):
            raise ValueError(f"assunto {number}: `inicio` precisa ser um número em segundos")
        if abs(start - previous_end) > CONTIGUITY_TOLERANCE:
            expected = (
                "o primeiro assunto começa em 0 s"
                if position == 0
                else f"o assunto {position} termina em {previous_end:g} s"
            )
            raise ValueError(
                f"assunto {number}: começa em {start:g} s, mas {expected}; os assuntos precisam se emendar, "
                "sem vão nem sobreposição, para o fundo trocar sem cortar a fala"
            )
        if end <= start:
            raise ValueError(f"assunto {number}: `fim` ({end:g}) precisa ser maior que o início ({start:g})")
        duration = round(end - start, 3)
        fundo = item.get("fundo") or DEFAULT_CYCLE[position % len(DEFAULT_CYCLE)]
        if not isinstance(fundo, str):
            raise ValueError(f"assunto {number}: `fundo` precisa ser um texto (nome, cor ou imagem)")
        image = item.get("imagem") or ""
        if not isinstance(image, str):
            raise ValueError(f"assunto {number}: `imagem` precisa ser o caminho de uma imagem")
        segment = background_segment(fundo, duration, f"assunto {number}")
        topics.append(
            {
                "index": position,
                "inicio": round(start, 3),
                "fim": round(end, 3),
                "duracao": duration,
                "fundo": fundo,
                "imagem": image,
                "segmento": segment,
            }
        )
        previous_end = end
    return topics


def prepare_explainer(params: dict[str, Any]) -> dict[str, Any]:
    """Preparador do template "explicativo": troca `assuntos` pela lista completa e acrescenta
    `duracao_total` (o fim do último assunto), que é a duração do vídeo."""
    topics = plan_topics(params.get("assuntos"))
    return {**params, "assuntos": topics, "duracao_total": topics[-1]["fim"]}
