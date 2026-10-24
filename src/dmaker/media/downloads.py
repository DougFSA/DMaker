"""Download de modelos com versão fixada: tamanho e SHA-256 conferidos antes de o arquivo valer.

Modelo baixado de release público roda código ONNX na máquina; por isso o arquivo só é aceito se bater com o
hash gravado no código, e o `.part` temporário nunca vira o arquivo final sem passar pela conferência.
"""

from __future__ import annotations

import hashlib
import tarfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

Downloader = Callable[[str, Path], None]
CHUNK_BYTES = 1 << 20


@dataclass(frozen=True)
class RemoteFile:
    name: str  # nome do arquivo na pasta de destino
    url: str
    size: int
    sha256: str


def download_file(url: str, destination: Path) -> None:
    """Baixa `url` para `destination` (sem checagem; quem chama confere tamanho e hash)."""
    with urllib.request.urlopen(url, timeout=60) as response, destination.open("wb") as out:
        while chunk := response.read(CHUNK_BYTES):
            out.write(chunk)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def is_intact(path: Path, expected: RemoteFile) -> bool:
    """Tamanho primeiro (barato); o hash só quando o tamanho bate."""
    return path.is_file() and path.stat().st_size == expected.size and sha256_of(path) == expected.sha256


def ensure_file(directory: Path, expected: RemoteFile, downloader: Downloader = download_file) -> Path:
    """Garante o arquivo íntegro em `directory`, baixando (para um .part, depois renomeado) se faltar."""
    target = directory / expected.name
    if is_intact(target, expected):
        return target
    directory.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    try:
        downloader(expected.url, partial)
        if not is_intact(partial, expected):
            raise RuntimeError(
                f"O download de {expected.name} veio corrompido (tamanho ou hash diferente do esperado). "
                "Tente de novo."
            )
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def ensure_archive_member(
    directory: Path,
    archive: RemoteFile,
    member: str,
    extracted: RemoteFile,
    downloader: Downloader = download_file,
) -> Path:
    """Garante `member` do pacote `archive` extraído em `directory/extracted.name`, conferido pelo hash dele.

    Só o membro pedido é lido, por nome, e gravado num nome fixo: um pacote com caminhos maliciosos não
    escreve fora da pasta. O pacote baixado é apagado depois da extração, o modelo é o que fica.
    """
    target = directory / extracted.name
    if is_intact(target, extracted):
        return target
    pack_dir = directory / ".pacote"
    try:
        pack = ensure_file(pack_dir, archive, downloader)
        with tarfile.open(pack, "r:*") as tar:
            try:
                source = tar.extractfile(member)
            except KeyError:
                source = None
            if source is None:
                raise RuntimeError(f"O pacote {archive.name} não traz {member}.")
            partial = target.with_suffix(target.suffix + ".part")
            try:
                with source, partial.open("wb") as out:
                    while chunk := source.read(CHUNK_BYTES):
                        out.write(chunk)
                if not is_intact(partial, extracted):
                    raise RuntimeError(
                        f"{extracted.name} extraído de {archive.name} não bate com o hash esperado."
                    )
                partial.replace(target)
            finally:
                partial.unlink(missing_ok=True)
    finally:
        for leftover in pack_dir.glob("*") if pack_dir.is_dir() else []:
            leftover.unlink(missing_ok=True)
        if pack_dir.is_dir():
            pack_dir.rmdir()
    return target
