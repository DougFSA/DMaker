"""Orquestração do render: fontes -> mezaninos -> legendas -> camada de texto -> montagem -> saída."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..config import JOBS_DIR, MEZ_DIR, OUTPUT_DIR, ensure_dirs
from ..domain.brand import load_theme
from ..domain.presets import Preset, get_preset
from ..domain.spec import Project
from ..domain.timeline import segment_duration, timeline_spans, timeline_total, transitions_of
from ..media.ffmpeg import FFmpegCommand, FFmpegRunner, RecordingRunner, SubprocessRunner, format_cmd
from ..media.probe import probe
from .assembly import LoudnessMeter, build_assembly
from .captions import CaptionPipeline, TranscriberFactory, default_transcriber_factory
from .context import Prober, RenderContext, RenderOptions, RenderResult
from .lint import lint
from .segments import MezzanineBuilder
from .sources import resolve_session, resolve_sources
from .sync import OffsetFinder, SyncResolver, ffmpeg_offset_finder
from .textlayer import build_text_layer


class RenderPipeline:
    """Recebe as dependências por injeção: runner do ffmpeg, probe e transcritor são trocáveis nos testes."""

    def __init__(
        self,
        project: Project,
        options: RenderOptions | None = None,
        *,
        runner: FFmpegRunner | None = None,
        prober: Prober = probe,
        transcriber_factory: TranscriberFactory = default_transcriber_factory,
        mezzanines: MezzanineBuilder | None = None,
        cache_dir: Path = MEZ_DIR,
        jobs_dir: Path = JOBS_DIR,
        output_dir: Path = OUTPUT_DIR,
        log: Callable[[str], None] | None = None,
        offset_finder: OffsetFinder | None = None,
    ):
        self.project = project
        self.options = options or RenderOptions()
        if runner is None:
            runner = RecordingRunner() if self.options.dry_run else SubprocessRunner(quiet=self.options.quiet)
        self.runner = runner
        self.prober = prober
        self.mezzanines = mezzanines or MezzanineBuilder()
        self.captions = CaptionPipeline(transcriber_factory)
        self.loudness = LoudnessMeter()
        self.log = log or (lambda message: None)
        self.sync = SyncResolver(offset_finder or ffmpeg_offset_finder(self.runner), self.log)
        self.cache_dir = cache_dir
        self.jobs_dir = jobs_dir
        self.output_dir = output_dir

    # ---------- preparação ----------

    def _context(self) -> RenderContext:
        ensure_dirs()
        p, o = self.project, self.options
        theme = load_theme(p.brand, p.theme)
        preset = get_preset(o.preset or p.output.preset)
        if o.preview:
            preset = preset.preview()
        job_dir = self.jobs_dir / (p.name + ("_preview" if o.preview else ""))
        job_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return RenderContext(
            project=p,
            options=o,
            theme=theme,
            preset=preset,
            fps=p.output.fps or preset.fps,
            job_dir=job_dir,
            cache_dir=self.cache_dir,
            runner=self.runner,
            prober=self.prober,
            log=self.log,
        )

    def _output_path(self, preset: Preset) -> Path:
        p, o = self.project, self.options
        if o.out:
            return Path(o.out).resolve()
        if p.output.path and not o.preview:
            return p.resolve(p.output.path)
        suffix = "__preview" if o.preview else ""
        return self.output_dir / f"{p.name}__{preset.id.replace('/', '-')}{suffix}.mp4"

    # ---------- execução ----------

    def run(self) -> RenderResult:
        ctx = self._context()
        p, o = ctx.project, ctx.options

        ctx.log(
            f"render {p.name}: {ctx.preset.id} {ctx.width}x{ctx.height}" + (" (preview)" if o.preview else "")
        )
        p = ctx.project = self._sliced(p, o, ctx)
        offsets = self.sync.resolve(p, (p.base_dir or ctx.job_dir) / "sync.json")
        ctx.session = resolve_session(p, ctx.prober, offsets)
        sources = resolve_sources(p, ctx.prober, ctx.session)
        infos = [s.info for s in sources]
        transitions = transitions_of(p.timeline)
        durations = [
            segment_duration(seg, src.info, src.offset) for seg, src in zip(p.timeline, sources, strict=True)
        ]
        total = timeline_total(durations, transitions)
        ctx.warnings.extend(
            lint(p, ctx.theme, ctx.preset, total, durations, infos, [s.offset for s in sources])
        )

        prepared = self.mezzanines.prepare(ctx, sources)
        pending = sum(1 for item in prepared if item.command is not None)
        ctx.log(f"trechos: {len(prepared)} ({pending} a gerar, {len(prepared) - pending} em cache)")
        self.mezzanines.build(ctx, prepared)
        durations = [item.duration for item in prepared]
        total = timeline_total(durations, transitions)
        spans = timeline_spans(durations, transitions)
        tones = [item.tone for item in prepared]

        if p.captions and p.captions.enabled and not o.no_captions:
            ctx.log(
                "legendas: "
                + ("transcrição automática" if p.captions.source == "auto" else p.captions.source)
            )
        captions = self.captions.produce(ctx, sources, prepared, transitions)
        guides = o.guides if o.guides is not None else p.output.guides
        layer = build_text_layer(ctx, total, spans, tones, captions.cues if captions else None, guides)
        layer.doc.write(ctx.job_dir / "overlay.ass")

        music_path = self._music_path()
        measured, normalize = self._loudness(ctx, prepared, transitions, music_path, total)
        out_path = self._output_path(ctx.preset)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        assembly = build_assembly(
            ctx, prepared, transitions, total, layer, music_path, measured, normalize, out_path
        )
        (ctx.job_dir / "graph.txt").write_text(";".join(assembly.graph), encoding="utf-8")
        (ctx.job_dir / "graph.pretty.txt").write_text(";\n".join(assembly.graph), encoding="utf-8")
        ctx.log("montagem final")
        ctx.runner.run(assembly.command)
        ctx.log(f"pronto: {out_path}")

        commands = [format_cmd(c) for c in getattr(ctx.runner, "commands", [])]
        (ctx.job_dir / "cmd.txt").write_text("\n\n".join(commands), encoding="utf-8")
        thumbnail = self._thumbnail(ctx, out_path, total)
        return RenderResult(
            output=out_path,
            duration=total,
            preset=ctx.preset,
            warnings=ctx.warnings,
            thumbnail=thumbnail,
            captions_file=captions.file if captions else None,
            commands=commands,
            job_dir=ctx.job_dir,
            size_bytes=out_path.stat().st_size if out_path.exists() and not o.dry_run else 0,
        )

    @staticmethod
    def _sliced(project: Project, options: RenderOptions, ctx: RenderContext) -> Project:
        """Render parcial: mantém só os trechos pedidos, sem sobreposições nem legendas (tempos absolutos
        deixariam de bater). Serve para revisar cortes de um vídeo longo sem renderizar tudo."""
        if options.segments is None:
            return project
        first, last = options.segments
        if first < 0 or last >= len(project.timeline) or first > last:
            raise ValueError(
                f"segmentos {first}-{last} fora da linha do tempo (0 a {len(project.timeline) - 1})"
            )
        ctx.log(f"render parcial: trechos {first} a {last} (sem sobreposições e legendas)")
        sliced = project.model_copy(
            update={"timeline": project.timeline[first : last + 1], "overlays": [], "captions": None}
        )
        sliced.base_dir = project.base_dir
        sliced.timeline[0] = sliced.timeline[0].model_copy(update={"transition": None})
        return sliced

    def _music_path(self) -> Path | None:
        music = self.project.audio.music
        if not music:
            return None
        path = self.project.resolve(music.src)
        if not path.exists():
            raise FileNotFoundError(f"Música não encontrada: {music.src}")
        return path

    def _loudness(self, ctx, prepared, transitions, music_path, total) -> tuple[dict | None, bool]:
        """Mede sempre (barato, só áudio): silêncio faz o loudnorm gerar NaN, então é pulado; a medição
        alimenta o modo linear (two-pass). "fast" usa o modo dinâmico, numa passada só."""
        mode = ctx.project.audio.normalize
        if mode == "off" or ctx.options.dry_run:
            return None, mode != "off"
        measure = self.loudness.measure(ctx, prepared, transitions, music_path, total)
        if measure.silent:
            ctx.warn("Áudio praticamente silencioso: normalização de loudness pulada.")
            return None, False
        return (measure.values if mode == "two-pass" else None), True

    def _thumbnail(self, ctx: RenderContext, out_path: Path, total: float) -> Path | None:
        if not ctx.options.thumbnail or ctx.options.dry_run:
            return None
        at = ctx.project.output.thumbnail_at
        t = at if at is not None else min(total * 0.15, max(total - 0.1, 0))
        thumb = out_path.with_suffix(".jpg")
        args = ["-ss", f"{t:.3f}", "-i", str(out_path), "-frames:v", "1", "-q:v", "2", str(thumb)]
        ctx.runner.run(FFmpegCommand(args, label="thumbnail"))
        return thumb
