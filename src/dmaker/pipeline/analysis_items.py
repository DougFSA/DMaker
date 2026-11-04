"""De um alvo (`timeline.2`, `audio.voiceover.0`, `audio.music`...) ao áudio que ele toca: o arquivo, de onde a que
ponto, com que ganho e com que cadeia de efeitos, e como o tempo do item vira tempo da linha do tempo do projeto.

Os alvos são os mesmos dos efeitos de áudio. O item é visto "como soa": se tem efeitos ligados, a análise lê o arquivo
já processado pelo `EffectProcessor` (o mesmo que o render usa), e o ganho do item (`volume`) entra por cima. Nada aqui
decodifica ou mede; isso é do `audio_analysis.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..domain.audio_effects import EffectBase, chain_duration
from ..domain.music_tempo import music_chain
from ..domain.spec import ClipSegment, Project, VideoOverlay
from ..filtergraph.audio import resolve_span
from ..filtergraph.mezzanine import uses_camera_audio
from ..media.ffmpeg import FFmpegRunner
from ..voice.library import VoiceLibrary
from .context import Prober
from .layout import ProjectLayout
from .voicefiles import play_length
from .voiceover import narration_text

_TARGET = re.compile(r"(timeline|overlays|audio\.voiceover|audio\.narration|audio\.tracks)\.(\d+)")
ITEM_TARGETS = (
    "timeline.N",
    "overlays.N",
    "audio.voiceover.N",
    "audio.narration.N",
    "audio.music",
    "audio.tracks.N",
)


@dataclass(frozen=True)
class ItemClock:
    """Como o tempo do item (segundos do áudio dele, desde o ponto em que ele começa a tocar) vira tempo do projeto:
    `início + tempo / velocidade`. O `speed` do clipe é o que faz um segundo do áudio durar menos na linha do tempo."""

    start: float = 0.0
    speed: float = 1.0

    def to_project(self, item_time: float) -> float:
        return self.start + item_time / self.speed

    def to_item(self, project_time: float) -> float:
        return (project_time - self.start) * self.speed


@dataclass(frozen=True)
class ItemAudio:
    """O áudio de um item: `duration` segundos do arquivo `path` a partir de `offset` (faixa `stream`), com a cadeia
    `effects` e o ganho linear `gain`. `clock` é None quando o item não tem lugar certo na linha do tempo (uma faixa
    externa, sincronizada por sessão): ele pode ser medido, mas não marcado. Com `whole_file`, os efeitos valem para o
    arquivo inteiro (música, faixa externa) e o `offset` recorta o arquivo já processado."""

    label: str
    path: Path
    offset: float
    duration: float
    stream: int = 0
    effects: tuple[EffectBase, ...] = ()
    gain: float = 1.0
    clock: ItemClock | None = None
    whole_file: bool = False
    file_duration: float = 0.0
    notes: tuple[str, ...] = ()


class TargetError(ValueError):
    """O alvo não existe, não tem som ou não pode ser analisado agora."""


def parse_target(target: str) -> tuple[str, int | None]:
    """`audio.voiceover.2` -> ("audio.voiceover", 2); `audio.music` -> ("audio.music", None)."""
    text = target.strip()
    if text == "audio.music":
        return text, None
    found = _TARGET.fullmatch(text)
    if found is None:
        raise TargetError(
            f"alvo de análise inválido: {target!r}. Use {', '.join(ITEM_TARGETS)}, output (a saída renderizada) "
            "ou informe um arquivo"
        )
    return found.group(1), int(found.group(2))


def _check_index(count: int, index: int, what: str) -> None:
    if not 0 <= index < count:
        raise TargetError(f"{what} {index} não existe (o projeto tem {count})")


def resolve_item(
    project: Project,
    layout: ProjectLayout,
    target: str,
    *,
    prober: Prober,
    runner: FFmpegRunner,
    library: VoiceLibrary | None = None,
) -> ItemAudio:
    """O áudio do alvo, ou `TargetError` dizendo por que ele não tem som para analisar."""
    kind, index = parse_target(target)
    if kind == "audio.music":
        return _music(project, layout, prober)
    assert index is not None
    resolver = _RESOLVERS[kind]
    return resolver(project, layout, index, prober, runner, library)


# ---------- um resolvedor por tipo de alvo ----------


def _clip(project, layout, index, prober, runner, library) -> ItemAudio:
    _check_index(len(project.timeline), index, "trecho")
    physical = next((p for p, origin in enumerate(layout.origin) if origin == index), index)
    segment, source = layout.project.timeline[physical], layout.sources[physical]
    if not isinstance(segment, ClipSegment) or source.path is None or source.info is None:
        raise TargetError(f"timeline.{index} não é um clipe de vídeo: só ele tem som para analisar")
    if not uses_camera_audio(segment, source.info):
        raise TargetError(
            f"timeline.{index} não toca o som da câmera (o clipe está mudo ou o arquivo não tem áudio)"
        )
    in_point = source.in_point(segment.start) if segment.source else segment.start
    notes = ()
    if segment.audio_mode != "original":
        notes = ("o clipe usa o áudio isolado (voz ou fundo); a análise lê o som original da câmera.",)
    start = layout.spans[physical][0]
    return ItemAudio(
        label=f"Clipe {index + 1} ({source.path.name})",
        path=source.path,
        offset=max(in_point, 0.0),
        duration=layout.durations[physical] * segment.speed,
        stream=source.audio_stream,
        effects=tuple(segment.effects),
        gain=segment.volume,
        clock=ItemClock(start, segment.speed),
        notes=notes,
    )


def _pip(project, layout, index, prober, runner, library) -> ItemAudio:
    _check_index(len(project.overlays), index, "sobreposição")
    overlay = project.overlays[index]
    if not isinstance(overlay, VideoOverlay):
        raise TargetError(f"overlays.{index} não é um vídeo sobreposto (PiP): só ele tem som para analisar")
    if overlay.source:
        source = layout.session.get(overlay.source)
        if source is None or source.path is None or source.info is None:
            raise TargetError(f"overlays.{index}: a fonte {overlay.source!r} não está no projeto")
        path, info, in_point, stream = (
            source.path,
            source.info,
            source.in_point(overlay.offset),
            source.audio_stream,
        )
    else:
        path = project.resolve(overlay.src or "")
        if not path.exists():
            raise TargetError(f"overlays.{index}: arquivo não encontrado: {overlay.src}")
        info, in_point, stream = prober(path), overlay.offset, 0
    if not info.has_audio or overlay.volume <= 0:
        raise TargetError(f"overlays.{index} não toca som (o arquivo não tem áudio ou o volume é zero)")
    end = min(overlay.end if overlay.end is not None else layout.total, layout.total)
    return ItemAudio(
        label=f"PiP {index + 1} ({path.name})",
        path=path,
        offset=max(in_point, 0.0),
        duration=max(end - overlay.start, 0.0),
        stream=stream,
        effects=tuple(overlay.effects),
        gain=overlay.volume,
        clock=ItemClock(overlay.start),
    )


def _voice_file(project, layout, index, prober, runner, library) -> ItemAudio:
    _check_index(len(project.audio.voiceover), index, "voz gravada")
    clip = project.audio.voiceover[index]
    path = project.resolve(clip.src)
    if not path.exists():
        raise TargetError(f"audio.voiceover.{index}: arquivo não encontrado: {clip.src}")
    info = prober(path)
    if not info.has_audio:
        raise TargetError(f"audio.voiceover.{index}: o arquivo {clip.src!r} não tem áudio")
    return ItemAudio(
        label=f"Voz gravada {index + 1} ({path.name})",
        path=path,
        offset=clip.offset,
        duration=play_length(clip, info.duration),
        effects=tuple(clip.effects),
        gain=clip.volume,
        clock=ItemClock(clip.start),
    )


def _narration(project, layout, index, prober, runner, library) -> ItemAudio:
    """A narração só é analisada se já foi sintetizada (o cache dela): analisar não gasta minutos de síntese."""
    from .preview_audio import default_narrator

    _check_index(len(project.audio.narration), index, "narração")
    narration = project.audio.narration[index]
    service = default_narrator(runner)
    voices = library or VoiceLibrary()
    text = narration_text(project, narration)
    voice = voices.get(narration.voice) if narration.voice else None
    settings = {
        "language": narration.language,
        "speed": narration.speed,
        "instruct": narration.instruct,
        "seed": narration.seed,
    }
    if service.cached_duration(text, voice, brand=project.brand, **settings) is None:
        raise TargetError(
            f"audio.narration.{index} ainda não foi sintetizada: renderize o projeto (ou gere a fala) antes de analisar"
        )
    cache = _narration_cache_dir()
    result = service.render(text, cache / f"narration_{index}.wav", voice, brand=project.brand, **settings)
    return ItemAudio(
        label=f"Narração {index + 1}",
        path=result.path,
        offset=0.0,
        duration=result.duration,
        effects=tuple(narration.effects),
        gain=narration.volume,
        clock=ItemClock(narration.start),
    )


def _narration_cache_dir() -> Path:
    from .. import config

    folder = config.CACHE_DIR / "analysis"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _music(project, layout, prober) -> ItemAudio:
    music = project.audio.music
    if music is None:
        raise TargetError("o projeto não tem música (audio.music)")
    path = project.resolve(music.src)
    if not path.exists():
        raise TargetError(f"audio.music: arquivo não encontrado: {music.src}")
    info = prober(path)
    notes: tuple[str, ...] = ()
    if music.spans:
        start, end, start_at = resolve_span(music.spans[0], layout.total, info.duration)
        if len(music.spans) > 1:
            notes = ("a música tem várias janelas; a análise vale para a primeira.",)
    else:
        start, end, start_at = 0.0, None, music.start_at
        if music.loop:
            notes = ("a música está em loop; a análise vale para a primeira volta do arquivo.",)
    until = layout.total if end is None else min(end, layout.total)
    chain = music_chain(project.audio)
    # o arquivo depois da cadeia (o esticamento até o andamento do projeto muda o quanto ele toca)
    playable = chain_duration(chain, info.duration)
    return ItemAudio(
        label=f"Música ({path.name})",
        path=path,
        offset=start_at,
        duration=max(min(playable - start_at, until - start), 0.0),
        effects=chain,
        gain=music.volume,
        clock=ItemClock(start),
        whole_file=True,
        file_duration=info.duration,
        notes=notes,
    )


def _track(project, layout, index, prober, runner, library) -> ItemAudio:
    _check_index(len(project.audio.tracks), index, "faixa externa")
    track = project.audio.tracks[index]
    source = layout.session.get(track.source)
    if source is None or source.path is None or source.info is None or not source.info.has_audio:
        raise TargetError(f"audio.tracks.{index}: a fonte {track.source!r} não tem áudio")
    return ItemAudio(
        label=f"Faixa {index + 2} ({source.path.name})",
        path=source.path,
        offset=0.0,
        duration=source.info.duration,
        stream=source.audio_stream,
        effects=tuple(track.effects),
        gain=track.volume,
        clock=None,  # a faixa é fatiada por clipe e sincronizada por sessão: não há um único lugar na linha do tempo
        whole_file=True,
        file_duration=source.info.duration,
    )


_RESOLVERS = {
    "timeline": _clip,
    "overlays": _pip,
    "audio.voiceover": _voice_file,
    "audio.narration": _narration,
    "audio.tracks": _track,
}
