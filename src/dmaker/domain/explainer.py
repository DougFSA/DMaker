"""Preparação do modelo "explicativo" (`templates/explicativo.json`): confere a lista de assuntos e deriva
o que o JSON do template não calcula sozinho (duração de cada assunto, tom do fundo, o trecho de fundo).

Cada assunto vira um trecho de fundo na linha do tempo e, se tiver imagem, uma sobreposição na região
"topo"; se tiver infográfico (`infografico`: o nome de um modelo pronto e os parâmetros dele), uma composição em
HTML na mesma região, durante o assunto. A gravação do apresentador é uma sobreposição só, contínua: por isso os
assuntos precisam ser contíguos e a troca de fundo nunca corta a fala. Cada assunto pode ter `sons` (efeitos da
biblioteca num instante contado desde o começo dele), que viram `audio.sfx` no tempo do vídeo. Tudo aqui é puro:
recebe dados, devolve dados. Os parâmetros do infográfico são conferidos pelo esquema do modelo na validação do
projeto, não aqui.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Any

from ..sfx.synth import library_names
from .spec import SFX_VOLUME_MAX

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
TOPIC_FIELDS = {"inicio", "fim", "fundo", "imagem", "infografico", "sons"}
INFOGRAPHIC_FIELDS = {"nome", "parametros"}
SOUND_FIELDS = {"som", "em", "volume"}
CONTIGUITY_TOLERANCE = 0.005  # s: abaixo disso uma emenda entre assuntos é só arredondamento
_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_finite_number(value: Any) -> bool:
    """Número de verdade: `nan` e infinito passariam por qualquer comparação de limite sem serem recusados."""
    return _is_number(value) and math.isfinite(value)


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


def plan_infographic(raw: Any, number: int) -> dict | None:
    """O infográfico de um assunto (`{"nome": "contador", "parametros": {...}}`) conferido na forma, ou None se o
    assunto não tem. Quais parâmetros o modelo aceita é assunto do esquema dele, conferido na validação do projeto."""
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError(
            f"assunto {number}: `infografico` precisa ser um objeto com `nome` e `parametros`, "
            'como {"nome": "contador", "parametros": {"ate": 10000}}'
        )
    unknown = sorted(set(raw) - INFOGRAPHIC_FIELDS)
    if unknown:
        raise ValueError(
            f"assunto {number}: `infografico` tem campo(s) desconhecido(s): {', '.join(unknown)} "
            f"(use {', '.join(sorted(INFOGRAPHIC_FIELDS))})"
        )
    name = raw.get("nome")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(
            f"assunto {number}: `infografico` precisa de `nome` (um modelo de `list_infographics`)"
        )
    params = raw.get("parametros") or {}
    if not isinstance(params, dict):
        raise ValueError(f"assunto {number}: `infografico.parametros` precisa ser um objeto")
    return {"nome": name.strip(), "parametros": params}


def plan_sounds(
    raw: Any, number: int, start: float, duration: float, available: Sequence[str]
) -> list[dict[str, Any]]:
    """Os sons de um assunto (`[{"som": "whoosh", "em": 0, "volume": 1}]`) como itens de `audio.sfx`: o instante
    `em` (segundos desde o começo do assunto, 0 se omitido) somado ao início do assunto dá o tempo do vídeo.
    Só entram nomes da biblioteca (`available`), para o erro sair aqui, dizendo o assunto, e não no render."""
    if raw is None or raw == []:
        return []
    if not isinstance(raw, list):
        raise ValueError(
            f"assunto {number}: `sons` precisa ser uma lista de objetos com `som`, `em` e `volume`, "
            'como [{"som": "whoosh", "em": 0}]'
        )
    cues: list[dict[str, Any]] = []
    for position, item in enumerate(raw):
        label = f"assunto {number}, som {position + 1}"
        if not isinstance(item, dict):
            raise ValueError(f"{label}: esperava um objeto com som, em e volume")
        unknown = sorted(set(item) - SOUND_FIELDS)
        if unknown:
            raise ValueError(
                f"{label}: campo(s) desconhecido(s): {', '.join(unknown)} "
                f"(use {', '.join(sorted(SOUND_FIELDS))})"
            )
        name = item.get("som")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{label}: `som` é obrigatório (disponíveis: {', '.join(available)})")
        sound = {candidate.lower(): candidate for candidate in available}.get(name.strip().lower())
        if sound is None:
            raise ValueError(
                f'{label}: o som "{name.strip()}" não existe na biblioteca de efeitos '
                f"(disponíveis: {', '.join(available)})"
            )
        offset = item.get("em")
        offset = 0 if offset is None else offset
        if not _is_finite_number(offset):
            raise ValueError(f"{label}: `em` precisa ser um número em segundos desde o começo do assunto")
        if offset < 0 or offset > duration:
            raise ValueError(
                f"{label}: `em` ({offset:g} s) cai fora do assunto, que dura {duration:g} s; "
                f"use um valor de 0 a {duration:g}"
            )
        cue: dict[str, Any] = {"sound": sound, "at": round(start + offset, 3)}
        volume = item.get("volume")
        if volume is not None:
            if not _is_finite_number(volume) or not 0 <= volume <= SFX_VOLUME_MAX:
                raise ValueError(
                    f"{label}: `volume` precisa ser um número de 0 a {SFX_VOLUME_MAX:g} "
                    "(1 é o nível padrão do efeito)"
                )
            cue["volume"] = volume
        cues.append(cue)
    return cues


def collect_sfx(topics: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Os sons de todos os assuntos numa lista só, na ordem dos assuntos: o `audio.sfx` do projeto."""
    return [cue for topic in topics for cue in topic["sons"]]


def plan_topics(raw: Any, available_sounds: Sequence[str] | None = None) -> list[dict]:
    """Assuntos conferidos e completos. Aceita `inicio`, `fim`, `fundo`, `imagem`, `infografico` e `sons`; o início
    de cada um é o fim do anterior (e 0 para o primeiro), e dizê-lo é opcional. `available_sounds` são os nomes de
    som aceitos (a biblioteca, se omitido). Levanta ValueError dizendo qual assunto e o que está errado."""
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            "`assuntos` precisa ser uma lista com pelo menos um assunto "
            "(inicio, fim, fundo, imagem, infografico, sons)"
        )
    sounds = library_names() if available_sounds is None else available_sounds
    topics: list[dict] = []
    previous_end = 0.0
    for position, item in enumerate(raw):
        number = position + 1
        if not isinstance(item, dict):
            raise ValueError(
                f"assunto {number}: esperava um objeto com inicio, fim, fundo, imagem, infografico e sons"
            )
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
                "infografico": plan_infographic(item.get("infografico"), number),
                "sons": plan_sounds(item.get("sons"), number, round(start, 3), duration, sounds),
                "segmento": segment,
            }
        )
        previous_end = end
    return topics


def prepare_explainer(params: dict[str, Any]) -> dict[str, Any]:
    """Preparador do template "explicativo": troca `assuntos` pela lista completa e acrescenta
    `duracao_total` (o fim do último assunto, que é a duração do vídeo) e `sfx` (os sons de todos os assuntos,
    no tempo do vídeo, que o template põe em `audio.sfx`)."""
    topics = plan_topics(params.get("assuntos"))
    return {**params, "assuntos": topics, "duracao_total": topics[-1]["fim"], "sfx": collect_sfx(topics)}
