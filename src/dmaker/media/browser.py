"""Acesso ao navegador (Chromium do Playwright) atrás de um protocolo pequeno, para imprimir e fotografar HTML.

Quem precisa de um navegador (o PDF do manual, as capturas de tela, e depois a composição em HTML) depende do
protocolo `Browser`, nunca do Playwright: os testes entram com um falso e o resto do pacote não importa nada
pesado. O Playwright é um extra opcional (`pip install -e ".[docs]"`), e o Chromium baixa à parte
(`python -m playwright install chromium`).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

INSTALL_HINT = (
    'Instale o extra e o navegador: pip install -e ".[docs]" e depois python -m playwright install chromium.'
)
PDF_FOOTER = (
    '<div style="width:100%;font-size:8px;color:#5b6f77;text-align:center;'
    'font-family:Segoe UI,Arial,sans-serif;">Manual do DMaker, página '
    '<span class="pageNumber"></span> de <span class="totalPages"></span></div>'
)


class BrowserUnavailable(RuntimeError):
    """O Playwright ou o Chromium não estão instalados; a mensagem diz como instalar."""


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

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._depth = 0

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
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch()
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
