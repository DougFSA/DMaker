"""O que o pedido já diz: extração determinística dos dados que o usuário escreveu, para o modelo não perguntar de novo.

Um modelo pequeno pergunta "qual é o nome do projeto?" quando o pedido já dizia `meu-video`, ou "qual trecho?" quando
a pessoa queria o arquivo inteiro. Tirar esse trabalho dele é mais seguro do que pedir no prompt que ele não o faça:
a regra acha o nome de projeto que existe, os arquivos, os intervalos de tempo ("de 0:12 a 0:20", "os primeiros
30 s"), o que está entre aspas, o idioma, a data e o casal, e o resultado entra na mensagem como um bloco curto.
Tudo aqui é função pura sobre texto: o disco (a lista de projetos) entra por parâmetro.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from .triage import normalize

TimeKind = Literal["range", "first", "last", "from"]

_NUMBER = r"\d+(?::\d{2})?(?:[.,]\d+)?"
_UNIT = r"(?:s|seg|segs|segundo|segundos|min|mins|minuto|minutos)"
# "de 0:12 a 0:20", "entre 10 e 14 s", "dos 1 aos 6 segundos": o segundo número leva a unidade ou os dois têm ":"
_RANGE = re.compile(
    rf"\b(?:de|entre|dos|das|do|da)\s+({_NUMBER})\s*({_UNIT})?\s*(?:a|ate|e|aos|as)\s+({_NUMBER})\s*({_UNIT})?\b"
)
_FIRST = re.compile(rf"\bprimeir[oa]s?\s+({_NUMBER})\s*({_UNIT})\b")
_LAST = re.compile(rf"\bultim[oa]s?\s+({_NUMBER})\s*({_UNIT})\b")
_FROM = re.compile(rf"\ba partir de\s+({_NUMBER})\s*({_UNIT})\b")
_DRIVE_PATH = re.compile(r"[A-Za-z]:[\\/][^\s\"'<>|?*;,]+")
_MEDIA_NAME = re.compile(
    r"(?<![\w/\\:.-])[\w.-]+\.(?:mp4|mov|mkv|webm|avi|m4v|wav|mp3|m4a|flac|aac|png|jpe?g|webp|csv|xlsx|srt)\b",
    re.IGNORECASE,
)
_QUOTED = re.compile(r"\"([^\"\n]{1,200})\"|“([^”\n]{1,200})”|(?<![\w])'([^'\n]{1,120})'(?![\w])")
_DATE = re.compile(r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b")
_COUPLE = re.compile(r"\b([A-ZÀ-Ý][\wÀ-ÿ]+)\s*&\s*([A-ZÀ-Ý][\wÀ-ÿ]+)")
_TRAILING = ".,;:)]}"

LANGUAGES: dict[str, tuple[str, str]] = {
    "ingles": ("inglês", "en"),
    "espanhol": ("espanhol", "es"),
    "frances": ("francês", "fr"),
    "alemao": ("alemão", "de"),
    "italiano": ("italiano", "it"),
    "japones": ("japonês", "ja"),
    "chines": ("chinês", "zh"),
    "mandarim": ("mandarim", "zh"),
    "portugues": ("português", "pt"),
}


@dataclass(frozen=True)
class TimeSpan:
    """Um trecho de tempo dito no pedido, em segundos: o intervalo, os primeiros, os últimos ou a partir de."""

    kind: TimeKind
    first: float
    second: float | None = None

    def label(self) -> str:
        if self.kind == "range":
            return f"de {_seconds(self.first)} a {_seconds(self.second or 0)}"
        if self.kind == "first":
            return f"os primeiros {_seconds(self.first)}"
        if self.kind == "last":
            return f"os últimos {_seconds(self.first)}"
        return f"a partir de {_seconds(self.first)}"


@dataclass(frozen=True)
class RequestFacts:
    projects: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    spans: tuple[TimeSpan, ...] = ()
    quoted: tuple[str, ...] = ()
    languages: tuple[tuple[str, str], ...] = ()
    dates: tuple[str, ...] = ()
    couples: tuple[str, ...] = ()
    suggested_name: str | None = None
    notes: tuple[str, ...] = field(default=())

    @property
    def empty(self) -> bool:
        return not any(
            (
                self.projects,
                self.files,
                self.spans,
                self.quoted,
                self.languages,
                self.dates,
                self.couples,
                self.notes,
            )
        )


def _seconds(value: float) -> str:
    text = f"{value:g}"
    return f"{text} s"


def parse_time(text: str, unit: str | None = None) -> float:
    """`0:12` vira 12 s e `1:05` 65 s; sem os dois pontos, o número vale segundos (ou minutos se a unidade disser)."""
    if ":" in text:
        minutes, _, rest = text.partition(":")
        return int(minutes) * 60 + float(rest.replace(",", "."))
    value = float(text.replace(",", "."))
    return value * 60 if unit and unit.startswith("min") else value


def find_spans(request: str) -> tuple[TimeSpan, ...]:
    """Os trechos de tempo do pedido. Um par de números sem unidade de tempo ("de 0 a 95 mg") não é um trecho."""
    text = normalize(request)
    spans: list[TimeSpan] = []
    for match in _RANGE.finditer(text):
        start, start_unit, end, end_unit = match.groups()
        clocks = ":" in start and ":" in end
        if not (end_unit or clocks):
            continue
        unit = end_unit or start_unit
        spans.append(
            TimeSpan("range", parse_time(start, start_unit or unit), parse_time(end, end_unit or unit))
        )
    singles: tuple[tuple[re.Pattern[str], TimeKind], ...] = (
        (_FIRST, "first"),
        (_LAST, "last"),
        (_FROM, "from"),
    )
    for pattern, kind in singles:
        for match in pattern.finditer(text):
            spans.append(TimeSpan(kind, parse_time(match.group(1), match.group(2))))
    return tuple(spans)


def find_files(request: str) -> tuple[str, ...]:
    """Os arquivos e pastas citados: caminhos com unidade (`C:/...`) e nomes soltos com extensão de mídia."""
    paths = [match.group(0).rstrip(_TRAILING) for match in _DRIVE_PATH.finditer(request)]
    bare = [
        match.group(0).rstrip(_TRAILING)
        for match in _MEDIA_NAME.finditer(request)
        if not any(match.group(0) in path for path in paths)
    ]
    return tuple(dict.fromkeys([*paths, *bare]))


def find_projects(request: str, known: Sequence[str]) -> tuple[str, ...]:
    """Os nomes de projeto existentes que o pedido cita (sem diferenciar caixa nem acento, o mais longo primeiro)."""
    text = normalize(request)
    found = []
    for name in sorted(known, key=len, reverse=True):
        plain = normalize(name)
        if plain and re.search(rf"(?<![\w-]){re.escape(plain)}(?![\w-])", text):
            found.append(name)
    return tuple(found)


def find_quoted(request: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(next(group for group in match.groups() if group) for match in _QUOTED.finditer(request))
    )


def find_languages(request: str) -> tuple[tuple[str, str], ...]:
    words = set(re.findall(r"[a-z]+", normalize(request)))
    return tuple(info for key, info in LANGUAGES.items() if key in words)


def slug(text: str) -> str:
    """Minúsculas, sem acento, palavras separadas por hífen: o jeito dos nomes de projeto do DMaker."""
    return re.sub(r"[^a-z0-9]+", "-", normalize(text)).strip("-")


def extract_facts(request: str, known_projects: Sequence[str] = ()) -> RequestFacts:
    """Tudo o que o pedido já diz, mais as observações que evitam as perguntas mais comuns do modelo."""
    files = find_files(request)
    projects = find_projects(request, known_projects)
    spans = find_spans(request)
    notes: list[str] = []
    if files and not spans:
        notes.append("Sem trecho de tempo citado: use o arquivo inteiro.")
    suggested = None
    if files and not projects:
        suggested = slug(os.path.splitext(os.path.basename(files[0].replace("\\", "/")))[0]) or None
    couples = tuple(f"{a} & {b}" for a, b in _COUPLE.findall(request))
    return RequestFacts(
        projects=projects,
        files=files,
        spans=spans,
        quoted=find_quoted(request),
        languages=find_languages(request),
        dates=tuple(dict.fromkeys(_DATE.findall(request))),
        couples=couples,
        suggested_name=suggested,
        notes=tuple(notes),
    )


def render_facts(facts: RequestFacts) -> str:
    """O bloco que vai depois do pedido, ou texto vazio quando não há nada a dizer."""
    if facts.empty:
        return ""
    lines = ["O que o pedido já diz (use estes dados, não pergunte de novo):"]
    lines += [f"- Projeto que já existe: {name} (use este nome)." for name in facts.projects]
    lines += [f"- Arquivo ou pasta: {path}" for path in facts.files]
    lines += [f"- Trecho de tempo: {span.label()}." for span in facts.spans]
    lines += [f"- {note}" for note in facts.notes]
    if facts.quoted:
        lines.append("- Entre aspas: " + ", ".join(f'"{text}"' for text in facts.quoted))
    lines += [f"- Idioma: {name} ({code})." for name, code in facts.languages]
    lines += [f"- Data: {date}." for date in facts.dates]
    lines += [f"- Casal: {couple}." for couple in facts.couples]
    if facts.suggested_name:
        lines.append(f'- Nenhum projeto citado: se precisar criar um, chame-o "{facts.suggested_name}".')
    return "\n".join(lines)


def with_facts(request: str, known_projects: Sequence[str] = ()) -> str:
    """O pedido seguido do bloco de dados que ele já traz (o pedido sozinho quando não há nada a acrescentar)."""
    block = render_facts(extract_facts(request, known_projects))
    return f"{request}\n\n{block}" if block else request
