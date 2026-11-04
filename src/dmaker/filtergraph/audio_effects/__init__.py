"""Construtores dos efeitos de áudio: a cadeia de um item vira linhas de grafo do ffmpeg.

Como acrescentar um efeito: a classe do efeito vai em `domain/audio_effects/<família>.py`, e o construtor em
`filtergraph/audio_effects/<família>.py`, com o mesmo nome de arquivo. O construtor é uma função pura que recebe
um `EffectRequest` e devolve as linhas do grafo; `@register_builder("<type>")` o registra e este `__init__`
importa cada módulo da pasta sozinho. Quatro pontos do contrato:

- Medidas: um efeito cuja classe devolve `needs_measure() == True` recebe em `request.measure` o pico, o DC e os
  extremos de cada canal do sinal que entra nele (lidos por uma passada de análise antes do render).
- Duração: um efeito que muda a duração declara `changes_duration = True` na classe e sobrescreve
  `output_duration()`; a spec só o aceita onde o item pode crescer.
- Intervalo: `start`/`end` valem para qualquer efeito sem trabalho extra (ver `chain.apply_effect`): o
  construtor recebe só o trecho do intervalo, com o tempo zerado.
- Estágio de amostras: o efeito que não cabe num filtro (subtração espectral, interpolação) marca `sample_stage = True`
  na classe e registra uma função pura sobre arrays com `@register_sample_builder("<type>")`, que recebe um
  `SampleRequest` (`samples` de forma `(amostras, canais)`, `measure`) e devolve o sinal depois do efeito. O processador
  parte a cadeia em trechos de ffmpeg e estágios de amostras, e o intervalo e a emenda de 10 ms são os mesmos.
- Segunda entrada: um efeito que usa outra trilha (Vocoder, Auto Duck) a recebe em `request.side`, um rótulo
  de entrada já posto no grafo por quem monta o comando (`pipeline.audio_effects`); hoje ninguém o preenche.
"""

from __future__ import annotations

import importlib
import pkgutil

from .registry import (
    SAMPLE_RATE,
    EffectBuilder,
    EffectRequest,
    SampleBuilder,
    SampleRequest,
    build_effect,
    build_samples,
    builder_types,
    is_sample_effect,
    register_builder,
    register_sample_builder,
    sample_builder_types,
)

# os módulos de família registram os construtores ao serem importados
for _module in pkgutil.iter_modules(__path__):
    if _module.name not in {"registry", "measure", "chain", "samples"}:
        importlib.import_module(f"{__name__}.{_module.name}")

from .chain import (  # noqa: E402
    SEAM_SECONDS,
    Stage,
    apply_effect,
    chain_lines,
    ingress_line,
    span_samples,
    split_stages,
    stage_lines,
)
from .measure import ChannelLevels, Measure, measure_lines, parse_astats  # noqa: E402
from .samples import apply_sample_effect  # noqa: E402

__all__ = [
    "SAMPLE_RATE",
    "SEAM_SECONDS",
    "ChannelLevels",
    "EffectBuilder",
    "EffectRequest",
    "Measure",
    "SampleBuilder",
    "SampleRequest",
    "Stage",
    "apply_effect",
    "apply_sample_effect",
    "build_effect",
    "build_samples",
    "builder_types",
    "chain_lines",
    "ingress_line",
    "is_sample_effect",
    "measure_lines",
    "parse_astats",
    "register_builder",
    "register_sample_builder",
    "sample_builder_types",
    "span_samples",
    "split_stages",
    "stage_lines",
]
