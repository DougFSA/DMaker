"""Render e exportação de áudio com dependências falsas: sem ffmpeg e sem Whisper.

Prova pelos comandos que o ffmpeg recebe que nenhum quadro de vídeo nasce (nenhum `-c:v`, nenhum mezanino de
vídeo), que o grafo é o do render de vídeo e que cada modo de exportação monta os comandos certos.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmaker.domain.audio_export import ExportRequest
from dmaker.domain.audio_presets import EncodingChoices, get_audio_preset
from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.pipeline import RenderOptions, create_renderer
from dmaker.pipeline.audio_export import AudioExporter, destinations, plan_files
from dmaker.pipeline.audio_render import AudioRenderPipeline, encoding_for, output_tags
from dmaker.pipeline.audio_service import (
    audio_preset_name,
    build_pipeline,
    planned_outputs,
    project_with_loudness,
)
from dmaker.pipeline.output_kinds import create_renderer as factory
from dmaker.pipeline.renderer import RenderPipeline

LOUDNORM = json.dumps(
    {
        "input_i": "-24.0",
        "input_tp": "-12.0",
        "input_lra": "5.0",
        "input_thresh": "-34.0",
        "target_offset": "0.2",
    }
)
VIDEO_FLAGS = {"-c:v", "-vcodec", "libx264", "-pix_fmt", "-filter:v", "-vf"}


def fake_prober(path: Path) -> MediaInfo:
    if path.suffix == ".mp4":
        return MediaInfo(path, 8.0, 1920, 1080, 30.0, True, True, False)
    return MediaInfo(path, 30.0, 0, 0, 0.0, False, True, False, sample_rate=48000, channels=2)


@pytest.fixture
def media(tmp_path: Path) -> Path:
    for name in ("voz.wav", "musica.wav", "take.mp4"):
        (tmp_path / name).write_bytes(b"x")  # o probe é falso; só precisa existir
    return tmp_path


def audio_project(media: Path, **changes) -> Project:
    spec = {
        "name": "ep",
        "output": {
            "preset": "audio/mp3",
            "audio_format": {"bitrate_k": 192},
            "metadata": {"title": "Episódio", "artist": "Fulano"},
        },
        "audio": {"voiceover": [{"src": "voz.wav"}], "target_lufs": -16},
        "timeline": [],
        "markers": [
            {"start": 0, "end": 10, "text": "Abertura"},
            {"start": 10, "end": 25, "text": "Miolo"},
        ],
        **changes,
    }
    project = Project.model_validate(spec)
    project.base_dir = media
    return project


def pipeline(project: Project, tmp_path: Path, runner=None, **options) -> AudioRenderPipeline:
    return AudioRenderPipeline(
        project,
        RenderOptions(quiet=True, **options),
        runner=runner or RecordingRunner(capture_stderr=LOUDNORM),
        prober=fake_prober,
        cache_dir=tmp_path / "cache",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "out",
    )


def commands(runner) -> list[str]:
    return [" ".join(map(str, c)) for c in runner.commands]


def test_the_preset_type_picks_the_renderer_without_an_if_in_the_caller(media, tmp_path):
    assert isinstance(factory(audio_project(media), RenderOptions()), AudioRenderPipeline)
    video = Project.model_validate({"name": "v", "timeline": [{"type": "card", "title": "t", "duration": 1}]})
    assert isinstance(create_renderer(video, RenderOptions()), RenderPipeline)
    # o preset do pedido (`--preset`) também decide
    assert isinstance(create_renderer(video, RenderOptions(preset="audio/wav")), AudioRenderPipeline)
    assert isinstance(
        create_renderer(audio_project(media), RenderOptions(preset="youtube/shorts")), RenderPipeline
    )


def test_a_narration_alone_renders_with_no_video_at_all(media, tmp_path):
    runner = RecordingRunner(capture_stderr=LOUDNORM)
    result = pipeline(audio_project(media), tmp_path, runner).run()
    lines = commands(runner)
    assert lines, "o render precisa ter rodado ao menos um comando"
    for line in lines:
        assert not VIDEO_FLAGS & set(line.split()), line
        assert "libx264" not in line and ".mp4" not in line and "mezz" not in line.lower()
    final = lines[-1]
    assert "-vn" in final.split() and "libmp3lame" in final and "-b:a 192k" in final
    assert "anullsrc" in final  # a base é um silêncio da duração da voz, no lugar do som dos clipes
    assert "loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=-24.0" in final  # duas passadas, com a medição
    assert result.output == tmp_path / "out" / "ep__audio-mp3.mp3"
    assert result.preset.id == "audio/mp3" and result.duration == 30.0
    assert result.thumbnail is None and result.captions_file is None


def test_the_metadata_of_the_spec_reaches_the_command_in_id3v23(media, tmp_path):
    runner = RecordingRunner(capture_stderr=LOUDNORM)
    pipeline(audio_project(media), tmp_path, runner).run()
    final = commands(runner)[-1]
    assert "-metadata title=Episódio" in final and "-metadata artist=Fulano" in final
    assert "-id3v2_version 3" in final


def test_the_brand_template_fills_what_the_spec_leaves_out(media):
    from dmaker.domain.brand import Theme

    theme = Theme("m", {}, {}, metadata={"artist": "Marca", "album": "Temporada", "comment": "da marca"})
    project = audio_project(media)
    tags, warnings = output_tags(project, theme, get_audio_preset("mp3"))
    assert dict(tags) == {
        "artist": "Fulano",
        "title": "Episódio",
        "album": "Temporada",
        "comment": "da marca",
    }
    assert warnings == []


def test_the_audio_format_of_the_spec_only_applies_to_its_own_preset(media):
    project = audio_project(media)
    assert encoding_for(project, get_audio_preset("mp3")).bitrate_k == 192
    # exportar o mesmo projeto em WAV não herda o 192 kbps do MP3 (nem falha por isso)
    assert encoding_for(project, get_audio_preset("wav")).bit_depth == 16
    over = encoding_for(project, get_audio_preset("mp3"), EncodingChoices(bitrate_k=96))
    assert over.bitrate_k == 96


def test_the_output_goes_to_the_given_path_or_to_output_with_the_preset_in_the_name(media, tmp_path):
    chosen = tmp_path / "x" / "episodio.mp3"
    assert pipeline(audio_project(media), tmp_path, out=chosen).output_path() == chosen.resolve()
    assert pipeline(audio_project(media), tmp_path).output_path() == tmp_path / "out" / "ep__audio-mp3.mp3"
    assert (
        pipeline(audio_project(media), tmp_path, preview=True).output_path().name
        == "ep__audio-mp3__preview.mp3"
    )
    assert (
        pipeline(audio_project(media), tmp_path, preset="audio/flac").output_path().name
        == "ep__audio-flac.flac"
    )


def test_a_project_with_nothing_to_play_says_what_is_missing(media, tmp_path):
    empty = Project.model_validate({"name": "vazio", "output": {"preset": "audio/wav"}})
    with pytest.raises(ValueError, match="nenhum áudio que dê duração"):
        pipeline(empty, tmp_path).run()


def test_a_video_project_can_be_exported_as_audio_and_still_carries_no_video(media, tmp_path):
    video = Project.model_validate(
        {
            "name": "clip",
            "output": {"preset": "instagram/reels"},
            "timeline": [{"type": "clip", "src": "take.mp4"}],
        }
    )
    video.base_dir = media
    runner = RecordingRunner(capture_stderr=LOUDNORM)
    result = pipeline(video, tmp_path, runner, preset="audio/wav").run()
    lines = commands(runner)
    assert result.duration == 8.0 and result.preset.id == "audio/wav"
    assert any("take.mp4" in line for line in lines)  # o som do clipe vira um pedaço de WAV
    for line in lines:
        assert "libx264" not in line and "-c:v" not in line.split()


def test_the_loudness_name_replaces_the_target_of_the_project(media):
    project = audio_project(media)
    assert project_with_loudness(project, "broadcast").audio.target_lufs == -23
    assert project_with_loudness(project, None) is project
    assert project.audio.target_lufs == -16  # o original não é mudado


def test_the_service_asks_for_the_format_when_the_project_is_a_video_one(media):
    video = Project.model_validate({"name": "v", "timeline": [{"type": "card", "title": "t", "duration": 1}]})
    with pytest.raises(ValueError, match="informe o formato do arquivo"):
        audio_preset_name(video, None)
    assert audio_preset_name(video, "mp3") == "audio/mp3"
    assert audio_preset_name(audio_project(media), None) == "audio/mp3"


# ---------- exportação múltipla ----------


def export(project, tmp_path, request, runner=None, **options):
    runner = runner or RecordingRunner(capture_stderr=LOUDNORM)
    return AudioExporter(pipeline(project, tmp_path, runner, **options)).run(request), runner


def test_one_file_per_region_cut_from_a_float_master_and_normalised_one_by_one(media, tmp_path):
    result, runner = export(audio_project(media), tmp_path, ExportRequest(mode="regions"))
    assert [(f.name, f.start, f.duration) for f in result.files] == [
        ("Abertura", 0.0, 10.0),
        ("Miolo", 10.0, 15.0),
    ]
    assert [f.path.name for f in result.files] == ["Abertura.mp3", "Miolo.mp3"]
    assert result.folder == tmp_path / "out" / "ep__audio-mp3__regioes"
    lines = commands(runner)
    assert "pcm_f32le" in lines[0] and "-t 30.000000" in lines[0]  # a referência, uma vez só
    cut = [line for line in lines if "-ss" in line.split() and "audio_master.wav" in line]
    assert len(cut) == 2 * 2  # cada região é medida e depois gravada
    encode = [line for line in cut if "libmp3lame" in line]
    assert len(encode) == 2 and "-ss 10.000000 -t 15.000000" in encode[1]
    assert all(
        "loudnorm" in line and "measured_I" in line for line in encode
    )  # normalizada sozinha, em duas passadas
    assert (
        "-metadata title=Miolo" in encode[1] and "-metadata track=2/2" in encode[1]
    )  # cada arquivo é uma faixa
    for line in lines:
        assert "libx264" not in line and "-c:v" not in line.split()


def test_pauses_between_regions_are_exported_when_asked(media, tmp_path):
    project = audio_project(
        media, markers=[{"start": 2, "end": 5, "text": "A"}, {"start": 8, "end": 9, "text": "B"}]
    )
    result, _ = export(project, tmp_path, ExportRequest(mode="regions", pauses=True))
    assert [(f.name, f.start, f.duration) for f in result.files] == [
        ("pausa-01", 0.0, 2.0),
        ("A", 2.0, 3.0),
        ("pausa-02", 5.0, 3.0),
        ("B", 8.0, 1.0),
    ]


def test_a_region_past_the_end_is_skipped_or_cut_with_a_warning(media, tmp_path):
    project = audio_project(
        media, markers=[{"start": 20, "end": 40, "text": "Longa"}, {"start": 50, "end": 60, "text": "Fora"}]
    )
    result, _ = export(project, tmp_path, ExportRequest(mode="regions"))
    assert [(f.name, f.duration) for f in result.files] == [("Longa", 10.0)]
    assert any("passa do fim" in w for w in result.warnings) and any(
        "depois do fim" in w for w in result.warnings
    )


def test_the_selection_accepts_markers_and_exports_one_file(media, tmp_path):
    result, runner = export(
        audio_project(media), tmp_path, ExportRequest(mode="selection", start="marker:Miolo", end=22.5)
    )
    assert [(f.name, f.start, f.duration) for f in result.files] == [("selecao", 10.0, 12.5)]
    assert result.files[0].path.name == "ep__audio-mp3__selecao.mp3"
    assert any("-ss 10.000000 -t 12.500000" in line for line in commands(runner))


def test_stems_are_one_ffmpeg_run_with_one_output_per_track_and_the_same_linear_gain(media, tmp_path):
    (media / "m.wav").write_bytes(b"x")
    project = audio_project(
        media, audio={"voiceover": [{"src": "voz.wav"}], "music": {"src": "m.wav"}, "target_lufs": -16}
    )
    result, runner = export(project, tmp_path, ExportRequest(mode="stems"))
    assert [(f.track, f.path.name) for f in result.files] == [
        ("VO", "VO-voz-gravada.mp3"),
        ("MUS", "MUS-musica.mp3"),
    ]
    run = commands(runner)[-1]
    assert run.count("-map [stem_out_") == 2
    # o ganho é o da normalização da mixagem (-16 menos -24 = +8 dB), igual nas duas trilhas, sem loudnorm por trilha
    assert run.count("volume=8.000000dB") == 2
    assert "loudnorm" not in run  # nenhuma normalização própria: as trilhas só levam o ganho da mixagem
    assert "anullsink" in run  # a mixagem em si não é gravada
    assert "libx264" not in run and "-c:v" not in run.split()


def test_a_project_without_the_asked_track_fails_clearly(media, tmp_path):
    with pytest.raises(Exception, match="não tem a trilha SFX"):
        export(audio_project(media), tmp_path, ExportRequest(mode="stems", tracks=("SFX",)))


# ---------- onde cada arquivo cai (o que o agente confere antes de sobrescrever) ----------


def test_the_destinations_are_the_same_the_exporter_writes(media, tmp_path):
    project = audio_project(media)
    planned, folder = destinations(
        project, ExportRequest(mode="regions"), get_audio_preset("flac"), output_dir=tmp_path
    )
    assert folder == tmp_path / "ep__audio-flac__regioes"
    assert [path.name for _, path in planned] == ["Abertura.flac", "Miolo.flac"]
    own, _ = destinations(
        project,
        ExportRequest(mode="regions"),
        get_audio_preset("flac"),
        out_dir=tmp_path / "meus",
        output_dir=tmp_path,
    )
    assert own[0][1].parent == tmp_path / "meus"
    mix, none = destinations(
        project, ExportRequest(), get_audio_preset("wav"), out=tmp_path / "a.wav", output_dir=tmp_path
    )
    assert mix[0][1] == tmp_path / "a.wav" and none is None


def test_planned_outputs_read_the_project_without_rendering(media, tmp_path):
    project = audio_project(media)
    paths = planned_outputs(
        "ep", ExportRequest(mode="regions"), output_dir=tmp_path, loader=lambda _: project
    )
    assert [p.name for p in paths] == ["Abertura.mp3", "Miolo.mp3"]
    assert plan_files(project, ExportRequest(mode="selection", start=1, end=2))[0].name == "selecao"
    assert build_pipeline(project, "audio/ogg", loudness="podcast").preset.id == "audio/ogg"


def test_the_timeline_preview_also_mixes_an_audio_only_project(media, tmp_path):
    """A prévia da linha do tempo usa o mesmo grafo: sem trechos, a base é o silêncio da duração do projeto."""
    from dmaker.pipeline.preview_audio import PreviewAudioBuilder

    from .conftest import fake_ffmpeg_output

    runner = RecordingRunner(on_run=fake_ffmpeg_output, capture_stderr=LOUDNORM)
    builder = PreviewAudioBuilder(
        runner=runner, prober=fake_prober, cache_dir=tmp_path / "preview", jobs_dir=tmp_path / "jobs"
    )
    mix = builder.build(audio_project(media))
    assert mix.duration == 30.0 and mix.path.exists()
    final = commands(runner)[-1]
    assert "anullsrc" in final and "-vn" in final.split() and "aac" in final
    assert "libx264" not in final and "-c:v" not in final.split()
