"""Fumaça do motor real: baixa o modelo na primeira vez e sintetiza uma frase na CPU.

Só roda com `DMAKER_VOICE_SMOKE=1` e com torch/omnivoice instalados (extra `voice`).
"""

from __future__ import annotations

import importlib.util
import os

import pytest

from dmaker.voice.synth import OmniVoiceSynthesizer, VoiceRequest

pytestmark = [
    pytest.mark.skipif(os.environ.get("DMAKER_VOICE_SMOKE") != "1", reason="defina DMAKER_VOICE_SMOKE=1"),
    pytest.mark.skipif(
        importlib.util.find_spec("omnivoice") is None or importlib.util.find_spec("torch") is None,
        reason="omnivoice/torch não instalados (pip install -e .[voice])",
    ),
]


def test_omnivoice_speaks_a_sentence():
    speech = OmniVoiceSynthesizer(device="cpu").synthesize(
        VoiceRequest(text="Olá, este é um teste do DMaker.", instruct="female", seed=1)
    )
    assert speech.sample_rate == 24000
    assert speech.duration > 0.5
    assert float(abs(speech.samples).max()) > 0.01  # não é silêncio


def test_kokoro_dora_speaks_intelligible_portuguese(tmp_path):
    pytest.importorskip("kokoro_onnx")
    pytest.importorskip("faster_whisper")
    from dmaker.media.wavio import write_wav
    from dmaker.text.transcribe import WhisperTranscriber
    from dmaker.voice.kokoro import KokoroSynthesizer
    from dmaker.voice.library import VoiceLibrary

    speech = KokoroSynthesizer().synthesize(
        VoiceRequest(text="Hoje é um bom dia para gravar um vídeo.", voice=VoiceLibrary(tmp_path).get("dora"))
    )
    assert speech.sample_rate == 24000 and speech.duration > 1.5
    assert float(abs(speech.samples).max()) > 0.05

    wav = write_wav(tmp_path / "dora.wav", speech.samples, speech.sample_rate)
    heard = " ".join(c.text for c in WhisperTranscriber().transcribe(wav, "pt").cues).lower()
    assert sum(word in heard for word in ("hoje", "bom dia", "gravar", "vídeo")) >= 3
