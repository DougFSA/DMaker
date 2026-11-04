"""Construtores do Atraso, do Eco e do Reverb (as classes estão em `domain/audio_effects/delay_reverb.py`).

- **Atraso:** o som e cada repetição são ramos do grafo (`asplit`), cada um com o `adelay`, o ganho e, se o tom muda, o
  `rubberband`; o `amix` soma tudo sem normalizar.
- **Eco:** é um pente com realimentação, `y[n] = x[n] + d y[n-D]`. A resposta dele é a soma geométrica de `d^k` vezes o
  sinal atrasado `k` vezes, e essa soma se faz em poucos estágios de dobra: o estágio `j` soma ao sinal uma cópia dele
  mesmo atrasada `2^j` atrasos e com ganho `d^(2^j)`. Dez estágios cobrem 1023 repetições, e o resultado é exato.
- **Reverb:** a resposta ao impulso (`media/reverb.py`) é lida do cache pelo `amovie` e aplicada pelo `afir`, que faz a
  convolução em blocos com FFT. O som entra somado em mono (como no Freeverb) e sai em estéreo, e o seco passa à parte.
"""

from __future__ import annotations

import math

from ...domain.audio_effects.delay_reverb import Delay, Echo, Reverb
from ...domain.echo import doubling_blocks, doubling_stages, echo_repeats, echo_tail_seconds
from ...media.reverb import impulse_path
from ..common import ffq
from .pitch_tempo import rubberband, with_quiet_tail
from .registry import EffectRequest, register_builder

# Um tom que muda menos que isto (em semitons) não precisa do `rubberband`
PITCH_EPSILON = 1e-6
# O Reverb entra em mono: a soma dos dois canais com metade de cada um, que mantém o nível de uma fonte central
MONO_SUM = "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1"
# As opções do `afir` que fazem dele uma convolução exata: sem ganho automático nem normalização da resposta (a resposta já
# vem normalizada em energia, em `media/reverb.py`), e `maxir` acima do maior arquivo de resposta (uns 11 s)
AFIR_OPTIONS = "gtype=none:irnorm=-1:irgain=1:maxir=30"


def _volume(db: float) -> str:
    return f"volume={db:.6f}dB"


@register_builder("delay")
def build_delay(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, Delay)
    rate, total = request.sample_rate, request.samples
    echoes = effect.repetitions()
    count = len(echoes) + 1
    branches = [request.label(f"b{k}") for k in range(count)]
    outputs = [request.label(f"o{k}") for k in range(count)]
    lines = [f"{request.source}asplit={count}" + "".join(branches)]
    lines.append(f"{branches[0]}{_volume(effect.dry_db)}{outputs[0]}")
    for k, echo in enumerate(echoes, start=1):
        chain: list[str] = []
        if abs(echo.semitones) > PITCH_EPSILON:
            # o tom muda antes do atraso; o `rubberband` mantém a duração, e o silêncio e o corte exato evitam o degrau do fim
            chain += with_quiet_tail(rubberband(f"pitch={2.0 ** (echo.semitones / 12.0):.9f}", False), total)
        chain += [f"adelay={max(round(echo.at * rate), 1)}S:all=1", _volume(echo.gain_db)]
        lines.append(f"{branches[k]}{','.join(chain)}{outputs[k]}")
    length = total + (round(echoes[-1].at * rate) if effect.extend_tail else 0)
    mix = f"amix=inputs={count}:normalize=0:duration=longest:dropout_transition=0,atrim=end_sample={length}"
    lines.append("".join(outputs) + f"{mix}{request.out}")
    return lines


def echo_stage_count(effect: Echo, samples: int, rate: int) -> int:
    """Quantas repetições do eco o grafo precisa: as até -60 dB, limitadas ao que cabe no item (ou na cauda, se o item
    estica). Zero quando o decaimento é 0."""
    repeats = echo_repeats(effect.decay)
    if repeats == 0:
        return 0
    if effect.extend_tail:
        return max(
            int(echo_tail_seconds(effect.delay_seconds, effect.decay) / effect.delay_seconds + 1e-9), 1
        )
    fits = math.ceil(samples / max(round(effect.delay_seconds * rate), 1))
    return max(min(repeats, fits) if repeats is not None else fits, 1)


