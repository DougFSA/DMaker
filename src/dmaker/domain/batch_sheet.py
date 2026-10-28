"""Planilha de lote: o texto de um CSV ou JSON vira linhas, e as colunas casam com os parâmetros de um modelo.

Tudo aqui é puro: entra texto e dicionários, saem dados. Nada toca o disco (a leitura do arquivo, inclusive
do XLSX, fica em `pipeline/batch_files.py`), então cada regra de casamento tem teste direto.

Uma planilha tem uma linha por vídeo e uma coluna por parâmetro do modelo (`titulo`, `imagem`, `narracao`...).
O nome da coluna casa com o do parâmetro sem diferenciar maiúscula, acento, espaço, hífen ou sublinhado
("Título", "CTA final" e "cta_final" casam com `titulo` e `cta_final`). Célula vazia usa o valor padrão do
modelo; parâmetro obrigatório sem valor, número ilegível e lista malformada viram problema daquela linha.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import unicodedata
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from .templates import TemplateParam

Level = Literal["erro", "aviso"]

DELIMITERS = (";", ",", "\t")
# planilha de uma coluna só: nenhum separador de verdade, então um caractere que não aparece em texto algum
# impede que uma vírgula dentro do texto da célula parta a linha ao meio
NO_DELIMITER = "\x1f"
BOM = chr(0xFEFF)  # marca de ordem de byte que o Excel põe no começo de um CSV em UTF-8
LIST_SEPARATORS = ("|", "\n", ",")
TRUE_WORDS = frozenset({"1", "true", "sim", "s", "yes", "y", "verdadeiro", "x"})
FALSE_WORDS = frozenset({"0", "false", "nao", "n", "no", "falso"})
# colunas que costumam trazer o nome do vídeo, da mais específica para a mais genérica
NAME_COLUMN_HINTS = ("nomedoarquivo", "arquivo", "nomedovideo", "nome", "name", "slug", "titulo", "title")
MAX_SLUG_CHARS = 60
# extensões que identificam um caminho de mídia dentro de um JSON de célula (ex.: a imagem de cada assunto)
_MEDIA_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".mp4",
    ".mov",
    ".mkv",
    ".m4v",
    ".avi",
    ".webm",
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
)


class SheetError(ValueError):
    """A planilha não pôde ser lida ou não tem a forma esperada (JSON que não é lista, coluna do nome ausente)."""


class CellError(ValueError):
    """O valor de uma célula não serve para o tipo do parâmetro (número ilegível, lista malformada)."""


@dataclass(frozen=True)
class Issue:
    """Um problema (ou aviso) achado antes de renderizar: onde está e o que fazer."""

    line: int | None  # linha da planilha; None quando o problema é da planilha inteira
    field: str | None  # coluna da planilha, no nome em que a pessoa a escreveu
    message: str
    level: Level = "erro"

    def describe(self) -> str:
        where = "planilha" if self.line is None else f"linha {self.line}"
        if self.field:
            where += f", coluna {self.field}"
        return f"{where}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {"line": self.line, "field": self.field, "message": self.message, "level": self.level}


@dataclass(frozen=True)
class SheetRow:
    line: int  # onde a pessoa acha a linha: linha do arquivo (1 é o cabeçalho) ou posição no JSON
    cells: dict[str, Any]


@dataclass(frozen=True)
class Sheet:
    headers: list[str]
    rows: list[SheetRow]


@dataclass(frozen=True)
class ColumnMatch:
    """Como as colunas da planilha casam com os parâmetros do modelo."""

    columns: dict[str, str]  # parâmetro do modelo -> cabeçalho da planilha
    unused: list[str]  # colunas que não casam com parâmetro algum (ignoradas)
    missing: list[str]  # parâmetros obrigatórios sem coluna
    issues: list[Issue] = field(default_factory=list)

    def header_of(self, param: str) -> str:
        """Nome da coluna do parâmetro, ou o próprio nome do parâmetro quando a planilha não o traz."""
        return self.columns.get(param, param)


# ---------- leitura do texto ----------


def _count_outside_quotes(line: str, char: str) -> int:
    count, inside = 0, False
    for current in line:
        if current == '"':
            inside = not inside
        elif current == char and not inside:
            count += 1
    return count


def detect_delimiter(text: str) -> str:
    """Separador do CSV pelo cabeçalho: o Excel brasileiro exporta com ponto e vírgula, os demais com vírgula."""
    header = next((line for line in text.splitlines() if line.strip()), "")
    counts = {delimiter: _count_outside_quotes(header, delimiter) for delimiter in DELIMITERS}
    best = max(DELIMITERS, key=lambda delimiter: counts[delimiter])
    return best if counts[best] else NO_DELIMITER


def sheet_from_grid(grid: Iterable[tuple[int, Sequence[Any]]]) -> Sheet:
    """Planilha a partir de uma grade de (número da linha, células): a primeira linha com algo escrito é o
    cabeçalho e as linhas em branco depois dela são ignoradas, mas contam no número que o relatório mostra."""
    headers: list[str] = []
    rows: list[SheetRow] = []
    for line, record in grid:
        if all(_is_blank(cell) for cell in record):
            continue
        if not headers:
            headers = ["" if cell is None else str(cell).strip() for cell in record]
            continue
        padded = [*record, *[""] * (len(headers) - len(record))]
        rows.append(SheetRow(line, {h: cell for h, cell in zip(headers, padded, strict=False) if h}))
    return Sheet([header for header in headers if header], rows)


def parse_csv(text: str) -> Sheet:
    """Linhas de um CSV (UTF-8 com ou sem BOM; separador `;`, `,` ou tabulação)."""
    text = text.lstrip(BOM)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=detect_delimiter(text))
    grid: list[tuple[int, list[str]]] = []
    previous_end = 0
    for (
        record
    ) in reader:  # `line_num` é a última linha física do registro: uma célula com quebra ocupa várias
        grid.append((previous_end + 1, record))
        previous_end = reader.line_num
    return sheet_from_grid(grid)


def parse_json_rows(text: str) -> Sheet:
    """Linhas de um JSON: uma lista de objetos (ou um objeto cuja única lista de objetos são os vídeos).
    A linha é a posição do objeto na lista, começando em 1."""
    try:
        data = json.loads(text.lstrip(BOM))
    except json.JSONDecodeError as exc:
        raise SheetError(f"JSON inválido na linha {exc.lineno}, coluna {exc.colno}: {exc.msg}") from exc
    if isinstance(data, dict):
        lists = [value for value in data.values() if isinstance(value, list)]
        if len(lists) == 1:
            data = lists[0]
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise SheetError("O JSON precisa ser uma lista de objetos, um por vídeo.")
    headers: list[str] = []
    for item in data:
        headers.extend(key for key in item if key not in headers)
    return Sheet(headers, [SheetRow(position, dict(item)) for position, item in enumerate(data, start=1)])


# ---------- casamento das colunas ----------


def normalize_name(text: str) -> str:
    """Nome de coluna ou de parâmetro sem acento, maiúscula, espaço, hífen ou sublinhado."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", folded.lower())


