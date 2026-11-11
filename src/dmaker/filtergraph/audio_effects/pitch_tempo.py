"""Construtores dos efeitos de tempo e afinação: Mudar Tom, Mudar Velocidade e Tom, Mudar Andamento, Esticar Gradualmente
e Paulstretch (as classes estão em `domain/audio_effects/pitch_tempo.py` e as contas, puras, em `domain/pitch_tempo.py`).

O `rubberband` faz o tom e o andamento independentes; o `asetrate` com o `aresample` faz o "vinil", em que os dois andam
juntos; o Paulstretch é uma função sobre as amostras (`media/paulstretch.py`).
"""

from __future__ import annotations

import numpy as np

from ...domain.audio_effects.pitch_tempo import (
    ChangePitch,
    ChangeSpeed,
    ChangeTempo,
    Paulstretch,
    SlidingStretch,
    paulstretch_refusal,
)
from ...domain.pitch_tempo import (
    SlidingStep,
    percent_ratio,
    resample_rate,
    sliding_duration,
    sliding_steps,
)
from ...media.paulstretch import paulstretch, stretched_length
from .registry import EffectRequest, SampleRequest, register_builder, register_sample_builder

# As opções do `rubberband` em alta qualidade, todas medidas num tom puro de 440 Hz:
# - `pitchq=quality`: a conversão de tom de maior qualidade do motor.
# - `transients=mixed`: o padrão `crisp` reinicia a fase a cada transiente e desafinava o tom puro em até 2,5 Hz (de
#   493,88 Hz saía 494,68 Hz); com `mixed` e `smooth` a frequência sai exata. `mixed` guarda o ataque da voz melhor.
# - `channels=together`: os dois canais são processados juntos, para a imagem estéreo não oscilar entre eles.
RUBBERBAND_QUALITY = "transients=mixed:channels=together"
PITCH_QUALITY = "pitchq=quality"
# No Esticar Gradualmente o tom muda o tempo todo, e o modo `quality` perde nível (até -6 dB num tom puro) quando a razão
# muda durante o processamento; o `consistency` é o modo do motor para tom que muda com frequência e manteve o nível
# (0,063 de RMS do começo ao fim, como a entrada) com a frequência igualmente exata.
SLIDING_PITCH_QUALITY = "pitchq=consistency"
FORMANT_PRESERVED = "formant=preserved"
# O `asendcmd` só muda o `rubberband` na fronteira de um quadro: com quadros de 10 ms (480 amostras a 48 kHz) o degrau
# atrasa no máximo 10 ms (com o quadro padrão de 1024 amostras, 21 ms)
SLIDING_FRAME_SAMPLES = 480
# O motor aplica o comando antes do que o `asendcmd` marca (ele já consumiu parte do sinal quando o comando chega), e a saída
# sai mais longa que a integral do andamento em até 115 ms. Atrasar os comandos em 60 ms deixou o erro, em dez casos
# medidos (andamento de 0,25 a 2, tom de -12 a +12, de 2 a 10 s), a no máximo 34 ms; o resto o corte exato abaixo desfaz.
SLIDING_COMMAND_DELAY = 0.06
# O silêncio que vai atrás do sinal antes do `rubberband` (ver `with_quiet_tail`): bem acima da janela de análise do motor
# (alguns milissegundos a dezenas deles) e curto o bastante para não pesar no tempo de processamento
RUBBERBAND_TAIL_PAD = 0.2
# Menos que isto (2 amostras) não é um trecho de som: não há o que esticar
MIN_SAMPLES = 2
UNCHANGED = 1e-9


def _is_unchanged(ratio: float) -> bool:
    return abs(ratio - 1.0) < UNCHANGED


@register_builder("change_pitch")
def build_change_pitch(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, ChangePitch)
    ratio = effect.pitch_ratio()
    if _is_unchanged(ratio):
        return request.chain("anull")
    return request.chain(
        *with_quiet_tail(rubberband(f"pitch={ratio:.9f}", effect.preserve_formants), request.samples)
    )


@register_builder("change_speed")
def build_change_speed(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, ChangeSpeed)
    rate = resample_rate(effect.requested_ratio(), request.sample_rate)
    if rate == request.sample_rate:
        return request.chain("anull")
    # O disco gira mais depressa ou mais devagar: o `asetrate` troca só a taxa declarada (o som toca na velocidade nova,
    # com o tom junto) e o `aresample` devolve o sinal à taxa da mistura. O `asetrate` só aceita taxa inteira, e a duração
    # de saída (`ChangeSpeed.output_duration`) usa essa mesma taxa.
    return request.chain(f"asetrate={rate}", f"aresample={request.sample_rate}")


