"""Efeitos de áudio da spec: a cadeia ordenada que qualquer item de áudio (ou o master) recebe.

Para criar um efeito novo, ponha a classe num arquivo desta pasta (decorada com `@register_effect`) e o construtor
do filtro no arquivo de mesmo nome em `filtergraph/audio_effects/`: este `__init__` importa sozinho cada módulo da
pasta, e a união `AudioEffect` da spec sai do registro. O contrato completo está em `docs/MANUAL.md`
("Edição de áudio") e no módulo `filtergraph.audio_effects`.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Sequence
from typing import Annotated, Any, Union

from pydantic import Field, TypeAdapter

from .base import EFFECT_CLASSES, EffectAction, EffectBase, effect_type, param, register_effect

# os módulos de família (basic, depois os dos outros cards) se registram ao serem importados; as predefinições citam
# efeitos pelo tipo, então só entram depois de todas as famílias
for _module in pkgutil.iter_modules(__path__):
    if _module.name not in {"base", "catalog", "presets"}:
        importlib.import_module(f"{__name__}.{_module.name}")

# a união discriminada pelo `type`, montada do registro: é o tipo dos campos `effects` da spec
AudioEffect = Annotated[Union[tuple(EFFECT_CLASSES.values())], Field(discriminator="type")]  # noqa: UP007

_ADAPTER: TypeAdapter[Any] = TypeAdapter(AudioEffect)

from .catalog import (  # noqa: E402
    EFFECT_TARGETS,
    EffectInfo,
    ParamInfo,
    catalog,
    catalog_payload,
    common_parameters,
    effect_info,
)
from .presets import (  # noqa: E402
    EFFECT_PRESETS,
    EffectPreset,
    check_preset_fits,
    get_effect_preset,
    preset_catalog,
    register_effect_preset,
)


def parse_effect(data: dict | EffectBase) -> EffectBase:
    """Um efeito da spec a partir de um dicionário (`{"type": "amplify", "gain_db": 6}`), com a mensagem de
    erro em português quando o tipo não existe: a do Pydantic para uma união discriminada é difícil de ler."""
    if isinstance(data, EffectBase):
        return data
    name = data.get("type") if isinstance(data, dict) else None
    if name not in EFFECT_CLASSES:
        known = ", ".join(sorted(EFFECT_CLASSES))
        raise ValueError(f"Efeito de áudio desconhecido: {name!r}. Use um de: {known}")
    return _ADAPTER.validate_python(data)


def active_effects(effects: Sequence[EffectBase]) -> list[tuple[int, EffectBase]]:
    """Os efeitos ligados, cada um com a posição que tem na lista da spec (as medidas e as mensagens usam essa
    posição, que não muda quando outro efeito é desligado)."""
    return [(index, effect) for index, effect in enumerate(effects) if effect.enabled]


def chain_duration(effects: Sequence[EffectBase], duration: float) -> float:
    """Quanto dura o item depois de toda a cadeia (os efeitos desligados não contam)."""
    for _, effect in active_effects(effects):
        duration = effect.output_duration(duration)
    return duration


def chain_refusal(effects: Sequence[EffectBase], duration: float) -> str | None:
    """O primeiro motivo pelo qual a cadeia não pode rodar num item de `duration` segundos (o teto de saída do
    Paulstretch), ou None. Cada efeito vê a duração que chega a ele, depois dos anteriores."""
    for _, effect in active_effects(effects):
        reason = effect.refusal(duration)
        if reason is not None:
            return reason
        duration = effect.output_duration(duration)
    return None


def rebase_effects(
    effects: Sequence[EffectBase], origin: float, length: float, total: float | None = None
) -> list[EffectBase]:
    """A cadeia de um pedaço do item que começa em `origin` (segundos do item) e dura `length`: cada intervalo anda
    junto com o som e o que cai fora do pedaço some. É o que leva a cadeia para a metade de uma divisão, para o
    trecho que sobra de uma apara e para a cópia de um trecho. `total` é a duração do item inteiro, quando se sabe: o
    Fade Out preso ao fim do item só fica no pedaço que contém o fim."""
    kept = []
    for effect in effects:
        moved = effect.rebased(origin, length, total)
        if moved is not None:
            kept.append(moved)
    return kept


def rebase_effect_dicts(
    chain: Sequence[dict], origin: float, length: float, total: float | None = None
) -> list[dict]:
    """Como `rebase_effects`, para a cadeia como dicionários (a forma que a edição da spec manipula)."""
    return [
        effect.model_dump()
        for effect in rebase_effects([parse_effect(item) for item in chain], origin, length, total)
    ]


def chain_signature(effects: Sequence[EffectBase]) -> list[dict]:
    """Os efeitos ligados como dados puros: é o que muda o som, então é o que entra na chave de cache."""
    return [effect.model_dump(mode="json") for _, effect in active_effects(effects)]


__all__ = [
    "EFFECT_CLASSES",
    "EFFECT_PRESETS",
    "EFFECT_TARGETS",
    "AudioEffect",
    "EffectAction",
    "EffectBase",
    "EffectInfo",
    "EffectPreset",
    "ParamInfo",
    "active_effects",
    "catalog",
    "catalog_payload",
    "chain_duration",
    "chain_refusal",
    "chain_signature",
    "check_preset_fits",
    "common_parameters",
    "effect_info",
    "effect_type",
    "get_effect_preset",
    "param",
    "parse_effect",
    "preset_catalog",
    "rebase_effect_dicts",
    "rebase_effects",
    "register_effect",
    "register_effect_preset",
]
