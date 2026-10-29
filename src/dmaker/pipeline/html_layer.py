"""Composições em HTML: a área de cada uma no quadro, o vídeo com alfa que sai do renderizador e o cache dele.

O vídeo de cada composição fica em `cache/mez`, por conteúdo (o HTML, todos os arquivos da pasta, o tamanho, o
fps, a duração, os dados, o borrão e a marca), como o mezanino: render igual não renderiza a página de novo. O
arquivo só ganha o nome final ao terminar inteiro, para um render interrompido não deixar no cache um vídeo
pela metade."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.brand import Theme
from ..domain.regions import html_box
from ..domain.spec import HtmlOverlay, Project
from ..domain.timeline import frame_range
from ..filtergraph.html_layer import ResolvedHtmlLayer, html_layer_command
from ..media import fonts
from ..media.ffmpeg import FFmpegCommand, FFmpegError
from ..media.html_render import HtmlComposition, HtmlRenderer, PlaywrightHtmlRenderer
from ..media.html_site import FontFace, composition_files, entry_file
from ..visuals.motion_blur import blend_stream, blur_sample_times
from .context import RenderContext
from .segments import cache_key

# Muda quando a receita da camada muda (o jeito de capturar, o relógio, o codec, o que a página recebe da marca):
# invalida o cache só das composições. Não é o MEZZ_VERSION nem o MATTE_VERSION, cujas receitas continuam as mesmas.
# h2: a página passou a receber o raio dos cantos da marca, a fonte dela de verdade (não só a Poppins) e os arquivos
# do projeto declarados pela composição.
HTML_LAYER_VERSION = "h2"

# Peso CSS de cada papel de peso da marca (`fonts.title`, `body`...): as `@font-face` da família cobrem os seis.
_CSS_WEIGHTS = (
    ("light", 300, "normal"),
    ("regular", 400, "normal"),
    ("medium", 500, "normal"),
    ("semibold", 600, "normal"),
    ("bold", 700, "normal"),
    ("extrabold", 800, "normal"),
    ("italic", 400, "italic"),
)


class HtmlRenderFailed(RuntimeError):
    """O renderizador da composição parou no meio; a mensagem é a do erro original."""


@dataclass(frozen=True)
class ResolvedHtmlOverlay:
    """Uma composição já com a região resolvida e o tempo cortado no vídeo, sem o arquivo gerado ainda.
    `box` é a área em pixels do quadro final: esquerda, topo, largura e altura."""

    overlay: HtmlOverlay
    source: Path
    start: float
    end: float
    box: tuple[int, int, int, int]
    index: int
    files: dict[str, Path] = field(
        default_factory=dict
    )  # arquivos do projeto que a página lê, por nome servido


def brand_font_faces(theme: Theme) -> tuple[FontFace, ...]:
    """As fontes da marca que a página precisa por `@font-face` além da Poppins de `assets/fonts`: os arquivos da
    família do `brand.json` quando ela não é a Poppins (Arial, Bahnschrift) e as fontes por papel (`fonts.files`:
    script, date, serif...), que viram `--dm-font-<papel>`. Fonte que não está no disco fica de fora (o texto cai
    na família da marca)."""
    faces: list[FontFace] = []
    family = theme.font_family
    if family != "Poppins" and family in fonts.FAMILIES:
        for role, weight, style in _CSS_WEIGHTS:
            ref = fonts.resolve(family, role)
            if ref.family == family:
                faces.append(FontFace(family, weight, style, ref.file))
    for role in sorted(theme.fonts.get("files", {})):
        try:
            path = fonts.resolve_file(theme.fonts["files"], role)
        except FileNotFoundError:
            continue
        faces.append(FontFace(f"dm-{role}", 400, "normal", path))
    return tuple(faces)


def brand_page_fields(theme: Theme) -> dict[str, Any]:
    """O que a marca entrega à página: cores, família, raio dos cantos e arquivos de fonte (ver `HtmlComposition`)."""
    return {
        "colors": dict(theme.colors),
        "font_family": theme.font_family,
        "radius": theme.rounded_box_radius,
        "fonts": brand_font_faces(theme),
    }


def has_html_overlays(project: Project) -> bool:
    return any(isinstance(overlay, HtmlOverlay) for overlay in project.overlays)


def resolve_html_source(project: Project, src: str) -> Path:
    """O arquivo ou a pasta da composição, conferidos (levanta o erro que diz o que falta)."""
    source = project.resolve(src)
    entry_file(source)
    return source


def resolve_html_overlay(
    ctx: RenderContext, overlay: HtmlOverlay, source: Path, total: float, index: int
) -> ResolvedHtmlOverlay | None:
    """A composição no tempo e no lugar certos, ou None se ela cai depois do fim do vídeo."""
    end = min(overlay.end if overlay.end is not None else total, total)
    if end <= overlay.start:
        return None
    box = html_box(overlay, ctx.width, ctx.height)
    files = {name: ctx.project.resolve(path) for name, path in overlay.files.items()}
    return ResolvedHtmlOverlay(overlay, source, overlay.start, end, box, index, files)


def files_digest(files: Mapping[str, Path], faces: tuple[FontFace, ...]) -> str:
    """Impressão digital dos arquivos de fora da pasta que a página lê (imagens do projeto, fontes da marca): trocar
    o conteúdo de um deles renderiza de novo."""
    digest = hashlib.sha1()
    entries = [(name, path) for name, path in sorted(files.items())]
    entries += [(f"{face.family}/{face.weight}/{face.style}", face.path) for face in faces]
    for name, path in entries:
        digest.update(name.encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"?")  # arquivo sumido: a página recebe 404 e avisa; a chave só precisa mudar
    return digest.hexdigest()


def content_digest(source: Path) -> str:
    """Impressão digital do que a página pode ler (o `.html` ou a pasta inteira): trocar um arquivo qualquer
    dela, mesmo uma imagem, renderiza de novo; tocar sem mudar o conteúdo, não."""
    digest = hashlib.sha1()
    root = source if source.is_dir() else source.parent
    for path in composition_files(source):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    return digest.hexdigest()


@dataclass
class _Frames:
    """Os quadros a entregar ao ffmpeg. Se o renderizador parar no meio, o fluxo termina (o ffmpeg fecha o arquivo
    com o que veio, em vez de ficar esperando o resto) e o erro fica guardado para o `build` levantar."""

    source: Iterator[bytes]
    error: Exception | None = None

    def __iter__(self) -> Iterator[bytes]:
        try:
            yield from self.source
        except Exception as exc:  # noqa: BLE001 - guardado e reerguido por quem sabe o nome da composição
            self.error = exc


@dataclass
class PreparedHtmlLayer:
    """Uma composição pronta para a montagem: o vídeo com alfa e os comandos que o geram (nenhum, se já estava em
    cache). O vídeo só ganha o nome final ao terminar inteiro."""

    layer: ResolvedHtmlLayer
    partial: Path
    sidecar: Path
    commands: tuple[FFmpegCommand, ...] = ()
    stream: _Frames | None = None
    warnings: list[str] | None = None


def _needs_render(out: Path, ctx: RenderContext) -> bool:
    return ctx.options.dry_run or ctx.options.force or not out.exists()


class HtmlLayerBuilder:
    """Prepara e gera (quando não está em cache) o vídeo com alfa de cada composição em HTML.

    O renderizador entra por injeção (`HtmlRenderer`): os testes do pipeline usam um falso, e o de verdade só abre
    o Chromium na primeira composição que precisa ser renderizada."""

    def __init__(self, renderer: HtmlRenderer | None = None):
        self.renderer = renderer or PlaywrightHtmlRenderer()

    def unavailable_reason(self) -> str | None:
        return self.renderer.unavailable_reason()

    def prepare(self, ctx: RenderContext, items: list[ResolvedHtmlOverlay]) -> list[PreparedHtmlLayer]:
        prepared: list[PreparedHtmlLayer] = []
        for item in items:
            layer = self._prepare_one(ctx, item)
            if layer is not None:
                prepared.append(layer)
        return prepared

    def _prepare_one(self, ctx: RenderContext, item: ResolvedHtmlOverlay) -> PreparedHtmlLayer | None:
        overlay, fps = item.overlay, ctx.fps
        first, stop = frame_range(item.start, item.end, fps)
        count = stop - first
        if count <= 0:
            return None
        left, top, box_width, box_height = item.box
        # a página é desenhada na base 1080, como o resto do DMaker: na prévia (metade do tamanho) o mesmo
        # desenho sai menor, em vez de a página ver uma janela menor e se reorganizar
        size = overlay.size or (max(round(box_width / ctx.scale), 1), max(round(box_height / ctx.scale), 1))
        composition = HtmlComposition(
            source=item.source,
            size=size,
            scale=ctx.scale,
            fps=fps,
            duration=item.end - item.start,
            data=overlay.data,
            files=item.files,
            **brand_page_fields(ctx.theme),
        )
        output_size = composition.output_size
        # o instante da página no primeiro quadro: 0 quando o início cai na grade de quadros, uma fração dele
        # quando não cai (a composição acompanha o início pedido, não o quadro mais próximo)
        offset = round(first / fps - item.start, 6)
        times = [offset + index / fps for index in range(count)]
        blur = overlay.motion_blur
        samples = blur_sample_times(times, fps, blur.subframes, blur.shutter) if blur else times
        key = cache_key(
            HTML_LAYER_VERSION,
            content_digest(item.source),
            size,
            round(ctx.scale, 6),
            fps,
            count,
            offset,
            round(composition.duration, 6),
            overlay.data,
            blur.model_dump(mode="json") if blur else None,
            composition.colors,  # a marca chega à página por variáveis CSS
            composition.font_family,
            composition.radius,
            files_digest(composition.files, composition.fonts),
        )
        out = ctx.cache_dir / f"{key}_html.mov"
        partial = ctx.cache_dir / f"{key}_html.part.mov"
        sidecar = ctx.cache_dir / f"{key}_html.json"
        resolved = ResolvedHtmlLayer(
            out,
            first / fps,
            stop / fps,
            str(left),
            str(top),
            None if output_size == (box_width, box_height) else (box_width, box_height),
            behind=overlay.layer == "behind-person",
        )
        label = f"overlays[{item.index}] (html {overlay.src})"
        if not _needs_render(out, ctx):
            for warning in self._stored_warnings(sidecar):  # o aviso de rede não some no segundo render
                ctx.warn(f"{label}: {warning}")
            return PreparedHtmlLayer(resolved, partial, sidecar)
        warnings: list[str] = []

        def on_warning(message: str, label: str = label, bucket: list[str] = warnings) -> None:
            bucket.append(message)
            ctx.warn(f"{label}: {message}")

        # no dry-run o comando é só registrado; a página nunca é aberta
        raw = iter(()) if ctx.options.dry_run else self.renderer.frames(composition, samples, on_warning)
        stream = _Frames(blend_stream(raw, blur.subframes, output_size) if blur else raw)
        command = html_layer_command(
            stream, output_size, fps, count, partial, label=f"composição html ({overlay.src})"
        )
        return PreparedHtmlLayer(resolved, partial, sidecar, (command,), stream, warnings)

    @staticmethod
    def _stored_warnings(sidecar: Path) -> list[str]:
        try:
            return list(json.loads(sidecar.read_text(encoding="utf-8")).get("warnings", []))
        except (OSError, ValueError):
            return []

    def build(self, ctx: RenderContext, layers: list[PreparedHtmlLayer]) -> None:
        pending = [item for item in layers if item.commands]
        if not pending:
            return
        # um renderizador que sabe ser aberto uma vez só (`with`) mantém o navegador de pé entre as composições
        with self.renderer if hasattr(self.renderer, "__enter__") else nullcontext():
            for item in pending:
                try:
                    self._run(ctx, item)
                    if item.partial.exists():
                        item.sidecar.write_text(
                            json.dumps({"warnings": item.warnings or []}, ensure_ascii=False),
                            encoding="utf-8",
                        )
                        item.partial.replace(item.layer.path)
                finally:
                    item.partial.unlink(missing_ok=True)

    @staticmethod
    def _run(ctx: RenderContext, item: PreparedHtmlLayer) -> None:
        stream = item.stream
        try:
            for command in item.commands:
                ctx.runner.run(command)
        except FFmpegError:
            if stream is not None and stream.error is not None:
                raise HtmlRenderFailed(str(stream.error)) from stream.error
            raise
        if stream is not None and stream.error is not None:
            raise HtmlRenderFailed(str(stream.error)) from stream.error


def html_warnings(project: Project, problem: Callable[[], str | None]) -> list[str]:
    """Avisos, antes de renderizar, sobre as composições em HTML do projeto: a que não existe e o navegador que
    não está instalado. `problem` é quem sabe do navegador (em produção, `browser_problem`); sem composição
    nenhuma ele nem é chamado."""
    if not has_html_overlays(project):
        return []
    warnings = []
    for index, overlay in enumerate(project.overlays):
        if isinstance(overlay, HtmlOverlay) and overlay.src is not None:  # os modelos prontos: ver `lint`
            try:
                resolve_html_source(project, overlay.src)
            except (FileNotFoundError, ValueError) as exc:
                warnings.append(f"overlays[{index}].src: {exc}")
    reason = problem()
    if reason:
        warnings.append(f"o projeto tem composição HTML e o render vai falhar: {reason}")
    return warnings
