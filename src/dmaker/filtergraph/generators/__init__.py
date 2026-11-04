"""Construtores dos geradores de som: dado o gerador e a duração, devolvem uma fonte do ffmpeg ou as amostras em numpy.

Para criar um construtor novo, ponha a função num arquivo desta pasta (`@register_generator_builder("tipo")`) e a classe
de mesmo `type` em `domain/generators/`: este `__init__` importa sozinho cada módulo da pasta. Há um teste que prende
os dois registros aos mesmos tipos.
"""

from __future__ import annotations

import importlib
import pkgutil

from .registry import (
    FilterSource,
    GeneratorBuilder,
    GeneratorRequest,
    build_generator,
    builder_types,
    register_generator_builder,
)

for _module in pkgutil.iter_modules(__path__):
    if _module.name != "registry":
        importlib.import_module(f"{__name__}.{_module.name}")

__all__ = [
    "FilterSource",
    "GeneratorBuilder",
    "GeneratorRequest",
    "build_generator",
    "builder_types",
    "register_generator_builder",
]
