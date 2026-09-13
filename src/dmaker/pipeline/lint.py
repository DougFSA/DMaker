"""Avisos sobre a spec antes de renderizar (limites da plataforma, regras da marca, cortes inválidos)."""

from __future__ import annotations

from ..domain.brand import Theme
from ..domain.presets import Preset
from ..domain.spec import ClipSegment, Project
from ..media.probe import MediaInfo

DASHES = ("—", "–")


def lint(
    project: Project,
    theme: Theme,
    preset: Preset,
    total: float,
    durations: list[float],
    infos: list[MediaInfo | None],
) -> list[str]:
    """Devolve avisos; levanta ValueError só para o que não tem como renderizar."""
    warnings: list[str] = []
    segments = project.timeline
    if preset.max_duration and total > preset.max_duration + 0.01:
        warnings.append(
            f"Duração final {total:.1f}s passa do limite de {preset.platform} {preset.name} ({preset.max_duration:.0f}s)."
        )
    if theme.no_dash:
        for where, text in project.texts():
            if any(d in text for d in DASHES):
                warnings.append(
                    f"{where}: contém travessão/meia-risca. Regra da marca {theme.name}: usar vírgula, ponto ou dois-pontos."
                )
    if segments[0].transition:
        warnings.append("timeline[0].transition é ignorada (não existe trecho anterior).")
    for i in range(1, len(segments)):
        tr = segments[i].transition
        if tr and tr.type != "cut" and tr.duration > min(durations[i - 1], durations[i]) * 0.5:
            warnings.append(
                f"timeline[{i}]: transição de {tr.duration:g}s é longa para trechos de "
                f"{durations[i - 1]:.1f}s/{durations[i]:.1f}s; será encurtada."
            )
    for i, (seg, info) in enumerate(zip(segments, infos, strict=True)):
        if isinstance(seg, ClipSegment) and info:
            if seg.start >= info.duration:
                raise ValueError(
                    f"timeline[{i}]: start={seg.start}s é maior que a duração da fonte ({info.duration:.2f}s)."
                )
            if seg.end and seg.end > info.duration + 0.05:
                warnings.append(
                    f"timeline[{i}]: end={seg.end:g}s passa da duração da fonte ({info.duration:.2f}s); cortado no fim."
                )
        if info and info.width and max(info.width, info.height) < preset.short_side:
            warnings.append(
                f"timeline[{i}]: fonte {info.width}x{info.height} é menor que a saída "
                f"({preset.width}x{preset.height}); perde nitidez."
            )
    for i, ov in enumerate(project.overlays):
        start = getattr(ov, "start", None)
        if start is not None and start >= total:
            warnings.append(f"overlays[{i}]: começa em {start:g}s, depois do fim do vídeo ({total:.1f}s).")
    captions = project.captions
    if captions and captions.enabled and captions.source == "auto" and project.audio.mute_clips:
        warnings.append("Legendas automáticas com audio.mute_clips: não há voz para transcrever.")
    return warnings
