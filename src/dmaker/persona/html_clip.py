"""O que os motores de persona desenhados no Chromium dividem: quadros da página para o ffmpeg e a chave da página.

Há um jeito só de capturar quadros de uma página (o da composição HTML); os motores 2D e 3D só diferem na página
e nos dados que mandam para ela.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from pathlib import Path

from ..filtergraph.html_layer import html_layer_command
from ..media.ffmpeg import FFmpegError, FFmpegRunner
from ..media.html_render import HtmlComposition, HtmlRenderer
from ..media.html_site import composition_files
from .engine import PersonaEngineError, PersonaRender


class FrameStream:
    """Os quadros a entregar ao ffmpeg. Se a página parar no meio, o fluxo termina e o erro fica guardado para
    quem sabe o que se renderizava (o ffmpeg fecha o arquivo com o que veio, em vez de esperar o resto)."""

    def __init__(self, source: Iterator[bytes]) -> None:
        self.source = source
        self.error: Exception | None = None

    def __iter__(self) -> Iterator[bytes]:
        try:
            yield from self.source
        except Exception as exc:  # noqa: BLE001 - reerguido por `render_html_clip`, que sabe o nome da persona
            self.error = exc


def page_digest(root: Path) -> str:
    """O conteúdo da página (e de tudo o que ela importa) numa só impressão: mexer no desenho invalida os clipes
    em cache sem precisar mudar a versão do motor."""
    digest = hashlib.sha1()
    for path in composition_files(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def render_html_clip(
    renderer: HtmlRenderer,
    composition: HtmlComposition,
    request: PersonaRender,
    out: Path,
    runner: FFmpegRunner,
    on_warning: Callable[[str], None],
) -> None:
    """Desenha os quadros da página nos instantes do clipe e os entrega ao ffmpeg, que grava `out` (com alfa)."""
    count = request.frame_count
    times = [index / request.fps for index in range(count)]
    stream = FrameStream(renderer.frames(composition, times, on_warning))
    partial = out.with_name(f"{out.stem}.part{out.suffix}")
    drawn = composition.output_size  # a página pode ter sido desenhada menor que o clipe (mais rápido)
    command = html_layer_command(
        stream,
        drawn,
        request.fps,
        count,
        partial,
        label=f"persona {request.persona.id}",
        scale_to=request.size if drawn != request.size else None,
    )
    try:
        try:
            runner.run(command)
        except FFmpegError:
            if stream.error is not None:
                raise PersonaEngineError(
                    f"A página da persona parou no meio do desenho: {stream.error}"
                ) from stream.error
            raise
        if stream.error is not None:
            raise PersonaEngineError(
                f"A página da persona parou no meio do desenho: {stream.error}"
            ) from stream.error
        partial.replace(out)
    finally:
        partial.unlink(missing_ok=True)
