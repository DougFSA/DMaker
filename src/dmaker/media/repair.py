"""Reparo de um trecho curtíssimo de áudio por predição linear: refaz o estalo com a onda de antes e de depois dele.

Funções puras sobre amostras (numpy). Um modelo autorregressivo, ajustado ao som que vem antes e depois do trecho,
diz o quanto cada amostra se parece com as que a antecedem. As amostras do trecho são então as que menos quebram essa
regra, vistas dos dois lados ao mesmo tempo (a interpolação autorregressiva clássica): um sistema linear pequeno, de
tantas incógnitas quantas amostras há no trecho. Para um trecho de até 128 amostras (2,7 ms) de voz ou música, em que
a onda é quase periódica, isso refaz a curva com erro muito menor que o de uma reta entre as pontas, e as pontas
encontram o som real sem degrau, porque a regra vale também através delas.
"""

from __future__ import annotations

import numpy as np

AR_ORDER = 32  # coeficientes do modelo: o bastante para os harmônicos de uma voz, curto para ajustar rápido
CONTEXT_SAMPLES = (
    768  # amostras de cada lado que alimentam o ajuste (16 ms a 48 kHz, vários períodos de uma voz)
)
MIN_CONTEXT = 8  # com menos amostras que isso de um lado, esse lado não ensina nada ao modelo
REGULARIZATION = 1e-9  # a diagonal do ajuste cresce um tico: um contexto quase mudo não vira sistema singular


def repair_interval(samples: np.ndarray, first: int, last: int) -> np.ndarray:
    """O sinal `(amostras, canais)` com as amostras `first` a `last` (exclusivo) refeitas. Cada canal é consertado
    sozinho. Uma cópia: a entrada não muda."""
    out = np.array(samples, copy=True)
    first, last = max(first, 0), min(last, len(out))
    if last - first < 1:
        return out
    # só o som em volta do trecho entra na conta (em 64 bits); o resto do sinal é copiado como veio
    low, high = max(first - CONTEXT_SAMPLES, 0), min(last + CONTEXT_SAMPLES, len(out))
    window = np.asarray(out[low:high], dtype=np.float64)
    squeeze = window.ndim == 1
    if squeeze:
        window = window[:, None]
    for channel in range(window.shape[1]):
        window[first - low : last - low, channel] = _repair_channel(
            window[:, channel], first - low, last - low
        )
    out[first:last] = (
        window[first - low : last - low, 0] if squeeze else window[first - low : last - low]
    ).astype(out.dtype)
    return out


def _repair_channel(channel: np.ndarray, first: int, last: int) -> np.ndarray:
    """As amostras novas de `first` a `last` de um canal."""
    length = last - first
    before = channel[max(0, first - CONTEXT_SAMPLES) : first]
    after = channel[last : last + CONTEXT_SAMPLES]
    usable = [side for side in (before, after) if len(side) >= MIN_CONTEXT]
    if not usable:
        return channel[first:last]  # sem som dos dois lados não há como prever: o trecho fica como está
    mean = float(
        np.concatenate(usable).mean()
    )  # o modelo vale para a onda sem o deslocamento DC; ele volta no fim
    order = min(AR_ORDER, min(len(side) for side in usable) // 3)
    coefficients = _autoregression([side - mean for side in usable], order)
    if len(before) >= order and len(after) >= order:
        return _interpolate(before[-order:] - mean, after[:order] - mean, length, coefficients) + mean
    if len(before) >= MIN_CONTEXT:
        return _extrapolate(before[-order:] - mean, length, coefficients) + mean
    return _extrapolate(after[:order][::-1] - mean, length, coefficients)[::-1] + mean


def _interpolate(head: np.ndarray, tail: np.ndarray, length: int, coefficients: np.ndarray) -> np.ndarray:
    """As `length` amostras entre `head` e `tail` que minimizam o erro de predição de todas as equações que as
    tocam: `head` são as `order` amostras que as antecedem, `tail` as que vêm depois."""
    order = len(coefficients)
    equations = length + order  # da primeira amostra do trecho até a última que ainda depende dele
    columns = length + 2 * order
    system = np.zeros((equations, columns))
    for k, coefficient in enumerate(coefficients, start=1):
        system[np.arange(equations), order + np.arange(equations) - k] = -coefficient
    system[np.arange(equations), order + np.arange(equations)] = 1.0
    unknown = slice(order, order + length)
    known = np.concatenate([np.arange(order), np.arange(order + length, columns)])
    knowns = np.concatenate([head, tail])
    solution, *_ = np.linalg.lstsq(system[:, unknown], -system[:, known] @ knowns, rcond=None)
    return solution


def _extrapolate(context: np.ndarray, length: int, coefficients: np.ndarray) -> np.ndarray:
    """As próximas `length` amostras depois de `context`, que o modelo prevê uma a uma (para um trecho na ponta do
    arquivo, com som só de um lado)."""
    order = len(coefficients)
    history = list(context[-order:])
    predicted = np.empty(length)
    for i in range(length):
        value = float(np.dot(coefficients, history[::-1][:order]))
        predicted[i] = value
        history.append(value)
    return predicted


def _autoregression(contexts: list[np.ndarray], order: int) -> np.ndarray:
    """Os coeficientes `a` tais que `x[n] ≈ a[0]*x[n-1] + a[1]*x[n-2] + ...`, pelo ajuste de mínimos quadrados da
    própria predição sobre os contextos (o método da covariância). Cada contexto já vem sem o deslocamento DC.

    Não é Yule-Walker: a autocorrelação de um trecho curto de senoides sai enviesada, amortece os polos e a previsão
    morre em poucas dezenas de amostras. O ajuste direto não tem esse viés e segue a onda por todo o trecho."""
    if order == 0 or sum(float(np.dot(side, side)) for side in contexts) < 1e-18:
        return np.zeros(order)  # contexto mudo: a previsão repete o que há
    lag_rows, targets = [], []
    for side in contexts:
        if len(side) > order:
            # linha i: as `order` amostras que antecedem side[order + i], da mais recente para a mais antiga
            lag_rows.append(np.lib.stride_tricks.sliding_window_view(side, order)[: len(side) - order, ::-1])
            targets.append(side[order:])
    lags, target = np.concatenate(lag_rows), np.concatenate(targets)
    gram = lags.T @ lags
    gram[np.diag_indices(order)] += REGULARIZATION * float(np.trace(gram)) / order
    try:
        return np.linalg.solve(gram, lags.T @ target)
    except np.linalg.LinAlgError:
        return np.zeros(order)
