"""Informações da CPU para dimensionar o cálculo dos modelos locais."""

from __future__ import annotations

import os


def compute_threads() -> int:
    """Threads de cálculo: os núcleos físicos, porque os 'lógicos' do hyper-threading disputam as mesmas
    unidades de ponto flutuante e não aceleram a inferência de redes neurais na CPU."""
    try:
        import psutil

        physical = psutil.cpu_count(logical=False)
    except ImportError:
        physical = None
    return physical or os.cpu_count() or 1
