"""Tira as capturas de tela do manual (docs/img) da interface do DMaker, com projetos sintéticos.

Uso (de dentro da pasta do DMaker, com o extra `docs` e o Chromium instalados):

    # 1. uma pasta de dados só para a captura, com projetos de mídia sintética (nunca os seus projetos reais)
    $env:DMAKER_DATA_DIR = "C:\\temp\\dados-captura"
    # 2. a interface nessa pasta, numa porta que não seja a 8765 (a do uso diário)
    python -m dmaker.cli ui --port 8769 --no-browser
    # 3. em outra janela
    python scripts/capturar_manual.py --base-url http://127.0.0.1:8769

Os nomes dos projetos usados (`quick_gravacao`, `entrevista-corte`, o lote `semana`) vêm da tarefa "Fazer um Reel"
e das tarefas de corte e de lote do manual: seguir o manual numa pasta de dados limpa os cria. A captura da Fila
mostra o que a fila da pasta de dados tem na hora: deixe nela um item pronto, um rodando e alguns esperando.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dmaker.media.browser import PlaywrightBrowser

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "docs" / "img"


@dataclass(frozen=True)
class Shot:
    name: str
    path: str
    width: int = 1280
    height: int = 800
    prepare: Callable[[Any], None] | None = None


def _settle(page: Any, ms: int = 1200) -> None:
    page.wait_for_timeout(ms)


def _open_new_project(page: Any) -> None:
    page.get_by_role("button", name="Novo projeto").first.click()
    page.get_by_label("Nome do projeto").fill("meu-reel")
    _settle(page, 500)


def _open_autocut(page: Any) -> None:
    page.get_by_role("button", name="Cortar gravação").first.click()
    _settle(page, 600)


def _validate_and_qa(page: Any) -> None:
    page.get_by_role("button", name="Validar").click()
    _settle(page, 2500)
    page.get_by_role("button", name="Conferir qualidade").click()
    _settle(page, 6000)


def _fill_batch(sheet: str) -> Callable[[Any], None]:
    def prepare(page: Any) -> None:
        page.get_by_label("Modelo").select_option("stories-medlycare")
        page.get_by_placeholder("Caminho do .csv, .xlsx ou .json").fill(sheet)
        page.get_by_role("button", name="Validar planilha").click()
        _settle(page, 3000)

    return prepare


def _wait_images(page: Any) -> None:
    _settle(page, 9000)  # as folhas de contato nascem na primeira visita (ffmpeg) e depois ficam em cache


def _fill_clone_voice(page: Any) -> None:
    page.get_by_label("Nome da voz").first.fill("Locutora da clínica")
    page.get_by_label("Tenho permissão do dono desta voz para cloná-la").scroll_into_view_if_needed()
    _settle(page, 600)


def _fill_narration(page: Any) -> None:
    roteiro = (
        "Olá! Este é o roteiro da narração.\n\n"
        "O [[DMaker|Di-mêiker]] fala cada frase assim que ela fica pronta. [pausa 0.8] Até já."
    )
    page.get_by_label("Roteiro").fill(roteiro)
    _settle(page, 600)


def _open_tab(tab: str, scroll_to: str | None = None) -> Callable[[Any], None]:
    def prepare(page: Any) -> None:
        page.locator(f'button[data-tab="{tab}"]').click()
        _settle(page, 1500)
        if scroll_to:
            page.locator(scroll_to).scroll_into_view_if_needed()
            _settle(page, 400)

    return prepare


def shots(sheet: str) -> list[Shot]:
    return [
        Shot("ui-projetos.png", "/projetos", prepare=lambda page: _settle(page, 1500)),
        Shot("ui-novo-projeto.png", "/projetos", prepare=_open_new_project),
        Shot("ui-cortar-gravacao.png", "/projetos", prepare=_open_autocut),
        Shot("ui-projeto-qa.png", "/projetos/entrevista-corte", height=1100, prepare=_validate_and_qa),
        Shot("ui-lote.png", "/lote", height=1000, prepare=_fill_batch(sheet)),
        Shot("ui-transicoes.png", "/transicoes", prepare=_wait_images),
        Shot("ui-looks.png", "/looks", prepare=_wait_images),
        Shot("ui-voz-vozes.png", "/voz", height=1250, prepare=_fill_clone_voice),
        Shot("ui-voz-narracao.png", "/voz/narracao", height=1000, prepare=_fill_narration),
        Shot("ui-fila.png", "/fila", height=900, prepare=lambda page: _settle(page, 2500)),
        Shot("classica-linha-do-tempo.png", "/classica#project=quick_gravacao", prepare=lambda page: _settle(page, 3500)),
        Shot("classica-voz.png", "/classica", height=900, prepare=_open_tab("voice", "#voice-clone-consent")),
        Shot("classica-dublar.png", "/classica", height=900, prepare=_open_tab("voice", "#dub-source")),
        Shot("classica-modelos.png", "/classica", height=900, prepare=_open_tab("models")),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8769")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--sheet", default="semana.csv", help="Planilha do lote usada na tela Lote.")
    parser.add_argument("--only", nargs="*", help="Só estes arquivos (por exemplo ui-lote.png).")
    args = parser.parse_args()

    selected = [shot for shot in shots(args.sheet) if not args.only or shot.name in args.only]
    with PlaywrightBrowser() as browser:
        for shot in selected:
            target = args.out / shot.name
            browser.screenshot(
                args.base_url + shot.path, target, width=shot.width, height=shot.height, prepare=shot.prepare
            )
            print(f"{shot.name}: {target.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
