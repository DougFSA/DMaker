"""A fala continua inteligível quando o Vocoder canta na harmonia de uma trilha de acordes (DMK-70), com os modelos de voz de verdade.

A frase é a mesma do teste do Vocoder gerado (DMK-57), falada pelo Kokoro como voz gravada. A "música" é um sinal sintético com
troca de acordes (dentes de serra somadas), sem nenhum áudio real. Só roda com `DMAKER_VOICE_SMOKE=1`, porque carrega o Kokoro e o
Whisper; o resultado é a frase que o Whisper reconhece, palavra por palavra.
"""

from __future__ import annotations

import os
import subprocess

import numpy as np
import pytest

from dmaker import config
from dmaker.media.wavio import write_wav_float

from .conftest import requires_ffmpeg
from .test_dynamics_integration import RATE, write_wav
from .test_vocoder_carrier_track_integration import MUSIC_VOLUME, make_video, project_for, render_pcm

pytestmark = [
    requires_ffmpeg,
    pytest.mark.skipif(
        os.environ.get("DMAKER_VOICE_SMOKE") != "1", reason="modelos reais: defina DMAKER_VOICE_SMOKE=1"
    ),
]

PHRASE = "Hoje o dia está lindo, e vamos passear no parque com os nossos amigos."
CHORDS = [(110.0, 130.81, 164.81), (87.31, 110.0, 130.81), (98.0, 123.47, 146.83), (82.41, 103.83, 123.47)]


def chord_track(seconds: float, change_every: float = 2.0, harmonics: int = 30) -> np.ndarray:
    """Dentes de serra somadas em acordes que trocam a cada `change_every` s: o fundo harmônico de uma música simples."""
    t = np.arange(round(seconds * RATE)) / RATE
    wave = np.zeros_like(t)
    for position, notes in enumerate(CHORDS * int(seconds / change_every / len(CHORDS) + 1)):
        first, last = position * change_every, (position + 1) * change_every
        gate = ((t >= first) & (t < last)).astype(np.float64)
        for note in notes:
            wave += gate * sum(
                np.sin(2 * np.pi * note * k * t) / k for k in range(1, harmonics) if note * k < 8000
            )
    return (0.5 * wave / np.abs(wave).max()).astype(np.float32)


def test_the_whisper_recognizes_the_phrase_sung_on_the_harmony_of_a_chord_track(tmp_path, capsys):
    from dmaker.text.transcribe import WhisperTranscriber
    from dmaker.voice.kokoro import KokoroSynthesizer
    from dmaker.voice.synth import VoiceRequest

    speech = KokoroSynthesizer(models_dir=config.MODELS_DIR / "kokoro").synthesize(VoiceRequest(PHRASE, "pt"))
    wave = np.repeat(speech.samples[:, None] * 0.8, 2, axis=1).astype(np.float32)
    source = write_wav_float(tmp_path / "frase_24k.wav", wave, speech.sample_rate)
    resampled = tmp_path / "frase.wav"
    subprocess.run(
        [str(config.find_tool("ffmpeg")), "-y", "-v", "error", "-i", str(source), "-ar", "48000"]
        + ["-c:a", "pcm_f32le", str(resampled)],
        check=True,
    )
    seconds = len(wave) / speech.sample_rate
    total = float(int(seconds) + 3)
    make_video(tmp_path, total)
    write_wav(tmp_path / "acordes.wav", chord_track(total))
    project = project_for(
        tmp_path,
        [{"type": "clip", "src": "video.mp4", "start": 0, "end": total, "mute": True}],
        {
            "voiceover": [
                {
                    "src": "frase.wav",
                    "start": 1.0,
                    "effects": [{"type": "vocoder", "carrier_track": "MUS", "noise_level": 25}],
                }
            ],
            "music": {"src": "acordes.wav", "volume": MUSIC_VOLUME, "ducking": False},
        },
    )
    mix = render_pcm(project, tmp_path, "mix")
    robot = tmp_path / "robo.wav"
    write_wav_float(robot, np.repeat(mix[:, None], 2, axis=1), RATE)
    resampled_robot = tmp_path / "robo16.wav"
    subprocess.run(
        [str(config.find_tool("ffmpeg")), "-y", "-v", "error", "-i", str(robot), "-ar", "16000", "-ac", "1"]
        + ["-c:a", "pcm_s16le", str(resampled_robot)],
        check=True,
    )
    transcript = WhisperTranscriber().transcribe(resampled_robot, "pt")
    text = " ".join(word.text.strip() for cue in transcript.cues for word in cue.words)
    with capsys.disabled():
        print(f"\nFRASE RECONHECIDA: {text}")
    expected = PHRASE.lower().replace(",", "").replace(".", "").split()
    heard = [word.strip(".,!?") for word in text.lower().split()]
    hits = sum(word in heard for word in expected)
    assert hits / len(expected) >= 0.8, text
