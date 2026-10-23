"""Narração: cache de falas, tempos das legendas, comando de montagem e SRT."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker.media.ffmpeg import RecordingRunner
from dmaker.pipeline.narration import NarrationService, cue_timeline
from dmaker.voice.library import VoiceLibrary
from dmaker.voice.pronunciation import Lexicon
from dmaker.voice.script import Utterance
from dmaker.voice.synth import Speech, VoiceRequest

SAMPLE_RATE = 24000


class FakeSynthesizer:
    """Seno cuja duração é proporcional ao texto (0,05 s por caractere), contando chamadas."""

    engine_id = "fake-1"

    def __init__(self):
        self.requests: list[VoiceRequest] = []

    def synthesize(self, request: VoiceRequest) -> Speech:
        self.requests.append(request)
        count = int(len(request.text) * 0.05 * SAMPLE_RATE)
        t = np.arange(count) / SAMPLE_RATE
        return Speech((0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), SAMPLE_RATE)


def _service(tmp_path, synthesizer=None, runner=None, log=None):
    synthesizer = synthesizer or FakeSynthesizer()

    def on_run(command):
        Path(command.args[-1]).write_bytes(b"audio")

    runner = runner or RecordingRunner(on_run=on_run)
    return NarrationService(synthesizer, runner, tmp_path / "cache", log), synthesizer, runner


TEXT = "Primeira fala completa aqui. Segunda fala também completa.\n\nTerceira em outro parágrafo."


def test_cue_timeline_adds_pauses_but_not_after_last():
    cues, total = cue_timeline(
        [(1.0, Utterance("a", 0.5)), (2.0, Utterance("b", 0.7)), (1.5, Utterance("c", 0.0))]
    )
    assert cues == [(0.0, 1.0, "a"), (1.5, 3.5, "b"), (4.2, 5.7, "c")]
    assert total == 5.7
    assert cue_timeline([]) == ([], 0.0)


def test_render_builds_cues_with_real_durations_and_pauses(tmp_path):
    service, synthesizer, runner = _service(tmp_path)
    out = tmp_path / "saida" / "narracao.wav"

    result = service.render(TEXT, out, voice=None)

    assert [r.text for r in synthesizer.requests] == [
        "Primeira fala completa aqui.",
        "Segunda fala também completa.",
        "Terceira em outro parágrafo.",
    ]
    first, second, third = (len(r.text) * 0.05 for r in synthesizer.requests)
    assert [c[2] for c in result.cues] == [r.text for r in synthesizer.requests]
    assert result.cues[0][:2] == pytest.approx((0.0, first), abs=1e-3)
    assert result.cues[1][0] == pytest.approx(first + 0.35, abs=1e-3)  # pausa de frase
    assert result.cues[2][0] == pytest.approx(first + 0.35 + second + 0.7, abs=1e-3)  # pausa de parágrafo
    assert result.duration == pytest.approx(first + second + third + 0.35 + 0.7, abs=1e-3)
    assert result.path == out and result.srt_path is None


def test_render_concatenates_cached_files_in_order(tmp_path):
    service, _, runner = _service(tmp_path)
    out = tmp_path / "narracao.mp3"
    service.render(TEXT, out, voice=None)

    command = runner.commands[0]
    inputs = [command[i + 1] for i, arg in enumerate(command) if arg == "-i"]
    assert len(inputs) == 3 and all(Path(p).parent == tmp_path / "cache" for p in inputs)
    graph = command[command.index("-filter_complex") + 1]
    assert "apad=pad_dur=0.350[p0]" in graph and "apad=pad_dur=0.700[p1]" in graph
    assert "concat=n=3:v=0:a=1[joined]" in graph and graph.endswith("[out]")
    assert command[command.index("-c:a") + 1] == "libmp3lame" and command[-1] == str(out)


def test_second_render_does_not_call_the_synthesizer(tmp_path):
    service, synthesizer, runner = _service(tmp_path)
    service.render(TEXT, tmp_path / "a.wav", voice=None)
    calls = len(synthesizer.requests)
    again = service.render(TEXT, tmp_path / "b.wav", voice=None)
    assert calls == 3 and len(synthesizer.requests) == 3
    assert len(runner.commands) == 2 and again.duration > 0


def test_repeated_sentence_is_synthesized_once(tmp_path):
    service, synthesizer, _ = _service(tmp_path)
    service.render("Mesma frase. Mesma frase. Mesma frase.", tmp_path / "a.wav", voice=None)
    assert len(synthesizer.requests) == 1


@pytest.mark.parametrize(
    "change", [{"speed": 1.2}, {"seed": 7}, {"language": "en"}, {"instruct": "female"}, {"steps": 8}]
)
def test_any_synthesis_parameter_invalidates_the_cache(tmp_path, change):
    service, synthesizer, _ = _service(tmp_path)
    service.render("Uma frase só.", tmp_path / "a.wav", voice=None)
    service.render("Uma frase só.", tmp_path / "b.wav", voice=None, **change)
    assert len(synthesizer.requests) == 2


def test_engine_and_voice_are_part_of_the_cache_key(tmp_path):
    library = VoiceLibrary(tmp_path / "voices")
    ana = library.save_design("Ana", "female")
    bia = library.save_design("Bia", "male")
    service, synthesizer, _ = _service(tmp_path)
    service.render("Uma frase só.", tmp_path / "a.wav", voice=ana)
    service.render("Uma frase só.", tmp_path / "b.wav", voice=bia)
    assert len(synthesizer.requests) == 2

    other_engine = FakeSynthesizer()
    other_engine.engine_id = "fake-2"
    again, _, _ = _service(tmp_path, other_engine)
    again.render("Uma frase só.", tmp_path / "c.wav", voice=ana)
    assert len(other_engine.requests) == 1


def test_numbers_are_spoken_but_cue_keeps_the_original_text(tmp_path):
    pytest.importorskip("num2words")
    service, synthesizer, _ = _service(tmp_path)
    result = service.render("Custa R$ 19,90.", tmp_path / "a.wav", voice=None)
    assert synthesizer.requests[0].text == "Custa dezenove reais e noventa centavos."
    assert result.cues[0][2] == "Custa R$ 19,90."


def test_srt_is_written_next_to_the_audio_when_requested(tmp_path):
    service, _, _ = _service(tmp_path)
    result = service.render(TEXT, tmp_path / "narracao.wav", voice=None, write_srt=True)
    assert result.srt_path == tmp_path / "narracao.srt"
    srt = result.srt_path.read_text(encoding="utf-8")
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,400\nPrimeira fala completa aqui.")
    assert srt.count("-->") == 3


def test_progress_reports_each_utterance(tmp_path):
    messages: list[str] = []
    steps: list[tuple[int, int]] = []
    service, _, _ = _service(tmp_path, log=messages.append)
    service.render(TEXT, tmp_path / "a.wav", voice=None, on_progress=lambda i, n: steps.append((i, n)))
    assert steps == [(1, 3), (2, 3), (3, 3)]
    assert messages[:3] == ["Fala 1 de 3", "Fala 2 de 3", "Fala 3 de 3"]


def test_empty_text_is_rejected(tmp_path):
    service, synthesizer, runner = _service(tmp_path)
    with pytest.raises(ValueError, match="vazio"):
        service.render("   ", tmp_path / "a.wav", voice=None)
    assert synthesizer.requests == [] and runner.commands == []


def _lexicon_service(tmp_path, lexicons):
    def on_run(command):
        Path(command.args[-1]).write_bytes(b"audio")

    synthesizer = FakeSynthesizer()
    service = NarrationService(
        synthesizer, RecordingRunner(on_run=on_run), tmp_path / "cache", lexicons=lexicons
    )
    return service, synthesizer


def test_pronunciation_changes_what_is_synthesized_but_cues_and_srt_keep_the_written_text(tmp_path):
    lexicon = Lexicon.of({"DMaker": "Di Meiker"})
    service, synthesizer = _lexicon_service(tmp_path, lambda _brand, _language: lexicon)

    result = service.render("O DMaker edita vídeos.", tmp_path / "a.wav", voice=None, write_srt=True)

    assert synthesizer.requests[0].text == "O Di Meiker edita vídeos."
    assert result.cues[0][2] == "O DMaker edita vídeos."
    assert "O DMaker edita vídeos." in result.srt_path.read_text(encoding="utf-8")


def test_inline_override_is_spoken_but_the_cue_shows_the_term(tmp_path):
    service, synthesizer = _lexicon_service(
        tmp_path, lambda _brand, _language: Lexicon.of({"DMaker": "Di Meiker"})
    )

    result = service.render(
        "Fale [[DMaker|Dimêiker]] agora. Depois [[Samanta]] sorri.", tmp_path / "a.wav", voice=None
    )

    assert [r.text for r in synthesizer.requests] == ["Fale Dimêiker agora.", "Depois Samanta sorri."]
    assert [cue[2] for cue in result.cues] == ["Fale DMaker agora.", "Depois Samanta sorri."]


def test_brand_selects_the_lexicon_and_changing_it_invalidates_the_cache(tmp_path):
    asked: list[str | None] = []
    spellings = {None: "Di Meiker", "medlycare": "Dimêiker"}

    def lexicons(brand, _language):
        asked.append(brand)
        return Lexicon.of({"DMaker": spellings[brand]})

    service, synthesizer = _lexicon_service(tmp_path, lexicons)
    service.render("Uma frase com DMaker.", tmp_path / "a.wav", voice=None)
    service.render("Uma frase com DMaker.", tmp_path / "b.wav", voice=None)  # mesma pronúncia: vem do cache
    service.render("Uma frase com DMaker.", tmp_path / "c.wav", voice=None, brand="medlycare")

    assert asked == [None, None, "medlycare"]
    assert [r.text for r in synthesizer.requests] == ["Uma frase com Di Meiker.", "Uma frase com Dimêiker."]


def test_cached_duration_follows_the_same_pronunciation_as_render(tmp_path):
    service, _ = _lexicon_service(tmp_path, lambda _brand, _language: Lexicon.of({"DMaker": "Di Meiker"}))
    assert service.cached_duration("Uma frase com DMaker.", None) is None

    rendered = service.render("Uma frase com DMaker.", tmp_path / "a.wav", voice=None)

    assert service.cached_duration("Uma frase com DMaker.", None) == pytest.approx(rendered.duration)
    other, _ = _lexicon_service(
        tmp_path, lambda _brand, _language: Lexicon()
    )  # sem a troca o texto é outro: não está no cache
    assert other.cached_duration("Uma frase com DMaker.", None) is None


def test_without_a_lexicon_provider_the_text_is_spoken_as_written(tmp_path):
    service, synthesizer, _ = _service(tmp_path)
    service.render("O DMaker edita.", tmp_path / "a.wav", voice=None, brand="medlycare")
    assert synthesizer.requests[0].text == "O DMaker edita."


def test_forced_duration_is_part_of_the_cache_key_and_is_cached_per_duration(tmp_path):
    service, synthesizer, _ = _service(tmp_path)
    short = VoiceRequest(text="Mesma frase.", duration=2.0)
    long = VoiceRequest(text="Mesma frase.", duration=3.5)
    assert not service.is_cached(short)
    service.speak(short)
    assert service.is_cached(short) and not service.is_cached(long)
    service.speak(long)
    service.speak(short)
    assert len(synthesizer.requests) == 2
    assert (
        service.cache_key(short)
        != service.cache_key(long)
        != service.cache_key(VoiceRequest(text="Mesma frase."))
    )


def test_the_language_of_the_speech_selects_which_pronunciation_applies(tmp_path):
    asked: list[tuple[str | None, str | None]] = []
    portuguese_only = {"pt": Lexicon.of({"DMaker": "Di Mêiker"})}

    def lexicons(brand, language):
        asked.append((brand, language))
        return portuguese_only.get(language, Lexicon())

    service, synthesizer = _lexicon_service(tmp_path, lexicons)
    service.render("Conheça o DMaker hoje.", tmp_path / "a.wav", voice=None, language="pt")
    service.render("Meet the DMaker today.", tmp_path / "b.wav", voice=None, language="en")

    assert asked == [(None, "pt"), (None, "en")]
    assert [r.text for r in synthesizer.requests] == ["Conheça o Di Mêiker hoje.", "Meet the DMaker today."]


def test_cached_duration_asks_the_lexicon_for_the_language_of_the_speech(tmp_path):
    asked: list[str | None] = []

    def lexicons(_brand, language):
        asked.append(language)
        return Lexicon()

    service, _ = _lexicon_service(tmp_path, lexicons)
    service.cached_duration("Hello there my friend.", None, language="en")

    assert asked == ["en"]


def test_inline_override_wins_in_any_language_even_without_an_entry(tmp_path):
    service, synthesizer = _lexicon_service(tmp_path, lambda _brand, _language: Lexicon())

    result = service.render("Say [[DMaker|Dee Maker]] now.", tmp_path / "a.wav", voice=None, language="en")

    assert synthesizer.requests[0].text == "Say Dee Maker now."
    assert result.cues[0][2] == "Say DMaker now."
