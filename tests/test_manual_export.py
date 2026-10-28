"""Exportação do manual: HTML de página única (imagens embutidas, sumário com âncoras) e PDF por um navegador falso."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dmaker.manual import files, service
from dmaker.manual.export import render_html
from dmaker.media import browser as browser_module
from dmaker.media.browser import BrowserUnavailable, PlaywrightBrowser

MINI = """# Manual de teste

Texto de abertura com [um link para fora](../CLAUDE.md) e [um para dentro](#segunda).

## Primeira

### Tarefa A

#### Pela CLI

```powershell
dmaker quick a.mp4
```

### Tarefa B

#### Pela CLI

| Campo | Tipo |
| --- | --- |
| `a` | texto |

![Captura](img/captura.png)

## Segunda

Fim. ![Faltando](img/nao-existe.png)
"""

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


def _loader(source: str):
    return ("image/png", PNG) if source == "img/captura.png" else None


def test_html_embeds_images_and_reports_the_missing_ones():
    document = render_html(MINI, title="Manual", load_image=_loader)
    assert "data:image/png;base64," in document.html
    assert 'src="img/captura.png"' not in document.html
    assert document.missing_images == ("img/nao-existe.png",)


def test_html_toc_links_resolve_to_heading_ids_and_repeated_titles_get_unique_ids():
    html = render_html(MINI, title="Manual", load_image=_loader).html
    ids = set(re.findall(r'<h[1-6] id="([^"]+)"', html))
    toc = re.search(r'<nav class="toc".*?</nav>', html, re.DOTALL).group(0)
    links = re.findall(r'href="#([^"]+)"', toc)
    assert links == ["primeira", "tarefa-a", "tarefa-b", "segunda"]
    assert set(links) <= ids
    assert {"pela-cli", "pela-cli-1"} <= ids  # os dois "Pela CLI" não colidem
    assert toc.index("tarefa-a") > toc.index("primeira") and "<ul>" in toc  # tarefas dentro do capítulo


def test_html_keeps_internal_links_and_strips_links_to_repository_files():
    html = render_html(MINI, title="Manual", load_image=_loader).html
    assert '<a href="#segunda">um para dentro</a>' in html
    assert "<a>um link para fora</a>" in html and "CLAUDE.md" not in html.replace("um link para fora", "")


def test_html_internal_links_keep_accents_so_they_match_the_heading_ids():
    markdown = "# T\n\n[ir](#ação-rápida)\n\n## Ação rápida\n"
    html = render_html(markdown, title="T", load_image=_loader).html
    assert 'href="#ação-rápida"' in html and 'id="ação-rápida"' in html


def test_html_renders_tables_code_and_print_styles():
    html = render_html(MINI, title="Manual", load_image=_loader).html
    assert "<table>" in html and "<code>a</code>" in html and "dmaker quick a.mp4" in html
    assert "@media print" in html and '<html lang="pt-BR">' in html and "<title>Manual</title>" in html


def test_count_pdf_pages_counts_page_objects_not_the_page_tree(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4\n<</Type /Pages /Count 2>>\n<</Type /Page>>\n<</Type/Page /Parent 1 0 R>>\n")
    assert service.count_pdf_pages(pdf) == 2


class _FakeBrowser:
    def __init__(self) -> None:
        self.html = ""

    def html_to_pdf(self, html: str, out: Path) -> None:
        self.html = html
        out.write_bytes(b"%PDF-1.4 /Type /Page /Type /Page /Type /Pages")

    def screenshot(self, url, out, **kwargs) -> None:  # pragma: no cover - não usado aqui
        raise AssertionError


@pytest.fixture
def mini_docs(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    (docs / "img").mkdir(parents=True)
    (docs / "MANUAL.md").write_text(MINI, encoding="utf-8")
    (docs / "img" / "captura.png").write_bytes(PNG)
    monkeypatch.setattr(files, "docs_dir", lambda: docs)
    return docs


def test_export_manual_writes_html_and_pdf_with_the_injected_browser(mini_docs, tmp_path):
    fake = _FakeBrowser()
    report = service.export_manual(tmp_path / "saida", html=True, pdf=True, browser=fake)
    assert report.html_path.name == "DMaker-manual.html" and report.pdf_path.name == "DMaker-manual.pdf"
    assert report.pages == 2 and report.missing_images == ("img/nao-existe.png",)
    assert "data:image/png" in fake.html and report.html_path.read_text(encoding="utf-8") == fake.html


def test_export_only_html_does_not_need_a_browser(mini_docs, tmp_path):
    report = service.export_manual(tmp_path / "saida", html=True, pdf=False, browser=None)
    assert report.html_path.exists() and report.pdf_path is None and report.pages is None


def test_load_image_stays_inside_the_docs_folder(mini_docs):
    assert service.load_image("img/captura.png") == ("image/png", PNG)
    assert service.load_image("../secreto.png") is None
    assert service.load_image("https://example.com/a.png") is None
    assert service.load_image("img/nao-existe.png") is None


def test_playwright_browser_explains_how_to_install_when_the_package_is_missing(monkeypatch, tmp_path):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError("sem playwright")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(BrowserUnavailable, match=r'pip install -e "\.\[docs\]"'):
        PlaywrightBrowser().html_to_pdf("<p>oi</p>", tmp_path / "a.pdf")
    assert "playwright install chromium" in browser_module.INSTALL_HINT


def test_playwright_prints_a_real_pdf_with_internal_links(tmp_path):
    """Com o Chromium instalado (extra `docs`), o PDF sai de verdade e traz a ligação do sumário."""
    pytest.importorskip("playwright")
    html = render_html(MINI, title="Manual", load_image=_loader).html
    out = tmp_path / "manual.pdf"
    try:
        with PlaywrightBrowser() as browser:
            browser.html_to_pdf(html, out)
    except BrowserUnavailable:
        pytest.skip("Chromium do Playwright não instalado")
    data = out.read_bytes()
    assert data.startswith(b"%PDF") and service.count_pdf_pages(out) >= 2
    assert b"/Link" in data or b"/Dest" in data
