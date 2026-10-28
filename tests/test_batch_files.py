"""Leitura da planilha do disco: CSV (UTF-8 e o ANSI do Excel brasileiro), JSON e XLSX."""

from __future__ import annotations

import sys
from datetime import date

import pytest

from dmaker.domain.batch_sheet import SheetError
from dmaker.pipeline.batch_files import XLSX_INSTALL_HINT, decode_text, read_sheet


def test_csv_in_utf8_with_bom_and_in_windows_1252_read_the_same_accents(tmp_path):
    text = "titulo;texto\nDica três;Atenção ao paciente\n"
    (tmp_path / "utf8.csv").write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    (tmp_path / "ansi.csv").write_bytes(text.encode("cp1252"))

    for name in ("utf8.csv", "ansi.csv"):
        sheet = read_sheet(tmp_path / name)
        assert sheet.rows[0].cells == {"titulo": "Dica três", "texto": "Atenção ao paciente"}, name


def test_decode_text_falls_back_to_windows_1252_when_it_is_not_utf8():
    assert decode_text("ação".encode("cp1252")) == "ação"
    assert decode_text(b"\xef\xbb\xbfola") == "ola"


def test_json_file_is_read_as_one_object_per_video(tmp_path):
    path = tmp_path / "videos.json"
    path.write_text('[{"titulo": "A", "duracao": 5}, {"titulo": "B"}]', encoding="utf-8")

    sheet = read_sheet(path)

    assert sheet.headers == ["titulo", "duracao"] and [row.line for row in sheet.rows] == [1, 2]


def test_xlsx_first_sheet_is_read_with_real_line_numbers_and_typed_cells(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Título", "Imagem", "Duração", "Data"])
    sheet.append(["Dica um", "fotos/1.png", 4, date(2026, 10, 28)])
    sheet.append([None, None, None, None])
    sheet.append(["Dica dois", "fotos/2.png", 5.5, None])
    other = workbook.create_sheet("Outra aba")
    other.append(["x"])
    path = tmp_path / "semana.xlsx"
    workbook.save(path)

    read = read_sheet(path)

    assert read.headers == ["Título", "Imagem", "Duração", "Data"]
    assert [row.line for row in read.rows] == [2, 4]
    assert read.rows[0].cells["Duração"] == 4 and read.rows[1].cells["Duração"] == 5.5
    assert read.rows[0].cells["Data"].year == 2026


def test_xlsx_without_openpyxl_says_how_to_install_the_extra(tmp_path, monkeypatch):
    path = tmp_path / "semana.xlsx"
    path.write_bytes(b"PK")
    monkeypatch.setitem(sys.modules, "openpyxl", None)  # o import falha como se o pacote não existisse

    with pytest.raises(SheetError) as raised:
        read_sheet(path)

    assert str(raised.value) == XLSX_INSTALL_HINT and "[lote]" in XLSX_INSTALL_HINT


def test_missing_file_old_xls_and_unknown_types_have_their_own_messages(tmp_path):
    with pytest.raises(FileNotFoundError, match="Planilha não encontrada"):
        read_sheet(tmp_path / "sumiu.csv")
    (tmp_path / "velha.xls").write_bytes(b"x")
    with pytest.raises(SheetError, match="salve a planilha como .xlsx ou .csv"):
        read_sheet(tmp_path / "velha.xls")
    (tmp_path / "x.pdf").write_bytes(b"x")
    with pytest.raises(SheetError, match="não suportado"):
        read_sheet(tmp_path / "x.pdf")
