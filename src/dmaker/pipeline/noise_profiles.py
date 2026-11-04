"""Perfis de ruído do projeto: de onde vem o som de cada perfil, o espectro dele e o relatório por banda.

Um perfil (`audio.noise_profiles`) é um nome para "este trecho deste item, que só tem o chiado". Guardado na spec só como
`{target, start, end}` (o `start` e o `end` são tempo do item); o espectro é medido na hora de processar, pelo mesmo
caminho do render, e nunca vai para a spec. Aqui ficam: achar o arquivo e o trecho de cada alvo, medir o espectro, a
janela mais quieta do item (o perfil automático) e a lista de níveis por banda que o `noise_profile` do MCP devolve.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain.audio_edits import require_file_time
from ..domain.audio_effects.restoration import AUTO_PROFILE
from ..domain.audio_targets import parse_target
from ..domain.edits import EditError
from ..domain.spec import ClipSegment, NoiseProfile, Project, VideoOverlay
from ..filtergraph.audio_effects.registry import SAMPLE_RATE
from ..media.spectral import MIN_PROFILE_SECONDS, NoiseSpectrum, band_levels, noise_spectrum, quietest_window
from .sample_reader import AudioSlice, SampleReader
from .sources import Source

# A janela do perfil automático: meio segundo de som mais quieto do item tem tempo de sobra para a média por bin se
# sustentar (mais de 40 quadros da FFT), e é curto o bastante para caber numa pausa entre duas frases
AUTO_PROFILE_SECONDS = 0.5
# O quanto do item se examina atrás do trecho mais quieto quando não se sabe a duração dele (música, faixa externa)
AUTO_SCAN_SECONDS = 600.0
# O trecho do perfil é lido como o item chega ao efeito: estéreo na taxa da mistura
PROFILE_CHANNELS = 2


@dataclass(frozen=True)
class TargetAudio:
    """O som de um item da spec como arquivo: `file_start` é o segundo do arquivo em que o item começa (o tempo 0 do
    item), para ler um trecho `a`..`b` do item é só somar."""

    path: Path
    file_start: float
    stream: int = 0

    def slice(self, start: float, end: float) -> AudioSlice:
        return AudioSlice(self.path, self.file_start + start, end - start, self.stream)


def locate_target_audio(project: Project, session: Mapping[str, Source], target: str) -> TargetAudio:
    """O arquivo e o ponto de partida do som do item `target` (`timeline.0`, `audio.voiceover.1`...), do jeito que o
    render o lê. A narração (sintetizada, sem ruído de fundo) e a mistura (que não é um arquivo) recusam com o motivo."""
    kind, index = parse_target(target)
    if kind == "clip":
        assert index is not None
        return _clip_audio(project, session, target, index)
    if kind == "pip":
        assert index is not None
        return _pip_audio(project, session, target, index)
    if kind == "voiceover":
        assert index is not None
        clip = project.audio.voiceover[index]
        require_file_time(clip.effects, target)
        return TargetAudio(project.resolve(clip.src), clip.offset)
    if kind == "music":
        music = project.audio.music
        if music is None:
            raise EditError("o projeto não tem música (audio.music)")
        require_file_time(music.effects, target)
        return TargetAudio(project.resolve(music.src), 0.0)
    if kind == "track":
        assert index is not None
        track = project.audio.tracks[index]
        found = _session_source(session, track.source, target)
        return TargetAudio(found.path, 0.0, found.audio_stream)  # type: ignore[arg-type]
    reasons = {
        "narration": "a narração é sintetizada do texto e não tem chiado de fundo para medir",
        "master": "a mistura não é um arquivo: pegue o perfil de um item (um clipe, uma voz gravada...)",
    }
    raise EditError(f"{target}: {reasons[kind]}")


def _session_source(session: Mapping[str, Source], name: str, target: str) -> Source:
    source = session.get(name)
    if source is None or source.path is None:
        raise EditError(f"{target}: o arquivo da fonte {name!r} não foi encontrado")
    return source


def _clip_audio(project: Project, session: Mapping[str, Source], target: str, index: int) -> TargetAudio:
    if not 0 <= index < len(project.timeline):
        raise EditError(f"índice de trecho fora do intervalo: {index} (0 a {len(project.timeline) - 1})")
    segment = project.timeline[index]
    if not isinstance(segment, ClipSegment):
        raise EditError(f"{target}: só o trecho de vídeo (clipe) tem som para medir")
    require_file_time(segment.effects, target)
    if segment.source:
        reference = project.sources.get(segment.source)
        if reference is not None and reference.parts:
            raise EditError(
                f"{target}: a fonte tem várias partes (`parts`); pegue o perfil de uma voz gravada"
            )
        found = _session_source(session, segment.source, target)
        # o som sai da janela do clipe, deslocada pelo `audio_offset` (positivo atrasa o som em relação à imagem)
        return TargetAudio(
            found.path, found.in_point(segment.start) - segment.audio_offset, found.audio_stream
        )  # type: ignore[arg-type]
    return TargetAudio(project.resolve(segment.src or ""), segment.start - segment.audio_offset)


def _pip_audio(project: Project, session: Mapping[str, Source], target: str, index: int) -> TargetAudio:
    if not 0 <= index < len(project.overlays):
        raise EditError(
            f"índice de sobreposição fora do intervalo: {index} (0 a {len(project.overlays) - 1})"
        )
    overlay = project.overlays[index]
    if not isinstance(overlay, VideoOverlay):
        raise EditError(f"{target}: só a sobreposição de vídeo (PiP) tem som para medir")
    require_file_time(overlay.effects, target)
    if overlay.source:
        found = _session_source(session, overlay.source, target)
        return TargetAudio(
            found.path, found.in_point(overlay.offset) - overlay.audio_offset, found.audio_stream
        )  # type: ignore[arg-type]
    return TargetAudio(project.resolve(overlay.src or ""), overlay.offset - overlay.audio_offset)


def _stamp(path: Path) -> list[Any] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return [str(path), stat.st_mtime_ns, stat.st_size]


class ProfileLocator:
    """Acha, para cada perfil do projeto, o trecho de arquivo que ele aponta. É o que o processador de efeitos usa para
    medir o espectro e para a chave de cache mudar quando o perfil (ou o arquivo dele) muda."""

    def __init__(self, project: Project, session: Mapping[str, Source]) -> None:
        self.project = project
        self.session = session

    def profile(self, name: str) -> NoiseProfile:
        try:
            return self.project.audio.noise_profiles[name]
        except KeyError:
            known = ", ".join(sorted(self.project.audio.noise_profiles)) or "nenhum"
            raise ValueError(
                f"o perfil de ruído {name!r} não existe neste projeto (perfis: {known}). "
                f"Crie com `noise_profile`, ou use {AUTO_PROFILE!r}"
            ) from None

    def slice(self, name: str) -> AudioSlice:
        profile = self.profile(name)
        try:
            return locate_target_audio(self.project, self.session, profile.target).slice(
                profile.start, profile.end
            )
        except EditError as exc:
            raise ValueError(f"perfil de ruído {name!r}: {exc}") from exc

    def signature(self, name: str) -> list[Any]:
        """O que muda o espectro do perfil: o trecho e o arquivo (nome, data e tamanho). Entra na chave do cache."""
        audio = self.slice(name)
        return [name, round(audio.start, 6), round(audio.duration, 6), audio.stream, _stamp(audio.path)]


def measure_profile(reader: SampleReader, audio: AudioSlice) -> NoiseSpectrum:
    """O espectro do trecho de ruído, lido como o item chega aos efeitos (estéreo, 48 kHz)."""
    samples = reader.read(audio, rate=SAMPLE_RATE, channels=PROFILE_CHANNELS)
    if len(samples) == 0:
        raise ValueError(f"não consegui ler o trecho de ruído de {audio.path.name}")
    return noise_spectrum(samples, SAMPLE_RATE)


def quietest_item_window(
    reader: SampleReader, source: TargetAudio, length: float | None, seconds: float = AUTO_PROFILE_SECONDS
) -> tuple[float, float]:
    """O início e o fim, em tempo do item, da janela mais quieta dele: o perfil automático. Lê o item em mono a 16 kHz
    (a energia não pede mais que isso) e, sem saber a duração dele, examina até `AUTO_SCAN_SECONDS`."""
    scan = min(length, AUTO_SCAN_SECONDS) if length is not None else AUTO_SCAN_SECONDS
    rate = 16000
    samples = reader.read(source.slice(0.0, scan), rate=rate, channels=1)
    if len(samples) < MIN_PROFILE_SECONDS * rate:
        raise EditError("o item é curto demais para achar um trecho de ruído (menos de 0,1 s de som)")
    return quietest_window(samples, rate, seconds)


def band_report(spectrum: NoiseSpectrum) -> list[dict[str, float]]:
    """Os níveis do ruído por banda de um terço de oitava, em dBFS: o que o `noise_profile` mostra."""
    return [{"hz": hz, "db": round(db, 1)} for hz, db in band_levels(spectrum)]


# ---------- o serviço que o MCP, a CLI e a interface chamam ----------


def measure_saved_profile(
    project: Project, name: str, prober: Any = None, reader: SampleReader | None = None
) -> dict[str, Any]:
    """Mede o perfil `name` do projeto e devolve o trecho dele e o nível do ruído por banda de um terço de oitava."""
    from ..media.ffmpeg import SubprocessRunner
    from ..media.probe import probe
    from .layout import project_layout
    from .missing import MissingMedia
    from .sample_reader import FFmpegSampleReader

    layout = project_layout(project, prober or probe, None, MissingMedia.scan(project))
    locator = ProfileLocator(project, layout.session)
    profile = locator.profile(name)
    spectrum = measure_profile(reader or FFmpegSampleReader(SubprocessRunner(quiet=True)), locator.slice(name))
    bands = band_report(spectrum)
    total = 10 * math.log10(sum(10 ** (band["db"] / 10) for band in bands))
    return {
        "name": name,
        "target": profile.target,
        "start": profile.start,
        "end": profile.end,
        "duration": round(profile.end - profile.start, 6),
        "level_db": round(total, 1),
        "bands": bands,
    }


def capture_noise_profile(
    name_or_path: Any,
    profile_name: str,
    target: str,
    start: Any = None,
    end: Any = None,
    reader: SampleReader | None = None,
) -> dict[str, Any]:
    """Guarda um perfil de ruído no projeto (pelo `edit_project`, então entra no histórico e o `dmaker undo` o desfaz) e
    devolve o nível medido por banda. Sem `start` e `end`, o perfil é o trecho mais quieto do item."""
    from .edit_history import edit_and_record

    operation: dict[str, Any] = {"type": "noise_profile_set", "name": profile_name, "target": target}
    if start is not None:
        operation["start"] = start
    if end is not None:
        operation["end"] = end
    report, path = edit_and_record(name_or_path, operation, sample_reader=reader)
    return {"spec_path": str(path), **measure_saved_profile(report.project, profile_name, reader=reader)}
