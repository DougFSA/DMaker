"""O Noise Gate em numpy: o ganho que fecha o chiado entre as frases e abre antes da palavra chegar.

Por que não é o `agate` do ffmpeg: ele não tem `hold` (o tempo que o gate segura aberto depois de o som cair) e o
critério do efeito é que o começo das palavras fique inteiro, o que pede um ataque que ABRE ANTES de o som passar do
limiar. As duas coisas saem de contas vetorizadas sobre blocos de 1 ms, sem laço por amostra em Python:

1. o nível de cada bloco é o pico dele, com uma janela de 5 ms para trás (um tom grave tem um pico por ciclo; sem a
   janela o nível tremeria e o gate picotaria);
2. o bloco está "aberto" quando o nível passa do limiar; o `hold` estende a abertura para a frente e o ataque a estende
   para trás (o lookahead), então o ganho já começou a subir quando a palavra chega;
3. o ganho segue a abertura por uma rampa linear de `attack` ms para abrir e de `release` ms para fechar, entre a
   redução e 1, calculada por médias móveis (somas acumuladas);
4. o ganho de cada bloco é interpolado entre os centros dos blocos, e o sinal é multiplicado em pedaços de 20 s, para
   um item de uma hora não ter nenhuma cópia temporária do tamanho dele além da saída.

Funções puras: recebem amostras e devolvem amostras (ou números), sem tocar disco.
"""

from __future__ import annotations

import numpy as np

# O bloco de análise: 1 ms. O ataque mínimo do Audacity também é de 1 ms, então a rampa mais curta ocupa um bloco
BLOCK_SECONDS = 0.001
# A janela do detector: o nível de um bloco é o maior pico dos 5 ms que terminam nele
DETECTOR_BLOCKS = 5
# A margem que o ataque ganha além do pedido: a rampa é interpolada entre centros de bloco, e este bloco a mais garante
# que o ganho chegue a 1 antes do primeiro bloco acima do limiar
ATTACK_MARGIN_BLOCKS = 1
# Quanto da saída se multiplica de uma vez (segundos): o temporário do ganho tem este tamanho, não o do item
APPLY_CHUNK_SECONDS = 20.0
# O Analisar ruído sugere o limiar assim: o nível de ruído (percentil 95 do detector, que ignora um estalo solto) mais
# esta margem. Seis dB deixam o chiado de fundo (cujo pico oscila uns 3 dB em volta do percentil) sempre abaixo dele
NOISE_PERCENTILE = 95.0
SUGGESTED_MARGIN_DB = 6.0
FLOOR_DB = -120.0  # o nível de um bloco mudo: um piso finito, para as contas em dB não virarem -inf


def block_size(rate: int) -> int:
    return max(round(BLOCK_SECONDS * rate), 1)


def detector_levels_db(samples: np.ndarray, rate: int) -> np.ndarray:
    """O nível do detector de cada bloco de 1 ms, em dBFS, forma `(blocos, canais)`. O pico do bloco e, para trás, o maior
    dos `DETECTOR_BLOCKS` últimos. Lê o sinal em pedaços: o temporário é do tamanho do pedaço."""
    size = block_size(rate)
    channels = samples.shape[1]
    blocks = len(samples) // size
    peaks = np.empty((blocks, channels), dtype=np.float32)
    chunk_blocks = max(round(APPLY_CHUNK_SECONDS / BLOCK_SECONDS), 1)
    for first in range(0, blocks, chunk_blocks):
        last = min(first + chunk_blocks, blocks)
        piece = np.abs(np.asarray(samples[first * size : last * size], dtype=np.float32))
        peaks[first:last] = piece.reshape(last - first, size, channels).max(axis=1)
    if blocks:
        peaks = _running_max(peaks, DETECTOR_BLOCKS)
    return 20.0 * np.log10(np.maximum(peaks, 1e-6)).astype(np.float32)


def _running_max(values: np.ndarray, window: int) -> np.ndarray:
    """O maior valor dos `window` últimos (incluindo o atual), por canal; o começo repete o primeiro valor."""
    if window <= 1 or len(values) == 0:
        return values
    padded = np.concatenate([np.repeat(values[:1], window - 1, axis=0), values], axis=0)
    result = padded[window - 1 :].copy()
    for shift in range(1, window):
        np.maximum(result, padded[window - 1 - shift : len(padded) - shift], out=result)
    return result


def _moving_average(values: np.ndarray, length: int) -> np.ndarray:
    """A média dos `length` últimos valores (o atual incluso), com o começo repetindo o primeiro: o gate parte do estado
    em que o trecho está, e não de "fechado"."""
    if length <= 1:
        return values.astype(np.float64)
    padded = np.concatenate([np.repeat(values[:1], length - 1), values]).astype(np.float64)
    total = np.concatenate([[0.0], np.cumsum(padded)])
    return (total[length:] - total[:-length]) / length


def _dilate_forward(opened: np.ndarray, blocks: int) -> np.ndarray:
    """O estado aberto estendido `blocks` blocos para a frente (o `hold`)."""
    index = np.arange(len(opened), dtype=np.int32)
    last_open = np.maximum.accumulate(np.where(opened, index, -(2**30)).astype(np.int32))
    return (index - last_open) <= blocks


