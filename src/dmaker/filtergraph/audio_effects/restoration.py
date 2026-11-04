"""Construtores dos efeitos de limpeza e reparo (as classes estão em `domain/audio_effects/restoration.py`).

Quais viram filtro do ffmpeg e quais viram conta em numpy foi decidido medindo, com ruído branco a -45 dBFS e uma
fala sintética (o trecho só de ruído antes e depois, 12 dB de redução pedidos):

- `afftdn` com o perfil por bandas (`noise_type=custom` com `band_noise`): 4,75 dB de queda, igual para qualquer
  valor de banda de -85 a +20 dB, ou seja, o perfil é ignorado. Com ruído branco e o piso certo (`noise_type=white`,
  `noise_floor=-45`): 9,92 dB, abaixo dos 10 dB que o critério pede e dos 12 dB pedidos. Só passa de 12 dB com um
  piso de ruído errado para cima (-40), que também tira fala. Por isso a Redução de ruído é subtração espectral em
  numpy (`media/spectral.py`), que entrega os 12 dB pedidos (11,99 medidos) e muda a fala em menos de 0,05 dB.
- `adeclick` e `adeclip` fazem o que o Audacity descreve e ficam como filtros. Os dois têm um defeito de partida: sem
  histórico, a primeira janela (55 ms) sai deformada (o erro nos primeiros 80 ms de um seno estourado ficou em
  -13,8 dB contra -30,5 dB do sinal estourado). A solução é pôr na frente uma cópia espelhada dos primeiros 100 ms e
  tirá-la depois: com ela o erro do clipping caiu de -33,5 para -53,4 dB, uniforme do começo ao fim.
- O Reparar é a interpolação autorregressiva de `media/repair.py`.
"""

from __future__ import annotations

import numpy as np

from ...domain.audio_effects.restoration import ClickRemoval, ClipFix, NoiseReduction, Repair
from ...media.repair import repair_interval
from ...media.spectral import reduce_noise
from .registry import EffectRequest, SampleRequest, register_builder, register_sample_builder

# O histórico espelhado que alimenta o `adeclick` e o `adeclip`: mais que a janela deles (55 ms) e que o período de
# uma voz grave
PREROLL_SECONDS = 0.1
# Uma amostra de 16 bits no teto vale 0,99997 do fundo de escala; esta folga deixa o limiar de 100% pegar o clipping
# digital de verdade, que nunca chega a 1,0 exato
CLIP_LEVEL_TOLERANCE = 0.001
# A janela de análise do `adeclick`: com a padrão (55 ms), cliques de 2 amostras passaram sem ser vistos (2 de 6 numa
# fala sintética), porque o limiar é relativo ao erro de predição da janela inteira; com 30 ms e `t=1` os cliques de 1
# a 5 amostras de uma voz sintetizada pelo próprio DMaker (Kokoro) foram apagados (erro de 0,5 para 0,004 no ponto do
# clique) e o nível da fala mudou -0,05 dB
ADECLICK_WINDOW_MS = 30
# Os extremos que o `adeclick` aceita: `t` (limiar) vai de 1 a 100 e `b` (fusão de rajadas) de 0 a 10
ADECLICK_MIN_THRESHOLD = 1.0
ADECLICK_MAX_BURST = 10.0
# O limiar do Audacity (0 a 900, padrão 200) e o do `adeclick` (1 a 100, padrão 2) correm no mesmo sentido: menor pega
# mais cliques. O padrão do Audacity cai na sensibilidade máxima do ffmpeg, a que apagou os cliques do teste; por isso
# `t = limiar / 200`, e abaixo de 200 o detector já está no limite
ADECLICK_THRESHOLD_SCALE = 200.0
# A largura máxima do pico do Audacity (amostras) decide até onde o `adeclick` funde detecções vizinhas (`b`). Quanto
# maior a fusão, mais ele interpola, e numa fala de verdade as consoantes (fricativas) parecem rajadas de cliques: com
# `b=5` o nível da fala caiu 0,4 dB e com `b=10`, 1,5 dB. A largura padrão (20) vira o `b=2` do ffmpeg; a máxima (40) vira 4
ADECLICK_BURST_PER_SAMPLE = 0.1


