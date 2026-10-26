"""Marca d'água inaudível: contas puras, escolha do marcador, integração com a narração e a verificação."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from dmaker.cli import app
from dmaker.filtergraph.voice import detection_audio_command
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.wavio import read_wav
from dmaker.pipeline import voices
from dmaker.pipeline.narration import NarrationService
from dmaker.voice import watermark
from dmaker.voice.synth import Speech, VoiceRequest
from dmaker.voice.watermark import (
    DETECTION_THRESHOLD,
    MESSAGE_BITS,
    AudioSealWatermarker,
    NullWatermarker,
    WatermarkResult,
    choose_verdict,
    chunk_bounds,
    default_watermarker,
    delay_on_detector_grid,
    matching_bits,
    phase_offsets,
    watermark_enabled,
    weighted_message,
)

from .conftest import fake_ffmpeg_output

SAMPLE_RATE = 24000


class FakeWatermarker:
    """Soma um deslocamento fixo às amostras (para ver que a marca foi gravada) e conta as chamadas."""

    identity = "fake-marca:1"
    provenance = True
    OFFSET = 0.05

    def __init__(self, detected: bool = True):
        self.embedded: list[int] = []
        self.verdict = WatermarkResult(0.9 if detected else 0.0, "found" if detected else "absent", 16)
        self.detected_rates: list[int] = []

    def embed(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        self.embedded.append(len(samples))
        return (samples + self.OFFSET).astype(np.float32)

    def detect(self, samples: np.ndarray, sample_rate: int) -> WatermarkResult:
        self.detected_rates.append(sample_rate)
        return self.verdict


class FakeSynthesizer:
    engine_id = "fake-1"

    def __init__(self):
        self.calls = 0

    def synthesize(self, request: VoiceRequest) -> Speech:
        self.calls += 1
        t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
        return Speech((0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), SAMPLE_RATE)


def _service(tmp_path, watermarker):
    return NarrationService(FakeSynthesizer(), RecordingRunner(), tmp_path / "cache", watermarker=watermarker)


# ---------- contas puras ----------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, True), ("", True), ("1", True), ("0", False), ("false", False), (" OFF ", False), ("não", False)],
)
def test_watermark_is_on_unless_the_variable_turns_it_off(value, expected):
    environ = {} if value is None else {"DMAKER_WATERMARK": value}
    assert watermark_enabled(environ) is expected


def test_chunk_bounds_cover_the_audio_and_fold_a_short_tail():
    assert chunk_bounds(0, 100, 10) == []
    assert chunk_bounds(80, 100, 10) == [(0, 80)]
    assert chunk_bounds(250, 100, 10) == [(0, 100), (100, 200), (200, 250)]
    assert chunk_bounds(205, 100, 10) == [(0, 100), (100, 205)]  # cauda de 5 < 10 entra no bloco anterior


def test_null_watermarker_changes_nothing_and_never_detects():
    samples = np.ones(10, dtype=np.float32)
    null = NullWatermarker()
    assert null.embed(samples, SAMPLE_RATE) is samples
    assert null.detect(samples, SAMPLE_RATE) == WatermarkResult(0.0, "absent")
    assert null.identity == "" and null.provenance is False


# ---------- escolha do marcador ----------


def test_default_watermarker_is_audioseal_when_on_and_installed():
    assert isinstance(default_watermarker(environ={}, installed=True), AudioSealWatermarker)


def test_default_watermarker_is_null_when_turned_off_by_argument_or_variable():
    assert isinstance(default_watermarker(enabled=False, environ={}, installed=True), NullWatermarker)
    assert isinstance(default_watermarker(environ={"DMAKER_WATERMARK": "0"}, installed=True), NullWatermarker)


def test_the_provenance_label_follows_the_same_switch_as_the_mark():
    """Ligada: marca e etiqueta. Desligada pelo argumento ou pela variável: nenhuma das duas.
    Sem a biblioteca a voz continua gerada, então a etiqueta fica e só a marca no áudio falta."""
    assert default_watermarker(environ={}, installed=True).provenance is True
    assert default_watermarker(enabled=False, environ={}, installed=True).provenance is False
    assert default_watermarker(environ={"DMAKER_WATERMARK": "0"}, installed=True).provenance is False
    assert default_watermarker(environ={}, installed=False).provenance is True


def test_default_watermarker_warns_once_in_portuguese_when_the_library_is_missing(monkeypatch, caplog):
    monkeypatch.setattr(watermark, "_missing_library_warned", False)
    with caplog.at_level(logging.WARNING, logger="dmaker.voice.watermark"):
        first = default_watermarker(environ={}, installed=False)
        second = default_watermarker(environ={}, installed=False)
    assert isinstance(first, NullWatermarker) and isinstance(second, NullWatermarker)
    assert len(caplog.records) == 1 and "SEM marca d'água" in caplog.records[0].getMessage()


# ---------- AudioSeal com rede falsa ----------


@pytest.fixture
def needs_torch():
    return pytest.importorskip("torch")


class _AddConstantGenerator:
    """Gerador falso: devolve o áudio mais 0,01 e registra a taxa, o ganho e a mensagem recebidos."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, audio, sample_rate, message, alpha):
        self.calls.append({"sample_rate": sample_rate, "alpha": alpha, "bits": message.shape[-1]})
        return audio + 0.01


