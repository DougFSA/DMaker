"""Exportação de áudio em vários arquivos: por região de marcador, por trilha, ou só um intervalo.

Parte do mesmo `PreparedAudio` do render (`pipeline/audio_render.py`), então o som é o do render de vídeo e da prévia.

- **Por trilha** (`stems`): uma única passada do ffmpeg grava todas as trilhas. Cada uma leva o mesmo ganho linear da
  normalização da mixagem, sem normalização própria nem limitador, e é por isso que a soma dos arquivos reproduz a
  mixagem. Os efeitos do master (cadeia de efeitos) são aplicados depois da soma e não entram nas trilhas: elas saem
  antes deles.
- **Por região e seleção**: a mixagem vai uma vez para um WAV de ponto flutuante (referência, apagado no fim) e cada
  arquivo é cortado dele, medido e normalizado sozinho. Um arquivo por região é uma entrega própria, então cada um
  chega ao alvo de loudness; o corte é exato (a referência é PCM de 48 kHz) e a duração do arquivo é a da região.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..domain.audio_effects import active_effects
from ..domain.audio_export import (
    ExportFile,
    ExportMode,
    ExportRequest,
    region_files,
    selection_file,
    stem_files,
)
from ..domain.audio_presets import AudioEncoding, AudioPreset
from ..domain.spec import Project
from ..filtergraph.audio import StemTaps, loudnorm_filter
from ..filtergraph.audio_output import encode_args, format_filters, linear_normalization_applies
from ..media.ffmpeg import FFmpegCommand
from .assembly import LoudnessMeasure, graph_args, loudnorm_report
from .audio_render import AudioRenderPipeline, PreparedAudio, output_tags
from .output_kinds import output_path_in

SILENT_RANGE = "esse trecho é praticamente silencioso: a normalização de loudness foi pulada nele."


@dataclass(frozen=True)
class ExportedFile:
    """Um arquivo gravado: onde, o que é e quanto dura."""

    path: Path
    name: str
    kind: str
    start: float
    duration: float
    track: str | None = None


@dataclass
class ExportResult:
    mode: ExportMode
    preset: AudioPreset
    files: list[ExportedFile]
    warnings: list[str] = field(default_factory=list)
    folder: Path | None = None
    commands: list[str] = field(default_factory=list)


def spec_stem_tracks(project: Project) -> list[str]:
    """As trilhas de som que o projeto tem, lidas da spec: o que o gate do agente e o exportador usam para dizer
    quais arquivos a exportação por trilha grava."""
    from ..domain.audio_export import available_stems

    audio = project.audio
    plays_sfx = bool(audio.sfx) or any(getattr(overlay, "sound", None) for overlay in project.overlays)
    return available_stems(
        has_clips=bool(project.timeline) and not audio.mute_clips,
        narrations=sum(1 for item in audio.narration if item.volume > 0),
        voice_files=sum(1 for item in audio.voiceover if item.volume > 0),
        has_music=audio.music is not None and audio.music.volume > 0,
        has_sfx=plays_sfx,
    )


def plan_files(project: Project, request: ExportRequest) -> list[ExportFile]:
    """Os arquivos que o pedido gera, em ordem. Erros claros (sem regiões, marcador inexistente) saem daqui."""
    if request.mode == "regions":
        return region_files(project.markers, request.group, pauses=request.pauses, numbered=request.numbered)
    if request.mode == "selection":
        return [selection_file(project.markers, request.start, request.end)]
    if request.mode == "stems":
        return stem_files(spec_stem_tracks(project), request.tracks)
    return [ExportFile("mix", 0.0, None)]


def destinations(
    project: Project,
    request: ExportRequest,
    preset: AudioPreset,
    *,
    out: Path | str | None = None,
    out_dir: Path | str | None = None,
    output_dir: Path,
) -> tuple[list[tuple[ExportFile, Path]], Path | None]:
    """Cada arquivo do pedido com o caminho onde ele vai, e a pasta quando são vários.

    Sem `out` (um arquivo) nem `out_dir` (uma pasta), vai para `output/`: o arquivo único com o nome de sempre do
    render, e os vários numa pasta `projeto__preset__regioes` (ou `__trilhas`)."""
    files = plan_files(project, request)
    extension = preset.extension
    if request.mode in ("mix", "selection"):
        suffix = "" if request.mode == "mix" else "__selecao"
        path = Path(out) if out else output_path_in(output_dir, project.name, preset.id, suffix, extension)
        return [(files[0], path)], None
    label = "regioes" if request.mode == "regions" else "trilhas"
    folder = (
        Path(out_dir) if out_dir else output_dir / f"{project.name}__{preset.id.replace('/', '-')}__{label}"
    )
    return [(item, folder / f"{item.name}{extension}") for item in files], folder


class AudioExporter:
    """Grava os arquivos do pedido a partir de um `AudioRenderPipeline` já montado."""

    def __init__(self, pipeline: AudioRenderPipeline):
        self.pipeline = pipeline
        self._modes: dict[ExportMode, Callable[..., list[ExportedFile]]] = {
            "mix": self._export_mix,
            "selection": self._export_ranges,
            "regions": self._export_ranges,
            "stems": self._export_stems,
        }

    def run(
        self,
        request: ExportRequest,
        *,
        out: Path | str | None = None,
        out_dir: Path | str | None = None,
    ) -> ExportResult:
        pipeline = self.pipeline
        encoding = pipeline.encoding()
        if out is None and request.mode in ("mix", "selection"):
            out = (
                pipeline.options.out
            )  # o `--out` do render vale para o arquivo único, como no render de vídeo
        planned, folder = destinations(
            pipeline.project,
            request,
            encoding.preset,
            out=out,
            out_dir=out_dir,
            output_dir=pipeline.output_dir,
        )
        job = pipeline.prepare()
        written = self._modes[request.mode](job, planned, encoding)
        commands = [" ".join(map(str, c)) for c in getattr(job.ctx.runner, "commands", [])]
        return ExportResult(request.mode, encoding.preset, written, job.ctx.warnings, folder, commands)

    # ---------- um arquivo: a mixagem inteira ----------

    def _export_mix(
        self, job: PreparedAudio, planned: list[tuple[ExportFile, Path]], encoding: AudioEncoding
    ) -> list[ExportedFile]:
        file, path = planned[0]
        self.pipeline.render_mix(job, path, encoding)
        return [ExportedFile(path, file.name, "mix", 0.0, job.total)]

    # ---------- uma trilha por arquivo ----------

    def _export_stems(
        self, job: PreparedAudio, planned: list[tuple[ExportFile, Path]], encoding: AudioEncoding
    ) -> list[ExportedFile]:
        pipeline = self.pipeline
        plan = pipeline.loudness(job)
        gain = plan.gain_db if plan.normalize else 0.0
        if (
            plan.normalize
            and plan.measured
            and not linear_normalization_applies(plan.measured, job.project.audio.target_lufs)
        ):
            job.ctx.warnings.append(
                "a normalização da mixagem não é linear neste projeto (o pico ou a variação de volume passam do "
                "limite): as trilhas levam o ganho limitado pelo pico, e a soma delas pode diferir do arquivo da mixagem."
            )
        if active_effects(job.project.audio.master_effects):
            job.ctx.warnings.append(
                "os efeitos do master (audio.master_effects) não entram nas trilhas: elas saem antes dele, e a soma "
                "delas não reproduz a mixagem."
            )
        taps = StemTaps(frozenset(item.track for item, _ in planned if item.track))
        inputs, lines, aout = pipeline.mix_graph(job, plan=None, stems=taps)
        lines.append(
            f"{aout}anullsink"
        )  # a mixagem em si não é gravada aqui; sem consumir a saída o ffmpeg recusa
        tail = format_filters(encoding)
        args = []
        tags, notes = output_tags(job.project, job.ctx.theme, encoding.preset, job.provenance)
        job.ctx.warnings.extend(notes)
        written = []
        for file, path in planned:
            label = taps.labels.get(file.track or "")
            if label is None:
                job.ctx.warnings.append(
                    f"a trilha {file.track} não tem som neste projeto e não foi exportada."
                )
                continue
            chain = [f"apad=whole_dur={job.total:.6f}", f"volume={gain:.6f}dB", *tail]
            lines.append(f"{label}{','.join(chain)}[stem_out_{file.track}]")
            path.parent.mkdir(parents=True, exist_ok=True)
            args += [
                "-map",
                f"[stem_out_{file.track}]",
                *encode_args(encoding, tags, path, duration=job.total),
            ]
            written.append(ExportedFile(path, file.name, "stem", 0.0, job.total, file.track))
        if written:
            command = [*graph_args(job.ctx, inputs, lines, "audio_stems.txt"), *args]
            job.ctx.log(f"gravando {len(written)} trilha(s)")
            job.ctx.runner.run(
                FFmpegCommand(command, label="trilhas de áudio", total=job.total, cwd=job.ctx.job_dir)
            )
        return written

    # ---------- um intervalo por arquivo: regiões e seleção ----------

    def _export_ranges(
        self, job: PreparedAudio, planned: list[tuple[ExportFile, Path]], encoding: AudioEncoding
    ) -> list[ExportedFile]:
        pipeline = self.pipeline
        ctx = job.ctx
        master = ctx.job_dir / "audio_master.wav"
        inputs, lines, aout = pipeline.mix_graph(job, plan=None)
        # a referência em ponto flutuante de 32 bits não perde nada da mixagem; cada arquivo sai dela
        ctx.runner.run(
            FFmpegCommand(
                [
                    *graph_args(ctx, inputs, lines, "audio_master.txt"),
                    *["-map", aout, "-vn", "-c:a", "pcm_f32le", "-t", f"{job.total:.6f}", str(master)],
                ],
                label="mixagem de referência",
                total=job.total,
                cwd=ctx.job_dir,
            )
        )
        written: list[ExportedFile] = []
        try:
            for position, (file, path) in enumerate(planned, 1):
                exported = self._export_range(job, master, file, path, encoding, position, len(planned))
                if exported is not None:
                    written.append(exported)
        finally:
            master.unlink(missing_ok=True)
        return written

    def _export_range(
        self,
        job: PreparedAudio,
        master: Path,
        file: ExportFile,
        path: Path,
        encoding: AudioEncoding,
        position: int,
        count: int,
    ) -> ExportedFile | None:
        ctx = job.ctx
        start = max(file.start, 0.0)
        end = job.total if file.end is None else min(file.end, job.total)
        if end - start <= 0:
            ctx.warnings.append(
                f"{file.name}: o trecho começa depois do fim do projeto ({job.total:.2f} s) e foi pulado."
            )
            return None
        if file.end is not None and file.end > job.total + 0.001:
            ctx.warnings.append(
                f"{file.name}: o trecho passa do fim do projeto e foi cortado em {job.total:.2f} s."
            )
        duration = end - start
        seek = ["-ss", f"{start:.6f}", "-t", f"{duration:.6f}", "-i", str(master)]
        audio = job.project.audio
        filters = self._normalization(job, seek, file, audio.normalize, audio.target_lufs)
        filters += format_filters(encoding)
        tags, notes = output_tags(job.project, ctx.theme, encoding.preset, job.provenance)
        tags = self._region_tags(tags, file, position, count)
        ctx.warnings.extend(note for note in notes if note not in ctx.warnings)
        path.parent.mkdir(parents=True, exist_ok=True)
        args = [*seek, *(["-af", ",".join(filters)] if filters else []), *encode_args(encoding, tags, path)]
        ctx.log(f"gravando {file.name}")
        ctx.runner.run(FFmpegCommand(args, label=f"exportando {file.name}", total=duration, cwd=ctx.job_dir))
        return ExportedFile(path, file.name, file.kind, start, duration)

    def _normalization(
        self, job: PreparedAudio, seek: list[str], file: ExportFile, mode: str, target: float
    ) -> list[str]:
        """O filtro de loudness do arquivo: mede o trecho e aplica o ganho linear dele (duas passadas), ou o modo
        dinâmico numa passada só. Trecho praticamente mudo não é normalizado: o `loudnorm` daria um valor sem sentido."""
        if mode == "off":
            return []
        ctx = job.ctx
        if mode == "fast" or ctx.options.dry_run:
            return [loudnorm_filter(target), "aresample=48000"]
        report = loudnorm_report(
            ctx.runner.capture(
                [*seek, "-af", f"{loudnorm_filter(target)}:print_format=json", "-f", "null", "-"],
                label=f"medição de loudness de {file.name}",
            )
        )
        measure = LoudnessMeasure(report)
        if report is None or measure.silent:
            ctx.warnings.append(f"{file.name}: {SILENT_RANGE}")
            return []
        return [loudnorm_filter(target, report), "aresample=48000"]

    @staticmethod
    def _region_tags(
        tags: list[tuple[str, str]], file: ExportFile, position: int, count: int
    ) -> list[tuple[str, str]]:
        """Numa exportação por região, cada arquivo é uma faixa: o título é o nome da região e o número é a posição
        dela, no lugar do título e da faixa do projeto (que seriam iguais em todos os arquivos)."""
        if file.kind != "region":
            return tags
        kept = [(key, value) for key, value in tags if key not in ("title", "track")]
        return [("title", file.name), ("track", f"{position}/{count}"), *kept]
