"""O quadro de um instante pelo serviço, com o ffmpeg, o probe, o navegador e o recortador falsos: o comando certo,
só os mezaninos que aparecem, o cache e o que o quadro diz que não mostra."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image

from dmaker.domain.brand import load_theme
from dmaker.domain.presets import get_preset
from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.context import RenderContext
from dmaker.pipeline.instant_frame import (
    InstantFrameRenderer,
    frame_index,
    instant_notes,
    shows_frame,
)
from dmaker.pipeline.segments import MezzanineBuilder
from dmaker.pipeline.sources import resolve_sources
from dmaker.text.captions import Cue
from dmaker.text.transcribe import Transcript

from .conftest import fake_ffmpeg_output
from .test_html import FakeHtmlRenderer, FakeMatter
from .test_pipeline_unit import LOUDNORM_JSON, fake_prober, touch_output

# cartão [0, 2], clipe [1,5, 5,5] (a transição de 0,5 s junta os dois entre 1,5 e 2) e imagem [5,5, 7,5] (corte)
SPEC = {
    "name": "quadro",
    "output": {"preset": "instagram/reels"},
    "timeline": [
        {"type": "card", "title": "Abertura", "duration": 2.0, "motion": "none"},
        {
            "type": "clip",
            "src": "take.mp4",
            "start": 0,
            "end": 4,
            "transition": {"type": "fade", "duration": 0.5},
        },
        {"type": "image", "src": "print.png", "duration": 2.0, "motion": "none"},
    ],
    "overlays": [{"type": "text", "text": "Gancho", "role": "hook", "start": 0, "end": 7}],
    "audio": {"normalize": "off"},
}


def make_project(tmp_path: Path, **changes) -> Project:
    tmp_path.mkdir(parents=True, exist_ok=True)
    if not (tmp_path / "take.mp4").exists():  # reescrever mudaria o `mtime`, que as chaves enxergam
        (tmp_path / "take.mp4").write_bytes(b"x")
        Image.new("RGB", (1000, 620), "#3366CC").save(tmp_path / "print.png")
    folder = tmp_path / "comp"
    if not folder.exists():
        folder.mkdir()
        (folder / "index.html").write_text("<p>oi</p>", encoding="utf-8")
    project = Project.model_validate({**SPEC, **changes})
    project.base_dir = tmp_path
    return project


def make_renderer(tmp_path: Path, runner=None, html=None, matter=None, **options) -> InstantFrameRenderer:
    return InstantFrameRenderer(
        runner or RecordingRunner(on_run=fake_ffmpeg_output),
        fake_prober,
        html_renderer=html or FakeHtmlRenderer(),
        matter=matter or FakeMatter(),
        cache_dir=tmp_path / "mez",
        frames_dir=tmp_path / "frames",
        jobs_dir=tmp_path / "jobs",
        **options,
    )


def graph_of(tmp_path: Path) -> str:
    return (tmp_path / "jobs" / "quadro_frame" / "graph.txt").read_text(encoding="utf-8")


def command_of(tmp_path: Path) -> str:
    """O último comando do quadro, que o serviço deixa em `cmd.txt` na pasta do trabalho (para quem for depurar)."""
    return (tmp_path / "jobs" / "quadro_frame" / "cmd.txt").read_text(encoding="utf-8")


def ass_of(tmp_path: Path) -> str:
    return (tmp_path / "jobs" / "quadro_frame" / "overlay.ass").read_text(encoding="utf-8-sig")


# ---------- o comando ----------


def test_one_clip_frame_builds_only_its_mezzanine_and_one_frame_command(tmp_path):
    runner = RecordingRunner(on_run=fake_ffmpeg_output)
    frame = make_renderer(tmp_path, runner).render(make_project(tmp_path), 3.0)

    assert frame.at == 3.0 and frame.notes == () and frame.path.suffix == ".png" and frame.path.exists()
    mezzanine, command = runner.commands  # o cartão e a imagem não aparecem em 3 s: nenhum mezanino deles
    assert "take.mp4" in " ".join(mezzanine) and mezzanine[-1].endswith(".mov")
    assert len(list((tmp_path / "mez").glob("*.mov"))) == 1 and not list(
        (tmp_path / "mez").glob("*_card.png")
    )
    joined = " ".join(command)
    # o clipe começa em 1,5 s do vídeo final: o quadro de 3 s é o de 1,5 s dele, e o mezanino abre ali
    assert "-ss 1.500000 -i" in joined
    assert (
        "-/filter_complex graph.txt" in joined
        and "-an -frames:v 1" in joined
        and command[-1].endswith(".png")
    )
    graph = graph_of(tmp_path)
    assert "trim=start_frame=0:end_frame=1,setpts=PTS-STARTPTS+3.000000/TB" in graph
    assert "ass=filename='overlay.ass'" in graph and graph.endswith("format=rgb24[vout]")
    assert "GANCHO" in ass_of(tmp_path).upper()
    assert json.loads(frame.path.with_suffix(".json").read_text(encoding="utf-8")) == {"at": 3.0, "notes": []}


def test_a_second_request_for_the_same_frame_comes_from_the_cache(tmp_path):
    project = make_project(tmp_path)
    first = make_renderer(tmp_path).render(project, 3.0)
    runner = RecordingRunner(on_run=fake_ffmpeg_output)
    again = make_renderer(tmp_path, runner).render(project, 3.004)  # o mesmo quadro (arredondado)
    assert again.path == first.path and again.key == first.key and runner.commands == []


def test_a_frame_inside_a_transition_mixes_both_clips_from_where_the_transition_started(tmp_path):
    runner = RecordingRunner(on_run=fake_ffmpeg_output)
    make_renderer(tmp_path, runner).render(make_project(tmp_path), 1.7)
    assert len(runner.commands) == 3  # o mezanino do cartão, o do clipe e o quadro
    graph = graph_of(tmp_path)
    assert "xfade=transition=fade" in graph
    assert (
        "trim=start_frame=6:end_frame=7,setpts=PTS-STARTPTS+1.700000/TB" in graph
    )  # 1,7 s é o 6º quadro da transição
    command = " ".join(runner.commands[-1])
    assert "-ss 1.500000" in command  # o cartão, aberto onde a transição começou


def test_each_instant_builds_the_mezzanines_it_shows(tmp_path):
    for t, expected in ((0.5, 2), (6.0, 2), (1.7, 3)):  # (o mezanino de cada trecho que aparece) + o quadro
        runner = RecordingRunner(on_run=fake_ffmpeg_output)
        make_renderer(tmp_path / f"t{t}", runner).render(make_project(tmp_path / f"t{t}"), t)
        assert len(runner.commands) == expected, t


def test_an_instant_past_the_end_shows_the_last_frame_and_says_so(tmp_path):
    frame = make_renderer(tmp_path).render(make_project(tmp_path), 100.0)
    assert frame.at == pytest.approx(224 / 30)  # 7,5 s a 30 quadros: o último é o 224
    assert len(frame.notes) == 1 and "passa do fim" in frame.notes[0] and "último quadro" in frame.notes[0]


def test_a_missing_source_fails_with_the_file_in_the_message(tmp_path):
    project = make_project(tmp_path)
    (tmp_path / "take.mp4").unlink()
    with pytest.raises(FileNotFoundError, match="take.mp4"):
        make_renderer(tmp_path).render(project, 3.0)


def test_a_checkpoint_that_raises_stops_before_any_ffmpeg_command(tmp_path):
    runner = RecordingRunner(on_run=fake_ffmpeg_output)

    def checkpoint() -> None:
        raise RuntimeError("superado")

    with pytest.raises(RuntimeError, match="superado"):
        make_renderer(tmp_path, runner).render(make_project(tmp_path), 3.0, checkpoint=checkpoint)
    assert runner.commands == []


def test_old_frames_of_a_project_are_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr("dmaker.pipeline.instant_frame.KEEP_FRAMES_PER_PROJECT", 2)
    project = make_project(tmp_path)
    renderer = make_renderer(tmp_path)
    paths = []
    for stamp, t in enumerate((0.5, 3.0, 4.0), start=1):
        paths.append(renderer.render(project, t).path)
        os.utime(
            paths[-1], (stamp * 1000, stamp * 1000)
        )  # a ordem de gravação não depende do relógio do disco
    left = sorted((tmp_path / "frames").glob("*.png"))
    assert len(left) == 2 and paths[0] not in left  # o mais antigo saiu, com o `.json` dele
    assert len(list((tmp_path / "frames").glob("*.json"))) == 2


# ---------- a chave ----------


def test_the_key_follows_the_spec_the_frame_and_the_files_it_reads(tmp_path):
    renderer = make_renderer(tmp_path)
    project = make_project(tmp_path)
    key = renderer.key(project, 3.0)
    assert renderer.key(project, 3.01) == key  # o mesmo quadro
    assert renderer.key(project, 3.04) != key  # o quadro seguinte
    edited = make_project(tmp_path, overlays=[{"type": "text", "text": "Outro", "role": "hook"}])
    assert renderer.key(edited, 3.0) != key  # a spec mudou
    (tmp_path / "take.mp4").write_bytes(b"outro conteudo")
    assert renderer.key(project, 3.0) != key  # o arquivo que o quadro lê mudou


def test_the_key_follows_the_html_composition_files(tmp_path):
    spec = {"overlays": [{"type": "html", "src": "comp", "x": 0.5, "y": 0.5, "width": 0.5, "height": 0.2}]}
    renderer = make_renderer(tmp_path)
    project = make_project(tmp_path, **spec)
    key = renderer.key(project, 1.0)
    (tmp_path / "comp" / "index.html").write_text("<p>mudou por fora</p>", encoding="utf-8")
    assert renderer.key(project, 1.0) != key


def test_the_instant_is_the_one_of_the_nearest_frame(tmp_path):
    renderer = make_renderer(tmp_path)
    project = make_project(tmp_path)
    assert renderer.instant(project, 3.016) == pytest.approx(3.0)  # 90,48 quadros: o 90
    assert renderer.instant(project, 3.017) == pytest.approx(91 / 30)
    assert frame_index(0.0, 30) == 0 and frame_index(0.016, 30) == 0 and frame_index(0.017, 30) == 1


def test_a_frame_shows_a_span_with_the_same_rule_as_the_text(tmp_path):
    assert shows_frame(1.0, 2.0, 30, 30) and shows_frame(1.0, 2.0, 59, 30)
    assert not shows_frame(1.0, 2.0, 29, 30) and not shows_frame(1.0, 2.0, 60, 30)


# ---------- as composições em HTML ----------

HTML = {
    "overlays": [
        {"type": "html", "src": "comp", "x": 0.5, "y": 0.5, "width": 0.5, "height": 0.2, "start": 1, "end": 3}
    ]
}


def test_an_html_composition_is_drawn_straight_at_the_instant_and_kept_in_the_cache(tmp_path):
    html = FakeHtmlRenderer()
    renderer = make_renderer(tmp_path, html=html)
    renderer.render(make_project(tmp_path, **HTML), 2.0)

    [(composition, at)] = html.stills
    assert at == pytest.approx(1.0)  # 2 s do vídeo, a composição entrou em 1 s
    assert composition.output_size == (270, 192) and composition.scale == 0.5  # a mesma página, na prévia
    graph = graph_of(tmp_path)
    assert "_htmlstill.png" in command_of(tmp_path)
    assert "enable='gte(t,1.983333)*lt(t,2.016667)'" in graph and "tpad" not in graph
    assert html.calls == []  # nunca o vídeo da composição inteiro

    more = {"overlays": [*HTML["overlays"], {"type": "text", "text": "Mais", "role": "hook"}]}
    renderer.render(
        make_project(tmp_path, **more), 2.0
    )  # outra chave, mesmo quadro da página: ela não é desenhada de novo
    assert len(html.stills) == 1


def test_an_html_composition_that_is_not_on_screen_is_not_drawn(tmp_path):
    html = FakeHtmlRenderer()
    make_renderer(tmp_path, html=html).render(make_project(tmp_path, **HTML), 0.5)
    assert html.stills == [] and "htmlstill" not in command_of(tmp_path)


def test_without_a_browser_the_frame_still_comes_with_a_note_about_the_composition(tmp_path):
    html = FakeHtmlRenderer(problem="O Chromium não está instalado.")
    frame = make_renderer(tmp_path, html=html).render(make_project(tmp_path, **HTML), 2.0)
    assert html.stills == [] and len(frame.notes) == 1
    assert "composição em HTML" in frame.notes[0] and "Chromium" in frame.notes[0]


# ---------- a pessoa atrás do texto ----------

BEHIND = {"overlays": [{"type": "text", "text": "Atrás", "layer": "behind-person", "start": 0, "end": 7}]}


def test_the_person_is_cut_out_of_only_the_asked_frame_with_the_warmup_of_the_model(tmp_path):
    matter = FakeMatter()
    make_renderer(tmp_path, matter=matter).render(make_project(tmp_path, **BEHIND), 3.0)
    [request] = matter.person_requests
    assert request.model == "mobilenetv3" and request.warmup_frames == 12  # o modelo leve da prévia
    assert request.length == pytest.approx((12 + 1) / 30)  # o aquecimento e o quadro: nada do resto do texto
    assert "ass=filename='overlay_behind.ass'" in graph_of(tmp_path)
    assert "_person.mov" in command_of(tmp_path)


def test_during_a_transition_the_person_is_cut_from_the_start_of_the_transition_to_the_frame(tmp_path):
    matter = FakeMatter()
    make_renderer(tmp_path, matter=matter).render(make_project(tmp_path, **BEHIND), 1.7)
    [request] = matter.person_requests
    assert request.length == pytest.approx(
        (12 + 7) / 30
    )  # a transição já andou 6 quadros: do 45 ao 51, inclusive


def test_no_person_is_cut_when_the_text_is_not_behind_or_not_on_screen(tmp_path):
    matter = FakeMatter()
    make_renderer(tmp_path, matter=matter).render(make_project(tmp_path), 3.0)
    late = {"overlays": [{"type": "text", "text": "Depois", "layer": "behind-person", "start": 6, "end": 7}]}
    make_renderer(tmp_path / "b", matter=matter).render(make_project(tmp_path / "b", **late), 3.0)
    assert matter.person_requests == []


# ---------- as legendas e o audiograma ----------


def test_the_automatic_caption_without_a_stored_transcription_is_left_out_with_a_note(tmp_path):
    def never(captions):
        raise AssertionError("o quadro do instante não chama o Whisper")

    renderer = make_renderer(tmp_path, transcriber_factory=never)
    project = make_project(tmp_path, captions={"source": "auto", "language": "pt"})
    frame = renderer.render(project, 3.0)
    assert (
        len(frame.notes) == 1
        and "legenda automática" in frame.notes[0]
        and "primeiro render" in frame.notes[0]
    )


class OneCueTranscriber:
    def transcribe(self, wav, language, initial_prompt=None):
        return Transcript([Cue(0.2, 4.0, "olá mundo", [])], {"language": language})


def test_the_stored_transcription_of_a_previous_render_is_used(tmp_path):
    project = make_project(tmp_path, captions={"source": "auto", "language": "pt"})
    RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=tmp_path / "out.mp4"),
        runner=RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON),
        prober=fake_prober,
        transcriber_factory=lambda captions: OneCueTranscriber(),
        cache_dir=tmp_path / "mez-render",
        jobs_dir=tmp_path / "jobs-render",
        output_dir=tmp_path / "output",
    ).run()
    assert (tmp_path / "captions.auto.json").exists()

    frame = make_renderer(tmp_path).render(project, 3.0)
    assert frame.notes == ()
    # as legendas do quadro são, linha a linha, as que o render pôs no ASS dele
    rendered = (tmp_path / "jobs-render" / "quadro_preview" / "overlay.ass").read_text(encoding="utf-8-sig")
    captions = [line for line in rendered.splitlines() if ",Cap," in line]
    assert len(captions) == 2 and all(line in ass_of(tmp_path) for line in captions)


def test_a_caption_file_is_read_like_the_render_does(tmp_path):
    (tmp_path / "falas.srt").write_text(
        "1\n00:00:00,200 --> 00:00:04,000\nlegenda do arquivo\n", encoding="utf-8"
    )
    project = make_project(tmp_path, captions={"source": "falas.srt"})
    frame = make_renderer(tmp_path).render(project, 3.0)
    assert frame.notes == () and ",Cap," in ass_of(tmp_path)  # a legenda do arquivo entrou no ASS do quadro


def test_a_narration_caption_is_left_out_with_a_note(tmp_path):
    project = make_project(tmp_path, captions={"source": "narration"})
    frame = make_renderer(tmp_path).render(project, 3.0)
    assert len(frame.notes) == 1 and "narração" in frame.notes[0]


def test_the_audiogram_is_left_out_with_a_note(tmp_path):
    project = make_project(tmp_path, overlays=[{"type": "audiogram", "start": 0, "end": 7}])
    frame = make_renderer(tmp_path).render(project, 3.0)
    assert len(frame.notes) == 1 and "audiograma" in frame.notes[0]
    assert "audiogram" not in graph_of(tmp_path)


def test_a_disabled_caption_or_a_project_without_caption_says_nothing():
    plain = Project.model_validate(SPEC)
    off = Project.model_validate({**SPEC, "captions": {"enabled": False}})
    muted = Project.model_validate(
        {**SPEC, "captions": {"source": "auto"}, "audio": {"normalize": "off", "mute_clips": True}}
    )
    for project in (plain, off, muted):
        assert instant_notes(project, captions_found=False, audiograms=False) == []


# ---------- o plano da linha do tempo ----------


def test_the_mezzanine_builder_can_prepare_only_some_segments(tmp_path):
    project = make_project(tmp_path)
    preset = get_preset(project.output.preset).preview()
    ctx = RenderContext(
        project=project,
        options=RenderOptions(preview=True, quiet=True, dry_run=True),
        theme=load_theme(None, None),
        preset=preset,
        fps=30.0,
        job_dir=tmp_path / "jobs",
        cache_dir=tmp_path / "mez",
        runner=RecordingRunner(),
        prober=fake_prober,
        matter=FakeMatter(),
    )
    sources = resolve_sources(project, fake_prober, {})
    builder = MezzanineBuilder()
    assert [item.index for item in builder.prepare(ctx, sources)] == [0, 1, 2]
    assert [item.index for item in builder.prepare(ctx, sources, only=[1])] == [1]
    assert builder.prepare(ctx, sources, only=[]) == []


def test_clean_also_clears_the_frames_the_editor_asked_for():
    from typer.testing import CliRunner

    from dmaker import config
    from dmaker.cli import app

    config.FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    (config.FRAMES_DIR / "p__abc.png").write_bytes(b"x")
    result = CliRunner().invoke(app, ["clean"])
    assert result.exit_code == 0, result.output
    assert config.FRAMES_DIR.is_dir() and not list(config.FRAMES_DIR.iterdir())
