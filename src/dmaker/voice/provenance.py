"""Etiqueta de procedência: o texto legível, gravado no contêiner, que diz "este arquivo tem voz gerada por IA".

A marca d'água no áudio não acha uma frase curta dentro de um vídeo longo (medido: uma janela de 2 s de fala
humana sem marca pontua 0.82, tanto quanto a frase marcada), então o DMaker também carimba o arquivo que grava.
A etiqueta é versionada e diz onde a voz gerada toca, em segundos do arquivo final:

    DMaker: voz gerada por IA (v1); trechos=33.10-34.42,50.00-52.30

Sem `trechos=`, a voz gerada é o arquivo inteiro. Tudo aqui é puro: o texto sai de dados e volta a dados; quem
grava (filtergraph) e quem lê (verificação) ficam fora.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .watermark import Span

PROVENANCE_VERSION = 1
PROVENANCE_PREFIX = f"DMaker: voz gerada por IA (v{PROVENANCE_VERSION})"
SPANS_KEY = "trechos="
# `comment` é a chave padrão do ffmpeg para um comentário livre e existe em todos os contêineres que o DMaker
# grava: mp4 e m4a (©cmt), mp3 (COMM do ID3) e wav (ICMT do LIST INFO). Sobrevive a copiar o fluxo (`-c copy`),
# mas não a recodificar o arquivo por um programa que descarta os metadados (o que as redes sociais fazem).
TAG_KEY = "comment"
# Uma dublagem tem dezenas de falas; passando disso as falas próximas são fundidas, para a etiqueta continuar curta.
MAX_SPANS = 40
# Folgas (s) tentadas, da menor à maior, até os trechos caberem em `MAX_SPANS`.
_MERGE_GAPS = (0.05, 0.5, 2.0, 8.0, 30.0)

_SPAN_PATTERN = re.compile(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)")
_VERSION_PATTERN = re.compile(r"^DMaker: voz gerada por IA \(v(\d+)\)")


@dataclass(frozen=True)
class Provenance:
    """O que a etiqueta de um arquivo diz: a versão do formato e os trechos de voz gerada (vazio = o arquivo todo)."""

    version: int
    spans: tuple[Span, ...] = ()


def merge_spans(spans: Iterable[Span], limit: int = MAX_SPANS, total: float | None = None) -> list[Span]:
    """Ordena, descarta o vazio e funde trechos que se tocam; se ainda passar de `limit`, funde os mais próximos.

    `total` corta o que passa do fim do arquivo (uma narração maior que o vídeo é cortada na saída).
    """
    cleaned = sorted(
        (max(0.0, start), min(end, total) if total is not None else end)
        for start, end in spans
        if end > start
    )
    cleaned = [(start, end) for start, end in cleaned if end > start]
    merged = _merge_closer_than(cleaned, 0.0)
    for gap in _MERGE_GAPS:
        if len(merged) <= limit:
            break
        merged = _merge_closer_than(merged, gap)
    return merged


def _merge_closer_than(spans: Sequence[Span], gap: float) -> list[Span]:
    merged: list[Span] = []
    for start, end in spans:
        if merged and start - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def provenance_text(spans: Iterable[Span] | None = None, total: float | None = None) -> str:
    """O texto da etiqueta. `spans=None` é o arquivo inteiro; com trechos que não deixam nada dentro do
    arquivo (a narração começa depois do fim do vídeo) não há voz gerada a declarar e o texto é vazio."""
    if spans is None:
        return PROVENANCE_PREFIX
    merged = merge_spans(spans, total=total)
    if not merged:
        return ""
    listed = ",".join(f"{start:.2f}-{end:.2f}" for start, end in merged)
    return f"{PROVENANCE_PREFIX}; {SPANS_KEY}{listed}"


def parse_provenance(tags: Mapping[str, str]) -> Provenance | None:
    """A etiqueta de procedência de um arquivo a partir das tags do contêiner; None se não houver."""
    value = next((str(text) for key, text in tags.items() if key.lower() == TAG_KEY), "")
    found = _VERSION_PATTERN.match(value.strip())
    if found is None:
        return None
    _, _, tail = value.partition(SPANS_KEY)
    spans = tuple((float(start), float(end)) for start, end in _SPAN_PATTERN.findall(tail)) if tail else ()
    return Provenance(int(found.group(1)), spans)


def describe_spans(spans: Sequence[Span]) -> str:
    """Os trechos em português, para a frase do veredito: "33,1 a 34,4 s; 50,0 a 52,3 s"."""
    return "; ".join(f"{start:.1f} a {end:.1f} s".replace(".", ",") for start, end in spans)


def combine_spans(existing: Provenance | None, new: Iterable[Span]) -> list[Span] | None:
    """Trechos de voz gerada de um arquivo que foi editado: os da etiqueta que ele já tinha mais os novos.

    `None` quando a etiqueta anterior declarava o arquivo inteiro: acrescentar trechos não diminui isso.
    """
    if existing is not None and not existing.spans:
        return None
    return [*(existing.spans if existing else ()), *new]
