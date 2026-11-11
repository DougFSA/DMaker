"""O Ollama que acompanha o pacote: a versão e o arquivo de cada sistema. Dado puro."""

from __future__ import annotations

OLLAMA_VERSION = "0.40.16"
OLLAMA_BASE = f"https://github.com/ollama/ollama/releases/download/v{OLLAMA_VERSION}"
OLLAMA_SUMS_NAME = f"sha256sum-ollama-{OLLAMA_VERSION}.txt"
OLLAMA_SUMS_URL = f"{OLLAMA_BASE}/sha256sum.txt"
# O nome do arquivo na release do Ollama, por sistema.
OLLAMA_ASSETS = {"windows": "OllamaSetup.exe", "linux": "ollama-linux-amd64.tar.zst"}


def ollama_asset(platform: str) -> str:
    return OLLAMA_ASSETS[platform]


def ollama_url(platform: str) -> str:
    return f"{OLLAMA_BASE}/{ollama_asset(platform)}"


def ollama_local_name(platform: str) -> str:
    """O nome do arquivo na pasta de downloads (com a versão, para não confundir duas)."""
    asset = ollama_asset(platform)
    stem, dot, extension = asset.partition(".")
    return f"{stem}-{OLLAMA_VERSION}{dot}{extension}"
