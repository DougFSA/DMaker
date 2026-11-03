"""O modelo "podcast": voz gravada entre a música de abertura e a de encerramento, MP3 a -16 LUFS com etiquetas."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.podcast_template import prepare_podcast
from dmaker.domain.spec import Project
from dmaker.domain.templates import TemplateError, find_template, render_template
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.pipeline import RenderOptions, create_renderer
from dmaker.pipeline.projects import describe_templates, project_from_template, summarize


def fake_prober(path: Path) -> MediaInfo:
    seconds = 600.0 if path.stem == "episodio" else 180.0
    return MediaInfo(path, seconds, 0, 0, 0.0, False, True, False, sample_rate=48000, channels=2)


PARAMS = {
    "voz": "episodio.wav",
    "trilha": "tema.mp3",
    "duracao_voz": 600,
    "titulo": "Episódio 12",
    "faixa": "12",
    "artista": "Programa",
}


def render(**changes) -> dict:
    return render_template(find_template("podcast"), {**PARAMS, **changes})


def test_the_total_is_the_opening_plus_the_voice_plus_the_closing():
    prepared = prepare_podcast(
        {"duracao_voz": 600, "abertura": 8, "encerramento": 10, "titulo": "T", "ano": ""}
    )
    assert (prepared["total"], prepared["inicio_encerramento"]) == (618.0, 608.0)
    assert prepared["etiquetas"] == {"title": "T"}  # etiqueta vazia não entra


@pytest.mark.parametrize(
    "bad",
    [{"duracao_voz": 0}, {"duracao_voz": "10"}, {"abertura": -1}, {"encerramento": "dez"}],
)
def test_wrong_durations_are_refused_with_the_name_of_the_parameter(bad):
    with pytest.raises(ValueError, match="`duracao_voz`|`abertura`|`encerramento`"):
        prepare_podcast({"duracao_voz": 60, "abertura": 8, "encerramento": 10, **bad})


def test_the_rendered_spec_is_an_audio_only_project_at_minus_16_with_the_episode_tags():
    project = Project.model_validate(render())
    assert project.timeline == [] and project.output.preset == "audio/mp3"
    assert project.audio.target_lufs == -16
    assert [(c.src, c.start) for c in project.audio.voiceover] == [("episodio.wav", 8.0)]
    assert project.output.metadata.model_dump(exclude_none=True) == {
        "title": "Episódio 12",
        "track": "12",
        "artist": "Programa",
        "genre": "Podcast",
    }
    spans = project.audio.music.spans
    assert (spans[0].start, spans[0].end) == (0, 8) and (spans[1].start, spans[1].end, spans[1].tail) == (
        608.0,
        618.0,
        True,
    )


def test_without_opening_or_closing_the_matching_music_span_is_dropped():
    project = Project.model_validate(render(abertura=0))
    assert [(s.start, s.end) for s in project.audio.music.spans] == [(600.0, 610.0)]
    assert project.audio.voiceover[0].start == 0
    assert [(s.start, s.end) for s in Project.model_validate(render(encerramento=0)).audio.music.spans] == [
        (0, 8)
    ]


def test_the_format_and_the_target_are_parameters():
    project = Project.model_validate(render(formato="audio/m4a", loudness=-14))
    assert project.output.preset == "audio/m4a" and project.audio.target_lufs == -14


def test_the_media_parameters_are_required_with_no_default_path():
    template = describe_templates()
    podcast = next(item for item in template if item["name"] == "podcast")
    assert podcast["params"]["voz"]["required"] and podcast["params"]["trilha"]["required"]
    assert podcast["params"]["duracao_voz"]["required"] is False  # medida do arquivo de voz
    with pytest.raises(TemplateError, match="faltam parâmetros obrigatórios"):
        render_template(find_template("podcast"), {})


def test_creating_the_project_measures_the_voice_file_and_the_summary_gives_the_total(tmp_path):
    for name in ("episodio.wav", "tema.mp3"):
        (tmp_path / name).write_bytes(b"x")
    project = project_from_template(
        "podcast",
        "ep12",
        {"voz": str(tmp_path / "episodio.wav"), "trilha": str(tmp_path / "tema.mp3")},
        prober=fake_prober,
    )
    assert project.audio.voiceover[0].start == 8.0
    summary = summarize(project, fake_prober)
    assert summary.total == 618.0 and summary.preset.id == "audio/mp3"


def test_the_template_renders_without_any_video_command(tmp_path):
    for name in ("episodio.wav", "tema.mp3"):
        (tmp_path / name).write_bytes(b"x")
    spec = render(voz=str(tmp_path / "episodio.wav"), trilha=str(tmp_path / "tema.mp3"))
    project = Project.model_validate({**spec, "name": "ep12"})
    runner = RecordingRunner(
        capture_stderr='{"input_i": "-24", "input_tp": "-12", "input_lra": "5", "input_thresh": "-34", "target_offset": "0"}'
    )
    result = create_renderer(
        project,
        RenderOptions(out=tmp_path / "ep12.mp3", quiet=True),
        runner=runner,
        prober=fake_prober,
        cache_dir=tmp_path / "c",
        jobs_dir=tmp_path / "j",
        output_dir=tmp_path,
    ).run()
    final = " ".join(runner.commands[-1])
    assert result.duration == 618.0 and "libmp3lame" in final and "-vn" in final.split()
    assert "-metadata title=Episódio 12" in final and "loudnorm=I=-16" in final
    assert all("libx264" not in " ".join(command) for command in runner.commands)
