"""Acesso ao navegador (Chromium do Playwright) atrás de um protocolo pequeno, para imprimir e fotografar HTML.

Quem precisa de um navegador (o PDF do manual, as capturas de tela, e a composição em HTML, que usa a partida
daqui) depende do protocolo `Browser`, nunca do Playwright: os testes entram com um falso e o resto do pacote não
importa nada pesado. O Playwright é um extra opcional (`pip install -e ".[html]"`) e o Chromium baixa à parte,
para dentro do clone (`dmaker setup --html`, que o guarda em `bin/playwright`).
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from .. import config

INSTALL_HINT = (
    'Instale o extra e o navegador: pip install -e ".[html]" e depois dmaker setup --html '
    "(o Chromium fica em bin/playwright, dentro do DMaker)."
)
BROWSERS_PATH_VAR = "PLAYWRIGHT_BROWSERS_PATH"
PDF_FOOTER = (
    '<div style="width:100%;font-size:8px;color:#5b6f77;text-align:center;'
    'font-family:Segoe UI,Arial,sans-serif;">Manual do DMaker, página '
    '<span class="pageNumber"></span> de <span class="totalPages"></span></div>'
)


class BrowserUnavailable(RuntimeError):
    """O Playwright ou o Chromium não estão instalados; a mensagem diz como instalar."""


def playwright_env() -> dict[str, str]:
    """O ambiente que aponta o Playwright para o Chromium do DMaker (`bin/playwright`), lido de `config` na
    hora: sem isso ele procuraria (e instalaria) em `%LOCALAPPDATA%/ms-playwright`, pasta que outras ferramentas
    da máquina também usam e que o DMaker não pode tocar."""
    return {**os.environ, BROWSERS_PATH_VAR: str(config.PLAYWRIGHT_DIR)}


@contextmanager
def _browsers_path() -> Iterator[None]:
    """O `PLAYWRIGHT_BROWSERS_PATH` só durante a partida do driver, que herda o ambiente ao nascer: depois o
    processo (interface, servidor MCP) volta ao ambiente que tinha."""
    previous = os.environ.get(BROWSERS_PATH_VAR)
    os.environ[BROWSERS_PATH_VAR] = str(config.PLAYWRIGHT_DIR)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(BROWSERS_PATH_VAR, None)
        else:
            os.environ[BROWSERS_PATH_VAR] = previous


def browser_problem() -> str | None:
    """Por que um navegador não vai abrir (a mensagem de instalação), ou None se tudo indica que abre. Não abre
    nada: só procura o pacote e o Chromium na pasta do DMaker, para a validação avisar antes do render."""
    if importlib.util.find_spec("playwright") is None:
        return f"O Playwright não está instalado. {INSTALL_HINT}"
    folder = config.PLAYWRIGHT_DIR
    if not (folder.is_dir() and any(folder.glob("chromium*-*"))):
        return f"O Chromium não está em {folder}. {INSTALL_HINT}"
    return None


class Browser(Protocol):
    def html_to_pdf(self, html: str, out: Path) -> None:
        """Imprime a página HTML (A4, com fundo, links internos e marcadores) em `out`."""
        ...

    def screenshot(
        self,
        url: str,
        out: Path,
        *,
        width: int = 1280,
        height: int = 800,
        full_page: bool = False,
        prepare: Callable[[Any], None] | None = None,
    ) -> None:
        """Abre `url` numa janela `width` x `height` e grava a imagem em `out` (PNG ou JPEG, pela extensão).

        `prepare` recebe a página já carregada e pode clicar, digitar e esperar antes da foto.
        """
        ...


class PlaywrightBrowser:
    """Chromium headless do Playwright. Use como contexto para reaproveitar o navegador entre várias chamadas."""

    def __init__(self, launch_args: Sequence[str] = ()) -> None:
        self._launch_args = list(launch_args)
        self._playwright: Any = None
        self._browser: Any = None
        self._depth = 0

    @property
    def is_open(self) -> bool:
        """O Chromium já está aberto (por um `with` desta thread)."""
        return self._depth > 0

    def __enter__(self) -> PlaywrightBrowser:
        if self._depth == 0:
            self._start()
        self._depth += 1
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._depth -= 1
        if self._depth == 0:
            self._stop()

    def _start(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserUnavailable(f"O Playwright não está instalado. {INSTALL_HINT}") from exc
        with _browsers_path():
            self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(args=self._launch_args)
        except Exception as exc:  # noqa: BLE001 - o Playwright levanta um erro próprio quando falta o Chromium
            self._playwright.stop()
            self._playwright = None
            raise BrowserUnavailable(f"Não consegui abrir o Chromium. {INSTALL_HINT}") from exc

    def _stop(self) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._browser = self._playwright = None

    def new_context(self, **options: Any) -> Any:
        """Um contexto isolado do Chromium aberto (use dentro do `with`): é por onde a composição em HTML pede o
        tamanho da janela, a escala de pixels e as rotas que servem os arquivos dela."""
        if self._browser is None:
            raise RuntimeError("o navegador não está aberto: use `with PlaywrightBrowser()`")
        return self._browser.new_context(**options)

    def html_to_pdf(self, html: str, out: Path) -> None:
        with self:
            page = self._browser.new_page()
            try:
                page.set_content(html, wait_until="load")
                out.parent.mkdir(parents=True, exist_ok=True)
                page.pdf(
                    path=str(out),
                    format="A4",
                    print_background=True,
                    prefer_css_page_size=False,
                    margin={"top": "16mm", "bottom": "18mm", "left": "14mm", "right": "14mm"},
                    display_header_footer=True,
                    header_template="<span></span>",
                    footer_template=PDF_FOOTER,
                    outline=True,  # painel de marcadores do leitor de PDF, além do sumário clicável da página
                    tagged=True,
                )
            finally:
                page.close()

    def screenshot(
        self,
        url: str,
        out: Path,
        *,
        width: int = 1280,
        height: int = 800,
        full_page: bool = False,
        prepare: Callable[[Any], None] | None = None,
    ) -> None:
        with self:
            page = self._browser.new_page(viewport={"width": width, "height": height})
            try:
                page.goto(url, wait_until="networkidle")
                if prepare is not None:
                    prepare(page)
                out.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out), full_page=full_page)
            finally:
                page.close()
