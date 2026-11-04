"""Construtores dos efeitos de volume e dinâmica (as classes estão em `domain/audio_effects/dynamics.py`).

Como cada um foi decidido:

- **Compressor** sobre o `acompressor`. O filtro conta tudo em escala linear, então os dB do catálogo viram fator:
  limiar `10^(dB/20)`, ganho de compensação `10^(dB/20)` (de 1 a 64 é de 0 a 36 dB) e joelho `10^(dB/20)` (de 1 a 8 é de
  0 a 18 dB; o joelho do filtro é um fator, a largura da transição em volta do limiar é `20·log10(fator)` dB). O
  lookahead é um atraso compensado: o detector (`sidechaincompress`) lê a cópia SEM atraso e o sinal que recebe o ganho
  vai atrasado, então o ganho já baixou quando o pico chega; depois o atraso é cortado e o tamanho do item não muda.
- **Limitador** sobre o `alimiter`, sempre com `level=0` (o padrão dele normaliza o volume sozinho). O critério é o pico
  VERDADEIRO (dBTP): o limitador roda a 4x a taxa (192 kHz), onde um pico entre duas amostras já é uma amostra, e a saída
  volta a 48 kHz. A volta pode passar o teto por uma fração de dB (a reconstrução da onda), por isso o teto interno é
  `TRUE_PEAK_MARGIN_DB` mais baixo que o pedido, valor medido e não chutado (ver o comentário da constante).
- **Normalização de loudness** é um `volume` com o ganho calculado da medida do sinal que entra (LUFS integrado pelo
  `ebur128` ou RMS pelo `astats`), só no intervalo do efeito, sem limitar o pico.
- **Noise Gate** é uma função sobre as amostras (`media/gate.py`): o `agate` não tem `hold` e não abre antes do som.
"""

from __future__ import annotations

import math

import numpy as np

from ...domain.audio_effects.dynamics import Compressor, Limiter, LoudnessNormalize, NoiseGate
from ...media.gate import apply_gate
from .measure import Measure
from .registry import EffectRequest, SampleRequest, register_builder, register_sample_builder

# O silêncio depois do programa, nos dois lados do `sidechaincompress`: ele encerra a saída quando UMA das entradas acaba
# e descarta o que esperava na outra (a corrida que o DMK-47 achou no ducking). Com as duas entradas mais longas que o
# item, o compressor nunca vê o fim; o `atrim` final devolve o tamanho exato do item.
SIDECHAIN_TAIL_SECONDS = 1.0
# O Limitador a 4x ainda deixa o pico verdadeiro passar do teto por uma fração de dB depois de voltar a 48 kHz (a
# reconstrução da onda entre as amostras). Medido com o ebur128 em seis sinais (fala alta, senos de 11 e 12 kHz, onda
# quadrada, rajadas e ruído branco com 12 dB de pico): sem margem, o ruído branco passava 0,4 dB do teto e o seno de
# 11 kHz 0,2 dB; com 0,5 dB de margem nenhum passou. O teto interno fica esta margem abaixo do pedido.
TRUE_PEAK_MARGIN_DB = 0.5
OVERSAMPLE_RATE = 192_000  # 4x 48 kHz: o mesmo fator com que o ebur128 mede o pico verdadeiro
# O limitador suave começa a abaixar o som este tanto antes do teto, com um compressor de razão alta e joelho largo
SOFT_HEADROOM_DB = 4.0
SOFT_KNEE_DB = 6.0
SOFT_RATIO = 20.0
# O alimiter pede o ataque em ms entre 0,1 e 80; o compressor suave segue o mesmo lookahead do limitador, com este piso
# para o ataque do detector de pico nunca ser mais rápido que um ciclo de grave
SOFT_MIN_ATTACK_MS = 1.0
# O fator linear do dual-mono: um arquivo mono medido como se tocasse nos dois lados mede 3,01 LU a mais (dois canais
# de mesma potência), o que a mistura já faz ao levá-lo para os dois lados
DUAL_MONO_LU = 10.0 * math.log10(2.0)


def to_linear(db: float) -> float:
    """Ganho em dB como fator de amplitude: `10^(dB/20)`, a escala dos filtros de dinâmica do ffmpeg."""
    return 10.0 ** (db / 20.0)


