"""Análise de áudio: funções puras sobre amostras (numpy), sem ffmpeg e sem disco.

Os analisadores do Audacity (Contraste, Achar Clipping, Medir RMS, Espectro de Frequência, Marcar Sons, Achar Batidas e
Exportar Amostras) são classes registradas em `analyzers/`: o registro e o catálogo estão em `registry.py`, o sinal e
as contas de dB em `signal.py`, e a FFT com as janelas, que o espectrograma também usa, em `fft.py`. Quem lê o som do
projeto e decodifica é o pipeline (`pipeline/audio_analysis.py`).
"""

from __future__ import annotations

import importlib
import pkgutil

from . import analyzers
from .registry import (
    ANALYSIS_SOURCES,
    ANALYZER_CLASSES,
    AnalysisResult,
    AnalyzerBase,
    MarkerProposal,
    analyzer_catalog,
    analyzer_class,
    parse_analyzer,
    register_analyzer,
)
from .signal import Signal

# cada módulo de `analyzers/` registra o seu analisador ao ser importado
for _module in pkgutil.iter_modules(analyzers.__path__):
    importlib.import_module(f"{analyzers.__name__}.{_module.name}")

__all__ = [
    "ANALYSIS_SOURCES",
    "ANALYZER_CLASSES",
    "AnalysisResult",
    "AnalyzerBase",
    "MarkerProposal",
    "Signal",
    "analyzer_catalog",
    "analyzer_class",
    "parse_analyzer",
    "register_analyzer",
]
