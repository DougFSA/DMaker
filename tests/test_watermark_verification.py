"""Verificação em três níveis: a etiqueta de procedência primeiro, o áudio depois; frases, CLI e MCP."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from dmaker.cli import app
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.media.wavio import write_wav
from dmaker.pipeline import voices
from dmaker.voice.provenance import provenance_text
from dmaker.voice.watermark import WatermarkResult

LABEL = provenance_text([(30.0, 33.44)])
WHOLE_FILE_LABEL = provenance_text()


class AudioMarker:
    """Detector falso: devolve o resultado combinado e anota as chamadas."""

    def __init__(self, result: WatermarkResult):
        self.result = result
        self.detected_rates: list[int] = []

    def detect(self, samples: np.ndarray, sample_rate: int) -> WatermarkResult:
        self.detected_rates.append(sample_rate)
        return self.result


def prober_with(comment: str | None):
    tags = {} if comment is None else {"comment": comment}
    return lambda path: MediaInfo(path, 60.0, 0, 0, 0.0, False, True, False, format_tags=tags)


def extracting_runner(samples: np.ndarray | None = None) -> RecordingRunner:
    audio = np.full(16000, 0.1, dtype=np.float32) if samples is None else samples
    return RecordingRunner(on_run=lambda command: write_wav(Path(command.args[-1]), audio, 16000))


@pytest.fixture
def media(tmp_path) -> Path:
    path = tmp_path / "video.mp4"
    path.write_bytes(b"mp4")
    return path


# ---------- sem etiqueta: o áudio decide, em três níveis ----------


@pytest.mark.parametrize(
    "result",
    [
        WatermarkResult(0.83, "found", 16),
        WatermarkResult(0.9, "indication", 8),
        WatermarkResult(0.01, "absent", 7),
    ],
)
def test_without_a_label_the_audio_analysis_gives_the_verdict(media, result):
    marker = AudioMarker(result)
    runner = extracting_runner()

    answer = voices.verify_watermark(media, runner=runner, watermarker=marker, prober=prober_with(None))

    assert answer == result and answer.origin == "audio"
    assert str(media) in runner.commands[0]
    assert marker.detected_rates == [16000]


def test_a_comment_that_is_not_ours_is_ignored(media):
    marker = AudioMarker(WatermarkResult(0.0, "absent"))

    answer = voices.verify_watermark(
        media, runner=extracting_runner(), watermarker=marker, prober=prober_with("Gravado no celular")
    )

    assert answer.origin == "audio" and marker.detected_rates == [16000]


def test_without_a_label_and_without_the_library_it_fails_instead_of_saying_not_found(monkeypatch, media):
    monkeypatch.setattr(voices, "audioseal_installed", lambda: False)
    with pytest.raises(RuntimeError, match="audioseal não está instalada"):
        voices.verify_watermark(media, runner=RecordingRunner(), prober=prober_with(None))


def test_a_missing_file_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError, match="não encontrado"):
        voices.verify_watermark(tmp_path / "nada.wav", prober=prober_with(None))


# ---------- com etiqueta: ela responde primeiro ----------


def test_the_label_answers_without_touching_the_audio(media):
    marker = AudioMarker(WatermarkResult(0.0, "absent"))
    runner = RecordingRunner()

    answer = voices.verify_watermark(media, runner=runner, watermarker=marker, prober=prober_with(LABEL))

    assert answer.verdict == "found" and answer.detected and answer.origin == "label"
    assert answer.spans == ((30.0, 33.44),)
    assert answer.audio_verdict is None
    assert runner.commands == [] and marker.detected_rates == []  # nenhum ffmpeg, nenhum modelo


def test_the_label_works_even_without_the_audio_library(monkeypatch, media):
    monkeypatch.setattr(voices, "audioseal_installed", lambda: False)
    answer = voices.verify_watermark(media, prober=prober_with(WHOLE_FILE_LABEL))
    assert answer.verdict == "found" and answer.spans == ()


def test_the_audio_analysis_can_be_asked_for_next_to_the_label(media):
    marker = AudioMarker(WatermarkResult(0.31, "found", 16))

    answer = voices.verify_watermark(
        media, runner=extracting_runner(), watermarker=marker, prober=prober_with(LABEL), check_audio=True
    )

    assert answer.origin == "label" and answer.verdict == "found"
    assert answer.audio_verdict == "found" and answer.probability == 0.31 and answer.matched_bits == 16


def test_the_label_wins_over_an_audio_that_does_not_show_the_mark(media):
    """O caso do vídeo longo: a marca no áudio some na mixagem, mas a etiqueta diz onde a voz gerada está."""
    marker = AudioMarker(WatermarkResult(0.02, "absent", 9))

    answer = voices.verify_watermark(
        media, runner=extracting_runner(), watermarker=marker, prober=prober_with(LABEL), check_audio=True
    )

    assert answer.verdict == "found" and answer.audio_verdict == "absent"


# ---------- frases ----------


def test_verdict_sentences_are_in_portuguese_without_dashes():
    found = voices.watermark_verdict(WatermarkResult(0.83, "found", 16))
    indication = voices.watermark_verdict(WatermarkResult(0.9, "indication", 8))
    absent = voices.watermark_verdict(WatermarkResult(0.0, "absent", 7))
    assert "Marca d'água encontrada" in found and "83%" in found and "16 de 16 bits" in found
    assert "Indício, inconclusivo" in indication and "8 de 16 bits" in indication
    assert "música e tons puros podem imitar a marca" in indication and "só a assinatura" in indication
    assert "não encontrada" in absent and "recodificado" in absent
    assert "—" not in found + indication + absent


def test_label_sentence_lists_the_spans_in_portuguese():
    answer = WatermarkResult(0.0, "found", origin="label", spans=((33.1, 34.42), (50.0, 52.3)))
    sentence = voices.watermark_verdict(answer)
    assert sentence.startswith("Etiqueta de procedência encontrada")
    assert "33,1 a 34,4 s; 50,0 a 52,3 s" in sentence and "—" not in sentence


def test_label_sentence_for_the_whole_file_and_with_the_audio_analysis():
    whole = voices.watermark_verdict(WatermarkResult(0.0, "found", origin="label"))
    assert "arquivo inteiro" in whole
    both = voices.watermark_verdict(
        WatermarkResult(0.31, "found", 16, origin="label", spans=((1.0, 2.0),), audio_verdict="indication")
    )
    assert "Análise do áudio: indício, inconclusivo (31% dos quadros)" in both


# ---------- CLI ----------


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (WatermarkResult(0.8123, "found", 16), "Marca d'água encontrada"),
        (WatermarkResult(0.97, "indication", 8), "Indício, inconclusivo"),
        (WatermarkResult(0.01, "absent", 7), "Marca d'água não encontrada"),
        (WatermarkResult(0.0, "found", origin="label", spans=((30.0, 33.4),)), "Etiqueta de procedência"),
    ],
)
def test_voice_verify_prints_the_level(monkeypatch, tmp_path, result, expected):
    source = tmp_path / "voz.wav"
    source.write_bytes(b"wav")
    monkeypatch.setattr(voices, "verify_watermark", lambda path, **options: result)

    answer = CliRunner().invoke(app, ["voice", "verify", str(source)])

    assert answer.exit_code == 0, answer.output
    assert expected in answer.output
    if result.origin == "audio":
        assert (
            f"{result.probability:.3f}" in answer.output
            and f"{result.matched_bits} de 16 bits" in answer.output
        )


def test_voice_verify_audio_flag_asks_for_the_audio_analysis_too(monkeypatch, tmp_path):
    source = tmp_path / "voz.wav"
    source.write_bytes(b"wav")
    received = []

    def fake(path, **options):
        received.append(options["check_audio"])
        return WatermarkResult(0.0, "found", origin="label")

    monkeypatch.setattr(voices, "verify_watermark", fake)
    cli = CliRunner()
    assert cli.invoke(app, ["voice", "verify", str(source)]).exit_code == 0
    assert cli.invoke(app, ["voice", "verify", str(source), "--audio"]).exit_code == 0
    assert received == [False, True]


def test_voice_verify_reports_errors_with_exit_code_1(tmp_path):
    result = CliRunner().invoke(app, ["voice", "verify", str(tmp_path / "fantasma.wav")])
    assert result.exit_code == 1 and "não encontrado" in result.output


def test_help_says_that_one_switch_turns_off_the_mark_and_the_label():
    plain = CliRunner().invoke(app, ["voice", "say", "--help"]).output
    assert "--no-watermark" in plain and "etiqueta" in plain.replace("\n", " ")


# ---------- MCP ----------


def test_mcp_verify_watermark_returns_level_origin_bits_and_spans(monkeypatch, tmp_path):
    import dmaker.mcp_server as mcp_server

    result = WatermarkResult(0.31, "found", 16, origin="label", spans=((30.0, 33.44),), audio_verdict="found")
    received = []

    def fake(path, **options):
        received.append(options["check_audio"])
        return result

    monkeypatch.setattr(voices, "verify_watermark", fake)

    answer = mcp_server.verify_watermark(str(tmp_path / "x.mp4"), check_audio=True)

    assert received == [True]
    assert answer["level"] == "found" and answer["origin"] == "label" and answer["detected"] is True
    assert (
        answer["matched_bits"] == 16
        and answer["spans"] == [[30.0, 33.44]]
        and answer["audio_level"] == "found"
    )
    assert "Etiqueta de procedência" in answer["verdict"]


def test_mcp_verify_watermark_an_indication_is_not_a_detection(monkeypatch, tmp_path):
    import dmaker.mcp_server as mcp_server

    monkeypatch.setattr(
        voices, "verify_watermark", lambda path, **options: WatermarkResult(0.9, "indication", 8)
    )

    answer = mcp_server.verify_watermark(str(tmp_path / "x.wav"))

    assert answer["level"] == "indication" and answer["detected"] is False
    assert "Indício" in answer["verdict"]
