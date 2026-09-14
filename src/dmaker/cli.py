"""Interface de linha de comando do DMaker. Só traduz argumentos em chamadas aos serviços."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from . import __version__, config
from .domain.presets import get_preset, list_presets

for _stream in (sys.stdout, sys.stderr):
    try:  # acentos no console do Windows
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

app = typer.Typer(
    help="DMaker: editor de vídeos curtos por comando (Instagram, Facebook, YouTube, TikTok, WhatsApp).",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)
console = Console()
err = Console(stderr=True, style="bold red")

RENDER_ERRORS: tuple[type[Exception], ...] = (FileNotFoundError, ValueError, KeyError, RuntimeError)


def _fail(message: str) -> None:
    err.print(message)
    raise typer.Exit(code=1)


def _load(spec: Path):
    from .pipeline.projects import load_project

    try:
        return load_project(spec)
    except FileNotFoundError as exc:
        _fail(str(exc))
    except ValidationError as exc:
        _fail(f"Spec inválida ({spec}):\n{exc}")
    except json.JSONDecodeError as exc:
        _fail(f"JSON inválido em {spec}: {exc}")


def _print_result(result) -> None:
    mb = result.size_bytes / 1e6
    console.print(
        f"[green]Pronto:[/green] {result.output}  ({result.duration:.1f}s, {mb:.1f} MB, "
        f"{result.preset.id} {result.preset.width}x{result.preset.height})"
    )
    if result.thumbnail:
        console.print(f"  thumbnail: {result.thumbnail}")
    if result.captions_file:
        console.print(f"  legendas: {result.captions_file}")
    for w in result.warnings:
        console.print(f"[yellow]aviso:[/yellow] {w}")


def _print_qa_summary(spec: Path, project, preset: str | None, output: Path) -> None:
    """Contagem e achados de erro/aviso do relatório de QA, ao final de um render local."""
    from .pipeline.report import build_report

    report_project = project
    if preset:
        report_project = project.model_copy(
            update={"output": project.output.model_copy(update={"preset": preset})}
        )
    try:
        report = build_report(report_project, output=output)
    except Exception as exc:  # noqa: BLE001 - QA é um extra; não deve interromper o render
        console.print(f"[yellow]QA não pôde ser gerado: {exc}[/yellow]")
        return
    counts = {"erro": 0, "aviso": 0, "info": 0}
    for f in report.findings:
        counts[f.level] = counts.get(f.level, 0) + 1
    console.print(
        f"QA: {counts['erro']} erro(s), {counts['aviso']} aviso(s), {counts['info']} info(s) "
        f"(dmaker qa {spec} --output {output} para o relatório completo)"
    )
    for f in report.findings:
        if f.level in ("erro", "aviso"):
            console.print(f"  {f.level}: {f.where}: {f.message}", markup=False, highlight=False)


def _project_name_for_ui(spec: Path, project) -> str | None:
    """Nome do projeto para a interface: só quando a spec está no layout padrão projects/<nome>/spec.json
    (a interface só conhece projetos por nome, não caminhos de spec avulsos)."""
    from .pipeline.projects import project_path

    try:
        return project.name if project_path(project.name).resolve() == spec.resolve() else None
    except OSError:
        return None


def _console_log(message: str) -> None:
    console.print(f"  {message}", markup=False, highlight=False)


def _make_dispatcher():
    from .pipeline.remote import RenderDispatcher, UIClient

    return RenderDispatcher(UIClient(), log=_console_log)


def _render_options_body(options) -> dict:
    return {
        "preview": options.preview,
        "preset": options.preset,
        "force": options.force,
        "guides": bool(options.guides),
        "no_captions": options.no_captions,
        "segments": f"{options.segments[0]}-{options.segments[1]}" if options.segments else None,
    }


def _print_ui_result(result: dict) -> None:
    console.print(f"[green]Pronto (pela interface):[/green] {result.get('output')}")
    if result.get("thumbnail"):
        console.print(f"  thumbnail: {result['thumbnail']}")
    if result.get("captions_file"):
        console.print(f"  legendas: {result['captions_file']}")
    for w in result.get("warnings") or []:
        console.print(f"[yellow]aviso:[/yellow] {w}")


@app.callback()
def _main(version: Annotated[bool, typer.Option("--version", help="Mostra a versão.")] = False) -> None:
    if version:
        console.print(f"dmaker {__version__}")
        raise typer.Exit()


# ---------- ambiente ----------


@app.command()
def doctor(
    hw: Annotated[bool, typer.Option(help="Testa encoders de hardware (nvenc/amf/qsv).")] = True,
) -> None:
    """Verifica FFmpeg, fontes, marcas e dependências opcionais."""
    from .domain.brand import available_brands
    from .media import fonts

    console.print(f"[bold]DMaker {__version__}[/bold]  raiz: {config.ROOT}")
    exe = config.find_tool("ffmpeg")
    if not exe or not config.find_tool("ffprobe"):
        console.print("[red]FFmpeg/ffprobe não encontrados.[/red] Rode: dmaker setup")
    else:
        from .media.ffmpeg import capabilities, encoder_works

        caps = capabilities()
        console.print(f"[green]ffmpeg[/green] {caps.version}  ({exe})")
        console.print(
            f"  libass: {'sim' if caps.libass else '[red]NÃO (texto e legendas não funcionam)[/red]'}"
        )
        needed = ["xfade", "acrossfade", "loudnorm", "sidechaincompress", "ass", "tile", "lut3d"]
        missing = [f for f in needed if not caps.has_filter(f)]
        console.print(
            f"  filtros: {'ok' if not missing else '[red]faltam: ' + ', '.join(missing) + '[/red]'}"
        )
        if hw:
            from .media.ffmpeg import hardware_encoder

            for enc in ("h264_nvenc", "h264_amf", "h264_qsv"):
                ok = caps.has_encoder(enc) and encoder_works(enc)
                console.print(f"  {enc}: {'[green]disponível[/green]' if ok else 'indisponível'}")
            chosen = hardware_encoder()
            console.print(f'  encoder de hardware para "encoder": "auto": {chosen or "nenhum (x264)"}')
    for fam in ("Poppins", "Bahnschrift", "Arial"):
        console.print(f"  fonte {fam}: {'ok' if fonts.family_available(fam) else '[yellow]ausente[/yellow]'}")
    console.print(f"  marcas: {', '.join(available_brands())}")
    try:
        import faster_whisper  # noqa: F401

        console.print("  faster-whisper: ok (legendas automáticas)")
    except ImportError:
        console.print("  faster-whisper: [yellow]não instalado[/yellow] (pip install -e .[captions])")
    try:
        import mcp  # noqa: F401

        console.print("  mcp: ok (servidor para IAs: dmaker mcp)")
    except ImportError:
        console.print("  mcp: [yellow]não instalado[/yellow]")
    for name, d in (
        ("cache", config.CACHE_DIR),
        ("saída", config.OUTPUT_DIR),
        ("projetos", config.PROJECTS_DIR),
    ):
        console.print(f"  {name}: {d}")


@app.command()
def setup(force: Annotated[bool, typer.Option(help="Baixa de novo mesmo se já existir.")] = False) -> None:
    """Baixa FFmpeg (bin/ffmpeg), a fonte Poppins (assets/fonts) e o modelo de recorte de pessoa."""
    from .media.matting import ensure_model, model_path
    from .setup_tools import install_ffmpeg, install_fonts

    config.ensure_dirs()
    install_ffmpeg(force=force)
    install_fonts(force=force)
    if force and model_path().exists():
        model_path().unlink()
    console.print(f"[green]Modelo de recorte (RVM):[/green] {ensure_model()}")


@app.command()
def presets(
    platform: Annotated[
        str | None, typer.Argument(help="Filtra por plataforma (instagram, youtube...)")
    ] = None,
) -> None:
    """Lista os formatos de saída disponíveis."""
    table = Table(title="Presets")
    for col in ("id", "plataforma", "formato", "tamanho", "fps", "max", "zona segura (t/b/l/r)", "obs"):
        table.add_column(col)
    for p in list_presets(platform):
        table.add_row(
            p.id,
            p.platform,
            p.name,
            f"{p.width}x{p.height}",
            f"{p.fps:g}",
            f"{p.max_duration:.0f}s" if p.max_duration else "-",
            f"{p.safe.top}/{p.safe.bottom}/{p.safe.left}/{p.safe.right}",
            p.notes,
        )
    console.print(table)


@app.command()
def probe(files: Annotated[list[Path], typer.Argument(help="Arquivos de vídeo, imagem ou áudio.")]) -> None:
    """Mostra duração, tamanho, fps e áudio dos arquivos."""
    from .media.probe import probe as _probe

    table = Table(title="Mídia")
    for col in ("arquivo", "tipo", "tamanho", "duração", "fps", "áudio", "orientação"):
        table.add_column(col)
    for f in files:
        try:
            info = _probe(f)
        except Exception as exc:  # noqa: BLE001 - mostra o erro na tabela
            table.add_row(str(f), "[red]erro[/red]", str(exc), "", "", "", "")
            continue
        kind = "imagem" if info.is_image else ("vídeo" if info.has_video else "áudio")
        table.add_row(
            f.name,
            kind,
            f"{info.width}x{info.height}" if info.width else "-",
            f"{info.duration:.2f}s",
            f"{info.fps:.3g}" if info.fps else "-",
            "sim" if info.has_audio else "não",
            info.orientation,
        )
    console.print(table)


# ---------- projetos ----------


@app.command()
def new(
    name: Annotated[str, typer.Argument(help="Nome do projeto (vira pasta em projects/).")],
    preset: Annotated[str, typer.Option(help="Formato de saída (dmaker presets).")] = "instagram/reels",
    src: Annotated[list[Path] | None, typer.Option("--src", help="Vídeos/imagens fonte, na ordem.")] = None,
    brand: Annotated[str | None, typer.Option(help="Marca (medlycare) ou vazio para o tema padrão.")] = None,
    captions: Annotated[bool, typer.Option(help="Incluir legendas automáticas.")] = True,
    logo: Annotated[bool, typer.Option(help="Incluir logo da marca no canto.")] = False,
) -> None:
    """Cria projects/<nome>/spec.json a partir dos arquivos fonte."""
    from .pipeline.projects import save_project, scaffold_project

    try:
        project = scaffold_project(name, preset, src, brand, captions, logo)
    except (FileNotFoundError, KeyError, ValidationError) as exc:
        _fail(str(exc))
    path = save_project(project)
    console.print(f"[green]Projeto criado:[/green] {path}")
    console.print(f"Edite a spec e rode: dmaker render {path}")


@app.command(name="templates")
def list_templates_cmd() -> None:
    """Lista os templates disponíveis (templates/*.json) e os parâmetros de cada um."""
    from .domain.templates import list_templates as _list_templates
    from .domain.templates import template_summary

    for t in _list_templates():
        console.print(template_summary(t))
        console.print()


@app.command(name="new-from-template")
def new_from_template_cmd(
    template: Annotated[str, typer.Argument(help="Nome do template (dmaker templates).")],
    name: Annotated[str, typer.Argument(help="Nome do projeto (vira pasta em projects/).")],
    param: Annotated[
        list[str] | None,
        typer.Option(
            "--param", help='Parâmetro "chave=valor" (listas separadas por vírgula). Repita para cada um.'
        ),
    ] = None,
    params_json: Annotated[
        str | None,
        typer.Option("--params-json", help='Parâmetros como um JSON só, ex.: \'{"titulo": "..."}\'.'),
    ] = None,
) -> None:
    """Cria projects/<nome>/spec.json a partir de um template + parâmetros (dmaker templates lista as opções)."""
    from .domain.templates import TemplateError, find_template
    from .pipeline.projects import project_from_template, project_path, summarize

    try:
        tmpl = find_template(template)
    except TemplateError as exc:
        _fail(str(exc))

    params: dict = {}
    if params_json:
        try:
            params.update(json.loads(params_json))
        except json.JSONDecodeError as exc:
            _fail(f"--params-json inválido: {exc}")
    for item in param or []:
        key, sep, value = item.partition("=")
        if not sep:
            _fail(f'--param inválido: "{item}" (use chave=valor)')
        params[key] = _coerce_param(tmpl, key, value)

    try:
        project = project_from_template(tmpl.name, name, params)
    except (TemplateError, FileNotFoundError, ValidationError) as exc:
        _fail(str(exc))
    try:
        s = summarize(project)
    except RENDER_ERRORS as exc:
        _fail(str(exc))
    console.print(
        f"[green]Projeto criado a partir do template {tmpl.name!r}:[/green] {project_path(name)} "
        f"({s.total:.1f}s, {len(s.segments)} trechos)"
    )
    for w in s.warnings:
        console.print(f"[yellow]aviso:[/yellow] {w}")


def _coerce_param(template, key: str, value: str):
    """Converte o texto vindo de `--param chave=valor` para o tipo declarado no template."""
    param_type = template.params[key].type if key in template.params else None
    if param_type in ("list", "paths"):
        return [v.strip() for v in value.split(",")] if "," in value else [value]
    if param_type == "number":
        return float(value) if "." in value else int(value)
    if param_type == "bool":
        return value.strip().lower() in ("1", "true", "sim", "yes")
    return value


@app.command()
def validate(spec: Annotated[Path, typer.Argument(help="Caminho do spec.json")]) -> None:
    """Valida a spec, confere arquivos e mostra a duração final e avisos."""
    from .pipeline.projects import summarize

    project = _load(spec)
    try:
        s = summarize(project)
    except RENDER_ERRORS as exc:
        _fail(str(exc))
    console.print(
        f"[green]Spec válida.[/green] {s.name}: {len(s.segments)} trechos, {s.total:.1f}s, "
        f"{s.preset.id} ({s.preset.width}x{s.preset.height}), tema {s.theme.name}"
    )
    for seg in s.segments:
        console.print(f"  [{seg.index}] {seg.type:5s} {seg.duration:6.2f}s  {seg.label}")
    for w in s.warnings:
        console.print(f"[yellow]aviso:[/yellow] {w}")


@app.command()
def render(
    spec: Annotated[Path, typer.Argument(help="Caminho do spec.json")],
    preview: Annotated[bool, typer.Option(help="Render rápido em baixa resolução para conferir.")] = False,
    dry_run: Annotated[bool, typer.Option(help="Só mostra os comandos ffmpeg.")] = False,
    force: Annotated[bool, typer.Option(help="Ignora o cache de trechos e legendas.")] = False,
    out: Annotated[Path | None, typer.Option(help="Arquivo de saída.")] = None,
    preset: Annotated[str | None, typer.Option(help="Sobrescreve o preset da spec.")] = None,
    guides: Annotated[
        bool | None, typer.Option("--guides/--no-guides", help="Desenha as zonas seguras.")
    ] = None,
    no_captions: Annotated[bool, typer.Option(help="Não gera legendas.")] = False,
    quiet: Annotated[bool, typer.Option(help="Sem barra de progresso.")] = False,
    segments: Annotated[
        str | None,
        typer.Option(help="Render parcial só destes trechos, ex.: 12-20 (para revisar vídeos longos)."),
    ] = None,
    no_ui: Annotated[
        bool, typer.Option("--no-ui", help="Roda só no terminal; não usa a interface gráfica.")
    ] = False,
) -> None:
    """Renderiza o projeto no formato da plataforma. Por padrão abre a interface para acompanhar."""
    from .media.ffmpeg import FFmpegError, NullSink, RichSink
    from .pipeline import RenderOptions, RenderPipeline
    from .pipeline.projects import parse_segments

    project = _load(spec)
    options = RenderOptions(
        preview=preview,
        dry_run=dry_run,
        force=force,
        quiet=quiet,
        guides=guides,
        out=out,
        preset=preset,
        no_captions=no_captions,
        segments=parse_segments(segments),
    )
    dispatcher = None
    ui_name = None if (dry_run or no_ui or out) else _project_name_for_ui(spec, project)
    if ui_name:
        dispatcher = _make_dispatcher()
        try:
            dispatcher.ensure_ui()
        except RuntimeError as exc:
            console.print(f"[yellow]{exc} Rodando localmente.[/yellow]")
            dispatcher = None
    if dispatcher:
        sink = NullSink() if quiet else RichSink()
        try:
            snapshot = dispatcher.render(ui_name, _render_options_body(options), sink, _console_log)
        except RuntimeError as exc:
            _fail(str(exc))
        _print_ui_result(snapshot.get("result") or {})
        return

    try:
        result = RenderPipeline(project, options).run()
    except (FFmpegError, *RENDER_ERRORS) as exc:
        _fail(str(exc))
    if dry_run:
        for c in result.commands:
            console.print(c, markup=False, highlight=False)
            console.print()
        return
    _print_result(result)
    if not preview and not segments:
        _print_qa_summary(spec, project, preset, result.output)


@app.command()
def export(
    spec: Annotated[Path, typer.Argument(help="Caminho do spec.json")],
    presets: Annotated[
        list[str], typer.Argument(help="Presets de saída (ex.: instagram/reels youtube/shorts).")
    ],
    preview: Annotated[bool, typer.Option(help="Versões rápidas de conferência.")] = False,
    no_ui: Annotated[
        bool, typer.Option("--no-ui", help="Roda só no terminal; não usa a interface gráfica.")
    ] = False,
) -> None:
    """Exporta o mesmo projeto para vários formatos de uma vez. Por padrão abre a interface para acompanhar."""
    from .media.ffmpeg import FFmpegError, RichSink
    from .pipeline import RenderOptions, RenderPipeline

    project = _load(spec)
    for p in presets:
        get_preset(p)

    dispatcher = None
    ui_name = None if no_ui else _project_name_for_ui(spec, project)
    if ui_name:
        dispatcher = _make_dispatcher()
        try:
            dispatcher.ensure_ui()
        except RuntimeError as exc:
            console.print(f"[yellow]{exc} Rodando localmente.[/yellow]")
            dispatcher = None

    for p in presets:
        console.rule(p)
        if dispatcher:
            try:
                snapshot = dispatcher.render(
                    ui_name, {"preview": preview, "preset": p}, RichSink(), _console_log
                )
            except RuntimeError as exc:
                _fail(str(exc))
            _print_ui_result(snapshot.get("result") or {})
            continue
        try:
            result = RenderPipeline(project, RenderOptions(preview=preview, preset=p)).run()
        except (FFmpegError, *RENDER_ERRORS) as exc:
            _fail(str(exc))
        _print_result(result)


# ---------- ferramentas ----------


@app.command()
def captions(
    video: Annotated[Path, typer.Argument(help="Vídeo ou áudio para transcrever.")],
    lang: Annotated[str, typer.Option(help="Idioma (pt, en, es...).")] = "pt",
    model: Annotated[str, typer.Option(help="tiny | base | small | medium | large-v3")] = "small",
    out: Annotated[Path | None, typer.Option(help="Arquivo .srt de saída (também gera .json).")] = None,
    max_words: Annotated[int, typer.Option(help="Palavras por linha.")] = 4,
    max_chars: Annotated[int, typer.Option(help="Caracteres por linha.")] = 22,
    device: Annotated[str, typer.Option(help="cpu | cuda")] = "cpu",
) -> None:
    """Transcreve com faster-whisper e gera .srt (linhas curtas) e .json (tempo por palavra)."""
    from .config import CACHE_DIR
    from .media.ffmpeg import SubprocessRunner
    from .text.captions import regroup, save_captions
    from .text.transcribe import WhisperTranscriber, extract_audio_wav

    if not video.exists():
        _fail(f"Arquivo não encontrado: {video}")
    console.print(f"Transcrevendo {video.name} ({model}, {lang})...")
    try:
        wav = extract_audio_wav(
            SubprocessRunner(quiet=True), video, CACHE_DIR / "audio" / f"{video.stem}.16k.wav"
        )
        transcript = WhisperTranscriber(model=model, device=device).transcribe(wav, lang)
    except RuntimeError as exc:
        _fail(str(exc))
    out = out or video.with_suffix(".srt")
    save_captions(transcript.cues, out.with_suffix(".json"), lang)
    lines = regroup(transcript.cues, max_words, max_chars)
    save_captions(lines, out.with_suffix(".srt"))
    meta = transcript.meta
    console.print(
        f"[green]{len(transcript.cues)} trechos, {len(lines)} linhas[/green] -> {out.with_suffix('.srt')} e .json "
        f"(idioma detectado: {meta.get('language')}, {meta.get('language_probability', 0):.0%})"
    )


@app.command()
def sync(
    master: Annotated[Path, typer.Argument(help="Fonte principal (relógio da sessão).")],
    others: Annotated[list[Path], typer.Argument(help="Outras câmeras ou gravadores do mesmo evento.")],
    master_stream: Annotated[int, typer.Option(help="Faixa de áudio da fonte principal.")] = 0,
    stream: Annotated[int, typer.Option(help="Faixa de áudio das outras fontes.")] = 0,
) -> None:
    """Descobre pelo áudio em que instante do relógio da fonte principal cada outra fonte começa."""
    from .config import CACHE_DIR
    from .media.audiosync import sync_offset
    from .media.ffmpeg import FFmpegError, SubprocessRunner

    for f in (master, *others):
        if not f.exists():
            _fail(f"Arquivo não encontrado: {f}")
    runner = SubprocessRunner(quiet=True)
    console.print(f"Fonte principal: {master.name}")
    for other in others:
        try:
            result = sync_offset(runner, master, other, CACHE_DIR / "audio" / "sync", master_stream, stream)
        except FFmpegError as exc:
            _fail(str(exc))
        flag = "" if result.reliable else "  [yellow](baixa confiança, confira)[/yellow]"
        console.print(
            f"  {other.name}: começa em [green]{result.offset:+.3f} s[/green]  confiança {result.confidence:.1f}{flag}"
        )
    console.print(
        'Na spec: "sources": {"cam2": {"src": "...", "sync": <valor>}} (ou "sync": "auto" para calcular no render).'
    )


@app.command()
def thumbnail(
    video: Annotated[Path, typer.Argument()],
    at: Annotated[float, typer.Option(help="Instante em segundos.")] = 1.0,
    out: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Extrai um quadro como imagem (capa)."""
    from .pipeline.qa import frame_at

    out = out or video.with_name(f"{video.stem}_{at:.1f}s.jpg")
    frame_at(video, at, out)
    console.print(f"[green]Quadro salvo:[/green] {out}")


@app.command()
def sheet(
    video: Annotated[Path, typer.Argument()],
    out: Annotated[Path | None, typer.Option()] = None,
    cols: Annotated[int, typer.Option()] = 3,
    rows: Annotated[int, typer.Option()] = 3,
    width: Annotated[int, typer.Option(help="Largura de cada quadro.")] = 360,
) -> None:
    """Grade de quadros do vídeo inteiro (para revisar de uma vez)."""
    from .pipeline.qa import contact_sheet

    if not video.exists():
        _fail(f"Arquivo não encontrado: {video}")
    out = out or video.with_name(f"{video.stem}_sheet.png")
    contact_sheet(video, out, cols, rows, width)
    console.print(f"[green]Grade salva:[/green] {out}")


@app.command()
def qa(
    spec: Annotated[Path, typer.Argument(help="Caminho do spec.json")],
    output: Annotated[
        Path | None,
        typer.Option(
            help="Vídeo já renderizado para conferir junto (duração, resolução, quadros pretos, "
            "silêncio, loudness). Sem isso, só as checagens estáticas da spec."
        ),
    ] = None,
) -> None:
    """Relatório de QA em texto: o que dá para checar sem olhar imagem."""
    from .media.ffmpeg import FFmpegError
    from .pipeline.report import build_report

    project = _load(spec)
    try:
        report = build_report(project, output=output)
    except (FFmpegError, *RENDER_ERRORS) as exc:
        _fail(str(exc))
    console.print(report.to_text(), markup=False, highlight=False)


@app.command()
def frames(
    video: Annotated[Path, typer.Argument()],
    times: Annotated[list[float], typer.Argument(help="Instantes em segundos.")],
    out_dir: Annotated[Path | None, typer.Option()] = None,
    width: Annotated[int, typer.Option()] = 540,
) -> None:
    """Extrai quadros em instantes específicos."""
    from .pipeline.qa import frame_at

    out_dir = out_dir or video.parent / f"{video.stem}_frames"
    for t in times:
        console.print(f"  {frame_at(video, t, out_dir / f'{video.stem}_{t:06.2f}s.jpg', width)}")


@app.command()
def card(
    title: Annotated[str, typer.Argument()],
    subtitle: Annotated[str | None, typer.Option()] = None,
    brand: Annotated[str | None, typer.Option()] = "medlycare",
    preset: Annotated[str, typer.Option()] = "instagram/reels",
    variant: Annotated[str | None, typer.Option(help="light | dark")] = None,
    out: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Gera um cartão (PNG) com o visual da marca, para conferir o design."""
    from .domain.brand import load_theme
    from .visuals.cards import render_card, save_card

    theme = load_theme(brand)
    p = get_preset(preset)
    img = render_card(theme, p.width, p.height, title, subtitle, variant, True, None, p.safe)
    out = out or config.OUTPUT_DIR / f"card_{p.id.replace('/', '-')}.png"
    save_card(img, out)
    console.print(f"[green]Cartão salvo:[/green] {out}")


@app.command()
def quick(
    src: Annotated[Path, typer.Argument(help="Vídeo fonte.")],
    preset: Annotated[str, typer.Option()] = "instagram/reels",
    start: Annotated[float, typer.Option(help="Entrada (s).")] = 0.0,
    end: Annotated[float | None, typer.Option(help="Saída (s).")] = None,
    reframe: Annotated[str, typer.Option(help="auto | crop | pad | blur | brand")] = "auto",
    brand: Annotated[str | None, typer.Option()] = None,
    captions: Annotated[bool, typer.Option(help="Legendas automáticas.")] = False,
    logo: Annotated[bool, typer.Option(help="Logo da marca no canto.")] = False,
    hook: Annotated[str | None, typer.Option(help="Texto de gancho no topo (primeiros 3 s).")] = None,
    cta: Annotated[str | None, typer.Option(help="Chamada no final (últimos 4 s).")] = None,
    music: Annotated[Path | None, typer.Option(help="Trilha de fundo.")] = None,
    preview: Annotated[bool, typer.Option()] = False,
    out: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Edição rápida de um único vídeo: corte + formato + (legenda, logo, gancho, CTA, música)."""
    from .media.ffmpeg import FFmpegError
    from .pipeline import RenderOptions, RenderPipeline
    from .pipeline.projects import quick_project, save_project

    try:
        project = quick_project(src, preset, start, end, reframe, brand, captions, logo, hook, cta, music)
        save_project(project)
        result = RenderPipeline(project, RenderOptions(preview=preview, out=out)).run()
    except (FFmpegError, ValidationError, *RENDER_ERRORS) as exc:
        _fail(str(exc))
    _print_result(result)


@app.command()
def clean(
    jobs: Annotated[
        bool, typer.Option(help="Apaga também cache/jobs (grafos, ASS, áudio de transcrição).")
    ] = False,
) -> None:
    """Limpa o cache de trechos intermediários (cache/mez), proxies de prévia (cache/proxy) e formas
    de onda (cache/waveform)."""
    import shutil

    n = 0
    for d in (config.MEZ_DIR, config.PROXY_DIR, config.WAVEFORM_DIR):
        if d.exists():
            n += sum(1 for _ in d.iterdir())
            shutil.rmtree(d)
    if jobs and config.JOBS_DIR.exists():
        shutil.rmtree(config.JOBS_DIR)
    config.ensure_dirs()
    console.print(f"[green]Cache limpo[/green] ({n} arquivos).")


@app.command()
def proxies(
    name: Annotated[str, typer.Argument(help="Nome do projeto (pasta em projects/).")],
) -> None:
    """Gera os proxies 540p H.264 para a prévia ao vivo na interface (cache/proxy) e mostra o status."""
    from .media.ffmpeg import FFmpegError, RichSink, SubprocessRunner
    from .pipeline.projects import load_project
    from .pipeline.proxies import ProxyBuilder

    try:
        project = load_project(name)
    except FileNotFoundError as exc:
        _fail(str(exc))
    except ValidationError as exc:
        _fail(f"Spec inválida ({name}):\n{exc}")
    builder = ProxyBuilder(SubprocessRunner(quiet=True), log=lambda m: console.print(f"  {m}"))
    try:
        statuses = builder.build(project, sink=RichSink())
    except (FFmpegError, *RENDER_ERRORS) as exc:
        _fail(str(exc))
    table = Table(title=f"Proxies de prévia: {project.name}")
    for col in ("fonte", "proxy", "status"):
        table.add_column(col)
    for st in statuses:
        status = "[green]pronto[/green]" if st.ready else "[red]faltou[/red]"
        table.add_row(st.src.name, str(st.proxy), status)
    console.print(table)


@app.command()
def ui(
    port: Annotated[int, typer.Option(help="Porta local.")] = 8765,
    no_browser: Annotated[bool, typer.Option("--no-browser", help="Não abre o navegador.")] = False,
) -> None:
    """Abre a interface gráfica (http://127.0.0.1:8765): projetos, editor, preview e progresso em tempo real."""
    from .ui.server import serve

    console.print(f"[green]DMaker UI[/green] em http://127.0.0.1:{port}  (Ctrl+C para parar)")
    serve(port=port, open_browser=not no_browser)


@app.command()
def mcp() -> None:
    """Sobe o servidor MCP (stdio) para qualquer IA operar o DMaker."""
    from .mcp_server import main

    main()


def _agent_tool_call_line(name: str, arguments: dict) -> str:
    parts = []
    for key, value in arguments.items():
        try:
            rendered = json.dumps(value, ensure_ascii=False)
        except TypeError:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return f"  -> {name}({', '.join(parts)})"


def _agent_on_event(kind: str, data: dict) -> None:
    if kind == "tool_call":
        console.print(_agent_tool_call_line(data["name"], data["arguments"]), style="dim", markup=False)
    elif kind == "tool_result":
        first_line = (data["result"] or "").splitlines()[0] if data["result"] else ""
        console.print(f"  <- {first_line}", style="dim", markup=False)


@app.command()
def agent(
    model: Annotated[str, typer.Option(help="Modelo do Ollama.")] = "gpt-oss:20b",
    url: Annotated[str | None, typer.Option(help="Endereço do servidor Ollama.")] = None,
    num_ctx: Annotated[int, typer.Option(help="Tamanho do contexto (tokens).")] = 16384,
    once: Annotated[str | None, typer.Option(help="Executa um único pedido e sai.")] = None,
) -> None:
    """Opera o DMaker por um modelo local do Ollama: tarefas mecânicas (template, render, QA, legendas).

    Cortes, ritmo, multicâmera e textos da marca continuam sendo trabalho de uma IA maior ou de uma
    pessoa; veja a seção "Operador local com Ollama" do README.
    """
    import os

    from .agent import AgentLoop, McpToolHost, OllamaChat, system_prompt
    from .agent.llm import OLLAMA_URL_ENV

    base_url = url or os.environ.get(OLLAMA_URL_ENV, "http://127.0.0.1:11434")
    chat = OllamaChat(model=model, base_url=base_url, num_ctx=num_ctx)

    if not chat.is_alive():
        _fail(f"Ollama não está rodando em {base_url}; abra o app do Ollama ou rode `ollama serve`.")
    if not chat.has_model():
        _fail(f"Modelo '{model}' não encontrado no Ollama; rode `ollama pull {model}`.")

    loop = AgentLoop(model=chat, tools=McpToolHost(), system=system_prompt(), on_event=_agent_on_event)

    def _ask(message: str) -> str | None:
        try:
            with console.status("pensando...", spinner="dots"):
                return loop.ask(message)
        except (OSError, ValueError) as exc:
            console.print(f"[red]Erro de comunicação com o Ollama: {exc}[/red]")
            return None

    if once is not None:
        answer = _ask(once)
        if answer is not None:
            console.print(answer, markup=False)
        return

    console.print(
        "[bold]Agente DMaker[/bold] (modelo local via Ollama). "
        "/sair encerra, /limpar reinicia a conversa, /ferramentas lista o que ele pode usar."
    )
    while True:
        try:
            message = console.input("[bold]você>[/bold] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not message:
            continue
        if message == "/sair":
            break
        if message == "/limpar":
            loop.reset()
            console.print("[dim]histórico limpo.[/dim]")
            continue
        if message == "/ferramentas":
            for spec in McpToolHost().specs():
                console.print(f"  {spec.name}: {spec.description}", markup=False, highlight=False)
            continue
        answer = _ask(message)
        if answer is not None:
            console.print(answer, markup=False)


if __name__ == "__main__":  # pragma: no cover
    app()
