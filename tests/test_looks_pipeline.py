"""Looks no pipeline (dependências falsas, sem ffmpeg): qual look vale em cada trecho, o cache e os erros."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.segments import MEZZ_VERSION, cache_key, segment_look

from .test_pipeline_unit import LOUDNORM_JSON, fake_prober, touch_output

CINEMA_MARK = "curves=m='0/0.03"  # só o look cinema usa esta curva


def _project(tmp_path: Path, **extra) -> Project:
    # o probe é falso; as fontes só precisam existir, e uma vez só: a chave do cache lê a data do arquivo
    if not (tmp_path / "take.mp4").exists():
        (tmp_path / "take.mp4").write_bytes(b"x")
        Image.new("RGB", (1000, 620), "#3366CC").save(tmp_path / "print.png")
    spec = {
        "name": "looks",
        "output": {"preset": "instagram/reels"},
        "timeline": [
            {"type": "card", "title": "Abertura", "duration": 1.0, "motion": "none"},
            {"type": "clip", "src": "take.mp4", "start": 0, "end": 2},
            {"type": "clip", "src": "take.mp4", "start": 0, "end": 2, "color": {"brightness": 0.1}},
            {"type": "image", "src": "print.png", "duration": 1.0, "motion": "zoom-in"},
        ],
        "audio": {"normalize": "off"},
        **extra,
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    return project


def _graphs(tmp_path: Path, project: Project, brand: str | None = None) -> list[str]:
    """Filtro de cada um dos quatro mezaninos, na ordem da linha do tempo."""
    if brand:
        project = project.model_copy(update={"brand": brand})
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, no_captions=True, out=tmp_path / "out.mp4"),
        runner=runner,
        prober=fake_prober,
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "out",
    ).run()
    graphs = []
    for command in runner.commands:
        if "-filter_complex" in command and "[vout]" in command[command.index("-filter_complex") + 1]:
            graphs.append(command[command.index("-filter_complex") + 1])
    return graphs[:4]


def test_project_look_reaches_every_segment_except_the_one_with_its_own_color(tmp_path):
    graphs = _graphs(tmp_path, _project(tmp_path, look="cinema"))
    assert len(graphs) == 4
    has_look = [CINEMA_MARK in graph for graph in graphs]
    assert has_look == [True, True, False, True]  # o trecho de cor própria (índice 2) mantém a sua
    assert "brightness=0.100" in graphs[2] and "vignette" not in graphs[2]
    assert all("noise=c0s=3" in graphs[i] for i in (0, 1, 3))  # o grão do cinema (0.25) nos outros três


def test_without_any_look_the_mezzanine_graphs_have_no_finishing_at_all(tmp_path):
    graphs = _graphs(tmp_path, _project(tmp_path))
    assert not any(
        word in graph for graph in graphs for word in ("curves", "noise", "blend", "vignette", "fx_")
    )


def test_a_segment_look_beats_the_projects_and_nenhum_turns_it_off(tmp_path):
    project = _project(tmp_path, look="cinema")
    project.timeline[0].look = "nenhum"  # o cartão não recebe o look
    project.timeline[1].look = "frio"
    project.timeline[2].look = "pb-contraste"  # pedindo o look no trecho com cor própria, ele vale
    graphs = _graphs(tmp_path, project)
    assert "curves" not in graphs[0]
    assert "r='0/0 0.5/0.45" in graphs[1] and CINEMA_MARK not in graphs[1]
    assert "saturation=0.000" in graphs[2] and "brightness=0.100" in graphs[2]  # a cor dele e depois o look
    assert CINEMA_MARK in graphs[3]


def test_a_brand_look_replaces_the_default_with_the_same_name(tmp_path, monkeypatch):
    import json

    from dmaker import config
    from dmaker.domain import brand as brand_module

    folder = tmp_path / "brands" / "minha"
    folder.mkdir(parents=True)
    (folder / "brand.json").write_text(
        json.dumps({"name": "Minha", "looks": {"cinema": {"color": {"saturation": 1.4}}}}), encoding="utf-8"
    )
    monkeypatch.setattr(config, "BRANDS_DIR", tmp_path / "brands")
    monkeypatch.setattr(brand_module, "BRANDS_DIR", tmp_path / "brands")
    graphs = _graphs(tmp_path, _project(tmp_path, look="cinema"), brand="minha")
    assert "saturation=1.400" in graphs[1] and CINEMA_MARK not in graphs[1]  # o da marca, não o padrão


def test_unknown_look_stops_the_render_before_any_work_and_names_where(tmp_path):
    project = _project(tmp_path, look="neon")
    with pytest.raises(ValueError, match=r"^look: look desconhecido: 'neon'.*cinema"):
        _graphs(tmp_path, project)
    project = _project(tmp_path)
    project.timeline[2].look = "neon"
    with pytest.raises(ValueError, match=r"^timeline\[2\]\.look: look desconhecido"):
        _graphs(tmp_path, project)


def test_the_look_is_part_of_the_mezzanine_cache_key_by_content_not_by_name(tmp_path):
    def run(project: Project) -> int:
        again = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
        RenderPipeline(
            project,
            RenderOptions(preview=True, quiet=True, no_captions=True, out=tmp_path / "o.mp4"),
            runner=again,
            prober=fake_prober,
            cache_dir=tmp_path / "mez",
            jobs_dir=tmp_path / "jobs",
            output_dir=tmp_path / "out",
        ).run()
        return sum(1 for c in again.commands if c[-1].endswith(".mov"))  # os mezaninos gerados

    assert run(_project(tmp_path)) == 4  # nada em cache
    assert run(_project(tmp_path)) == 0  # tudo em cache
    assert run(_project(tmp_path, look="cinema")) == 3  # o look gerou de novo os três trechos que o recebem
    assert run(_project(tmp_path, look="cinema")) == 0


def test_cache_key_changes_with_the_mezzanine_version_and_the_look_content():
    assert MEZZ_VERSION != "m6"  # o acabamento mudou a receita do mezanino
    assert cache_key(MEZZ_VERSION, None) != cache_key(MEZZ_VERSION, {"grain": 0.2})
    assert cache_key("m6", None) != cache_key(MEZZ_VERSION, None)


def test_segment_look_resolves_through_the_context_theme(tmp_path):
    from dmaker.domain.brand import load_theme

    class Ctx:
        project = _project(tmp_path, look="quente")
        theme = load_theme(None)

    segment = Ctx.project.timeline[1]
    look = segment_look(1, segment, Ctx)  # type: ignore[arg-type]
    assert look is not None and look.glow == 0.2
    assert segment_look(2, Ctx.project.timeline[2], Ctx) is None  # type: ignore[arg-type]
