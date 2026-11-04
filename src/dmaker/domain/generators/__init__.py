"""Geradores de som da spec: Tom, Chirp, Ruído, DTMF, Silêncio, Pluck, Tambor de Risset, Faixa de Ritmo e Importar Amostras.

Para criar um gerador novo, ponha a classe num arquivo desta pasta (decorada com `@register_generator`) e a função que
produz as amostras no arquivo de mesmo nome em `filtergraph/generators/` (`@register_generator_builder`): este
`__init__` importa sozinho cada módulo da pasta. O som posto no projeto é um item de `audio.generated`
(`GeneratedSound`, em `domain/spec.py`); o contrato completo está em `docs/MANUAL.md` ("Edição de áudio").
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import asdict, dataclass
from typing import Any

from pydantic import ValidationError
from pydantic_core import to_jsonable_python

from ..audio_effects.catalog import ParamInfo, param_info
from .base import (
    DEFAULT_DURATION,
    GENERATOR_CLASSES,
    GENERATOR_SAMPLE_RATE,
    GeneratorBase,
    generator_type,
    register_generator,
)

# os módulos de família (tons, telefonia...) se registram ao serem importados
for _module in pkgutil.iter_modules(__path__):
    if _module.name != "base":
        importlib.import_module(f"{__name__}.{_module.name}")

__all__ = [
    "DEFAULT_DURATION",
    "GENERATOR_CLASSES",
    "GENERATOR_SAMPLE_RATE",
    "GeneratorBase",
    "GeneratorInfo",
    "catalog",
    "catalog_payload",
    "generator_info",
    "generator_type",
    "normalized_params",
    "parse_generator",
    "register_generator",
]


def parse_generator(name: object, params: dict[str, Any] | None = None) -> GeneratorBase:
    """O gerador de tipo `name` com os parâmetros dados (os que faltam ficam no padrão). A mensagem de erro é em português
    e cita o tipo: a do Pydantic para um campo fora da faixa não diz qual gerador reclamou."""
    if not isinstance(name, str) or name not in GENERATOR_CLASSES:
        known = ", ".join(GENERATOR_CLASSES)
        raise ValueError(f"Gerador de som desconhecido: {name!r}. Use um de: {known}")
    cls = GENERATOR_CLASSES[name]
    try:
        return cls.model_validate({**(params or {}), "type": name})
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'valor'}: {error['msg'].removeprefix('Value error, ')}"
            for error in exc.errors()
        )
        raise ValueError(f"gerador {name}: {details}") from exc


def normalized_params(name: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """Os parâmetros completos do gerador (padrões incluídos) como vão para a spec: dois pedidos iguais têm o mesmo JSON."""
    generator = parse_generator(name, params)
    return generator.model_dump(mode="json", exclude={"type"})


@dataclass(frozen=True)
class GeneratorInfo:
    """Um gerador do catálogo: o `type` da spec, os nomes (português e Audacity), o que faz e os parâmetros."""

    type: str
    label: str
    audacity_name: str
    summary: str
    family: str
    default_duration: float
    has_natural_duration: bool
    parameters: tuple[ParamInfo, ...]

    def to_dict(self) -> dict:
        return to_jsonable_python(asdict(self))


def generator_info(cls: type[GeneratorBase]) -> GeneratorInfo:
    own = [name for name in cls.model_fields if name != "type"]
    return GeneratorInfo(
        type=generator_type(cls),
        label=cls.label,
        audacity_name=cls.audacity_name,
        summary=cls.summary,
        family=cls.family,
        default_duration=cls().natural_duration(),  # todo parâmetro tem padrão, então a classe se cria sozinha
        has_natural_duration=cls.has_natural_duration,
        parameters=tuple(param_info(name, cls) for name in own),
    )


def catalog() -> list[GeneratorInfo]:
    """Todos os geradores registrados, na ordem em que foram registrados."""
    return [generator_info(cls) for cls in GENERATOR_CLASSES.values()]


def catalog_payload(generator_type_name: str | None = None) -> dict[str, Any]:
    """O catálogo como a API, o MCP e a CLI o entregam: os geradores (todos, ou só o de `generator_type_name`) e os campos
    do item da spec que valem para qualquer um deles. Um nome que não existe é erro."""
    infos = catalog()
    if generator_type_name is not None:
        infos = [info for info in infos if info.type == generator_type_name]
        if not infos:
            known = ", ".join(GENERATOR_CLASSES)
            raise ValueError(f"Gerador de som desconhecido: {generator_type_name!r}. Use um de: {known}")
    return {
        "generators": [info.to_dict() for info in infos],
        "item": [
            {
                "name": "start",
                "label": "Início",
                "unit": "s",
                "hint": "O instante do vídeo final em que o som começa.",
            },
            {
                "name": "duration",
                "label": "Duração",
                "unit": "s",
                "hint": "Quanto o som dura; o gerador enche exatamente esse tempo.",
            },
            {
                "name": "volume",
                "label": "Volume",
                "unit": "",
                "hint": "Ganho linear do item (1 é o nível do gerador).",
            },
            {"name": "pan", "label": "Equilíbrio", "unit": "", "hint": "De -1 (esquerda) a 1 (direita)."},
        ],
        "target": "audio.generated.N",
        "track": "SFX",
    }
