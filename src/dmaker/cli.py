"""Interface de linha de comando do DMaker. Só traduz argumentos em chamadas aos serviços."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Column, Table
from typer.core import TyperGroup

from . import __version__, config
from .domain.models import format_size
from .domain.presets import get_preset, list_presets

app = typer.Typer(
    help="DMaker: editor de vídeos curtos por comando (Instagram, Facebook, YouTube, TikTok, WhatsApp).",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)


@app.callback()
def _console_utf8() -> None:
    """Acentos no console do Windows: só quando a CLI roda de verdade, não ao importar o módulo
    (um teste que importa `dmaker.cli` não pode mudar a codificação do stderr do processo)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


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
        if value.lstrip().startswith("["):  # lista em JSON, para itens que têm vírgula dentro
            return json.loads(value)
        return [v.strip() for v in value.split(",")] if "," in value else [value]
    if param_type == "number":
        return float(value) if "." in value else int(value)
    if param_type == "bool":
        return value.strip().lower() in ("1", "true", "sim", "yes")
    return value


def _format_mmss(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


@app.command()
def plan(
    name: Annotated[
        str, typer.Argument(help="Nome do projeto (pasta em projects/) ou caminho da spec.json.")
    ],
) -> None:
    """Planeja o corte automático de um bloco `multicam`: transcreve a câmera de áudio, reconhece as
    fases da cerimônia pela fala e substitui o bloco pelos clipes concretos, alternando as câmeras."""
    from .pipeline.multicam_plan import plan_multicam as _plan_multicam

    try:
        result = _plan_multicam(name, log=lambda m: console.print(f"  {m}", markup=False, highlight=False))
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        _fail(str(exc))
    console.print(
        f"[green]Corte planejado:[/green] {result.clips} clipes, {result.speech_seconds:.0f}s de fala "
        f"({result.start:.1f}s a {result.end:.1f}s da sessão)"
    )
    for label, at in result.phases:
        console.print(f"  {_format_mmss(at)}  {label}", markup=False, highlight=False)
    for w in result.warnings:
        console.print(f"[yellow]aviso:[/yellow] {w}")


def _format_clock(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{seconds % 60:04.1f}"


def _print_cut_report(report) -> None:
    """Resumo e tabela do que foi cortado (tempos na gravação original), para conferir antes de renderizar."""
    from .voice.cut_plan import REASON_LABELS

    removed = report.removed_seconds
    percent = 100 * removed / report.duration if report.duration else 0.0
    by_reason = (
        ", ".join(f"{n} {REASON_LABELS.get(r, r)}" for r, n in report.counts().items()) or "nenhum corte"
    )
    console.print(
        f"[green]{report.duration:.1f}s -> {report.duration_after:.1f}s[/green] "
        f"({percent:.0f}% a menos, intensidade {report.intensity}): {by_reason}"
    )
    if not report.cuts:
        return
    table = Table(
        Column("#", justify="right"),
        "Início",
        "Fim",
        Column("Duração", justify="right"),
        "Motivo",
        "Palavras",
    )
    for cut in report.cuts:
        mark = " (desfeito)" if cut.undone else ""
        table.add_row(
            str(cut.id),
            _format_clock(cut.start),
            _format_clock(cut.end),
            f"{cut.duration:.2f}s",
            REASON_LABELS.get(cut.reason, cut.reason) + mark,
            cut.text,
            style="dim" if cut.undone else None,
        )
    console.print(table)


@app.command()
def autocut(
    source: Annotated[Path, typer.Argument(help="Gravação falada (vídeo ou áudio).")],
    name: Annotated[
        str | None, typer.Option(help="Nome do projeto (padrão: nome do arquivo + -corte).")
    ] = None,
    intensity: Annotated[
        str,
        typer.Option(
            help="suave (só pausas) | normal (pausas e vícios) | agressiva (inclui frases repetidas)."
        ),
    ] = "normal",
    min_pause: Annotated[float, typer.Option(help="Pausa (s) acima da qual vira corte.")] = 0.5,
    breath: Annotated[float, typer.Option(help="Silêncio (s) mantido antes e depois de cada fala.")] = 0.15,
    preset: Annotated[str, typer.Option()] = "instagram/reels",
    brand: Annotated[str | None, typer.Option()] = None,
    captions: Annotated[bool, typer.Option(help="Legendas automáticas seguindo a fala cortada.")] = True,
    language: Annotated[str, typer.Option(help="Idioma da fala (pt, en, es...).")] = "pt",
    model: Annotated[str, typer.Option(help="Whisper: tiny | base | small | medium | large-v3")] = "small",
    device: Annotated[str, typer.Option(help="cpu | cuda")] = "cpu",
    overwrite: Annotated[bool, typer.Option(help="Refaz o projeto se ele já existir.")] = False,
) -> None:
    """Corta as pausas, os vícios e as frases repetidas de uma gravação falada. Cria um projeto com os clipes
    já cortados e mostra a lista do que saiu (tempo e motivo) para conferir antes de renderizar."""
    from .pipeline.autocut import AutoCutRequest, default_autocut_service
    from .voice.cut_plan import CutOptions

    project_name = name or f"{source.stem}-corte"
    try:
        request = AutoCutRequest(
            source=source,
            name=project_name,
            options=CutOptions(intensity=intensity, min_pause=min_pause, breath=breath),  # type: ignore[arg-type]
            preset=preset,
            brand=brand,
            captions=captions,
            language=language,
            model=model,
            device=device,  # type: ignore[arg-type]
            overwrite=overwrite,
        )
        service = default_autocut_service(lambda m: console.print(f"  {m}", markup=False, highlight=False))
        result = service.cut(request, lambda label, fraction: console.print(f"  {label}...", markup=False))
    except (ValidationError, *RENDER_ERRORS) as exc:
        _fail(str(exc))
    _print_cut_report(result.report)
    for warning in result.warnings:
        console.print(f"[yellow]aviso:[/yellow] {warning}")
    console.print(f"Projeto: {result.spec_path}", markup=False, highlight=False)
    console.print(
        f"Confira com [bold]dmaker cuts {project_name}[/bold]; devolva um corte com "
        f"[bold]dmaker uncut {project_name} <número>[/bold]; depois renderize com "
        f"[bold]dmaker render {project_name} --preview[/bold]."
    )


@app.command()
def cuts(name: Annotated[str, typer.Argument(help="Projeto criado por `dmaker autocut`.")]) -> None:
    """Lista o que o autocut removeu do projeto (tempo na gravação original e motivo)."""
    from .pipeline.autocut import load_cut_report
    from .pipeline.projects import project_path

    report = load_cut_report(project_path(name).parent)
    if report is None:
        _fail(f"{name} não tem lista de cortes (só projetos criados por `dmaker autocut` têm).")
    _print_cut_report(report)


@app.command()
def uncut(
    name: Annotated[str, typer.Argument(help="Projeto criado por `dmaker autocut`.")],
    cut_ids: Annotated[list[int], typer.Argument(help="Número do corte na lista de `dmaker cuts`.")],
) -> None:
    """Desfaz cortes do autocut: o trecho volta ao projeto e as legendas acompanham."""
    from .pipeline.autocut import undo_cut

    report = None
    try:
        for cut_id in cut_ids:
            report = undo_cut(name, cut_id)
    except (ValidationError, *RENDER_ERRORS) as exc:
        _fail(str(exc))
    assert report is not None
    _print_cut_report(report)


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
    console.print(report.to_text(), markup=False, highlight=False, soft_wrap=True)


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
    timeout: Annotated[
        float, typer.Option(help="Espera máxima por resposta do modelo (s); modelo em CPU demora.")
    ] = 1800.0,
    once: Annotated[str | None, typer.Option(help="Executa um único pedido e sai.")] = None,
) -> None:
    """Opera o DMaker por um modelo local do Ollama: tarefas mecânicas (template, render, QA, legendas).

    Cortes na mão, ritmo e textos da marca continuam sendo trabalho de uma IA maior ou de uma pessoa;
    multicâmera entra só pelo caminho automático (template com bloco `multicam` + `plan_multicam`).
    Veja a seção "Operador local com Ollama" do README.
    """
    import os

    from .agent import AgentLoop, McpToolHost, OllamaChat, system_prompt
    from .agent.llm import OLLAMA_URL_ENV

    base_url = url or os.environ.get(OLLAMA_URL_ENV, "http://127.0.0.1:11434")
    chat = OllamaChat(model=model, base_url=base_url, num_ctx=num_ctx, timeout=timeout)

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


# ---------- lote: vários vídeos de uma planilha ----------

batch_app = typer.Typer(
    help="Lote: um vídeo por linha de uma planilha (CSV, XLSX ou JSON) sobre um modelo de projeto.",
    no_args_is_help=True,
)
app.add_typer(batch_app, name="batch")


def _batch_service():
    from .pipeline.batch import BatchService

    return BatchService()


def _batch_fail(exc: Exception) -> None:
    """Erro do lote com a frase pronta; a validação que o causou vem junto, linha por linha."""
    from .pipeline.batch import BatchInvalidError

    if isinstance(exc, BatchInvalidError):
        console.print(exc.validation.to_text(), markup=False, highlight=False, soft_wrap=True)
    _fail(str(exc.args[0]) if isinstance(exc, KeyError) else str(exc))


def _batch_errors() -> tuple[type[Exception], ...]:
    from .domain.batch_sheet import SheetError
    from .domain.templates import TemplateError
    from .pipeline.batch import BatchBusyError, BatchError
    from .pipeline.batch_state import BatchFileError, BatchNotFoundError

    return (
        SheetError,
        TemplateError,
        BatchError,
        BatchBusyError,
        BatchNotFoundError,
        BatchFileError,
        FileNotFoundError,
    )


def _parse_rows(rows: str | None) -> set[int] | None:
    """ "2,4" -> {2, 4}; sem valor, todas as linhas do lote."""
    if not rows:
        return None
    try:
        return {int(item) for item in rows.replace(";", ",").split(",") if item.strip()}
    except ValueError:
        _fail(f'--rows inválido: "{rows}" (use números de vídeo separados por vírgula, ex.: 2,4)')
        return None


def _run_batch(name: str, rows: set[int] | None, force: bool) -> None:
    service = _batch_service()
    try:
        report = service.run(name, rows=rows, force=force, log=_console_log)
    except KeyboardInterrupt:
        _fail(f"Interrompido. O que já saiu fica; retome com: dmaker batch resume {name}")
    except _batch_errors() as exc:
        _batch_fail(exc)
    console.print(report.to_text(), markup=False, highlight=False, soft_wrap=True)
    if report.failed:
        raise typer.Exit(code=1)


@batch_app.command("validate")
def batch_validate(
    template: Annotated[str, typer.Argument(help="Nome do modelo (dmaker templates).")],
    sheet: Annotated[Path, typer.Argument(help="Planilha: .csv, .xlsx ou .json, uma linha por vídeo.")],
    name_column: Annotated[
        str | None, typer.Option("--name-column", help="Coluna cujo texto dá nome ao arquivo de cada vídeo.")
    ] = None,
) -> None:
    """Confere a planilha contra o modelo sem renderizar nada: campo faltando, arquivo inexistente, texto que
    não cabe e travessão. Sai com erro se alguma linha tem problema."""
    try:
        validation = _batch_service().validate(template, sheet, name_column)
    except _batch_errors() as exc:
        _batch_fail(exc)
    console.print(validation.to_text(), markup=False, highlight=False, soft_wrap=True)
    if not validation.ok:
        raise typer.Exit(code=1)
    console.print("[green]Planilha válida:[/green] todas as linhas podem ser renderizadas.")


@batch_app.command("run")
def batch_run(
    template: Annotated[str, typer.Argument(help="Nome do modelo (dmaker templates).")],
    sheet: Annotated[Path, typer.Argument(help="Planilha: .csv, .xlsx ou .json, uma linha por vídeo.")],
    lote: Annotated[
        str | None, typer.Option("--lote", help="Nome do lote (pasta em output/). Padrão: o da planilha.")
    ] = None,
    name_column: Annotated[
        str | None, typer.Option("--name-column", help="Coluna cujo texto dá nome ao arquivo de cada vídeo.")
    ] = None,
    skip_invalid: Annotated[
        bool, typer.Option("--skip-invalid", help="Segue sem as linhas com problema, em vez de parar.")
    ] = False,
    preview: Annotated[bool, typer.Option(help="Prévias rápidas em baixa resolução.")] = False,
    preset: Annotated[str | None, typer.Option(help="Sobrescreve o formato de saída do modelo.")] = None,
    replace: Annotated[
        bool,
        typer.Option(
            help="Refaz um lote de mesmo nome a partir da planilha atual (o que não mudou não é refeito)."
        ),
    ] = False,
) -> None:
    """Valida, cria um projeto por linha e renderiza tudo em output/<lote>/. Ctrl+C interrompe; retome com
    `dmaker batch resume`."""
    service = _batch_service()
    try:
        batch = service.create(
            template,
            sheet,
            name=lote,
            name_column=name_column,
            preview=preview,
            preset=preset,
            skip_invalid=skip_invalid,
            replace=replace,
        )
    except _batch_errors() as exc:
        _batch_fail(exc)
    skipped = sum(1 for row in batch.rows if row.project is None)
    console.print(
        f"[green]Lote criado:[/green] {batch.name}, {len(batch.rows) - skipped} projeto(s) em projects/"
        + (f", {skipped} linha(s) pulada(s)" if skipped else "")
    )
    _run_batch(batch.name, None, False)


@batch_app.command("resume")
def batch_resume(
    lote: Annotated[str, typer.Argument(help="Nome do lote (dmaker batch status).")],
    rows: Annotated[
        str | None, typer.Option("--rows", help="Só estes vídeos (números da tabela), ex.: 2,4.")
    ] = None,
    force: Annotated[bool, typer.Option(help="Refaz também os vídeos que já estão prontos.")] = False,
) -> None:
    """Continua o lote: renderiza o que falta, o que falhou e o que mudou no projeto. O que já saiu e continua
    igual não é refeito."""
    _run_batch(lote, _parse_rows(rows), force)


@batch_app.command("pause")
def batch_pause(lote: Annotated[str, typer.Argument(help="Nome do lote.")]) -> None:
    """Pede a um lote em andamento (em outra janela) que pare depois do vídeo que está renderizando."""
    try:
        _batch_service().pause(lote)
    except _batch_errors() as exc:
        _batch_fail(exc)
    console.print(f"[green]Pausa pedida:[/green] {lote} para depois do vídeo em andamento.")


@batch_app.command("status")
def batch_status(
    lote: Annotated[str | None, typer.Argument(help="Nome do lote. Sem ele, lista todos.")] = None,
) -> None:
    """Mostra o relatório de um lote (o que saiu, o que falhou e por quê) ou a lista de lotes."""
    service = _batch_service()
    try:
        if lote:
            console.print(service.report(lote).to_text(), markup=False, highlight=False, soft_wrap=True)
            return
        reports = service.reports()
    except _batch_errors() as exc:
        _batch_fail(exc)
    if not reports:
        console.print("Nenhum lote ainda. Use `dmaker batch run`.")
        return
    table = Table("lote", "modelo", "estado", "andamento")
    for report in reports:
        table.add_row(report.name, report.template, report.to_dict()["status_label"], report.summary())
    console.print(table)


# ---------- voz e narração ----------

voice_app = typer.Typer(
    help="Voz: narração por texto, clonagem de voz e voz projetada por descrição (modelo local OmniVoice).",
    no_args_is_help=True,
)
app.add_typer(voice_app, name="voice")

VOICE_ERRORS: tuple[type[Exception], ...] = (*RENDER_ERRORS, ValidationError, OSError)


def _voice_fail(exc: Exception) -> None:
    from .media.ffmpeg import FFmpegError

    _fail(str(exc) if not isinstance(exc, FFmpegError) else f"FFmpeg falhou: {exc.args[0]}")


def _print_narration(result) -> None:
    console.print(f"[green]Pronto:[/green] {result.path}  ({result.duration:.1f}s de áudio)")
    if result.srt_path:
        console.print(f"  legendas: {result.srt_path}")


@voice_app.command("say")
def voice_say(
    text: Annotated[str | None, typer.Argument(help="Texto a narrar (ou use --file).")] = None,
    out: Annotated[Path | None, typer.Option(help="Arquivo de saída: .wav, .mp3 ou .m4a.")] = None,
    voice: Annotated[
        str | None, typer.Option(help="Id de uma voz (dmaker voice list): dora, alex, santa ou uma sua.")
    ] = None,
    file: Annotated[Path | None, typer.Option(help="Arquivo .txt com o roteiro.")] = None,
    language: Annotated[
        str | None, typer.Option(help="Idioma (pt, en, es...). Padrão: o da voz, ou pt.")
    ] = None,
    instruct: Annotated[str | None, typer.Option(help="Descrição da voz, ex.: 'female, low pitch'.")] = None,
    speed: Annotated[float, typer.Option(help="Velocidade da fala (1.0 normal, 1.2 mais rápida).")] = 1.0,
    seed: Annotated[int | None, typer.Option(help="Semente: mesma semente, mesma fala.")] = None,
    steps: Annotated[
        int | None,
        typer.Option(
            help="Passos de síntese do OmniVoice (padrão 16, como no VoiceStudio; 32 para máxima qualidade)."
        ),
    ] = None,
    srt: Annotated[bool, typer.Option(help="Grava um .srt com o tempo de cada fala.")] = False,
    draft: Annotated[
        bool, typer.Option(help="Rascunho: 8 passos no OmniVoice (metade do tempo, mais áspero).")
    ] = False,
    raw: Annotated[bool, typer.Option(help="Voz crua do modelo, sem o acabamento broadcast.")] = False,
    device: Annotated[str, typer.Option(help="auto | cpu | cuda")] = "auto",
    brand: Annotated[
        str | None, typer.Option(help="Marca cujo dicionário de pronúncia vale (padrão: a da voz).")
    ] = None,
    watermark: Annotated[
        bool,
        typer.Option(
            "--watermark/--no-watermark",
            help="Marca d'água inaudível e etiqueta de procedência no arquivo (ligadas por padrão; "
            "--no-watermark ou DMAKER_WATERMARK=0 desligam as duas).",
        ),
    ] = True,
) -> None:
    """Narra um texto. Sem --voice usa a voz padrão (Kokoro, rápida); clones e vozes projetadas usam o OmniVoice
    (lento na CPU). O resultado de cada fala fica em cache. Toda fala sai com marca d'água inaudível e o arquivo
    com uma etiqueta de procedência (confira com `dmaker voice verify`)."""
    import time

    from .pipeline.voices import build_synthesizer, speak
    from .voice.synth import DRAFT_STEPS

    script = file.read_text(encoding="utf-8") if file else text
    if not script or not script.strip():
        _fail("Informe o texto ou --file.")
    synthesizer = build_synthesizer(device)
    started = time.perf_counter()
    try:
        result = speak(
            script,
            out,
            voice_id=voice,
            language=language,
            speed=speed,
            instruct=instruct,
            seed=seed,
            steps=DRAFT_STEPS if draft and steps is None else steps,
            write_srt=srt,
            master=not raw,
            log=_console_log,
            synthesizer=synthesizer,
            brand=brand,
            watermark=watermark,
        )
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    _print_narration(result)
    console.print(f"  tempo de processamento: {time.perf_counter() - started:.1f}s")


@voice_app.command("verify")
def voice_verify(
    file: Annotated[Path, typer.Argument(help="Áudio ou vídeo a conferir: .wav, .mp3, .m4a, .mp4...")],
    audio: Annotated[
        bool,
        typer.Option(
            "--audio",
            help="Analisa também o áudio quando há etiqueta (demora cerca de meio segundo por segundo).",
        ),
    ] = False,
) -> None:
    """Confere se o arquivo tem voz gerada por IA do DMaker: lê a etiqueta de procedência e, sem ela, analisa a
    marca d'água do áudio. Responde em três níveis: encontrada, indício (inconclusivo) ou não encontrada."""
    from .pipeline.voices import verify_watermark, watermark_verdict

    try:
        result = verify_watermark(file, check_audio=audio)
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    style = {"found": "green", "indication": "yellow", "absent": "white"}[result.verdict]
    console.print(f"[{style}]{watermark_verdict(result)}[/{style}]")
    if result.origin == "audio" or result.audio_verdict is not None:
        bits = f", assinatura {result.matched_bits} de 16 bits" if result.matched_bits is not None else ""
        console.print(f"  probabilidade: {result.probability:.3f}{bits}")


@voice_app.command("clone")
def voice_clone(
    name: Annotated[str, typer.Argument(help="Nome da voz.")],
    reference: Annotated[Path, typer.Argument(help="Gravação da voz (3 a 15 s de fala limpa).")],
    text: Annotated[
        str | None, typer.Option(help="O que é dito na gravação (sem isso, o Whisper transcreve).")
    ] = None,
    brand: Annotated[str | None, typer.Option(help="Marca dona da voz.")] = None,
    language: Annotated[str, typer.Option()] = "pt",
) -> None:
    """Cria uma voz clonada a partir de uma gravação."""
    from .pipeline.voices import clone_voice

    try:
        profile = clone_voice(name, reference, reference_text=text, brand=brand, language=language)
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    console.print(f"[green]Voz criada:[/green] {profile.id}")
    console.print(f"  texto da referência: {profile.reference_text}", markup=False, highlight=False)


@voice_app.command("design")
def voice_design(
    name: Annotated[str, typer.Argument(help="Nome da voz.")],
    gender: Annotated[str | None, typer.Option(help="male | female (masculino | feminino)")] = None,
    age: Annotated[
        str | None, typer.Option(help="child, teenager, young adult, middle-aged, elderly")
    ] = None,
    pitch: Annotated[
        str | None, typer.Option(help="very low pitch ... very high pitch (grave ... agudo)")
    ] = None,
    accent: Annotated[str | None, typer.Option(help="ex.: british accent, portuguese accent")] = None,
    whisper: Annotated[bool, typer.Option(help="Voz sussurrada.")] = False,
    instruct: Annotated[
        str | None, typer.Option(help="Descrição completa, ex.: 'female, low pitch'.")
    ] = None,
    brand: Annotated[str | None, typer.Option(help="Marca dona da voz.")] = None,
    language: Annotated[str, typer.Option()] = "pt",
) -> None:
    """Cria uma voz descrevendo como ela soa (sem gravação)."""
    from .pipeline.voices import design_voice

    try:
        profile = design_voice(name, gender, age, pitch, accent, whisper, instruct, brand, language)
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    console.print(f"[green]Voz criada:[/green] {profile.id}  ({profile.instruct})", highlight=False)


@voice_app.command("list")
def voice_list(
    brand: Annotated[str | None, typer.Option(help="Só as vozes dessa marca e as sem marca.")] = None,
) -> None:
    """Lista as vozes da biblioteca."""
    from .voice.library import VoiceLibrary

    profiles = VoiceLibrary().list(brand=brand)
    if not profiles:
        console.print("Nenhuma voz cadastrada. Use `dmaker voice clone` ou `dmaker voice design`.")
        return
    table = Table("id", "motor", "tipo", "idioma", "marca", "descrição")
    for p in profiles:
        table.add_row(
            p.id, p.engine, p.kind, p.language, p.brand or "-", p.instruct or p.reference_text or p.name
        )
    console.print(table)


@voice_app.command("remove")
def voice_remove(voice_id: Annotated[str, typer.Argument(help="Id da voz.")]) -> None:
    """Apaga uma voz da biblioteca."""
    from .voice.library import VoiceLibrary

    try:
        VoiceLibrary().remove(voice_id)
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    console.print(f"[green]Voz removida:[/green] {voice_id}")


queue_app = typer.Typer(
    help="Fila de narrações longas (audiobook, vários roteiros): roda em segundo plano e retoma de onde parou.",
    no_args_is_help=True,
)
voice_app.add_typer(queue_app, name="queue")


def _queue_service():
    from .pipeline.voice_queue_service import VoiceQueueService

    return VoiceQueueService()


def _queue_describe(view: dict) -> str:
    """Resumo de uma linha do andamento de um item: capítulo e fala em andamento, ou o desfecho."""
    if view["state"] == "running" and view["chapter"]:
        return f"capítulo {view['chapter']} de {view['chapters_total']}, fala {view['utterance']} de {view['utterances']}"
    if view["state"] == "failed":
        return (view["error"] or "").splitlines()[0] if view["error"] else ""
    if view["state"] == "done":
        return view["output_dir"]
    return f"{view['chapters_total']} capítulo(s)"


@queue_app.command("add")
def queue_add(
    text: Annotated[str | None, typer.Option(help="Texto a narrar (ou use --file).")] = None,
    file: Annotated[
        Path | None, typer.Option(help="Roteiro em .txt, .md ou .docx, um capítulo por título.")
    ] = None,
    voice: Annotated[
        str | None, typer.Option(help="Id da voz (dmaker voice list). Sem ela, a voz padrão.")
    ] = None,
    title: Annotated[str | None, typer.Option(help="Nome do item e da pasta em output/narracoes.")] = None,
    draft: Annotated[bool, typer.Option(help="Rascunho: 8 passos no OmniVoice (metade do tempo).")] = False,
    format: Annotated[str, typer.Option(help="Formato dos áudios: wav ou mp3.")] = "wav",
    language: Annotated[str | None, typer.Option(help="Idioma (pt, en...). Padrão: o da voz.")] = None,
    speed: Annotated[float, typer.Option(help="Velocidade da fala (1.0 normal).")] = 1.0,
    brand: Annotated[str | None, typer.Option(help="Marca cujo dicionário de pronúncia vale.")] = None,
) -> None:
    """Põe um roteiro no fim da fila. Quem executa é o `dmaker ui` aberto ou o `dmaker voice queue run`."""
    from .pipeline.voice_queue import QueueOptions

    if bool(text) == bool(file):
        _fail("Informe o texto (--text) ou o arquivo de roteiro (--file), um dos dois.")
    try:
        options = QueueOptions(
            voice=voice, language=language, speed=speed, brand=brand, draft=draft, audio_format=format
        )
        service = _queue_service()
        item = service.add_text(text, options, title) if text else service.add_path(file, options, title)
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    console.print(f"[green]Na fila:[/green] {item.id}  {item.title}  ({item.chapters_total} capítulo(s))")
    console.print(f"  saída: {item.output_dir}", markup=False, highlight=False)


@queue_app.command("list")
def queue_list() -> None:
    """Mostra a fila: estado, andamento e tempo estimado de cada item."""
    view = _queue_service().view()
    if not view["items"]:
        console.print("A fila está vazia. Use `dmaker voice queue add`.")
        return
    table = Table("id", "título", "estado", "andamento", "restante")
    for item in view["items"]:
        table.add_row(
            item["id"],
            item["title"],
            item["state_label"],
            _queue_describe(item),
            item["eta_label"] or "-",
        )
    console.print(table)
    if view["eta_label"]:
        console.print(f"Tempo estimado para esvaziar a fila: {view['eta_label']}")


def _queue_transition(item_id: str, action: str, success: str) -> None:
    queue = _queue_service().queue
    try:
        getattr(queue, action)(item_id)
    except VOICE_ERRORS as exc:
        _fail(str(exc.args[0]) if isinstance(exc, KeyError) else str(exc))
    console.print(f"[green]{success}:[/green] {item_id}")


@queue_app.command("cancel")
def queue_cancel(
    item_id: Annotated[str, typer.Argument(help="Id do item (dmaker voice queue list).")],
) -> None:
    """Cancela um item; o que estava em andamento para na próxima fala."""
    _queue_transition(item_id, "cancel", "Cancelado")


@queue_app.command("pause")
def queue_pause(item_id: Annotated[str, typer.Argument(help="Id do item.")]) -> None:
    """Pausa um item sem perder o que já foi narrado."""
    _queue_transition(item_id, "pause", "Pausado")


@queue_app.command("resume")
def queue_resume(item_id: Annotated[str, typer.Argument(help="Id do item.")]) -> None:
    """Devolve um item pausado à fila."""
    _queue_transition(item_id, "resume", "Retomado")


@queue_app.command("run")
def queue_run() -> None:
    """Executa a fila em primeiro plano, um item por vez, e volta quando ela esvazia. Ctrl+C interrompe e
    o item em andamento retoma de onde parou na próxima execução."""
    from .pipeline.voice_queue import VoiceQueue
    from .pipeline.voice_queue_service import build_worker
    from .pipeline.voice_worker import WorkerBusyError

    queue = VoiceQueue()
    worker = build_worker(queue, log=_console_log)
    try:
        processed = worker.run_pending()
    except WorkerBusyError as exc:
        _fail(str(exc))
    except KeyboardInterrupt:
        queue.requeue_interrupted()
        _fail("Interrompido; o item em andamento volta para a fila e retoma na próxima execução.")
    console.print(f"[green]Fila concluída:[/green] {processed} item(ns) executado(s)")


@voice_app.command("preview")
def voice_preview(
    voice_id: Annotated[str, typer.Argument(help="Id da voz.")],
    text: Annotated[
        str | None, typer.Option(help="Frase de teste (padrão: uma frase curta no idioma da voz).")
    ] = None,
    out: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Gera uma amostra curta da voz para ouvir antes de usar."""
    from .pipeline.voices import preview_voice

    try:
        result = preview_voice(voice_id, text, out, log=_console_log)
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    _print_narration(result)


def _print_words(words, detail: bool) -> None:
    """Palavras com tempo: agrupadas por fôlego (uma linha por frase) ou, com `detail`, uma por linha."""
    if detail:
        table = Table("início", "fim", "palavra")
        for word in words:
            table.add_row(f"{word.start:.2f}", f"{word.end:.2f}", word.text)
        console.print(table)
        return
    from .voice.speech_edit import MIN_PAUSE_SECONDS

    line: list = []
    for word in [*words, None]:
        if line and (word is None or word.start - line[-1].end >= MIN_PAUSE_SECONDS):
            console.print(
                f"{line[0].start:8.1f} a {line[-1].end:.1f} s  {' '.join(w.text for w in line)}",
                markup=False,
                highlight=False,
            )
            line = []
        if word is not None:
            line.append(word)


@voice_app.command("words")
def voice_words(
    file: Annotated[Path, typer.Argument(help="Vídeo ou áudio com fala.")],
    start: Annotated[
        float | None, typer.Option(help="Início do trecho a transcrever (s no arquivo).")
    ] = None,
    end: Annotated[float | None, typer.Option(help="Fim do trecho a transcrever (s no arquivo).")] = None,
    language: Annotated[str, typer.Option(help="Idioma da fala.")] = "pt",
    detail: Annotated[bool, typer.Option("--words", help="Uma palavra por linha, com início e fim.")] = False,
) -> None:
    """Lista o que foi dito com o tempo de cada trecho, para escolher o que corrigir com `voice fix`."""
    from .media.ffmpeg import SubprocessRunner
    from .pipeline.speech_fix import default_speech_fix_service

    service = default_speech_fix_service(SubprocessRunner(quiet=True), _console_log)
    try:
        words = service.transcribe_words(file, start, end, language)
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    if not words:
        console.print("Nenhuma fala encontrada no trecho.")
        return
    _print_words(words, detail)


@voice_app.command("fix")
def voice_fix(
    file: Annotated[Path, typer.Argument(help="Vídeo ou áudio com a fala a corrigir.")],
    text: Annotated[str, typer.Option(help="O que deve ser dito no lugar (texto certo).")],
    find: Annotated[
        str | None, typer.Option(help="Texto errado como foi dito (sem diferenciar acento nem maiúscula).")
    ] = None,
    occurrence: Annotated[int | None, typer.Option(help="Qual ocorrência de --find (1, 2...).")] = None,
    start: Annotated[float | None, typer.Option(help="Início do trecho errado (s no arquivo).")] = None,
    end: Annotated[float | None, typer.Option(help="Fim do trecho errado (s no arquivo).")] = None,
    search_from: Annotated[
        float | None,
        typer.Option(help="Com --find, só transcreve a partir daqui (s); poupa tempo em vídeos longos."),
    ] = None,
    search_to: Annotated[float | None, typer.Option(help="Com --find, só transcreve até aqui (s).")] = None,
    voice: Annotated[
        str | None, typer.Option(help="Voz da biblioteca. Sem ela, clona a voz do próprio falante.")
    ] = None,
    no_expand: Annotated[
        bool, typer.Option("--no-expand", help="Fala só o trecho trocado, sem as palavras vizinhas.")
    ] = False,
    save_voice: Annotated[
        str | None, typer.Option(help="Guarda a voz clonada do falante na biblioteca com este nome.")
    ] = None,
    language: Annotated[str, typer.Option(help="Idioma da fala.")] = "pt",
    brand: Annotated[str | None, typer.Option(help="Marca cujo dicionário de pronúncia vale.")] = None,
    steps: Annotated[int | None, typer.Option(help="Passos de síntese do OmniVoice (padrão 16).")] = None,
    draft: Annotated[bool, typer.Option(help="Rascunho: 8 passos no OmniVoice (metade do tempo).")] = False,
    seed: Annotated[int | None, typer.Option(help="Semente: mesma semente, mesma fala.")] = None,
    out: Annotated[
        Path | None, typer.Option(help="Arquivo de saída (padrão: output/correcao/<nome>.corrigido.<ext>).")
    ] = None,
    device: Annotated[str, typer.Option(help="auto | cpu | cuda")] = "auto",
) -> None:
    """Regrava um trecho de fala com a voz do próprio falante (corrige uma palavra sem gravar de novo).

    Aponte o trecho com --find "texto errado" ou com --start e --end (veja `dmaker voice words`). O resto do
    arquivo fica como está e o vídeo mantém a duração. Na CPU leva cerca de 20 s por segundo de fala nova
    mais a separação da voz (que fica em cache)."""
    import time

    from .media.ffmpeg import SubprocessRunner
    from .pipeline.speech_fix import FixRequest, default_speech_fix_service
    from .voice.synth import DRAFT_STEPS

    started = time.perf_counter()
    try:
        request = FixRequest(
            src=file,
            text=text,
            find=find,
            occurrence=occurrence,
            start=start,
            end=end,
            search_from=search_from,
            search_to=search_to,
            voice=voice,
            expand=not no_expand,
            save_voice=save_voice,
            language=language,
            brand=brand,
            steps=DRAFT_STEPS if draft and steps is None else steps,
            seed=seed,
            out=out,
        )
        service = default_speech_fix_service(SubprocessRunner(quiet=True), _console_log, device=device)
        result = service.fix(request)
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    console.print(f"[green]Pronto:[/green] {result.path}", highlight=False, soft_wrap=True)
    console.print(f'  trocado: "{result.old_text}" -> "{result.new_text}"', markup=False, highlight=False)
    console.print(
        f"  região {result.region_start:.2f} a {result.region_end:.2f} s; fala: {result.spoken_context}",
        markup=False,
        highlight=False,
    )
    console.print(f"  duração: {result.rule}", markup=False, highlight=False)
    console.print(f"  voz: {result.voice}; tempo de processamento: {time.perf_counter() - started:.1f}s")


@voice_app.command("convert")
def voice_convert(
    file: Annotated[Path, typer.Argument(help="Vídeo ou áudio com a fala a converter.")],
    voice: Annotated[
        str, typer.Option(help="Voz da biblioteca que vai falar no lugar (clonada ou desenhada).")
    ],
    start: Annotated[float | None, typer.Option(help="Início do trecho (s no arquivo).")] = None,
    end: Annotated[float | None, typer.Option(help="Fim do trecho (s no arquivo).")] = None,
    out: Annotated[
        Path | None,
        typer.Option(help="Arquivo de saída (padrão: output/troca-de-voz/<nome>.<voz>-<id>.<ext>)."),
    ] = None,
) -> None:
    """Troca a voz de uma gravação pela de uma voz da biblioteca, mantendo ritmo, pausas, entonação e o fundo.

    Diferente de `dub` (que traduz e fala de novo) e de `fix` (que troca um trecho): todas as palavras são as
    da gravação, só o timbre muda. A voz e o fundo são separados antes (fica em cache) e só a voz é convertida.
    Na CPU a conversão leva de 1,5 a 2 s por segundo de fala, além da separação."""
    from .media.ffmpeg import SubprocessRunner
    from .pipeline.voice_conversion import ConversionRequest, default_voice_conversion_service

    announced: list[str] = []

    def report(stage: str, fraction: float) -> None:
        if stage not in announced:
            announced.append(stage)
            console.print(f"[dim]{stage}...[/dim]")

    try:
        request = ConversionRequest(src=file, voice=voice, start=start, end=end, out=out)
        service = default_voice_conversion_service(SubprocessRunner(quiet=True), _console_log)
        result = service.convert(request, report)
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    console.print(f"[green]Pronto:[/green] {result.path}", highlight=False, soft_wrap=True)
    console.print(
        f"  voz: {result.voice}; {result.seconds:.1f}s em {result.blocks} bloco(s); "
        f"volume ajustado em {result.gain_db:+.1f} dB",
        markup=False,
        highlight=False,
    )
    spent = ", ".join(f"{stage} {seconds:.1f}s" for stage, seconds in result.timings.items())
    console.print(f"  tempo: {spent}", markup=False, highlight=False)


lexicon_app = typer.Typer(
    help="Dicionário de pronúncia: como a voz fala cada termo (global ou por marca).", no_args_is_help=True
)
voice_app.add_typer(lexicon_app, name="lexicon")


@lexicon_app.command("list")
def lexicon_list(
    brand: Annotated[str | None, typer.Option(help="Mostra também os termos dessa marca.")] = None,
    language: Annotated[str | None, typer.Option(help="Só esse idioma (padrão: todos).")] = None,
) -> None:
    """Lista os termos: os globais e, com --brand, os da marca (que valem por cima)."""
    from .voice.lexicon_store import LexiconStore
    from .voice.pronunciation import language_code

    store = LexiconStore()
    try:
        scopes = [("global", store.by_language())] + ([(brand, store.by_language(brand))] if brand else [])
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    table = Table("escopo", "idioma", "termo", "pronúncia")
    for scope, languages in scopes:
        for code, lexicon in languages.items():
            if language is None or code == language_code(language):
                for term, spoken in lexicon.entries:
                    table.add_row(scope, code, term, spoken)
    if not table.rows:
        console.print("Nenhum termo cadastrado. Use `dmaker voice lexicon add TERMO PRONÚNCIA`.")
        return
    console.print(table)


@lexicon_app.command("add")
def lexicon_add(
    term: Annotated[str, typer.Argument(help="Como o termo é escrito (ex.: DMaker).")],
    spoken: Annotated[str, typer.Argument(help="Como deve ser falado (ex.: Di-mêiker).")],
    brand: Annotated[str | None, typer.Option(help="Vale só para essa marca (padrão: global).")] = None,
    language: Annotated[str, typer.Option(help="Idioma da fala em que vale (pt, en...).")] = "pt",
) -> None:
    """Cadastra ou troca a pronúncia de um termo num idioma. Só a fala muda; legendas mantêm o texto escrito."""
    from .voice.lexicon_store import LexiconStore

    try:
        LexiconStore().add(term, spoken, brand, language)
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    console.print(f"[green]Pronúncia salva ({language}):[/green] {term} -> {spoken}", highlight=False)


@lexicon_app.command("remove")
def lexicon_remove(
    term: Annotated[str, typer.Argument(help="Termo a tirar do dicionário.")],
    brand: Annotated[str | None, typer.Option(help="Tira da marca (padrão: do global).")] = None,
    language: Annotated[str, typer.Option(help="Idioma do termo a tirar.")] = "pt",
) -> None:
    """Tira um termo do dicionário, no idioma dado."""
    from .voice.lexicon_store import LexiconStore

    try:
        LexiconStore().remove(term, brand, language)
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    console.print(f"[green]Termo removido:[/green] {term}", highlight=False)


# ---------- áudio ----------

audio_app = typer.Typer(
    help="Áudio: isolamento vocal (voz de um lado, música e ruído do outro) com o modelo local Demucs.",
    no_args_is_help=True,
)
app.add_typer(audio_app, name="audio")

ISOLATION_FORMATS = ("wav", "mp3")


@audio_app.command("isolate")
def audio_isolate(
    file: Annotated[Path, typer.Argument(help="Vídeo ou áudio com fala e fundo.")],
    start: Annotated[float | None, typer.Option(help="Início do trecho, em segundos no arquivo.")] = None,
    end: Annotated[float | None, typer.Option(help="Fim do trecho, em segundos no arquivo.")] = None,
    out_dir: Annotated[Path | None, typer.Option(help="Pasta de saída (padrão: output/isolamento).")] = None,
    audio_format: Annotated[str, typer.Option("--format", help="wav (sem perdas) ou mp3.")] = "wav",
    stream: Annotated[int, typer.Option(help="Faixa de áudio do arquivo (0 é a primeira).")] = 0,
    device: Annotated[str, typer.Option(help="auto | cpu | cuda")] = "auto",
) -> None:
    """Separa a voz do fundo e grava `<nome>_voz` e `<nome>_fundo`. Lento na CPU (veja o fator no fim) e
    guardado em cache: repetir o mesmo trecho é instantâneo."""
    import time

    from .media.ffmpeg import SubprocessRunner
    from .media.probe import probe
    from .media.separation import DemucsSeparator
    from .pipeline.isolation import IsolationService, progress_logger

    if audio_format not in ISOLATION_FORMATS:
        _fail(f"Formato {audio_format!r} não suportado; use {' ou '.join(ISOLATION_FORMATS)}.")
    service = IsolationService(DemucsSeparator(device=device), SubprocessRunner(quiet=True))
    started = time.perf_counter()
    try:
        duration = (end if end is not None else probe(file).duration) - (start or 0.0)
        stems = service.export(
            file,
            out_dir or config.OUTPUT_DIR / "isolamento",
            audio_format,
            start,
            end,
            stream,
            progress_logger(_console_log, "separação"),
        )
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    elapsed = time.perf_counter() - started
    console.print(f"[green]Voz:[/green]   {stems.vocals}", highlight=False, soft_wrap=True)
    console.print(f"[green]Fundo:[/green] {stems.background}", highlight=False, soft_wrap=True)
    console.print(f"  {duration:.1f}s de áudio em {elapsed:.1f}s (fator {elapsed / max(duration, 0.1):.1f}x)")


# ---------- modelos ----------

models_app = typer.Typer(
    help="Modelos de IA em cache/models: ver o que está baixado e quanto ocupa, baixar, apagar e limpar sobras.",
    no_args_is_help=True,
)
app.add_typer(models_app, name="models")

STATE_LABELS = {"installed": "baixado", "partial": "parcial", "absent": "ausente"}
STATE_STYLES = {"installed": "green", "partial": "yellow", "absent": "dim"}


def _models_service():
    from .pipeline.models_service import ModelService

    return ModelService()


def _models_fail(exc: Exception) -> None:
    _fail(str(exc))


def _ask_yes_no(question: str) -> bool:
    """Pergunta em português (s/N); o `typer.confirm` só entende y/n. Sem resposta (stdin fechado), é não."""
    try:
        answer = console.input(f"{question} [s/N] ", markup=False)
    except EOFError:
        return False
    return answer.strip().lower() in {"s", "sim", "y", "yes"}


def _confirm_removal(plan, assume_yes: bool) -> None:
    """Mostra o que vai embora e pergunta; `--yes` pula a pergunta (para scripts), nunca o aviso."""
    console.print(plan.warning(), highlight=False)
    for path in plan.paths:
        console.print(f"  {path}", markup=False, highlight=False)
    if not assume_yes and not _ask_yes_no("Apagar?"):
        console.print("Nada foi apagado.")
        raise typer.Exit()


@models_app.command("list")
def models_list() -> None:
    """Lista os modelos com estado, tamanho medido em disco, licença e para que servem, mais as sobras."""
    from .pipeline.models_service import ModelError

    try:
        inventory = _models_service().inventory()
    except ModelError as exc:
        _models_fail(exc)
    # id, estado e tamanho não quebram linha (o id é o que se digita em `download` e `remove`); o resto cede
    table = Table(
        Column("id", no_wrap=True),
        "modelo",
        Column("estado", no_wrap=True),
        Column("no disco", no_wrap=True),
        "licença",
        "serve para",
    )
    for status in inventory.models:
        spec = status.spec
        size = (
            format_size(status.size_bytes)
            if status.state != "absent"
            else f"(~{format_size(spec.expected_size)})"
        )
        table.add_row(
            spec.id,
            spec.name,
            f"[{STATE_STYLES[status.state]}]{STATE_LABELS[status.state]}[/]",
            size,
            spec.license,
            spec.purpose,
        )
    console.print(table)
    if inventory.leftovers:
        console.print(
            f"[yellow]Sobras[/yellow] (nenhum modelo usa; `dmaker models prune` apaga, "
            f"{format_size(inventory.leftover_bytes)}):"
        )
        for item in inventory.leftovers:
            console.print(f"  {item.path}  {format_size(item.size_bytes)}", markup=False, highlight=False)
    free = (
        f" · livre no disco: {format_size(inventory.disk_free_bytes)}"
        if inventory.disk_free_bytes is not None
        else ""
    )
    console.print(
        f"Total ocupado em {inventory.models_dir}: {format_size(inventory.total_bytes)}{free}",
        markup=False,
        highlight=False,
        soft_wrap=True,
    )


@models_app.command("download")
def models_download(
    model_id: Annotated[str, typer.Argument(help="Id do modelo (veja `dmaker models list`).")],
) -> None:
    """Baixa o modelo (se faltar) e confere que ficou inteiro. Os de ~3 GB levam minutos."""
    from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TimeRemainingColumn

    from .pipeline.models_service import ModelError

    service = _models_service()
    try:
        name = service.spec(model_id).name
        with Progress(
            TextColumn("[cyan]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(name, total=None)

            def on_progress(done: int, total: int) -> None:
                progress.update(task, completed=done, total=total)

            status = service.download(model_id, on_progress)
    except ModelError as exc:
        _models_fail(exc)
    except Exception as exc:  # noqa: BLE001 - rede, disco e biblioteca de cada motor falham de jeitos próprios
        _fail(f"Não consegui baixar {model_id}: {exc}")

    console.print(
        f"[green]Pronto:[/green] {status.spec.name} ({format_size(status.size_bytes)})", highlight=False
    )


@models_app.command("remove")
def models_remove(
    model_id: Annotated[str, typer.Argument(help="Id do modelo (veja `dmaker models list`).")],
    yes: Annotated[bool, typer.Option("--yes", help="Apaga sem perguntar.")] = False,
) -> None:
    """Apaga o modelo do disco, dizendo antes quais funções dependem dele."""
    from .pipeline.models_service import ModelError

    service = _models_service()
    try:
        plan = service.plan_removal(model_id)
        if not plan.paths:
            _fail(f"{service.spec(model_id).name} não está baixado; não há o que apagar.")
        _confirm_removal(plan, yes)
        service.remove(model_id, confirm=True)
    except ModelError as exc:
        _models_fail(exc)
    console.print(
        f"[green]Apagado:[/green] {plan.title}, {format_size(plan.freed_bytes)} liberados.", highlight=False
    )


@models_app.command("prune")
def models_prune(
    yes: Annotated[bool, typer.Option("--yes", help="Apaga sem perguntar.")] = False,
) -> None:
    """Apaga as sobras: pastas e arquivos em cache/models que nenhum modelo do DMaker usa."""
    from .pipeline.models_service import ModelError

    service = _models_service()
    try:
        plan = service.plan_prune()
        if not plan.paths:
            console.print("Não há sobras em cache/models.")
            return
        _confirm_removal(plan, yes)
        service.prune(confirm=True, only=plan.paths)
    except ModelError as exc:
        _models_fail(exc)
    console.print(
        f"[green]Sobras apagadas:[/green] {format_size(plan.freed_bytes)} liberados.", highlight=False
    )


# ---------- dublagem ----------


class _DubGroup(TyperGroup):
    """`dmaker dub ARQUIVO --to en` (sem subcomando) prepara e gera de uma vez, como `dub run`."""

    def resolve_command(self, ctx, args):
        if args and args[0] not in self.commands and args[0] not in ctx.help_option_names:
            return "run", self.commands["run"], args
        return super().resolve_command(ctx, args)


dub_app = typer.Typer(
    cls=_DubGroup,
    help="Dublagem: traduz a fala de um vídeo ou áudio e a refaz, com a voz clonada de quem fala, no idioma alvo.",
    no_args_is_help=True,
)
app.add_typer(dub_app, name="dub")

SPEAKER_MODES = ("per_speaker", "per_segment", "single")
SPEAKER_HELP = (
    "per_speaker (padrão: separa quem fala e usa uma voz clonada por pessoa), per_segment (clona a voz de "
    "cada fala) ou single (um clone para o arquivo)."
)
SPEAKERS_HELP = (
    "Quantas pessoas falam (força a separação de falantes; sem isso o áudio decide). Só no modo per_speaker."
)
FIT_HELP = (
    "Quando a fala traduzida não cabe no tempo: voz (acelera a voz, o padrão), video (estica o vídeo "
    "naquele trecho, até 1,3x) ou misto (acelera a voz até 1,15x e estica o vídeo no resto)."
)


def _check_fit(fit: str) -> None:
    from .domain.dub import FIT_MODES

    if fit not in FIT_MODES:
        _fail(f"Modo de encaixe {fit!r} inválido; use {', '.join(FIT_MODES)}.")


def _print_segments(project) -> None:
    from rich.markup import escape

    with_speakers = len(project.speakers) > 1
    table = Table("fala", "tempo", *(["falante"] if with_speakers else []), "original", "tradução", "trava")
    for s in project.segments:
        table.add_row(
            s.id,
            f"{s.start:.1f} a {s.end:.1f}",
            *([escape(s.speaker or "")] if with_speakers else []),
            escape(s.source_text),
            escape(s.text),
            "sim" if s.locked else "",
        )
    console.print(table)


def _print_dub_result(result) -> None:
    from rich.markup import escape

    console.print(f"[green]Pronto:[/green] {result.path}", highlight=False, soft_wrap=True)
    console.print(f"  legenda: {result.srt_path}", markup=False, highlight=False, soft_wrap=True)
    stretched = result.stretched
    if stretched:
        added = sum(r.added_seconds for r in stretched)
        console.print(
            f"  vídeo esticado em {len(stretched)} trecho(s), +{added:.1f} s: {result.output_seconds:.1f} s no total",
            markup=False,
            highlight=False,
            soft_wrap=True,
        )
    table = Table("fala", "início", "tradução", "fala (s)", "toca (s)", "situação", "cache")
    for r in result.report:
        table.add_row(
            r.id,
            f"{r.retimed_start if r.retimed_start is not None else r.start:.1f}",
            escape(r.text),
            f"{r.speech_seconds:.1f}",
            f"{r.played_seconds:.1f}",
            escape(r.message),
            "sim" if r.cached else "não",
        )
    console.print(table)
    for warning in result.warnings:
        err.print(f"Atenção: {warning}", markup=False, highlight=False, soft_wrap=True)
    steps = "; ".join(f"{name} {seconds:.0f} s" for name, seconds in result.timings.items())
    console.print(
        f"  {result.regenerated} fala(s) sintetizada(s) agora. Tempos: {steps}", markup=False, soft_wrap=True
    )


def _print_stems(stems) -> None:
    console.print(f"[green]Trilhas:[/green] {stems.folder}", highlight=False, soft_wrap=True)
    for path in stems.files:
        console.print(f"  {path.name}", markup=False, highlight=False, soft_wrap=True)
    console.print(
        f"  duração de cada uma: {stems.duration:.3f} s (a do vídeo), começando no zero", markup=False
    )
    if stems.zip_path:
        console.print(f"  zip: {stems.zip_path}", markup=False, highlight=False, soft_wrap=True)
    if stems.original_voice_db is not None:
        console.print(
            f"  o vídeo dublado usa a voz original a {stems.original_voice_db:g} dB; a trilha sai sem atenuar",
            markup=False,
            soft_wrap=True,
        )


def _prepare_dub(
    service,
    file: Path,
    target: str,
    source: str,
    speaker: str | None,
    voice: str | None,
    keep_original: float | None,
    glossary: list[str] | None,
    brand: str | None,
    project_path: Path | None,
    fit: str = "voz",
    num_speakers: int | None = None,
) -> tuple:
    from .pipeline.dubbing import default_project_path

    if speaker is not None and speaker not in SPEAKER_MODES:
        _fail(f"Modo de falante {speaker!r} inválido; use {' ou '.join(SPEAKER_MODES)}.")
    _check_fit(fit)
    path = project_path or default_project_path(file, target)
    project = service.prepare(
        file,
        target,
        source,
        speaker_mode=speaker,
        voice=voice,
        keep_original_db=keep_original,
        glossary=glossary or [],
        brand=brand,
        project_path=path,
        fit_mode=fit,
        num_speakers=num_speakers,
    )
    return project, path


@dub_app.command("prepare")
def dub_prepare(
    file: Annotated[Path, typer.Argument(help="Vídeo ou áudio com fala.")],
    target: Annotated[str, typer.Option("--to", help="Idioma alvo (en, es, fr, de, it, pt...).")],
    source: Annotated[str, typer.Option("--from", help="Idioma da fala original.")] = "pt",
    speaker: Annotated[str | None, typer.Option(help=SPEAKER_HELP)] = None,
    speakers: Annotated[int | None, typer.Option("--speakers", min=1, help=SPEAKERS_HELP)] = None,
    voice: Annotated[str | None, typer.Option(help="Voz da biblioteca no lugar da clonada.")] = None,
    keep_original: Annotated[
        float | None,
        typer.Option(help="Mantém a voz original por baixo, em dB (ex.: -18). Sem isso, só a dublada."),
    ] = None,
    glossary: Annotated[
        list[str] | None, typer.Option(help="Termo que não se traduz (repita a opção para vários).")
    ] = None,
    brand: Annotated[str | None, typer.Option(help="Marca cujo dicionário de pronúncia vale.")] = None,
    project: Annotated[
        Path | None,
        typer.Option(help="Onde gravar o projeto (padrão: output/dublagem/<nome>.<idioma>.dub.json)."),
    ] = None,
    fit: Annotated[str, typer.Option(help=FIT_HELP)] = "voz",
    device: Annotated[str, typer.Option(help="auto | cpu | cuda")] = "auto",
) -> None:
    """Separa a voz, transcreve, parte em frases e traduz; grava o projeto `.dub.json` para você revisar.

    Corrija as traduções no JSON (ou na aba Voz da interface) e rode `dmaker dub render`. A tradução usa o
    Ollama local (modelo em DMAKER_TRANSLATE_MODEL) e leva minutos na CPU."""
    import time

    from .media.ffmpeg import SubprocessRunner
    from .pipeline.dubbing import default_dubbing_service

    started = time.perf_counter()
    try:
        service = default_dubbing_service(SubprocessRunner(quiet=True), _console_log, device=device)
        dub, path = _prepare_dub(
            service,
            file,
            target,
            source,
            speaker,
            voice,
            keep_original,
            glossary,
            brand,
            project,
            fit,
            speakers,
        )
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    _print_segments(dub)
    console.print(f"[green]Projeto:[/green] {path}", highlight=False, soft_wrap=True)
    console.print(f"  tempo de processamento: {time.perf_counter() - started:.1f}s")


@dub_app.command("render")
def dub_render(
    project: Annotated[Path, typer.Argument(help="Projeto .dub.json (de `dmaker dub prepare`).")],
    out: Annotated[
        Path | None, typer.Option(help="Arquivo de saída (padrão: output/dublagem/<nome>.<idioma>.<ext>).")
    ] = None,
    steps: Annotated[int | None, typer.Option(help="Passos de síntese do OmniVoice (padrão 16).")] = None,
    draft: Annotated[bool, typer.Option(help="Rascunho: 8 passos no OmniVoice (metade do tempo).")] = False,
    fit: Annotated[
        str | None,
        typer.Option(help=f"{FIT_HELP} Vale só para esta geração; sem isso vale o `fit_mode` do projeto."),
    ] = None,
    stems: Annotated[
        bool,
        typer.Option(help="Exporta também as trilhas separadas (voz dublada, fundo e voz original) em WAV."),
    ] = False,
    zip_stems: Annotated[bool, typer.Option("--zip", help="Com --stems, junta as trilhas num .zip.")] = False,
    device: Annotated[str, typer.Option(help="auto | cpu | cuda")] = "auto",
) -> None:
    """Gera a dublagem: sintetiza as traduções com a voz de cada falante e monta com o fundo original.

    Só as falas novas ou editadas são sintetizadas; o resto sai do cache. Grava o vídeo e a legenda (.srt)."""
    from .domain.dub import load_dub_project
    from .media.ffmpeg import SubprocessRunner
    from .pipeline.dub_stems import StemsOptions
    from .pipeline.dubbing import default_dubbing_service
    from .voice.synth import DRAFT_STEPS

    if zip_stems and not stems:
        raise typer.BadParameter("--zip só vale junto com --stems.", param_hint="--zip")
    if fit is not None:
        _check_fit(fit)
    try:
        dub = load_dub_project(project)
        if fit is not None:
            dub = dub.model_copy(update={"fit_mode": fit})
        service = default_dubbing_service(SubprocessRunner(quiet=True), _console_log, device=device)
        result = service.render(
            dub,
            out,
            steps=DRAFT_STEPS if draft and steps is None else steps,
            stems=StemsOptions(make_zip=zip_stems) if stems else None,
        )
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    _print_dub_result(result)
    if result.stems:
        _print_stems(result.stems)


@dub_app.command("stems")
def dub_stems(
    project: Annotated[Path, typer.Argument(help="Projeto .dub.json (de `dmaker dub prepare`).")],
    out_dir: Annotated[
        Path | None,
        typer.Option(help="Pasta das trilhas (padrão: output/dublagem/<nome>.<idioma>.trilhas)."),
    ] = None,
    zip_stems: Annotated[
        bool, typer.Option("--zip", help="Junta as três trilhas num .zip ao lado da pasta.")
    ] = False,
    steps: Annotated[int | None, typer.Option(help="Passos de síntese do OmniVoice (padrão 16).")] = None,
    draft: Annotated[bool, typer.Option(help="Rascunho: 8 passos no OmniVoice (metade do tempo).")] = False,
    device: Annotated[str, typer.Option(help="auto | cpu | cuda")] = "auto",
) -> None:
    """Exporta as trilhas separadas da dublagem (voz dublada, fundo e voz original) para remixar em outro editor.

    Três WAV (48 kHz, estéreo) com a duração exata do vídeo, alinhados no zero e sem acabamento (sem loudnorm
    nem limitador). Usa as falas já sintetizadas do cache; só sintetiza o que ainda não existe."""
    from .domain.dub import load_dub_project
    from .media.ffmpeg import SubprocessRunner
    from .pipeline.dub_stems import StemsOptions
    from .pipeline.dubbing import default_dubbing_service
    from .voice.synth import DRAFT_STEPS

    try:
        dub = load_dub_project(project)
        service = default_dubbing_service(SubprocessRunner(quiet=True), _console_log, device=device)
        stems = service.export_stems(
            dub,
            StemsOptions(out_dir, zip_stems),
            steps=DRAFT_STEPS if draft and steps is None else steps,
        )
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    _print_stems(stems)


@dub_app.command("retranslate")
def dub_retranslate(
    project: Annotated[Path, typer.Argument(help="Projeto .dub.json.")],
    device: Annotated[str, typer.Option(help="auto | cpu | cuda")] = "auto",
) -> None:
    """Traduz de novo as falas do projeto que não estão travadas (`locked`), sem tocar nas travadas."""
    from .domain.dub import load_dub_project, save_dub_project
    from .media.ffmpeg import SubprocessRunner
    from .pipeline.dubbing import default_dubbing_service

    try:
        service = default_dubbing_service(SubprocessRunner(quiet=True), _console_log, device=device)
        dub = service.retranslate(load_dub_project(project))
        save_dub_project(dub, project)
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    _print_segments(dub)


@dub_app.command("run")
def dub_run(
    file: Annotated[Path, typer.Argument(help="Vídeo ou áudio com fala.")],
    target: Annotated[str, typer.Option("--to", help="Idioma alvo (en, es, fr, de, it, pt...).")],
    source: Annotated[str, typer.Option("--from", help="Idioma da fala original.")] = "pt",
    speaker: Annotated[str | None, typer.Option(help=SPEAKER_HELP)] = None,
    speakers: Annotated[int | None, typer.Option("--speakers", min=1, help=SPEAKERS_HELP)] = None,
    voice: Annotated[str | None, typer.Option(help="Voz da biblioteca no lugar da clonada.")] = None,
    keep_original: Annotated[
        float | None, typer.Option(help="Mantém a voz original por baixo, em dB (ex.: -18).")
    ] = None,
    glossary: Annotated[
        list[str] | None, typer.Option(help="Termo que não se traduz (repita a opção).")
    ] = None,
    brand: Annotated[str | None, typer.Option(help="Marca cujo dicionário de pronúncia vale.")] = None,
    out: Annotated[Path | None, typer.Option(help="Arquivo de saída da dublagem.")] = None,
    project: Annotated[Path | None, typer.Option(help="Onde gravar o projeto .dub.json.")] = None,
    steps: Annotated[int | None, typer.Option(help="Passos de síntese do OmniVoice (padrão 16).")] = None,
    draft: Annotated[bool, typer.Option(help="Rascunho: 8 passos no OmniVoice (metade do tempo).")] = False,
    fit: Annotated[str, typer.Option(help=FIT_HELP)] = "voz",
    device: Annotated[str, typer.Option(help="auto | cpu | cuda")] = "auto",
) -> None:
    """Prepara e gera a dublagem de uma vez (é o que `dmaker dub ARQUIVO --to en` faz).

    Para revisar as traduções antes de sintetizar, use `dub prepare` e depois `dub render`."""
    from .media.ffmpeg import SubprocessRunner
    from .pipeline.dubbing import default_dubbing_service
    from .voice.synth import DRAFT_STEPS

    try:
        service = default_dubbing_service(SubprocessRunner(quiet=True), _console_log, device=device)
        dub, path = _prepare_dub(
            service,
            file,
            target,
            source,
            speaker,
            voice,
            keep_original,
            glossary,
            brand,
            project,
            fit,
            speakers,
        )
        _print_segments(dub)
        result = service.render(dub, out, steps=DRAFT_STEPS if draft and steps is None else steps)
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    console.print(f"  projeto: {path}", markup=False, highlight=False, soft_wrap=True)
    _print_dub_result(result)


if __name__ == "__main__":  # pragma: no cover
    app()
