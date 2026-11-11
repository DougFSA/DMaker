"""SHA-256: conferir um download contra o `SHA256SUMS` e calcular o de cada arquivo da release."""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK = 8 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def parse_sha256sums(text: str) -> dict[str, str]:
    """`<hash>  <arquivo>` por linha (o `*` do modo binário é ignorado)."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            sums[parts[1].strip().lstrip("*")] = parts[0].lower()
    return sums
