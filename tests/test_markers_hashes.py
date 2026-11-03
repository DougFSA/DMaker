"""Projeto antigo igual: marcadores não entram em hash nenhum (mezanino, receita da prévia, quadro instantâneo) e o
projeto sem eles renderiza exatamente o mesmo."""

from __future__ import annotations

from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.pipeline.preview_audio import mix_recipe

from .test_instant_frame import make_project, make_renderer
from .test_pipeline_unit import LOUDNORM_JSON, _pipeline, touch_output, workspace  # noqa: F401

MARKERS = [
    {"at": 0.5, "text": "gancho", "color": "#e0a020"},
    {"start": 1.0, "end": 2.5, "text": "trecho bom", "group": "análise"},
]


def test_a_project_with_markers_reuses_every_mezzanine_of_the_same_project_without_them(workspace):  # noqa: F811
    first = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    plain = _pipeline(workspace, first).run()
    mezzanines = sorted(path.name for path in (workspace["dir"] / "mez").glob("*.mov"))
    graph = (plain.job_dir / "graph.txt").read_text(encoding="utf-8")
    assert len(first.commands) == 7 and mezzanines

    project = workspace["project"]
    marked = Project.model_validate({**project.model_dump(), "markers": MARKERS})
    marked.base_dir = project.base_dir
    workspace["project"] = marked
    second = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    result = _pipeline(workspace, second).run()

    # só a medição de loudness, a montagem e a miniatura: os três mezaninos e a transcrição vieram do cache
    assert len(second.commands) == 3 and second.frames_consumed == 0
    assert sorted(path.name for path in (workspace["dir"] / "mez").glob("*.mov")) == mezzanines
    assert (result.job_dir / "graph.txt").read_text(encoding="utf-8") == graph


def test_the_preview_audio_recipe_ignores_markers(workspace):  # noqa: F811
    project = workspace["project"]
    marked = Project.model_validate({**project.model_dump(), "markers": MARKERS})
    assert mix_recipe(marked) == mix_recipe(project)


def test_the_instant_frame_key_ignores_markers(tmp_path):
    renderer = make_renderer(tmp_path)
    assert renderer.key(make_project(tmp_path, markers=MARKERS), 3.0) == renderer.key(
        make_project(tmp_path), 3.0
    )