def declick_parameters(threshold: int, max_spike_width: int) -> tuple[float, float]:
    """Os parâmetros do `adeclick` (`t` e `b`) para o limiar e a largura máxima do pico do Audacity."""
    detection = max(ADECLICK_MIN_THRESHOLD, threshold / ADECLICK_THRESHOLD_SCALE)
    burst = min(ADECLICK_MAX_BURST, max_spike_width * ADECLICK_BURST_PER_SAMPLE)
    return detection, burst


def _mirrored_preroll(request: EffectRequest, restore: str, source: str, out: str) -> list[str]:
    """`restore` (um filtro que precisa de histórico) aplicado a `source` precedido de uma cópia espelhada do começo
    dele; a cópia sai depois, e o resultado tem exatamente o tamanho de `source`. O espelho continua a onda sem
    degrau no ponto de emenda (a primeira amostra real é a vizinha dele)."""
    preroll = max(min(round(PREROLL_SECONDS * request.sample_rate), request.samples), 1)
    head, body = request.label("pa"), request.label("pb")
    mirrored = request.label("pm")
    return [
        f"{source}asplit=2{head}{body}",
        f"{head}atrim=end_sample={preroll},areverse{mirrored}",
        f"{mirrored}{body}concat=n=2:v=0:a=1,{restore},atrim=start_sample={preroll},asetpts=PTS-STARTPTS{out}",
    ]


@register_builder("click_removal")
def build_click_removal(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, ClickRemoval)
    detection, burst = declick_parameters(effect.threshold, effect.max_spike_width)
    restore = f"adeclick=w={ADECLICK_WINDOW_MS}:t={detection:g}:b={burst:g}"
    return _mirrored_preroll(request, restore, request.source, request.out)


@register_builder("clip_fix")
def build_clip_fix(request: EffectRequest) -> list[str]:
    """O `adeclip` acha sozinho onde a onda foi achatada (pelo histograma das amostras), então o limiar do Audacity vira
    uma máscara: só as amostras de `limiar` % para cima trocam pela reconstrução, e o resto fica como veio. A redução de
    volume do Audacity (dar espaço para os picos refeitos) é um ganho depois."""
    effect = request.effect
    assert isinstance(effect, ClipFix)
    level = max(effect.threshold_percent / 100.0 - CLIP_LEVEL_TOLERANCE, 0.0)
    original, whole = request.label("o"), request.label("w")
    restored = request.label("r")
    lines = [f"{request.source}asplit=2{original}{whole}"]
    lines += _mirrored_preroll(request, "adeclip", whole, restored)
    # as duas pontas lado a lado: canais 0 e 1 são o original, 2 e 3 o reconstruído (som estéreo)
    choose = "|".join(
        f"if(lt(abs(val({channel})),{level:.6f}),val({channel}),val({channel + 2}))" for channel in (0, 1)
    )
    tail = [f"aeval=exprs='{choose}':channel_layout=stereo", "aformat=sample_fmts=fltp"]
    if effect.reduce_db > 0:
        tail.append(f"volume=-{effect.reduce_db:.6f}dB")
    lines.append(f"{original}{restored}amerge=inputs=2,{','.join(tail)}{request.out}")
    return lines


@register_sample_builder("noise_reduction")
def build_noise_reduction(request: SampleRequest) -> np.ndarray:
    effect = request.effect
    assert isinstance(effect, NoiseReduction)
    spectrum = request.measure.noise if request.measure else None
    if spectrum is None:
        raise ValueError("a Redução de ruído precisa do perfil medido (request.measure.noise)")
    return reduce_noise(
        request.samples, spectrum, effect.reduction_db, effect.sensitivity, effect.smoothing_bands
    ).astype(request.samples.dtype, copy=False)


@register_sample_builder("repair")
def build_repair(request: SampleRequest) -> np.ndarray:
    effect = request.effect
    assert isinstance(effect, Repair) and effect.start is not None and effect.end is not None
    first = round(effect.start * request.sample_rate)
    last = round(effect.end * request.sample_rate)
    return repair_interval(request.samples, first, last)
