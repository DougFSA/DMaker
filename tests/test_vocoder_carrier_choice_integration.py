"""O Vocoder do clipe ouvindo uma faixa externa e a escolha "ouvir a trilha mesmo muda" em cada tipo de trilha, com ffmpeg de
verdade (ajuste do DMK-70).

O sinal é o do alinhamento (`test_vocoder_carrier_track_integration.py`): um modulador de ruído branco e uma portadora em rajada de
início conhecido, com `noise_level=0` e `original_level=0`. A medida é o instante em que a energia aparece no arquivo processado do
item; com a trilha mesmo muda ele tem de ser o da rajada, e o da portadora gerada (que toca desde o começo) seria outro.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.domain.spec import Project, TrackState

from .conftest import requires_ffmpeg
from .test_dynamics_integration import RATE, decode, write_wav
from .test_vocoder_carrier_track_integration import (
    MUSIC_VOLUME,
    TOLERANCE,
    energy_onset,
    harmonic_burst,
    make_video,
    noise,
    preview_pcm,
    project_for,
    render_pcm,
)

pytestmark = requires_ffmpeg

VOCODER = {"type": "vocoder", "noise_level": 0, "original_level": 0}


@pytest.fixture(autouse=True)
def own_effects_folder(tmp_path, monkeypatch):
    """Cada teste tem a própria pasta de efeitos, para o arquivo processado do item ser o único e a medida ser dele."""
    monkeypatch.setattr(config, "AUDIO_FX_DIR", tmp_path / "fx")


def processed_item() -> np.ndarray:
    found = sorted(Path(config.AUDIO_FX_DIR).glob("*.wav"))
    assert len(found) == 1, found
    return decode(found[0], RATE, 1)[:, 0]


def rms_db(samples: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(samples.astype(np.float64) ** 2)) + 1e-12))


# ---------- parte 1: a câmera ouve uma faixa externa ----------


def camera_case(folder: Path, enabled: bool = True) -> Project:
    """Uma câmera de 10 s (fonte `cam`) em dois clipes: o primeiro, mudo, vai de 0 a 5 s, e o segundo, que NÃO é o primeiro, vai de 5
    a 10 s e tem o Vocoder ouvindo a A2. A câmera tem ruído de 5 a 7 s e depois cala. A A2 (gravador) tem uma rajada de 5,5 a 7 s,
    junto com o ruído, e outra de 8 a 9,5 s, depois que a câmera calou: ali o Vocoder não tem o que modular, e a faixa toca sozinha."""
    camera = np.concatenate(
        [
            np.zeros(round(5.0 * RATE), dtype=np.float32),
            noise(2.0),
            np.zeros(round(3.0 * RATE), dtype=np.float32),
        ]
    )
    make_video(folder, 10.0, "camera.mov", camera)
    write_wav(folder / "gravador.wav", harmonic_burst(10.0, [(5.5, 7.0), (8.0, 9.5)]))
    return project_for(
        folder,
        [
            {"type": "clip", "source": "cam", "start": 0, "end": 5, "mute": True},
            {
                "type": "clip",
                "source": "cam",
                "start": 5,
                "end": 10,
                "effects": [{**VOCODER, "carrier_track": "A2", "enabled": enabled}],
            },
        ],
        {"tracks": [{"source": "gravador", "volume": MUSIC_VOLUME * 5}]},
        {"cam": {"src": "camera.mov"}, "gravador": {"src": "gravador.wav", "sync": 0.0}},
    )


def test_the_camera_of_a_clip_that_is_not_the_first_hears_an_external_track(tmp_path):
    folder = tmp_path / "com"
    folder.mkdir()
    render_pcm(camera_case(folder), folder, "mix")
    item = processed_item()
    # o item é o som do clipe (5 s a partir do ponto de entrada): o ruído toca desde o começo dele e a rajada da A2 começa em 5,5 s
    # do projeto, 0,5 s depois do clipe; a energia do Vocoder aparece nesse instante, e não no começo do clipe
    onset = energy_onset(item, 0.0, 2.0)
    assert onset == pytest.approx(0.5, abs=TOLERANCE)


def test_the_external_track_stays_audible_in_the_mix_at_its_usual_level(tmp_path, monkeypatch):
    folder = tmp_path / "com"
    folder.mkdir()
    with_vocoder = render_pcm(camera_case(folder), folder, "ligado", cache="mez")
    monkeypatch.setattr(config, "AUDIO_FX_DIR", tmp_path / "fx-desligado")
    plain = render_pcm(camera_case(folder, enabled=False), folder, "desligado", cache="mez-desligado")
    # na segunda rajada a câmera já calou: só a A2 toca, e ela soa igual com ou sem o Vocoder lendo-a
    window = slice(round(8.2 * RATE), round(9.3 * RATE))
    assert rms_db(plain[window]) > -45.0  # a faixa toca de verdade ali
    assert abs(rms_db(with_vocoder[window]) - rms_db(plain[window])) < 0.5


# ---------- parte 2: a escolha em cada tipo de trilha ----------


def muted(project: Project, *track_ids: str) -> Project:
    """O mesmo projeto com as trilhas dadas mudas."""
    states = {track_id: TrackState(muted=True) for track_id in track_ids}
    updated = project.model_copy(update={"tracks": states})
    updated.base_dir = project.base_dir
    return updated


def voice_host(folder: Path, carrier: str, **audio) -> tuple[dict, list[dict]]:
    """A voz gravada (ruído, 3 s a partir de 1 s) com o Vocoder ouvindo `carrier` e a escolha ligada."""
    write_wav(folder / "fala.wav", noise(3.0))
    effect = {**VOCODER, "carrier_track": carrier, "carrier_ignores_mute": True}
    audio["voiceover"] = [{"src": "fala.wav", "start": 1.0, "effects": [effect]}]
    return audio, [{"type": "clip", "src": "video.mp4", "start": 0, "end": 6, "mute": True}]


def test_a_muted_music_is_still_the_carrier_when_the_choice_is_on(tmp_path):
    make_video(tmp_path, 6.0)
    write_wav(tmp_path / "musica.wav", harmonic_burst(6.0, [(2.0, 5.0)]))
    audio, timeline = voice_host(
        tmp_path, "MUS", music={"src": "musica.wav", "volume": MUSIC_VOLUME, "ducking": False}
    )
    project = muted(project_for(tmp_path, timeline, audio), "MUS")
    mix = render_pcm(project, tmp_path, "mix")
    # a voz toca de 1 a 4 s e a rajada da música de 2 a 5 s: a energia aparece em 2 s, e não em 1 s (portadora gerada)
    assert energy_onset(processed_item(), 0.0, 3.0) == pytest.approx(1.0, abs=TOLERANCE)
    assert energy_onset(mix, 1.0, 4.5) == pytest.approx(2.0, abs=TOLERANCE)
    # a mistura não tem a música (muda): depois da voz não sobra a rajada dela
    assert rms_db(mix[round(4.3 * RATE) : round(4.9 * RATE)]) < -80.0
    # a prévia soa como o render
    preview = preview_pcm(project, tmp_path)
    window = slice(round(2.2 * RATE), round(3.8 * RATE))
    assert abs(rms_db(preview[window]) - rms_db(mix[window])) < 0.5


def test_a_muted_recorded_voice_is_still_the_carrier_of_the_music(tmp_path):
    make_video(tmp_path, 6.0)
    write_wav(tmp_path / "burst.wav", harmonic_burst(6.0, [(2.0, 5.0)]))
    write_wav(tmp_path / "ruido.wav", noise(6.0))
    effect = {**VOCODER, "carrier_track": "VO", "carrier_ignores_mute": True}
    project = muted(
        project_for(
            tmp_path,
            [{"type": "clip", "src": "video.mp4", "start": 0, "end": 6, "mute": True}],
            {
                "music": {"src": "ruido.wav", "volume": 1.0, "ducking": False, "effects": [effect]},
                "voiceover": [{"src": "burst.wav", "start": 0.0}],
            },
        ),
        "VO",
    )
    render_pcm(project, tmp_path, "mix")
    assert energy_onset(processed_item(), 0.0, 6.0) == pytest.approx(2.0, abs=TOLERANCE)


def test_a_muted_narration_is_still_the_carrier_and_is_spoken_for_it(tmp_path):
    make_video(tmp_path, 8.0)
    # 80 caracteres a 0,05 s cada: a narração toca 4 s a partir de 2 s (senoide de 440 Hz do sintetizador falso)
    audio, timeline = voice_host(tmp_path, "NAR", narration=[{"text": "a" * 80, "start": 2.0, "voice": None}])
    timeline[0]["end"] = 8
    project = muted(project_for(tmp_path, timeline, audio), "NAR")
    render_pcm(project, tmp_path, "mix")
    assert energy_onset(processed_item(), 0.0, 3.0) == pytest.approx(1.0, abs=TOLERANCE)


def test_a_muted_camera_is_still_the_carrier_of_a_recorded_voice(tmp_path):
    make_video(tmp_path, 6.0, "camera.mov", harmonic_burst(6.0, [(2.0, 5.0)]))
    audio, _ = voice_host(tmp_path, "A1")
    project = muted(
        project_for(tmp_path, [{"type": "clip", "src": "camera.mov", "start": 0, "end": 6}], audio), "A1"
    )
    mix = render_pcm(project, tmp_path, "mix")
    assert energy_onset(mix, 1.0, 4.5) == pytest.approx(2.0, abs=TOLERANCE)
