"""Planilha de lote, parte pura: leitura do texto (CSV, JSON), casamento das colunas com os parâmetros do
modelo e o valor de cada célula no tipo certo. Nada aqui toca o disco."""

from __future__ import annotations

import os

import pytest

from dmaker.domain.batch_sheet import (
    BOM,
    CellError,
    Issue,
    SheetError,
    SheetRow,
    coerce_cell,
    detect_delimiter,
    flatten_strings,
    match_columns,
    normalize_name,
    parse_csv,
    parse_json_rows,
    pick_name_column,
    row_params,
    sheet_from_grid,
    slugify,
    unique_slugs,
)
from dmaker.domain.templates import TemplateParam


def param(kind: str = "text", required: bool = False, default=None) -> TemplateParam:
    return TemplateParam(name="x", type=kind, required=required, default=default)


PARAMS = {
    "titulo": param("text", required=True),
    "imagem": param("path", required=True),
    "cta_final": param("text", default="Agende agora"),
    "duracao": param("number", default=4),
    "legendas": param("bool", default=True),
    "prints": param("paths"),
    "assuntos": param("list"),
}


# ---------- nomes ----------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Título", "titulo"),
        ("CTA final", "ctafinal"),
        ("cta_final", "ctafinal"),
        ("  Cta-Final ", "ctafinal"),
        ("Descrição do vídeo", "descricaodovideo"),
    ],
)
def test_normalize_name_ignores_case_accent_space_hyphen_and_underscore(text, expected):
    assert normalize_name(text) == expected


def test_slugify_gives_a_safe_file_name_and_never_an_empty_one():
    assert slugify("Procedimento da Semana: Botox!") == "procedimento-da-semana-botox"
    assert slugify("Ação número 3") == "acao-numero-3"
    assert slugify("???", "video-02") == "video-02"
    assert len(slugify("a" * 200)) <= 60


def test_unique_slugs_numbers_repeated_names_and_avoids_taken_ones():
    assert unique_slugs(["a", "b", "a", "a"]) == ["a", "b", "a-2", "a-3"]
    assert unique_slugs(["a", "b"], taken={"a"}) == ["a-2", "b"]


# ---------- CSV ----------


def test_detect_delimiter_picks_the_most_frequent_outside_quotes():
    assert detect_delimiter("titulo;imagem;cta\n") == ";"
    assert detect_delimiter("titulo,imagem,cta\n") == ","
    assert detect_delimiter("titulo\timagem\n") == "\t"
    assert detect_delimiter('"a,b";c;d\n') == ";"  # a vírgula entre aspas não conta
    assert (
        detect_delimiter("titulo\nUm, dois\n") not in ";,\t"
    )  # coluna só: vírgula do texto não parte a linha


def test_parse_csv_reads_semicolon_with_bom_and_accents():
    sheet = parse_csv(f"{BOM}Título;Imagem\nDica um;fotos/1.png\nDica dois;fotos/2.png\n")
    assert sheet.headers == ["Título", "Imagem"]
    assert [row.cells for row in sheet.rows] == [
        {"Título": "Dica um", "Imagem": "fotos/1.png"},
        {"Título": "Dica dois", "Imagem": "fotos/2.png"},
    ]
    assert [row.line for row in sheet.rows] == [2, 3]


def test_parse_csv_reads_comma_and_keeps_commas_inside_quotes():
    sheet = parse_csv('titulo,texto\n"Oi, mundo","Linha um\nlinha dois"\nTchau,fim\n')
    assert sheet.rows[0].cells == {"titulo": "Oi, mundo", "texto": "Linha um\nlinha dois"}
    # a célula com quebra ocupa as linhas 2 e 3 do arquivo: a próxima linha de dados é a 4
    assert [row.line for row in sheet.rows] == [2, 4]


def test_parse_csv_skips_blank_lines_but_keeps_the_real_line_numbers():
    sheet = parse_csv("titulo;imagem\n\nA;a.png\n;\n\nB;b.png\n")
    assert [(row.line, row.cells["titulo"]) for row in sheet.rows] == [(3, "A"), (6, "B")]


def test_parse_csv_pads_short_rows_and_drops_unnamed_columns():
    sheet = parse_csv("titulo;imagem;\nA\n")
    assert sheet.headers == ["titulo", "imagem"]
    assert sheet.rows[0].cells == {"titulo": "A", "imagem": ""}


