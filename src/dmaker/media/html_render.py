"""Renderizador de composições em HTML: abre a página no Chromium, controla o relógio e fotografa cada quadro
com fundo transparente.

O resto do DMaker depende do protocolo `HtmlRenderer`, nunca do Playwright (os testes do pipeline entram com um
falso). A `PlaywrightHtmlRenderer` reaproveita a partida do Chromium de `browser.py` e segue três regras:
- o relógio é do DMaker: antes de qualquer script da página entra o `html_runtime.js`, que troca o relógio do
  navegador por um virtual e posiciona animações CSS, Web Animations, GSAP e Lottie no instante exato do quadro;
- a página não tem rede: tudo o que não é da origem falsa (`html_site.py`) é abortado e vira aviso;
- a captura sai do Chromium em PNG com alfa direto (não pré-multiplicado), pelo protocolo de depuração, que é mais
  rápido que o `page.screenshot`.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from .. import config
from .browser import PlaywrightBrowser, browser_problem
from .html_site import (
    ENTRY_PATH,
    FREEZE_CSS,
    ORIGIN,
    CompositionSite,
    FontFace,
    brand_css,
    brand_font_faces_css,
    brand_font_probes,
    font_face_probes,
    font_faces_css,
    font_file_names,
    is_composition_origin,
    is_local_scheme,
)

# Instante zero do relógio da composição: `new Date()` dá sempre esta data, que é um dia comum e fixo, em vez de
# a data de hoje (a mesma composição tem que sair igual amanhã). 1º de janeiro de 2026, 15h UTC, meio-dia em Brasília.
EPOCH_MS = 1_767_279_600_000
RANDOM_SEED = 1  # semente de Math.random e do ruído: composição com sorteio sai igual em todo render
MAX_WARNINGS = 25  # um erro em laço não pode encher o relatório

# Cada opção do Chromium tem uma razão:
# - o WebGL por software (SwiftShader, pela camada ANGLE): a GPU muda de máquina para máquina e a mesma cena sairia
#   diferente; por software sai igual em qualquer uma (`--enable-unsafe-swiftshader` é a licença que o Chromium
#   atual pede para usá-lo, e `--ignore-gpu-blocklist` impede que ele recuse a GPU virtual);
# - `--force-color-profile=srgb`: sem isso a cor depende do perfil do monitor da máquina;
# - `--font-render-hinting=none` e `--disable-lcd-text`: o desenho do texto não varia com a configuração do
#   Windows (ClearType) e as bordas do texto saem sem franja colorida, o que importa com fundo transparente;
# - `--host-resolver-rules`: nenhum nome resolve, nem o que escapasse da rota (WebSocket, beacon): a rede fica
#   fechada por dentro do Chromium também, não só pela interceptação.
CHROMIUM_ARGS = (
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--ignore-gpu-blocklist",
    "--force-color-profile=srgb",
    "--font-render-hinting=none",
    "--disable-lcd-text",
    "--host-resolver-rules=MAP * ~NOTFOUND",
)


class HtmlRenderError(RuntimeError):
    """A composição não pôde ser renderizada (página travada, navegador caiu); a mensagem diz onde."""


@dataclass(frozen=True)
class HtmlComposition:
    """O que o renderizador precisa saber de uma composição.

    `size` é o tamanho da página em px CSS (a base 1080 do resto do DMaker) e `scale` quantos pixels de saída
    cabem em um px CSS: a prévia renderiza a mesma página com `scale` 0,5, e o desenho sai igual em menor.

    A marca chega à página por `colors` (variáveis `--dm-<cor>`), `font_family` (`--dm-font`), `radius` (`--dm-radius`,
    o raio dos cantos em px na base 1080) e `fonts` (os arquivos de fonte da marca que não são a Poppins de
    `assets/fonts`, servidos por `@font-face`). `files` são os arquivos do projeto que a composição declarou, por nome."""

    source: Path
    size: tuple[int, int]
    scale: float = 1.0
    fps: float = 30.0
    duration: float = 5.0
    data: Mapping[str, Any] = field(default_factory=dict)
    colors: Mapping[str, str] = field(default_factory=dict)
    font_family: str = "Poppins"
    radius: float | None = None
    fonts: tuple[FontFace, ...] = ()
    files: Mapping[str, Path] = field(default_factory=dict)

    @property
    def output_size(self) -> tuple[int, int]:
        """Largura e altura, em pixels, de cada quadro que sai."""
        return max(round(self.size[0] * self.scale), 1), max(round(self.size[1] * self.scale), 1)


class HtmlRenderer(Protocol):
    def unavailable_reason(self) -> str | None:
        """Por que não consegue renderizar (como instalar o que falta), ou None. Não renderiza nada."""
        ...

    def frames(
        self, composition: HtmlComposition, times: Sequence[float], on_warning: Callable[[str], None]
    ) -> Iterator[bytes]:
        """Um quadro RGBA cru (largura x altura x 4 bytes, alfa direto) para cada instante de `times` (segundos
        da composição, em ordem crescente). `on_warning` recebe o que a página tentou e foi negado ou deu erro."""
        ...

    def still(self, composition: HtmlComposition, at: float, on_warning: Callable[[str], None]) -> bytes:
        """O quadro do instante `at`, em PNG com alfa, indo direto a ele (sem desenhar os de antes)."""
        ...


def runtime_script(composition: HtmlComposition, fonts_dir: Path | None = None) -> str:
    """O script que entra antes de qualquer outro da página: a configuração e o `html_runtime.js`."""
    fonts = fonts_dir or config.FONTS_DIR
    # a família da marca chega por `composition.fonts` quando não é a Poppins; sem isso, a família pedida é servida
    # com a Poppins de `assets/fonts` (o caso comum). As fontes por papel (`dm-<papel>`) vêm sempre de `fonts`.
    serves_family = any(face.family == composition.font_family for face in composition.fonts)
    faces_css = brand_font_faces_css(composition.fonts)
    probes = brand_font_probes(composition.fonts)
    if not serves_family:
        faces_css = font_faces_css(fonts, composition.font_family) + faces_css
        probes = font_face_probes(fonts, composition.font_family) + probes
    role_fonts = {
        face.family.removeprefix("dm-"): face.family
        for face in composition.fonts
        if face.family.startswith("dm-")
    }
    css = (
        faces_css
        + brand_css(dict(composition.colors), composition.font_family, composition.radius, role_fonts)
        + FREEZE_CSS
    )
    settings = {
        "width": composition.size[0],
        "height": composition.size[1],
        "fps": composition.fps,
        "duration": composition.duration,
        "data": dict(composition.data),
        "brand": dict(composition.colors),
        "fontFamily": composition.font_family,
        "fontFaces": probes,
        "css": css,
        "epoch": EPOCH_MS,
        "seed": RANDOM_SEED,
    }
    runtime = (config.PACKAGE_DIR / "media" / "html_runtime.js").read_text(encoding="utf-8")
    return f"window.__dmakerConfig = {json.dumps(settings, ensure_ascii=False)};\n{runtime}"


class _Warnings:
    """Os avisos de uma composição, sem repetir o mesmo nem passar de `MAX_WARNINGS`."""

    def __init__(self, sink: Callable[[str], None]):
        self._sink = sink
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def add(self, message: str) -> None:
        with self._lock:
            if message in self._seen:
                return
            if len(self._seen) >= MAX_WARNINGS:
                if len(self._seen) == MAX_WARNINGS:
                    self._seen.add("")  # marca que o aviso de corte já saiu
                    message = f"outros avisos da composição foram omitidos (são mais de {MAX_WARNINGS})"
                else:
                    return
            else:
                self._seen.add(message)
        self._sink(message)


class _CompositionPage:
    """Uma página aberta num contexto isolado do Chromium, já carregada e parada no instante 0."""

    def __init__(self, browser: PlaywrightBrowser, composition: HtmlComposition, warnings: _Warnings):
        self._browser = browser
        self._composition = composition
        self._warnings = warnings
        self._site = CompositionSite(
            composition.source,
            files={**composition.files, **font_file_names(composition.fonts)},
        )
        self._context: Any = None
        self._page: Any = None
        self._cdp: Any = None

    def __enter__(self) -> _CompositionPage:
        width, height = self._composition.size
        context = self._browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=self._composition.scale,
            service_workers="block",  # um service worker serviria arquivos por fora da rota
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",  # datas e horas formatadas iguais em qualquer máquina
            color_scheme="light",
        )
        self._context = context
        try:
            context.add_init_script(runtime_script(self._composition))
            context.route("**/*", self._handle_request)
            if hasattr(context, "route_web_socket"):  # Playwright 1.48+
                context.route_web_socket("**", self._handle_web_socket)
            page = context.new_page()
            self._page = page
            page.on(
                "pageerror", lambda error: self._warnings.add(f"erro de JavaScript na composição: {error}")
            )
            page.on("console", self._on_console)
            self._cdp = context.new_cdp_session(page)
            # fundo transparente de verdade: sem isto o Chromium pinta de branco o que a página não cobre
            self._cdp.send(
                "Emulation.setDefaultBackgroundColorOverride", {"color": {"r": 0, "g": 0, "b": 0, "a": 0}}
            )
            page.goto(ORIGIN + ENTRY_PATH, wait_until="load")
            self._evaluate("() => window.__dmakerHost.ready()", "preparar a composição")
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except Exception:  # noqa: BLE001 - fechar um navegador que já caiu não pode esconder o erro de origem
                pass
        self._context = self._page = self._cdp = None

    def _handle_request(self, route: Any) -> None:
        url = route.request.url
        if is_local_scheme(url):
            route.continue_()
        elif is_composition_origin(url):
            path = urlsplit(url).path
            served = self._site.lookup(path)
            if served is not None:
                route.fulfill(status=200, body=served.body, headers={"content-type": served.content_type})
                return
            if path != "/favicon.ico":  # o Chromium pede o ícone sozinho; não é erro da composição
                self._warnings.add(f"a composição pediu um arquivo que não existe nela: {path}")
            route.fulfill(status=404, body=b"")
        else:
            self._warnings.add(
                f"a composição tentou acessar {url} na internet; o pedido foi bloqueado "
                "(a página só pode usar os arquivos que estão junto dela)"
            )
            route.abort("blockedbyclient")

    def _handle_web_socket(self, socket: Any) -> None:
        """O WebSocket não passa pela rota de requisições. Sem `connect_to_server`, o Playwright não abre conexão
        nenhuma (a página só fala com um servidor de mentira), então nada sai; fechar o soquete aqui trava o
        despachante síncrono, por isso só se registra o aviso."""
        self._warnings.add(
            f"a composição tentou abrir um WebSocket em {socket.url}; o pedido foi bloqueado "
            "(a página só pode usar os arquivos que estão junto dela)"
        )

    def _on_console(self, message: Any) -> None:
        if message.type != "error":
            return
        text = message.text
        if text.startswith("Failed to load resource"):  # já tem aviso próprio, com a URL (rede negada, 404)
            return
        self._warnings.add(f"console.error da composição: {text}")

    def _evaluate(self, expression: str, what: str, argument: Any = None) -> Any:
        try:
            return self._page.evaluate(expression, argument)
        except Exception as exc:  # noqa: BLE001 - qualquer falha da página vira o erro com o que se fazia
            raise HtmlRenderError(f"A composição HTML falhou ao {what}: {_first_line(exc)}") from exc

    def seek(self, seconds: float) -> None:
        self._evaluate("(t) => window.__dmakerHost.seek(t)", f"chegar ao instante {seconds:.3f}s", seconds)

    def png(self, optimize_for_speed: bool) -> bytes:
        width, height = self._composition.size
        # o protocolo de depuração ignora a escala de pixels do contexto e devolve o tamanho em px CSS; `clip.scale`
        # a aplica de verdade (a página é desenhada na escala, não reduzida depois)
        clip = {"x": 0, "y": 0, "width": width, "height": height, "scale": self._composition.scale}
        shot = self._cdp.send(
            "Page.captureScreenshot",
            {"format": "png", "optimizeForSpeed": optimize_for_speed, "fromSurface": True, "clip": clip},
        )
        return base64.b64decode(shot["data"])

    def rgba(self) -> bytes:
        """O quadro em RGBA cru, no tamanho de saída (a captura pode diferir um pixel em escalas quebradas)."""
        from PIL import Image

        # `optimizeForSpeed`: PNG quase sem compressão, que o Chromium escreve e o Pillow lê em uma fração do tempo
        with Image.open(io.BytesIO(self.png(optimize_for_speed=True))) as image:
            frame = image.convert("RGBA")
            wanted = self._composition.output_size
            if frame.size != wanted:
                frame = frame.resize(wanted, Image.Resampling.LANCZOS)
            return frame.tobytes()


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    return text[0] if text else type(exc).__name__


def _foreign_event_loop_running(browser_open: bool) -> bool:
    """Esta thread tem um laço asyncio que não é o do Playwright? O Playwright síncrono recusa uma thread assim (o
    servidor MCP chama as ferramentas de dentro de um laço). Com o navegador já aberto nesta thread, o laço que se
    vê é o do próprio Playwright, que roda numa corrotina da mesma thread: não é estranho."""
    if browser_open:
        return False
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _run_outside_event_loop(work: Callable[[], bytes], browser_open: bool) -> bytes:
    """Roda `work` na thread de quem chamou, ou numa nova se a dela tem um laço estranho (uma thread nova nunca
    tem um)."""
    if not _foreign_event_loop_running(browser_open):
        return work()
    result: dict[str, Any] = {}

    def target() -> None:
        try:
            result["value"] = work()
        except BaseException as exc:  # noqa: BLE001 - reerguido na thread de quem chamou
            result["error"] = exc

    thread = threading.Thread(target=target, name="dmaker-html-frame")
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result["value"]


class PlaywrightHtmlRenderer:
    """`HtmlRenderer` sobre o Chromium do Playwright (extra opcional `html`)."""

    def __init__(self, browser: PlaywrightBrowser | None = None):
        self._browser = browser or PlaywrightBrowser(CHROMIUM_ARGS)

    def __enter__(self) -> PlaywrightHtmlRenderer:
        """Mantém o Chromium aberto entre as composições de um mesmo render (abrir leva cerca de um segundo)."""
        self._browser.__enter__()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._browser.__exit__(*exc_info)

    def unavailable_reason(self) -> str | None:
        return browser_problem()

    def frames(
        self, composition: HtmlComposition, times: Sequence[float], on_warning: Callable[[str], None]
    ) -> Iterator[bytes]:
        if any(later < earlier for earlier, later in zip(times, times[1:], strict=False)):
            raise ValueError("os instantes de uma composição HTML precisam estar em ordem crescente")
        with self._browser, _CompositionPage(self._browser, composition, _Warnings(on_warning)) as page:
            for seconds in times:
                page.seek(seconds)
                yield page.rgba()

    def still(self, composition: HtmlComposition, at: float, on_warning: Callable[[str], None]) -> bytes:
        def work() -> bytes:
            with self._browser, _CompositionPage(self._browser, composition, _Warnings(on_warning)) as page:
                page.seek(at)
                return page.png(optimize_for_speed=False)

        return _run_outside_event_loop(work, self._browser.is_open)
