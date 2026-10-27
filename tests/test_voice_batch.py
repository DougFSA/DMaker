"""Narração em lote: um áudio por capítulo, o completo com pausa e legenda, e a retomada sem ressintetizar."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from dmaker import config
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.pipeline.narration import NarrationService
from dmaker.pipeline.voice_batch import BatchNarrator, no_guard
from dmaker.pipeline.voice_queue import PAUSED, ItemInterrupted, QueueOptions, VoiceQueue
from dmaker.text.captions import parse_srt
from dmaker.voice.library import VoiceLibrary
from dmaker.voice.manuscript import Chapter
from dmaker.voice.synth import DRAFT_STEPS
from tests.test_narration import FakeSynthesizer

from .conftest import concat_commands, fake_ffmpeg_output, finish_commands

# frases com mais de 20 caracteres: cada uma vira uma fala (as curtas se juntam à seguinte)
CHAPTERS = [
    Chapter("A origem", "Primeira frase do primeiro capítulo. Segunda frase do primeiro capítulo."),
    Chapter(
        "O meio",
        "Terceira frase do segundo capítulo. Quarta frase do segundo capítulo. Quinta frase deste mesmo capítulo.",
    ),
    Chapter("O fim", "Sexta frase do terceiro capítulo."),
]


class Harness:
    def __init__(self, tmp_path: Path, monkeypatch, synthesizer=None, guard=no_guard) -> None:
        monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
        self.queue = VoiceQueue(tmp_path / "cache" / "voice_queue.json")
        self.synthesizer = synthesizer or FakeSynthesizer()
        self.runner = RecordingRunner(on_run=fake_ffmpeg_output)
        self.service = NarrationService(self.synthesizer, self.runner, tmp_path / "voice-cache")
        self.clock_now = 0.0
        self.narrator = BatchNarrator(
            self.queue,
            self.service,
            self.runner,
            VoiceLibrary(tmp_path / "voices"),
            guard,
            clock=lambda: self.clock_now,
        )

    def enqueue(self, chapters=CHAPTERS, title="Meu livro", **options):
        item = self.queue.add(title, chapters, QueueOptions(**options), "text")
        return self.queue.claim_next() if self.queue.get(item.id).state == "pending" else item


@pytest.fixture
def harness(tmp_path, monkeypatch) -> Harness:
    return Harness(tmp_path, monkeypatch)


# ---------- saída ----------


def test_three_chapters_produce_three_files_plus_the_complete_audio_and_its_srt(harness):
    item = harness.enqueue()

    output = harness.narrator.process(item)

    folder = Path(item.output_dir)
    assert output.files == [
        "01-a-origem.wav",
        "02-o-meio.wav",
        "03-o-fim.wav",
        "meu-livro-completo.wav",
        "meu-livro-completo.srt",
    ]
    assert all((folder / name).exists() for name in output.files[:4])
    # três capítulos montados + o completo: tudo passa pelo runner, nada de ffmpeg direto
    assert len(concat_commands(harness.runner)) == 4


def test_the_complete_audio_joins_the_chapters_in_order_with_a_pause_between_them_only(harness):
    item = harness.enqueue()
    harness.narrator.process(item)

    complete = concat_commands(harness.runner)[-1]
    inputs = [Path(complete[index + 1]).name for index, arg in enumerate(complete) if arg == "-i"]
    assert inputs == ["01-a-origem.wav", "02-o-meio.wav", "03-o-fim.wav"]
    graph = complete[complete.index("-filter_complex") + 1]
    assert graph.count("apad=pad_dur=1.500") == 2  # depois do 1 e do 2; o último não ganha silêncio
    assert "acompressor" not in graph  # o acabamento broadcast já foi aplicado em cada capítulo
    finishes = finish_commands(harness.runner)  # cada fala dos capítulos ganhou o acabamento, antes da marca
    assert finishes and all("acompressor" in command[command.index("-af") + 1] for command in finishes)


def test_complete_srt_shifts_each_chapter_by_the_previous_durations_and_the_gap(harness):
    item = harness.enqueue()
    output = harness.narrator.process(item)

    cues = parse_srt((Path(item.output_dir) / "meu-livro-completo.srt").read_text(encoding="utf-8"))
    texts = [c.text for c in cues]
    assert texts == [
        "Primeira frase do primeiro capítulo.",
        "Segunda frase do primeiro capítulo.",
        "Terceira frase do segundo capítulo.",
        "Quarta frase do segundo capítulo.",
        "Quinta frase deste mesmo capítulo.",
        "Sexta frase do terceiro capítulo.",
    ]
    # a fake fala 0,05 s por caractere: o capítulo 1 dura as suas duas falas mais a pausa de frase entre elas
    first = len(texts[0]) * 0.05 + 0.35 + len(texts[1]) * 0.05
    assert cues[2].start == pytest.approx(first + 1.5, abs=0.01)
    assert cues[0].start == 0.0
    assert output.duration == pytest.approx(cues[-1].end, abs=0.01)
    assert all(a.end <= b.start for a, b in zip(cues, cues[1:], strict=False))  # nenhuma legenda se atropela


def test_a_single_chapter_script_makes_only_the_complete_file_with_its_srt(harness):
    item = harness.enqueue(chapters=[Chapter("Só um", "Uma única fala longa o bastante para existir.")])

    output = harness.narrator.process(item)

    assert output.files == ["meu-livro-completo.wav", "meu-livro-completo.srt"]
    assert len(concat_commands(harness.runner)) == 1


def test_mp3_format_and_draft_steps_reach_the_files_and_the_synthesizer(harness):
    item = harness.enqueue(chapters=CHAPTERS[:2], draft=True, audio_format="mp3")

    output = harness.narrator.process(item)

    assert output.files[0].endswith(".mp3") and output.files[2] == "meu-livro-completo.mp3"
    assert {request.steps for request in harness.synthesizer.requests} == {DRAFT_STEPS}


def test_voice_language_speed_and_brand_come_from_the_item(harness):
    item = harness.enqueue(chapters=CHAPTERS[:1], voice="dora", speed=1.2, language="en")

    harness.narrator.process(item)

    request = harness.synthesizer.requests[0]
    assert request.voice.id == "dora" and request.speed == 1.2 and request.language == "en"
    assert request.steps is None  # qualidade final: o motor escolhe o padrão dele


def test_chapters_with_nothing_to_say_are_skipped_without_breaking_the_book(harness):
    item = harness.enqueue(chapters=[CHAPTERS[0], Chapter("Só símbolos", "[pausa 1.2]"), CHAPTERS[2]])

    output = harness.narrator.process(item)

    assert output.files[:2] == ["01-a-origem.wav", "03-o-fim.wav"]


# ---------- andamento ----------


def test_progress_is_recorded_in_the_queue_for_every_utterance(harness):
    item = harness.enqueue()
    seen: list[tuple[int, int, int, int, int]] = []
    original = harness.synthesizer.synthesize

    def spy(request):
        now = harness.queue.get(item.id)
        seen.append((now.chapter, now.utterance, now.utterances, now.utterances_done, now.chars_left))
        return original(request)

    harness.synthesizer.synthesize = spy
    harness.narrator.process(item)

    chars = [len(r.text) for r in harness.synthesizer.requests]
    # (capítulo, fala, falas do capítulo, falas prontas no item, caracteres que faltam) quando cada fala começa
    assert seen[0] == (1, 1, 2, 0, sum(chars))
    assert seen[1] == (1, 2, 2, 1, sum(chars) - chars[0])
    assert seen[2][:4] == (2, 1, 3, 2)
    assert seen[-1][:3] == (3, 1, 1)
    final = harness.queue.get(item.id)
    assert final.utterances_total == 6 and final.chapters_total == 3


def test_speed_is_measured_per_synthesized_utterance_but_not_for_the_last_one_of_a_chapter(harness):
    item = harness.enqueue()
    original = harness.synthesizer.synthesize

    def slow(request):
        harness.clock_now += 3.0
        return original(request)

    harness.synthesizer.synthesize = slow
    harness.narrator.process(item)

    samples = harness.queue.samples("omnivoice:final")
    chars = [len(r.text) for r in harness.synthesizer.requests]
    # 6 falas; a última de cada um dos 3 capítulos não entra (o tempo dela inclui a montagem)
    assert samples == [(chars[0], 3.0), (chars[2], 3.0), (chars[3], 3.0)]


def test_samples_are_kept_separately_for_ready_made_voices_and_for_drafts(harness):
    harness.narrator.process(harness.enqueue(chapters=CHAPTERS[:2], voice="dora", draft=True))
    assert harness.queue.samples("kokoro:draft")
    assert harness.queue.samples("omnivoice:final") == []


def test_synthesis_guard_is_held_only_around_each_uncached_utterance(tmp_path, monkeypatch):
    events: list[str] = []

    @contextmanager
    def guard(_note):
        events.append("entra")
        yield
        events.append("sai")

    harness = Harness(tmp_path, monkeypatch, guard=guard)
    original = harness.synthesizer.synthesize

    def record(request):
        events.append("sintetiza")
        return original(request)

    harness.synthesizer.synthesize = record
    item = harness.enqueue(chapters=CHAPTERS[:1])
    harness.narrator.process(item)
    assert events == ["entra", "sintetiza", "sai", "entra", "sintetiza", "sai"]

    events.clear()
    harness.queue.finish(item.id, [], 0.0)
    harness.queue.add("Repete", CHAPTERS[:1], QueueOptions(), "text")
    harness.narrator.process(harness.queue.claim_next())
    assert events == []  # tudo no cache: nem a trava é tocada


def test_waiting_for_the_lock_is_shown_in_the_item_note_and_cleared_afterwards(tmp_path, monkeypatch):
    notes: list[str] = []

    @contextmanager
    def busy_guard(note):
        note("Aguardando outro trabalho de voz terminar")
        yield

    harness = Harness(tmp_path, monkeypatch, guard=busy_guard)
    item = harness.enqueue(chapters=CHAPTERS[:1])
    original = harness.synthesizer.synthesize

    def spy(request):
        notes.append(harness.queue.get(item.id).note)
        return original(request)

    harness.synthesizer.synthesize = spy
    harness.narrator.process(item)

    assert notes == ["", ""]  # a nota some assim que a trava é conquistada e a fala começa
    assert harness.queue.get(item.id).note == ""


# ---------- retomada ----------


def test_pausing_midway_stops_at_the_next_utterance_and_resuming_never_resynthesizes(tmp_path, monkeypatch):
    harness = Harness(tmp_path, monkeypatch)
    item = harness.enqueue()
    original = harness.synthesizer.synthesize

    def pause_on_third(request):
        if len(harness.synthesizer.requests) == 2:  # a terceira chamada acontece com o usuário pausando
            harness.queue.pause(item.id)
        return original(request)

    harness.synthesizer.synthesize = pause_on_third

    with pytest.raises(ItemInterrupted):
        harness.narrator.process(item)

    first_run = [r.text for r in harness.synthesizer.requests]
    assert len(first_run) == 3  # a fala em andamento terminou e foi para o cache; a próxima nem começou
    assert harness.queue.get(item.id).state == PAUSED

    harness.queue.resume(item.id)
    resumed = harness.queue.claim_next()
    output = harness.narrator.process(resumed)

    second_run = [r.text for r in harness.synthesizer.requests][3:]
    assert len(second_run) == 3  # as outras três falas do livro
    assert set(first_run).isdisjoint(second_run)  # nenhuma fala foi sintetizada duas vezes
    assert len(harness.synthesizer.requests) == 6
    assert output.files[-2:] == ["meu-livro-completo.wav", "meu-livro-completo.srt"]


def test_a_second_run_over_a_half_done_chapter_only_synthesizes_the_missing_utterances(tmp_path, monkeypatch):
    """O processo cai (o item fica `rodando`) no meio do capítulo; o worker novo refaz sem repetir falas."""
    harness = Harness(tmp_path, monkeypatch)
    item = harness.enqueue(chapters=CHAPTERS[1:2])  # um capítulo, três falas
    original = harness.synthesizer.synthesize

    class Crash(BaseException):
        """Como um processo morto: nada do `process` tem a chance de arrumar o estado."""

    def die_on_third(request):
        if len(harness.synthesizer.requests) == 2:
            raise Crash
        return original(request)

    harness.synthesizer.synthesize = die_on_third
    with pytest.raises(Crash):
        harness.narrator.process(item)
    assert len(harness.synthesizer.requests) == 2  # duas falas saíram; a terceira morreu antes de gerar áudio
    assert harness.queue.get(item.id).state == "running"  # ninguém atualizou: igual a um kill

    harness.synthesizer.synthesize = original
    assert harness.queue.requeue_interrupted() == 1
    harness.narrator.process(harness.queue.claim_next())

    texts = [r.text for r in harness.synthesizer.requests]
    assert (
        texts.count("Quinta frase deste mesmo capítulo.") == 1
    )  # só a que morreu foi sintetizada na retomada
    assert texts.count("Terceira frase do segundo capítulo.") == 1
    assert texts.count("Quarta frase do segundo capítulo.") == 1
    assert len(texts) == 3


def test_cancelling_before_the_first_utterance_interrupts_without_synthesizing(harness):
    item = harness.enqueue()
    harness.queue.cancel(item.id)

    with pytest.raises(ItemInterrupted):
        harness.narrator.process(item)

    assert harness.synthesizer.requests == []
    assert harness.runner.commands == []