def match_columns(headers: Sequence[str], params: Mapping[str, TemplateParam]) -> ColumnMatch:
    """Casa cada parâmetro do modelo com a coluna de mesmo nome (normalizado). Aponta o que impede qualquer
    linha de dar certo: coluna obrigatória ausente e duas colunas para o mesmo parâmetro."""
    by_normalized: dict[str, list[str]] = {}
    for header in headers:
        by_normalized.setdefault(normalize_name(header), []).append(header)
    columns: dict[str, str] = {}
    issues: list[Issue] = []
    for name in params:
        candidates = by_normalized.get(normalize_name(name), [])
        if candidates:
            columns[name] = candidates[0]
        if len(candidates) > 1:
            listed = " e ".join(f'"{header}"' for header in candidates)
            issues.append(Issue(None, candidates[0], f'as colunas {listed} casam com o mesmo campo "{name}"'))
    matched = set(columns.values())
    unused = [header for header in headers if header not in matched]
    missing = [name for name, param in params.items() if param.required and name not in columns]
    for name in missing:
        issues.append(Issue(None, name, f'falta a coluna "{name}" (campo obrigatório do modelo)'))
    for header in unused:
        issues.append(Issue(None, header, "não casa com nenhum campo do modelo e será ignorada", "aviso"))
    return ColumnMatch(columns, unused, missing, issues)


def pick_name_column(headers: Sequence[str], requested: str | None) -> str | None:
    """Coluna cujo texto dá nome ao arquivo de cada vídeo: a pedida (casando sem acento nem maiúscula) ou a
    que costuma servir (`nome`, `arquivo`, `titulo`...), por último a primeira da planilha."""
    by_normalized = {normalize_name(header): header for header in reversed(headers)}
    if requested:
        found = by_normalized.get(normalize_name(requested))
        if found is None:
            known = ", ".join(headers) or "nenhuma"
            raise SheetError(f'A coluna do nome "{requested}" não existe na planilha (colunas: {known}).')
        return found
    for hint in NAME_COLUMN_HINTS:
        if hint in by_normalized:
            return by_normalized[hint]
    return headers[0] if headers else None


