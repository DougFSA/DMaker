"""A etiqueta de procedência nos arquivos que o DMaker grava com voz gerada: render, narração, dublagem,
correção de fala e troca de voz (runner gravado, sem ffmpeg nem modelo)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from dmaker.domain.dub import load_dub_project
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.voice.provenance import PROVENANCE_PREFIX, parse_provenance, provenance_text
from dmaker.voice.watermark import NullWatermarker
from tests.test_dubbing import DubHarness
from tests.test_pipeline_unit import LOUDNORM_JSON, FakeSynthesizer, _narrated_pipeline, touch_output
from tests.test_speech_fix import Harness, video_info
from tests.test_voice_batch import CHAPTERS
from tests.test_voice_batch import Harness as BatchHarness
from tests.test_voice_conversion_service import ServiceHarness
from tests.test_voice_watermark import FakeWatermarker

from .conftest import concat_commands, fake_ffmpeg_output


def metadata(args) -> list[str]:
    args = list(args)
    return [args[i + 1] for i, arg in enumerate(args) if arg == "-metadata"]


def label_of(args) -> str:
    """O texto da etiqueta que o comando grava (sem o `comment=` do ffmpeg)."""
    (value,) = metadata(args)
    assert value.startswith("comment=") and value != "comment="
    return value.removeprefix("comment=")


def rounded(spans) -> list[tuple[float, float]]:
    return [(round(start, 2), round(end, 2)) for start, end in spans]


# ---------- render do projeto ----------


def render_final(tmp_path: Path, watermarker, **change):
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    pipeline = _narrated_pipeline(tmp_path, FakeSynthesizer(), runner)
    pipeline.narrator.watermarker = watermarker
    if change:
        pipeline.project.audio.narration[0] = pipeline.project.audio.narration[0].model_copy(update=change)
    pipeline.run()
    return next(command for command in runner.commands if "-shortest" in command)


def test_render_labels_the_video_with_where_the_narration_plays(tmp_path):
    final = render_final(tmp_path, FakeWatermarker())

    found = parse_provenance({"comment": label_of(final)})
    assert found is not None and len(found.spans) == 1
    start, end = found.spans[0]
    assert start == 0.5 and 1.0 < end - start < 2.5  # a fala de 21 letras começa em 0,5 s
    assert final.index("-metadata") < final.index("-shortest")  # opção de saída, antes do arquivo


def test_render_without_the_mark_has_no_label_and_clears_an_inherited_one(tmp_path):
    final = render_final(tmp_path, NullWatermarker())
    assert metadata(final) == ["comment="]


def test_render_with_the_library_missing_still_labels(tmp_path):
    final = render_final(tmp_path, NullWatermarker(provenance=True))
    assert label_of(final).startswith(PROVENANCE_PREFIX)


def test_a_narration_that_starts_after_the_video_declares_no_synthetic_voice(tmp_path):
    final = render_final(tmp_path, FakeWatermarker(), start=7.0)  # o vídeo tem 6 s
    assert metadata(final) == ["comment="]


def test_a_silent_narration_declares_no_synthetic_voice(tmp_path):
    final = render_final(tmp_path, FakeWatermarker(), volume=0.0)
    assert metadata(final) == ["comment="]


def test_a_render_without_narration_has_no_label():
    from types import SimpleNamespace

    from dmaker.pipeline.renderer import RenderPipeline

    marked = SimpleNamespace(narrator=SimpleNamespace(provenance=lambda spans, total: "nunca chamada"))
    assert RenderPipeline._provenance(SimpleNamespace(narrator=None), [], 6.0) == ""  # noqa: SLF001
    assert RenderPipeline._provenance(marked, [], 6.0) == ""  # noqa: SLF001


# ---------- narração em arquivo ----------


def narrated_file(tmp_path: Path, watermarker):
    from dmaker.pipeline.narration import NarrationService
    from tests.test_voice_watermark import FakeSynthesizer as TinySynthesizer

    runner = RecordingRunner(on_run=fake_ffmpeg_output)
    service = NarrationService(TinySynthesizer(), runner, tmp_path / "cache", watermarker=watermarker)
    service.render("Uma fala curta.", tmp_path / "narracao.m4a", None, master=False)
    return concat_commands(runner)[-1]


def test_a_narration_file_declares_the_whole_file(tmp_path):
    command = narrated_file(tmp_path, FakeWatermarker())
    assert label_of(command) == PROVENANCE_PREFIX and command[-1].endswith("narracao.m4a")


def test_a_narration_file_without_the_mark_has_no_label(tmp_path):
    assert metadata(narrated_file(tmp_path, NullWatermarker())) == []


def test_the_complete_audio_of_a_batch_narration_is_labeled_too(tmp_path, monkeypatch):
    harness = BatchHarness(tmp_path, monkeypatch)
    harness.service.watermarker = FakeWatermarker()
    item = harness.enqueue(chapters=CHAPTERS)

    harness.narrator.process(item)

    assert label_of(concat_commands(harness.runner)[-1]) == PROVENANCE_PREFIX


# ---------- dublagem ----------


@pytest.fixture
def dub(tmp_path: Path) -> DubHarness:
    harness = DubHarness(tmp_path)
    harness.base.service.narrator.watermarker = FakeWatermarker()
    return harness


def test_dubbing_labels_the_file_where_each_dubbed_line_plays(dub: DubHarness):
    dub.prepare()
    result = dub.service.render(load_dub_project(dub.project_path), dub.out)

    (mix,) = dub.mix_commands()
    expected = [(r.retimed_start, r.retimed_start + r.played_seconds) for r in result.report]
    found = parse_provenance({"comment": label_of(mix.args)})
    assert found is not None and rounded(found.spans) == rounded(expected) and len(expected) == 3


def test_dubbing_without_the_mark_has_no_label(tmp_path: Path):
    plain = DubHarness(tmp_path)
    plain.prepare()
    plain.service.render(load_dub_project(plain.project_path), plain.out)
    (mix,) = plain.mix_commands()
    assert metadata(mix.args) == ["comment="]  # nenhuma etiqueta herdada do vídeo de origem


def test_the_separated_tracks_label_only_the_dubbed_voice(dub: DubHarness):
    dub.service.export_stems(dub.prepare())

    (command,) = dub.labeled("trilhas")
    values = metadata(command.args)
    assert len(values) == 1 and values[0].startswith("comment=" + PROVENANCE_PREFIX)
    index = command.args.index("-metadata")
    assert Path(command.args[index + 2]).name == "voz-dublada.wav"


# ---------- correção de fala ----------


def fix_command(harness: Harness) -> list[str]:
    harness.service.fix(harness.request())
    return next(c for c in harness.runner.commands if "-filter_complex" in c)


def test_speech_fix_labels_the_new_speech_in_the_corrected_file(tmp_path: Path):
    harness = Harness(tmp_path)
    harness.service.narrator.watermarker = FakeWatermarker()

    result = harness.service.fix(harness.request())

    command = next(c for c in harness.runner.commands if "-filter_complex" in c)
    found = parse_provenance({"comment": label_of(command)})
    assert found is not None and len(found.spans) == 1
    start, end = found.spans[0]
    assert result.region_start <= start < end <= result.region_end


def test_speech_fix_keeps_what_the_file_already_declared(tmp_path: Path):
    harness = Harness(tmp_path)
    harness.service.narrator.watermarker = FakeWatermarker()
    earlier = provenance_text([(1.0, 2.0)])
    harness.service.prober = lambda path: replace(video_info(path), format_tags={"comment": earlier})

    found = parse_provenance({"comment": label_of(fix_command(harness))})

    assert found is not None and found.spans[0] == (1.0, 2.0) and len(found.spans) == 2


def test_speech_fix_of_a_file_that_was_all_synthetic_stays_all_synthetic(tmp_path: Path):
    harness = Harness(tmp_path)
    harness.service.narrator.watermarker = FakeWatermarker()
    harness.service.prober = lambda path: replace(
        video_info(path), format_tags={"comment": provenance_text()}
    )
    assert label_of(fix_command(harness)) == PROVENANCE_PREFIX


def test_speech_fix_without_the_mark_adds_nothing(tmp_path: Path):
    harness = Harness(tmp_path)
    assert metadata(fix_command(harness)) == []


# ---------- troca de voz ----------


def test_voice_swap_declares_the_whole_file_when_the_mark_is_on(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("dmaker.config.VOICE_CACHE_DIR", tmp_path / "voice-cache")
    monkeypatch.setattr("dmaker.config.OUTPUT_DIR", tmp_path / "output")
    harness = ServiceHarness(tmp_path / "media", watermarker=FakeWatermarker())

    harness.conversion.convert(harness.request())

    assert label_of(harness.swap_command()) == PROVENANCE_PREFIX


def test_voice_swap_without_the_mark_clears_an_inherited_label(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("dmaker.config.VOICE_CACHE_DIR", tmp_path / "voice-cache")
    monkeypatch.setattr("dmaker.config.OUTPUT_DIR", tmp_path / "output")
    harness = ServiceHarness(tmp_path / "media")

    harness.conversion.convert(harness.request())

    assert metadata(harness.swap_command()) == ["comment="]
