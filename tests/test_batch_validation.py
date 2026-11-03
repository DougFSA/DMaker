"""Validação do lote antes de renderizar: cada problema da planilha sai com linha, coluna e motivo, sem ffmpeg
(o probe e a checagem de arquivo entram falsos) e sem gravar nada."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmaker.domain.batch_sheet import parse_csv, parse_json_rows
from dmaker.domain.templates import Template, load_template
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.batch_validation import media_references, validate_sheet

LONG_WORD = "Palavragiganteinquebravelquenaocabenalarguradoquadrodopreset"


def fake_prober(path: Path) -> MediaInfo:
    return MediaInfo(path, 0.0, 1080, 1920, 0.0, True, False, True)


def make_template(tmp_path: Path, overlays: list[dict] | None = None, params: dict | None = None) -> Template:
    """Um modelo de story: uma imagem de fundo, o título como gancho e o texto como legenda."""
    body = {
        "params": params
        or {
            "titulo": {"description": "Gancho", "type": "text", "required": True},
            "texto": {"description": "Legenda", "type": "text", "default": "Texto padrão"},
            "imagem": {"description": "Fundo", "type": "path", "required": True},
        },
        "name": "story-teste",
        "output": {"preset": "instagram/stories"},
        "brand": "medlycare",
        "timeline": [{"type": "image", "src": "{{imagem}}", "duration": 6}],
        "overlays": overlays
        if overlays is not None
        else [
            {"type": "text", "text": "{{titulo}}", "role": "hook", "start": 0.3, "end": 6},
            {
                "type": "text",
                "text": "{{texto}}",
                "role": "subtitle",
                "position": "bottom",
                "start": 1,
                "end": 6,
            },
        ],
        "audio": {"normalize": "off"},
    }
    path = tmp_path / "story-teste.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return load_template(path)


def validate(template: Template, csv_text: str, **kwargs):
    """Valida o CSV com as imagens `1.png`, `2.png`, `3.png` e `ok.png` existindo (vazias: o probe é falso)."""
    folder = template.path.parent
    for name in ("1.png", "2.png", "3.png", "ok.png"):
        (folder / name).write_bytes(b"x")
    kwargs.setdefault("base_dir", str(folder))
    return validate_sheet(template, parse_csv(csv_text), prober=fake_prober, **kwargs)


def messages(row) -> list[str]:
    return [issue.message for issue in row.issues]


def test_a_good_sheet_builds_one_valid_spec_per_row_without_rendering(tmp_path):
    result = validate(make_template(tmp_path), "titulo;imagem\nDica um;1.png\nDica dois;2.png\n")

    assert result.ok and result.runnable and len(result.valid_rows) == 2
    first = result.rows[0]
    assert first.spec["timeline"][0]["src"].endswith("1.png")
    assert first.spec["overlays"][0]["text"] == "Dica um"
    assert result.name_column == "titulo" and [row.title for row in result.rows] == ["Dica um", "Dica dois"]


def test_a_missing_file_is_pointed_at_with_its_line_and_column(tmp_path):
    result = validate(make_template(tmp_path), "Título;Imagem\nUm;ok.png\nDois;falta.png\n")

    assert [row.valid for row in result.rows] == [True, False]
    issue = result.rows[1].errors[0]
    assert (issue.line, issue.field) == (3, "Imagem")
    assert "arquivo não encontrado" in issue.message and "falta.png" in issue.message
    assert not result.ok and result.runnable  # as outras linhas ainda podem seguir se a pessoa mandar


def test_an_empty_required_cell_and_an_unreadable_number_are_row_errors(tmp_path):
    params = {
        "titulo": {"type": "text", "required": True},
        "imagem": {"type": "path", "required": True},
        "duracao": {"type": "number", "default": 6},
    }
    overlays = [{"type": "text", "text": "{{titulo}}", "role": "hook", "start": 0, "end": 3}]
    template = make_template(tmp_path, overlays, params)
    result = validate(template, "titulo;imagem;duracao\n;1.png;5\nUm;2.png;muito\n")

    assert [(i.line, i.field, i.message) for i in result.rows[0].errors] == [
        (2, "titulo", "campo obrigatório vazio")
    ]
    assert [(i.line, i.field) for i in result.rows[1].errors] == [(3, "duracao")]


def test_a_dash_in_the_sheet_text_breaks_the_brand_rule_and_names_the_column(tmp_path):
    result = validate(
        make_template(tmp_path), "titulo;imagem;texto\nCom travessão — aqui;1.png;ok\nLimpo;2.png;ok\n"
    )

    issue = result.rows[0].errors[0]
    assert issue.field == "titulo" and "travessão" in issue.message and "MedlyCare" in issue.message
    assert result.rows[1].valid


def test_a_dash_is_found_even_when_the_file_is_missing(tmp_path):
    result = validate(make_template(tmp_path), "titulo;imagem\nCom – meia-risca;falta.png\n")

    found = messages(result.rows[0])
    assert any("não encontrado" in m for m in found) and any("travessão" in m for m in found)


def test_text_that_does_not_fit_is_an_error_on_its_column(tmp_path):
    result = validate(make_template(tmp_path), f"titulo;imagem\n{LONG_WORD};1.png\nCurto;2.png\n")

    wide = [i for i in result.rows[0].errors if "mais larga" in i.message]
    assert wide and wide[0].field == "titulo"
    assert result.rows[1].valid


def test_a_problem_of_the_template_itself_is_a_warning_shown_once_not_a_row_error(tmp_path):
    # o texto fixo do modelo encosta na borda inferior: nenhuma linha consegue consertar isso
    overlays = [
        {"type": "text", "text": "{{titulo}}", "role": "hook", "start": 0, "end": 3},
        {"type": "text", "text": "medlycare.com.br", "role": "cta", "start": 1, "end": 3, "y": 0.97},
    ]
    sheet = "titulo;imagem\nUm;1.png\nDois;falta.png\nTrês;3.png\n"
    result = validate(make_template(tmp_path, overlays), sheet)

    assert result.runnable and [row.valid for row in result.rows] == [True, False, True]
    assert [issue.level for issue in result.issues] == ["aviso"]
    assert "Vem do modelo" in result.issues[0].message
    assert all(issue.level == "erro" for row in result.rows for issue in row.issues)  # nenhum aviso repetido


def test_a_missing_file_is_reported_once_even_though_the_spec_points_at_it_too(tmp_path):
    result = validate(make_template(tmp_path), "titulo;imagem\nUm;falta.png\n")

    assert [issue.message.startswith("arquivo não encontrado") for issue in result.rows[0].issues] == [True]


def test_a_missing_required_column_blocks_the_whole_sheet(tmp_path):
    result = validate(make_template(tmp_path), "titulo\nUm\nDois\n")

    assert result.sheet_errors and "imagem" in result.sheet_errors[0].message
    assert not result.runnable and not result.ok
    assert all(row.errors for row in result.rows)


def test_an_unused_column_is_only_a_warning(tmp_path):
    result = validate(make_template(tmp_path), "titulo;imagem;observacoes\nUm;1.png;nada\n")

    assert result.ok
    warnings = [issue for issue in result.issues if issue.level == "aviso"]
    assert warnings and warnings[0].field == "observacoes"


def test_an_empty_sheet_is_a_sheet_error(tmp_path):
    result = validate(make_template(tmp_path), "titulo;imagem\n")

    assert (
        not result.ok and not result.runnable and result.issues[-1].message.startswith("a planilha não tem")
    )


def test_a_file_hidden_inside_a_json_list_is_found_from_the_spec_the_template_built(tmp_path):
    params = {
        "titulo": {"type": "text", "required": True},
        "itens": {"type": "list", "required": True, "example": [{"imagem": "a.png"}]},
    }
    overlays = [
        {"type": "text", "text": "{{titulo}}", "role": "hook", "start": 0, "end": 3},
        {
            "$for": "itens",
            "as": "item",
            "item": {"type": "image", "src": "{{item.imagem}}", "start": 0, "end": 3, "position": "center"},
        },
    ]
    template = make_template(tmp_path, overlays, params)
    template.body["timeline"] = [{"type": "card", "title": "{{titulo}}", "duration": 4}]
    sheet = parse_json_rows(
        '[{"titulo": "A", "itens": [{"imagem": "ok.png"}]}, {"titulo": "B", "itens": [{"imagem": "falta.png"}]}]'
    )
    (tmp_path / "ok.png").write_bytes(b"x")
    result = validate_sheet(template, sheet, base_dir=str(tmp_path), prober=fake_prober)

    assert [row.valid for row in result.rows] == [True, False]
    issue = result.rows[1].errors[0]
    assert issue.field == "itens" and "falta.png" in issue.message


def test_media_references_lists_segments_overlay_images_and_music_but_not_the_brand_logo(tmp_path):
    seal, music = tmp_path / "selo.png", tmp_path / "trilha.mp3"
    for path in (seal, music):
        path.write_bytes(b"x")
    overlays = [
        {"type": "image", "src": "logo:symbol", "position": "top-right", "width": 0.1},
        {"type": "image", "src": str(seal), "position": "top-left", "width": 0.1},
    ]
    template = make_template(tmp_path, overlays)
    template.body["audio"] = {"normalize": "off", "music": {"src": str(music)}}
    result = validate(template, "titulo;imagem\nUm;1.png\n")

    from dmaker.domain.spec import Project

    project = Project.model_validate(result.rows[0].spec)
    sources = [src for _where, src in media_references(project)]
    assert any(src.endswith("1.png") for src in sources)
    assert str(seal) in sources and str(music) in sources
    assert not any(src.startswith("logo") for src in sources)


def test_to_dict_and_text_carry_what_the_screen_and_the_cli_need(tmp_path):
    result = validate(make_template(tmp_path), "Título;Imagem\nUm;ok.png\nDois;falta.png\n")

    data = result.to_dict()
    assert data["total"] == 2 and data["valid"] == 1 and data["invalid"] == 1 and data["ok"] is False
    assert data["columns"]["matched"] == {"titulo": "Título", "imagem": "Imagem"}
    assert data["rows"][1]["issues"][0]["field"] == "Imagem"
    text = result.to_text()
    assert "1 válida(s)" in text and "linha 3, coluna Imagem" in text


def test_unknown_name_column_is_an_error_before_any_row_is_checked(tmp_path):
    from dmaker.domain.batch_sheet import SheetError

    with pytest.raises(SheetError):
        validate(make_template(tmp_path), "titulo;imagem\nUm;1.png\n", name_column="nome")