# ---------- valor das células ----------


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return isinstance(value, (list, dict)) and not value


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "sim" if value else "não"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y" if not (value.hour or value.minute) else "%d/%m/%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, (list, dict)):
        raise CellError("a célula traz uma lista ou um objeto, e o campo é texto")
    return str(value)


def _as_path(text: str, base_dir: str | None) -> str:
    """Caminho relativo parte da pasta da planilha; o absoluto fica como está. Não confere se existe."""
    expanded = os.path.expanduser(text)
    if os.path.isabs(expanded) or not base_dir:
        return expanded
    return os.path.normpath(os.path.join(base_dir, expanded))


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return [value]
    text = value.strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CellError(f"lista em JSON inválida ({exc.msg})") from exc
        if not isinstance(parsed, list):
            raise CellError("lista em JSON inválida (esperava colchetes)")
        return parsed
    for separator in LIST_SEPARATORS:
        if separator in text:
            return [item.strip() for item in text.split(separator) if item.strip()]
    return [text]


def _as_number(value: Any) -> int | float:
    if isinstance(value, bool):
        raise CellError(f'"{_as_text(value)}" não é um número')
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if "," in text:  # 1.234,5 ou 3,5: o Excel brasileiro escreve a vírgula como separador decimal
        text = text.replace(".", "").replace(",", ".")
    try:
        number = float(text)
    except ValueError as exc:
        raise CellError(f'"{value}" não é um número') from exc
    return int(number) if number.is_integer() and "." not in text else number


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    word = normalize_name(str(value))
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise CellError(f'"{value}" não é sim nem não (use sim, não, 1 ou 0)')


def _resolve_nested_paths(value: Any, base_dir: str | None) -> Any:
    """Dentro de uma lista vinda de JSON, texto que é só o nome de uma mídia relativa parte da pasta da planilha."""
    if isinstance(value, list):
        return [_resolve_nested_paths(item, base_dir) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_nested_paths(item, base_dir) for key, item in value.items()}
    if isinstance(value, str) and base_dir and value.lower().endswith(_MEDIA_SUFFIXES):
        return _as_path(value.strip(), base_dir)
    return value


def coerce_cell(value: Any, param: TemplateParam, base_dir: str | None = None) -> Any:
    """Valor da célula no tipo do parâmetro do modelo. None quando a célula está vazia (vale o padrão do
    modelo); CellError quando o conteúdo não serve para o tipo."""
    if _is_blank(value):
        return None
    kind = param.type
    if kind == "text":
        return _as_text(value)
    if kind in ("path", "dir"):
        return _as_path(_as_text(value), base_dir)
    if kind == "paths":
        return [_as_path(_as_text(item), base_dir) for item in _as_list(value)]
    if kind == "number":
        return _as_number(value)
    if kind == "bool":
        return _as_bool(value)
    return _resolve_nested_paths(_as_list(value), base_dir)


def row_params(
    row: SheetRow, match: ColumnMatch, params: Mapping[str, TemplateParam], base_dir: str | None = None
) -> tuple[dict[str, Any], list[Issue]]:
    """Parâmetros do modelo preenchidos por uma linha, e os problemas dela. Célula vazia não entra (vale o
    padrão do modelo); obrigatório vazio e valor que não serve ao tipo viram problema da linha."""
    values: dict[str, Any] = {}
    issues: list[Issue] = []
    for name, param in params.items():
        header = match.columns.get(name)
        try:
            value = coerce_cell(row.cells.get(header) if header else None, param, base_dir)
        except CellError as exc:
            issues.append(Issue(row.line, match.header_of(name), str(exc)))
            continue
        if value is None:
            if param.required and header:
                issues.append(Issue(row.line, header, "campo obrigatório vazio"))
            elif param.required:
                issues.append(Issue(row.line, name, f'falta a coluna "{name}"'))
            continue
        values[name] = value
    return values, issues


# ---------- nomes de arquivo ----------


def slugify(text: str, fallback: str = "video") -> str:
    """Texto livre vira trecho de nome de arquivo: sem acento, minúsculas, hifens; nunca vazio."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")[:MAX_SLUG_CHARS].strip("-")
    return slug or fallback


def unique_slugs(candidates: Sequence[str], taken: Collection[str] = ()) -> list[str]:
    """Os nomes na mesma ordem, sem repetição entre si nem com `taken`: o repetido ganha -2, -3..."""
    used = set(taken)
    result: list[str] = []
    for candidate in candidates:
        slug, number = candidate, 1
        while slug in used:
            number += 1
            slug = f"{candidate}-{number}"
        used.add(slug)
        result.append(slug)
    return result


def flatten_strings(value: Any) -> Iterator[str]:
    """Todos os textos dentro de um valor (texto, lista, objeto), para achar de que coluna veio um trecho."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from flatten_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from flatten_strings(item)
