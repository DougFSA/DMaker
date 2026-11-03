"""Serviço `autocut` (`pipeline/autocut.py`) com ffmpeg, probe e Whisper falsos: o áudio sintético é um tom por
palavra, e o transcritor devolve as palavras combinadas com ele."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from dmaker.domain.edits import EditError
from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import FFmpegCommand, RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.media.wavio import write_wav
from dmaker.pipeline.autocut import (
    CAPTIONS_FILE,
    CUT_FADE_SECONDS,
    DISFLUENCY_PROMPT,
    REPORT_FILE,
    TRANSCRIPT_FILE,
    AutoCutRequest,
    AutoCutService,
    clips_from_ranges,
    load_cut_report,
    undo_cut,
    with_refined_words,
)
from dmaker.pipeline.projects import load_project, project_path
from dmaker.text.captions import Cue, Word, from_json
from dmaker.text.transcribe import Transcript
from dmaker.voice.cut_plan import CutOptions

RATE = 16000
TOTAL = 13.5
#                   palavra     início  fim
SCRIPT = [
    ("Então", 0.0, 0.8),
    ("é...", 2.0, 2.3),  # vício isolado por pausa
    ("vamos", 3.5, 4.3),
    ("começar", 4.35, 5.2),
    ("né?", 5.5, 5.8),  # fecha a frase antes de uma pausa
    ("agora", 7.0, 7.6),
    ("Hoje", 9.0, 9.4),  # falso começo
    ("eu", 9.45, 9.6),
    ("vou", 9.65, 10.0),
    ("Hoje", 11.5, 11.9),
    ("eu", 11.95, 12.1),
    ("vou", 12.15, 12.5),
    ("falar", 12.55, 13.5),
]


def recording() -> np.ndarray:
    samples = np.zeros(int(TOTAL * RATE), dtype=np.float32)
    for _, start, end in SCRIPT:
        t = np.arange(int((end - start) * RATE)) / RATE
        samples[int(start * RATE) : int(start * RATE) + len(t)] = 0.3 * np.sin(2 * np.pi * 200 * t)
    return samples


class FakeTranscriber:
    def __init__(self) -> None:
        self.calls = 0
        self.prompts: list[str | None] = []

    def transcribe(self, wav: Path, language: str, initial_prompt: str | None = None) -> Transcript:
        self.calls += 1
        self.prompts.append(initial_prompt)
        words = [Word(start, end, text, 0.9) for text, start, end in SCRIPT]
        return Transcript([Cue(words[0].start, words[-1].end, " ".join(w.text for w in words), words)])


def fake_prober(path: Path) -> MediaInfo:
    return MediaInfo(path, TOTAL, 1920, 1080, 30.0, True, True, False)


def silent_prober(path: Path) -> MediaInfo:
    return MediaInfo(path, TOTAL, 1920, 1080, 30.0, True, False, False)


def writes_the_recording(command: FFmpegCommand) -> None:
    if command.label == "áudio para transcrição":
        write_wav(Path(command.args[-1]), recording(), RATE)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "gravacao.mp4"
    path.write_bytes(b"\x00" * 64)
    return path


def service(transcriber: FakeTranscriber | None = None, prober=fake_prober) -> AutoCutService:
    return AutoCutService(
        runner=RecordingRunner(on_run=writes_the_recording),
        prober=prober,
        transcriber=transcriber or FakeTranscriber(),
    )


def request(source: Path, name: str = "corte", **options) -> AutoCutRequest:
    return AutoCutRequest(source, name, CutOptions(frame_grid=None, **options))


# ---------- o projeto e a lista ----------


def test_cut_builds_a_project_of_clips_of_the_same_recording_and_lists_every_cut(source):
    result = service().cut(request(source, intensity="agressiva"))

    clips = result.project.timeline
    assert {clip.src for clip in clips} == {str(source.resolve())}
    assert all(clip.audio_fade == CUT_FADE_SECONDS for clip in clips)
    assert clips[0].start == 0.0 and clips[-1].end == pytest.approx(TOTAL, abs=0.01)  # o fim é explícito
    reasons = [cut.reason for cut in result.report.cuts]
    assert reasons.count("filler") == 2  # o "é..." e o "né?"
    assert "repetition" in reasons
    assert [cut.id for cut in result.report.cuts] == list(range(1, len(reasons) + 1))
    # quanto sobra é o que os clipes somam
    kept = sum((c.end if c.end is not None else TOTAL) - c.start for c in clips)
    assert kept == pytest.approx(result.report.duration_after, abs=0.01)


def test_the_project_and_the_list_are_saved_next_to_each_other(source):
    result = service().cut(request(source, "meu-corte"))

    folder = project_path("meu-corte").parent
    assert result.spec_path == folder / "spec.json"
    assert load_project("meu-corte").timeline == result.project.timeline
    saved = json.loads((folder / REPORT_FILE).read_text(encoding="utf-8"))
    assert saved["intensity"] == "normal" and saved["cuts"]
    assert (folder / TRANSCRIPT_FILE).exists() and (folder / CAPTIONS_FILE).exists()


def test_intensity_decides_what_is_cut(source):
    soft = service().cut(request(source, "suave", intensity="suave"))
    normal = service().cut(request(source, "normal", intensity="normal"))
    aggressive = service().cut(request(source, "agressiva", intensity="agressiva"))

    assert set(soft.report.counts()) == {"silence"}
    assert set(normal.report.counts()) == {"silence", "filler"}
    assert set(aggressive.report.counts()) == {"filler", "repetition"}  # as pausas saem junto com eles
    assert soft.report.duration_after > normal.report.duration_after > aggressive.report.duration_after


def test_the_transcription_asks_the_whisper_to_keep_the_fillers(source):
    transcriber = FakeTranscriber()
    service(transcriber).cut(request(source))
    assert transcriber.prompts == [DISFLUENCY_PROMPT]


def test_redoing_the_cut_with_another_intensity_reuses_the_transcription(source):
    transcriber = FakeTranscriber()
    cutter = service(transcriber)
    cutter.cut(request(source, "primeiro", intensity="suave"))
    cutter.cut(request(source, "segundo", intensity="agressiva"))
    assert transcriber.calls == 1


def test_the_report_summarizes_before_after_and_counts_by_reason(source):
    report = service().cut(request(source, intensity="agressiva")).report.to_dict()

    assert report["duration_before_s"] == pytest.approx(TOTAL, abs=0.01)
    assert report["duration_after_s"] == pytest.approx(TOTAL - report["removed_s"], abs=0.02)
    assert report["counts"]["filler"] == 2
    first = report["cuts"][0]
    assert {"id", "start_s", "end_s", "duration_s", "reason", "reason_label", "text", "undone"} <= set(first)
    assert first["reason_label"] == "vício de fala" and first["text"] == "é..."


# ---------- legendas ----------


def test_the_captions_follow_the_cut_speech(source):
    result = service().cut(request(source, intensity="agressiva"))

    cues = from_json((project_path("corte").parent / CAPTIONS_FILE).read_text(encoding="utf-8"))
    spoken = [w.text for cue in cues for w in cue.words]
    assert "é..." not in spoken and "né?" not in spoken  # os vícios saíram da legenda
    assert spoken.count("Hoje") == 1  # só a última tomada
    assert spoken[:3] == ["Então", "vamos", "começar"]
    # a primeira palavra depois do primeiro corte começa onde o primeiro clipe termina
    first_clip_length = result.project.timeline[0].end - result.project.timeline[0].start
    vamos = next(w for cue in cues for w in cue.words if w.text == "vamos")
    assert vamos.start == pytest.approx(first_clip_length + 0.15, abs=0.1)


def test_the_project_points_its_captions_at_the_cut_file_or_has_none(source):
    assert service().cut(request(source)).project.captions.source == CAPTIONS_FILE
    plain = AutoCutRequest(source, "sem-legenda", CutOptions(frame_grid=None), captions=False)
    result = service().cut(plain)
    assert (
        result.project.captions is None and not (project_path("sem-legenda").parent / CAPTIONS_FILE).exists()
    )


def test_with_refined_words_keeps_the_cue_structure():
    cues = [Cue(0, 1, "a b", [Word(0, 0.5, "a"), Word(0.5, 1, "b")]), Cue(2, 3, "c", [Word(2, 3, "c")])]
    refined = [Word(0.1, 0.4, "a"), Word(0.6, 0.9, "b"), Word(2.1, 2.9, "c")]
    out = with_refined_words(cues, refined)
    assert [(c.start, c.end, c.text) for c in out] == [(0.1, 0.9, "a b"), (2.1, 2.9, "c")]


# ---------- desfazer ----------


def test_undoing_a_cut_gives_the_removed_stretch_back_and_rejoins_the_clips(source):
    result = service().cut(request(source, intensity="agressiva"))
    clips_before = len(result.project.timeline)
    filler = next(cut for cut in result.report.cuts if cut.reason == "filler")

    report = undo_cut("corte", filler.id)

    assert report.find(filler.id).undone
    restored = load_project("corte")
    assert len(restored.timeline) == clips_before - 1
    assert any(c.start <= filler.start and (c.end or TOTAL) >= filler.end for c in restored.timeline)
    assert report.duration_after == pytest.approx(result.report.duration_after + filler.duration, abs=0.01)
    assert load_cut_report(project_path("corte").parent).find(filler.id).undone  # ficou salvo


def test_undoing_a_cut_brings_its_words_back_to_the_captions(source):
    result = service().cut(request(source, intensity="agressiva"))
    filler = next(cut for cut in result.report.cuts if cut.reason == "filler" and "é" in cut.text)
    path = project_path("corte").parent / CAPTIONS_FILE
    assert "é..." not in [w.text for cue in from_json(path.read_text(encoding="utf-8")) for w in cue.words]

    undo_cut("corte", filler.id)

    assert "é..." in [w.text for cue in from_json(path.read_text(encoding="utf-8")) for w in cue.words]


def test_undoing_the_head_and_tail_cuts_extends_the_edge_clips(source):
    # o áudio termina com fala em 13,5 s; a cabeça (0 a 0,0) não tem pausa: força cortes nas pontas por opção
    result = service().cut(request(source, "pontas", intensity="suave", min_pause=0.3))
    assert result.report.cuts
    for cut in list(result.report.cuts):
        undo_cut("pontas", cut.id)
    (clip,) = load_project("pontas").timeline
    assert clip.start == 0.0 and clip.end == pytest.approx(TOTAL, abs=0.01)


def test_undoing_twice_or_an_unknown_cut_is_an_error_in_portuguese(source):
    result = service().cut(request(source))
    undo_cut("corte", result.report.cuts[0].id)
    with pytest.raises(ValueError, match="já foi desfeito"):
        undo_cut("corte", result.report.cuts[0].id)
    with pytest.raises(ValueError, match="não há o corte 99"):
        undo_cut("corte", 99)


def test_undo_refuses_when_the_timeline_no_longer_has_the_neighbour_clips(source):
    from dmaker.domain.edits import insert_segment
    from dmaker.pipeline.projects import save_project

    result = service().cut(request(source))
    project = load_project("corte")
    save_project(
        insert_segment(project, 1, {"type": "card", "title": "no meio", "duration": 1.0}), project.base_dir
    )
    with pytest.raises(EditError, match="vizinhos"):
        undo_cut("corte", result.report.cuts[0].id)


def test_undo_on_a_project_that_was_not_cut_says_so(tmp_path):
    from dmaker.pipeline.projects import save_project

    save_project(Project.model_validate({"name": "avulso", "timeline": [{"type": "clip", "src": "a.mp4"}]}))
    with pytest.raises(ValueError, match="não tem lista de cortes"):
        undo_cut("avulso", 1)


# ---------- pedidos que não dão certo ----------


def test_cut_fails_before_transcribing_when_the_request_cannot_work(source, tmp_path):
    transcriber = FakeTranscriber()
    cutter = service(transcriber)
    with pytest.raises(FileNotFoundError, match="não encontrada"):
        cutter.cut(AutoCutRequest(tmp_path / "nao-existe.mp4", "x"))
    with pytest.raises(ValueError):
        cutter.cut(AutoCutRequest(source, "nome/invalido"))
    with pytest.raises(KeyError):
        cutter.cut(AutoCutRequest(source, "x", preset="plataforma/inexistente"))
    cutter.cut(request(source, "existente"))
    with pytest.raises(ValueError, match="já existe um projeto"):
        cutter.cut(request(source, "existente"))
    assert transcriber.calls == 1  # só o corte que deu certo transcreveu


def test_overwrite_replaces_an_existing_project(source):
    cutter = service()
    cutter.cut(request(source, "refazer", intensity="suave"))
    again = AutoCutRequest(
        source, "refazer", CutOptions(frame_grid=None, intensity="agressiva"), overwrite=True
    )
    assert cutter.cut(again).report.intensity == "agressiva"
    assert load_cut_report(project_path("refazer").parent).intensity == "agressiva"


def test_a_recording_without_audio_is_refused(source):
    with pytest.raises(ValueError, match="não tem áudio"):
        service(prober=silent_prober).cut(request(source))


def test_warns_when_there_is_no_speech_or_nothing_to_cut(source):
    class Mute:
        def transcribe(self, wav, language, initial_prompt=None):
            return Transcript([])

    assert "não encontrou fala" in service(Mute()).cut(request(source, "mudo")).warnings[0]
    other = source.with_name("outra.mp4")
    other.write_bytes(b"\x00" * 64)
    nothing = service().cut(request(other, "nada", min_pause=60.0, intensity="suave"))
    assert nothing.report.cuts == [] and "Nada passou do limite" in nothing.warnings[0]
    assert len(nothing.project.timeline) == 1


def test_clips_from_ranges_gives_every_clip_an_explicit_end_and_the_audio_fade():
    clips = clips_from_ranges(Path("g.mp4"), [(0.0, 2.0), (3.0, 10.0)])
    assert [(c.start, c.end, c.audio_fade) for c in clips] == [(0.0, 2.0, 0.01), (3.0, 10.0, 0.01)]
