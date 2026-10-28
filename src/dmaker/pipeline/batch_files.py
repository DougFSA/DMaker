"""Leitura da planilha de lote do disco: CSV, JSON e XLSX viram a mesma `Sheet` da camada pura.

É a camada fina entre o arquivo e `domain/batch_sheet.py`, que faz o resto. O XLSX pede o `openpyxl`, de um
extra opcional (`pip install -e ".[lote]"`), importado só aqui e só na hora de abrir um .xlsx.
"""

from __future__ import annotations

from pathlib import Path

from ..domain.batch_sheet import Sheet, SheetError, parse_csv, parse_json_rows, sheet_from_grid

CSV_SUFFIXES = {".csv", ".tsv", ".txt"}
XLSX_SUFFIXES = {".xlsx", ".xlsm"}
SHEET_SUFFIXES = CSV_SUFFIXES | XLSX_SUFFIXES | {".json"}
XLSX_INSTALL_HINT = (
    'Ler planilha .xlsx precisa do pacote openpyxl. Instale com: pip install -e ".[lote]" '
    "(ou salve a planilha como .csv)."
)


def decode_text(data: bytes) -> str:
    """UTF-8 (com ou sem BOM). O "CSV" comum do Excel brasileiro é Windows-1252, por isso é o plano B."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def read_xlsx(path: Path) -> Sheet:
    """Primeira aba do arquivo, valores calculados das fórmulas; a primeira linha escrita é o cabeçalho."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise SheetError(XLSX_INSTALL_HINT) from exc
    workbook = load_workbook(path, data_only=True)
    try:
        worksheet = workbook.active
        grid = [(row[0].row, [cell.value for cell in row]) for row in worksheet.iter_rows() if row]
    finally:
        workbook.close()
    return sheet_from_grid(grid)


def read_sheet(path: Path | str) -> Sheet:
    """Lê a planilha pelo tipo do arquivo. Levanta FileNotFoundError se não existe e SheetError se não dá
    para entendê-la."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Planilha não encontrada: {path}")
    suffix = path.suffix.lower()
    if suffix in XLSX_SUFFIXES:
        return read_xlsx(path)
    if suffix == ".json":
        return parse_json_rows(decode_text(path.read_bytes()))
    if suffix in CSV_SUFFIXES:
        return parse_csv(decode_text(path.read_bytes()))
    if suffix == ".xls":
        raise SheetError("O formato .xls antigo não é lido: salve a planilha como .xlsx ou .csv.")
    raise SheetError(
        f"Tipo de planilha não suportado: {suffix or 'sem extensão'} (use .csv, .xlsx ou .json)."
    )
