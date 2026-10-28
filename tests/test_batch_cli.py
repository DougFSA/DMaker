"""Comandos `dmaker batch`: validar, rodar, retomar, pausar e ver o relatório, com o render falso."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from dmaker import config
from dmaker.cli import app
from dmaker.pipeline.batch import BatchService
from dmaker.pipeline.batch_state import BatchStore

from .batch_support import FakeRenderer, fake_prober, make_media, write_sheet

runner = CliRunner()


@pytest.fixture
def media(tmp_path):
    return make_media(tmp_path)


@pytest.fixture
def renderer() -> FakeRenderer:
    return FakeRenderer()


@pytest.fixture(autouse=True)
def service(monkeypatch, tmp_path, renderer) -> BatchService:
    built = BatchService(store=BatchStore(tmp_path / "lotes"), renderer=renderer, prober=fake_prober)
    monkeypatch.setattr("dmaker.cli._batch_service", lambda: built)
    return built


def batch(*args: str):
    return runner.invoke(app, ["batch", *args])


def test_validate_says_every_row_is_fine(media):
    result = batch("validate", "stories-medlycare", str(write_sheet(media)), "--name-column", "titulo")

    assert result.exit_code == 0, result.output
    assert "5 linha(s), 5 válida(s)" in result.output and "Planilha válida" in result.output


def test_validate_points_at_line_and_column_and_exits_with_error(media):
    sheet = write_sheet(media, broken={2: "nao-existe.png"})
    result = batch("validate", "stories-medlycare", str(sheet), "--name-column", "titulo")

    assert result.exit_code == 1
    assert "linha 3, coluna print: arquivo não encontrado" in result.output
    assert "Planilha válida" not in result.output


def test_validate_reports_a_dash_in_the_sheet_text(media):
    sheet = write_sheet(media, ["Dica um", "Dica — dois"])
    result = batch("validate", "stories-medlycare", str(sheet))

    assert (
        result.exit_code == 1 and "linha 3, coluna titulo" in result.output and "travessão" in result.output
    )


def test_run_creates_projects_renders_and_prints_the_report(media, renderer):
    result = batch(
        "run", "stories-medlycare", str(write_sheet(media)), "--name-column", "titulo", "--lote", "serie"
    )

    assert result.exit_code == 0, result.output
    assert "Lote criado: serie, 5 projeto(s)" in result.output
    assert "5 de 5 vídeo(s) pronto(s)" in result.output and "dica-um.mp4" in result.output
    assert len(renderer.calls) == 5
    assert (config.OUTPUT_DIR / "serie" / "relatorio.txt").exists()
    assert len(list(config.PROJECTS_DIR.glob("serie-*/spec.json"))) == 5


def test_run_refuses_a_sheet_with_a_bad_row_before_rendering_anything(media, renderer):
    sheet = write_sheet(media, broken={3: "nao-existe.png"})
    result = batch("run", "stories-medlycare", str(sheet), "--name-column", "titulo")

    assert result.exit_code == 1
    assert "linha 4, coluna print" in result.output and "skip_invalid" in result.output
    assert renderer.calls == [] and not config.PROJECTS_DIR.exists()


def test_run_skip_invalid_renders_the_other_rows_and_the_report_says_why_one_was_left_out(media, renderer):
    sheet = write_sheet(media, broken={3: "nao-existe.png"})
    result = batch("run", "stories-medlycare", str(sheet), "--name-column", "titulo", "--skip-invalid")

    assert result.exit_code == 0, result.output
    assert len(renderer.calls) == 4
    assert "1 linha(s) pulada(s)" in result.output and "[pulada] Dica três (linha 4)" in result.output
    assert "arquivo não encontrado" in result.output


def test_a_failed_video_makes_the_command_exit_with_error_and_shows_the_reason(media, renderer):
    def fail_third(project, rendered_so_far):
        if project.name.endswith("dica-tres"):
            raise RuntimeError("sem espaço em disco")

    renderer.before = fail_third
    result = batch("run", "stories-medlycare", str(write_sheet(media)), "--name-column", "titulo")

    assert result.exit_code == 1
    assert "4 de 5 vídeo(s) pronto(s), 1 falhou(aram)" in result.output
    assert "RuntimeError: sem espaço em disco" in result.output


def test_ctrl_c_keeps_what_came_out_and_resume_finishes_without_redoing_it(media, renderer):
    def interrupt_on_third(project, rendered_so_far):
        if rendered_so_far == 2:
            raise KeyboardInterrupt

    renderer.before = interrupt_on_third
    interrupted = batch(
        "run", "stories-medlycare", str(write_sheet(media)), "--name-column", "titulo", "--lote", "s"
    )
    assert interrupted.exit_code == 1 and "dmaker batch resume s" in interrupted.output
    assert len(renderer.calls) == 2

    renderer.before = None
    resumed = batch("resume", "s")

    assert resumed.exit_code == 0, resumed.output
    assert len(renderer.calls) == 5 and "5 de 5 vídeo(s) pronto(s)" in resumed.output


def test_resume_can_redo_chosen_videos(media, renderer):
    batch("run", "stories-medlycare", str(write_sheet(media, ["A", "B", "C"])), "--lote", "s")
    renderer.calls.clear()

    redone = batch("resume", "s", "--rows", "1,3", "--force")

    assert redone.exit_code == 0 and renderer.calls == ["s-a", "s-c"]
    assert batch("resume", "s", "--rows", "a").exit_code == 1


def test_pause_asks_the_running_batch_to_stop_and_status_lists_the_lotes(media, service):
    batch("run", "stories-medlycare", str(write_sheet(media, ["A", "B"])), "--lote", "s")

    paused = batch("pause", "s")
    assert paused.exit_code == 0 and "Pausa pedida" in paused.output and service.store.pause_requested("s")

    listed = batch("status")
    assert (
        "s" in listed.output
        and "stories-medlycare" in listed.output
        and "2 de 2 vídeo(s) pronto(s)" in listed.output
    )
    detail = batch("status", "s")
    assert "Lote s (modelo stories-medlycare" in detail.output and "a.mp4" in detail.output


def test_unknown_lote_and_unknown_template_are_plain_errors(media):
    assert batch("status", "nada").exit_code == 1
    assert "Não existe o lote" in batch("resume", "nada").output
    result = batch("validate", "nao-existe", str(write_sheet(media)))
    assert result.exit_code == 1 and "não encontrado" in result.output
    assert batch("validate", "stories-medlycare", str(media / "sumiu.csv")).exit_code == 1


def test_running_the_same_name_again_says_to_resume_or_use_another_name(media):
    sheet = write_sheet(media, ["A"])
    batch("run", "stories-medlycare", str(sheet), "--lote", "s")
    again = batch("run", "stories-medlycare", str(sheet), "--lote", "s")

    assert again.exit_code == 1 and "Já existe o lote" in again.output
