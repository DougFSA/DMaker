"""Peças compartilhadas pelos testes do lote: render falso, probe falso, planilha e imagens de exemplo."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from dmaker.media.probe import MediaInfo
from dmaker.pipeline.batch import RowOutcome

TITLES = ["Dica um", "Dica dois", "Dica três", "Dica quatro", "Dica cinco"]


def fake_prober(path: Path) -> MediaInfo:
    return MediaInfo(path, 0.0, 1080, 1920, 0.0, True, False, True)


class FakeRenderer:
    """Escreve o vídeo e anota o que renderizou; `before` deixa o teste interferir no meio (pausar, cair)."""

    def __init__(self, before=None) -> None:
        self.calls: list[str] = []
        self.before = before

    def render(self, project, out, *, preview, preset, sink, log) -> RowOutcome:
        if self.before:
            self.before(project, len(self.calls))
        self.calls.append(project.name)
        out.write_bytes(b"video")
        return RowOutcome(out, 8.0, 0.1, [])


def make_media(tmp_path: Path) -> Path:
    """Pasta da planilha com cinco imagens de verdade (a pipeline abre o arquivo, mesmo com o ffmpeg gravado)."""
    folder = tmp_path / "planilha"
    folder.mkdir()
    for number in range(1, 6):
        Image.new("RGB", (108, 192), "#3366CC").save(folder / f"img{number}.png")
    return folder


def write_sheet(folder: Path, titles=TITLES, name="semana.csv", broken: dict[int, str] | None = None) -> Path:
    """CSV de três colunas (titulo;texto;print), UTF-8 com BOM como o Excel grava; `broken` troca a imagem de uma linha."""
    lines = ["titulo;texto;print"]
    for position, title in enumerate(titles, start=1):
        image = (broken or {}).get(position, f"img{position}.png")
        lines.append(f"{title};Texto {position};{image}")
    path = folder / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path