@register_builder("change_tempo")
def build_change_tempo(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, ChangeTempo)
    ratio = effect.tempo_ratio()
    if _is_unchanged(ratio):
        return request.chain("anull")
    return request.chain(*with_quiet_tail(rubberband(f"tempo={ratio:.9f}", False), request.samples / ratio))


def with_quiet_tail(stretcher: str, output_samples: float) -> list[str]:
    """O `rubberband` entre um silêncio e um corte exato. Ao fim do arquivo o motor despeja o que guardava e deixa um
    degrau de até 4 vezes a variação normal do tom nos últimos milissegundos (medido: 0,036 contra 0,007 num tom puro).
    Com 200 ms de silêncio na entrada o degrau cai dentro do silêncio, e o `atrim` devolve a duração exata da conta."""
    return [
        f"apad=pad_dur={RUBBERBAND_TAIL_PAD}",
        stretcher,
        f"atrim=end_sample={max(round(output_samples), 1)}",
    ]


def rubberband(
    setting: str, preserve_formants: bool, name: str = "", pitch_quality: str = PITCH_QUALITY
) -> str:
    """O filtro `rubberband` com o ajuste (`tempo=...`, `pitch=...`) e as opções de qualidade. `name` o rotula quando um
    `asendcmd` vai comandá-lo."""
    options = f"{setting}:{pitch_quality}:{RUBBERBAND_QUALITY}"
    if preserve_formants:
        options += f":{FORMANT_PRESERVED}"
    return f"rubberband@{name}={options}" if name else f"rubberband={options}"


def sliding_command_text(name: str, steps: list[SlidingStep], delay: float = SLIDING_COMMAND_DELAY) -> str:
    """Os comandos do `asendcmd` do Esticar Gradualmente: a cada degrau, o andamento e o tom novos do `rubberband`
    (`instante filtro comando valor`, separados por ponto e vírgula), `delay` segundos depois do degrau. Função pura."""
    entries = []
    for step in steps:
        at = step.at + delay
        entries.append(f"{at:.4f} rubberband@{name} tempo {step.tempo:.6f}")
        entries.append(f"{at:.4f} rubberband@{name} pitch {step.pitch:.6f}")
    return ";".join(entries)


@register_builder("sliding_stretch")
def build_sliding_stretch(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, SlidingStretch)
    if request.samples < MIN_SAMPLES:
        return request.chain("anull")
    steps = sliding_steps(
        request.duration,
        percent_ratio(effect.tempo_start),
        percent_ratio(effect.tempo_end),
        effect.pitch_start,
        effect.pitch_end,
    )
    name = f"{request.tag}_rb"
    first = steps[0]
    # O `asendcmd` troca o andamento e o tom do `rubberband` a cada degrau, e a mudança aos poucos é o efeito. A conta da
    # duração de saída soma os mesmos degraus (`sliding_duration`), então a linha do tempo mostra o que sai: o `atrim` acerta
    # o arquivo, na amostra, nessa mesma duração (o motor erra por até 34 ms, ver `SLIDING_COMMAND_DELAY`).
    stretcher = rubberband(
        f"tempo={first.tempo:.6f}:pitch={first.pitch:.6f}",
        effect.preserve_formants,
        name,
        SLIDING_PITCH_QUALITY,
    )
    return request.chain(
        f"asetnsamples=n={SLIDING_FRAME_SAMPLES}:p=0",
        f"asendcmd=c='{sliding_command_text(name, steps)}'",
        *with_quiet_tail(stretcher, sliding_duration(steps) * request.sample_rate),
    )


@register_sample_builder("paulstretch")
def build_paulstretch(request: SampleRequest) -> np.ndarray:
    effect = request.effect
    assert isinstance(effect, Paulstretch)
    # o teto vale para o pedaço que este estágio recebe (com intervalo, só ele): quem processa o item inteiro já conferiu o total
    seconds = stretched_length(len(request.samples), effect.stretch_factor) / request.sample_rate
    reason = paulstretch_refusal(seconds)
    if reason:
        raise ValueError(reason)
    return paulstretch(request.samples, request.sample_rate, effect.stretch_factor, effect.time_resolution)
