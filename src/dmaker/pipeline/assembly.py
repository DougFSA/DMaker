"""Montagem final: linha do tempo + sobreposições + ASS + áudio -> um comando ffmpeg. Medição de loudness."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..config import FONTS_DIR
from ..domain.spec import Transition
from ..filtergraph.audio import AudioTaps, audio_graph, loudnorm_measure_graph
from ..filtergraph.audiogram import audiogram_graph, normalization_gain_db
from ..filtergraph.behind_person import AssBehindLayer, BehindLayer, ResolvedPersonLayer, behind_person_graph
from ..filtergraph.common import Inputs, ffq
from ..filtergraph.encode import encode_args, resolve_encoder
from ..filtergraph.html_layer import HtmlBehindLayer, ResolvedHtmlLayer, html_overlay_graph
from ..filtergraph.overlays import image_overlay_graph
from ..filtergraph.pip import ResolvedVideoOverlay, pip_audio_graph, video_overlay_graph
from ..filtergraph.provenance import inherited_provenance_args
from ..filtergraph.sfx import SfxInput
from ..filtergraph.timeline import timeline_graph
from ..media.ffmpeg import FFmpegCommand, filter_complex_file_args, hardware_encoder
from .context import RenderContext
from .segments import PreparedSegment
from .textlayer import TextLayer
from .voicefiles import PreparedVoiceFile
from .voiceover import PreparedVoiceover

SILENCE_LUFS = -60.0
# a linha de comando do Windows aceita ~32 mil caracteres: acima deste tamanho o grafo vai para um arquivo
INLINE_GRAPH_LIMIT = 20_000


def _relpath(target: Path, base: Path) -> str:
    try:
        return os.path.relpath(target, base).replace("\\", "/")
    except ValueError:  # unidades diferentes
        return str(target)


def _finite(value: object) -> float | None:
    try:
        f = float(str(value))
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _music_duration(ctx: RenderContext, music_path: Path | None) -> float | None:
    """Duração da música, só quando algum span usa `tail` (evita uma sondagem desnecessária)."""
    music = ctx.project.audio.music
    if music_path is None or music is None or not any(span.tail for span in music.spans):
        return None
    return ctx.prober(music_path).duration


def graph_args(ctx: RenderContext, inputs: Inputs, lines: list[str], name: str) -> list[str]:
    """Entradas e grafo como argumentos do ffmpeg. Um projeto com centenas de trechos passa do limite da linha
    de comando, então o grafo grande vai para um arquivo da pasta do trabalho (`name`)."""
    graph = ";".join(lines)
    if len(graph) + sum(len(arg) + 1 for arg in inputs.args) < INLINE_GRAPH_LIMIT:
        return [*inputs.args, "-filter_complex", graph]
    path = ctx.job_dir / name
    path.write_text(graph, encoding="utf-8")
    return [*inputs.args, *filter_complex_file_args(str(path))]


def audio_only_graph(
    ctx: RenderContext,
    prepared: list[PreparedSegment],
    transitions: list[Transition | None],
    music_path: Path | None,
    total: float,
    voiceovers: Sequence[PreparedVoiceover],
    video_overlays: Sequence[ResolvedVideoOverlay],
    include_music: bool = True,
    sfx: Sequence[SfxInput] = (),
    voice_files: Sequence[PreparedVoiceFile] = (),
    *,
    include_norm: bool = False,
    measured: dict | None = None,
) -> tuple[Inputs, list[str], str]:
    """Entradas e linhas do grafo só de áudio, com a mesma mixagem da montagem final. Sem `include_norm` é a
    mistura antes da normalização (a que se mede); com ele, já normalizada, como sai do render (`measured` é a
    medição do modo two-pass). É o que o render mede e o que a prévia da linha do tempo mixa."""
    inputs = Inputs()
    for item in prepared:
        inputs.add(item.mezzanine)
    graph = timeline_graph(
        len(prepared), [p.duration for p in prepared], transitions, ctx.fps, want_video=False
    )
    lines = list(graph.lines)
    # o áudio dos PiPs entra na medição como entra na mixagem final; sem ele a medida não vale
    pip_audio = pip_audio_graph(lines, inputs, list(video_overlays))
    aout = audio_graph(
        lines,
        inputs,
        graph.audio,
        ctx.project.audio,
        music_path,
        total,
        measured=measured,
        include_music=include_music,
        include_norm=include_norm,
        extra_voices=pip_audio,
        music_duration=_music_duration(ctx, music_path),
        narrations=voiceovers,
        sfx=sfx,
        voice_files=voice_files,
    )
    return inputs, lines, aout


def _loudnorm_report(stderr: str) -> dict | None:
    """O último bloco JSON que o loudnorm imprime em modo de medição (None se não imprimiu nenhum)."""
    blocks = re.findall(r"\{[^{}]*\}", stderr)
    return json.loads(blocks[-1]) if blocks else None


@dataclass
class LoudnessMeasure:
    """Resultado da passada de medição do loudnorm (None = silêncio ou medição indisponível)."""

    values: dict | None

    @property
    def silent(self) -> bool:
        loudness = _finite(self.values.get("input_i")) if self.values else None
        return loudness is None or loudness < SILENCE_LUFS


class LoudnessMeter:
    """Roda só o grafo de áudio com loudnorm em modo de medição e lê o JSON do stderr."""

    def measure(
        self,
        ctx: RenderContext,
        prepared: list[PreparedSegment],
        transitions: list[Transition | None],
        music_path: Path | None,
        total: float,
        voiceovers: Sequence[PreparedVoiceover] = (),
        video_overlays: Sequence[ResolvedVideoOverlay] = (),
        sfx: Sequence[SfxInput] = (),
        voice_files: Sequence[PreparedVoiceFile] = (),
    ) -> LoudnessMeasure:
        inputs, lines, aout = audio_only_graph(
            ctx,
            prepared,
            transitions,
            music_path,
            total,
            voiceovers,
            video_overlays,
            sfx=sfx,
            voice_files=voice_files,
        )
        lines.append(loudnorm_measure_graph(aout, ctx.project.audio.target_lufs))
        args = [*graph_args(ctx, inputs, lines, "loudness.txt"), "-map", "[ameas]", "-f", "null", "-"]
        stderr = ctx.runner.capture(args, label="medição de loudness")
        data = _loudnorm_report(stderr)
        if data is None:
            return LoudnessMeasure(None)
        (ctx.job_dir / "loudnorm.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        return LoudnessMeasure(data)


@dataclass(frozen=True)
class LoudnessPlan:
    """Como a normalização de loudness vai ser aplicada: a medição (só no modo two-pass), se normaliza e o ganho
    (dB) que ela dá à saída, que os audiogramas repetem na cópia do áudio que leem."""

    measured: dict | None
    normalize: bool
    gain_db: float


def plan_loudness(
    ctx: RenderContext,
    meter: LoudnessMeter,
    prepared: list[PreparedSegment],
    transitions: list[Transition | None],
    music_path: Path | None,
    total: float,
    voiceovers: Sequence[PreparedVoiceover] = (),
    video_overlays: Sequence[ResolvedVideoOverlay] = (),
    sfx: Sequence[SfxInput] = (),
    voice_files: Sequence[PreparedVoiceFile] = (),
) -> LoudnessPlan:
    """Mede sempre (barato, só áudio): silêncio faz o loudnorm gerar NaN, então é pulado; a medição alimenta o
    modo linear (two-pass). "fast" usa o modo dinâmico, numa passada só. É a mesma decisão para o render e
    para a prévia da linha do tempo, que por isso têm o mesmo nível."""
    mode = ctx.project.audio.normalize
    if mode == "off" or ctx.options.dry_run:
        return LoudnessPlan(None, mode != "off", 0.0)
    measure = meter.measure(
        ctx, prepared, transitions, music_path, total, voiceovers, video_overlays, sfx, voice_files
    )
    if measure.silent:
        ctx.warn("Áudio praticamente silencioso: normalização de loudness pulada.")
        return LoudnessPlan(None, False, 0.0)
    gain = normalization_gain_db(measure.values, ctx.project.audio.target_lufs)
    return LoudnessPlan(measure.values if mode == "two-pass" else None, True, gain)


@dataclass(frozen=True)
class VoiceLevel:
    """Loudness integrado (LUFS) e pico verdadeiro (dBFS) da voz, antes da música, dos efeitos e da normalização."""

    loudness: float
    true_peak: float


class VoiceLevelMeter:
    """Mede a voz sozinha (áudio dos clipes, PiP, narração e arquivos de `audio.voiceover`; sem música nem
    efeitos) com o loudnorm em modo de medição: é a régua que acerta o nível dos efeitos sonoros, definido em
    relação a ela."""

    def measure(
        self,
        ctx: RenderContext,
        prepared: list[PreparedSegment],
        transitions: list[Transition | None],
        total: float,
        voiceovers: Sequence[PreparedVoiceover] = (),
        video_overlays: Sequence[ResolvedVideoOverlay] = (),
        voice_files: Sequence[PreparedVoiceFile] = (),
    ) -> VoiceLevel | None:
        """None quando não há voz (clipes mudos, só música) ou a medição não devolveu números."""
        inputs, lines, aout = audio_only_graph(
            ctx,
            prepared,
            transitions,
            None,
            total,
            voiceovers,
            video_overlays,
            include_music=False,
            voice_files=voice_files,
        )
        lines.append(loudnorm_measure_graph(aout, ctx.project.audio.target_lufs, "[vmeas]"))
        args = [*graph_args(ctx, inputs, lines, "voice_level.txt"), "-map", "[vmeas]", "-f", "null", "-"]
        data = _loudnorm_report(ctx.runner.capture(args, label="medição da voz"))
        if data is None or LoudnessMeasure(data).silent:
            return None
        loudness, true_peak = _finite(data.get("input_i")), _finite(data.get("input_tp"))
        if loudness is None or true_peak is None:
            return None
        return VoiceLevel(loudness, true_peak)


@dataclass
class Assembly:
    command: FFmpegCommand
    graph: list[str]


def build_assembly(
    ctx: RenderContext,
    prepared: list[PreparedSegment],
    transitions: list[Transition | None],
    total: float,
    layer: TextLayer,
    music_path: Path | None,
    measured: dict | None,
    normalize: bool,
    out_path: Path,
    voiceovers: Sequence[PreparedVoiceover] = (),
    provenance: str = "",
    sfx: Sequence[SfxInput] = (),
    voice_files: Sequence[PreparedVoiceFile] = (),
    visual_gain_db: float = 0.0,
    person_layers: Sequence[ResolvedPersonLayer] = (),
    html_layers: Sequence[ResolvedHtmlLayer] = (),
) -> Assembly:
    """Comando final. O grafo vai em arquivo (graph.txt) e o ASS é referenciado por caminho relativo
    ao diretório do job, o que evita a escapada de `C:` nos filtros. `visual_gain_db` é o ganho que a
    normalização aplica à saída, repetido na cópia do áudio que os audiogramas leem. `person_layers` são os
    vídeos da pessoa recortada que passam por cima do texto `behind-person` (ver `pipeline/person_layer.py`).
    `html_layers` são os vídeos com alfa das composições em HTML (ver `pipeline/html_layer.py`): as da frente entram
    logo depois das imagens, e as `behind-person` na pilha de trás da pessoa, antes do texto dela."""
    p, o = ctx.project, ctx.options
    inputs = Inputs()
    for item in prepared:
        inputs.add(item.mezzanine)
    graph = timeline_graph(
        len(prepared),
        [x.duration for x in prepared],
        transitions,
        ctx.fps,
        want_video=True,
        size=(ctx.width, ctx.height),
    )
    lines = list(graph.lines)
    cur_v = graph.video or ""
    # a pilha de profundidade vem logo depois da linha do tempo: o que fica atrás da pessoa, depois a pessoa; as
    # imagens, as composições da frente, o PiP, os audiogramas e o ASS da frente entram por cima de tudo isso
    behind: list[BehindLayer] = [HtmlBehindLayer(item, ctx.fps) for item in html_layers if item.behind]
    if layer.has_behind_text:
        behind.append(AssBehindLayer("overlay_behind.ass", _relpath(FONTS_DIR, ctx.job_dir)))
    if behind or person_layers:
        cur_v = behind_person_graph(lines, inputs, cur_v, behind, person_layers, ctx.fps)
    cur_v = image_overlay_graph(
        lines,
        inputs,
        cur_v,
        layer.image_overlays,
        ctx.width,
        ctx.height,
        ctx.fps,
        total,
        ctx.scale,
        ctx.preset.safe,
    )
    cur_v = html_overlay_graph(
        lines, inputs, cur_v, [item for item in html_layers if not item.behind], ctx.fps
    )
    cur_v, pip_audio = video_overlay_graph(
        lines,
        inputs,
        cur_v,
        layer.video_overlays,
        ctx.width,
        ctx.height,
        ctx.fps,
        total,
        ctx.scale,
        ctx.preset.safe,
    )
    # o áudio entra primeiro numa lista própria: o audiograma precisa das cópias que ele devolve, e as linhas
    # do áudio seguem no fim do grafo, onde sempre estiveram
    audio_lines: list[str] = []
    taps = AudioTaps(frozenset(item.follow for item in layer.audiograms))
    aout = audio_graph(
        audio_lines,
        inputs,
        graph.audio,
        p.audio,
        music_path,
        total,
        measured=measured,
        include_norm=normalize,
        extra_voices=pip_audio,
        music_duration=_music_duration(ctx, music_path),
        narrations=voiceovers,
        sfx=sfx,
        voice_files=voice_files,
        taps=taps if layer.audiograms else None,
    )
    if layer.audiograms:
        cur_v = audiogram_graph(
            lines,
            inputs,
            cur_v,
            layer.audiograms,
            taps,
            visual_gain_db,
            ctx.width,
            ctx.height,
            ctx.fps,
            total,
            ctx.scale,
            ctx.preset.safe,
        )
    if layer.has_text:
        lines.append(
            f"{cur_v}ass=filename={ffq('overlay.ass')}:fontsdir={ffq(_relpath(FONTS_DIR, ctx.job_dir))}[v_ass]"
        )
        cur_v = "[v_ass]"
    lines.append(f"{cur_v}format=yuv420p[vout]")
    lines += audio_lines

    quality = "draft" if o.preview else p.output.quality
    encoder = "x264" if o.preview else resolve_encoder(p.output.encoder, hardware_encoder())
    args = inputs.args + filter_complex_file_args("graph.txt") + ["-map", "[vout]", "-map", aout]
    args += encode_args(ctx.preset, quality, encoder, ctx.fps) + inherited_provenance_args(provenance)
    args += ["-shortest", str(out_path)]
    return Assembly(FFmpegCommand(args, label="montagem final", total=total, cwd=ctx.job_dir), lines)
