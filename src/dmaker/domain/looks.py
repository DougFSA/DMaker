"""Looks: acabamentos visuais prontos, com nome, para o pedido em português virar uma palavra só.

Um look é um `ColorAdjust` com nome: o ajuste de cor (eq, curves) mais os efeitos de acabamento
(vinheta, granulação, brilho, vazamento de luz, aberração). Os padrões moram aqui, sem arquivo de terceiros e sem
LUT; a marca define os seus em `looks` do brand.json e, com o mesmo nome, o da marca vale no lugar do padrão.
Quem escolhe o look de cada trecho é `effective_look_name` (função pura, com a regra de precedência).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from .spec import ColorAdjust

NO_LOOK = "nenhum"  # valor de `look` que desliga o acabamento (no trecho, desliga o do projeto)


class UnknownLookError(ValueError):
    """Nome de look que nem os padrões nem a marca conhecem."""


@dataclass(frozen=True)
class Look:
    name: str
    summary: str
    color: ColorAdjust
    aliases: tuple[str, ...] = ()
    source: Literal["padrão", "marca"] = "padrão"


# Cada look combina `eq` (contraste e saturação, no próprio quadro YUV) com UM `curves` (em RGB, onde a mistura de
# cor é natural): `master` é a curva de tons e `r`/`b` empurram o vermelho e o azul. Foi `colorbalance` no começo, que
# faz o mesmo, mas custa 9 s por 10 s de vídeo em 1080x1920 contra 1 s do `curves`. Os desvios de cor ficam em poucos
# centésimos: o suficiente para o olho ler a cor do look sem que a pele ou a marca no quadro virem outra cor. Os
# efeitos de acabamento usam quantidades modestas: a granulação custa tamanho de arquivo (o x264 gasta bits no grão),
# então os padrões ficam na faixa em que o render cresce pouco (ver o guia, seção "Looks e acabamento").
_CINEMA = ColorAdjust(
    contrast=1.06,
    saturation=0.9,
    # curva em S suave com preto levantado a 3% e branco abaixado a 97%, como a curva da cópia em película; sombras
    # para o verde-azulado (menos vermelho, mais azul) e luzes para o laranja (o contrário), as cores complementares
    # que o cinema usa
    extra=(
        "curves=m='0/0.03 0.25/0.21 0.75/0.79 1/0.97'"
        ":r='0/0 0.3/0.27 0.7/0.74 1/1':b='0/0.03 0.3/0.34 0.7/0.66 1/0.97'"
    ),
    vignette=0.25,
    grain=0.25,
)
_QUENTE = ColorAdjust(
    brightness=0.015,
    contrast=1.04,
    saturation=1.1,
    # meios-tons e luzes para o âmbar (vermelho acima da diagonal, azul abaixo) sem mexer no preto nem no branco
    extra="curves=r='0/0 0.5/0.56 1/1':b='0/0 0.5/0.44 1/0.94'",
    vignette=0.15,
    glow=0.2,
)
_FRIO = ColorAdjust(
    contrast=1.05,
    saturation=0.95,
    # o espelho do quente: azul acima da diagonal, vermelho abaixo
    extra="curves=r='0/0 0.5/0.45 1/0.96':b='0/0.02 0.5/0.56 1/1'",
    vignette=0.1,
)
_PB_CONTRASTE = ColorAdjust(
    contrast=1.1,
    saturation=0,
    # curva em S mais forte que a do cinema (sombras a 17%, luzes a 85% nos quartos): o preto e branco precisa de
    # separação de tons porque não tem cor para ajudar
    extra="curves=m='0/0 0.25/0.17 0.5/0.5 0.75/0.85 1/1'",
    vignette=0.4,
    grain=0.35,
)
_VINTAGE = ColorAdjust(
    contrast=0.95,
    saturation=0.8,
    gamma=1.05,
    # preto levantado a 7% e branco a 93% (desbotado), tom amarelado (azul para baixo, vermelho para cima), vinheta
    # forte, grão, um vazamento de luz e um pouco de aberração: os defeitos de lente e de película que dão a idade
    extra="curves=m='0/0.07 0.5/0.52 1/0.93':r='0/0.02 0.5/0.55 1/1':b='0/0 0.5/0.44 1/0.9'",
    vignette=0.45,
    grain=0.35,
    light_leak=0.3,
    aberration=0.15,
)

DEFAULT_LOOKS: dict[str, Look] = {
    look.name: look
    for look in (
        Look(
            "cinema",
            "Verde-azulado nas sombras, laranja nas luzes, preto levantado, vinheta e um grão fino de película.",
            _CINEMA,
            aliases=("cinematografico", "filme"),
        ),
        Look(
            "quente",
            "Tom âmbar de fim de tarde, cores mais vivas, vinheta leve e um brilho suave nas luzes.",
            _QUENTE,
            aliases=("quentinho", "dourado"),
        ),
        Look(
            "frio",
            "Tom azulado e calmo, cores um pouco mais contidas e vinheta leve.",
            _FRIO,
            aliases=("azulado",),
        ),
        Look(
            "pb-contraste",
            "Preto e branco de contraste alto, com vinheta marcada e grão.",
            _PB_CONTRASTE,
            aliases=("pb", "p-b", "preto-e-branco", "bw"),
        ),
        Look(
            "vintage",
            "Película antiga: cores desbotadas e amareladas, grão, vinheta, vazamento de luz e aberração.",
            _VINTAGE,
            aliases=("antigo", "retro"),
        ),
    )
}


def look_effects(look: Look) -> dict[str, float]:
    """Os efeitos de acabamento que o look liga (vinheta, grão, brilho, vazamento, aberração) e a quantidade de
    cada um, para listas e galerias dizerem o que o look faz além de mudar a cor."""
    color = look.color
    effects = {
        "vignette": 0.4 if color.vignette is True else float(color.vignette),
        "glow": color.glow,
        "aberration": color.aberration,
        "light_leak": color.light_leak,
        "grain": color.grain,
    }
    return {name: amount for name, amount in effects.items() if amount > 0}


def normalize_look_name(name: str) -> str:
    """Forma comparável do nome: minúsculas, sem acento, com hífen no lugar de espaço e sublinhado."""
    plain = unicodedata.normalize("NFKD", name.strip().lower())
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return "-".join(plain.replace("_", " ").split())


def is_no_look(name: str | None) -> bool:
    return name is not None and normalize_look_name(name) == NO_LOOK


def brand_look(name: str, data: Mapping[str, Any]) -> Look:
    """Look declarado no brand.json: `{"summary": "...", "color": {campos de ColorAdjust}}`."""
    unknown = set(data) - {"summary", "color"}
    if unknown:
        raise ValueError(f"look {name!r} da marca: campo(s) desconhecido(s) {', '.join(sorted(unknown))}")
    try:
        color = ColorAdjust.model_validate(data.get("color", {}))
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        raise ValueError(f"look {name!r} da marca: color.{where}: {first['msg']}") from exc
    return Look(normalize_look_name(name), str(data.get("summary", "")), color, source="marca")


def available_looks(brand_looks: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Look]:
    """Os looks padrão com os da marca por cima: com o mesmo nome, vale o da marca."""
    looks = dict(DEFAULT_LOOKS)
    for name, data in (brand_looks or {}).items():
        looks[normalize_look_name(name)] = brand_look(name, data)
    return looks


def resolve_look(name: str, brand_looks: Mapping[str, Mapping[str, Any]] | None = None) -> Look:
    """O look de um nome (ou apelido dos padrões); levanta `UnknownLookError` listando os que existem."""
    looks = available_looks(brand_looks)
    key = normalize_look_name(name)
    if key in looks:
        return looks[key]
    for look in DEFAULT_LOOKS.values():
        if key in look.aliases:
            return looks[look.name]
    raise UnknownLookError(f"look desconhecido: {name!r}. Use {', '.join([*looks, NO_LOOK])}.")


def effective_look_name(
    segment_look: str | None, project_look: str | None, segment_color: ColorAdjust
) -> str | None:
    """Nome do look que vale num trecho, ou None se ele não leva nenhum.

    O look do próprio trecho vence (e "nenhum" desliga o do projeto). Sem ele, vale o do projeto, a menos que o
    trecho declare ajuste de cor próprio: quem acertou a cor de um trecho à mão não quer vê-la trocada por um look
    global (se quiser os dois, pede o look no próprio trecho).
    """
    if segment_look is not None:
        return None if is_no_look(segment_look) else segment_look
    if project_look is None or is_no_look(project_look) or not segment_color.is_identity():
        return None
    return project_look
