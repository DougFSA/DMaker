"""A chave de cache dos artefatos do pipeline: um hash curto e estável das partes que decidem o conteúdo."""

from __future__ import annotations

import hashlib
import json


def cache_key(*parts: object) -> str:
    """Hash (16 hex) de `parts` serializadas de forma canônica: a mesma entrada dá sempre a mesma chave."""
    raw = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
