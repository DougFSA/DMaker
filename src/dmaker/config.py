"""Caminhos do projeto. Tudo fica dentro da pasta raiz, que é a do clone, a do programa instalado (achada pelo
`instalacao.json`) ou a de `DMAKER_HOME`; os dados gerados vão para `DMAKER_DATA_DIR` ou, no instalado, para a pasta
do marcador."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent

# O marcador que o instalador grava na raiz do programa instalado: `{"versao": "...", "dados": "<pasta dos dados>"}`.
INSTALL_MARKER_NAME = "instalacao.json"
# O pacote instalado mora em `<programa>/python/Lib/site-packages/dmaker` (Windows) ou em
# `<programa>/python/lib/python3.13/site-packages/dmaker` (Linux): do `site-packages` até o programa são no máximo 4 níveis.
_SITE_PACKAGES = "site-packages"
_MARKER_SEARCH_LEVELS = 5


@dataclass(frozen=True)
class InstallInfo:
    """O que o marcador `instalacao.json` diz: a pasta do programa, a versão instalada e a pasta dos dados."""

    root: Path
    version: str
    data_dir: Path


def find_install_root(package_dir: Path) -> Path | None:
    """Sobe do pacote até achar o marcador; só vale para um pacote dentro de `site-packages`, nunca para o clone
    editável, para um `instalacao.json` solto numa pasta acima do clone não virar a raiz dele."""
    if package_dir.parent.name != _SITE_PACKAGES:
        return None
    for level, folder in enumerate(package_dir.parents):
        if level > _MARKER_SEARCH_LEVELS:
            break
        if (folder / INSTALL_MARKER_NAME).is_file():
            return folder
    return None


def read_install_info(root: Path) -> InstallInfo | None:
    """Lê o marcador da raiz; um marcador ilegível conta como "não instalado", para o clone nunca quebrar por ele."""
    try:
        data = json.loads((root / INSTALL_MARKER_NAME).read_text(encoding="utf-8-sig"))
        data_dir = Path(str(data["dados"])).expanduser().resolve()
        return InstallInfo(root=root.resolve(), version=str(data.get("versao", "")), data_dir=data_dir)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _detect_install() -> InstallInfo | None:
    root = find_install_root(PACKAGE_DIR)
    return read_install_info(root) if root else None


def resolve_root(env_home: str | None, install: InstallInfo | None, package_dir: Path, cwd: Path) -> Path:
    """A raiz do programa: `DMAKER_HOME`, depois o marcador do instalado, depois o clone (pyproject), depois a pasta atual."""
    if env_home:
        return Path(env_home).expanduser().resolve()
    if install:
        return install.root
    # instalação editável: <raiz>/src/dmaker/config.py
    candidate = package_dir.parents[1]
    if (candidate / "pyproject.toml").exists():
        return candidate
    return cwd


def resolve_data_dir(env_data: str | None, install: InstallInfo | None, root: Path) -> Path:
    """Os dados: `DMAKER_DATA_DIR` manda; sem ele, o `dados` do marcador no modo instalado; senão a própria raiz."""
    if env_data:
        return Path(env_data).expanduser().resolve()
    if install:
        return install.data_dir
    return root.resolve()


INSTALL = _detect_install()
ROOT = resolve_root(os.environ.get("DMAKER_HOME"), INSTALL, PACKAGE_DIR, Path.cwd())
# Onde nascem os dados gerados (cache, saída, projetos, vozes, léxico, layouts). Por padrão é a própria raiz;
# os testes apontam DMAKER_DATA_DIR para uma pasta temporária para nunca tocar nos dados de quem usa o editor.
DATA_DIR = resolve_data_dir(os.environ.get("DMAKER_DATA_DIR"), INSTALL, ROOT)
BIN_DIR = ROOT / "bin"
FFMPEG_DIR = BIN_DIR / "ffmpeg"
# Chromium do Playwright (composição em HTML, PDF do manual): mora dentro do clone, como o ffmpeg, para o DMaker
# não guardar nada na pasta compartilhada `%LOCALAPPDATA%/ms-playwright` e não depender dela.
PLAYWRIGHT_DIR = BIN_DIR / "playwright"
# Segundo ffmpeg, só para os efeitos de plugin LV2 (o build principal, o completo do gyan.dev, hospeda o LADSPA mas não o LV2).
# Mora ao lado do principal, instalado por `dmaker setup --plugins`.
FFMPEG_LV2_DIR = BIN_DIR / "ffmpeg-lv2"
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
AUDIO_FX_DIR = (
    CACHE_DIR / "audio-fx"
)  # itens de áudio já com a cadeia de efeitos aplicada (WAV float), compartilhados por render e prévia
GENERATED_DIR = (
    CACHE_DIR / "generated"
)  # sons sintetizados (Tom, Ruído, Bipe...) de `audio.generated`, por hash do gerador, dos parâmetros e da duração
REVERB_IR_DIR = (
    CACHE_DIR / "reverb-ir"
)  # respostas ao impulso do Reverb (WAV float), uma por conjunto de parâmetros da sala
PLUGIN_SCAN_DIR = (
    CACHE_DIR / "plugins"
)  # a varredura dos plugins (o que cada um expõe, lido pelo ffmpeg), por pasta
FRAMES_DIR = CACHE_DIR / "frames"  # quadros do projeto num instante, renderizados pelo pipeline (editor)
WAVEFORM_DIR = CACHE_DIR / "waveform"
SPECTROGRAM_DIR = (
    CACHE_DIR / "spectrogram"
)  # imagens PNG do espectrograma do painel Áudio, por trecho da grade
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
# As predefinições de efeitos de áudio que a pessoa salvou (a cadeia de efeitos com um nome): dado de quem usa o editor,
# irmão do layouts.json, fora do repositório
EFFECT_PRESETS_FILE = (
    DATA_DIR / "effect-presets.json"
)  # só o que veio do DMK-54: as entradas migram para MACROS_DIR
# As macros de áudio que a pessoa salvou (um JSON por macro): as globais aqui e as de cada marca em
# `BRAND_DATA_DIR/<marca>/macros`. É dado de quem usa o editor, por isso fica fora do repositório.
MACROS_DIR = DATA_DIR / "assets" / "macros"
BRAND_DATA_DIR = DATA_DIR / "assets" / "brands"
# Plugins de efeito de terceiros (LV2 e LADSPA) que a pessoa quer usar só no DMaker; a varredura lê também as pastas
# padrão do sistema (somente leitura). O `plugins.json` guarda os que ela desligou. Ambos são dados de quem usa o editor.
PLUGINS_DIR = DATA_DIR / "plugins"
PLUGINS_FILE = DATA_DIR / "plugins.json"

WINDOWS_FONTS_DIR = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"


def ensure_dirs() -> None:
    for d in (
        BIN_DIR,
        FONTS_DIR,
        BRANDS_DIR,
        MEZ_DIR,
        PROXY_DIR,
        PREVIEW_AUDIO_DIR,
        AUDIO_FX_DIR,
        GENERATED_DIR,
        REVERB_IR_DIR,
        FRAMES_DIR,
        WAVEFORM_DIR,
        SPECTROGRAM_DIR,
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


def plugin_ffmpeg_candidates(format_name: str) -> list[Path]:
    """Os ffmpeg que podem hospedar os plugins de um formato (`lv2` ou `ladspa`), do mais específico ao principal: a variável
    `DMAKER_FFMPEG_<FORMATO>_DIR`, o `bin/ffmpeg-lv2` (só no LV2) e o ffmpeg principal. Lidos na hora do uso, para os testes e
    a verificação apontarem para outra pasta. Quem escolhe o que tem o filtro é `media.plugin_host`."""
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    folders: list[Path] = []
    env_dir = os.environ.get(f"DMAKER_FFMPEG_{format_name.upper()}_DIR")
    if env_dir:
        folders.append(Path(env_dir).expanduser())
    if format_name == "lv2":
        folders.append(FFMPEG_LV2_DIR)
    candidates = [folder / sub / exe for folder in folders for sub in ("bin", ".")]
    main = find_tool("ffmpeg")
    if main is not None:
        candidates.append(main)
    return [candidate for candidate in candidates if candidate.exists()]
