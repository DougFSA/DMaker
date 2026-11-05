"""Instalação das dependências externas dentro da pasta do projeto: FFmpeg (bin/ffmpeg), Poppins (assets/fonts) e,
a pedido, o Chromium do Playwright (`dmaker setup --html`, em bin/playwright) e o FFmpeg que hospeda os plugins LV2
(`dmaker setup --plugins`, em bin/ffmpeg-lv2). Todo download de programa tem o SHA-256 conferido contra o que o site publica."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import platform as platform_module
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TransferSpeedColumn

from . import config
from .config import BIN_DIR, FFMPEG_DIR, FONTS_DIR, find_tool
from .media.browser import BROWSERS_PATH_VAR, browser_problem, playwright_env

console = Console()


@dataclass(frozen=True)
class FfmpegBuild:
    """Um build do ffmpeg para baixar: de onde, em que formato de arquivo e onde está a soma SHA-256 para conferir.

    `checksum` é o endereço do arquivo de soma. Ele pode ter só o hash (o `.sha256` do gyan.dev) ou uma lista `hash  arquivo`
    (o `checksums.sha256` do BtbN); `parse_checksum` lê os dois."""

    name: str
    url: str
    checksum: str
    archive: str  # "7z", "zip" ou "tar.xz"


# O build principal é o completo do gyan.dev: tem tudo o que o essentials tinha e mais o filtro `ladspa` (os plugins LADSPA).
# Foi medido que ele renderiza igual: a saída dos projetos de teste (vídeo, legenda, música, transições, efeitos, PiP) saiu
# byte a byte igual à do essentials, e as chaves de mezanino são as mesmas (não dependem do ffmpeg). O essentials fica de
# reserva, para a máquina em que o `tar` não abre `.7z`.
FFMPEG_FULL = FfmpegBuild(
    "FFmpeg completo (gyan.dev)",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z.sha256",
    "7z",
)
FFMPEG_ESSENTIALS = FfmpegBuild(
    "FFmpeg essentials (gyan.dev)",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256",
    "zip",
)
FFMPEG_BUILDS = [FFMPEG_FULL, FFMPEG_ESSENTIALS]

# O filtro `lv2` não vem no build do gyan.dev. O BtbN o compila, e ele fica à parte (`bin/ffmpeg-lv2`), só para os efeitos de
# plugin LV2: o render comum segue no build principal.
_BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
FFMPEG_LV2_BUILDS = {
    ("win32", "x64"): FfmpegBuild(
        "FFmpeg com LV2 (BtbN, Windows x64)",
        _BTBN + "ffmpeg-n9.0-latest-win64-gpl-9.0.zip",
        _BTBN + "checksums.sha256",
        "zip",
    ),
    ("linux", "x64"): FfmpegBuild(
        "FFmpeg com LV2 (BtbN, Linux x64)",
        _BTBN + "ffmpeg-n9.0-latest-linux64-gpl-9.0.tar.xz",
        _BTBN + "checksums.sha256",
        "tar.xz",
    ),
}
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


def fetch_text(url: str) -> str:
    """O texto de um endereço (os arquivos de soma são pequenos)."""
    req = urllib.request.Request(url, headers={"User-Agent": "dmaker/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_checksum(text: str, filename: str) -> str:
    """O SHA-256 de `filename` num arquivo de soma. Aceita só o hash (uma linha) ou uma lista `hash  arquivo` / `hash *arquivo`;
    na lista, o nome do arquivo escolhe a linha."""
    lines = [line.split() for line in text.splitlines() if line.strip()]
    if len(lines) == 1 and len(lines[0]) == 1:
        found = lines[0][0]
    else:
        found = next(
            (parts[0] for parts in lines if len(parts) >= 2 and parts[-1].lstrip("*") == filename), ""
        )
    if len(found) != 64 or any(char not in "0123456789abcdefABCDEF" for char in found):
        raise RuntimeError(f"não achei o SHA-256 de {filename} no arquivo de soma")
    return found.lower()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_download(path: Path, expected: str) -> None:
    """Recusa o arquivo cuja soma não é a que o site publicou (download cortado, ou trocado no caminho)."""
    actual = sha256_of(path)
    if actual != expected:
        raise RuntimeError(
            f"o SHA-256 de {path.name} não confere (esperado {expected[:12]}..., veio {actual[:12]}...)"
        )


def extract_archive(archive: Path, kind: str, destination: Path) -> None:
    """Descompacta sem dependência nova: `.zip` pelo Python e o resto (`.7z`, `.tar.xz`) pelo `tar` do sistema. No Windows é o
    `tar.exe` do System32 (bsdtar, que abre `.7z`), nunca o `tar` do Git Bash, que é o GNU e não abre."""
    destination.mkdir(parents=True, exist_ok=True)
    if kind == "zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(destination)
        return
    system_tar = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "tar.exe"
    tar = str(system_tar) if os.name == "nt" and system_tar.exists() else shutil.which("tar")
    if tar is None:
        raise RuntimeError(f"não há o programa `tar` para abrir {archive.name}")
    result = subprocess.run(
        [tar, "-xf", str(archive), "-C", str(destination)], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"o `tar` não conseguiu abrir {archive.name}: {result.stderr.strip()[-300:]}")


def _fetch_build(
    build: FfmpegBuild, work: Path, download_file: Callable[..., Path], read_text: Callable[[str], str]
) -> Path:
    """Baixa o arquivo do build, confere a soma e o descompacta numa pasta de trabalho; devolve a pasta do build dentro dele."""
    filename = build.url.rsplit("/", 1)[-1]
    archive = work / filename
    console.print(f"Baixando {build.name} de {build.url}")
    download_file(build.url, archive, filename)
    verify_download(archive, parse_checksum(read_text(build.checksum), filename))
    unpacked = work / "extraido"
    shutil.rmtree(unpacked, ignore_errors=True)
    extract_archive(archive, build.archive, unpacked)
    archive.unlink(missing_ok=True)
    return next((p for p in unpacked.iterdir() if p.is_dir()), unpacked)


def _swap_folder(new: Path, target: Path) -> None:
    """Põe a pasta `new` no lugar de `target`. A antiga só some depois de a nova entrar: se o ffmpeg dela está em uso (a interface
    aberta), o Windows recusa renomear e a instalação antiga fica intacta, com o motivo."""
    old = target.with_name(target.name + ".antigo")
    shutil.rmtree(old, ignore_errors=True)
    if target.exists():
        try:
            target.rename(old)
        except OSError as exc:
            raise RuntimeError(
                f"não consegui trocar {target}: {exc}. Feche a interface (`dmaker ui`) e qualquer render e rode de novo."
            ) from exc
    shutil.move(str(new), str(target))
    shutil.rmtree(old, ignore_errors=True)


def _has_ladspa(executable: Path) -> bool:
    from .media.plugin_host import has_filter

    return has_filter(executable, "ladspa")


def install_ffmpeg(
    force: bool = False,
    *,
    builds: Sequence[FfmpegBuild] = (),
    download_file: Callable[..., Path] | None = None,
    read_text: Callable[[str], str] | None = None,
) -> Path:
    """Instala o FFmpeg em `bin/ffmpeg`: o build completo do gyan.dev (o essentials é a reserva). Um FFmpeg que já está lá mas não
    tem o filtro `ladspa` (o essentials de antes) é trocado sem `--force`, porque a diferença é o que os plugins LADSPA precisam."""
    existing = find_tool("ffmpeg")
    if existing and existing.is_relative_to(BIN_DIR) and not force:
        if _has_ladspa(existing):
            console.print(f"[green]FFmpeg já instalado:[/green] {existing}")
            return existing
        console.print("O FFmpeg instalado é o essentials, sem o filtro ladspa: trocando pelo build completo.")
    download_file = download_file or download
    read_text = read_text or fetch_text
    work = BIN_DIR / "ffmpeg_tmp"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    unpacked: Path | None = None
    try:
        for build in builds or FFMPEG_BUILDS:
            try:
                unpacked = _fetch_build(build, work, download_file, read_text)
                break
            except Exception as exc:  # pragma: no cover - rede e disco
                last_error = exc
                console.print(f"[yellow]falhou:[/yellow] {exc}")
        if unpacked is None:
            raise RuntimeError(f"Não foi possível baixar o FFmpeg: {last_error}")
        _swap_folder(unpacked, FFMPEG_DIR)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    exe = find_tool("ffmpeg")
    if not exe:
        raise RuntimeError("FFmpeg extraído, mas ffmpeg.exe não foi encontrado em bin/ffmpeg/bin")
    console.print(f"[green]FFmpeg instalado em[/green] {exe}")
    return exe


def lv2_build(platform: str | None = None, machine: str | None = None) -> FfmpegBuild | None:
    """O build com LV2 para este sistema, ou None quando não há um (o DMaker só baixa o de Windows e Linux x64)."""
    system = platform or sys.platform
    kind = "win32" if system.startswith("win") else "linux" if system.startswith("linux") else system
    arch = (machine or platform_module.machine()).lower()
    return FFMPEG_LV2_BUILDS.get((kind, "x64" if arch in {"amd64", "x86_64"} else arch))


def install_lv2_ffmpeg(
    force: bool = False,
    *,
    build: FfmpegBuild | None = None,
    download_file: Callable[..., Path] | None = None,
    read_text: Callable[[str], str] | None = None,
) -> Path:
    """Instala o segundo FFmpeg, o que hospeda os plugins LV2, em `bin/ffmpeg-lv2` (`dmaker setup --plugins`)."""
    target = config.FFMPEG_LV2_DIR
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    installed = target / "bin" / exe
    if installed.exists() and not force:
        console.print(f"[green]FFmpeg com LV2 já instalado:[/green] {installed}")
        return installed
    chosen = build or lv2_build()
    if chosen is None:
        raise RuntimeError(
            "Não há um FFmpeg com LV2 pronto para este sistema. Instale um e aponte a variável DMAKER_FFMPEG_LV2_DIR para ele."
        )
    work = BIN_DIR / "ffmpeg_lv2_tmp"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    try:
        unpacked = _fetch_build(chosen, work, download_file or download, read_text or fetch_text)
        _swap_folder(unpacked, target)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if not installed.exists():
        raise RuntimeError(f"O FFmpeg com LV2 foi extraído, mas {installed} não existe")
    console.print(f"[green]FFmpeg com LV2 instalado em[/green] {installed}")
    return installed


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


def install_chromium(run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> Path:
    """Instala o Chromium do Playwright em `bin/playwright`, dentro do clone: a pasta compartilhada
    `%LOCALAPPDATA%/ms-playwright` não é do DMaker, e apagar o clone leva o navegador junto. Exige o extra
    `html` (que traz o pacote `playwright`). `run` entra por injeção para o teste não baixar 120 MB."""
    if importlib.util.find_spec("playwright") is None:
        raise RuntimeError(browser_problem() or "O Playwright não está instalado.")
    target = config.PLAYWRIGHT_DIR
    target.mkdir(parents=True, exist_ok=True)
    console.print(f"Baixando o Chromium (cerca de 120 MB) para {target}")
    result = run([sys.executable, "-m", "playwright", "install", "chromium"], env=playwright_env())
    if result.returncode != 0:
        raise RuntimeError(f"O playwright não conseguiu instalar o Chromium (código {result.returncode}).")
    if browser_problem() is not None:
        raise RuntimeError(f"O Chromium foi baixado, mas não está em {target} ({BROWSERS_PATH_VAR}).")
    console.print(f"[green]Chromium pronto em[/green] {target}")
    return target
