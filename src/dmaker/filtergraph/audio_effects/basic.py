"""Construtores dos cinco efeitos básicos (as classes estão em `domain/audio_effects/basic.py`)."""

from __future__ import annotations

from ...domain.audio_effects.basic import Amplify, Invert, Normalize, Repeat, Reverse
from .registry import EffectRequest, register_builder

# Abaixo disto o trecho é silêncio para a normalização: dividir o alvo por um pico quase zero estouraria o ganho
# (e não há o que normalizar)
SILENT_PEAK = 1e-9
# `aloop` guarda as amostras que vai repetir; o limite alto garante que o item inteiro entre, e a memória só
# cresce até o tamanho real do item
LOOP_MAX_SAMPLES = 2_147_483_647


def _number(value: float) -> str:
    """Número para dentro de uma expressão do ffmpeg: entre parênteses, para o sinal negativo não colar no
    operador vizinho (`a--0.1`)."""
    return f"({value:.9f})"


@register_builder("amplify")
def build_amplify(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, Amplify)
    gain = effect.gain_db
    if effect.prevent_clipping and gain > 0 and request.measure is not None:
        # o ganho que leva o pico atual exatamente a 0 dBFS; um som mudo (-inf) não limita nada
        gain = min(gain, -request.measure.peak_db)
    return request.chain(f"volume={gain:.6f}dB")


@register_builder("normalize")
def build_normalize(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, Normalize)
    measure = request.measure
    if measure is None:  # sem medida (simulação) não há o que calcular
        return request.chain("anull")
    target = 10 ** (effect.peak_db / 20)
    peaks = [channel.peak_after_dc(effect.remove_dc) for channel in measure.channels]
    loudest = max(peaks, default=0.0)
    if loudest <= SILENT_PEAK:
        return request.chain("anull")
    # cada canal vai ao próprio pico, ou os dois ao pico do mais alto (o que preserva o balanço entre eles)
    gains = [
        target / peak if effect.stereo_independent and peak > SILENT_PEAK else target / loudest
        for peak in peaks
    ]
    if not effect.remove_dc and not effect.stereo_independent:
        return request.chain(f"volume={gains[0]:.9f}")
    shifts = [channel.dc_offset if effect.remove_dc else 0.0 for channel in measure.channels]
    expressions = "|".join(
        f"(val({k})-{_number(shift)})*{_number(gain)}"
        for k, (shift, gain) in enumerate(zip(shifts, gains, strict=True))
    )
    return request.chain(f"aeval=exprs={expressions}:channel_layout=stereo", "aformat=sample_fmts=fltp")


@register_builder("invert")
def build_invert(request: EffectRequest) -> list[str]:
    assert isinstance(request.effect, Invert)
    # multiplicar por -1 é exato em ponto flutuante: inverter duas vezes devolve a mesma amostra
    return request.chain("volume=-1")


@register_builder("reverse")
def build_reverse(request: EffectRequest) -> list[str]:
    assert isinstance(request.effect, Reverse)
    return request.chain("areverse")


@register_builder("repeat")
def build_repeat(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, Repeat)
    # `loop` conta as passagens além da primeira
    return request.chain(f"aloop=loop={effect.times - 1}:size={LOOP_MAX_SAMPLES}")
