"""Receber um arquivo enviado pela interface: gravar em disco ou ler em memória, sempre com limite de tamanho.

O upload de fala (`speech_routes`) e os anexos do agente (`agent_attachments`) usam este mesmo mecanismo: o arquivo é
lido em blocos (nunca inteiro de uma vez), o limite é conferido enquanto se lê, e o resultado só aparece com o nome
final quando terminou (`.part` e `replace`), para ninguém usar um arquivo pela metade.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile

from .. import config

# Um vídeo de celular de alguns minutos cabe nisto; o limite só barra o que claramente não é mídia.
MAX_UPLOAD_BYTES = 4 * 1024**3
UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024
UPLOADS_SUBDIR = "uploads"
DEFAULT_TOO_BIG = "Arquivo grande demais."


@dataclass(frozen=True)
class SavedUpload:
    path: Path
    size: int  # bytes gravados


def media_upload_dir() -> Path:
    """Onde ficam os arquivos que as ferramentas leem por caminho (lido de `config` na hora do uso)."""
    return config.CACHE_DIR / UPLOADS_SUBDIR


def upload_file_name(upload: UploadFile) -> str:
    """O nome do arquivo enviado em forma segura para o disco: sem pasta, sem caractere estranho, com extensão."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(upload.filename or "arquivo").stem).strip("-.")[:60]
    suffix = re.sub(r"[^a-z0-9.]", "", Path(upload.filename or "").suffix.lower())[:6] or ".bin"
    return f"{stem or 'arquivo'}{suffix}"


def _copy_limited(
    upload: UploadFile, write: Callable[[bytes], object], max_bytes: int, too_big: str
) -> tuple[int, str]:
    """Lê o upload em blocos entregando cada um a `write`; devolve os bytes lidos e o sha256 do conteúdo."""
    digest = hashlib.sha256()
    written = 0
    while chunk := upload.file.read(UPLOAD_CHUNK_BYTES):
        written += len(chunk)
        if written > max_bytes:
            raise HTTPException(status_code=413, detail=too_big)
        digest.update(chunk)
        write(chunk)
    if not written:
        raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
    return written, digest.hexdigest()


def save_upload(
    upload: UploadFile,
    folder: Path,
    max_bytes: int = MAX_UPLOAD_BYTES,
    too_big: str = DEFAULT_TOO_BIG,
    name_prefix: str | None = None,
) -> SavedUpload:
    """Grava o arquivo enviado em `folder`, recusando o que passa de `max_bytes`.

    Sem `name_prefix` o conteúdo entra no nome: enviar o mesmo arquivo de novo reaproveita o caminho (e os caches por
    caminho). Com `name_prefix` (o id de um anexo) o nome é só dele, porque dois anexos do mesmo conteúdo não podem
    dividir o arquivo: apagar um levaria o outro junto.
    """
    folder.mkdir(parents=True, exist_ok=True)
    partial = folder / f".{hashlib.sha1(str(id(upload)).encode()).hexdigest()[:8]}.part"
    try:
        with partial.open("wb") as handle:
            written, digest = _copy_limited(upload, handle.write, max_bytes, too_big)
    except BaseException:
        partial.unlink(missing_ok=True)  # o `with` já fechou o arquivo: o Windows só apaga o que está fechado
        raise
    prefix = name_prefix or digest[:10]
    destination = folder / f"{prefix}-{upload_file_name(upload)}"
    partial.replace(destination)
    return SavedUpload(destination, written)


def read_upload(upload: UploadFile, max_bytes: int, too_big: str = DEFAULT_TOO_BIG) -> bytes:
    """O arquivo enviado em memória, para os formatos que se leem por inteiro (documentos pequenos)."""
    chunks: list[bytes] = []
    _copy_limited(upload, chunks.append, max_bytes, too_big)
    return b"".join(chunks)
