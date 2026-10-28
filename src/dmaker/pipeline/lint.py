"""Avisos sobre a spec antes de renderizar (limites da plataforma, regras da marca, cortes inválidos)."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from ..domain.audiogram import project_has_voice
from ..domain.brand import Theme
from ..domain.looks import UnknownLookError, is_no_look, resolve_look
from ..domain.presets import Preset
from ..domain.spec import AudiogramOverlay, ClipSegment, Project
from ..domain.tracks import known_track_ids
from ..media.probe import MediaInfo
from .voicefiles import voice_file_warnings
from .voiceover import estimate_narration_duration

DASHES = ("—", "–")


def lint(
    project: Project,
    theme: Theme,
    preset: Preset,
    total: float,
    durations: list[float],
    infos: list[MediaInfo | None],
    offsets: list[float] | None = None,
    known_voices: Collection[str] | None = None,
    voiceover_playtimes: Sequence[float | None] = (),
) -> list[str]:
    """Devolve avisos; levanta ValueError só para o que não tem como renderizar. `offsets` é onde cada
    fonte começa no relógio da sessão (0 para arquivos avulsos). `known_voices` são os ids da biblioteca
    de vozes; sem ele, a existência da voz de cada narração não é conferida. `voiceover_playtimes` é quanto
    toca de cada arquivo de `audio.voiceover` (ver `voice_file_playtimes`); sem ele só a existência dos
    arquivos é conferida, porque medir a duração exige o ffprobe."""
    warnings: list[str] = []
    segments = project.timeline
    _check_look_names(project, theme)
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
            offset = offsets[i] if offsets else 0.0
            begins, ends = offset, offset + info.duration
            where = (
                f"a fonte {seg.source!r} cobre {begins:.2f}s a {ends:.2f}s da sessão"
                if seg.source
                else (f"a fonte tem {info.duration:.2f}s")
            )
            if seg.start >= ends or seg.start < begins:
                raise ValueError(f"timeline[{i}]: start={seg.start}s fora da fonte ({where}).")
            if seg.end and seg.end > ends + 0.05:
                warnings.append(
                    f"timeline[{i}]: end={seg.end:g}s passa do fim da fonte ({where}); cortado no fim."
                )
        if isinstance(seg, ClipSegment) and info and seg.audio_mode != "original":
            if reason := _silent_clip_reason(seg, info):
                warnings.append(
                    f"timeline[{i}]: audio_mode {seg.audio_mode!r} não faz efeito, o trecho {reason}."
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
    if (
        captions
        and captions.enabled
        and captions.source == "auto"
        and project.audio.mute_clips
        and not project.audio.voiceover
    ):
        warnings.append("Legendas automáticas com audio.mute_clips: não há voz para transcrever.")
    warnings += _narration_warnings(project, total, known_voices)
    warnings += voice_file_warnings(project, total, voiceover_playtimes)
    warnings += _audiogram_warnings(project, infos)
    warnings += _sfx_warnings(project, total)
    if project.tracks:
        known = known_track_ids(project)
        for track_id in project.tracks:
            if track_id not in known:
                warnings.append(f"tracks.{track_id}: id de trilha desconhecido (ignorado no render).")
        v1_state = project.tracks.get("V1")
        if v1_state and v1_state.hidden:
            warnings.append("tracks.V1.hidden é ignorado: V1 é a linha do tempo principal.")
    return warnings


def _check_look_names(project: Project, theme: Theme) -> None:
    """Look desconhecido (no projeto ou num trecho) não tem como renderizar: erro antes de gastar o render."""
    asked = [("look", project.look)] + [
        (f"timeline[{i}].look", seg.look) for i, seg in enumerate(project.timeline)
    ]
    for where, name in asked:
        if name is not None and not is_no_look(name):
            try:
                resolve_look(name, theme.looks)
            except UnknownLookError as exc:
                raise ValueError(f"{where}: {exc}") from exc


def _silent_clip_reason(seg: ClipSegment, info: MediaInfo) -> str | None:
    """Por que o trecho não tem áudio da câmera (mudo ou fonte sem áudio); None se tem."""
    if seg.mute or seg.volume <= 0:
        return "está mudo"
    return None if info.has_audio else "não tem áudio"


def _audiogram_warnings(project: Project, infos: list[MediaInfo | None]) -> list[str]:
    """Audiograma que segue a voz num projeto sem voz: a animação ficaria parada o vídeo inteiro."""
    audiograms = [(i, ov) for i, ov in enumerate(project.overlays) if isinstance(ov, AudiogramOverlay)]
    if not audiograms or project_has_voice(project, [bool(info and info.has_audio) for info in infos]):
        return []
    return [
        f'overlays[{i}]: o audiograma segue a voz (follow "voice"), mas o projeto não tem voz (clipes mudos '
        'ou sem áudio, nem narração nem audio.voiceover): ele ficaria parado. Use follow "mix" ou "auto".'
        for i, ov in audiograms
        if ov.follow == "voice"
    ]


def _sfx_warnings(project: Project, total: float) -> list[str]:
    """Efeito sonoro marcado depois do fim do vídeo (a mixagem o corta) ou que nunca soaria (sem volume)."""
    warnings = []
    for i, cue in enumerate(project.audio.sfx):
        if cue.at >= total:
            warnings.append(f"audio.sfx[{i}]: toca em {cue.at:g}s, depois do fim do vídeo ({total:.1f}s).")
        elif cue.volume <= 0:
            warnings.append(f"audio.sfx[{i}]: volume 0, o efeito não toca.")
    return warnings


def _narration_warnings(project: Project, total: float, known_voices: Collection[str] | None) -> list[str]:
    """Voz inexistente, narração fora do vídeo (pela duração estimada) e legenda de narração sem narração."""
    warnings: list[str] = []
    for i, narration in enumerate(project.audio.narration):
        where = f"audio.narration[{i}]"
        if narration.voice and known_voices is not None and narration.voice not in known_voices:
            available = ", ".join(sorted(known_voices)) or "nenhuma voz cadastrada"
            warnings.append(f"{where}: a voz {narration.voice!r} não existe na biblioteca ({available}).")
        if narration.script and not project.resolve(narration.script).exists():
            warnings.append(f"{where}: roteiro {narration.script!r} não encontrado.")
            continue
        if narration.start >= total:
            warnings.append(
                f"{where}: começa em {narration.start:g}s, depois do fim do vídeo ({total:.1f}s)."
            )
            continue
        end = narration.start + estimate_narration_duration(project, narration)
        if end > total + 0.5:
            warnings.append(
                f"{where}: deve terminar por volta de {end:.1f}s (estimativa), depois do fim do vídeo "
                f"({total:.1f}s); o final da fala seria cortado."
            )
    captions = project.captions
    if captions and captions.enabled and captions.source == "narration" and not project.audio.narration:
        warnings.append('captions.source "narration" sem audio.narration: não há fala para legendar.')
    return warnings
