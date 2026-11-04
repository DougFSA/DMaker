"""O efeito de amostras no sinal todo ou só no intervalo dele, com a mesma emenda de 10 ms dos efeitos de filtro.

É o par numpy de `chain.apply_effect`: o construtor registrado (`register_sample_builder`) só enxerga o trecho do
intervalo, com o tempo zerado, e aqui se cuida do resto. Funções puras sobre arrays."""

from __future__ import annotations

import numpy as np

from .chain import SEAM_SECONDS
from .registry import SampleRequest, build_samples


def apply_sample_effect(request: SampleRequest) -> np.ndarray:
    """O sinal `(amostras, canais)` depois do efeito. Sem intervalo (ou cobrindo o item todo) o construtor recebe o
    sinal inteiro; com intervalo, só o trecho dele, e o resultado volta para o lugar com uma rampa linear de 10 ms nas
    bordas, em que o som seco sai enquanto o processado entra (a soma dos pesos é 1, então não há degrau). Um efeito
    que muda a duração é emendado por concatenação, sem rampa. O Reparar e os outros que leem o próprio intervalo
    (`owns_interval`) recebem o sinal inteiro e os `start`/`end` do efeito."""
    effect = request.effect
    samples = request.samples
    if effect.owns_interval:
        return build_samples(request)
    total = len(samples)
    span = effect.span(total / request.sample_rate)
    if span is None:
        return build_samples(request)
    first, last = round(span[0] * request.sample_rate), round(span[1] * request.sample_rate)
    first, last = max(first, 0), min(last, total)
    if first <= 0 and last >= total:
        return build_samples(request)
    if last - first < 2:  # nada a processar: um intervalo vazio deixa o som como está
        return samples
    inner = SampleRequest(effect, samples[first:last], request.sample_rate, request.measure)
    wet = build_samples(inner)
    if effect.alters_duration():
        return np.concatenate([samples[:first], wet, samples[last:]])
    return _crossfaded(samples, wet, first, last, round(SEAM_SECONDS * request.sample_rate))


def _crossfaded(dry: np.ndarray, wet: np.ndarray, first: int, last: int, seam: int) -> np.ndarray:
    """O processado no lugar do seco entre `first` e `last`, com rampa de `seam` amostras em cada borda que tem
    vizinho. Quando o intervalo começa em 0 ou termina no fim, aquela borda não leva rampa."""
    ramp = min(seam, (last - first) // 2)
    weight = np.ones(last - first)
    if first > 0 and ramp:
        weight[:ramp] = np.linspace(0.0, 1.0, ramp, endpoint=False)
    if last < len(dry) and ramp:
        weight[-ramp:] = np.linspace(1.0, 0.0, ramp, endpoint=False)
    result = np.array(dry, copy=True)
    shape = (-1,) + (1,) * (dry.ndim - 1)
    result[first:last] = dry[first:last] * (1.0 - weight).reshape(shape) + wet * weight.reshape(shape)
    return result
