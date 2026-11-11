"""Construtores dos efeitos de fade: Fade In, Fade Out, Fade Ajustável e Studio Fade Out (as classes estão em
`domain/audio_effects/fades.py` e as curvas, como funções puras, em `domain/fade_curves.py`)."""

from __future__ import annotations

from ...domain.audio_effects.editing import EnvelopePoint
from ...domain.audio_effects.fades import AdjustableFade, EdgeFade, StudioFadeOut
from ...domain.fade_curves import AFADE_CURVE, adjustable_gain, curve_db_points, gain_db, gain_from_unit
from .editing import ENVELOPE_FRAME_SAMPLES, envelope_gain_expression
from .registry import EffectRequest, register_builder

# O passa-baixa do Studio Fade Out parte daqui: acima da audição de quase todo mundo e perto do limite de 48 kHz, para
# o começo do fade soar igual ao som sem efeito
STUDIO_START_CUTOFF_HZ = 20000.0
# Quadros de 10 ms (480 amostras a 48 kHz) para o `asendcmd` mudar a frequência do passa-baixa: o comando só vale na
# fronteira de um quadro, e o quadro padrão (1024 amostras) faria o corte andar em degraus audíveis
STUDIO_FRAME_SAMPLES = 480
# Um comando de frequência a cada 10 ms, no máximo 150: um fade de minutos não pode estourar a linha de comando
STUDIO_STEP_SECONDS = 0.010
STUDIO_MAX_STEPS = 150
STUDIO_MIN_STEPS = 8
# A resposta de um passa-baixa de 2 polos (12 dB por oitava): o suficiente para fechar os agudos sem soar abafado de uma vez
STUDIO_POLES = 2
MIN_FADE_SAMPLES = 2


def fade_span(request: EffectRequest, at_start: bool) -> tuple[float, float]:
    """Onde o fade cai no sinal que entra, em segundos (começo, duração): o sinal todo quando o efeito tem intervalo (o
    pedaço já vem recortado, ou o intervalo cobre o item), senão `duration` a partir da borda, sem passar do sinal."""
    effect = request.effect
    if effect.start is not None or effect.end is not None:
        return 0.0, request.duration
    length = min(effect.duration, request.duration)  # type: ignore[attr-defined]
    return (0.0, length) if at_start else (request.duration - length, length)


@register_builder("fade_in", "fade_out")
def build_edge_fade(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, EdgeFade)
    begin, length = fade_span(request, effect.at_start)
    if length * request.sample_rate < MIN_FADE_SAMPLES:  # menos de duas amostras: nada a abrir ou fechar
        return request.chain("anull")
    direction = "in" if effect.at_start else "out"
    return request.chain(
        f"afade=t={direction}:st={begin:.6f}:d={length:.6f}:curve={AFADE_CURVE[effect.curve]}"
    )


@register_builder("adjustable_fade")
def build_adjustable_fade(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, AdjustableFade)
    start = gain_from_unit(effect.start_gain, effect.unit)
    end = gain_from_unit(effect.end_gain, effect.unit)
    if abs(start - end) < 1e-9:  # ganho inicial igual ao final: um ganho só, sem reavaliar nada
        return request.chain(f"volume={gain_db(start):.6f}dB")
    points = [
        EnvelopePoint(at=at, db=db)
        for at, db in curve_db_points(
            lambda u: adjustable_gain(effect.shape, effect.mid_adjust, start, end, u), request.duration
        )
    ]
    expression = envelope_gain_expression(points)
    return request.chain(
        f"asetnsamples=n={ENVELOPE_FRAME_SAMPLES}:p=0",
        f"volume='pow(10,({expression})/20)':eval=frame:precision=float",
    )


def studio_cutoff_commands(
    begin: float, length: float, final_cutoff: float, steps: int | None = None
) -> list[tuple[float, float]]:
    """A frequência do passa-baixa ao longo do fade: pares (instante em segundos, corte em Hz). O corte desce de
    `STUDIO_START_CUTOFF_HZ` a `final_cutoff` em oitavas iguais (a audição é logarítmica em frequência, então é assim que
    os agudos parecem fechar num ritmo só). Função pura."""
    count = steps or max(STUDIO_MIN_STEPS, min(STUDIO_MAX_STEPS, round(length / STUDIO_STEP_SECONDS)))
    ratio = final_cutoff / STUDIO_START_CUTOFF_HZ
    return [
        (round(begin + length * step / count, 6), round(STUDIO_START_CUTOFF_HZ * ratio ** (step / count), 2))
        for step in range(count + 1)
    ]


def studio_command_text(name: str, steps: list[tuple[float, float]]) -> str:
    """Os comandos do `asendcmd` (`instante filtro f frequência`, separados por ponto e vírgula)."""
    return ";".join(f"{at:.4f} lowpass@{name} f {hz:.2f}" for at, hz in steps)


@register_builder("studio_fade_out")
def build_studio_fade_out(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, StudioFadeOut)
    begin, length = fade_span(request, at_start=False)
    if length * request.sample_rate < MIN_FADE_SAMPLES:
        return request.chain("anull")
    name = f"{request.tag}_lp"
    commands = studio_command_text(name, studio_cutoff_commands(begin, length, effect.final_cutoff))
    # O volume fecha numa curva quadrática (`qua`, u ao quadrado de trás para a frente), que cai bem depressa no fim,
    # enquanto o passa-baixa, que o `asendcmd` abaixa a cada 10 ms, tira os agudos antes de o som sumir. O filtro só liga
    # quando o fade começa (`enable`): até lá o som passa intacto, inclusive acima de 20 kHz, que um passa-baixa de 2
    # polos já abaixaria.
    return request.chain(
        f"asetnsamples=n={STUDIO_FRAME_SAMPLES}:p=0",
        f"asendcmd=c='{commands}'",
        f"lowpass@{name}=f={STUDIO_START_CUTOFF_HZ:.0f}:p={STUDIO_POLES}:enable='gte(t,{begin:.6f})'",
        f"afade=t=out:st={begin:.6f}:d={length:.6f}:curve=qua",
    )
