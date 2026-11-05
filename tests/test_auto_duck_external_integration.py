"""Auto Duck da faixa externa sob a câmera, a voz gravada, a narração e a música, com ffmpeg de verdade (DMK-69).

A faixa externa é misturada dentro do mezanino do clipe, então a chave dela é medida ANTES dos mezaninos. Cada teste usa
uma faixa externa que é um tom constante e uma chave de OUTRO tom em rajadas, e mede no arquivo final, por FFT, o nível do
tom de fundo: ele cai a quantidade pedida só enquanto a chave soa e fica no nível original fora das rampas.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker.domain.spec import Project
from dmaker.media import ffmpeg
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.narration import NarrationService
from dmaker.pipeline.preview_audio import PreviewAudioBuilder

from .conftest import requires_ffmpeg
from .test_dynamics_integration import band_level, decode, no_sync, tone_at, write_wav
from .test_narration import FakeSynthesizer

pytestmark = requires_ffmpeg

DJ_HZ = 330  # o fundo; longe dos tons das chaves (1000 Hz a câmera e as vozes gravadas, 440 Hz o sintetizador falso)
KEY_BURSTS = [(3.0, 5.0), (7.0, 8.0)]
# a descida de 0,5 s termina quando a chave começa e a subida começa quando ela cala: o que cai nas rampas não se mede
WINDOWS = [(0.3, 2.3, 0.0), (3.2, 4.8, -12.0), (5.7, 6.4, 0.0), (7.2, 7.8, -12.0), (8.8, 9.7, 0.0)]
RULE_KEYS = ("A1", "VO", "NAR", "MUS")


def event_project(
    folder: Path, key: str | None, *, ducked: bool = True, camera_speaks: bool = True, **audio
) -> Project:
    """Um clipe de 10 s com a câmera e uma faixa externa contínua (o DJ), e a chave pedida tocando em rajadas. Sem `ducked`
    o projeto é o mesmo e sem a regra; sem `camera_speaks` a câmera do clipe fica calada."""
    write_wav(folder / "dj.wav", tone_at(DJ_HZ, 0.2, 10))
    camera = folder / "camera.wav"
    speaks = key == "A1" and camera_speaks
    write_wav(camera, tone_at(1000, 0.3, 10, KEY_BURSTS) if speaks else tone_at(1000, 0.0, 10))
    ffmpeg.run(
        ["-f", "lavfi", "-i", "color=c=gray:size=320x180:rate=15:d=10", "-i", str(camera)]
        + ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"]
        + [str(folder / "video.mp4")],
        quiet=True,
    )
    settings: dict = {"tracks": [{"source": "dj"}], "normalize": "off", **audio}
    if key == "VO":
        write_wav(folder / "fala.wav", tone_at(1000, 0.3, 10, KEY_BURSTS))
        settings["voiceover"] = [{"src": "fala.wav", "start": 0.0}]
    if key == "MUS":
        write_wav(folder / "musica.wav", tone_at(1000, 0.3, 10, KEY_BURSTS))
        settings["music"] = {"src": "musica.wav", "volume": 1.0, "ducking": False}
    if key == "NAR":
        # o sintetizador falso dura 0,05 s por caractere: 40 caracteres tocam 2 s, a partir de 3 s, e 20 tocam 1 s, a partir de 7 s
        settings["narration"] = [{"text": "x" * 40, "start": 3.0}, {"text": "y" * 20, "start": 7.0}]
    if key and ducked:
        settings["ducks"] = [{"background": "A2", "key": key, "amount_db": -12}]
    project = Project.model_validate(
        {
            "name": "evento",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "sources": {"cam": {"src": "video.mp4"}, "dj": {"src": "dj.wav", "sync": 0.0}},
            "timeline": [{"type": "clip", "source": "cam", "start": 0, "end": 10}],
            "audio": settings,
        }
    )
    project.base_dir = folder
    return project


def render_pcm(project: Project, folder: Path, name: str) -> np.ndarray:
    runner = SubprocessRunner(quiet=True)
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=folder / f"{name}.mp4", thumbnail=False),
        runner=runner,
        offset_finder=no_sync,
        narrator=NarrationService(FakeSynthesizer(), runner, folder / f"voz-{name}"),
        cache_dir=folder / f"mez-{name}",
        jobs_dir=folder / f"jobs-{name}",
    ).run()
    return decode(result.output, 16000, 1)[:, 0]


def drops(ducked: np.ndarray, plain: np.ndarray) -> list[tuple[float, float, float]]:
    """(início, fim, queda medida em dB) do tom de fundo em cada janela de `WINDOWS`."""
    return [
        (first, last, band_level(ducked, DJ_HZ, first, last) - band_level(plain, DJ_HZ, first, last))
        for first, last, _ in WINDOWS
    ]


def assert_ducks_only_while_the_key_sounds(measured: list[tuple[float, float, float]]) -> None:
    for (first, last, drop), (_, _, expected) in zip(measured, WINDOWS, strict=True):
        assert drop == pytest.approx(expected, abs=0.5), (first, last)


@pytest.mark.parametrize("key", RULE_KEYS)
def test_the_external_track_ducks_the_requested_amount_only_while_the_key_sounds(tmp_path, key):
    plain = render_pcm(event_project(tmp_path, key, ducked=False), tmp_path, "plain")
    ducked = render_pcm(event_project(tmp_path, key), tmp_path, "ducked")
    assert_ducks_only_while_the_key_sounds(drops(ducked, plain))


def test_the_a1_key_is_only_the_camera_and_never_the_external_track_it_ducks(tmp_path):
    """Com a câmera calada, o DJ (alto o bastante para ser chave) não abaixa a si mesmo: nada cai."""
    plain = render_pcm(event_project(tmp_path, "A1", ducked=False, camera_speaks=False), tmp_path, "plain")
    ducked = render_pcm(event_project(tmp_path, "A1", camera_speaks=False), tmp_path, "ducked")
    for first, last, _ in WINDOWS:
        assert band_level(ducked, DJ_HZ, first, last) == pytest.approx(
            band_level(plain, DJ_HZ, first, last), abs=0.5
        )


def test_the_preview_measures_the_same_drop_as_the_render(tmp_path):
    builder = PreviewAudioBuilder(offset_finder=no_sync, cache_dir=tmp_path / "pa", jobs_dir=tmp_path / "pj")
    plain = builder.build(event_project(tmp_path, None))
    ducked = builder.build(event_project(tmp_path, "A1"))
    assert ducked.key != plain.key
    measured = [
        (
            first,
            last,
            band_level(decode(ducked.path, 16000, 1)[:, 0], DJ_HZ, first, last)
            - band_level(decode(plain.path, 16000, 1)[:, 0], DJ_HZ, first, last),
        )
        for first, last, _ in WINDOWS
    ]
    assert_ducks_only_while_the_key_sounds(measured)


def test_an_old_project_with_music_ducking_and_no_rule_is_not_measured_and_sounds_the_same(tmp_path):
    runner = _CountingRunner()
    project = event_project(tmp_path, None, music={"src": "musica.wav", "volume": 0.5, "ducking": True})
    write_wav(tmp_path / "musica.wav", tone_at(220, 0.3, 10))
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=tmp_path / "antigo.mp4", thumbnail=False),
        runner=runner,
        offset_finder=no_sync,
        cache_dir=tmp_path / "mez-antigo",
        jobs_dir=tmp_path / "jobs-antigo",
    ).run()
    assert result.output.exists()
    assert runner.level_passes == 0  # sem regra, nenhuma passada a mais de nível


class _CountingRunner(SubprocessRunner):
    """Conta as passadas de nível do Auto Duck."""

    def __init__(self):
        super().__init__(quiet=True)
        self.level_passes = 0

    def capture(self, args, label="ffmpeg"):
        if "Auto Duck" in label:
            self.level_passes += 1
        return super().capture(args, label=label)
