"""Serviço `plan_multicam`: transcreve a câmera de áudio de um bloco `multicam`, reconhece as fases da
cerimônia pela fala e substitui o bloco por clipes concretos alternando as câmeras.

Funções puras (cobertura, fala, plano, clipes, expansão da timeline) ficam separadas do que toca disco
e ffmpeg: só `plan_multicam` carrega o projeto, transcreve com cache e salva o resultado.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import CACHE_DIR
from ..domain.multicam import (
    Coverage,
    MulticamPlan,
    PhaseRule,
    PlannedClip,
    Speech,
    default_wedding_phases,
    phase_windows,
    plan_cuts,
)
from ..domain.spec import ClipSegment, MulticamBlock, Project
from ..media.ffmpeg import FFmpegRunner, SubprocessRunner
from ..media.probe import probe
from ..text.captions import Cue, from_json, to_json
from ..text.transcribe import Transcriber, WhisperTranscriber, extract_audio_wav
from .context import Prober
from .projects import load_project
from .projects import save_project as _save_project
from .sources import Source, resolve_session
from .sync import OffsetFinder, SyncResolver, ffmpeg_offset_finder

TRANSCRIPT_MODEL = "small"
TRANSCRIPT_LANGUAGE = "pt"
TRANSCRIPT_CACHE_DIR = CACHE_DIR / "transcripts"

TranscriberFactory = Callable[[], Transcriber]


def coverage_from_session(session: dict[str, Source], cameras: list[str]) -> list[Coverage]:
    """Uma `Coverage` por parte (fonte com `parts`) ou pela fonte inteira, para cada nome em `cameras`."""
    coverage: list[Coverage] = []
    for name in cameras:
        if name in session:
            source = session[name]
            assert source.info is not None
            coverage.append(Coverage(name, source.offset, source.offset + source.info.duration))
            continue
        k = 0
        while f"{name}#{k}" in session:
            source = session[f"{name}#{k}"]
            assert source.info is not None
            coverage.append(Coverage(name, source.offset, source.offset + source.info.duration))
            k += 1
    return coverage


def speech_from_cues(cues: list[Cue], part_offset: float) -> list[Speech]:
    """Cues (tempos do arquivo) para o relógio da sessão, somando o deslocamento da parte."""
    return [Speech(c.start + part_offset, c.end + part_offset, c.text) for c in cues]


def block_to_plan(block: MulticamBlock) -> MulticamPlan:
    """Bloco da spec para os parâmetros puros de `plan_cuts` ("casamento" usa as fases do rito católico)."""
    if block.phases == "casamento":
        phases = default_wedding_phases()
    else:
        phases = tuple(
            PhaseRule(p.name, tuple(p.match), p.main, p.cadence, p.max_duration) for p in block.phases
        )
    return MulticamPlan(
        cameras=tuple(block.cameras),
        main=block.main,
        audio=block.audio,
        cadence=block.cadence,
        phases=phases,
        min_clip=block.min_clip,
        snap_window=block.snap_window,
        pause=block.pause,
    )


def clips_from_plan(clips: list[PlannedClip], block: MulticamBlock) -> list[ClipSegment]:
    """Clipes planejados como trechos da spec: transição só no primeiro, rótulo da fase por padrão."""
    return [
        ClipSegment(
            source=clip.camera,
            start=clip.start,
            end=clip.end,
            mute=clip.mute,
            volume=1.0,
            label=block.label or clip.label,
            transition=block.transition_in if i == 0 else None,
        )
        for i, clip in enumerate(clips)
    ]


def expand_multicam(project: Project, planned: list[ClipSegment]) -> Project:
    """Insere os clipes planejados em `multicam.at` e remove o bloco, preservando `base_dir`."""
    assert project.multicam is not None
    at = project.multicam.at
    timeline = [*project.timeline[:at], *planned, *project.timeline[at:]]
    updated = project.model_copy(update={"timeline": timeline, "multicam": None})
    updated.base_dir = project.base_dir
    return updated


@dataclass
class PlanResult:
    """Resultado de `plan_multicam`, para quem chamou conferir o corte sem reabrir a spec salva."""

    clips: int
    warnings: list[str]
    phases: list[tuple[str, float]]  # fase reconhecida e instante da sessão em que abriu
    speech_seconds: float
    start: float
    end: float


def _default_transcriber() -> Transcriber:
    return WhisperTranscriber(model=TRANSCRIPT_MODEL, device="cpu")


def _transcript_cache_key(path: Path, model: str, language: str) -> str:
    st = path.stat()
    raw = f"{path}|{st.st_mtime_ns}|{st.st_size}|{model}|{language}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _cached_transcript(
    path: Path,
    transcriber: Transcriber,
    runner: FFmpegRunner,
    language: str,
    model: str,
    cache_dir: Path,
) -> list[Cue]:
    """Transcreve com cache em disco por arquivo (caminho, data de modificação, tamanho, modelo, idioma)."""
    key = _transcript_cache_key(path, model, language)
    store = cache_dir / f"{key}.json"
    if store.exists():
        try:
            return from_json(store.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    wav = cache_dir / f"{key}.wav"
    extract_audio_wav(runner, path, wav)
    transcript = transcriber.transcribe(wav, language)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(to_json(transcript.cues, language), encoding="utf-8")
    return transcript.cues


def _audio_parts(project: Project, block: MulticamBlock) -> list[str]:
    """Chaves da sessão (nome, ou nome#k para fonte com `parts`) da fonte de áudio do bloco, em ordem."""
    ref = project.sources[block.audio]
    if not ref.parts:
        return [block.audio]
    return [f"{block.audio}#{k}" for k in range(len(ref.parts))]


def plan_multicam(
    name_or_path: str | Path,
    prober: Prober = probe,
    transcriber_factory: TranscriberFactory | None = None,
    offset_finder: OffsetFinder | None = None,
    runner: FFmpegRunner | None = None,
    log: Callable[[str], None] | None = None,
    cache_dir: Path = TRANSCRIPT_CACHE_DIR,
) -> PlanResult:
    """Planeja o corte de um bloco `multicam`: transcreve a câmera de áudio, reconhece as fases pela
    fala, gera os clipes alternando câmeras e salva o projeto com o bloco já expandido no lugar."""
    log = log or (lambda message: None)
    project = load_project(name_or_path)
    if project.multicam is None:
        raise ValueError(f"{project.name}: sem bloco multicam para planejar")
    block = project.multicam

    runner = runner or SubprocessRunner(quiet=True)
    finder = offset_finder or ffmpeg_offset_finder(runner)
    store = (project.base_dir / "sync.json") if project.base_dir else None
    resolution = SyncResolver(finder, log=log, prober=prober).resolve(project, store)
    session = resolve_session(project, prober, resolution.offsets, resolution.parts)

    names = list(dict.fromkeys([*block.cameras, block.audio]))
    coverage = coverage_from_session(session, names)
    # o relógio da sessão começa na fonte principal: o que uma câmera gravou antes disso (posição
    # negativa) não entra na linha do tempo, porque um trecho não pode começar antes de 0
    start = block.start if block.start is not None else max(min(c.start for c in coverage), 0.0)
    end = block.end if block.end is not None else max(c.end for c in coverage)

    transcriber = (transcriber_factory or _default_transcriber)()
    parts = _audio_parts(project, block)
    speech: list[Speech] = []
    for i, key in enumerate(parts, start=1):
        source = session[key]
        assert source.path is not None
        log(f"transcrevendo {block.audio} parte {i} de {len(parts)}...")
        cues = _cached_transcript(
            source.path, transcriber, runner, TRANSCRIPT_LANGUAGE, TRANSCRIPT_MODEL, cache_dir
        )
        speech.extend(speech_from_cues(cues, source.offset))

    plan = block_to_plan(block)
    clips, cut_warnings = plan_cuts(plan, coverage, speech, start, end)
    windows = phase_windows(plan, speech, start, end)

    updated = expand_multicam(project, clips_from_plan(clips, block))
    _save_project(updated, project.base_dir)

    return PlanResult(
        clips=len(clips),
        warnings=[*cut_warnings, *resolution.warnings],
        phases=[(label, window_start) for label, window_start, _window_end in windows],
        speech_seconds=sum(s.end - s.start for s in speech),
        start=start,
        end=end,
    )
