"""Construtores da Distorção, do Phaser, do Tremolo, do Wahwah e do Vocoder (as classes estão em
`domain/audio_effects/distortion_modulation.py`).

Quais viram filtro do ffmpeg e quais viram conta em numpy foi decidido pelo controle que o Audacity dá:

- **Tremolo:** `volume` com o LFO por expressão, reavaliada a cada 64 amostras (1,3 ms), como o Envelope. O `tremolo` do
  ffmpeg só tem onda senoidal e a fase fixa em zero; aqui há as cinco ondas e a fase inicial.
- **Distorção:** curvas de transferência por elemento em numpy (`media/distortion.py`); o `asoftclip` do ffmpeg cobre só
  alguns tipos e não tem o limiar, a repetição nem o filtro de corrente contínua do Audacity.
- **Phaser e Wahwah:** o `aphaser` tem uma só linha de atraso e o LFO no máximo a 2 Hz (o Audacity vai a 4), sem estágios nem
  fase inicial, e o Wahwah precisaria de um comando a cada quadro por cima de um passa-banda. Os dois são filtros de resposta
  conhecida em cada instante, então se aplicam quadro a quadro no domínio da frequência (`media/stft_filter.py`).
- **Vocoder:** o filtro por canais de `media/vocoder.py`, com a portadora em `SampleRequest.side`.
"""

from __future__ import annotations

import numpy as np

from ...domain.audio_effects.distortion_modulation import Distortion, Phaser, Tremolo, Vocoder, Wahwah
from ...media.distortion import DistortionSettings, distort
from ...media.modulation import phaser_response, wah_response
from ...media.stft_filter import apply_response
from ...media.vocoder import vocode
from .editing import ENVELOPE_FRAME_SAMPLES
from .registry import EffectRequest, SampleRequest, register_builder, register_sample_builder

# A expressão do LFO de cada onda, de 0 a 1, em função de `c = frequência * t + fase` (em ciclos)
TREMOLO_WAVES = {
    "sine": "(1+sin(2*PI*({c})))/2",
    "triangle": "1-abs(2*mod({c},1)-1)",
    "sawtooth": "mod({c},1)",
    "inverse_sawtooth": "1-mod({c},1)",
    "square": "if(lt(mod({c},1),0.5),1,0)",
}


def tremolo_gain_expression(
    waveform: str, frequency_hz: float, phase_degrees: float, depth_percent: float
) -> str:
    """O ganho linear do Tremolo como expressão do ffmpeg em `t` (segundos do item): `1 - profundidade (1 - LFO)`, de
    `1 - profundidade` no ponto baixo a 1 no alto. Função pura."""
    cycles = f"{frequency_hz:.9g}*t+{phase_degrees / 360.0:.9g}"
    wave = TREMOLO_WAVES[waveform].format(c=cycles)
    return f"1-{depth_percent / 100.0:.9g}*(1-({wave}))"


@register_builder("tremolo")
def build_tremolo(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, Tremolo)
    if effect.depth <= 0.0:
        return request.chain("anull")
    expression = tremolo_gain_expression(
        effect.waveform, effect.frequency_hz, effect.phase_degrees, effect.depth
    )
    return request.chain(
        f"asetnsamples=n={ENVELOPE_FRAME_SAMPLES}:p=0",
        f"volume='{expression}':eval=frame:precision=float",
    )


def _gain(db: float) -> np.float32:
    return np.float32(10.0 ** (db / 20.0))


@register_sample_builder("distortion")
def build_distortion(request: SampleRequest) -> np.ndarray:
    effect = request.effect
    assert isinstance(effect, Distortion)
    settings = DistortionSettings(
        effect.kind,
        effect.drive_db,
        effect.threshold_db,
        effect.amount,
        effect.repeats,
        effect.bits,
        effect.downsample,
        effect.dc_filter,
        effect.hiss_db,
        effect.output_db,
    )
    return distort(request.samples, settings, request.sample_rate)


@register_sample_builder("phaser")
def build_phaser(request: SampleRequest) -> np.ndarray:
    effect = request.effect
    assert isinstance(effect, Phaser)

    def response(times: np.ndarray) -> np.ndarray:
        return phaser_response(
            times,
            request.sample_rate,
            effect.stages,
            effect.dry_wet,
            effect.lfo_hz,
            effect.phase_degrees,
            effect.depth,
            effect.feedback_percent,
        )

    return apply_response(request.samples, request.sample_rate, response) * _gain(effect.output_db)


@register_sample_builder("wahwah")
def build_wahwah(request: SampleRequest) -> np.ndarray:
    effect = request.effect
    assert isinstance(effect, Wahwah)

    def response(times: np.ndarray) -> np.ndarray:
        return wah_response(
            times,
            request.sample_rate,
            effect.lfo_hz,
            effect.phase_degrees,
            effect.depth / 100.0,
            effect.resonance,
            effect.offset / 100.0,
        )

    return apply_response(request.samples, request.sample_rate, response) * _gain(effect.output_db)


@register_sample_builder("vocoder")
def build_vocoder(request: SampleRequest) -> np.ndarray:
    effect = request.effect
    assert isinstance(effect, Vocoder)
    if request.side is None:
        raise ValueError("o Vocoder precisa da portadora (request.side)")
    shaped = vocode(
        request.samples,
        request.side,
        request.sample_rate,
        effect.bands,
        effect.distance,
        effect.original_level / 100.0,
        effect.noise_level / 100.0,
        effect.radar_level / 100.0,
        effect.radar_hz,
    )
    return shaped * _gain(effect.output_db)