def test_parse_csv_of_one_column_keeps_commas_in_the_text():
    sheet = parse_csv("titulo\nOlá, tudo bem?\n")
    assert sheet.rows[0].cells == {"titulo": "Olá, tudo bem?"}


def test_sheet_from_grid_accepts_spreadsheet_values_and_takes_the_first_written_row_as_header():
    sheet = sheet_from_grid(
        [(1, [None, None]), (2, ["titulo", "duracao"]), (3, ["A", 4.0]), (4, [None, None]), (5, ["B", 5])]
    )
    assert sheet.headers == ["titulo", "duracao"]
    assert [(row.line, row.cells) for row in sheet.rows] == [
        (3, {"titulo": "A", "duracao": 4.0}),
        (5, {"titulo": "B", "duracao": 5}),
    ]


# ---------- JSON ----------


def test_parse_json_rows_reads_a_list_of_objects_with_the_item_position_as_line():
    sheet = parse_json_rows('[{"titulo": "A", "imagem": "a.png"}, {"titulo": "B", "extra": 1}]')
    assert sheet.headers == ["titulo", "imagem", "extra"]
    assert [row.line for row in sheet.rows] == [1, 2]
    assert sheet.rows[1].cells == {"titulo": "B", "extra": 1}


def test_parse_json_rows_accepts_an_object_holding_the_only_list():
    assert len(parse_json_rows('{"videos": [{"titulo": "A"}, {"titulo": "B"}]}').rows) == 2


@pytest.mark.parametrize("text", ["[1, 2]", '{"a": 1}', '"texto"', "[{"])
def test_parse_json_rows_rejects_anything_but_a_list_of_objects(text):
    with pytest.raises(SheetError):
        parse_json_rows(text)


# ---------- casamento das colunas ----------


def test_match_columns_matches_without_case_accent_or_space():
    match = match_columns(["Título", "IMAGEM", "CTA Final", "Observações"], PARAMS)
    assert match.columns == {"titulo": "Título", "imagem": "IMAGEM", "cta_final": "CTA Final"}
    assert match.unused == ["Observações"]
    assert match.missing == []
    assert [i.level for i in match.issues] == ["aviso"]
    assert "Observações" in match.issues[0].field and "ignorada" in match.issues[0].message


def test_match_columns_reports_the_required_column_that_is_missing():
    match = match_columns(["titulo"], PARAMS)
    assert match.missing == ["imagem"]
    assert any(i.level == "erro" and i.field == "imagem" for i in match.issues)


def test_match_columns_reports_two_columns_for_the_same_field():
    match = match_columns(["Título", "titulo", "imagem"], PARAMS)
    conflict = [i for i in match.issues if i.level == "erro"]
    assert len(conflict) == 1 and "Título" in conflict[0].message and "titulo" in conflict[0].message


def test_pick_name_column_uses_the_requested_one_a_hint_or_the_first():
    assert pick_name_column(["Imagem", "Título"], "titulo") == "Título"
    assert pick_name_column(["imagem", "Nome do arquivo", "titulo"], None) == "Nome do arquivo"
    assert pick_name_column(["imagem", "titulo"], None) == "titulo"
    assert pick_name_column(["foto", "legenda"], None) == "foto"
    assert pick_name_column([], None) is None
    with pytest.raises(SheetError, match="não existe na planilha"):
        pick_name_column(["imagem"], "nome")


# ---------- valor das células ----------


def test_text_cells_are_trimmed_and_numbers_become_text():
    assert coerce_cell("  Olá  ", param("text")) == "Olá"
    assert coerce_cell(2024, param("text")) == "2024"
    assert coerce_cell(3.0, param("text")) == "3"
    assert coerce_cell(True, param("text")) == "sim"
    assert coerce_cell("   ", param("text")) is None and coerce_cell(None, param("text")) is None
    with pytest.raises(CellError):
        coerce_cell(["a"], param("text"))


def test_number_cells_accept_the_brazilian_decimal_comma():
    assert coerce_cell("4", param("number")) == 4
    assert coerce_cell("3,5", param("number")) == 3.5
    assert coerce_cell("1.234,5", param("number")) == 1234.5
    assert coerce_cell("2.5", param("number")) == 2.5
    assert coerce_cell(7, param("number")) == 7
    with pytest.raises(CellError, match="não é um número"):
        coerce_cell("quatro", param("number"))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("sim", True),
        ("Sim", True),
        ("1", True),
        ("true", True),
        ("não", False),
        ("0", False),
        ("falso", False),
    ],
)
def test_bool_cells_accept_portuguese_and_english_words(raw, expected):
    assert coerce_cell(raw, param("bool")) is expected


