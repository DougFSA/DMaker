"""Caminhos do projeto. Tudo fica dentro da pasta raiz (D:/DMaker por padrão)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def _detect_root() -> Path:
    env = os.environ.get("DMAKER_HOME")
    if env:
        return Path(env).expanduser().resolve()
    # instalação editável: <raiz>/src/dmaker/config.py
    candidate = PACKAGE_DIR.parents[1]
    if (candidate / "pyproject.toml").exists():
        return candidate
    return Path.cwd()


ROOT = _detect_root()
BIN_DIR = ROOT / "bin"
FFMPEG_DIR = BIN_DIR / "ffmpeg"
ASSETS_DIR = ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
BRANDS_DIR = ASSETS_DIR / "brands"
CACHE_DIR = ROOT / "cache"
MEZ_DIR = CACHE_DIR / "mez"
PROXY_DIR = CACHE_DIR / "proxy"
WAVEFORM_DIR = CACHE_DIR / "waveform"
JOBS_DIR = CACHE_DIR / "jobs"
MODELS_DIR = CACHE_DIR / "models"
OUTPUT_DIR = ROOT / "output"
PROJECTS_DIR = ROOT / "projects"
TEMPLATES_DIR = ROOT / "templates"

WINDOWS_FONTS_DIR = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"


def ensure_dirs() -> None:
    for d in (
        BIN_DIR,
        FONTS_DIR,
        BRANDS_DIR,
        MEZ_DIR,
        PROXY_DIR,
        WAVEFORM_DIR,
        JOBS_DIR,
        MODELS_DIR,
        OUTPUT_DIR,
        PROJECTS_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


def find_tool(name: str) -> Path | None:
    """Localiza ffmpeg/ffprobe: variável de ambiente > bin/ffmpeg do projeto > PATH."""
    exe = f"{name}.exe" if os.name == "nt" else name
    env_dir = os.environ.get("DMAKER_FFMPEG_DIR")
    candidates = []
    if env_dir:
        candidates += [Path(env_dir) / exe, Path(env_dir) / "bin" / exe]
    candidates += [FFMPEG_DIR / "bin" / exe, FFMPEG_DIR / exe]
    for c in candidates:
        if c.exists():
            return c
    found = shutil.which(name)
    return Path(found) if found else None
