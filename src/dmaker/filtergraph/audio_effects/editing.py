"""Construtores dos efeitos de edição de onda: Silenciar, Cortar, Envelope de volume e Canais (as classes estão em
`domain/audio_effects/editing.py`)."""

from __future__ import annotations

from collections.abc import Sequence

from ...domain.audio_effects.editing import Channels, Cut, Envelope, EnvelopePoint, Silence
from .registry import EffectRequest, register_builder

# Quadros de 64 amostras (1,3 ms a 48 kHz) para o `volume` reavaliar a curva do envelope: o filtro só recalcula a
# expressão a cada quadro, e o quadro padrão (1024 amostras, 21 ms) faria a rampa andar em degraus audíveis num
# envelope curto. `p=0` não completa o último quadro com silêncio, que alongaria o item.
ENVELOPE_FRAME_SAMPLES = 64


def _number(value: float) -> str:
    """Número para dentro de uma expressão do ffmpeg, entre parênteses para o sinal negativo não colar no operador."""
    return f"({value:.6f})"


def envelope_gain_expression(points: Sequence[EnvelopePoint]) -> str:
    """O ganho em dB da curva como expressão do ffmpeg em `t` (segundos do item): reta em dB entre os pontos e o
    ganho da ponta antes do primeiro e depois do último. Função pura, montada de trás para a frente em `if` aninhados."""
    first, last = points[0], points[-1]
    expression = _number(last.db)
    for before, after in reversed(list(zip(points, points[1:], strict=False))):
        slope = (after.db - before.db) / (after.at - before.at)
        expression = (
            f"if(lt(t,{_number(after.at)}),{_number(before.db)}+{_number(slope)}*(t-{_number(before.at)}),"
            f"{expression})"
        )
    return f"if(lt(t,{_number(first.at)}),{_number(first.db)},{expression})"


@register_builder("silence")
def build_silence(request: EffectRequest) -> list[str]:
    assert isinstance(request.effect, Silence)
    # multiplicar por zero dá amostras exatamente nulas; a emenda de 10 ms nas bordas vem da cadeia (`chain.py`)
    return request.chain("volume=0")


@register_builder("cut")
def build_cut(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, Cut) and effect.start is not None and effect.end is not None
    rate, total = request.sample_rate, request.samples
    first = max(round(effect.start * rate), 0)
    last = min(round(effect.end * rate), total)
    if last - first < 1 or first >= total:  # o intervalo não pega som nenhum: nada a tirar
        return request.chain("anull")
    # o fim completa até o tamanho de antes: `apad` com `whole_len` só acrescenta o que falta
    keep = [f"apad=whole_len={total}"] if effect.keep_length else []
    if first <= 0 and last >= total:  # o corte leva o item inteiro
        return request.chain("volume=0") if effect.keep_length else request.chain("atrim=end_sample=0")
    if first <= 0:
        return request.chain(f"atrim=start_sample={last}", "asetpts=PTS-STARTPTS", *keep)
    if last >= total:
        return request.chain(f"atrim=end_sample={first}", "asetpts=PTS-STARTPTS", *keep)
    head, tail = request.label("h"), request.label("t")
    joined = ",".join(["concat=n=2:v=0:a=1", *keep])
    return [
        f"{request.source}asplit=2{head}{tail}",
        f"{head}atrim=end_sample={first},asetpts=PTS-STARTPTS{request.label('hd')}",
        f"{tail}atrim=start_sample={last},asetpts=PTS-STARTPTS{request.label('td')}",
        f"{request.label('hd')}{request.label('td')}{joined}{request.out}",
    ]


@register_builder("envelope")
def build_envelope(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, Envelope)
    gains = {round(point.db, 6) for point in effect.points}
    if len(gains) == 1:  # curva reta: um ganho só, sem reavaliar nada
        return request.chain(f"volume={effect.points[0].db:.6f}dB")
    expression = envelope_gain_expression(effect.points)
    return request.chain(
        f"asetnsamples=n={ENVELOPE_FRAME_SAMPLES}:p=0",
        f"volume='pow(10,({expression})/20)':eval=frame:precision=float",
    )


# modo -> a mistura de cada canal de saída a partir dos de entrada (c0 esquerdo, c1 direito)
CHANNEL_MIXES: dict[str, tuple[str, str]] = {
    "mono": ("0.5*c0+0.5*c1", "0.5*c0+0.5*c1"),
    "swap": ("c1", "c0"),
    "left": ("c0", "c0"),
    "right": ("c1", "c1"),
}


@register_builder("channels")
def build_channels(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, Channels)
    left, right = CHANNEL_MIXES[effect.mode]
    return request.chain(f"pan=stereo|c0={left}|c1={right}")
