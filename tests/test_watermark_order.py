"""A marca d'água é a última transformação da voz: acabamento e andamento rodam antes dela, uma vez por fala.

Os dublês registram a ordem dos eventos (comando do ffmpeg e marca) para provar o invariante de
`voice/watermark.py` sem carregar o modelo. A prova com a AudioSeal de verdade está em
`test_voice_watermark_smoke.py`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker.filtergraph.voice import BROADCAST_MASTER_FILTERS, SpeechFinish
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.wavio import read_wav
from dmaker.pipeline.narration import NarrationService
from dmaker.voice.synth import Speech, VoiceRequest
from dmaker.voice.watermark import NullWatermarker, WatermarkResult

from .conftest import concat_commands, fake_ffmpeg_output, finish_commands
from .test_dubbing import DubHarness, stretched_project
from .test_speech_fix import SPEECH_RATE, FakeSynthesizer, Harness

SAMPLE_RATE = 24000
FINISH_LABEL = "acabamento da fala"


class OrderedWatermarker:
    """Soma um deslocamento e anota cada marca na mesma lista em que o runner anota os comandos."""

    identity = "ordem:1"
    OFFSET = 0.05

    def __init__(self, events: list[str]):
        self.events = events
        self.peaks_received: list[float] = []

    def embed(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        self.events.append("marca")
        self.peaks_received.append(float(np.abs(samples).max()))
        return (samples + self.OFFSET).astype(np.float32)

    def detect(self, samples: np.ndarray, sample_rate: int) -> WatermarkResult:
        return WatermarkResult(0.0, False)


class ToneSynthesizer:
    engine_id = "fake-ordem"

    def synthesize(self, request: VoiceRequest) -> Speech:
        t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
        return Speech((0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), SAMPLE_RATE)


def recording(runner: RecordingRunner, events: list[str]) -> None:
    """Faz o runner gravado anotar o rótulo de cada comando na lista de eventos antes de simular o efeito."""
    original = runner.on_run

    def on_run(command) -> None:
        events.append(command.label)
        if original:
            original(command)

    runner.on_run = on_run


def narration(tmp_path: Path) -> tuple[NarrationService, OrderedWatermarker, RecordingRunner, list[str]]:
    events: list[str] = []
    runner = RecordingRunner(on_run=fake_ffmpeg_output)
    recording(runner, events)
    marker = OrderedWatermarker(events)
    service = NarrationService(ToneSynthesizer(), runner, tmp_path / "cache", watermarker=marker)
    return service, marker, runner, events


# ---------- narração ----------


TEXT = "Primeira fala completa aqui. Segunda fala também completa."


def test_narration_finishes_each_utterance_before_marking_it_and_joins_dry(tmp_path):
    service, _marker, runner, events = narration(tmp_path)

    service.render(TEXT, tmp_path / "saida.wav", voice=None)

    assert events == [FINISH_LABEL, "marca", FINISH_LABEL, "marca", "narração"]
    (assembly,) = concat_commands(runner)
    graph = assembly[assembly.index("-filter_complex") + 1]
    for filter_name in BROADCAST_MASTER_FILTERS:
        assert filter_name not in graph
    for command in finish_commands(runner):
        assert command[command.index("-af") + 1] == ",".join(BROADCAST_MASTER_FILTERS)


def test_narration_without_master_only_marks_and_joins(tmp_path):
    service, _marker, runner, events = narration(tmp_path)

    service.render(TEXT, tmp_path / "saida.wav", voice=None, master=False)

    assert events == ["marca", "marca", "narração"] and finish_commands(runner) == []


def test_the_preview_of_each_utterance_is_the_finished_and_marked_file(tmp_path):
    service, marker, _runner, _events = narration(tmp_path)
    heard: list[Path] = []

    service.render(
        TEXT, tmp_path / "saida.wav", voice=None, on_utterance=lambda _i, _n, path, *_: heard.append(path)
    )

    assert len(heard) == 2
    for path in heard:
        samples, _rate = read_wav(path)
        assert np.isclose(np.abs(samples).max(), 0.3 + marker.OFFSET, atol=1e-3)  # a marca está lá


def test_the_cache_key_tells_apart_finishes_tempos_and_the_mark(tmp_path):
    service, _marker, _runner, _events = narration(tmp_path)
    request = VoiceRequest(text="Uma frase.")
    keys = {
        service.cache_key(request),
        service.cache_key(request, SpeechFinish(broadcast=True)),
        service.cache_key(request, SpeechFinish(tempo=1.15)),
        service.cache_key(request, SpeechFinish(tempo=0.9)),
        service.cache_key(request, SpeechFinish(broadcast=True, tempo=1.15)),
    }
    assert len(keys) == 5

    plain = NarrationService(
        ToneSynthesizer(), RecordingRunner(), tmp_path / "plain", watermarker=NullWatermarker()
    )
    assert plain.cache_key(request) == plain.cache_key(
        request, SpeechFinish()
    )  # sem acabamento nem marca: a de sempre
    assert plain.cache_key(request) != service.cache_key(request)


def test_a_finished_utterance_is_cached_and_never_finished_or_marked_again(tmp_path):
    service, _marker, runner, events = narration(tmp_path)

    service.render(TEXT, tmp_path / "a.wav", voice=None)
    before = len(events)
    service.render(TEXT, tmp_path / "b.wav", voice=None)

    assert events[before:] == ["narração"] and len(finish_commands(runner)) == 2


def test_speech_for_later_transformation_is_never_marked_and_every_mark_starts_from_the_raw_speech(tmp_path):
    service, marker, _runner, events = narration(tmp_path)
    request = VoiceRequest(text="Uma frase.")

    dry_path, _seconds = service.speak_dry(request)
    assert events == [] and np.isclose(np.abs(read_wav(dry_path)[0]).max(), 0.3, atol=1e-3)

    service.speak(request)  # só a marca
    service.speak(request, SpeechFinish(tempo=1.1))  # outro arquivo final, de novo a partir da fala crua
    service.speak(request, SpeechFinish(tempo=1.1))  # cache
    assert events == ["marca", FINISH_LABEL, "marca"]
    assert all(
        peak == pytest.approx(0.3, abs=1e-3) for peak in marker.peaks_received
    )  # ninguém marcou duas vezes
    assert np.isclose(np.abs(read_wav(dry_path)[0]).max(), 0.3, atol=1e-3)  # a fala crua continua intacta


def test_is_cached_means_the_model_already_spoke_it(tmp_path):
    service, _marker, _runner, _events = narration(tmp_path)
    request = VoiceRequest(text="Uma frase.")
    assert not service.is_cached(request)
    service.speak_dry(request)
    assert service.is_cached(request)


# ---------- dublagem ----------


def marked_dubbing(tmp_path: Path) -> tuple[DubHarness, OrderedWatermarker, list[str]]:
    dub = DubHarness(tmp_path)
    events: list[str] = []
    recording(dub.runner, events)
    marker = OrderedWatermarker(events)
    dub.service.narrator.watermarker = marker
    return dub, marker, events


def test_dubbing_speeds_up_the_speech_before_marking_it_and_the_mix_has_no_atempo_for_it(tmp_path):
    dub, marker, events = marked_dubbing(tmp_path)

    result = dub.service.render(stretched_project(dub, "misto", seconds=6.6), dub.out)

    assert result.report[0].tempo == pytest.approx(1.15)
    (speed_up,) = dub.labeled(FINISH_LABEL)
    assert speed_up.args[speed_up.args.index("-af") + 1] == "atempo=1.150000"
    assert events.index(FINISH_LABEL) + 1 == events.index(
        "marca", events.index(FINISH_LABEL)
    )  # marca logo depois
    assert events.count("marca") == 3  # uma por fala, nenhuma duas vezes
    assert all(peak == pytest.approx(0.1, abs=0.01) for peak in marker.peaks_received)  # sempre a fala crua
    chain = next(line for line in dub.graph().split(";") if line.endswith("[dub0]"))
    assert "atempo" not in chain


def test_dubbing_without_speed_change_marks_each_speech_without_any_ffmpeg_in_between(tmp_path):
    dub, _marker, events = marked_dubbing(tmp_path)

    result = dub.service.render(dub.prepare(fit_mode="video"), dub.out)

    assert all(entry.tempo == 1.0 for entry in result.report)
    assert dub.labeled(FINISH_LABEL) == [] and events.count("marca") == 3
    assert "atempo" not in dub.graph()


def test_dubbing_clips_are_the_marked_files_not_the_raw_ones(tmp_path):
    dub, marker, _events = marked_dubbing(tmp_path)

    dub.service.render(stretched_project(dub, "misto", seconds=6.6), dub.out)

    (mix,) = dub.mix_commands()
    clip_inputs = [Path(mix.args[i + 1]) for i, arg in enumerate(mix.args) if arg == "-i"][2:]
    assert len(clip_inputs) == 3
    for path in clip_inputs:
        samples, _rate = read_wav(path)
        assert (
            np.abs(samples).max() > 0.1 + marker.OFFSET * 0.9
        )  # cada fala que toca no vídeo carrega a marca


# ---------- correção de fala ----------


class LongWinded(FakeSynthesizer):
    """Ignora a duração pedida e fala 60% mais devagar (como o Kokoro), o que obriga a acelerar na emenda."""

    def synthesize(self, request: VoiceRequest) -> Speech:
        self.requests.append(request)
        seconds = (request.duration or len(request.text) * 0.05) * 1.6
        t = np.arange(int(seconds * SPEECH_RATE)) / SPEECH_RATE
        return Speech((0.1 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), SPEECH_RATE)


def test_speech_fix_speeds_up_before_marking_and_the_splice_has_no_atempo(tmp_path):
    harness = Harness(tmp_path)
    harness.service.narrator.synthesizer = LongWinded()
    events: list[str] = []
    recording(harness.runner, events)
    marker = OrderedWatermarker(events)
    harness.service.narrator.watermarker = marker

    harness.service.fix(harness.request())

    (speed_up,) = finish_commands(harness.runner)
    assert speed_up[speed_up.index("-af") + 1].startswith("atempo=1.1")
    assert events.index(FINISH_LABEL) + 1 == events.index("marca")
    assert events.count("marca") == 1 and marker.peaks_received[0] == pytest.approx(0.1, abs=0.01)
    splice = next(c for c in harness.runner.commands if "-filter_complex" in c)
    assert "atempo" not in splice[splice.index("-filter_complex") + 1]


def test_speech_fix_without_speed_change_only_marks(tmp_path):
    harness = Harness(tmp_path)
    events: list[str] = []
    recording(harness.runner, events)
    harness.service.narrator.watermarker = OrderedWatermarker(events)

    harness.service.fix(harness.request())

    assert finish_commands(harness.runner) == [] and events.count("marca") == 1
