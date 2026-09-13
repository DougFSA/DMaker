"""Instalação das dependências externas dentro da pasta do projeto: FFmpeg (bin/ffmpeg) e Poppins (assets/fonts)."""

from __future__ import annotations

import shutil
import urllib.request
import zipfile
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TransferSpeedColumn

from .config import BIN_DIR, FFMPEG_DIR, FONTS_DIR, find_tool

console = Console()

FFMPEG_URLS = [
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip",
]
POPPINS_BASE = "https://github.com/google/fonts/raw/main/ofl/poppins/"
POPPINS_FILES = [
    "Poppins-Light.ttf",
    "Poppins-Regular.ttf",
    "Poppins-Medium.ttf",
    "Poppins-SemiBold.ttf",
    "Poppins-Bold.ttf",
    "Poppins-ExtraBold.ttf",
    "Poppins-Italic.ttf",
    "Poppins-BoldItalic.ttf",
]


def download(url: str, dst: Path, label: str | None = None) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "dmaker/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dst, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        with Progress(
            TextColumn("[cyan]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task(label or dst.name, total=total or None)
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                fh.write(chunk)
                progress.update(task, advance=len(chunk))
    return dst


def install_ffmpeg(force: bool = False) -> Path:
    existing = find_tool("ffmpeg")
    if existing and existing.is_relative_to(BIN_DIR) and not force:
        console.print(f"[green]FFmpeg já instalado:[/green] {existing}")
        return existing
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = BIN_DIR / "ffmpeg.zip"
    last_error: Exception | None = None
    for url in FFMPEG_URLS:
        try:
            console.print(f"Baixando FFmpeg de {url}")
            download(url, zip_path, "ffmpeg.zip")
            break
        except Exception as exc:  # pragma: no cover - rede
            last_error = exc
            console.print(f"[yellow]falhou:[/yellow] {exc}")
    else:
        raise RuntimeError(f"Não foi possível baixar o FFmpeg: {last_error}")
    tmp = BIN_DIR / "ffmpeg_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(tmp)
    inner = next((p for p in tmp.iterdir() if p.is_dir()), tmp)
    shutil.rmtree(FFMPEG_DIR, ignore_errors=True)
    shutil.move(str(inner), str(FFMPEG_DIR))
    shutil.rmtree(tmp, ignore_errors=True)
    zip_path.unlink(missing_ok=True)
    exe = find_tool("ffmpeg")
    if not exe:
        raise RuntimeError("FFmpeg extraído, mas ffmpeg.exe não foi encontrado em bin/ffmpeg/bin")
    console.print(f"[green]FFmpeg instalado em[/green] {exe}")
    return exe


def install_fonts(force: bool = False) -> list[Path]:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    done: list[Path] = []
    for name in POPPINS_FILES:
        dst = FONTS_DIR / name
        if dst.exists() and not force:
            done.append(dst)
            continue
        download(POPPINS_BASE + name, dst, name)
        done.append(dst)
    license_file = FONTS_DIR / "OFL-Poppins.txt"
    if not license_file.exists():
        download(POPPINS_BASE + "OFL.txt", license_file, "OFL.txt")
    console.print(f"[green]Poppins pronta em[/green] {FONTS_DIR} ({len(done)} arquivos)")
    return done
