"""Acabamento de cada fala sintetizada, antes de guardar no cache e de juntar na narração. Funções puras."""

from __future__ import annotations

import numpy as np

# Cada motor enche a fala com entrada e cauda de silêncio próprias; deixadas ali, cada junção vira um
# buraco imprevisível. Aparadas, a pausa entre falas é só a que o roteiro pede. -40 dBFS está bem abaixo
# da fala e acima do ruído de fundo de uma síntese limpa; 40 ms de margem preservam ataque e decaimento.
EDGE_THRESHOLD_DB = -40.0
EDGE_KEEP_MS = 40

# Versão desta etapa, parte da chave do cache de falas: mudou o acabamento, as falas antigas não valem.
POSTPROCESS_VERSION = "2"


def sanitize_samples(samples: np.ndarray) -> np.ndarray:
    """Troca NaN e infinito por silêncio: um único valor inválido deixa o WAV ilegível para o ffmpeg."""
    return np.nan_to_num(np.asarray(samples, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)


def trim_edge_silence(
    samples: np.ndarray,
    sample_rate: int,
    threshold_db: float = EDGE_THRESHOLD_DB,
    keep_ms: int = EDGE_KEEP_MS,
) -> np.ndarray:
    """Remove o silêncio das pontas, deixando `keep_ms` de cada lado; uma fala toda muda volta como veio."""
    loud = np.flatnonzero(np.abs(samples) > 10.0 ** (threshold_db / 20.0))
    if loud.size == 0:
        return samples
    keep = int(sample_rate * keep_ms / 1000)
    start = max(0, int(loud[0]) - keep)
    end = min(len(samples), int(loud[-1]) + 1 + keep)
    return samples[start:end]


def finish_speech(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Limpeza e aparo de uma fala recém-sintetizada."""
    return trim_edge_silence(sanitize_samples(samples), sample_rate)
