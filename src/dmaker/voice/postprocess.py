"""Acabamento de cada fala sintetizada, antes de guardar no cache e de juntar na narração. Funções puras."""

from __future__ import annotations

import numpy as np

# Cada motor enche a fala com entrada e cauda de silêncio próprias; deixadas ali, cada junção vira um
# buraco imprevisível. Aparadas, a pausa entre falas é só a que o roteiro pede.
# O limiar fica em -55 dBFS, e não mais em -40: a última sílaba ainda está decaindo a -40/-45 dB, e
# aparar ali cortava o decaimento e deixava o fim da frase seco, pouco natural (DMK-79). -55 dB segue
# acima do ruído de fundo de uma síntese limpa (o Kokoro termina a -81 dB).
EDGE_THRESHOLD_DB = -55.0
# Margens assimétricas: o ataque é curto, 40 ms bastam antes da voz; o decaimento é longo, e 120 ms
# depois do último ponto acima do limiar levam a cauda até o silêncio. Margem maior dos dois lados
# alongaria a pausa entre frases; assim ela cresce cerca de 0,1 s.
LEAD_KEEP_MS = 40
TAIL_KEEP_MS = 120

# Versão desta etapa, parte da chave do cache de falas: mudou o acabamento, as falas antigas não valem.
POSTPROCESS_VERSION = "3"


def sanitize_samples(samples: np.ndarray) -> np.ndarray:
    """Troca NaN e infinito por silêncio: um único valor inválido deixa o WAV ilegível para o ffmpeg."""
    return np.nan_to_num(np.asarray(samples, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)


def trim_edge_silence(
    samples: np.ndarray,
    sample_rate: int,
    threshold_db: float = EDGE_THRESHOLD_DB,
    lead_ms: int = LEAD_KEEP_MS,
    tail_ms: int = TAIL_KEEP_MS,
) -> np.ndarray:
    """Remove o silêncio das pontas, com `lead_ms` antes da voz e `tail_ms` depois; fala toda muda volta como veio."""
    loud = np.flatnonzero(np.abs(samples) > 10.0 ** (threshold_db / 20.0))
    if loud.size == 0:
        return samples
    start = max(0, int(loud[0]) - int(sample_rate * lead_ms / 1000))
    end = min(len(samples), int(loud[-1]) + 1 + int(sample_rate * tail_ms / 1000))
    return samples[start:end]


def finish_speech(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Limpeza e aparo de uma fala recém-sintetizada."""
    return trim_edge_silence(sanitize_samples(samples), sample_rate)
