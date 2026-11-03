"""Preparação do modelo "podcast" (`templates/podcast.json`): confere os parâmetros e deriva o que o JSON do modelo
não calcula sozinho (a duração total, onde a música de encerramento entra e as etiquetas que o episódio preenche).

O modelo é um episódio só de áudio: a música de abertura, a voz gravada, a música de encerramento, tudo normalizado a
-16 LUFS (o alvo de podcast) e gravado como MP3 com as etiquetas do episódio. A limpeza da voz (ruído, cortes de
respiração) é uma etapa que o editor de áudio ainda vai ganhar; quando ela existir, este modelo a liga. Tudo aqui é
puro: recebe dados, devolve dados.
"""

from __future__ import annotations

from typing import Any

# (nome do parâmetro, etiqueta do arquivo): só as que o episódio preencheu entram em `output.metadata`
TAG_PARAMS = (
    ("artista", "artist"),
    ("titulo", "title"),
    ("album", "album"),
    ("faixa", "track"),
    ("ano", "year"),
    ("genero", "genre"),
    ("comentario", "comment"),
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def prepare_podcast(params: dict[str, Any]) -> dict[str, Any]:
    """Preparador do modelo "podcast": confere as durações e acrescenta `total` (abertura, voz e encerramento
    somados), `inicio_encerramento` (onde a música de encerramento entra), `tem_abertura`, `tem_encerramento` e
    `etiquetas` (só as etiquetas preenchidas)."""
    voice = params.get("duracao_voz")
    if not _is_number(voice) or voice <= 0:
        raise ValueError(
            "`duracao_voz` é a duração da gravação em segundos, maior que zero (omitida, vale a do arquivo de voz)"
        )
    intro = params.get("abertura", 0)
    outro = params.get("encerramento", 0)
    for name, value in (("abertura", intro), ("encerramento", outro)):
        if not _is_number(value) or value < 0:
            raise ValueError(f"`{name}` são os segundos de música, zero ou mais (veio {value!r})")
    voice, intro, outro = float(voice), float(intro), float(outro)
    tags = {
        tag: str(params[name]).strip()
        for name, tag in TAG_PARAMS
        if params.get(name) not in (None, "") and str(params[name]).strip()
    }
    return {
        **params,
        "duracao_voz": voice,
        "abertura": intro,
        "encerramento": outro,
        "total": round(intro + voice + outro, 3),
        "inicio_encerramento": round(intro + voice, 3),
        "tem_abertura": intro > 0,
        "tem_encerramento": outro > 0,
        "etiquetas": tags,
    }
