"""Sincronização por áudio: sinais sintéticos deslocados devem devolver o deslocamento certo."""

import numpy as np
import pytest

from dmaker.media.audiosync import (
    MIN_GUIDED_OVERLAP_S,
    RATE,
    SyncResult,
    estimate_offset,
    estimate_offset_near,
)


def _event_audio(seconds: float, seed: int = 1) -> np.ndarray:
    """Som de evento: ruído com rajadas (palmas, música) para a correlação ter o que agarrar."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    signal = rng.normal(0, 0.02, n).astype(np.float32)
    for start in rng.uniform(0, seconds - 0.5, size=int(seconds * 2)):
        i = int(start * RATE)
        burst = rng.normal(0, 0.4, int(0.15 * RATE)) * np.hanning(int(0.15 * RATE))
        signal[i : i + len(burst)] += burst.astype(np.float32)
    return signal


def _noise(seconds: float, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, 0.02, int(seconds * RATE)).astype(np.float32)


def _embed(base: np.ndarray, event: np.ndarray, start_s: float) -> np.ndarray:
    """Substitui (não soma) um trecho de `base` por `event`, como se fosse o mesmo som captado
    pelas duas câmeras naquele instante."""
    base = base.copy()
    i = int(start_s * RATE)
    base[i : i + len(event)] = event
    return base


@pytest.mark.parametrize("offset", [1.234, 17.5, -3.75])
def test_estimate_offset_recovers_shift(offset):
    master = _event_audio(120)
    shift = int(round(offset * RATE))
    # other = trecho do mesmo som, começando `offset` s depois do master (ou antes, se negativo)
    if shift >= 0:
        other = master[shift:].copy()
    else:
        other = np.concatenate([np.zeros(-shift, dtype=np.float32), master])
    other += np.random.default_rng(7).normal(0, 0.01, len(other)).astype(np.float32)  # microfone diferente
    result = estimate_offset(master, other)
    assert result.offset == pytest.approx(offset, abs=0.002)
    assert result.reliable


def test_long_recordings_use_coarse_stage(monkeypatch):
    master = _event_audio(900, seed=3)  # 15 min
    other = master[int(400.5 * RATE) : int(700 * RATE)].copy()  # gravador ligou em 400.5 s
    result = estimate_offset(master, other)
    assert result.offset == pytest.approx(400.5, abs=0.002)


def test_unrelated_audio_has_low_confidence():
    a = _event_audio(30, seed=1)
    b = _event_audio(30, seed=99)
    assert isinstance(estimate_offset(a, b), SyncResult)
    assert estimate_offset(a, b).confidence < estimate_offset(a, a).confidence


def test_guided_offset_finds_link_that_blind_correlation_misses():
    """Um arquivo longo com o MESMO trecho de evento repetido duas vezes (a posição verdadeira e
    uma "decoy" em outro ponto, como um aplauso parecido em outro momento da festa) engana a
    correlação cega, que não tem como saber qual das duas repetições é a de verdade; a guiada,
    sabendo a vizinhança esperada, ignora a decoy e acha o alinhamento certo (posição absoluta,
    não a do corte)."""
    event = _event_audio(20, seed=5)
    master = _embed(_embed(_noise(1200, seed=1), event, 200.0), event, 1000.0)  # decoy em 200s
    other = _embed(_noise(600, seed=2), event, 100.0)
    true_offset = 1000.0 - 100.0
    decoy_offset = 200.0 - 100.0

    blind = estimate_offset(master, other)
    assert blind.offset == pytest.approx(decoy_offset, abs=0.5)  # cega cai na decoy

    guided = estimate_offset_near(master, other, expected=910.0, tolerance=90.0)
    assert guided.reliable
    assert guided.offset == pytest.approx(true_offset, abs=0.05)


def test_guided_offset_reports_no_confidence_when_overlap_too_small():
    """Se o deslocamento esperado deixa quase nenhuma sobreposição prevista entre os arquivos, não
    há o que correlacionar: devolve o próprio `expected`, sem confiança."""
    master = np.zeros(int(100 * RATE), dtype=np.float32)
    other = np.zeros(int(50 * RATE), dtype=np.float32)
    result = estimate_offset_near(master, other, expected=99.0, tolerance=5.0)
    assert result.offset == 99.0
    assert result.confidence == 0.0
    assert not result.reliable
    assert MIN_GUIDED_OVERLAP_S > 100 - 99  # a sobreposição prevista (1s) fica abaixo do limiar