@register_builder("echo")
def build_echo(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, Echo)
    rate, total = request.sample_rate, request.samples
    repeats = echo_stage_count(effect, total, rate)
    if repeats == 0:
        return request.chain("anull")
    base = max(round(effect.delay_seconds * rate), 1)
    length = total + (
        round(echo_tail_seconds(effect.delay_seconds, effect.decay) * rate) if effect.extend_tail else 0
    )
    stages = doubling_stages(repeats)
    blocks = dict(doubling_blocks(repeats))  # estágio -> deslocamento, só dos que entram na soma final
    lines: list[str] = []
    stage_labels = {0: request.source}
    for stage in range(stages + 1):
        current = stage_labels[stage]
        uses = []  # o que sai deste estágio: a dobra para o seguinte (duas vezes: o som e a cópia) e a soma final
        if stage < stages:
            uses += [request.label(f"d{stage}"), request.label(f"c{stage}")]
        if stage in blocks:
            uses.append(request.label(f"f{stage}"))
        if len(uses) > 1:
            lines.append(f"{current}asplit={len(uses)}" + "".join(uses))
        else:
            uses = [current]
        if stage < stages:
            shifted = request.label(f"s{stage}")
            lines.append(
                f"{uses[1]}adelay={base * 2**stage}S:all=1,volume={effect.decay ** (2**stage):.12g}{shifted}"
            )
            following = request.label(f"e{stage + 1}")
            lines.append(
                f"{uses[0]}{shifted}amix=inputs=2:normalize=0:duration=longest:dropout_transition=0{following}"
            )
            stage_labels[stage + 1] = following
        if stage in blocks:
            stage_labels[f"final{stage}"] = uses[-1]
    finals = []
    for stage, offset in blocks.items():
        label = stage_labels[f"final{stage}"]
        if offset == 0:
            finals.append(label)
            continue
        placed = request.label(f"p{stage}")
        lines.append(f"{label}adelay={base * offset}S:all=1,volume={effect.decay**offset:.12g}{placed}")
        finals.append(placed)
    trim = f"atrim=end_sample={length}"
    if len(finals) == 1:
        lines.append(f"{finals[0]}{trim}{request.out}")
    else:
        mix = f"amix=inputs={len(finals)}:normalize=0:duration=longest:dropout_transition=0,{trim}"
        lines.append("".join(finals) + f"{mix}{request.out}")
    return lines


@register_builder("reverb")
def build_reverb(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, Reverb)
    settings = effect.impulse_settings()
    rate, total = request.sample_rate, request.samples
    length = total + (math.ceil(settings.tail_seconds() * rate) if effect.extend_tail else 0)
    # a cauda: o item é completado com silêncio até o tamanho final, senão o `afir` cortaria o reverb no fim do item
    pad = [f"apad=whole_len={length}"] if length > total else []
    impulse, wet_in, mono, wet = (request.label(name) for name in ("ir", "wi", "mono", "wet"))
    source_ir = f"amovie={ffq(impulse_path(settings, rate))}{impulse}"
    convolve = f"{mono}{impulse}afir={AFIR_OPTIONS}"
    if effect.wet_only:
        lines = [f"{request.source}{','.join([*pad, MONO_SUM])}{mono}", source_ir]
        lines.append(f"{convolve},atrim=end_sample={length}{request.out}")
        return lines
    dry = request.label("dry")
    lines = [f"{request.source}{','.join([*pad, 'asplit=2'])}{dry}{wet_in}", source_ir]
    lines.append(f"{wet_in}{MONO_SUM}{mono}")
    lines.append(f"{convolve}{wet}")
    mix = f"amix=inputs=2:normalize=0:duration=longest:dropout_transition=0,atrim=end_sample={length}"
    dry_out = request.label("dryv")
    lines.append(f"{dry}{_volume(effect.dry_db)}{dry_out}")
    lines.append(f"{dry_out}{wet}{mix}{request.out}")
    return lines
