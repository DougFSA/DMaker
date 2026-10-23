"""Isolamento vocal no pipeline: cache dos stems, comando de extração, exportação e uso em clipes
(`audio_mode`) com separador falso e RecordingRunner, sem Demucs nem ffmpeg."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.spec import Project
from dmaker.filtergraph.stems import convert_stem, extract_for_separation
from dmaker.media.ffmpeg import FFmpegCommand, RecordingRunner
from dmaker.media.separation import Stems
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.isolation import IsolationService, export_name, progress_logger
from dmaker.pipeline.segments import MEZZ_VERSION
from tests.test_pipeline_unit import LOUDNORM_JSON, FakeTranscriber, fake_prober, touch_output


class FakeSeparator:
    """Grava os dois stems com um texto e conta as separações."""

    def __init__(self, model_id: str = "fake:1") -> None:
        self.model_id = model_id
        self.calls: list[Path] = []
        self.fail = False

    def separate(self, wav: Path, out_dir: Path, on_progress=None) -> Stems:
        self.calls.append(wav)
        assert wav.exists()  # a extração do ffmpeg já aconteceu
        if on_progress:
            on_progress(1, 2)
            on_progress(2, 2)
        if self.fail:
            raise RuntimeError("modelo quebrou")
        stems = Stems.in_directory(out_dir)
        stems.vocals.write_bytes(b"voz")
        stems.background.write_bytes(b"fundo")
        return stems


def write_wav_output(command: FFmpegCommand) -> None:
    out = Path(command.args[-1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"audio")


@pytest.fixture
def media(tmp_path: Path) -> Path:
    path = tmp_path / "entrevista.mp4"
    path.write_bytes(b"video")
    return path


@pytest.fixture
def separator() -> FakeSeparator:
    return FakeSeparator()


@pytest.fixture
def runner() -> RecordingRunner:
    return RecordingRunner(on_run=write_wav_output)


@pytest.fixture
def service(tmp_path: Path, separator: FakeSeparator, runner: RecordingRunner) -> IsolationService:
    return IsolationService(separator, runner, cache_dir=tmp_path / "stems")


# ---------- comandos ----------


def test_extraction_command_cuts_the_window_and_converts_to_stereo_44k(tmp_path: Path):
    command = extract_for_separation(tmp_path / "v.mp4", tmp_path / "o.wav", 5.0, 15.0, audio_stream=1)
    args = " ".join(command.args)
    assert args.startswith("-ss 5.000 -t 10.000 -i ")
    assert "-map 0:a:1 -vn -ac 2 -ar 44100 -c:a pcm_s16le" in args
    assert command.args[-1] == str(tmp_path / "o.wav") and command.total == 10.0


def test_extraction_command_without_window_takes_the_whole_file(tmp_path: Path):
    command = extract_for_separation(tmp_path / "v.mp4", tmp_path / "o.wav")
    assert "-ss" not in command.args and "-t" not in command.args and command.total is None


def test_extraction_with_only_an_end_starts_at_zero(tmp_path: Path):
    command = extract_for_separation(tmp_path / "v.mp4", tmp_path / "o.wav", None, 7.5)
    assert "-ss" not in command.args and command.args[:2] == ["-t", "7.500"]


def test_convert_stem_picks_the_codec_from_the_extension(tmp_path: Path):
    assert "libmp3lame" in convert_stem(tmp_path / "a.wav", tmp_path / "a.mp3").args
    with pytest.raises(ValueError):
        convert_stem(tmp_path / "a.wav", tmp_path / "a.ogg")


# ---------- cache ----------


def test_second_call_comes_from_the_cache(service, separator, runner, media):
    first = service.isolate(media, 2, 12)
    second = service.isolate(media, 2, 12)

    assert first == second and first.exist()
    assert len(separator.calls) == 1 and len(runner.commands) == 1
    assert first.vocals.read_bytes() == b"voz" and first.background.read_bytes() == b"fundo"
    assert not list(first.vocals.parent.parent.glob("*.tmp"))  # sem pasta temporária sobrando
    assert not (first.vocals.parent / "input.wav").exists()  # o WAV de entrada não fica no cache


def test_window_audio_stream_and_model_are_part_of_the_key(service, separator, media):
    service.isolate(media, 0, 10)
    service.isolate(media, 0, 10)
    assert len(separator.calls) == 1
    service.isolate(media, 0, 11)  # outro fim
    service.isolate(media, 1, 10)  # outro início
    service.isolate(media, 0, 10, audio_stream=1)  # outra faixa de áudio
    service.isolate(media)  # arquivo todo
    assert len(separator.calls) == 5

    other_model = IsolationService(FakeSeparator("fake:2"), service.runner, cache_dir=service.cache_dir)
    assert other_model.stems_for(media, 0, 10) != service.stems_for(media, 0, 10)


def test_changing_the_file_invalidates_the_cache(service, separator, media):
    service.isolate(media, 0, 5)
    media.write_bytes(b"video editado, maior")
    service.isolate(media, 0, 5)
    assert len(separator.calls) == 2


def test_times_are_compared_at_millisecond_precision(service, media):
    assert service.stems_for(media, 1.00001, 2.0) == service.stems_for(media, 1.0, 2.0)
    assert service.stems_for(media, 1.01, 2.0) != service.stems_for(media, 1.0, 2.0)


def test_stems_for_never_separates_or_runs_ffmpeg(service, separator, runner, media):
    stems = service.stems_for(media, 0, 5)
    assert not stems.exist() and separator.calls == [] and runner.commands == []


def test_failed_separation_leaves_nothing_in_the_cache(service, separator, media):
    separator.fail = True
    with pytest.raises(RuntimeError, match="quebrou"):
        service.isolate(media, 0, 5)
    assert not service.stems_for(media, 0, 5).exist()
    assert not list(service.cache_dir.glob("*.tmp"))
    separator.fail = False
    assert service.isolate(media, 0, 5).exist()  # e uma nova tentativa funciona


def test_progress_is_forwarded_to_the_caller(service, media):
    calls = []
    service.isolate(media, 0, 5, on_progress=lambda done, total: calls.append((done, total)))
    assert calls == [(1, 2), (2, 2)]


def test_invalid_requests_fail_before_any_work(service, separator, runner, tmp_path: Path, media):
    with pytest.raises(FileNotFoundError):
        service.isolate(tmp_path / "nao-existe.mp4")
    with pytest.raises(ValueError, match="maior que start"):
        service.isolate(media, 10, 10)
    with pytest.raises(ValueError, match="negativo"):
        service.isolate(media, -1, 10)
    assert separator.calls == [] and runner.commands == []


# ---------- exportação ----------


def test_export_names_carry_the_window():
    src = Path("C:/v/entrevista.mp4")
    assert export_name(src, "voz", "wav") == "entrevista_voz.wav"
    assert export_name(src, "fundo", "mp3", 0, 30) == "entrevista_0-30s_fundo.mp3"
    assert export_name(src, "voz", "wav", 12.5, None) == "entrevista_12.5-fims_voz.wav"


def test_export_wav_copies_the_stems(service, runner, media, tmp_path: Path):
    stems = service.export(media, tmp_path / "saida", start=0, end=30)

    assert stems.vocals.name == "entrevista_0-30s_voz.wav" and stems.vocals.read_bytes() == b"voz"
    assert stems.background.name == "entrevista_0-30s_fundo.wav" and stems.background.read_bytes() == b"fundo"
    assert len(runner.commands) == 1  # só a extração: wav é cópia


def test_export_mp3_converts_each_stem_with_the_runner(service, runner, media, tmp_path: Path):
    service.export(media, tmp_path / "saida", "mp3")
    conversions = [c for c in runner.commands if "libmp3lame" in c]
    assert len(conversions) == 2
    assert {Path(c[-1]).name for c in conversions} == {"entrevista_voz.mp3", "entrevista_fundo.mp3"}


# ---------- progresso no log ----------


def test_progress_logger_writes_one_line_per_step():
    lines: list[str] = []
    report = progress_logger(lines.append, "separação", step=25)
    for done in range(0, 11):
        report(done, 10)
    assert [line.split("(")[1] for line in lines] == ["0%)", "25%)", "50%)", "75%)", "100%)"]
    assert lines[0].startswith("separação: 0 de 10")


# ---------- uso nos trechos do projeto ----------


@pytest.fixture
def clip_project(tmp_path: Path) -> Project:
    (tmp_path / "take.mp4").write_bytes(b"x")
    spec = {
        "name": "iso-unit",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 2, "end": 4, "audio_mode": "voice"}],
        "captions": {"enabled": False},
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    return project


def _pipeline(project: Project, runner: RecordingRunner, isolator: IsolationService, **options):
    d = project.base_dir
    return RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=d / "out.mp4", **options),
        runner=runner,
        prober=fake_prober,
        transcriber_factory=lambda captions: FakeTranscriber(),
        isolator=isolator,
        cache_dir=d / "mez",
        jobs_dir=d / "jobs",
        output_dir=d / "output",
    )


def _run_runner() -> RecordingRunner:
    return RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)


def _mezzanine(runner: RecordingRunner) -> str:
    return next(" ".join(c) for c in runner.commands if c[-1].endswith(".mov"))


def test_clip_with_voice_mode_reads_the_vocals_stem(clip_project: Project, tmp_path: Path):
    separator = FakeSeparator()
    runner = _run_runner()
    isolator = IsolationService(separator, runner, cache_dir=tmp_path / "stems")
    _pipeline(clip_project, runner, isolator).run()

    stems = isolator.stems_for(tmp_path / "take.mp4", 2.0, 4.0)
    assert len(separator.calls) == 1
    extraction = next(" ".join(c) for c in runner.commands if "pcm_s16le" in c and "-ss 2.000" in " ".join(c))
    assert "-t 2.000" in extraction
    mezzanine = _mezzanine(runner)
    assert str(stems.vocals) in mezzanine and str(stems.background) not in mezzanine
    assert "[1:a:0]" in mezzanine and "[0:a:0]" not in mezzanine  # a câmera vem do stem, não da fonte


def test_background_mode_reads_the_background_stem(clip_project: Project, tmp_path: Path):
    clip_project.timeline[0].audio_mode = "background"
    runner = _run_runner()
    isolator = IsolationService(FakeSeparator(), runner, cache_dir=tmp_path / "stems")
    _pipeline(clip_project, runner, isolator).run()
    stems = isolator.stems_for(tmp_path / "take.mp4", 2.0, 4.0)
    assert str(stems.background) in _mezzanine(runner)


def test_speed_extends_the_isolated_window(clip_project: Project, tmp_path: Path):
    clip_project.timeline[0].end = None  # até o fim da fonte (8 s no probe falso)
    clip_project.timeline[0].speed = 2.0  # 3 s de vídeo consomem 6 s de fonte
    runner = _run_runner()
    isolator = IsolationService(FakeSeparator(), runner, cache_dir=tmp_path / "stems")
    _pipeline(clip_project, runner, isolator).run()
    extraction = next(" ".join(c) for c in runner.commands if "pcm_s16le" in c)
    assert "-ss 2.000 -t 6.000" in extraction


def test_original_mode_never_touches_the_isolator(clip_project: Project, tmp_path: Path):
    clip_project.timeline[0].audio_mode = "original"
    separator = FakeSeparator()
    runner = _run_runner()
    isolator = IsolationService(separator, runner, cache_dir=tmp_path / "stems")
    _pipeline(clip_project, runner, isolator).run()
    assert separator.calls == [] and "[0:a:0]" in _mezzanine(runner)


def test_default_isolator_is_built_only_when_a_clip_asks(clip_project: Project, tmp_path: Path, monkeypatch):
    built = []

    def shared_separator() -> FakeSeparator:
        built.append(1)
        return FakeSeparator()

    monkeypatch.setattr("dmaker.pipeline.isolation.shared_separator", shared_separator)
    clip_project.timeline[0].audio_mode = "original"
    RenderPipeline(
        clip_project, RenderOptions(dry_run=True, quiet=True), runner=RecordingRunner(), prober=fake_prober
    ).run()
    assert built == []

    clip_project.timeline[0].audio_mode = "voice"
    RenderPipeline(
        clip_project, RenderOptions(dry_run=True, quiet=True), runner=RecordingRunner(), prober=fake_prober
    ).run()
    assert built == [1]


def test_mezzanine_is_cached_and_the_separation_skipped_on_the_second_render(
    clip_project: Project, tmp_path: Path
):
    separator = FakeSeparator()
    first_runner = _run_runner()
    isolator = IsolationService(separator, first_runner, cache_dir=tmp_path / "stems")
    _pipeline(clip_project, first_runner, isolator).run()
    second_runner = _run_runner()
    _pipeline(
        clip_project, second_runner, IsolationService(separator, second_runner, cache_dir=tmp_path / "stems")
    ).run()

    assert len(separator.calls) == 1
    assert not any(c[-1].endswith(".mov") for c in second_runner.commands)  # mezanino veio do cache


def test_stems_survive_a_cleaned_mezzanine_cache(clip_project: Project, tmp_path: Path):
    """Apagar o cache de mezaninos refaz o mezanino, mas não a separação (que é o passo caro)."""
    separator = FakeSeparator()
    runner = _run_runner()
    isolator = IsolationService(separator, runner, cache_dir=tmp_path / "stems")
    _pipeline(clip_project, runner, isolator).run()
    for mezzanine in (tmp_path / "mez").glob("*.mov"):
        mezzanine.unlink()
    again = _run_runner()
    _pipeline(clip_project, again, IsolationService(separator, again, cache_dir=tmp_path / "stems")).run()
    assert len(separator.calls) == 1 and any(c[-1].endswith(".mov") for c in again.commands)


def test_mezzanine_key_changes_with_the_audio_mode_and_the_recipe(clip_project: Project, tmp_path: Path):
    def mezzanine_name(mode: str) -> str:
        clip_project.timeline[0].audio_mode = mode
        runner = _run_runner()
        isolator = IsolationService(FakeSeparator(), runner, cache_dir=tmp_path / "stems")
        _pipeline(clip_project, runner, isolator, dry_run=True).run()
        return Path(_mezzanine(runner).split()[-1]).name

    names = {mezzanine_name(mode) for mode in ("original", "voice", "background")}
    assert len(names) == 3
    assert MEZZ_VERSION != "m4"  # a receita do mezanino mudou com o audio_mode


def test_dry_run_plans_the_stems_without_separating(clip_project: Project, tmp_path: Path):
    separator = FakeSeparator()
    runner = RecordingRunner()
    isolator = IsolationService(separator, runner, cache_dir=tmp_path / "stems")
    _pipeline(clip_project, runner, isolator, dry_run=True).run()

    assert separator.calls == []
    stems = isolator.stems_for(tmp_path / "take.mp4", 2.0, 4.0)
    assert str(stems.vocals) in _mezzanine(runner)


def test_muted_clip_ignores_the_audio_mode(clip_project: Project, tmp_path: Path):
    clip_project.timeline[0].mute = True
    separator = FakeSeparator()
    runner = _run_runner()
    _pipeline(clip_project, runner, IsolationService(separator, runner, cache_dir=tmp_path / "stems")).run()
    assert separator.calls == []


def test_lint_warns_when_audio_mode_has_nothing_to_isolate(clip_project: Project, tmp_path: Path):
    from dmaker.domain.brand import load_theme
    from dmaker.domain.presets import get_preset
    from dmaker.media.probe import MediaInfo
    from dmaker.pipeline.lint import lint

    def warnings_for(info: MediaInfo) -> list[str]:
        return lint(clip_project, load_theme(None, None), get_preset("instagram/reels"), 2.0, [2.0], [info])

    silent = MediaInfo(tmp_path / "take.mp4", 20.0, 1080, 1920, 30.0, True, False, False)
    assert any("audio_mode 'voice'" in w and "não tem áudio" in w for w in warnings_for(silent))
    talking = MediaInfo(tmp_path / "take.mp4", 20.0, 1080, 1920, 30.0, True, True, False)
    assert not any("audio_mode" in w for w in warnings_for(talking))
    clip_project.timeline[0].mute = True
    assert any("está mudo" in w for w in warnings_for(talking))