class _ScriptedDetector:
    """Rede falsa: `plan(bloco)` diz que fração dos quadros do bloco é vista como marcada e quais bits ela carrega.

    Os quadros não marcados votam o bit contrário e com mais força, para provar que a mensagem só conta os marcados.
    """

    normalizer = None

    def __init__(self, plan):
        self.plan = plan
        self.blocks: list[int] = []  # primeira amostra de cada bloco visto (acompanha o alinhamento)

    def detector(self, block):
        import torch

        self.blocks.append(int(block[0, 0, 0].item()))
        frames = max(1, block.shape[-1] // 320)
        fraction, bits = self.plan(block)
        marked_frames = round(fraction * frames)
        output = torch.zeros(1, 2 + len(MESSAGE_BITS), frames)
        output[0, 1, :marked_frames] = 5.0
        output[0, 0, marked_frames:] = 5.0
        for index, bit in enumerate(bits):
            output[0, 2 + index, :marked_frames] = 3.0 if bit else -3.0
            output[0, 2 + index, marked_frames:] = -9.0 if bit else 9.0
        return output


SIGNATURE = MESSAGE_BITS
NOT_THE_SIGNATURE = tuple(1 - bit for bit in MESSAGE_BITS)


def _loaded(generator=None, detector=None, **options) -> AudioSealWatermarker:
    marker = AudioSealWatermarker(**options)
    marker._generator = generator
    marker._detector = detector
    return marker


def test_audioseal_embed_keeps_length_and_rate_and_adds_only_the_residue(needs_torch):
    generator = _AddConstantGenerator()
    marker = _loaded(generator, strength=0.45)
    samples = np.zeros(SAMPLE_RATE, dtype=np.float32)

    marked = marker.embed(samples, SAMPLE_RATE)

    assert marked.dtype == np.float32 and len(marked) == len(samples)
    assert np.allclose(marked[100:-100], 0.01, atol=1e-3)  # o resíduo (0,01) volta na taxa original
    assert generator.calls == [{"sample_rate": 16000, "alpha": 0.45, "bits": 16}]  # o modelo vê 16 kHz


def test_audioseal_embed_of_nothing_returns_nothing_without_loading_the_model():
    assert len(AudioSealWatermarker().embed(np.zeros(0, dtype=np.float32), SAMPLE_RATE)) == 0


def _ramp(seconds: float) -> np.ndarray:
    """Áudio em que a amostra i vale i: o primeiro valor de um bloco diz quantas amostras foram cortadas."""
    return np.arange(int(seconds * 16000), dtype=np.float32)


def test_audioseal_detect_finds_the_signature_and_takes_the_best_block(needs_torch):
    two_blocks = _ramp(60.5)  # 60,5 s: dois blocos, a cauda de 0,5 s é incorporada
    marker = _loaded(
        detector=_ScriptedDetector(lambda block: (0.5 if block[0, 0, 0] == 0 else 0.1, SIGNATURE))
    )

    result = marker.detect(two_blocks, 16000)

    assert result.verdict == "found" and result.detected and result.matched_bits == 16
    assert result.probability == 0.5


def test_audioseal_detect_returns_an_indication_when_the_signature_does_not_match(needs_torch):
    """É o caso de música e tons: a rede reage (fração alta) mas a mensagem é outra."""
    marker = _loaded(detector=_ScriptedDetector(lambda block: (0.8, NOT_THE_SIGNATURE)))
    result = marker.detect(_ramp(1.0), 16000)
    assert result.verdict == "indication" and not result.detected
    assert result.matched_bits == 0 and result.probability > DETECTION_THRESHOLD


def test_audioseal_detect_reports_absent_below_the_threshold(needs_torch):
    marker = _loaded(detector=_ScriptedDetector(lambda block: (0.0, SIGNATURE)))
    result = marker.detect(_ramp(1.0), 16000)
    assert result.verdict == "absent" and result.probability == 0.0 and result.matched_bits is None


def test_audioseal_detect_counts_only_the_frames_the_network_marked_for_the_bits(needs_torch):
    """Os quadros não marcados votam o bit contrário com mais força: a média de todos erraria a assinatura."""
    marker = _loaded(detector=_ScriptedDetector(lambda block: (0.4, SIGNATURE)))
    result = marker.detect(_ramp(1.0), 16000)  # 50 quadros, 20 marcados
    assert result.verdict == "found" and result.matched_bits == 16


def test_audioseal_detect_stops_at_the_first_alignment_when_it_already_finds_the_mark(needs_torch):
    detector = _ScriptedDetector(lambda block: (0.6, SIGNATURE))
    _loaded(detector=detector).detect(_ramp(1.0), 16000)
    assert detector.blocks == [0]


def test_audioseal_detect_searches_the_other_alignments_and_keeps_the_best(needs_torch):
    """Só o alinhamento com 120 amostras cortadas (o quarto) enxerga a marca: a busca o acha e decodifica nele."""
    detector = _ScriptedDetector(
        lambda block: (0.6, SIGNATURE) if block[0, 0, 0] == 120 else (0.0, NOT_THE_SIGNATURE)
    )
    result = _loaded(detector=detector).detect(_ramp(1.0), 16000)
    assert detector.blocks == [0, 40, 80, 120, 160, 200, 240, 280]
    assert result.verdict == "found" and result.matched_bits == 16


def test_audioseal_detect_keeps_the_alignment_with_the_highest_fraction_not_the_best_bits(needs_torch):
    """Escolher pela assinatura multiplicaria o acaso por 8; o alinhamento vem da fração e os bits só são lidos nele."""

    def plan(block):
        skip = int(block[0, 0, 0])
        table = {0: (0.24, NOT_THE_SIGNATURE), 80: (0.6, NOT_THE_SIGNATURE), 120: (0.3, SIGNATURE)}
        return table.get(skip, (0.0, SIGNATURE))

    result = _loaded(detector=_ScriptedDetector(plan)).detect(_ramp(1.0), 16000)
    assert (
        result.verdict == "indication"
        and result.matched_bits == 0
        and result.probability == pytest.approx(0.6, abs=0.02)
    )


def test_audioseal_detect_ignores_a_shifted_alignment_that_only_reacts_a_little(needs_torch):
    """Em fala humana a fração oscila entre alinhamentos; o maior de 8 não pode virar "indício" por sorte."""

    def plan(block):
        skip = int(block[0, 0, 0])
        return (0.05, NOT_THE_SIGNATURE) if skip == 0 else (0.3, NOT_THE_SIGNATURE)

    result = _loaded(detector=_ScriptedDetector(plan)).detect(_ramp(1.0), 16000)
    assert result.verdict == "absent" and result.probability == pytest.approx(0.05, abs=0.02)


def test_audioseal_detect_of_nothing_is_absent_without_loading_the_model():
    assert AudioSealWatermarker().detect(np.zeros(0, dtype=np.float32), 16000).verdict == "absent"


# ---------- contas puras do veredito ----------


def test_matching_bits_counts_the_bits_equal_to_the_dm_signature():
    assert matching_bits(SIGNATURE) == 16
    assert matching_bits(NOT_THE_SIGNATURE) == 0
    assert matching_bits((*SIGNATURE[:14], 1 - SIGNATURE[14], 1 - SIGNATURE[15])) == 14


@pytest.mark.parametrize(
    ("fraction", "bits", "expected"),
    [
        (0.0, 16, "absent"),
        (0.19, 16, "absent"),  # abaixo do limiar nem a assinatura vale: o detector não viu marca
        (0.2, 16, "found"),
        (0.9, 15, "found"),
        (0.9, 14, "indication"),  # tom e acordes sem marca: fração alta, bits por acaso
        (0.97, 8, "indication"),
        (0.5, None, "indication"),
        (0.1, None, "absent"),
    ],
)
def test_choose_verdict_has_three_levels(fraction, bits, expected):
    assert choose_verdict(fraction, bits) == expected


def test_choose_verdict_accepts_a_looser_signature_requirement():
    assert choose_verdict(0.9, 14, min_bits=14) == "found"


def test_weighted_message_reads_only_the_marked_frames():
    logits = np.array([[2.0, 2.0, -9.0, -9.0], [-2.0, -2.0, 9.0, 9.0]])  # dois bits, quatro quadros
    marked = np.array([True, True, False, False])
    assert weighted_message(logits, marked) == (1, 0)
    assert weighted_message(logits, np.ones(4, dtype=bool)) == (0, 1)  # a média de todos inverteria os dois
    assert weighted_message(logits, np.zeros(4, dtype=bool)) == ()


def test_phase_offsets_start_at_the_audio_as_it_came_and_step_by_2_5_ms():
    offsets = phase_offsets()
    assert offsets == [0, 40, 80, 120, 160, 200, 240, 280]
    assert all(offset / 16000 * 1000 == index * 2.5 for index, offset in enumerate(offsets))


def test_the_result_counts_as_detected_only_when_found():
    assert WatermarkResult(0.9, "found").detected
    assert not WatermarkResult(0.9, "indication").detected
    assert not WatermarkResult(0.0, "absent").detected


# ---------- narração ----------


def test_speech_is_marked_before_it_is_written(tmp_path):
    marker = FakeWatermarker()
    service = _service(tmp_path, marker)

    path, _duration = service.speak(VoiceRequest(text="Olá, mundo."))

    samples, _rate = read_wav(path)
    assert marker.embedded == [SAMPLE_RATE]
    assert np.allclose(np.abs(samples).max(), 0.3 + FakeWatermarker.OFFSET, atol=1e-3)


def test_cached_speech_is_not_marked_again(tmp_path):
    marker = FakeWatermarker()
    service = _service(tmp_path, marker)
    request = VoiceRequest(text="Olá, mundo.")

    service.speak(request)
    service.speak(request)

    assert marker.embedded == [SAMPLE_RATE]
    assert service.synthesizer.calls == 1


def test_marked_and_unmarked_speech_never_share_a_cache_entry(tmp_path):
    request = VoiceRequest(text="Olá, mundo.")
    marked = _service(tmp_path, FakeWatermarker())
    plain = _service(tmp_path, NullWatermarker())

    assert marked.cache_key(request) != plain.cache_key(request)
    assert marked._cache_path(request) != plain._cache_path(request)


def test_cache_key_without_watermark_is_the_one_from_before_the_feature(tmp_path):
    """Desligada, a chave não muda: o cache de falas já existente continua valendo."""
    request = VoiceRequest(text="Olá, mundo.")
    with_null = _service(tmp_path, NullWatermarker()).cache_key(request)
    assert _service(tmp_path, NullWatermarker()).cache_key(request) == with_null
    marked = _service(tmp_path, FakeWatermarker())
    assert marked.cache_key(request) != with_null


def test_service_without_a_watermarker_follows_the_environment(tmp_path):
    """O conftest desliga a marca por DMAKER_WATERMARK=0: o padrão do serviço obedece à variável."""
    service = NarrationService(FakeSynthesizer(), RecordingRunner(), tmp_path / "cache")
    assert isinstance(service.watermarker, NullWatermarker)


# ---------- speak / verificação ----------


def test_speak_turns_the_watermark_off_with_the_flag(monkeypatch, tmp_path):
    received = []

    def fake_default(enabled=True, **_):
        received.append(enabled)
        return NullWatermarker()

    monkeypatch.setattr(voices, "default_watermarker", fake_default)
    runner = RecordingRunner(on_run=fake_ffmpeg_output)
    monkeypatch.setattr("dmaker.config.VOICE_CACHE_DIR", tmp_path / "cache")

    for flag in (True, False):
        voices.speak(
            "Uma fala curta.",
            tmp_path / "saida.wav",
            runner=runner,
            synthesizer=FakeSynthesizer(),
            watermark=flag,
        )

    assert received == [True, False]


def test_detection_audio_command_extracts_mono_pcm_at_the_detector_rate():
    command = detection_audio_command(Path("video.mp4"), Path("audio.wav"), 16000)
    args = command.args
    assert args[:2] == ["-i", "video.mp4"] and "-vn" in args
    assert args[args.index("-ac") + 1] == "1" and args[args.index("-ar") + 1] == "16000"
    assert args[args.index("-c:a") + 1] == "pcm_s16le" and args[-1] == "audio.wav"


# ---------- CLI ----------


def test_say_forwards_no_watermark(monkeypatch, tmp_path):
    from dmaker.pipeline.narration import NarrationResult

    received = []

    def fake_speak(script, out, **options):
        received.append(options["watermark"])
        return NarrationResult(tmp_path / "saida.wav", 1.0)

    monkeypatch.setattr(voices, "build_synthesizer", lambda device: object())
    monkeypatch.setattr(voices, "speak", fake_speak)

    cli = CliRunner()
    assert cli.invoke(app, ["voice", "say", "Oi."]).exit_code == 0
    assert cli.invoke(app, ["voice", "say", "Oi.", "--no-watermark"]).exit_code == 0
    assert received == [True, False]


# ---------- grade do detector ----------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0.0, 0), (0.5, 500), (1.234, 1240), (2.7, 2700), (4.25, 4240), (4.26, 4260), (-0.3, 0)],
)
def test_delays_land_on_the_detector_grid(seconds, expected):
    """O detector só enxerga a fala alinhada à grade de 20 ms: o atraso é arredondado a ela (até 10 ms)."""
    assert delay_on_detector_grid(seconds) == expected


def test_narration_and_dubbing_delays_use_the_detector_grid():
    from pathlib import Path as _Path
    from types import SimpleNamespace

    from dmaker.filtergraph.audio import narration_streams
    from dmaker.filtergraph.common import Inputs
    from dmaker.filtergraph.dub import DubClip, dub_clip_lines

    lines: list[str] = []
    narration_streams(lines, Inputs(), [SimpleNamespace(path=_Path("n.wav"), start=1.234, volume=1.0)])
    assert "adelay=1240:all=1" in lines[0]
    assert "adelay=delays=1240:all=1" in dub_clip_lines([DubClip(_Path("a.wav"), start=1.234)], 0)[0][0]
