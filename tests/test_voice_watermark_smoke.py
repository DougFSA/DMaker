"""Fumaça da marca d'água com a AudioSeal real: baixa os pesos na primeira vez e roda na CPU.

Só roda com `DMAKER_VOICE_SMOKE=1` e com torch, audioseal e kokoro instalados (extra `voice`). Cobre o que
os testes com marcador falso não alcançam: a marca é inaudível, sobrevive ao AAC 192k e a fala sem marca
não é acusada.
"""

from __future__ import annotations

import importlib.util
import os

import numpy as np
import pytest

from dmaker.filtergraph.voice import OUTPUT_SAMPLE_RATE, encoder_args
from dmaker.media.ffmpeg import FFmpegCommand, SubprocessRunner
from dmaker.media.wavio import write_wav
from dmaker.pipeline.voices import verify_watermark
from dmaker.voice.library import VoiceLibrary
from dmaker.voice.postprocess import finish_speech
from dmaker.voice.synth import VoiceRequest
from dmaker.voice.watermark import AudioSealWatermarker

from .conftest import requires_ffmpeg

pytestmark = [
    pytest.mark.skipif(os.environ.get("DMAKER_VOICE_SMOKE") != "1", reason="defina DMAKER_VOICE_SMOKE=1"),
    pytest.mark.skipif(
        any(importlib.util.find_spec(name) is None for name in ("torch", "audioseal", "kokoro_onnx")),
        reason="torch/audioseal/kokoro não instalados (pip install -e .[voice])",
    ),
    requires_ffmpeg,
]

TEXT = "Hoje vamos falar sobre como editar vídeos curtos de forma rápida e simples, sem complicação nenhuma."
MAX_RELATIVE_ENERGY_DB = -30.0  # a marca tem de ficar abaixo disso da energia da fala


def _relative_energy_db(plain: np.ndarray, marked: np.ndarray) -> float:
    residue = marked - plain
    return float(10 * np.log10((residue**2).sum() / (plain**2).sum()))


def test_mark_is_inaudible_survives_aac_and_is_absent_from_plain_speech(tmp_path):
    from dmaker.voice.kokoro import KokoroSynthesizer

    speech = KokoroSynthesizer().synthesize(VoiceRequest(text=TEXT, voice=VoiceLibrary(tmp_path).get("dora")))
    plain = finish_speech(speech.samples, speech.sample_rate)
    marker = AudioSealWatermarker()
    marked = marker.embed(plain, speech.sample_rate)

    assert len(marked) == len(plain)
    assert _relative_energy_db(plain, marked) < MAX_RELATIVE_ENERGY_DB

    runner = SubprocessRunner(quiet=True)
    for label, samples, expected in (("marcada", marked, True), ("sem-marca", plain, False)):
        wav = write_wav(tmp_path / f"{label}.wav", samples, speech.sample_rate)
        m4a = tmp_path / f"{label}.m4a"
        runner.run(
            FFmpegCommand(["-i", str(wav), "-ar", str(OUTPUT_SAMPLE_RATE), *encoder_args(m4a), str(m4a)])
        )
        result = verify_watermark(m4a, runner=runner, watermarker=marker)
        assert result.detected is expected, f"{label}: {result}"
