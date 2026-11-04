"""Interface de linha de comando do DMaker. Só traduz argumentos em chamadas aos serviços."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markup import escape
from rich.table import Column, Table
from typer.core import TyperGroup

from . import __version__, config
from .domain.audio_presets import list_audio_presets
from .domain.models import format_size
from .domain.outputs import resolve_output
from .domain.presets import get_preset, list_presets


def _console_utf8() -> None:
    """Põe o stdout e o stderr em UTF-8: redirecionados, o Windows os abre em cp1252 e o Rich cai para ASCII.

    Mantém o tratamento de erro de cada fluxo (`errors`): o stderr segue sem estourar com um caractere raro.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors=stream.errors)
        except (AttributeError, ValueError):
            pass


class _Utf8Typer(typer.Typer):
    """App que põe o console em UTF-8 ao ser chamado, não ao ser importado nem num `@app.callback()`.

    O `--help`, o `--version` e os erros de uso saem antes do corpo de qualquer callback, e o Typer guarda só
    um por app; já a chamada do app é a única porta por onde todos eles passam, e um teste que importa
    `dmaker.cli` (ou usa o `CliRunner`) não a atravessa, então a codificação do processo dele não muda.
    """

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        _console_utf8()
        return super().__call__(*args, **kwargs)


app = _Utf8Typer(
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
        f"{result.preset.id} {result.preset.resolution})"
    )
    if result.thumbnail:
        console.print(f"  thumbnail: {result.thumbnail}")
    if result.captions_file:
        console.print(f"  legendas: {result.captions_file}")
    for w in result.warnings:
        console.print(f"[yellow]aviso:[/yellow] {escape(w)}")


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
        console.print(f"[yellow]aviso:[/yellow] {escape(w)}")


def _show_version(requested: bool) -> None:
    """Imprime a versão e encerra: roda como opção eager, antes de o Typer exigir um comando."""
    if requested:
        console.print(f"dmaker {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_show_version, is_eager=True, help="Mostra a versão."),
    ] = False,
) -> None:
    """Callback do app: existe para hospedar a opção global `--version`; o Typer guarda só um por app."""


# ---------- ambiente ----------


@app.command()
def doctor(
    hw: Annotated[bool, typer.Option(help="Testa encoders de hardware (nvenc/amf/qsv).")] = True,
    offline: Annotated[
        bool,
        typer.Option(
            "--offline",
            help="Confere se tudo que as funções usam já está baixado e mostra o que falha sem rede.",
        ),
    ] = False,
) -> None:
    """Verifica FFmpeg, fontes, marcas e dependências opcionais; com --offline, o que falta para usar sem internet."""
    from .domain.brand import available_brands
    from .media import fonts

    if offline:
        _doctor_offline()
        return
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
        # transições de movimento: zoom, desfoque, tira de quadros, luz gerada por expressão e comandos por quadro
        needed += ["perspective", "gblur", "hstack", "vstack", "geq", "sendcmd", "gradients"]
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
    from .media.browser import browser_problem

    problem = browser_problem()
    console.print(
        "  playwright e Chromium: ok (composição em HTML)"
        if problem is None
        else "  playwright e Chromium: [yellow]faltam[/yellow] (composição em HTML: dmaker setup --html)"
    )
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


def _doctor_offline() -> None:
    """O relatório de "funciona sem internet?": cada item com onde procurei e o comando para baixar."""
    from .agent.offline import DiskOfflineProbe, build_report, render_report
    from .agent.settings import SettingsError, load_settings

    try:
        settings = load_settings()
    except SettingsError as exc:
        _fail(str(exc))
    report = build_report(settings, DiskOfflineProbe())
    for line in render_report(report):
        console.print(line, markup=False, highlight=False, soft_wrap=True)
    if not report.ready:
        raise typer.Exit(code=1)


@app.command()
def setup(
    force: Annotated[bool, typer.Option(help="Baixa de novo mesmo se já existir.")] = False,
    html: Annotated[
        bool,
        typer.Option(
            "--html",
            help="Instala só o Chromium da composição em HTML e do PDF do manual (em bin/playwright).",
        ),
    ] = False,
) -> None:
    """Baixa FFmpeg (bin/ffmpeg), a fonte Poppins (assets/fonts) e o modelo de recorte de pessoa; com --html, o Chromium."""
    from .setup_tools import install_chromium

    if html:
        try:
            install_chromium()
        except RuntimeError as exc:
            _fail(escape(str(exc)))  # a mensagem traz `[html]`, que o Rich leria como marcação
        return
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
    if platform is None or platform.lower() == "audio":
        audio_table = Table(title="Presets de áudio (saída só de som, sem imagem)")
        for col in ("id", "formato", "taxa e canais", "padrão", "obs"):
            audio_table.add_column(col)
        for a in list_audio_presets():
            audio_table.add_row(a.id, a.name, a.resolution, a.default_label, a.notes)
        console.print(audio_table)


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
        console.print(f"[yellow]aviso:[/yellow] {escape(w)}")


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
        console.print(f"[yellow]aviso:[/yellow] {escape(w)}")


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
        console.print(f"[yellow]aviso:[/yellow] {escape(warning)}")
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
        f"{s.preset.id} ({s.preset.resolution}), tema {s.theme.name}"
    )
    for seg in s.segments:
        console.print(f"  [{seg.index}] {seg.type:5s} {seg.duration:6.2f}s  {seg.label}")
    for w in s.warnings:
        console.print(f"[yellow]aviso:[/yellow] {escape(w)}")


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
    from .pipeline import RenderOptions, create_renderer
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
        result = create_renderer(project, options).run()
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
    from .pipeline import RenderOptions, create_renderer

    project = _load(spec)
    for p in presets:
        resolve_output(p)

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
            result = create_renderer(project, RenderOptions(preview=preview, preset=p)).run()
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