def test_bool_cell_that_is_neither_yes_nor_no_is_an_error():
    with pytest.raises(CellError, match="sim nem não"):
        coerce_cell("talvez", param("bool"))


def test_relative_paths_start_at_the_sheet_folder_and_absolute_ones_stay():
    base = os.path.join(os.sep, "planilhas", "semana")
    assert coerce_cell("fotos/1.png", param("path"), base) == os.path.normpath(
        os.path.join(base, "fotos/1.png")
    )
    absolute = os.path.abspath(os.path.join("x", "y.png"))
    assert coerce_cell(absolute, param("path"), base) == absolute
    assert coerce_cell("fotos/1.png", param("path"), None) == "fotos/1.png"


def test_list_cells_split_on_pipe_newline_or_comma_and_read_json():
    kind = param("paths")
    assert coerce_cell("a.png|b.png", kind) == ["a.png", "b.png"]
    assert coerce_cell("a.png\nb.png", kind) == ["a.png", "b.png"]
    assert coerce_cell("a.png, b.png", kind) == ["a.png", "b.png"]
    assert coerce_cell("a.png", kind) == ["a.png"]
    assert coerce_cell('["a.png", "b.png"]', kind) == ["a.png", "b.png"]
    assert coerce_cell(["a.png"], kind) == ["a.png"]
    with pytest.raises(CellError, match="JSON inválida"):
        coerce_cell("[1, 2", param("list"))


def test_json_list_cell_resolves_media_paths_inside_objects_from_the_sheet_folder():
    base = os.path.join(os.sep, "pasta")
    value = coerce_cell('[{"fim": 20, "imagem": "fotos/a.png", "fundo": "escuro"}]', param("list"), base)
    assert value[0]["fim"] == 20 and value[0]["fundo"] == "escuro"
    assert value[0]["imagem"] == os.path.normpath(os.path.join(base, "fotos/a.png"))


def test_flatten_strings_walks_lists_and_objects():
    assert sorted(flatten_strings([{"a": "x", "b": ["y", 3]}, "z"])) == ["x", "y", "z"]


# ---------- parâmetros de uma linha ----------


def row(line: int = 2, **cells) -> SheetRow:
    return SheetRow(line, cells)


def test_row_params_fills_typed_values_and_leaves_empty_cells_to_the_default():
    match = match_columns(["Título", "imagem", "duração", "cta final"], PARAMS)
    values, issues = row_params(
        row(**{"Título": "Dica", "imagem": "a.png", "duração": "5", "cta final": ""}), match, PARAMS
    )
    assert issues == []
    assert values == {"titulo": "Dica", "imagem": "a.png"} | {"duracao": 5}
    assert "cta_final" not in values  # vazio: vale o padrão do modelo


def test_row_params_points_at_the_empty_required_field_by_its_column_name():
    match = match_columns(["Título", "imagem"], PARAMS)
    _, issues = row_params(row(**{"Título": "", "imagem": "a.png"}), match, PARAMS)
    assert issues == [Issue(2, "Título", "campo obrigatório vazio")]


def test_row_params_reports_a_required_field_whose_column_does_not_exist():
    match = match_columns(["titulo"], PARAMS)
    _, issues = row_params(row(titulo="A"), match, PARAMS)
    assert [(i.field, i.message) for i in issues] == [("imagem", 'falta a coluna "imagem"')]


def test_row_params_reports_every_unreadable_value_with_its_column():
    match = match_columns(["titulo", "imagem", "duracao", "legendas"], PARAMS)
    values, issues = row_params(
        row(titulo="A", imagem="a.png", duracao="muito", legendas="quem sabe"), match, PARAMS
    )
    assert values == {"titulo": "A", "imagem": "a.png"}
    assert {i.field for i in issues} == {"duracao", "legendas"} and all(i.line == 2 for i in issues)


def test_issue_describe_names_line_and_column():
    assert (
        Issue(4, "titulo", "campo obrigatório vazio").describe()
        == "linha 4, coluna titulo: campo obrigatório vazio"
    )
    assert Issue(None, None, "sem linhas").describe() == "planilha: sem linhas"
