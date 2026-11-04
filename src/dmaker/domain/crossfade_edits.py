"""O crossfade de trilhas como edição da spec: um Fade Ajustável de saída num item e um de entrada no outro, no mesmo
intervalo, com as curvas casadas (o "Crossfade Tracks" do Audacity). Nada muda na mixagem: são dois efeitos comuns da
cadeia de cada item, que a pessoa vê, ajusta e tira depois. Puro, no molde de `domain/audio_edits.py`."""

from __future__ import annotations

from .edits import EditError, _check_index, _clone
from .fade_curves import ADJUSTABLE_SHAPES, CROSSFADE_TYPES, FadeLaw, crossfade_laws
from .spec import Project


def effect_from_law(law: FadeLaw, start: float, end: float) -> dict:
    """O Fade Ajustável (como a spec o escreve) que faz a `law` entre `start` e `end` (segundos do item)."""
    return {
        "type": "adjustable_fade",
        "shape": law.shape,
        "mid_adjust": law.mid_adjust,
        "start_gain": round(law.start_gain * 100.0, 6),
        "end_gain": round(law.end_gain * 100.0, 6),
        "unit": "percent",
        "start": round(start, 6),
        "end": round(end, 6),
    }


def set_clip_crossfade(project: Project, index: int, duration: float, curve: str | None) -> Project:
    """Põe, muda ou tira (`duration` zero) o crossfade de som no corte entre o trecho `index - 1` e o `index`. O trecho
    `index` é o que entra: o campo mora nele, como a transição de imagem. Os dois precisam ser clipes de vídeo."""
    _check_index(len(project.timeline), index, "trecho")
    if index == 0:
        raise EditError(
            "o primeiro trecho não tem corte de entrada: o crossfade de som vai no segundo trecho em diante"
        )
    for position in (index - 1, index):
        if project.timeline[position].type != "clip":
            raise EditError(
                f"timeline[{position}]: o crossfade de som vale entre dois clipes de vídeo; "
                f"{project.timeline[position].type} não tem som para cruzar"
            )
    if curve is not None and curve not in CLIP_CROSSFADE_TYPES:
        raise EditError(
            f"tipo de crossfade desconhecido: {curve!r}. Use um de: {', '.join(CLIP_CROSSFADE_TYPES)}"
        )

    def mutate(data: dict) -> None:
        segment = data["timeline"][index]
        if duration <= 0:
            segment.pop("audio_crossfade", None)
            return
        previous = segment.get("audio_crossfade") or {}
        segment["audio_crossfade"] = {
            "duration": round(duration, 6),
            "curve": curve or previous.get("curve", "constant_power_1"),
        }

    return _clone(project, mutate)


# os tipos que o campo `audio_crossfade` do clipe aceita (o `custom` é só do crossfade de trilhas)
CLIP_CROSSFADE_TYPES: tuple[str, ...] = ("constant_gain", "constant_power_1", "constant_power_2")


def check_crossfade_kind(kind: object, shape: object, mid_adjust: object) -> tuple[str, str, float]:
    """O tipo, a forma e o ajuste do meio já validados; o tipo desconhecido é erro que lista os aceitos. A forma só
    conta no tipo `custom`."""
    if kind not in CROSSFADE_TYPES:
        raise EditError(f"tipo de crossfade desconhecido: {kind!r}. Use um de: {', '.join(CROSSFADE_TYPES)}")
    chosen = "s_up" if shape is None else shape
    if chosen not in ADJUSTABLE_SHAPES:
        raise EditError(
            f"forma de crossfade desconhecida: {shape!r}. Use uma de: {', '.join(ADJUSTABLE_SHAPES)}"
        )
    try:
        mid = 0.0 if mid_adjust is None else float(mid_adjust)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise EditError(f"`mid_adjust` precisa ser um número de -100 a 100 (veio {mid_adjust!r})") from None
    if not -100.0 <= mid <= 100.0:
        raise EditError(f"`mid_adjust` precisa ficar entre -100 e 100 (veio {mid:g})")
    return str(kind), str(chosen), mid


def crossfade_pair(
    kind: str, shape: str, mid_adjust: float, out_span: tuple[float, float], in_span: tuple[float, float]
) -> tuple[dict, dict]:
    """Os dois efeitos do crossfade: o de saída, no intervalo `out_span` do item que some, e o de entrada, no intervalo
    `in_span` do que entra (cada intervalo em segundos do próprio item)."""
    leaving, entering = crossfade_laws(kind, shape, mid_adjust)
    return effect_from_law(leaving, *out_span), effect_from_law(entering, *in_span)