def _dilate_backward(opened: np.ndarray, blocks: int) -> np.ndarray:
    """O estado aberto estendido `blocks` blocos para trás (o lookahead do ataque)."""
    index = np.arange(len(opened), dtype=np.int32)
    next_open = np.minimum.accumulate(np.where(opened, index, 2**30).astype(np.int32)[::-1])[::-1]
    return (next_open - index) <= blocks


def gate_openness(
    levels_db: np.ndarray, threshold_db: float, attack_blocks: int, hold_blocks: int, release_blocks: int
) -> np.ndarray:
    """O quanto o gate está aberto em cada bloco, de 0 (fechado) a 1 (aberto), para UM canal de níveis. O estado alvo é
    "o som passa do limiar agora, ou passou há menos de `hold_blocks`, ou vai passar em menos de `attack_blocks`"; a
    abertura segue o alvo por uma rampa linear de `attack_blocks` ao subir e de `release_blocks` ao descer."""
    attack = max(attack_blocks, 1)
    release = max(release_blocks, 1)
    hold = max(hold_blocks, 0)
    loud = levels_db > threshold_db
    target = _dilate_forward(loud, hold) | _dilate_backward(loud, attack + ATTACK_MARGIN_BLOCKS)
    rising = _moving_average(target.astype(np.float64), attack)
    falling = _moving_average(target.astype(np.float64), release)
    # a subida usa a média curta do ataque e a descida a longa da liberação: com a liberação mais lenta que o ataque, o
    # maior dos dois acompanha a subida de um e a descida do outro (e o contrário com o menor)
    return np.maximum(rising, falling) if release >= attack else np.minimum(rising, falling)


def gate_gains(
    levels_db: np.ndarray,
    threshold_db: float,
    reduction_db: float,
    attack_ms: float,
    hold_ms: float,
    release_ms: float,
    link: bool,
) -> np.ndarray:
    """O ganho linear de cada bloco, forma `(blocos, canais)`: 1 com o gate aberto e `10^(-redução/20)` fechado. Com os
    canais ligados, o gate segue o mais alto e o ganho é o mesmo nos dois. Os tempos vêm em ms e o bloco é de 1 ms."""
    closed = 10.0 ** (-reduction_db / 20.0)
    if link:
        levels_db = levels_db.max(axis=1, keepdims=True)
    per_ms = 1.0 / (BLOCK_SECONDS * 1000.0)
    attack, hold, release = (round(value * per_ms) for value in (attack_ms, hold_ms, release_ms))
    columns = [
        closed + (1.0 - closed) * gate_openness(levels_db[:, k], threshold_db, attack, hold, release)
        for k in range(levels_db.shape[1])
    ]
    return np.stack(columns, axis=1).astype(np.float32)


def apply_gate(
    samples: np.ndarray,
    rate: int,
    *,
    threshold_db: float,
    reduction_db: float,
    attack_ms: float,
    hold_ms: float,
    release_ms: float,
    link: bool,
) -> np.ndarray:
    """O sinal `(amostras, canais)` depois do gate. O ganho de cada bloco é interpolado entre os centros dos blocos (sem
    degrau de ganho) e aplicado em pedaços de `APPLY_CHUNK_SECONDS`; a saída é a única cópia do tamanho do sinal."""
    size = block_size(rate)
    levels = detector_levels_db(samples, rate)
    result = np.array(samples, dtype=np.float32, copy=True)
    if len(levels) == 0:
        return result
    gains = gate_gains(levels, threshold_db, reduction_db, attack_ms, hold_ms, release_ms, link)
    centers = (np.arange(len(gains)) + 0.5) * size
    step = max(round(APPLY_CHUNK_SECONDS * rate), size)
    for first in range(0, len(result), step):
        last = min(first + step, len(result))
        positions = np.arange(first, last)
        for channel in range(result.shape[1]):
            column = gains[:, min(channel, gains.shape[1] - 1)]
            result[first:last, channel] *= np.interp(positions, centers, column).astype(np.float32)
    return result


def noise_level_db(samples: np.ndarray, rate: int) -> float:
    """O nível do ruído de um trecho em que ninguém fala, na régua do detector do gate: o percentil 95 dos níveis dos
    blocos de 1 ms, do canal mais alto. Num ruído estacionário o pico por bloco oscila, e o percentil deixa um estalo
    solto de fora. -120 dB num trecho mudo."""
    levels = detector_levels_db(samples, rate)
    if len(levels) == 0:
        return FLOOR_DB
    loudest = levels.max(axis=1)
    return float(max(np.percentile(loudest, NOISE_PERCENTILE), FLOOR_DB))


def suggested_threshold_db(noise_db: float) -> float:
    """O limiar que o Analisar ruído sugere: o nível do ruído mais `SUGGESTED_MARGIN_DB`. Fica dentro da faixa do campo
    (-96 a -6 dB)."""
    return float(min(max(noise_db + SUGGESTED_MARGIN_DB, -96.0), -6.0))