transitions_app = typer.Typer(
    help="Transições entre trechos: a lista e a folha de contato (prévia) de cada uma.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(transitions_app, name="transitions")


@transitions_app.command("list")
def transitions_list(
    kind: Annotated[str | None, typer.Option(help="movimento | xfade")] = None,
) -> None:
    """Lista as transições aceitas em `transition.type` e o que cada uma faz."""
    from .domain.transitions import catalog

    wanted = {"movimento": "motion", "xfade": "xfade", None: None}.get(kind)
    if kind is not None and wanted is None:
        _fail("Tipo desconhecido: use movimento ou xfade.")
    table = Table(Column("nome", no_wrap=True), Column("tipo", no_wrap=True), "o que faz", title="Transições")
    for info in catalog():
        if wanted in (None, info.kind):
            table.add_row(info.name, "movimento" if info.kind == "motion" else "xfade", info.summary)
    console.print(table)
    console.print("Curva de tempo (`transition.curve`): linear (padrão), ease ou spring.")


@transitions_app.command("sheet")
def transitions_sheet(
    name: Annotated[str, typer.Argument(help="Nome da transição, ou `all` para todas.")],
    curve: Annotated[str, typer.Option(help="linear | ease | spring | all")] = "linear",
    out_dir: Annotated[Path | None, typer.Option(help="Pasta de saída (padrão: output/transitions).")] = None,
) -> None:
    """Folha de contato da transição: os quadros da troca entre dois clipes sintéticos (PNG)."""
    import shutil

    from .domain.curves import CURVES
    from .domain.transitions import all_transition_names, catalog
    from .media.ffmpeg import FFmpegError, SubprocessRunner
    from .pipeline.transition_preview import TransitionPreview

    names = [info.name for info in catalog()] if name == "all" else [name]
    unknown = [n for n in names if n not in all_transition_names()]
    if unknown:
        _fail(f"Transição desconhecida: {unknown[0]}. Veja `dmaker transitions list`.")
    chosen = list(CURVES) if curve == "all" else [curve]
    if any(c not in CURVES for c in chosen):
        _fail(f"Curva desconhecida: {curve}. Use {', '.join(CURVES)} ou all.")
    folder = out_dir or config.OUTPUT_DIR / "transitions"
    folder.mkdir(parents=True, exist_ok=True)
    preview = TransitionPreview(SubprocessRunner(quiet=True))
    try:
        for transition in names:
            for chosen_curve in chosen:
                target = folder / f"{transition}-{chosen_curve}.png"
                shutil.copyfile(preview.sheet(transition, chosen_curve), target)
                console.print(f"[green]Folha salva:[/green] {target}")
    except FFmpegError as exc:
        _fail(str(exc))


looks_app = typer.Typer(
    help="Looks: acabamentos visuais prontos por nome (cinema, quente, frio...) e a folha de contato de cada um.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(looks_app, name="looks")

EFFECT_LABELS = {
    "vignette": "vinheta",
    "glow": "brilho",
    "aberration": "aberração",
    "light_leak": "vazamento de luz",
    "grain": "grão",
}


def _brand_looks(brand: str | None) -> dict:
    """Looks da marca (brand.json); marca desconhecida ou look inválido param o comando com a mensagem."""
    from .domain.brand import load_theme
    from .domain.looks import available_looks

    if not brand:
        return {}
    try:
        theme = load_theme(brand)
        available_looks(theme.looks)
    except (FileNotFoundError, ValueError) as exc:
        _fail(str(exc))
    return theme.looks


@looks_app.command("list")
def looks_list(
    brand: Annotated[
        str | None, typer.Option(help="Soma os looks desta marca (os dela valem no lugar).")
    ] = None,
) -> None:
    """Lista os looks aceitos em `look` (no projeto e no trecho) e o que cada um faz."""
    from .domain.looks import NO_LOOK, available_looks, look_effects

    table = Table(
        Column("nome", no_wrap=True),
        Column("origem", no_wrap=True),
        "efeitos",
        "o que faz",
        title="Looks",
    )
    for look in available_looks(_brand_looks(brand)).values():
        effects = ", ".join(
            f"{EFFECT_LABELS[name]} {amount:g}" for name, amount in look_effects(look).items()
        )
        table.add_row(look.name, look.source, effects or "só cor", look.summary)
    console.print(table)
    console.print(
        f'No projeto: "look": "cinema". Num trecho, o dele vence; "{NO_LOOK}" desliga o do projeto. '
        "Trecho com `color` próprio não recebe o look do projeto."
    )


@looks_app.command("sheet")
def looks_sheet(
    name: Annotated[str, typer.Argument(help="Nome do look, ou `all` para todos lado a lado.")],
    brand: Annotated[str | None, typer.Option(help="Soma os looks desta marca.")] = None,
    out_dir: Annotated[Path | None, typer.Option(help="Pasta de saída (padrão: output/looks).")] = None,
) -> None:
    """Folha de contato: a mesma cena de teste sem acabamento e com o look (JPEG), da esquerda para a direita."""
    import shutil

    from .domain.looks import UnknownLookError, available_looks
    from .media.ffmpeg import FFmpegError, SubprocessRunner
    from .pipeline.look_preview import LookPreview

    brand_looks = _brand_looks(brand)
    folder = out_dir or config.OUTPUT_DIR / "looks"
    folder.mkdir(parents=True, exist_ok=True)
    preview = LookPreview(SubprocessRunner(quiet=True))
    try:
        names = list(available_looks(brand_looks)) if name == "all" else [name]
        jobs = [("looks-todos", preview.overview(brand_looks))] if name == "all" else []
        jobs += [(look, preview.sheet(look, brand_looks)) for look in names]
    except UnknownLookError as exc:
        _fail(f"{exc} Veja `dmaker looks list`.")
    except FFmpegError as exc:
        _fail(str(exc))
    for stem, source in jobs:
        target = folder / f"{stem}.jpg"
        shutil.copyfile(source, target)
        console.print(f"[green]Folha salva:[/green] {target}")
    if name == "all":
        console.print("Na folha dos todos, da esquerda para a direita: original, " + ", ".join(names) + ".")


html_app = typer.Typer(
    help="Composições em HTML: confere um quadro de uma composição antes de renderizar o vídeo.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(html_app, name="html")


@html_app.command("frame")
def html_frame(
    src: Annotated[Path, typer.Argument(help="Arquivo .html ou pasta com index.html.")],
    at: Annotated[float, typer.Option(help="Instante da composição, em segundos.")] = 0.0,
    size: Annotated[
        str,
        typer.Option(help="Tamanho da página, LARGURAxALTURA em px na base 1080 (como a área da região)."),
    ] = "1080x1920",
    out: Annotated[
        Path | None, typer.Option(help="PNG de saída (padrão: output/html/<nome>_<instante>s.png).")
    ] = None,
    duration: Annotated[
        float, typer.Option(help="Duração da composição em segundos (a página lê dmaker.duration).")
    ] = 5.0,
    fps: Annotated[float, typer.Option(help="Quadros por segundo da composição.")] = 30.0,
    scale: Annotated[float, typer.Option(help="Pixels de saída por px da página (0,5 gera a metade).")] = 1.0,
    brand: Annotated[str | None, typer.Option(help="Marca cujas cores e fonte a página recebe.")] = None,
    data: Annotated[str | None, typer.Option(help="Dados para a página (dmaker.data), em JSON.")] = None,
    background: Annotated[
        str | None, typer.Option(help="Cor lisa por baixo, para ver o transparente (ex.: #808080).")
    ] = None,
) -> None:
    """Renderiza um quadro da composição, direto no instante pedido, em PNG com fundo transparente."""
    from .pipeline.html_frame import default_frame_path, parse_size, render_html_frame

    try:
        page_size = parse_size(size)
        page_data = json.loads(data) if data else {}
        if not isinstance(page_data, dict):
            raise ValueError('--data precisa ser um objeto JSON, como \'{"titulo": "Oi"}\'')
        result = render_html_frame(
            src,
            out or default_frame_path(config.OUTPUT_DIR, src, at),
            at=at,
            size=page_size,
            duration=duration,
            fps=fps,
            scale=scale,
            data=page_data,
            brand=brand,
            background=background,
        )
    except json.JSONDecodeError as exc:
        _fail(escape(f"--data não é um JSON válido: {exc}"))
    except RENDER_ERRORS as exc:
        _fail(escape(str(exc)))
    console.print(
        f"[green]Quadro salvo:[/green] {escape(str(result.path))}  ({result.size[0]}x{result.size[1]})"
    )
    for warning in result.warnings:
        console.print(f"[yellow]aviso:[/yellow] {escape(warning)}")


infographics_app = typer.Typer(
    help="Infográficos prontos (contador, barra, linha, imagem, etiqueta, grifo, emoji): lista, vê um quadro e põe no projeto.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(infographics_app, name="infographics")


def _infographic_values(name: str, data: str | None, params: list[str] | None) -> dict:
    """Os parâmetros do pedido: o JSON de `--data` e os `--param nome=valor` (estes, convertidos pelo tipo do esquema)."""
    from .domain.infographics import find_infographic
    from .pipeline.infographics import coerce_assignments

    values = json.loads(data) if data else {}
    if not isinstance(values, dict):
        raise ValueError("--data precisa ser um objeto JSON, como '{\"ate\": 10000}'")
    schema = find_infographic(name).schema
    return {**values, **coerce_assignments(schema, params or [])}


@infographics_app.command("list")
def infographics_list(
    name: Annotated[
        str | None, typer.Argument(help="Mostra os parâmetros de um modelo (sem ele, a lista dos modelos).")
    ] = None,
) -> None:
    """Lista os infográficos prontos e, dado um nome, os parâmetros que ele aceita."""
    from .domain.infographics import InfographicError, find_infographic, load_infographics

    try:
        if name is None:
            table = Table(Column("nome", no_wrap=True), "o que faz", "parâmetros", title="Infográficos")
            for model in load_infographics().values():
                table.add_row(model.name, model.schema.description, ", ".join(model.schema.params))
            console.print(table)
            console.print(
                'No projeto: {"type": "html", "infographic": "contador", "data": {"ate": 10000}, "region": "topo"}. '
                "Veja um modelo com `dmaker infographics list <nome>`."
            )
            return
        schema = find_infographic(name).schema
    except (InfographicError, ValueError) as exc:
        _fail(escape(str(exc)))
    table = Table(
        Column("parâmetro", no_wrap=True),
        Column("tipo", no_wrap=True),
        "padrão ou limites",
        "o que é",
        title=f"{schema.title} ({schema.name})",
    )
    for param in schema.params.values():
        limits = "obrigatório" if param.required else ""
        if param.default is not None:
            limits = f"padrão {param.default!r}"
        if param.minimum is not None:
            limits += f" ({param.minimum:.15g} a {param.maximum:.15g})"
        if param.options:
            limits += f" [{', '.join(param.options)}]"
        table.add_row(param.name, param.type, limits.strip(), param.label)
    console.print(table)
    console.print(f"{escape(schema.description)}")


@infographics_app.command("frame")
def infographics_frame(
    name: Annotated[str, typer.Argument(help="Nome do modelo (veja `dmaker infographics list`).")],
    param: Annotated[
        list[str] | None,
        typer.Option("--param", "-p", help="Um parâmetro, como ate=10000 (repita para vários)."),
    ] = None,
    data: Annotated[
        str | None, typer.Option(help="Os parâmetros em JSON (os --param valem por cima).")
    ] = None,
    at: Annotated[
        float | None, typer.Option(help="Instante, em segundos (padrão: o modelo já desenhado).")
    ] = None,
    size: Annotated[
        str | None, typer.Option(help="LARGURAxALTURA da página, em px na base 1080 (padrão: o do modelo).")
    ] = None,
    out: Annotated[
        Path | None, typer.Option(help="PNG de saída (padrão: output/html/<nome>_<instante>s.png).")
    ] = None,
    brand: Annotated[
        str | None, typer.Option(help="Marca cujas cores, fonte e cantos o modelo recebe.")
    ] = None,
    background: Annotated[
        str | None, typer.Option(help="Cor lisa por baixo, para ver o transparente.")
    ] = "#0F172A",
) -> None:
    """Renderiza um quadro do infográfico com os valores pedidos, em PNG, pelo mesmo renderizador do vídeo."""
    from .pipeline.html_frame import default_frame_path, parse_size
    from .pipeline.infographics import infographic_frame

    try:
        values = _infographic_values(name, data, param)
        at_value = at if at is not None else None
        target = out or default_frame_path(config.OUTPUT_DIR, Path(name), at_value or 0.0)
        result = infographic_frame(
            name,
            target,
            params=values,
            at=at_value,
            size=parse_size(size) if size else None,
            brand=brand,
            background=background,
        )
    except json.JSONDecodeError as exc:
        _fail(escape(f"--data não é um JSON válido: {exc}"))
    except RENDER_ERRORS as exc:
        _fail(escape(str(exc)))
    console.print(
        f"[green]Quadro salvo:[/green] {escape(str(result.path))}  ({result.size[0]}x{result.size[1]})"
    )
    for warning in result.warnings:
        console.print(f"[yellow]aviso:[/yellow] {escape(warning)}")


@infographics_app.command("add")
def infographics_add(
    project_name: Annotated[str, typer.Argument(help="Projeto (nome em projects/ ou caminho do spec.json).")],
    name: Annotated[str, typer.Argument(help="Nome do modelo (veja `dmaker infographics list`).")],
    param: Annotated[
        list[str] | None,
        typer.Option("--param", "-p", help="Um parâmetro, como ate=10000 (repita para vários)."),
    ] = None,
    data: Annotated[
        str | None, typer.Option(help="Os parâmetros em JSON (os --param valem por cima).")
    ] = None,
    start: Annotated[float, typer.Option(help="Quando entra, em segundos.")] = 0.0,
    end: Annotated[float | None, typer.Option(help="Quando sai (padrão: o fim do vídeo).")] = None,
    region: Annotated[
        str | None, typer.Option(help="Região do projeto onde o modelo entra (ex.: topo).")
    ] = None,
) -> None:
    """Põe o infográfico nas sobreposições do projeto e salva. Sem região, ele entra na área própria do modelo."""
    from .pipeline.infographics import add_infographic
    from .pipeline.projects import load_project, save_project, summarize

    try:
        values = _infographic_values(name, data, param)
        loaded = load_project(project_name)
        project = add_infographic(loaded, name, values, start=start, end=end, region=region)
        path = save_project(project, loaded.base_dir)
        summary = summarize(project)
    except json.JSONDecodeError as exc:
        _fail(escape(f"--data não é um JSON válido: {exc}"))
    except (ValidationError, *RENDER_ERRORS) as exc:
        _fail(escape(str(exc)))
    console.print(f"[green]Infográfico {escape(name)} no projeto:[/green] {escape(str(path))}")
    for warning in summary.warnings:
        console.print(f"[yellow]aviso:[/yellow] {escape(warning)}")


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
    """Limpa o cache de trechos intermediários (cache/mez), proxies de prévia (cache/proxy), formas de
    onda (cache/waveform), os espectrogramas (cache/spectrogram), o áudio da prévia da linha do tempo (cache/preview-audio), os itens de áudio com
    efeitos aplicados (cache/audio-fx) e os quadros que o editor pede ao pipeline (cache/frames)."""
    import shutil

    n = 0
    for d in (
        config.MEZ_DIR,
        config.PROXY_DIR,
        config.WAVEFORM_DIR,
        config.SPECTROGRAM_DIR,
        config.PREVIEW_AUDIO_DIR,
        config.AUDIO_FX_DIR,
        config.FRAMES_DIR,
    ):
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
    if kind == "triage":
        from .agent.kits import kit_by_name

        titles = ", ".join(kit_by_name(name).title for name in data["kits"])
        console.print(f"  kit: {titles} ({data['method']})", style="dim", markup=False)
    elif kind == "tool_call":
        console.print(_agent_tool_call_line(data["name"], data["arguments"]), style="dim", markup=False)
    elif kind == "tool_blocked":
        first_line = (data["reason"] or "").splitlines()[0] if data["reason"] else ""
        console.print(f"  barrado: {first_line}", style="yellow", markup=False)
    elif kind == "tool_result":
        first_line = (data["result"] or "").splitlines()[0] if data["result"] else ""
        console.print(f"  <- {first_line}", style="dim", markup=False)


def _interactive() -> bool:
    return sys.stdin.isatty()


class _TerminalConfirmation:
    """Pergunta no terminal antes do que é longo ou difícil de desfazer; sem terminal interativo, recusa."""

    def confirm(self, request) -> bool:
        console.print()
        console.print(request.question, markup=False, highlight=False)
        if not _interactive():
            console.print("Sem terminal interativo para perguntar: não vou fazer isso.", markup=False)
            return False
        if request.kind == "voice_consent":
            return typer.confirm("O dono da voz autorizou o uso dela?", default=False)
        return typer.confirm("Confirma?", default=False)


def _agent_session(settings, on_event=None, policy=None):
    """A sessão do agente com o motor configurado, o servidor MCP em processo e a confirmação no terminal."""
    from .agent import AgentSession, build_chat
    from .agent.session import default_host_factory, server_tool_names
    from .pipeline.recipes import project_exists

    return AgentSession(
        chat=build_chat(settings),
        host_factory=default_host_factory(),
        available=server_tool_names(),
        policy=policy or _TerminalConfirmation(),
        on_event=on_event or _agent_on_event,
        free_html=settings.free_html,
        project_exists=project_exists,
    )


def _agent_settings(
    engine: str | None, model: str | None, url: str | None, num_ctx: int | None, timeout: float | None
):
    from .agent.settings import SettingsError, load_settings

    try:
        return load_settings(engine=engine, model=model, url=url, num_ctx=num_ctx, timeout=timeout)
    except SettingsError as exc:
        _fail(str(exc))


def _require_language_model(settings) -> None:
    """Para o comando cedo, com o remédio, quando o servidor do modelo está fora do ar ou falta o modelo."""
    from .agent import build_chat

    chat = build_chat(settings)
    if not chat.is_alive():
        start = (
            "abra o app do Ollama ou rode `ollama serve`"
            if settings.engine == "ollama"
            else "inicie o servidor"
        )
        _fail(f"{settings.engine_label} não está respondendo em {settings.url}; {start}.")
    if settings.engine == "ollama" and not chat.has_model():
        _fail(f"Modelo '{settings.model}' não encontrado no Ollama; rode `ollama pull {settings.model}`.")


agent_app = typer.Typer(
    help=(
        "Agente local: opera o DMaker por conversa com um modelo que roda na sua máquina, sem internet. "
        "Sem subcomando, abre a conversa no terminal."
    ),
    invoke_without_command=True,
    no_args_is_help=False,
)
app.add_typer(agent_app, name="agent")

ENGINE_HELP = "Motor do modelo: ollama (padrão) ou openai (llama.cpp server, LM Studio)."


@agent_app.callback()
def agent(
    ctx: typer.Context,
    model: Annotated[str | None, typer.Option(help="Modelo (padrão: DMAKER_AGENT_MODEL).")] = None,
    engine: Annotated[str | None, typer.Option(help=ENGINE_HELP)] = None,
    url: Annotated[str | None, typer.Option(help="Endereço do servidor do modelo.")] = None,
    num_ctx: Annotated[int | None, typer.Option(help="Tamanho do contexto (tokens), no Ollama.")] = None,
    timeout: Annotated[
        float | None, typer.Option(help="Espera máxima por resposta do modelo (s); modelo em CPU demora.")
    ] = None,
    once: Annotated[str | None, typer.Option(help="Executa um único pedido e sai.")] = None,
) -> None:
    """Opera o DMaker por conversa: a triagem escolhe o kit de ferramentas e o modelo só vê o manual dele.

    Render final, apagar e sobrescrever pedem a sua confirmação no terminal; clonar voz só com a autorização
    do dono da voz. Veja o capítulo "Usando com LLM local (Ollama)" do manual (docs/MANUAL.md).
    """
    if ctx.invoked_subcommand is not None:
        return
    settings = _agent_settings(engine, model, url, num_ctx, timeout)
    _require_language_model(settings)
    session = _agent_session(settings)

    def _ask(message: str) -> str | None:
        try:
            with console.status("pensando...", spinner="dots"):
                return session.ask(message)
        except (OSError, ValueError) as exc:
            console.print(f"[red]Erro de comunicação com o modelo: {exc}[/red]")
            return None

    if once is not None:
        answer = _ask(once)
        if answer is not None:
            console.print(answer, markup=False)
        return

    console.print(
        f"[bold]Agente DMaker[/bold] ({settings.model}, {settings.engine_label}). "
        "/sair encerra, /limpar reinicia a conversa, /ferramentas lista o que ele pode usar agora."
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
            session.reset()
            console.print("[dim]histórico limpo.[/dim]")
            continue
        if message == "/ferramentas":
            from .agent.kits import kit_names

            for name in session.tool_names(session.current_kits or kit_names()):
                console.print(f"  {name}", markup=False, highlight=False)
            continue
        answer = _ask(message)
        if answer is not None:
            console.print(answer, markup=False)


@agent_app.command("eval")
def agent_eval(
    model: Annotated[str | None, typer.Option(help="Modelo a medir (padrão: DMAKER_AGENT_MODEL).")] = None,
    engine: Annotated[str | None, typer.Option(help=ENGINE_HELP)] = None,
    url: Annotated[str | None, typer.Option(help="Endereço do servidor do modelo.")] = None,
    num_ctx: Annotated[int | None, typer.Option(help="Tamanho do contexto (tokens), no Ollama.")] = None,
    timeout: Annotated[float | None, typer.Option(help="Espera máxima por resposta do modelo (s).")] = None,
    cases: Annotated[
        Path | None, typer.Option(help="Arquivo da bateria (padrão: tests/data/agent_eval.json).")
    ] = None,
    only: Annotated[
        list[str] | None, typer.Option(help="Roda só estes pedidos (id); repita a opção.")
    ] = None,
    real_tools: Annotated[
        bool,
        typer.Option(
            "--real-tools/--stub-heavy",
            help="Executa de verdade as ferramentas pesadas (render, Whisper, dublagem) em vez de simulá-las.",
        ),
    ] = False,
    fake: Annotated[
        bool,
        typer.Option(
            "--fake", help="Usa o modelo falso que segue o roteiro de cada pedido (valida a bateria)."
        ),
    ] = False,
    out: Annotated[
        Path | None, typer.Option(help="Pasta do relatório (padrão: output/avaliacao-agente).")
    ] = None,
) -> None:
    """Mede o agente com a bateria de pedidos reais: acerto, passos, tempo por pedido e memória do modelo.

    Cada pedido roda numa pasta de dados temporária, com mídia sintética, e o relatório sai em Markdown e JSON.
    """
    from rich.markup import escape

    from .agent import evaluation as ev
    from .agent import evaluation_runner as runner

    settings = _agent_settings(engine, model, url, num_ctx, timeout)
    path = cases or config.ROOT / "tests" / "data" / "agent_eval.json"
    try:
        battery = ev.load_cases(path)
    except (FileNotFoundError, ValueError) as exc:
        _fail(escape(str(exc)))
    if only:
        battery = [case for case in battery if case.id in only]
    if not fake:
        _require_language_model(settings)
    report = runner.run_battery(
        battery,
        settings=settings,
        fake=fake,
        real_tools=real_tools,
        progress=lambda line: console.print(line, markup=False, highlight=False),
    )
    folder = out or config.OUTPUT_DIR / "avaliacao-agente"
    markdown_path, json_path = ev.write_report(report, folder)
    console.print("\n".join(ev.render_markdown(report)), markup=False, highlight=False, soft_wrap=True)
    console.print(f"\nRelatório gravado em {markdown_path} e {json_path}", markup=False)
    if not report.passed_threshold:
        raise typer.Exit(code=1)


# ---------- manual: partes geradas, exportação e ajuda ----------

manual_app = typer.Typer(
    help="Manual: regenera as partes automáticas (referência, docs/ia) e exporta em PDF e HTML.",
    no_args_is_help=True,
)
app.add_typer(manual_app, name="manual")


@manual_app.command("build")
def manual_build(
    check: Annotated[
        bool,
        typer.Option("--check", help="Só confere: sai com erro se `build` mudaria algum arquivo."),
    ] = False,
) -> None:
    """Regenera o que o manual tira do código (comandos, ferramentas MCP, campos da spec, índice) e `docs/ia`."""
    from rich.markup import escape

    from .manual import service
    from .manual.build import ManualBuildError

    try:
        names = service.check() if check else service.build()
    except ManualBuildError as exc:
        _fail(escape("O manual não fecha com o código:\n" + "\n".join(f"  - {p}" for p in exc.problems)))
    except (FileNotFoundError, service.NotACheckout) as exc:
        _fail(escape(str(exc)))
    if check:
        if names:
            _fail(
                "O manual está desatualizado; rode `dmaker manual build`:\n"
                + "\n".join(f"  - {n}" for n in names)
            )
        console.print("[green]O manual está em dia com o código.[/green]")
        return
    if not names:
        console.print("[green]Nada mudou:[/green] o manual já estava em dia.")
        return
    console.print(f"[green]{len(names)} arquivo(s) atualizado(s):[/green]")
    for name in names:
        console.print(f"  {name}", markup=False)


@manual_app.command("export")
def manual_export(
    pdf: Annotated[bool, typer.Option("--pdf", help="Só o PDF (sem nenhuma opção, gera os dois).")] = False,
    html: Annotated[bool, typer.Option("--html", help="Só o HTML de página única.")] = False,
    out: Annotated[Path | None, typer.Option(help="Pasta de saída (padrão: output/manual).")] = None,
) -> None:
    """Exporta o manual em HTML de página única e PDF, com as imagens e o sumário navegável."""
    from rich.markup import escape

    from .manual import service
    from .media.browser import BrowserUnavailable

    both = not pdf and not html
    try:
        report = service.export_manual(out, html=html or both, pdf=pdf or both)
    except (FileNotFoundError, BrowserUnavailable) as exc:
        _fail(escape(str(exc)))  # a mensagem traz ".[docs]", que o Rich leria como marcação
    for path in (report.html_path, report.pdf_path):
        if path:
            console.print(
                f"[green]Pronto:[/green] {path}  ({path.stat().st_size / 1e6:.1f} MB)", highlight=False
            )
    if report.pages:
        console.print(f"  PDF com {report.pages} páginas")
    if report.missing_images:
        console.print(f"[yellow]Imagens não encontradas:[/yellow] {', '.join(report.missing_images)}")


@app.command()
def ajuda(
    pergunta: Annotated[str, typer.Argument(help="Sua dúvida, em português.")],
    model: Annotated[str, typer.Option(help="Modelo do Ollama.")] = "gpt-oss:20b",
    url: Annotated[str | None, typer.Option(help="Endereço do servidor Ollama.")] = None,
    num_ctx: Annotated[int, typer.Option(help="Tamanho do contexto (tokens).")] = 16384,
    timeout: Annotated[float, typer.Option(help="Espera máxima pela resposta do modelo (s).")] = 900.0,
    no_model: Annotated[
        bool,
        typer.Option("--no-model", help="Só mostra os trechos do manual, sem pedir a resposta ao modelo."),
    ] = False,
    offer: Annotated[
        bool,
        typer.Option(
            "--offer/--no-offer", help="Depois da resposta, oferece executar a tarefa pelo agente local."
        ),
    ] = True,
) -> None:
    """Responde uma dúvida sobre o DMaker em português, com o modelo local e a busca no manual (sem internet).

    A resposta cita a seção do manual. Se a dúvida é uma tarefa que o agente local já sabe fazer, oferece executá-la.
    """
    import os

    from .agent.llm import OLLAMA_URL_ENV, OllamaChat
    from .manual import files, service
    from .manual.ask import answer_question, search_only, thinking_level
    from .manual.search import cached_index

    try:
        index = cached_index(files.read_manual())
    except FileNotFoundError as exc:
        _fail(str(exc))
    base_url = url or os.environ.get(OLLAMA_URL_ENV, "http://127.0.0.1:11434")
    chat = OllamaChat(
        model=model, base_url=base_url, num_ctx=num_ctx, timeout=timeout, think=thinking_level(model)
    )
    usable = not no_model and chat.is_alive() and chat.has_model()
    if not no_model and not usable:
        console.print(
            f"[yellow]O Ollama não está no ar em {base_url} ou falta o modelo '{model}' "
            f"(`ollama pull {model}`); mostro só os trechos do manual.[/yellow]"
        )
    try:
        if usable:
            with console.status("lendo o manual...", spinner="dots"):
                answer = answer_question(pergunta, index, chat, ia_doc=files.read_ia_doc)
        else:
            answer = search_only(pergunta, index, ia_doc=files.read_ia_doc)
    except (OSError, ValueError) as exc:
        _fail(f"Erro de comunicação com o Ollama: {exc}")
    console.print(answer.text, markup=False, highlight=False)
    invented = service.invented_commands(answer.text) if usable else []
    if invented:
        console.print(
            "\n[yellow]Atenção: o modelo citou comando(s) que a CLI não tem. Confira com "
            "`dmaker COMANDO --help` ou na seção do manual:[/yellow]"
        )
        for command in invented:
            console.print(f"  {command}", markup=False, highlight=False)
    if answer.sources:
        console.print("\n[bold]Seções do manual:[/bold]")
        for source in answer.sources:
            console.print(f"  {source.section}", markup=False, highlight=False)
    if offer and usable and answer.task_id and sys.stdin.isatty():
        _offer_agent(answer.task_id, pergunta, chat)


def _offer_agent(task_id: str, question: str, chat) -> None:
    """Pergunta se o agente local deve executar a tarefa do manual e, se a pessoa aceitar, abre a conversa."""
    from .agent import AgentLoop, McpToolHost, ToolGate
    from .agent.kits import BASE_TOOLS
    from .agent.prompt import task_prompt
    from .manual import service
    from .pipeline.recipes import project_exists

    offer = service.agent_offer(task_id)
    if offer is None:
        return
    if not offer.runnable:
        missing = ", ".join(offer.missing_tools)
        console.print(
            f"\nO agente local ainda não enxerga estas ferramentas da tarefa '{offer.title}': {missing}. "
            "Siga o passo a passo do manual ou peça ao Claude."
        )
        return
    if not typer.confirm(f"\nQuer que o agente local execute '{offer.title}' agora?", default=False):
        return
    tools = McpToolHost(allowed=list(dict.fromkeys([*BASE_TOOLS, *offer.tools])))
    gate = ToolGate(schemas={}, policy=_TerminalConfirmation(), project_exists=project_exists)
    loop = AgentLoop(
        model=chat, tools=tools, system=task_prompt(offer.manual), on_event=_agent_on_event, gate=gate
    )
    message = f"Pedido do usuário: {question}\nSiga o manual da tarefa e pergunte o que faltar."
    while message:
        try:
            with console.status("pensando...", spinner="dots"):
                console.print(loop.ask(message), markup=False)
        except (OSError, ValueError) as exc:
            console.print(f"[red]Erro de comunicação com o Ollama: {exc}[/red]")
            return
        try:
            message = console.input("[bold]você>[/bold] (vazio encerra) ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return


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
    """Narra um texto. Sem --voice usa a voz automática do OmniVoice (ou a de DMAKER_DEFAULT_VOICE); as vozes
    prontas (dora, alex, santa) usam o Kokoro, rápido; clones e vozes projetadas usam o OmniVoice (lento na CPU).
    O resultado de cada fala fica em cache. Toda fala sai com marca d'água inaudível e o arquivo com uma etiqueta
    de procedência (confira com `dmaker voice verify`)."""
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
    help="Áudio: exportar o projeto como WAV, MP3, FLAC, OGG, Opus, M4A ou AIFF (inteiro, por região, por trilha ou só "
    "um trecho), importar áudio bruto, isolar a voz (voz de um lado, música e ruído do outro) com o modelo local "
    "Demucs, a cadeia de efeitos de qualquer item de áudio ou do master (Amplificar, Normalizar, Inverter, Reverter, "
    "Repetir) e a edição de onda como no Audacity (silenciar, cortar, envelope, canais, colar, dividir, juntar, "
    "aparar, deslocar no tempo e o ganho e o pan da trilha).",
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


@audio_app.command("effects")
def audio_effects_list(
    effect: Annotated[
        str | None, typer.Argument(help="Tipo de um efeito, para ver só os parâmetros dele.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Saída em JSON, como a ferramenta MCP.")] = False,
) -> None:
    """Lista os efeitos de áudio que a spec aceita em `effects` (e em `audio.master_effects`): o nome em
    português e no Audacity, o que faz e os parâmetros com unidade, faixa e padrão."""
    from .domain.audio_effects import catalog_payload

    try:
        payload = catalog_payload(effect)
    except ValueError as exc:
        _fail(str(exc))
    if as_json:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    table = Table(
        Column("tipo", no_wrap=True),
        Column("nome", no_wrap=True),
        "no Audacity",
        "parâmetros",
        title="Efeitos de áudio",
    )
    for info in payload["effects"]:
        params = "; ".join(_effect_param_text(p) for p in info["parameters"]) or "nenhum"
        table.add_row(info["type"], info["label"], info["audacity_name"], params)
    console.print(table)
    for info in payload["effects"]:
        console.print(f"[bold]{info['label']}[/bold]: {info['summary']}", highlight=False)
    console.print("Em todo efeito: `enabled` (liga e desliga), `start` e `end` (o intervalo, em segundos).")
    console.print("Alvos: " + ", ".join(t["target"] for t in payload["targets"]), highlight=False)


def _effect_param_text(param: dict) -> str:
    unit = f" {param['unit']}" if param["unit"] else ""
    low, high = param["minimum"], param["maximum"]
    span = (
        ""
        if low is None and high is None
        else f" [{'' if low is None else f'{low:g}'}..{'' if high is None else f'{high:g}'}]"
    )
    return f"{param['name']} ({param['label']}{unit}{span}, padrão {param['default']!r})"


audio_effect_app = typer.Typer(
    help="Cadeia de efeitos de um item de áudio: adicionar, remover, mover, ligar, desligar e ajustar.",
    no_args_is_help=True,
)
audio_app.add_typer(audio_effect_app, name="effect")

_EFFECT_SPEC = Annotated[Path, typer.Argument(help="Caminho do spec.json.")]
_EFFECT_TARGET = Annotated[
    str,
    typer.Argument(
        help="Onde fica a cadeia: timeline.N, overlays.N, audio.voiceover.N, audio.narration.N, audio.music, "
        "audio.tracks.N ou audio.master."
    ),
]


def _parse_effect_params(raw: list[str] | None) -> dict:
    """`gain_db=6` vira {"gain_db": 6}: o valor é lido como JSON (número, true/false) e, se não for, fica texto."""
    params: dict = {}
    for item in raw or []:
        name, separator, value = item.partition("=")
        if not separator or not name:
            _fail(f"Parâmetro mal escrito: {item!r}. Use nome=valor, por exemplo gain_db=6.")
        try:
            params[name] = json.loads(value)
        except json.JSONDecodeError:
            params[name] = value
    return params


def _apply_effect_op(spec: Path, op: dict) -> None:
    """Aplica a operação à spec e a grava de volta, com o passo no histórico (`dmaker undo` o desfaz); erro de
    pedido ou de spec sai como mensagem, sem traceback."""
    from .domain.edits import EditError
    from .pipeline.edit_history import edit_and_record

    _load(spec)  # a spec ilegível sai com a mensagem de sempre
    try:
        edit_and_record(spec, {"type": "audio_effect", **op})
    except EditError as exc:
        _fail(str(exc))
    console.print(f"[green]Cadeia de efeitos atualizada:[/green] {spec}", highlight=False, soft_wrap=True)


@audio_effect_app.command("add")
def audio_effect_add(
    spec: _EFFECT_SPEC,
    target: _EFFECT_TARGET,
    effect: Annotated[str, typer.Argument(help="Tipo do efeito (veja `dmaker audio effects`).")],
    param: Annotated[
        list[str] | None, typer.Option("--param", "-p", help="Parâmetro do efeito, nome=valor (repetível).")
    ] = None,
    start: Annotated[float | None, typer.Option(help="Início do intervalo, em segundos do item.")] = None,
    end: Annotated[float | None, typer.Option(help="Fim do intervalo, em segundos do item.")] = None,
    position: Annotated[int | None, typer.Option(help="Posição na cadeia (padrão: no fim).")] = None,
    disabled: Annotated[bool, typer.Option(help="Adiciona já desligado.")] = False,
    region: Annotated[
        str | None,
        typer.Option(
            help="Uma região de marcador (marker:<texto>) no lugar de --start e --end; se o marcador for "
            "espectral, traz também low_hz e high_hz (o intervalo vem em segundos da linha do tempo)."
        ),
    ] = None,
) -> None:
    """Acrescenta um efeito à cadeia do item (por exemplo: audio effect add spec.json audio.voiceover.0 amplify
    -p gain_db=6; ou um efeito espectral numa região: ... spectral_delete --region "marker:plim")."""
    data: dict = {"type": effect, **_parse_effect_params(param)}
    if start is not None:
        data["start"] = start
    if end is not None:
        data["end"] = end
    if disabled:
        data["enabled"] = False
    op: dict = {"action": "add", "target": target, "effect": data}
    if position is not None:
        op["index"] = position
    if region is not None:
        op["region"] = region
    _apply_effect_op(spec, op)


@audio_effect_app.command("remove")
def audio_effect_remove(
    spec: _EFFECT_SPEC,
    target: _EFFECT_TARGET,
    index: Annotated[int, typer.Argument(help="Posição na cadeia.")],
) -> None:
    """Tira o efeito da posição `index` da cadeia."""
    _apply_effect_op(spec, {"action": "remove", "target": target, "index": index})


@audio_effect_app.command("move")
def audio_effect_move(
    spec: _EFFECT_SPEC,
    target: _EFFECT_TARGET,
    index: Annotated[int, typer.Argument(help="Posição atual na cadeia.")],
    to: Annotated[int, typer.Argument(help="Nova posição.")],
) -> None:
    """Muda a ordem da cadeia: o efeito de `index` vai para `to`."""
    _apply_effect_op(spec, {"action": "move", "target": target, "index": index, "to": to})


@audio_effect_app.command("enable")
def audio_effect_enable(
    spec: _EFFECT_SPEC,
    target: _EFFECT_TARGET,
    index: Annotated[int, typer.Argument(help="Posição na cadeia.")],
) -> None:
    """Liga o efeito da posição `index`."""
    _apply_effect_op(spec, {"action": "enable", "target": target, "index": index})


@audio_effect_app.command("disable")
def audio_effect_disable(
    spec: _EFFECT_SPEC,
    target: _EFFECT_TARGET,
    index: Annotated[int, typer.Argument(help="Posição na cadeia.")],
) -> None:
    """Desliga o efeito da posição `index` sem apagá-lo (o botão de bypass)."""
    _apply_effect_op(spec, {"action": "disable", "target": target, "index": index})


@audio_effect_app.command("set")
def audio_effect_set(
    spec: _EFFECT_SPEC,
    target: _EFFECT_TARGET,
    index: Annotated[int, typer.Argument(help="Posição na cadeia.")],
    param: Annotated[
        list[str] | None, typer.Option("--param", "-p", help="Parâmetro a mudar, nome=valor (repetível).")
    ] = None,
) -> None:
    """Muda os parâmetros do efeito da posição `index` (os que não forem citados ficam como estão)."""
    params = _parse_effect_params(param)
    if not params:
        _fail("Informe ao menos um parâmetro: --param nome=valor.")
    _apply_effect_op(spec, {"action": "set", "target": target, "index": index, "params": params})


# ---------- analisadores de áudio ----------

audio_analyze_app = typer.Typer(
    help="Analisar o áudio sem mudar o som: Contraste, Achar Clipping, Medir RMS, Espectro de Frequência (CSV e PNG), "
    "Marcar Sons, Achar Batidas, Exportar Amostras e cortar no ritmo.",
    no_args_is_help=True,
)
audio_app.add_typer(audio_analyze_app, name="analyze")


@audio_analyze_app.command("catalog")
def audio_analyze_catalog(
    analyzer: Annotated[
        str | None, typer.Argument(help="Tipo de um analisador, para ver só os parâmetros dele.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Saída em JSON, como a ferramenta MCP.")] = False,
) -> None:
    """Lista os analisadores de áudio: o nome em português e no Audacity, o que fazem e os parâmetros."""
    from .analysis import analyzer_catalog

    try:
        payload = analyzer_catalog(analyzer)
    except ValueError as exc:
        _fail(str(exc))
    if as_json:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    table = Table(
        Column("tipo", no_wrap=True),
        Column("nome", no_wrap=True),
        "no Audacity",
        "parâmetros",
        title="Analisadores de áudio",
    )
    for info in payload["analyzers"]:
        params = "; ".join(_effect_param_text(p) for p in info["parameters"]) or "nenhum"
        table.add_row(info["type"], info["label"], info["audacity_name"], params)
    console.print(table)
    for info in payload["analyzers"]:
        marks = f" Marca no grupo '{info['marker_group']}'." if info["marker_group"] else ""
        console.print(f"[bold]{info['label']}[/bold]: {info['summary']}{marks}", highlight=False)
    console.print("De onde vem o som: " + ", ".join(s["source"] for s in payload["sources"]), highlight=False)


def _analysis_request(
    analyzer: str,
    target: str | None,
    file: Path | None,
    start: str | None,
    end: str | None,
    param: list[str] | None,
    mark: bool | None,
    group: str | None,
):
    from .pipeline.audio_analysis import AnalysisRequest

    def instant(value: str | None) -> float | str | None:
        if value is None or value.strip().lower().startswith("marker:"):
            return value
        try:
            return float(value)
        except ValueError:
            _fail(f"Instante inválido: {value!r}. Use segundos (12.5) ou marker:<texto>.")

    return AnalysisRequest(
        analyzer,
        _parse_effect_params(param),
        target=target,
        file=str(file) if file else None,
        start=instant(start),
        end=instant(end),
        mark=mark,
        group=group,
    )


def _print_outcome(outcome) -> None:
    console.print(f"[green]{escape(outcome.result.summary)}[/green]", highlight=False, soft_wrap=True)
    console.print(
        f"Som analisado: {escape(outcome.label)}, de {outcome.interval[0]:g} s a {outcome.interval[1]:g} s."
    )
    for note in (*outcome.notes, *outcome.result.warnings):
        console.print(f"[yellow]{escape(note)}[/yellow]", highlight=False, soft_wrap=True)
    if outcome.marker_group is not None:
        console.print(
            f"Marcadores no grupo '{escape(outcome.marker_group)}': {outcome.markers_written} (os marcadores "
            "de outros grupos ficaram como estavam).",
            highlight=False,
        )
        for warning in outcome.edit_warnings:
            console.print(f"[yellow]{escape(warning)}[/yellow]", highlight=False)
    if outcome.exported:
        console.print(f"Arquivo gravado: {outcome.exported}", highlight=False, soft_wrap=True)


@audio_analyze_app.command("run")
def audio_analyze_run(
    spec: Annotated[Path, typer.Argument(help="Caminho do spec.json.")],
    analyzer: Annotated[str, typer.Argument(help="O analisador (veja `dmaker audio analyze catalog`).")],
    target: Annotated[
        str | None,
        typer.Option(
            help="De onde vem o som: timeline.N, overlays.N, audio.voiceover.N, audio.narration.N, audio.music, "
            "audio.tracks.N ou output (a saída final já renderizada, o padrão)."
        ),
    ] = None,
    file: Annotated[
        Path | None, typer.Option(help="Um arquivo de áudio ou vídeo solto, no lugar do alvo.")
    ] = None,
    start: Annotated[
        str | None, typer.Option(help="Início do trecho, em segundos do item ou marker:<texto>.")
    ] = None,
    end: Annotated[
        str | None, typer.Option(help="Fim do trecho, em segundos do item ou marker:<texto>.")
    ] = None,
    param: Annotated[
        list[str] | None,
        typer.Option("--param", "-p", help="Parâmetro do analisador, nome=valor (repetível)."),
    ] = None,
    mark: Annotated[
        bool | None,
        typer.Option(
            "--mark/--no-mark",
            help="Grava os marcadores da análise (padrão: sim para Marcar Sons e Achar Batidas, não nos outros).",
        ),
    ] = None,
    group: Annotated[
        str | None, typer.Option(help="Grupo de marcadores onde gravar (padrão: o do analisador).")
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(help="Exporta o resultado: .csv ou .txt (tabela), .png (espectro) ou .json."),
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Resultado completo em JSON, como a ferramenta MCP.")
    ] = False,
) -> None:
    """Roda um analisador sobre o áudio do projeto (por exemplo: audio analyze run spec.json clipping --target
    audio.voiceover.0)."""
    from .media.ffmpeg import FFmpegError
    from .pipeline.audio_analysis import analyze_project

    request = _analysis_request(analyzer, target, file, start, end, param, mark, group)
    try:
        outcome = analyze_project(spec, request, out=out)
    except (FFmpegError, *RENDER_ERRORS) as exc:
        _fail(str(exc))
    if as_json:
        console.print_json(json.dumps(outcome.to_dict(), ensure_ascii=False))
        return
    _print_outcome(outcome)


@audio_analyze_app.command("cut-on-beat")
def audio_cut_on_beat(
    spec: Annotated[Path, typer.Argument(help="Caminho do spec.json.")],
    source: Annotated[str, typer.Option(help="De onde vêm as batidas (padrão: a música).")] = "audio.music",
    tolerance: Annotated[
        float, typer.Option(help="Quanto, em segundos, um corte pode andar para cair numa batida.")
    ] = 0.2,
    apply: Annotated[
        bool, typer.Option("--apply", help="Anda os cortes (por padrão só propõe e mostra a lista).")
    ] = False,
    group: Annotated[
        str | None,
        typer.Option(help="Usa as batidas de um grupo de marcadores que já existe, no lugar da análise."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Resultado completo em JSON.")] = False,
) -> None:
    """Propõe (ou, com --apply, aplica) o corte de cada fronteira entre clipes na batida da música mais perto."""
    from .media.ffmpeg import FFmpegError
    from .pipeline.beat_cut import cut_on_beat

    try:
        outcome = cut_on_beat(spec, source=source, tolerance=tolerance, apply=apply, group=group)
    except (FFmpegError, *RENDER_ERRORS) as exc:
        _fail(str(exc))
    if as_json:
        console.print_json(json.dumps(outcome.to_dict(), ensure_ascii=False))
        return
    bpm = f", cerca de {outcome.bpm:g} batidas por minuto" if outcome.bpm else ""
    console.print(f"{outcome.beats} batida(s){bpm}. Tolerância de {outcome.tolerance:g} s.", highlight=False)
    table = Table("Trecho", "Corte hoje", "Batida", "Andaria", "Obs.", title="Fronteiras entre os trechos")
    for proposal in outcome.proposals:
        table.add_row(
            str(proposal.index + 1),
            f"{proposal.boundary:.3f} s",
            "" if proposal.beat is None else f"{proposal.beat:.3f} s",
            "" if proposal.shift is None else f"{proposal.shift * 1000:+.0f} ms",
            escape(proposal.reason or ""),
        )
    console.print(table)
    for warning in outcome.warnings:
        console.print(f"[yellow]{escape(warning)}[/yellow]", highlight=False)
    if apply:
        console.print(f"[green]{outcome.moved} corte(s) andaram para a batida.[/green]")
    else:
        console.print("Nada foi gravado. Use --apply para andar os cortes.")


# ---------- efeitos sonoros ----------

sfx_app = typer.Typer(
    help="Efeitos sonoros curtos (whoosh, pop, clique...) para pôr num instante do vídeo: ver e gerar a biblioteca.",
    no_args_is_help=True,
)
app.add_typer(sfx_app, name="sfx")


@sfx_app.command("list")
def sfx_list() -> None:
    """Lista os sons da biblioteca (nomes que a spec aceita em `audio.sfx` e em `sound`)."""
    from .sfx import library_names, library_path, sound_def

    table = Table("Som", "Duração", "No disco", "Para quê")
    for name in library_names():
        definition = sound_def(name)
        present = "sim" if library_path(name).exists() else "não (rode dmaker sfx build)"
        table.add_row(name, f"{definition.duration:.2f} s", present, definition.description)
    console.print(table)


@sfx_app.command("build")
def sfx_build(
    out_dir: Annotated[
        Path | None,
        typer.Option("--out", help="Pasta de saída (padrão: assets/sfx, a biblioteca do DMaker)."),
    ] = None,
) -> None:
    """Sintetiza de novo os sons da biblioteca (determinístico: o mesmo código gera os mesmos arquivos) e o
    LICENSES. Só é preciso ao mudar uma receita em `sfx/synth.py`."""
    from .sfx import write_library

    for path in write_library(out_dir):
        console.print(f"[green]gravado[/green] {path}", highlight=False, soft_wrap=True)


# ---------- marcadores ----------

# ---------- edição de onda e histórico ----------

_WAVE_SPEC = Annotated[Path, typer.Argument(help="Caminho do spec.json.")]
_WAVE_TARGET = Annotated[
    str,
    typer.Argument(
        help="O item de áudio: timeline.N (som do clipe), overlays.N (PiP), audio.voiceover.N, audio.narration.N, "
        "audio.tracks.N, audio.music ou audio.master."
    ),
]
_WAVE_START = Annotated[
    str | None, typer.Option("--start", help="Início, em segundos do vídeo final (ou marker:<texto>).")
]
_WAVE_END = Annotated[
    str | None, typer.Option("--end", help="Fim, em segundos do vídeo final (ou marker:<texto>).")
]
_WAVE_REGION = Annotated[
    str | None,
    typer.Option("--region", help="Uma região de marcador (marker:<texto>), no lugar de --start e --end."),
]


def _instant_arg(value: str | None) -> float | str | None:
    """Um instante da linha de comando: um número de segundos, ou `marker:<texto>` (que o servidor resolve)."""
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return value


def _wave_op(operation: str, target: str | None = None, **fields: object) -> dict:
    """O pedido de `edit_project` a partir dos argumentos da linha de comando: só entra o que foi dado."""
    op: dict = {"type": operation}
    if target is not None:
        op["target"] = target
    op.update({name: value for name, value in fields.items() if value is not None})
    return op


def _run_wave_edit(spec: Path, op: dict, done: str) -> None:
    """Aplica a edição à spec, guarda o passo no histórico (`dmaker undo` o desfaz) e grava; recusa sai como mensagem."""
    from .domain.edits import EditError
    from .pipeline.edit_history import edit_and_record

    try:
        report, _ = edit_and_record(spec, op)
    except EditError as exc:
        _fail(str(exc))
    except RENDER_ERRORS as exc:
        _fail(str(exc))
    console.print(f"[green]{done}[/green] (desfaça com `dmaker undo`)", highlight=False)
    for note in report.notes:
        console.print(escape(note), highlight=False)
    for warning in report.warnings:
        console.print(f"[yellow]aviso:[/yellow] {escape(warning)}")


@audio_app.command("truncate-silence")
def audio_truncate_silence_command(
    spec: _WAVE_SPEC,
    target: _WAVE_TARGET,
    threshold_db: Annotated[
        float, typer.Option("--threshold-db", help="Abaixo deste nível (dBFS, de -80 a -20) é silêncio.")
    ] = -20.0,
    min_duration: Annotated[
        float, typer.Option("--min-duration", help="Só pausas de pelo menos isto (segundos) são encurtadas.")
    ] = 0.5,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="truncate: cada pausa vira --truncate-to segundos; compress: o que passa da duração mínima "
            "encolhe para --compress-percent %.",
        ),
    ] = "truncate",
    truncate_to: Annotated[
        float, typer.Option("--truncate-to", help="No modo truncate, a duração que a pausa passa a ter (s).")
    ] = 0.5,
    compress_percent: Annotated[
        float, typer.Option("--compress-percent", help="No modo compress, quanto do excesso fica (0 a 100).")
    ] = 50.0,
    start: _WAVE_START = None,
    end: _WAVE_END = None,
    region: _WAVE_REGION = None,
) -> None:
    """Encurta as pausas de um clipe (imagem e som juntos) ou de uma voz gravada, sem cortar fala (o Truncate Silence
    do Audacity). A boca continua sincronizada e os marcadores acompanham."""
    op = _wave_op(
        "audio_truncate_silence",
        target,
        threshold_db=threshold_db,
        min_duration=min_duration,
        mode=mode,
        truncate_to=truncate_to,
        compress_percent=compress_percent,
        start=_instant_arg(start),
        end=_instant_arg(end),
        region=region,
    )
    _run_wave_edit(spec, op, "Silêncios truncados.")


noise_profile_app = typer.Typer(
    help="Perfis de ruído do projeto, o primeiro passo da Redução de ruído (efeito noise_reduction).",
    no_args_is_help=True,
)
audio_app.add_typer(noise_profile_app, name="noise-profile")


@noise_profile_app.command("add")
def noise_profile_add(
    spec: _WAVE_SPEC,
    name: Annotated[str, typer.Argument(help="O nome do perfil (a Redução de ruído o cita em `profile`).")],
    target: _WAVE_TARGET,
    start: _WAVE_START = None,
    end: _WAVE_END = None,
    as_json: Annotated[bool, typer.Option("--json", help="Saída em JSON.")] = False,
) -> None:
    """Guarda o trecho que só tem chiado como perfil e mostra o nível do ruído por banda. Sem --start e --end, o perfil
    é o trecho mais quieto do item. Desfaça com `dmaker undo`."""
    from .domain.edits import EditError
    from .pipeline.noise_profiles import capture_noise_profile

    try:
        report = capture_noise_profile(spec, name, target, _instant_arg(start), _instant_arg(end))
    except (EditError, ValueError, FileNotFoundError) as exc:
        _fail(str(exc))
    if as_json:
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return
    console.print(
        f"[green]Perfil {escape(name)} guardado[/green]: {escape(report['target'])} de {report['start']:.3f} a "
        f"{report['end']:.3f} s, nível {report['level_db']:.1f} dBFS (desfaça com `dmaker undo`)",
        highlight=False,
    )
    table = Table("Banda (Hz)", "Nível (dBFS)")
    for band in report["bands"]:
        table.add_row(f"{band['hz']:g}", f"{band['db']:.1f}")
    console.print(table)


@noise_profile_app.command("list")
def noise_profile_list(spec: _WAVE_SPEC) -> None:
    """Lista os perfis de ruído do projeto."""
    project = _load(spec)
    profiles = project.audio.noise_profiles
    if not profiles:
        console.print("O projeto não tem perfis de ruído (crie com `dmaker audio noise-profile add`).")
        return
    table = Table("Perfil", "Item", "Início (s)", "Fim (s)")
    for key, profile in profiles.items():
        table.add_row(key, profile.target, f"{profile.start:.3f}", f"{profile.end:.3f}")
    console.print(table)


@noise_profile_app.command("remove")
def noise_profile_remove(
    spec: _WAVE_SPEC, name: Annotated[str, typer.Argument(help="O nome do perfil.")]
) -> None:
    """Apaga um perfil de ruído (recusa se algum efeito ainda o usa)."""
    _run_wave_edit(spec, {"type": "noise_profile_remove", "name": name}, f"Perfil {name} apagado.")


@audio_effect_app.command("preset")
def audio_effect_preset(
    spec: _EFFECT_SPEC,
    target: _EFFECT_TARGET,
    preset: Annotated[str, typer.Argument(help="O id da predefinição (veja `dmaker audio effects`).")],
    position: Annotated[int | None, typer.Option(help="Posição na cadeia (padrão: no fim).")] = None,
) -> None:
    """Põe no item uma cadeia pronta (por exemplo: audio effect preset spec.json audio.narration.0 podcast_voice). Cada
    efeito entra separado, e a pessoa ajusta ou tira depois."""
    op: dict = {"action": "preset", "target": target, "preset": preset}
    if position is not None:
        op["index"] = position
    _apply_effect_op(spec, op)


@audio_effect_app.command("action")
def audio_effect_action_command(
    spec: _EFFECT_SPEC,
    effect: Annotated[str, typer.Argument(help="Tipo do efeito (por exemplo noise_gate).")],
    action: Annotated[str, typer.Argument(help="A ação do efeito (por exemplo analyze_noise).")],
    target: Annotated[
        str | None, typer.Option(help="O item de onde sai o trecho (por exemplo audio.voiceover.0).")
    ] = None,
    profile: Annotated[
        str | None,
        typer.Option(help="Um perfil de ruído do projeto, ou auto (o trecho mais quieto do item)."),
    ] = None,
    start: _WAVE_START = None,
    end: _WAVE_END = None,
    as_json: Annotated[bool, typer.Option("--json", help="Saída em JSON, como a ferramenta MCP.")] = False,
) -> None:
    """Roda uma ação de um efeito e mostra o que ela sugere para os campos (o Analisar ruído do Noise Gate mede um trecho
    sem fala e sugere o limiar). Só lê: para gravar o valor, use `dmaker audio effect set`."""
    from .domain.edits import EditError
    from .pipeline.effect_actions import run_effect_action

    params = {"target": target, "profile": profile, "start": _instant_arg(start), "end": _instant_arg(end)}
    try:
        report = run_effect_action(
            _load(spec), effect, action, {key: value for key, value in params.items() if value is not None}
        )
    except (EditError, ValueError, FileNotFoundError) as exc:
        _fail(str(exc))
    if as_json:
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return
    console.print(escape(report.get("message", "Pronto.")), highlight=False)
    for name, value in report["fills"].items():
        console.print(f"  {name} = {value}", highlight=False)


RESPONSE_TABLE_ROWS = 24


@audio_effect_app.command("response")
def audio_effect_response_command(
    effect: Annotated[str, typer.Argument(help="Tipo do efeito de equalização (por exemplo highpass).")],
    param: Annotated[
        list[str] | None, typer.Option("--param", "-p", help="Parâmetro do efeito, nome=valor (repetível).")
    ] = None,
    points: Annotated[int, typer.Option(help="Quantas frequências, de 20 Hz a 20 kHz em oitavas.")] = 256,
    as_json: Annotated[
        bool, typer.Option("--json", help="Saída em JSON {hz, db}, como a ferramenta MCP.")
    ] = False,
) -> None:
    """Mostra a resposta de frequência de um efeito de equalização (o ganho em dB por frequência), a mesma curva que o
    gráfico da interface desenha, por exemplo: audio effect response highpass -p frequency_hz=80 -p slope_db=24."""
    from .pipeline.effect_response import effect_frequency_response

    try:
        response = effect_frequency_response({"type": effect, **_parse_effect_params(param)}, points)
    except ValueError as exc:
        _fail(str(exc))
    if as_json:
        typer.echo(json.dumps(response, ensure_ascii=False))
        return
    step = max(1, len(response["hz"]) // RESPONSE_TABLE_ROWS)
    table = Table(Column("Hz", justify="right"), Column("dB", justify="right"), title=f"Resposta de {effect}")
    for hz, db in list(zip(response["hz"], response["db"], strict=True))[::step]:
        table.add_row(f"{hz:g}", f"{db:+.2f}")
    console.print(table)


audio_preset_app = typer.Typer(
    help="Predefinições de efeitos de áudio que você salva por nome (a cadeia de efeitos já ajustada) para pôr em outros "
    "itens com `dmaker audio effect preset`.",
    no_args_is_help=True,
)
audio_app.add_typer(audio_preset_app, name="preset")


@audio_preset_app.command("list")
def audio_preset_list(
    as_json: Annotated[bool, typer.Option("--json", help="Saída em JSON, como a ferramenta MCP.")] = False,
) -> None:
    """Lista as predefinições que você salvou (as embutidas aparecem em `dmaker audio effects --json`)."""
    from .domain.audio_effects import list_user_presets

    try:
        presets = [preset.to_dict() for preset in list_user_presets()]
    except ValueError as exc:
        _fail(str(exc))
    if as_json:
        typer.echo(json.dumps({"presets": presets}, ensure_ascii=False, indent=2))
        return
    if not presets:
        console.print("Nenhuma predefinição salva. Salve uma com `dmaker audio preset save`.")
        return
    table = Table(Column("id", no_wrap=True), "nome", "efeitos", title="Predefinições salvas")
    for preset in presets:
        table.add_row(
            preset["id"], preset["label"], ", ".join(effect["type"] for effect in preset["effects"])
        )
    console.print(table)


@audio_preset_app.command("save")
def audio_preset_save(
    name: Annotated[
        str, typer.Argument(help="O nome da predefinição (salvar de novo com o mesmo nome a troca).")
    ],
    effect: Annotated[
        list[str] | None,
        typer.Option(
            "--effect",
            "-e",
            help='Um efeito em JSON, por exemplo \'{"type": "highpass", "frequency_hz": 80}\' (repetível).',
        ),
    ] = None,
    file: Annotated[
        Path | None, typer.Option("--file", help="Um arquivo JSON com a lista de efeitos da cadeia.")
    ] = None,
    summary: Annotated[str, typer.Option(help="Uma frase do que a predefinição faz.")] = "",
) -> None:
    """Salva uma cadeia de efeitos com um nome, na pasta de dados (effect-presets.json). O intervalo e o bypass de cada
    efeito não entram: a predefinição vale para qualquer item."""
    from .domain.audio_effects import save_user_preset

    effects: list = []
    try:
        for text in effect or []:
            effects.append(json.loads(text))
        if file is not None:
            loaded = json.loads(file.read_text(encoding="utf-8"))
            effects.extend(loaded if isinstance(loaded, list) else [loaded])
    except (OSError, ValueError) as exc:
        _fail(f"Não consegui ler os efeitos: {exc}")
    try:
        preset = save_user_preset(name, effects, summary)
    except ValueError as exc:
        _fail(str(exc))
    console.print(f"[green]Predefinição salva:[/green] {preset.label} (id {preset.id})", highlight=False)


@audio_preset_app.command("remove")
def audio_preset_remove(
    preset_id: Annotated[str, typer.Argument(help="O id da predefinição (veja `dmaker audio preset list`).")],
) -> None:
    """Apaga uma predefinição salva. As embutidas não se apagam."""
    from .domain.audio_effects import remove_user_preset

    try:
        preset = remove_user_preset(preset_id)
    except ValueError as exc:
        _fail(str(exc))
    console.print(f"[green]Predefinição removida:[/green] {preset.label}", highlight=False)


duck_app = typer.Typer(
    help="Auto Duck: abaixa uma trilha enquanto outra fala (a música sob a voz, o DJ sob o celebrante).",
    no_args_is_help=True,
)
audio_app.add_typer(duck_app, name="duck")

_DUCK_OPTIONS = {
    "amount_db": "Quanto o fundo abaixa, em dB (padrão -12).",
    "threshold_db": "Nível RMS da chave a partir do qual ela conta como som (padrão -30).",
    "max_pause": "Pausa da chave, em segundos, que ainda não deixa o fundo voltar (padrão 1).",
    "outer_fade_down": "Descida antes da chave soar, em segundos (padrão 0,5).",
    "inner_fade_down": "Descida dentro do trecho da chave (padrão 0).",
    "inner_fade_up": "Subida dentro do trecho da chave (padrão 0).",
    "outer_fade_up": "Subida depois da chave calar, em segundos (padrão 0,5).",
}


@duck_app.command("add")
def duck_add(
    spec: _EFFECT_SPEC,
    background: Annotated[str, typer.Argument(help="A trilha que abaixa: A1, A2..., MUS, NAR, VO ou SFX.")],
    key: Annotated[str, typer.Argument(help="A trilha que comanda: o fundo abaixa quando ela soa.")],
    param: Annotated[
        list[str] | None,
        typer.Option(
            "--param", "-p", help="Ajuste da regra, nome=valor (amount_db, threshold_db, max_pause...)."
        ),
    ] = None,
) -> None:
    """Acrescenta uma regra (por exemplo: audio duck add spec.json MUS VO -p amount_db=-15). Uma regra para a música
    substitui o ducking antigo dela; a faixa externa só abaixa sob outra faixa externa."""
    _run_wave_edit(
        spec,
        {"type": "auto_duck_add", "background": background, "key": key, **_parse_effect_params(param)},
        "Regra de Auto Duck acrescentada.",
    )


@duck_app.command("set")
def duck_set(
    spec: _EFFECT_SPEC,
    index: Annotated[int, typer.Argument(help="A posição da regra (veja `dmaker audio duck list`).")],
    param: Annotated[
        list[str] | None, typer.Option("--param", "-p", help="Ajuste da regra, nome=valor.")
    ] = None,
) -> None:
    """Muda campos de uma regra (os que não forem citados ficam como estão)."""
    _run_wave_edit(
        spec,
        {"type": "auto_duck_set", "index": index, **_parse_effect_params(param)},
        "Regra de Auto Duck mudada.",
    )


@duck_app.command("remove")
def duck_remove(
    spec: _EFFECT_SPEC, index: Annotated[int, typer.Argument(help="A posição da regra.")]
) -> None:
    """Tira uma regra de Auto Duck."""
    _run_wave_edit(spec, {"type": "auto_duck_remove", "index": index}, "Regra de Auto Duck removida.")


@duck_app.command("list")
def duck_list(spec: _EFFECT_SPEC) -> None:
    """Lista as regras de Auto Duck do projeto."""
    project = _load(spec)
    rules = project.audio.ducks
    music = project.audio.music
    if not rules:
        legacy = "ligado" if music is not None and music.ducking else "desligado"
        console.print(
            f"O projeto não tem regra de Auto Duck (o ducking antigo da música está {legacy}). "
            "Crie com `dmaker audio duck add`."
        )
        return
    table = Table("#", "Abaixa", "Sob", "Quantidade (dB)", "Limiar (dB)", "Pausa (s)", "Rampas (s)")
    for position, rule in enumerate(rules):
        ramps = (
            f"{rule.outer_fade_down:g}/{rule.inner_fade_down:g}/{rule.inner_fade_up:g}/{rule.outer_fade_up:g}"
        )
        table.add_row(
            str(position),
            rule.background,
            rule.key,
            f"{rule.amount_db:g}",
            f"{rule.threshold_db:g}",
            f"{rule.max_pause:g}",
            ramps,
        )
    console.print(table)
    console.print("Rampas: descida de fora / de dentro, subida de dentro / de fora.")
    if any(rule.is_music_rule for rule in rules):
        console.print("A regra da música substitui o ducking antigo (`music.ducking`).")


@audio_app.command("silence")
def audio_silence_command(
    spec: _WAVE_SPEC,
    target: _WAVE_TARGET,
    start: _WAVE_START = None,
    end: _WAVE_END = None,
    region: _WAVE_REGION = None,
) -> None:
    """Silencia um intervalo do som de um item, sem mexer na duração nem na imagem (o Silence Audio do Audacity)."""
    op = _wave_op("audio_silence", target, start=_instant_arg(start), end=_instant_arg(end), region=region)
    _run_wave_edit(spec, op, "Intervalo silenciado.")


@audio_app.command("cut")
def audio_cut_command(
    spec: _WAVE_SPEC,
    target: _WAVE_TARGET,
    start: _WAVE_START = None,
    end: _WAVE_END = None,
    region: _WAVE_REGION = None,
) -> None:
    """Corta um intervalo do som: o resto recua. Em clipe e PiP o fim completa com silêncio; na voz gravada e na
    música o item encolhe, e a voz gravada que vem depois recua junto (o Delete do Audacity)."""
    op = _wave_op("audio_cut", target, start=_instant_arg(start), end=_instant_arg(end), region=region)
    _run_wave_edit(spec, op, "Intervalo cortado.")


@audio_app.command("envelope")
def audio_envelope_command(
    spec: _WAVE_SPEC,
    target: _WAVE_TARGET,
    point: Annotated[
        list[str],
        typer.Option(
            "--point",
            "-p",
            help="Um ponto da curva, instante=ganho em dB (repetível): -p 10=0 -p 12=-12 baixa 12 dB entre 10 e 12 s.",
        ),
    ],
) -> None:
    """Desenha o volume ao longo do item por pontos, com retas em dB entre eles (a ferramenta Envelope do Audacity)."""
    points = []
    for raw in point:
        instant, separator, gain = raw.rpartition("=")
        if not separator or not instant:
            _fail(f"Ponto mal escrito: {raw!r}. Use instante=ganho, por exemplo 10=0.")
        try:
            points.append({"at": _instant_arg(instant), "db": float(gain)})
        except ValueError:
            _fail(f"Ganho inválido em {raw!r}: use um número de dB.")
    _run_wave_edit(spec, _wave_op("audio_envelope", target, points=points), "Envelope aplicado.")


@audio_app.command("channels")
def audio_channels_command(
    spec: _WAVE_SPEC,
    target: _WAVE_TARGET,
    mode: Annotated[
        str,
        typer.Argument(
            help="mono (mistura os dois canais), swap (troca esquerdo e direito), left ou right (esse canal sai "
            "nos dois lados)."
        ),
    ],
    start: _WAVE_START = None,
    end: _WAVE_END = None,
) -> None:
    """Mexe nos canais do som de um item (estéreo para mono, trocar canais, usar só um lado: o caso da lapela)."""
    op = _wave_op("audio_channels", target, mode=mode, start=_instant_arg(start), end=_instant_arg(end))
    _run_wave_edit(spec, op, "Canais ajustados.")


@audio_app.command("fade")
def audio_fade_command(
    spec: _WAVE_SPEC,
    target: _WAVE_TARGET,
    side: Annotated[str, typer.Argument(help="in (abre no começo do item) ou out (fecha no fim).")],
    duration: Annotated[
        float,
        typer.Argument(help="Quanto dura o fade, em segundos, contado da borda do item. 0 tira o fade."),
    ],
    curve: Annotated[
        str | None,
        typer.Option(
            "--curve",
            help="linear (padrão), logarithmic, exponential, sine (S) ou quadratic. Sem ela, mantém a que o fade já tem.",
        ),
    ] = None,
) -> None:
    """Põe, muda ou tira o fade da borda de um item de áudio, com a curva escolhida (o Fade In e o Fade Out do Audacity).
    É o fade que a alça da linha do tempo mexe; para um fade em um trecho marcado, use `audio effect add`."""
    op = _wave_op("audio_fade", target, side=side, duration=duration, curve=curve)
    _run_wave_edit(spec, op, "Fade ajustado." if duration > 0 else "Fade removido.")


@audio_app.command("crossfade-tracks")
def audio_crossfade_tracks_command(
    spec: _WAVE_SPEC,
    out_target: Annotated[
        str, typer.Argument(help="O item que some (mesma forma do alvo de `audio silence`).")
    ],
    in_target: Annotated[str, typer.Argument(help="O item que entra.")],
    start: Annotated[str, typer.Option("--start", help="Início do cruzamento, em segundos do vídeo final.")],
    end: Annotated[str, typer.Option("--end", help="Fim do cruzamento, em segundos do vídeo final.")],
    kind: Annotated[
        str,
        typer.Option(
            "--kind",
            help="constant_gain (soma de amplitudes: sons iguais), constant_power_1 (padrão), constant_power_2 ou custom.",
        ),
    ] = "constant_power_1",
    curve: Annotated[
        str | None,
        typer.Option("--curve", help="Só no custom: a forma (up, down, s_up, s_down, sine_up, sine_down)."),
    ] = None,
    mid_adjust: Annotated[
        float | None, typer.Option("--mid-adjust", help="Só no custom: o ajuste do meio, de -100 a 100.")
    ] = None,
) -> None:
    """Uma trilha some enquanto outra entra, no intervalo dado (o Crossfade Tracks do Audacity). Grava um Fade Ajustável
    em cada item, com as curvas casadas, num passo só do histórico; a mixagem não muda."""
    op = {
        "type": "audio_crossfade_tracks",
        "out_target": out_target,
        "in_target": in_target,
        "start": _instant_arg(start),
        "end": _instant_arg(end),
        "kind": kind,
    }
    if curve is not None:
        op["curve"] = curve
    if mid_adjust is not None:
        op["mid_adjust"] = mid_adjust
    _run_wave_edit(spec, op, "Crossfade de trilhas feito.")


@audio_app.command("crossfade-clips")
def audio_crossfade_clips_command(
    spec: _WAVE_SPEC,
    index: Annotated[
        int, typer.Argument(help="O clipe que entra no corte (1 é o segundo trecho da linha do tempo).")
    ],
    duration: Annotated[
        float,
        typer.Argument(
            help="Quanto dura o cruzamento do som, em segundos (metade antes e metade depois do corte). 0 tira."
        ),
    ] = 0.5,
    curve: Annotated[
        str | None,
        typer.Option("--curve", help="constant_gain, constant_power_1 (padrão) ou constant_power_2."),
    ] = None,
) -> None:
    """Cruza o som de dois clipes vizinhos sem mexer na imagem, que continua trocando no quadro exato do corte (o J-cut e o
    L-cut). O som de cada lado vem da sobra da fonte além do ponto de entrada e do de saída."""
    op = {"type": "audio_crossfade_clips", "index": index, "duration": duration}
    if curve is not None:
        op["curve"] = curve
    _run_wave_edit(spec, op, "Crossfade de som ajustado." if duration > 0 else "Crossfade de som removido.")


@audio_app.command("paste")
def audio_paste_command(
    spec: _WAVE_SPEC,
    target: _WAVE_TARGET,
    at: Annotated[
        str, typer.Option("--at", help="Onde colar, em segundos do vídeo final (ou marker:<texto>).")
    ],
    start: _WAVE_START = None,
    end: _WAVE_END = None,
    region: _WAVE_REGION = None,
) -> None:
    """Copia um trecho do som de um item (sem --start e --end, o item inteiro) e cola num instante como uma voz
    gravada nova, que aponta para o mesmo arquivo (Copy e Paste do Audacity)."""
    op = _wave_op(
        "audio_paste",
        target,
        at=_instant_arg(at),
        start=_instant_arg(start),
        end=_instant_arg(end),
        region=region,
    )
    _run_wave_edit(spec, op, "Trecho colado.")


@audio_app.command("duplicate")
def audio_duplicate_command(
    spec: _WAVE_SPEC,
    target: _WAVE_TARGET,
    start: _WAVE_START = None,
    end: _WAVE_END = None,
    region: _WAVE_REGION = None,
) -> None:
    """Duplica o item (ou um trecho dele) como uma voz gravada nova, logo depois do original."""
    op = _wave_op("audio_duplicate", target, start=_instant_arg(start), end=_instant_arg(end), region=region)
    _run_wave_edit(spec, op, "Som duplicado.")


@audio_app.command("split")
def audio_split_command(
    spec: _WAVE_SPEC,
    target: _WAVE_TARGET,
    at: Annotated[
        str, typer.Option("--at", help="Onde dividir, em segundos do vídeo final (ou marker:<texto>).")
    ],
) -> None:
    """Divide uma voz gravada em duas, que se encontram no ponto, no mesmo arquivo."""
    _run_wave_edit(spec, _wave_op("audio_split", target, at=_instant_arg(at)), "Voz dividida.")


@audio_app.command("join")
def audio_join_command(
    spec: _WAVE_SPEC,
    target: _WAVE_TARGET,
    other: Annotated[
        str | None,
        typer.Option("--with", help="A voz a juntar (audio.voiceover.M ou só o número); padrão: a seguinte."),
    ] = None,
) -> None:
    """Junta duas vozes gravadas vizinhas que são pedaços seguidos do mesmo arquivo (o contrário de dividir)."""
    value: object = None
    if other is not None:
        value = int(other) if other.isdigit() else other
    _run_wave_edit(spec, _wave_op("audio_join", target, **{"with": value}), "Vozes juntadas.")


@audio_app.command("trim")
def audio_trim_command(
    spec: _WAVE_SPEC,
    target: _WAVE_TARGET,
    start: _WAVE_START = None,
    end: _WAVE_END = None,
    region: _WAVE_REGION = None,
) -> None:
    """Apara o item fora da seleção: a voz gravada fica só com o trecho; nos outros itens o resto é silenciado."""
    op = _wave_op("audio_trim", target, start=_instant_arg(start), end=_instant_arg(end), region=region)
    _run_wave_edit(spec, op, "Item aparado.")


@audio_app.command("shift")
def audio_shift_command(
    spec: _WAVE_SPEC,
    target: _WAVE_TARGET,
    delta: Annotated[
        float | None, typer.Option("--delta", help="Quanto mover, em segundos (positivo atrasa).")
    ] = None,
    to: Annotated[float | None, typer.Option("--to", help="O deslocamento final, em segundos.")] = None,
) -> None:
    """Desloca o som no tempo: em clipe, PiP e faixa externa muda o `audio_offset` (corrige câmera dessincronizada);
    na voz gravada e na narração muda o instante de início."""
    _run_wave_edit(spec, _wave_op("audio_shift", target, delta=delta, to=to), "Som deslocado.")


@audio_app.command("split-stereo")
def audio_split_stereo_command(spec: _WAVE_SPEC, target: _WAVE_TARGET) -> None:
    """Divide um som estéreo em dois itens mono: um com o canal esquerdo e outro com o direito."""
    _run_wave_edit(spec, _wave_op("audio_split_stereo", target), "Estéreo dividido.")


@audio_app.command("track")
def audio_track_command(
    spec: _WAVE_SPEC,
    track: Annotated[str, typer.Argument(help="A trilha: A1, A2..., MUS, NAR, VO ou SFX.")],
    gain_db: Annotated[float | None, typer.Option("--gain-db", help="Ganho da trilha, em dB.")] = None,
    pan: Annotated[
        float | None, typer.Option("--pan", help="Equilíbrio, de -1 (esquerda) a 1 (direita).")
    ] = None,
    mute: Annotated[bool | None, typer.Option("--mute/--no-mute", help="Muda ou desmuda a trilha.")] = None,
    solo: Annotated[
        bool | None, typer.Option("--solo/--no-solo", help="Solo: as outras trilhas de áudio ficam mudas.")
    ] = None,
) -> None:
    """Ganho, pan, mudo e solo de uma trilha de áudio (os controles do cabeçalho de trilha do Audacity)."""
    op = _wave_op("track_set", track=track, gain_db=gain_db, pan=pan, muted=mute, solo=solo)
    _run_wave_edit(spec, op, f"Trilha {track} ajustada.")


def _history_outcome(outcome) -> None:
    console.print(
        f"[green]{outcome.label}[/green]: feito. Restam {outcome.undo_steps} para desfazer e {outcome.redo_steps} para refazer.",
        highlight=False,
    )
    for warning in outcome.warnings:
        console.print(f"[yellow]aviso:[/yellow] {escape(warning)}")


@app.command("undo")
def undo_command(spec: Annotated[Path, typer.Argument(help="Caminho do spec.json")]) -> None:
    """Desfaz a última edição gravada no projeto: a spec volta exatamente a como estava antes dela."""
    from .pipeline.edit_history import HistoryError, undo_edit

    try:
        outcome = undo_edit(spec)
    except (HistoryError, *RENDER_ERRORS) as exc:
        _fail(str(exc))
    console.print("[bold]Desfeito.[/bold]", end=" ")
    _history_outcome(outcome)


@app.command("redo")
def redo_command(spec: Annotated[Path, typer.Argument(help="Caminho do spec.json")]) -> None:
    """Refaz a última edição desfeita por `dmaker undo`."""
    from .pipeline.edit_history import HistoryError, redo_edit

    try:
        outcome = redo_edit(spec)
    except (HistoryError, *RENDER_ERRORS) as exc:
        _fail(str(exc))
    console.print("[bold]Refeito.[/bold]", end=" ")
    _history_outcome(outcome)


@app.command("history")
def history_command(spec: Annotated[Path, typer.Argument(help="Caminho do spec.json")]) -> None:
    """Lista os passos do histórico de edições do projeto (o que `undo` desfaria e o que `redo` refaria)."""
    from .pipeline.edit_history import history_listing

    try:
        listing = history_listing(spec)
    except RENDER_ERRORS as exc:
        _fail(str(exc))
    for title, steps in (
        ("Para desfazer (do mais recente)", listing["undo"]),
        ("Para refazer", listing["redo"]),
    ):
        console.print(f"[bold]{title}[/bold]", highlight=False)
        for step in steps or [{"label": "nenhum", "at": ""}]:
            console.print(f"  {escape(step['label'])}  [dim]{step['at']}[/dim]", highlight=False)


markers_app = typer.Typer(
    help="Marcadores da linha do tempo (trilha MK): ver, acrescentar, importar e exportar o .txt do Audacity e gerar regulares.",
    no_args_is_help=True,
)
app.add_typer(markers_app, name="markers")

MARKERS_NEWLINES = ("auto", "lf", "crlf")


@markers_app.command("list")
def markers_list(spec: Annotated[Path, typer.Argument(help="Caminho do spec.json")]) -> None:
    """Lista os marcadores do projeto, por trilha (grupo), com o tempo, a cor e o texto."""
    project = _load(spec)
    if not project.markers:
        console.print("O projeto não tem marcadores.")
        return
    table = Table("Nº", "Grupo", "Tempo", "Cor", "Texto")
    for index, marker in enumerate(project.markers):
        when = f"{marker.begin:g} s" if not marker.is_region else f"{marker.begin:g} a {marker.finish:g} s"
        table.add_row(str(index), marker.group or "(padrão)", when, marker.color or "", escape(marker.text))
    console.print(table)


@markers_app.command("add")
def markers_add(
    spec: Annotated[Path, typer.Argument(help="Caminho do spec.json")],
    at: Annotated[
        float | None, typer.Option(help="Instante do marcador, em segundos do vídeo final.")
    ] = None,
    start: Annotated[float | None, typer.Option(help="Início de uma região (use com --end).")] = None,
    end: Annotated[float | None, typer.Option(help="Fim de uma região (use com --start).")] = None,
    text: Annotated[str, typer.Option(help="Texto do marcador.")] = "",
    color: Annotated[str | None, typer.Option(help="Cor #RRGGBB.")] = None,
    group: Annotated[str, typer.Option(help="Trilha de marcadores (vazio = a padrão).")] = "",
) -> None:
    """Acrescenta um marcador (um instante com --at, ou uma região com --start e --end)."""
    from .pipeline.edit_history import edit_and_record

    operation = {"type": "marker_add", "text": text, "group": group}
    for key, value in (("at", at), ("start", start), ("end", end), ("color", color)):
        if value is not None:
            operation[key] = value
    _load(spec)
    try:
        report, _ = edit_and_record(spec, operation)
    except RENDER_ERRORS as exc:
        _fail(str(exc))
    console.print(f"[green]Marcador acrescentado.[/green] O projeto tem {len(report.project.markers)}.")


@markers_app.command("remove")
def markers_remove(
    spec: Annotated[Path, typer.Argument(help="Caminho do spec.json")],
    ref: Annotated[str, typer.Argument(help="O número do marcador (dmaker markers list) ou marker:<texto>.")],
) -> None:
    """Remove um marcador pelo número ou pelo texto (`marker:refrão`, ou `marker:grupo/refrão`)."""
    from .pipeline.edit_history import edit_and_record

    operation: dict[str, Any] = {"type": "marker_remove"}
    operation["index" if ref.strip().isdigit() else "ref"] = int(ref) if ref.strip().isdigit() else ref
    _load(spec)
    try:
        report, _ = edit_and_record(spec, operation)
    except RENDER_ERRORS as exc:
        _fail(str(exc))
    console.print(f"[green]Marcador removido.[/green] Sobram {len(report.project.markers)}.")


@markers_app.command("import")
def markers_import_command(
    spec: Annotated[Path, typer.Argument(help="Caminho do spec.json")],
    file: Annotated[Path, typer.Argument(help="O .txt de marcadores exportado do Audacity.")],
    group: Annotated[str, typer.Option(help="Trilha de marcadores que recebe (vazio = a padrão).")] = "",
    replace: Annotated[
        bool, typer.Option(help="Troca o que a trilha já tinha em vez de acrescentar.")
    ] = False,
) -> None:
    """Importa o .txt de marcadores do Audacity (início, fim e texto separados por tabulação). Os tempos valem
    para o vídeo final; linha ilegível é pulada com aviso."""
    from .pipeline.markers import import_labels

    try:
        result = import_labels(spec, file, group, replace)
    except RENDER_ERRORS as exc:
        _fail(str(exc))
    console.print(
        f"[green]{result.added} marcador(es) importado(s).[/green] O projeto tem {len(result.project.markers)}."
    )
    for warning in result.warnings:
        console.print(f"[yellow]aviso:[/yellow] {escape(warning)}")


@markers_app.command("export")
def markers_export_command(
    spec: Annotated[Path, typer.Argument(help="Caminho do spec.json")],
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Arquivo .txt de saída (padrão: output/<projeto>-marcadores.txt)."),
    ] = None,
    group: Annotated[
        str | None, typer.Option(help="Só esta trilha (vazio = a padrão); sem a opção, todas.")
    ] = None,
    newline: Annotated[
        str, typer.Option(help="Quebra de linha: auto (a do sistema, como o Audacity), lf ou crlf.")
    ] = "auto",
) -> None:
    """Exporta os marcadores no formato do Audacity (Arquivo > Importar > Rótulos), com seis casas decimais."""
    from .pipeline.markers import export_labels

    if newline not in MARKERS_NEWLINES:
        _fail(f"Quebra de linha {newline!r} não existe; use {', '.join(MARKERS_NEWLINES)}.")
    try:
        exported = export_labels(spec, out, group, newline)  # type: ignore[arg-type]
    except RENDER_ERRORS as exc:
        _fail(str(exc))
    console.print(
        f"[green]{exported.count} marcador(es) exportado(s):[/green] {exported.path}",
        highlight=False,
        soft_wrap=True,
    )


@markers_app.command("regular")
def markers_regular_command(
    spec: Annotated[Path, typer.Argument(help="Caminho do spec.json")],
    interval: Annotated[
        float | None, typer.Option(help="Segundos entre os marcadores (ou use --parts).")
    ] = None,
    parts: Annotated[int | None, typer.Option(help="Quantas partes iguais (ou use --interval).")] = None,
    start: Annotated[float, typer.Option(help="Onde começar, em segundos.")] = 0.0,
    end: Annotated[float | None, typer.Option(help="Onde terminar (padrão: o fim do vídeo).")] = None,
    prefix: Annotated[str, typer.Option(help="Texto antes do número (ex.: 'Parte ').")] = "",
    first_number: Annotated[int, typer.Option(help="Número do primeiro marcador.")] = 1,
    digits: Annotated[int, typer.Option(help="Casas do número (2 dá 01, 02...).")] = 1,
    group: Annotated[str, typer.Option(help="Trilha de marcadores (vazio = a padrão).")] = "",
    color: Annotated[str | None, typer.Option(help="Cor #RRGGBB.")] = None,
    kind: Annotated[
        str, typer.Option(help="region (cobre o intervalo) ou instant (marca o começo).")
    ] = "region",
    replace: Annotated[bool, typer.Option(help="Troca o que a trilha já tinha.")] = False,
) -> None:
    """Gera marcadores regulares (a cada N segundos ou em N partes iguais), como o Regular Interval Labels do Audacity."""
    from .pipeline.markers import add_regular_markers

    if kind not in ("region", "instant"):
        _fail(f"Tipo {kind!r} não existe; use region ou instant.")
    try:
        result = add_regular_markers(
            spec,
            interval,
            parts,
            start,
            end,
            prefix,
            first_number,
            digits,
            group,
            color,
            kind,
            replace,  # type: ignore[arg-type]
        )
    except RENDER_ERRORS as exc:
        _fail(str(exc))
    console.print(
        f"[green]{result.added} marcador(es) criado(s).[/green] O projeto tem {len(result.project.markers)}."
    )


# ---------- áudio: projeto só de som, exportação e áudio bruto ----------


def _seconds_or_marker(value: str | None) -> float | str | None:
    """Um tempo da linha de comando: segundos (`12.5`) ou uma referência a marcador (`marker:Introdução`)."""
    if value is None:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return value


@audio_app.command("presets")
def audio_presets_command() -> None:
    """Lista os formatos de arquivo de áudio com o padrão de cada um e os alvos de loudness."""
    from .domain.loudness import LOUDNESS_TARGETS

    table = Table(title="Formatos de áudio")
    for col in ("id", "formato", "taxa e canais", "padrão", "opções", "obs"):
        table.add_column(col)
    for a in list_audio_presets():
        if a.bit_depths:
            options = "bits: " + ", ".join(str(depth) for depth in a.bit_depths)
        else:
            options = "modos: " + ", ".join(a.bitrate_modes)
        table.add_row(a.id, a.name, a.resolution, a.default_label, options, a.notes)
    console.print(table)
    targets = ", ".join(f"{name} ({lufs:g})" for name, lufs in LOUDNESS_TARGETS.items())
    console.print(f"Alvos de loudness (--loudness): {targets} LUFS, ou um número.")


@audio_app.command("export")
def audio_export_command(
    spec: Annotated[Path, typer.Argument(help="Caminho do spec.json (ou o nome do projeto).")],
    preset: Annotated[
        str | None,
        typer.Option(help="Formato do arquivo: audio/mp3, audio/wav, audio/flac... (padrão: o do projeto)."),
    ] = None,
    mode: Annotated[
        str, typer.Option(help="mix (inteiro), regions (um por região), stems (um por trilha) ou selection.")
    ] = "mix",
    out: Annotated[Path | None, typer.Option(help="Arquivo de saída (mix e seleção).")] = None,
    out_dir: Annotated[Path | None, typer.Option(help="Pasta de saída (regiões e trilhas).")] = None,
    group: Annotated[str | None, typer.Option(help="Regiões: só deste grupo de marcadores.")] = None,
    pauses: Annotated[
        bool, typer.Option("--pauses", help="Regiões: exporta também o áudio entre elas (pausa-01...).")
    ] = False,
    numbered: Annotated[bool, typer.Option("--numbered", help="Regiões: número na frente do nome.")] = False,
    start: Annotated[str | None, typer.Option(help="Seleção: início em segundos ou marker:<texto>.")] = None,
    end: Annotated[
        str | None, typer.Option(help="Seleção: fim em segundos ou marker:<texto> (padrão: o fim).")
    ] = None,
    tracks: Annotated[
        str | None, typer.Option(help="Trilhas: quais, separadas por vírgula (NAR,VO,MUS,SFX,A1).")
    ] = None,
    loudness: Annotated[
        str | None,
        typer.Option(
            help="Alvo de loudness: redes (-14), podcast (-16), broadcast (-23) ou um número em LUFS."
        ),
    ] = None,
    sample_rate: Annotated[int | None, typer.Option(help="Taxa de amostragem em Hz.")] = None,
    channels: Annotated[int | None, typer.Option(help="1 (mono) ou 2 (estéreo).")] = None,
    bit_depth: Annotated[
        int | None, typer.Option(help="16, 24 ou 32 (ponto flutuante); WAV, FLAC e AIFF.")
    ] = None,
    bitrate: Annotated[int | None, typer.Option(help="Taxa de bits em kbps (MP3, OGG, Opus, M4A).")] = None,
    bitrate_mode: Annotated[str | None, typer.Option(help="cbr, vbr ou abr.")] = None,
    quality: Annotated[
        float | None, typer.Option(help="Qualidade do modo VBR (MP3: 0 a 9; OGG: -1 a 10).")
    ] = None,
) -> None:
    """Exporta o áudio do projeto, sem imagem, como um arquivo (ou vários, por região ou por trilha)."""
    from .domain.audio_presets import AudioFormatError, EncodingChoices
    from .media.ffmpeg import FFmpegError
    from .pipeline.audio_service import export_audio_project, export_request, result_dict

    choices = EncodingChoices(sample_rate, channels, bit_depth, bitrate_mode, bitrate, quality)  # type: ignore[arg-type]
    try:
        request = export_request(
            mode,
            group=group,
            pauses=pauses,
            numbered=numbered,
            start=_seconds_or_marker(start),
            end=_seconds_or_marker(end),
            tracks=[item.strip() for item in tracks.split(",") if item.strip()] if tracks else None,
        )
        result = export_audio_project(
            spec,
            request,
            preset=preset,
            out=out,
            out_dir=out_dir,
            loudness=loudness,
            choices=None if choices.empty else choices,
        )
    except (FFmpegError, AudioFormatError, ValidationError, *RENDER_ERRORS) as exc:
        _fail(str(exc))
    for item in result_dict(result)["files"]:
        console.print(
            f"[green]Pronto:[/green] {item['path']}  ({item['duration_s']:.2f}s, {item['size_mb']:.2f} MB)",
            highlight=False,
            soft_wrap=True,
        )
    for warning in result.warnings:
        console.print(f"[yellow]aviso:[/yellow] {escape(warning)}")


@audio_app.command("import-raw")
def audio_import_raw_command(
    spec: Annotated[
        Path, typer.Argument(help="Caminho do spec.json ou nome do projeto (criado se não existir).")
    ],
    raw: Annotated[Path, typer.Argument(help="Arquivo de áudio bruto (PCM sem cabeçalho).")],
    encoding: Annotated[
        str, typer.Option(help="s8, u8, s16, u16, s24, s32, f32, f64, ulaw ou alaw.")
    ] = "s16",
    byte_order: Annotated[str, typer.Option(help="little ou big.")] = "little",
    channels: Annotated[int, typer.Option(help="Canais (1 mono, 2 estéreo).")] = 1,
    sample_rate: Annotated[int, typer.Option(help="Taxa de amostragem em Hz.")] = 44100,
    offset_bytes: Annotated[int, typer.Option(help="Bytes a pular no começo do arquivo.")] = 0,
    percent: Annotated[float, typer.Option(help="Quanto do arquivo importar, em por cento.")] = 100.0,
    start: Annotated[
        float, typer.Option(help="Instante do projeto em que o áudio entra, em segundos.")
    ] = 0.0,
    volume: Annotated[float, typer.Option(help="Volume do áudio importado.")] = 1.0,
    name: Annotated[str | None, typer.Option(help="Nome do WAV gerado (sem a extensão).")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Troca um WAV que já exista.")] = False,
) -> None:
    """Importa áudio bruto como voz gravada do projeto: converte para um WAV na pasta dele (o arquivo original não muda)."""
    from .media.ffmpeg import FFmpegError
    from .pipeline.audio_import import RawImportError, import_raw_audio

    try:
        imported = import_raw_audio(
            spec,
            raw,
            encoding=encoding,
            byte_order=byte_order,
            channels=channels,
            sample_rate=sample_rate,
            offset_bytes=offset_bytes,
            percent=percent,
            start=start,
            volume=volume,
            name=name,
            overwrite=overwrite,
        )
    except (FFmpegError, RawImportError, ValidationError, *RENDER_ERRORS) as exc:
        _fail(str(exc))
    console.print(
        f"[green]Importado:[/green] {imported.wav}  ({imported.duration:.2f}s) como voz gravada em {start:g}s.",
        highlight=False,
        soft_wrap=True,
    )
    if imported.created_project:
        console.print("Projeto novo, só de áudio (saída audio/wav).")


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
OVERWRITE_HELP = (
    "Prepara de novo mesmo que o projeto .dub.json já exista, apagando as traduções revisadas e as falas "
    "travadas. Sem isto, o comando recusa."
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
    overwrite: bool = False,
) -> tuple:
    from .domain.dub import DubProjectExists
    from .pipeline.dubbing import default_project_path

    if speaker is not None and speaker not in SPEAKER_MODES:
        _fail(f"Modo de falante {speaker!r} inválido; use {' ou '.join(SPEAKER_MODES)}.")
    _check_fit(fit)
    path = project_path or default_project_path(file, target)
    try:
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
            overwrite=overwrite,
        )
    except DubProjectExists as exc:
        _fail(f"{exc} Use --overwrite para preparar de novo mesmo assim.")
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
    overwrite: Annotated[bool, typer.Option("--overwrite", help=OVERWRITE_HELP)] = False,
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
            overwrite,
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
    overwrite: Annotated[bool, typer.Option("--overwrite", help=OVERWRITE_HELP)] = False,
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
            overwrite,
        )
        _print_segments(dub)
        result = service.render(dub, out, steps=DRAFT_STEPS if draft and steps is None else steps)
    except VOICE_ERRORS as exc:
        _voice_fail(exc)
    console.print(f"  projeto: {path}", markup=False, highlight=False, soft_wrap=True)
    _print_dub_result(result)


if __name__ == "__main__":  # pragma: no cover
    app()
