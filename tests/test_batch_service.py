"""Serviço do lote: criar (um projeto por linha), rodar, pausar, retomar sem refazer o que já saiu, falhar por
linha e relatar. O render entra falso (conta as chamadas), e um teste usa a pipeline de verdade com
`RecordingRunner` e probe falso para provar que a retomada nem chega no runner."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dmaker import config
from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.pipeline.batch import (
    BatchBusyError,
    BatchExistsError,
    BatchInvalidError,
    BatchService,
    PipelineRenderer,
    project_signature,
)
from dmaker.pipeline.batch_state import BatchStore
from dmaker.pipeline.filelock import FileLock

from .batch_support import TITLES, FakeRenderer, fake_prober, make_media, write_sheet
from .test_pipeline_unit import touch_output


@pytest.fixture
def media(tmp_path: Path) -> Path:
    return make_media(tmp_path)


def make_service(tmp_path: Path, renderer=None) -> BatchService:
    return BatchService(
        store=BatchStore(tmp_path / "lotes"), renderer=renderer or FakeRenderer(), prober=fake_prober
    )


def create(service: BatchService, sheet: Path, **kwargs):
    return service.create("stories-medlycare", sheet, name_column="titulo", **kwargs)


# ---------- criar ----------


def test_create_saves_one_project_per_row_with_the_texts_and_images_of_that_row(tmp_path, media):
    service = make_service(tmp_path)
    batch = create(service, write_sheet(media))

    assert batch.name == "semana" and [row.slug for row in batch.rows] == [
        "dica-um",
        "dica-dois",
        "dica-tres",
        "dica-quatro",
        "dica-cinco",
    ]
    assert [row.project for row in batch.rows][0] == "semana-dica-um"
    for position, row in enumerate(batch.rows, start=1):
        project = Project.load(config.PROJECTS_DIR / row.project / "spec.json")
        hook, subtitle = project.overlays[0], project.overlays[1]
        assert hook.text == TITLES[position - 1] and subtitle.text == f"Texto {position}"
        assert project.timeline[0].src.endswith(f"img{position}.png")
    assert service.store.exists("semana") and all(row.state == "pending" for row in batch.rows)


def test_equal_titles_get_numbered_names_and_never_overwrite_an_existing_project(tmp_path, media):
    existing = config.PROJECTS_DIR / "semana-dica"
    existing.mkdir(parents=True)
    service = make_service(tmp_path)
    batch = create(service, write_sheet(media, ["Dica", "Dica", "Outra"]))

    assert [row.slug for row in batch.rows] == ["dica", "dica-2", "outra"]
    assert [row.project for row in batch.rows] == ["semana-dica-2", "semana-dica-2-2", "semana-outra"]
    assert not (existing / "spec.json").exists()


def test_a_sheet_with_a_bad_row_is_refused_with_the_validation_unless_told_to_skip_it(tmp_path, media):
    service = make_service(tmp_path)
    sheet = write_sheet(media, broken={3: "nao-existe.png"})

    with pytest.raises(BatchInvalidError) as refused:
        create(service, sheet)
    assert [row.line for row in refused.value.validation.invalid_rows] == [4]
    assert not service.store.exists("semana") and not config.PROJECTS_DIR.exists()  # nada foi gravado

    batch = create(service, sheet, skip_invalid=True)
    states = {row.index: row.state for row in batch.rows}
    assert states == {1: "pending", 2: "pending", 3: "invalid", 4: "pending", 5: "pending"}
    assert batch.rows[2].project is None and batch.rows[2].issues[0]["field"] == "print"
    assert len([p for p in config.PROJECTS_DIR.iterdir() if (p / "spec.json").exists()]) == 4


def test_nothing_runs_when_every_row_is_bad_even_if_told_to_skip(tmp_path, media):
    service = make_service(tmp_path)
    sheet = write_sheet(media, ["A", "B"], broken={1: "x.png", 2: "y.png"})
    with pytest.raises(BatchInvalidError, match="Nenhuma linha"):
        create(service, sheet, skip_invalid=True)


def test_creating_a_lote_with_a_name_in_use_asks_for_resume_or_replace(tmp_path, media):
    service = make_service(tmp_path)
    create(service, write_sheet(media))
    with pytest.raises(BatchExistsError, match="Já existe o lote"):
        create(service, write_sheet(media))


# ---------- rodar e retomar ----------


def test_run_renders_every_row_into_the_lote_folder_and_reports_what_came_out(tmp_path, media):
    renderer = FakeRenderer()
    service = make_service(tmp_path, renderer)
    create(service, write_sheet(media))

    report = service.run("semana")

    assert renderer.calls == [
        f"semana-{slug}" for slug in ("dica-um", "dica-dois", "dica-tres", "dica-quatro", "dica-cinco")
    ]
    folder = config.OUTPUT_DIR / "semana"
    assert sorted(path.name for path in folder.glob("*.mp4")) == [
        "dica-cinco.mp4",
        "dica-dois.mp4",
        "dica-quatro.mp4",
        "dica-tres.mp4",
        "dica-um.mp4",
    ]
    assert report.status == "finished" and report.done == 5 and report.failed == 0 and report.waiting == 0
    saved = (folder / "relatorio.txt").read_text(encoding="utf-8")
    assert "5 de 5 vídeo(s) pronto(s)" in saved and "dica-um.mp4" in saved and "finished" not in saved


def test_resume_does_not_render_again_what_already_came_out(tmp_path, media):
    renderer = FakeRenderer()
    service = make_service(tmp_path, renderer)
    create(service, write_sheet(media))
    service.run("semana")
    mtimes = {path.name: path.stat().st_mtime_ns for path in (config.OUTPUT_DIR / "semana").glob("*.mp4")}

    report = service.run("semana")

    assert len(renderer.calls) == 5  # a segunda execução não chamou o render nenhuma vez
    assert report.done == 5
    assert mtimes == {
        path.name: path.stat().st_mtime_ns for path in (config.OUTPUT_DIR / "semana").glob("*.mp4")
    }


def test_interrupting_the_third_video_and_resuming_redoes_only_the_third_onward(tmp_path, media):
    def interrupt_on_third(project, rendered_so_far):
        if rendered_so_far == 2:
            raise KeyboardInterrupt

    renderer = FakeRenderer(before=interrupt_on_third)
    service = make_service(tmp_path, renderer)
    create(service, write_sheet(media))

    with pytest.raises(KeyboardInterrupt):
        service.run("semana")
    interrupted = service.report("semana")
    assert [row.state for row in interrupted.rows] == ["done", "done", "pending", "pending", "pending"]
    assert interrupted.status == "paused" and interrupted.done == 2
    first_two = {row.output: Path(row.output).stat().st_mtime_ns for row in interrupted.rows[:2]}
    assert (config.OUTPUT_DIR / "semana" / "relatorio.txt").exists()

    renderer.before = None
    renderer.calls.clear()
    report = service.run("semana")

    assert renderer.calls == ["semana-dica-tres", "semana-dica-quatro", "semana-dica-cinco"]
    assert report.status == "finished" and report.done == 5
    assert first_two == {output: Path(output).stat().st_mtime_ns for output in first_two}


def test_a_crash_leaves_a_running_row_that_the_next_run_takes_back(tmp_path, media):
    renderer = FakeRenderer()
    service = make_service(tmp_path, renderer)
    create(service, write_sheet(media, ["A", "B"]))
    service.store.change(
        "semana", lambda batch: setattr(batch.rows[0], "state", "running")
    )  # o processo caiu

    assert service.report("semana").status == "paused"
    service.run("semana")

    assert renderer.calls == ["semana-a", "semana-b"]


def test_pausing_stops_after_the_video_in_progress_and_resuming_finishes(tmp_path, media):
    holder: dict = {}

    def pause_during_second(project, rendered_so_far):
        if rendered_so_far == 1:
            holder["service"].pause("semana")

    renderer = FakeRenderer(before=pause_during_second)
    service = holder["service"] = make_service(tmp_path, renderer)
    create(service, write_sheet(media))

    paused = service.run("semana")

    assert paused.paused and paused.done == 2 and paused.waiting == 3
    assert renderer.calls == ["semana-dica-um", "semana-dica-dois"]  # o segundo terminou antes de parar
    assert service.store.pause_requested("semana")

    renderer.before = None
    finished = service.run("semana")  # retomar limpa o pedido de pausa
    assert (
        finished.status == "finished" and finished.done == 5 and not service.store.pause_requested("semana")
    )
    assert len(renderer.calls) == 5


def test_a_should_stop_callback_pauses_the_batch_too(tmp_path, media):
    renderer = FakeRenderer()
    service = make_service(tmp_path, renderer)
    create(service, write_sheet(media))

    report = service.run("semana", should_stop=lambda: len(renderer.calls) >= 1)

    assert report.paused and report.done == 1 and len(renderer.calls) == 1


def test_a_failing_video_is_reported_with_its_reason_and_the_others_still_come_out(tmp_path, media):
    def fail_second(project, rendered_so_far):
        if project.name.endswith("dica-dois"):
            raise RuntimeError("ffmpeg falhou na montagem final")

    renderer = FakeRenderer(before=fail_second)
    service = make_service(tmp_path, renderer)
    create(service, write_sheet(media))

    report = service.run("semana")

    assert [row.state for row in report.rows] == ["done", "failed", "done", "done", "done"]
    assert report.failed == 1 and report.done == 4 and report.status == "finished"
    assert "RuntimeError: ffmpeg falhou na montagem final" in report.rows[1].error
    text = report.to_text()
    assert "[falhou] Dica dois (linha 3): RuntimeError: ffmpeg falhou" in text
    assert "4 de 5 vídeo(s) pronto(s), 1 falhou(aram)" in text

    renderer.before = None
    renderer.calls.clear()
    retried = service.run("semana")  # retomar tenta de novo só o que falhou
    assert renderer.calls == ["semana-dica-dois"] and retried.done == 5 and retried.failed == 0


def test_correcting_one_project_and_resuming_redoes_only_that_video(tmp_path, media):
    renderer = FakeRenderer()
    service = make_service(tmp_path, renderer)
    create(service, write_sheet(media))
    service.run("semana")
    spec_path = config.PROJECTS_DIR / "semana-dica-tres" / "spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["overlays"][0]["text"] = "Título corrigido"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    renderer.calls.clear()

    service.run("semana")

    assert renderer.calls == ["semana-dica-tres"]


def test_rows_and_force_redo_exactly_the_videos_asked_for(tmp_path, media):
    renderer = FakeRenderer()
    service = make_service(tmp_path, renderer)
    create(service, write_sheet(media))
    service.run("semana")
    renderer.calls.clear()

    service.run("semana", rows={2, 4}, force=True)
    assert renderer.calls == ["semana-dica-dois", "semana-dica-quatro"]

    renderer.calls.clear()
    service.run("semana", rows={2, 4})  # sem force, o que está pronto fica
    assert renderer.calls == []


def test_a_video_whose_file_disappeared_is_rendered_again(tmp_path, media):
    renderer = FakeRenderer()
    service = make_service(tmp_path, renderer)
    create(service, write_sheet(media))
    service.run("semana")
    (config.OUTPUT_DIR / "semana" / "dica-um.mp4").unlink()
    renderer.calls.clear()

    service.run("semana")

    assert renderer.calls == ["semana-dica-um"]


def test_two_runs_of_the_same_lote_cannot_overlap(tmp_path, media):
    service = make_service(tmp_path)
    create(service, write_sheet(media))
    other = FileLock(service.store.lock_path("semana"))
    assert other.try_acquire()
    try:
        assert service.active("semana") and service.report("semana").status == "running"
        with pytest.raises(BatchBusyError):
            service.run("semana")
    finally:
        other.release()
    assert not service.active("semana")


def test_progress_names_the_video_in_progress_and_counts_those_already_done(tmp_path, media):
    steps: list[tuple[str, float]] = []
    service = make_service(tmp_path)
    create(service, write_sheet(media, ["A", "B", "C"]))
    service.run("semana", rows={1}, progress=lambda label, fraction: steps.append((label, fraction)))
    steps.clear()

    service.run("semana", progress=lambda label, fraction: steps.append((label, fraction)))

    assert steps[0] == ("Vídeo 2 de 3: B", pytest.approx(1 / 3))  # o primeiro já estava pronto
    assert steps[-1][0].startswith("Vídeo 3 de 3: C") and steps[-1][1] == pytest.approx(2 / 3)


def test_the_preview_goes_to_its_own_file_and_does_not_count_as_the_final_video(tmp_path, media):
    renderer = FakeRenderer()
    service = make_service(tmp_path, renderer)
    create(service, write_sheet(media, ["A"]), preview=True)
    service.run("semana")
    assert (config.OUTPUT_DIR / "semana" / "a__preview.mp4").exists()
    assert not (config.OUTPUT_DIR / "semana" / "a.mp4").exists()


# ---------- refazer o lote a partir da planilha ----------


def test_replacing_a_lote_keeps_the_videos_that_did_not_change(tmp_path, media):
    renderer = FakeRenderer()
    service = make_service(tmp_path, renderer)
    create(service, write_sheet(media, ["A", "B", "C"]))
    service.run("semana")
    renderer.calls.clear()

    sheet = write_sheet(media, ["A", "B", "C"])
    sheet.write_text(
        sheet.read_text(encoding="utf-8-sig").replace("Texto 2", "Texto novo"), encoding="utf-8-sig"
    )
    create(service, sheet, replace=True)
    service.run("semana")

    assert renderer.calls == ["semana-b"]  # só a linha 2 mudou
    assert Project.load(config.PROJECTS_DIR / "semana-b" / "spec.json").overlays[1].text == "Texto novo"
    assert [path.name for path in config.PROJECTS_DIR.iterdir() if path.name.startswith("semana-b")] == [
        "semana-b"
    ]


# ---------- relatório e lista ----------


def test_reports_lists_every_lote_with_its_summary(tmp_path, media):
    service = make_service(tmp_path)
    create(service, write_sheet(media, ["A", "B"]))
    service.run("semana")
    service.create("stories-medlycare", write_sheet(media, ["C"], name="outra.csv"), name_column="titulo")

    by_name = {report.name: report for report in service.reports()}
    assert by_name["semana"].status == "finished" and by_name["outra"].status == "paused"
    assert by_name["outra"].summary() == "0 de 1 vídeo(s) pronto(s), 1 esperando"


def test_the_signature_ignores_how_the_json_was_formatted_but_not_the_options(tmp_path, media):
    service = make_service(tmp_path)
    batch = create(service, write_sheet(media, ["A"]))
    path = config.PROJECTS_DIR / batch.rows[0].project / "spec.json"
    before = project_signature(Project.load(path), False, None)
    path.write_text(json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=8), encoding="utf-8")
    after = Project.load(path)

    assert project_signature(after, False, None) == before
    assert project_signature(after, True, None) != before
    assert project_signature(after, False, "instagram/stories") != before


# ---------- a pipeline de verdade, com runner gravado ----------


def test_resume_never_reaches_the_ffmpeg_runner_for_videos_already_made(tmp_path, media):
    runner = RecordingRunner(on_run=touch_output)
    renderer = PipelineRenderer(prober=fake_prober, runner_factory=lambda sink: runner)
    service = make_service(tmp_path, renderer)
    create(service, write_sheet(media, ["A", "B"]))

    first = service.run("semana")
    commands_after_first_run = len(runner.commands)
    second = service.run("semana")

    assert first.done == 2 and second.done == 2, [row.error for row in first.rows]
    assert commands_after_first_run > 0 and len(runner.commands) == commands_after_first_run
    assert sorted(path.name for path in (config.OUTPUT_DIR / "semana").glob("*.mp4")) == ["a.mp4", "b.mp4"]
    assert all(os.path.getsize(row.output) for row in first.rows if row.output)  # vídeo e miniatura saíram