def _compressor_options(effect: Compressor) -> str:
    return (
        f"threshold={to_linear(effect.threshold_db):.9f}:ratio={effect.ratio:g}:knee={to_linear(effect.knee_db):.6f}"
        f":attack={effect.attack_ms:g}:release={effect.release_ms:g}:makeup={to_linear(effect.makeup_db):.6f}"
        ":link=maximum:detection=peak"
    )


@register_builder("compressor")
def build_compressor(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, Compressor)
    options = _compressor_options(effect)
    delay = round(effect.lookahead_ms / 1000.0 * request.sample_rate)
    if delay <= 0:
        return request.chain(f"acompressor={options}")
    # a cópia sem atraso detecta, a atrasada recebe o ganho; as duas viram mais longas que o item (o silêncio depois do
    # programa) e o `atrim` devolve o tamanho exato, já sem o atraso
    size = request.samples
    padded = size + delay + round(SIDECHAIN_TAIL_SECONDS * request.sample_rate)
    main, detect = request.label("m"), request.label("d")
    delayed, listened = request.label("md"), request.label("dd")
    return [
        f"{request.source}asplit=2{main}{detect}",
        f"{main}adelay={delay}S:all=1,apad=whole_len={padded}{delayed}",
        f"{detect}apad=whole_len={padded}{listened}",
        f"{delayed}{listened}sidechaincompress={options},atrim=start_sample={delay}:end_sample={delay + size},"
        f"asetpts=PTS-STARTPTS{request.out}",
    ]


@register_builder("limiter")
def build_limiter(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, Limiter)
    filters: list[str] = []
    if effect.input_gain_db > 0:
        filters.append(f"volume={effect.input_gain_db:.6f}dB")
    ceiling = effect.ceiling_db - TRUE_PEAK_MARGIN_DB
    filters.append(f"aresample={OVERSAMPLE_RATE}")
    if effect.limit_type == "soft":
        # começa a abaixar alguns dB antes do teto; o limitador logo depois garante o teto
        attack = max(effect.lookahead_ms, SOFT_MIN_ATTACK_MS)
        filters.append(
            f"acompressor=threshold={to_linear(ceiling - SOFT_HEADROOM_DB):.9f}:ratio={SOFT_RATIO:g}"
            f":knee={to_linear(SOFT_KNEE_DB):.6f}:attack={attack:g}:release={effect.release_ms:g}"
            ":link=maximum:detection=peak"
        )
    filters.append(
        f"alimiter=limit={to_linear(ceiling):.9f}:attack={effect.lookahead_ms:g}:release={effect.release_ms:g}"
        ":level=0:latency=1"
    )
    filters.append(f"aresample={request.sample_rate}")
    filters.append(f"aformat=sample_fmts=fltp:sample_rates={request.sample_rate}:channel_layouts=stereo")
    return request.chain(*filters)


def loudness_gain_db(effect: LoudnessNormalize, measure: Measure | None) -> float | None:
    """O ganho, em dB, que leva o sinal medido ao alvo; None quando não há medida (simulação, ou um sinal sem som, que
    não tem o que normalizar). No modo `lufs` com o dual-mono desligado, um arquivo mono mede 3 LU abaixo do que a mistura
    toca (o mesmo som nos dois lados), então o ganho sobe esses 3 dB."""
    if measure is None:
        return None
    if effect.mode == "lufs":
        if measure.loudness is None:
            return None
        gain = effect.target_db - measure.loudness
        if measure.mono_source and not effect.dual_mono:
            gain += DUAL_MONO_LU
        return gain
    if measure.rms_db is None:
        return None
    return effect.target_db - measure.rms_db


@register_builder("loudness_normalize")
def build_loudness_normalize(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, LoudnessNormalize)
    gain = loudness_gain_db(effect, request.measure)
    if gain is None or abs(gain) < 1e-9:
        return request.chain("anull")
    return request.chain(f"volume={gain:.6f}dB")


@register_sample_builder("noise_gate")
def build_noise_gate(request: SampleRequest) -> np.ndarray:
    effect = request.effect
    assert isinstance(effect, NoiseGate)
    return apply_gate(
        request.samples,
        request.sample_rate,
        threshold_db=effect.threshold_db,
        reduction_db=effect.reduction_db,
        attack_ms=effect.attack_ms,
        hold_ms=effect.hold_ms,
        release_ms=effect.release_ms,
        link=effect.stereo_link,
    )
