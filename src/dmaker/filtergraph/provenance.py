"""Argumentos do ffmpeg que gravam a etiqueta de procedência (ver `voice/provenance.py`) no arquivo de saída."""

from __future__ import annotations

from ..voice.provenance import TAG_KEY


def provenance_args(text: str) -> list[str]:
    """`-metadata comment=...` para ficar antes do nome do arquivo de saída; vazio quando não há etiqueta.

    `comment` é uma chave padrão do ffmpeg: mp4/m4a gravam como ©cmt, mp3 como COMM e wav como ICMT, sem
    `-movflags use_metadata_tags` (que só serve a chaves próprias em mp4). O valor é ASCII de propósito:
    o ID3v2.3 do mp3 guarda texto não ASCII em UTF-16 e nem todo leitor entende.
    """
    return ["-metadata", f"{TAG_KEY}={text}"] if text else []


def inherited_provenance_args(text: str) -> list[str]:
    """Como `provenance_args`, mas sem etiqueta apaga a que o ffmpeg herdaria do primeiro arquivo de entrada.

    O ffmpeg copia os metadados globais da primeira entrada. Num vídeo montado a partir de outro vídeo (um
    clipe que já foi exportado pelo DMaker), a etiqueta dele traria trechos de uma linha do tempo que não é a
    desta saída: melhor nenhuma do que uma que mente. `comment=` vazio remove a chave.
    """
    return provenance_args(text) or ["-metadata", f"{TAG_KEY}="]
