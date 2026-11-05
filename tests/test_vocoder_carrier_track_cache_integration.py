"""A invalidação, a prévia e a cadeia da portadora vinda de outra trilha, com ffmpeg de verdade (DMK-70).

O alinhamento de cada trilha hospedeira está em `test_vocoder_carrier_track_integration.py`; aqui ficam as perguntas de cache e de
caminho: trocar a trilha ou o arquivo dela muda o som, a prévia soa como o render e uma portadora que é ela mesma uma trilha com
Vocoder se resolve sem depender da ordem da spec.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker.domain.spec import Project

from .conftest import requires_ffmpeg
from .test_dynamics_integration import RATE, write_wav
from .test_vocoder_carrier_track_integration import (
    MUSIC_VOLUME,
    TOLERANCE,
    VOCODER,
    clip_case,
    energy_onset,
    harmonic_burst,
    make_video,
    noise,
    preview_pcm,
    project_for,
    render_pcm,
    voice_case,
)

pytestmark = requires_ffmpeg


def test_changing_the_carrier_file_changes_the_processed_voice(tmp_path):
    """O arquivo da portadora entra na chave do item processado: com o mesmo spec e o mesmo cache, a rajada que muda de lugar na
    música muda o som."""
    first = render_pcm(voice_case(tmp_path), tmp_path, "primeiro", cache="mez")
    assert energy_onset(first, 3.0, 6.5) == pytest.approx(4.0, abs=TOLERANCE)
    second = render_pcm(voice_case(tmp_path, burst=(5.0, 7.0)), tmp_path, "segundo", cache="mez")
    assert energy_onset(second, 3.0, 6.5) == pytest.approx(5.0, abs=TOLERANCE)


def test_changing_the_carrier_file_changes_the_clip_mezzanine(tmp_path):
    """O mezanino do clipe com Vocoder pula o `process` quando está em cache, então a chave dele precisa da identidade da trilha."""
    before = render_pcm(clip_case(tmp_path), tmp_path, "antes", cache="mez")
    assert energy_onset(before, 5.0, 9.5) == pytest.approx(7.0, abs=TOLERANCE)
    after = render_pcm(clip_case(tmp_path, burst=(8.0, 9.5)), tmp_path, "depois", cache="mez")
    assert energy_onset(after, 5.0, 9.8) == pytest.approx(8.0, abs=TOLERANCE)


def test_changing_the_carrier_track_changes_the_sound(tmp_path):
    make_video(tmp_path, 10.0)
    write_wav(tmp_path / "fala.wav", noise(6.0))
    write_wav(tmp_path / "gravador.wav", harmonic_burst(10.0, [(6.0, 8.0)]))
    write_wav(tmp_path / "musica.wav", harmonic_burst(10.0, [(4.0, 5.0)]))

    def render_with(track: str, name: str) -> np.ndarray:
        project = project_for(
            tmp_path,
            [{"type": "clip", "source": "cam", "start": 0, "end": 10, "mute": True}],
            {
                "voiceover": [
                    {"src": "fala.wav", "start": 3.0, "effects": [{**VOCODER, "carrier_track": track}]}
                ],
                "tracks": [{"source": "gravador", "volume": MUSIC_VOLUME}],
                "music": {"src": "musica.wav", "volume": MUSIC_VOLUME, "ducking": False},
            },
            {"cam": {"src": "video.mp4"}, "gravador": {"src": "gravador.wav", "sync": 0.0}},
        )
        return render_pcm(project, tmp_path, name, cache="mez")

    assert energy_onset(render_with("MUS", "musica"), 3.0, 5.5) == pytest.approx(4.0, abs=TOLERANCE)
    assert energy_onset(render_with("A2", "faixa"), 5.0, 8.5) == pytest.approx(6.0, abs=TOLERANCE)


def windows_db(samples: np.ndarray, seconds: float = 0.5) -> list[float]:
    size = round(seconds * RATE)
    return [
        20
        * np.log10(
            max(float(np.sqrt((samples[i * size : (i + 1) * size].astype(np.float64) ** 2).mean())), 1e-9)
        )
        for i in range(len(samples) // size)
    ]


def test_the_preview_sounds_like_the_render_within_half_a_decibel_per_window(tmp_path):
    rendered = windows_db(render_pcm(voice_case(tmp_path), tmp_path, "mix"))
    previewed = windows_db(preview_pcm(voice_case(tmp_path), tmp_path))
    compared = 0
    for heard, expected in zip(previewed, rendered, strict=False):
        if expected > -50:  # o piso de uma janela calada não é som
            assert heard == pytest.approx(expected, abs=0.5)
            compared += 1
    assert compared >= 4


def chain_project(folder: Path, reverse: bool = False) -> Project:
    """A voz tem o Vocoder com portadora na música, e a música tem o próprio Vocoder (com a portadora gerada)."""
    make_video(folder)
    write_wav(folder / "fala.wav", noise(3.0))
    write_wav(folder / "fala2.wav", noise(1.0, seed=9))
    write_wav(folder / "musica.wav", harmonic_burst(10.0, [(4.0, 6.0)]))
    voices = [
        {"src": "fala.wav", "start": 3.0, "effects": [VOCODER]},
        {"src": "fala2.wav", "start": 8.0},
    ]
    music = {
        "src": "musica.wav",
        "volume": 1.0,
        "ducking": False,
        "effects": [{"type": "vocoder", "noise_level": 0, "original_level": 0}],
    }
    audio = {"music": music, "voiceover": voices[::-1] if reverse else voices}
    return project_for(
        folder, [{"type": "clip", "src": "video.mp4", "start": 0, "end": 10, "mute": True}], audio
    )


def test_a_carrier_that_is_itself_a_vocoded_track_resolves_in_any_order_of_the_spec(tmp_path):
    forward = render_pcm(chain_project(tmp_path), tmp_path, "direto")
    backward = render_pcm(chain_project(tmp_path, reverse=True), tmp_path, "inverso")
    assert float(np.abs(forward - backward).max()) == 0.0
    assert energy_onset(forward, 3.0, 6.5) == pytest.approx(4.0, abs=0.03)
