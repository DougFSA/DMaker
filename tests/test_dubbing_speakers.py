"""Dublagem com uma voz por pessoa (per_speaker): diarizador falso, tudo o mais como em test_dubbing.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from dmaker.domain.dub import load_dub_project
from dmaker.media.diarization import SpeakerTurn
from dmaker.pipeline.dubbing import default_dubbing_service, project_summary, report_dict
from tests.test_dubbing import S1, S2, S3, DubHarness

ANA, BIA = "Falante 1", "Falante 2"
# S1 (2 a 5,6 s) e S3 (14 a 18,1 s) são da Ana; S2 (8 a 10,6 s) é da Bia
TWO_PEOPLE = [SpeakerTurn(0.0, 7.0, ANA), SpeakerTurn(7.0, 13.0, BIA), SpeakerTurn(13.0, 20.0, ANA)]


class FakeDiarizer:
    model_id = "diarizador-falso"

    def __init__(self, turns: list[SpeakerTurn]):
        self.turns = turns
        self.calls: list[tuple[Path, int | None]] = []

    def diarize(self, wav: Path, num_speakers: int | None = None, on_progress=None) -> list[SpeakerTurn]:
        self.calls.append((wav, num_speakers))
        if on_progress:
            on_progress(1, 2)
            on_progress(2, 2)
        return self.turns


@pytest.fixture
def dub(tmp_path: Path) -> DubHarness:
    harness = DubHarness(tmp_path)
    harness.diarizer = FakeDiarizer(TWO_PEOPLE)
    harness.service.diarizer = harness.diarizer
    return harness


# ---------- preparar ----------


def test_prepare_defaults_to_per_speaker_when_there_is_a_diarizer_and_labels_every_phrase(dub: DubHarness):
    project = dub.prepare()
    assert project.speaker_mode == "per_speaker" and project.speaker_names == [ANA, BIA]
    assert [s.speaker for s in project.segments] == [ANA, BIA, ANA]
    assert load_dub_project(dub.project_path) == project


def test_the_reference_of_each_speaker_is_stored_from_only_their_own_words(dub: DubHarness):
    project = dub.prepare()
    ana, bia = project.speakers
    assert (ana.reference_start, ana.reference_text.split()[0]) == (
        pytest.approx(14.0),
        "Depois",
    )  # a fala mais longa
    assert (bia.reference_start, bia.reference_text.split()[0]) == (pytest.approx(8.0), "Primeiro")
    assert S1.split()[0] not in ana.reference_text and ana.reference_text in S3


def test_prepare_diarizes_the_voice_stem_at_16k_and_passes_the_requested_count(dub: DubHarness):
    dub.prepare(num_speakers=2)
    (wav, count) = dub.diarizer.calls[0]
    assert count == 2 and wav.suffix == ".wav"
    extractions = dub.labeled("áudio para transcrição")
    assert len(extractions) == 2  # a transcrição e a diarização, as duas pelo ffmpeg do runner
    assert (
        "16000" in extractions[1].args
        and "vocals.wav" in extractions[1].args[extractions[1].args.index("-i") + 1]
    )
    assert not wav.exists()  # o WAV temporário não fica


def test_the_turns_are_cached_per_stem_and_per_requested_count(dub: DubHarness):
    dub.prepare()
    dub.prepare()
    assert len(dub.diarizer.calls) == 1
    dub.prepare(num_speakers=2)
    assert len(dub.diarizer.calls) == 2


def test_prepare_logs_the_diarization_time_as_a_factor_of_the_duration(dub: DubHarness):
    messages: list[str] = []
    dub.service.log = messages.append
    dub.prepare()
    line = next(m for m in messages if m.startswith("Diarização: 2 falante(s)"))
    assert "x a duração" in line


def test_prepare_reports_the_diarization_stage_in_order(dub: DubHarness):
    seen: list[tuple[str, float]] = []
    dub.prepare(on_progress=lambda label, fraction: seen.append((label, fraction)))
    labels = [label for label, _ in seen]
    assert "Separando quem fala" in labels and labels.index("Separando quem fala") < labels.index(
        "Traduzindo a fala 1 de 3"
    )
    assert [f for _, f in seen] == sorted(f for _, f in seen)


def test_without_a_diarizer_the_default_is_the_old_per_segment_mode(tmp_path: Path):
    plain = DubHarness(tmp_path)
    project = plain.prepare()
    assert project.speaker_mode == "per_segment" and project.speakers == []
    assert [s.speaker for s in project.segments] == [None, None, None]


def test_per_speaker_without_a_diarizer_and_a_count_in_other_modes_are_refused(
    tmp_path: Path, dub: DubHarness
):
    plain = DubHarness(tmp_path / "outro")
    with pytest.raises(ValueError, match="diarização não está disponível"):
        plain.prepare(speaker_mode="per_speaker")
    with pytest.raises(ValueError, match="só vale no modo per_speaker"):
        dub.prepare(speaker_mode="single", num_speakers=2)
    with pytest.raises(ValueError, match="1 ou mais"):
        dub.prepare(num_speakers=0)
    assert dub.diarizer.calls == [] and plain.base.isolation.calls == []


def test_the_old_modes_do_not_diarize(dub: DubHarness):
    for mode in ("per_segment", "single"):
        project = dub.prepare(speaker_mode=mode)
        assert project.speakers == [] and all(s.speaker is None for s in project.segments)
    assert dub.diarizer.calls == []


def test_a_single_voice_in_the_audio_keeps_one_speaker(dub: DubHarness):
    dub.diarizer.turns = [SpeakerTurn(0.0, 20.0, ANA)]
    project = dub.prepare()
    assert project.speaker_names == [ANA] and {s.speaker for s in project.segments} == {ANA}


def test_the_summary_lists_the_speakers_and_the_speaker_of_each_segment(dub: DubHarness):
    summary = project_summary(dub.prepare(), dub.project_path)
    assert summary["speakers"] == [ANA, BIA] and summary["speaker_mode"] == "per_speaker"
    assert [s["speaker"] for s in summary["segments"]] == [ANA, BIA, ANA]


# ---------- gerar ----------


def test_each_person_gets_one_clone_and_the_voices_alternate_with_the_speakers(dub: DubHarness):
    result = dub.service.render(dub.prepare(), dub.out)
    voices = [r.voice for r in dub.synthesizer.requests]
    assert voices[0] == voices[2] != voices[1]  # Ana, Bia, Ana
    references = [r.voice.reference_text for r in dub.synthesizer.requests]
    assert references[0] == references[2] and references[0] in S3 and references[1] in S2
    assert [r.speaker for r in result.report] == [ANA, BIA, ANA]
    assert len(dub.labeled("referência do falante")) == 2  # um recorte por pessoa, não um por fala
    assert [r.voice.name for r in dub.synthesizer.requests] == [ANA, BIA, ANA]


def test_the_reference_comes_from_the_stored_span_not_from_the_phrase_being_dubbed(dub: DubHarness):
    dub.service.render(dub.prepare(), dub.out)
    cuts = dub.labeled("referência do falante")
    starts = sorted(float(c.args[c.args.index("-ss") + 1]) for c in cuts)
    assert starts[0] == pytest.approx(8.0, abs=0.3) and starts[1] == pytest.approx(14.0, abs=0.3)


def test_changing_the_speaker_of_one_segment_regenerates_only_that_segment(dub: DubHarness):
    project = dub.prepare()
    first = dub.service.render(project, dub.out)
    assert first.regenerated == 3
    again = dub.service.render(project, dub.out)
    assert again.regenerated == 0

    swapped = project.edited("s3", speaker=BIA)
    third = dub.service.render(swapped, dub.out)
    assert third.regenerated == 1 and [r.cached for r in third.report] == [True, True, False]
    assert (
        dub.synthesizer.requests[-1].voice.reference_text == dub.synthesizer.requests[1].voice.reference_text
    )
    assert [r.speaker for r in third.report] == [ANA, BIA, BIA]


def test_the_stored_reference_keeps_the_other_voices_stable_when_a_speaker_is_swapped(dub: DubHarness):
    project = dub.prepare()
    dub.service.render(project, dub.out)
    ana_voice = dub.synthesizer.requests[0].voice.id
    # a Bia ganha a fala mais longa da Ana; se a referência fosse recalculada, a voz da Ana mudaria e as falas dela voltariam
    swapped = project.edited("s3", speaker=BIA)
    result = dub.service.render(swapped, dub.out)
    assert result.report[0].cached and result.report[0].voice == ana_voice


def test_a_library_voice_still_wins_over_every_speaker(dub: DubHarness):
    dub.base.library.save_design("Locutora", "female, low pitch", language="en")
    project = dub.prepare(voice="locutora")
    dub.service.render(project, dub.out)
    assert {r.voice.id for r in dub.synthesizer.requests} == {"locutora"}
    assert dub.labeled("referência do falante") == []


def test_with_one_speaker_per_speaker_behaves_like_single(dub: DubHarness):
    dub.diarizer.turns = [SpeakerTurn(0.0, 20.0, ANA)]
    dub.service.render(dub.prepare(), dub.out)
    assert len({r.voice.id for r in dub.synthesizer.requests}) == 1
    assert len(dub.labeled("referência do falante")) == 1


def test_a_speaker_without_three_seconds_of_clean_speech_falls_back_to_the_voice_around_each_line(
    dub: DubHarness,
):
    dub.diarizer.turns = [
        SpeakerTurn(0.0, 7.0, ANA),
        SpeakerTurn(7.0, 10.0, BIA),
        SpeakerTurn(10.0, 20.0, ANA),
    ]
    project = dub.prepare()
    assert project.segment("s2").speaker == BIA
    assert project.speakers[1].reference_start is None  # a Bia só tem 2 s seguidos de fala sua
    messages: list[str] = []
    dub.service.log = messages.append
    dub.service.render(project, dub.out)
    assert any("Falante 2: sem 3 s seguidos" in m for m in messages)
    assert len(dub.synthesizer.requests) == 3


def test_the_speaker_shows_up_in_the_report_dictionary(dub: DubHarness):
    result = dub.service.render(dub.prepare(), dub.out)
    assert report_dict(result.report[1])["speaker"] == BIA and report_dict(result.report[1])[
        "voice"
    ].startswith("falante-")


def test_the_per_segment_mode_still_clones_around_each_line(dub: DubHarness):
    result = dub.service.render(dub.prepare(speaker_mode="per_segment"), dub.out)
    assert len({r.voice.id for r in dub.synthesizer.requests}) == 3  # uma referência por fala
    assert all(r.speaker == "" for r in result.report)


# ---------- montagem do serviço ----------


def default_service(dub: DubHarness, **extra):
    return default_dubbing_service(
        dub.runner,
        library=dub.base.library,
        transcriber=dub.base.transcriber,
        isolation=dub.base.isolation,
        synthesizer=dub.synthesizer,
        translator=dub.translator,
        prober=dub.base.service.prober,
        **extra,
    )


def test_default_service_uses_the_given_diarizer(dub: DubHarness):
    assert default_service(dub, diarizer=dub.diarizer).diarizer is dub.diarizer


def test_the_off_switch_and_a_missing_sherpa_turn_the_default_diarizer_off(dub: DubHarness, monkeypatch):
    monkeypatch.setenv("DMAKER_DIARIZATION", "off")
    assert default_service(dub).diarizer is None
    monkeypatch.delenv("DMAKER_DIARIZATION")
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    assert default_service(dub).diarizer is None


@pytest.mark.skipif(
    importlib.util.find_spec("sherpa_onnx") is None, reason="sherpa-onnx não instalado (.[voice])"
)
def test_the_default_diarizer_is_the_local_sherpa_one(dub: DubHarness, monkeypatch):
    monkeypatch.delenv("DMAKER_DIARIZATION")
    diarizer = default_service(dub).diarizer
    assert diarizer is not None and diarizer.model_id.startswith("sherpa:")
