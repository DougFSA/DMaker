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
from dmaker.media.wavio import read_wav, write_wav
from dmaker.pipeline import voices
from dmaker.pipeline.narration import NarrationService
from dmaker.voice import watermark
from dmaker.voice.synth import Speech, VoiceRequest
from dmaker.voice.watermark import (
    AudioSealWatermarker,
    NullWatermarker,
    WatermarkResult,
    chunk_bounds,
    default_watermarker,
    delay_on_detector_grid,
    watermark_enabled,
)

from .conftest import fake_ffmpeg_output

SAMPLE_RATE = 24000


class FakeWatermarker:
    """Soma um deslocamento fixo às amostras (para ver que a marca foi gravada) e conta as chamadas."""

    identity = "fake-marca:1"
    OFFSET = 0.05

    def __init__(self, detected: bool = True):
        self.embedded: list[int] = []
        self.verdict = WatermarkResult(0.9 if detected else 0.0, detected)
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
    assert null.detect(samples, SAMPLE_RATE) == WatermarkResult(0.0, False)
    assert null.identity == ""


# ---------- escolha do marcador ----------


def test_default_watermarker_is_audioseal_when_on_and_installed():
    assert isinstance(default_watermarker(environ={}, installed=True), AudioSealWatermarker)


def test_default_watermarker_is_null_when_turned_off_by_argument_or_variable():
    assert isinstance(default_watermarker(enabled=False, environ={}, installed=True), NullWatermarker)
    assert isinstance(default_watermarker(environ={"DMAKER_WATERMARK": "0"}, installed=True), NullWatermarker)


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


class _FixedDetector:
    def __init__(self, probabilities: list[float]):
        self.probabilities = iter(probabilities)

    def detect_watermark(self, audio, sample_rate):
        import torch

        return torch.tensor([next(self.probabilities)]), torch.zeros(1, 16)


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


def test_audioseal_detect_takes_the_best_block_and_applies_the_threshold(needs_torch):
    two_blocks = np.zeros(
        int(60.5 * 16000), dtype=np.float32
    )  # 60,5 s: dois blocos, a cauda de 0,5 s é incorporada
    marker = _loaded(detector=_FixedDetector([0.05, 0.7]))
    result = marker.detect(two_blocks, 16000)
    assert result == WatermarkResult(0.7, True)

    quiet = _loaded(detector=_FixedDetector([0.01]))
    assert quiet.detect(np.zeros(16000, dtype=np.float32), 16000) == WatermarkResult(0.01, False)


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


def _extracting_runner(samples: np.ndarray, rate: int = 16000) -> RecordingRunner:
    return RecordingRunner(on_run=lambda command: write_wav(Path(command.args[-1]), samples, rate))


@pytest.mark.parametrize("detected", [True, False])
def test_verify_extracts_the_audio_and_returns_the_verdict(tmp_path, detected):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"mp4")
    marker = FakeWatermarker(detected=detected)
    runner = _extracting_runner(np.full(16000, 0.1, dtype=np.float32))

    result = voices.verify_watermark(source, runner=runner, watermarker=marker)

    assert result.detected is detected
    assert str(source) in runner.commands[0]
    assert marker.detected_rates == [16000]


def test_verify_fails_clearly_when_the_file_or_the_library_is_missing(monkeypatch, tmp_path):
    with pytest.raises(FileNotFoundError, match="não encontrado"):
        voices.verify_watermark(tmp_path / "nada.wav", watermarker=FakeWatermarker())

    source = tmp_path / "voz.wav"
    source.write_bytes(b"wav")
    monkeypatch.setattr(voices, "audioseal_installed", lambda: False)
    with pytest.raises(RuntimeError, match="audioseal não está instalada"):
        voices.verify_watermark(source, runner=RecordingRunner())


def test_verdict_text_is_in_portuguese_without_dashes():
    found = voices.watermark_verdict(WatermarkResult(0.83, True))
    absent = voices.watermark_verdict(WatermarkResult(0.0, False))
    assert "encontrada" in found and "83%" in found
    assert "não encontrada" in absent
    assert "—" not in found + absent


# ---------- CLI ----------


def test_voice_verify_prints_probability_and_verdict(monkeypatch, tmp_path):
    source = tmp_path / "voz.wav"
    source.write_bytes(b"wav")
    monkeypatch.setattr(voices, "verify_watermark", lambda path: WatermarkResult(0.8123, True))

    result = CliRunner().invoke(app, ["voice", "verify", str(source)])

    assert result.exit_code == 0, result.output
    assert "Marca d'água encontrada" in result.output and "0.812" in result.output


def test_voice_verify_reports_errors_with_exit_code_1(tmp_path):
    result = CliRunner().invoke(app, ["voice", "verify", str(tmp_path / "fantasma.wav")])
    assert result.exit_code == 1 and "não encontrado" in result.output


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


# ---------- MCP ----------


def test_mcp_verify_watermark_returns_the_verdict(monkeypatch, tmp_path):
    import dmaker.mcp_server as mcp_server

    monkeypatch.setattr(voices, "verify_watermark", lambda path: WatermarkResult(0.0, False))

    answer = mcp_server.verify_watermark(str(tmp_path / "x.wav"))

    assert answer["detected"] is False and answer["probability"] == 0.0
    assert "não encontrada" in answer["verdict"]


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
