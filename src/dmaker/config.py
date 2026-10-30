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
# Onde nascem os dados gerados (cache, saída, projetos, vozes, léxico, layouts). Por padrão é a própria raiz;
# os testes apontam DMAKER_DATA_DIR para uma pasta temporária para nunca tocar nos dados de quem usa o editor.
DATA_DIR = Path(os.environ.get("DMAKER_DATA_DIR") or ROOT).expanduser().resolve()
BIN_DIR = ROOT / "bin"
FFMPEG_DIR = BIN_DIR / "ffmpeg"
# Chromium do Playwright (composição em HTML, PDF do manual): mora dentro do clone, como o ffmpeg, para o DMaker
# não guardar nada na pasta compartilhada `%LOCALAPPDATA%/ms-playwright` e não depender dela.
PLAYWRIGHT_DIR = BIN_DIR / "playwright"
ASSETS_DIR = ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
HTML_ASSETS_DIR = ASSETS_DIR / "html"  # three.js e lottie-web (MIT), servidos às composições em HTML
BRANDS_DIR = ASSETS_DIR / "brands"
SFX_DIR = ASSETS_DIR / "sfx"  # biblioteca de efeitos sonoros (WAV sintetizados pelo DMaker, versionados)
VOICES_DIR = DATA_DIR / "assets" / "voices"
LEXICON_DIR = DATA_DIR / "assets"  # pronunciation.json global e brands/<marca>/pronunciation.json
CACHE_DIR = DATA_DIR / "cache"
MEZ_DIR = CACHE_DIR / "mez"
PROXY_DIR = CACHE_DIR / "proxy"
PREVIEW_AUDIO_DIR = (
    CACHE_DIR / "preview-audio"
)  # som da prévia da linha do tempo: pedaços por trecho e a mixagem
WAVEFORM_DIR = CACHE_DIR / "waveform"
VOICE_CACHE_DIR = CACHE_DIR / "voice"
STEMS_DIR = CACHE_DIR / "stems"  # voz e fundo separados (isolamento vocal), por trecho de arquivo
# Voz usada quando a narração não escolhe uma. Vazio (padrão) é a voz automática do OmniVoice; defina
# DMAKER_DEFAULT_VOICE=dora para um rascunho rápido com o Kokoro, por exemplo.
DEFAULT_VOICE_ID = os.environ.get("DMAKER_DEFAULT_VOICE") or None
# Modelo do Ollama que traduz as falas da dublagem. gpt-oss:20b traduz bem e cabe nos 32 GB de RAM; em CPU é
# lento (minutos por lote), então quem tiver outro modelo melhor ajusta por DMAKER_TRANSLATE_MODEL.
TRANSLATE_MODEL = os.environ.get("DMAKER_TRANSLATE_MODEL") or "gpt-oss:20b"
JOBS_DIR = CACHE_DIR / "jobs"
MODELS_DIR = CACHE_DIR / "models"
OUTPUT_DIR = DATA_DIR / "output"
PROJECTS_DIR = DATA_DIR / "projects"
# Conversas do agente local (um JSON por conversa e, ao lado, a pasta dos anexos dela): dado de quem usa o editor, por
# isso mora fora de `cache/`, que se pode apagar a qualquer hora.
CONVERSATIONS_DIR = DATA_DIR / "conversations"
TEMPLATES_DIR = ROOT / "templates"
# Infográficos prontos (contador, barra, linha...): cada um é uma pasta de composição em HTML com o seu esquema de
# parâmetros; moram ao lado dos modelos de projeto, como os outros recursos versionados do clone.
INFOGRAPHICS_DIR = TEMPLATES_DIR / "html"
LAYOUTS_FILE = DATA_DIR / "layouts.json"

WINDOWS_FONTS_DIR = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"


def ensure_dirs() -> None:
    for d in (
        BIN_DIR,
        FONTS_DIR,
        BRANDS_DIR,
        MEZ_DIR,
        PROXY_DIR,
        PREVIEW_AUDIO_DIR,
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
