"""Etiquetas do arquivo de áudio (artista, título, álbum...) e os alvos de loudness da saída.

Funções puras: juntam o modelo da marca com o que a spec define e dizem como cada formato guarda cada etiqueta.
Quem passa isso ao ffmpeg é `filtergraph/audio_output.py`.
"""

from __future__ import annotations

from collections.abc import Mapping

from .audio_presets import AudioPreset

# as etiquetas da janela "Edit Metadata Tags" do Audacity, na ordem em que ela as mostra
TAG_FIELDS: tuple[str, ...] = ("artist", "title", "album", "track", "year", "genre", "comment")

TAG_LABELS: dict[str, str] = {
    "artist": "artista",
    "title": "título",
    "album": "álbum",
    "track": "faixa",
    "year": "ano",
    "genre": "gênero",
    "comment": "comentário",
}

# a chave que o ffmpeg usa para cada etiqueta; o muxer de cada formato a converte para o que o contêiner guarda
# (ID3v2.3: TPE1, TIT2, TALB, TRCK, TYER/TDRC, TCON, COMM; Vorbis: ARTIST, TITLE...; INFO do WAV: IART, INAM...)
_FFMPEG_KEYS: dict[str, str] = {
    "artist": "artist",
    "title": "title",
    "album": "album",
    "track": "track",
    "year": "date",
    "genre": "genre",
    "comment": "comment",
}

# o AIFF só tem os blocos NAME, AUTH e ANNO: título, autor (o artista) e comentário
_AIFF_KEYS: dict[str, str] = {"title": "title", "artist": "author", "comment": "comment"}


def merge_metadata(
    template: Mapping[str, str] | None, overrides: Mapping[str, str | None] | None
) -> dict[str, str]:
    """As etiquetas do arquivo: o modelo da marca como ponto de partida e a spec por cima. Texto vazio apaga a
    etiqueta do modelo (a spec diz `comment: ""` para exportar sem o comentário que a marca define)."""
    merged: dict[str, str] = {
        name: str(value).strip() for name, value in (template or {}).items() if name in TAG_FIELDS
    }
    for name, value in (overrides or {}).items():
        if name not in TAG_FIELDS or value is None:
            continue
        merged[name] = str(value).strip()
    return {name: value for name, value in merged.items() if value}


def ffmpeg_tags(preset: AudioPreset, tags: Mapping[str, str]) -> tuple[list[tuple[str, str]], list[str]]:
    """As etiquetas como pares (chave do ffmpeg, valor) para o formato, e os nomes das que o formato não guarda.

    A ordem é a da janela do Audacity, para o comando sair igual a cada vez."""
    keys = _AIFF_KEYS if preset.metadata_style == "aiff" else _FFMPEG_KEYS
    pairs: list[tuple[str, str]] = []
    ignored: list[str] = []
    for name in TAG_FIELDS:
        value = tags.get(name)
        if not value:
            continue
        if name in keys:
            pairs.append((keys[name], value))
        else:
            ignored.append(TAG_LABELS[name])
    return pairs, ignored
