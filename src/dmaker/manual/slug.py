"""Âncoras de título no mesmo esquema do GitHub, para o link do Markdown e o do HTML exportado serem o mesmo."""

from __future__ import annotations

import re
import unicodedata


def strip_accents(text: str) -> str:
    """Tira os acentos (`ç` vira `c`): serve a busca, que não deve errar por causa de um acento."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def plain_title(raw: str) -> str:
    """O texto que se lê no título, sem crases, ênfase nem o destino de um link."""
    without_links = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", raw)
    return re.sub(r"[`*~]", "", without_links).strip()


def github_slug(title: str) -> str:
    """Minúsculas, sem pontuação, espaços viram hífen e os acentos ficam (como o GitHub faz)."""
    text = plain_title(title).lower()
    kept = "".join(ch for ch in text if ch.isalnum() or ch in " -_")
    return re.sub(r"\s", "-", kept.strip())


class SlugCounter:
    """Dá a cada título uma âncora única: o segundo "Pela CLI" vira `pela-cli-1`, como no GitHub."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def unique(self, title: str) -> str:
        base = github_slug(title)
        count = self._seen.get(base, 0)
        self._seen[base] = count + 1
        return base if count == 0 else f"{base}-{count}"
