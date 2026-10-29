"""O áudio da prévia contra o vídeo renderizado do mesmo projeto, com ffmpeg de verdade.

Num projeto multicâmera (câmeras mudas, a mesa com sincronia diferente de zero e a 0,5, música com span,
fonte em duas partes), o som que a interface toca precisa ser o do render: a correlação dos dois áudios, no
mesmo instante, passa de 0,98. Ruído rosa na mesa torna qualquer deslocamento de corte visível na correlação.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.domain.spec import Project
from dmaker.media import ffmpeg
from dmaker.media.audiosync import SyncResult
from dmaker.media.probe import probe
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.preview_audio import PreviewAudioBuilder

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

RATE = 16000


def no_audio_link(master: Path, other: Path, master_stream: int, other_stream: int) -> SyncResult:
    """Sem correlação entre as partes da câmera (silenciosas): uma encosta na outra, como na vista."""
    return SyncResult(0.0, confidence=0.0)


def make_media(folder: Path) -> None:
    """Câmera em duas partes de 12 s (sem som), a mesa de 40 s (ruído rosa) e uma música de 30 s."""
    for name in ("cam_a.mp4", "cam_b.mp4"):
        ffmpeg.run(
            ["-f", "lavfi", "-i", "color=c=gray:size=320x180:rate=15", "-t", "12", "-c:v", "libx264"]
            + ["-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an", str(folder / name)],
            quiet=True,
        )
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=d=40:c=pink:r=48000:seed=7:a=0.5",
            "-c:a",
            "pcm_s16le",
            str(folder / "mesa.wav"),
        ],
        quiet=True,
    )
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=330:sample_rate=48000:duration=30",
            "-c:a",
            "pcm_s16le",
            str(folder / "musica.wav"),
        ],
        quiet=True,
    )


def decode(path: Path) -> np.ndarray:
    """O áudio do arquivo em mono a 16 kHz, como números."""
    command = [str(config.find_tool("ffmpeg")), "-v", "error", "-i", str(path)]
    command += ["-vn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(command, capture_output=True, check=True).stdout, dtype=np.float32)


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    size = min(len(a), len(b))
    a, b = a[:size] - a[:size].mean(), b[:size] - b[:size].mean()
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def best_lag_ms(a: np.ndarray, b: np.ndarray, window_ms: int = 200) -> float:
    """Deslocamento (ms) de `b` em relação a `a` que mais os alinha, procurado numa janela curta."""
    size = min(len(a), len(b)) - RATE
    reach = RATE * window_ms // 1000
    scores = {
        lag: np.dot(a[RATE : RATE + size - reach], b[RATE + lag : RATE + lag + size - reach])
        for lag in range(-reach // 2, reach // 2)
    }
    return max(scores, key=scores.get) * 1000 / RATE


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    folder = tmp_path_factory.mktemp("sessao_previa")
    make_media(folder)
    project = Project.model_validate(
        {
            "name": "sessao-previa",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "sources": {
                "cam": {"parts": ["cam_a.mp4", "cam_b.mp4"], "sync": 0.0},
                "mesa": {"src": "mesa.wav", "sync": -2.0},
            },
            "timeline": [
                {"type": "clip", "source": "cam", "start": 3, "end": 9, "mute": True},
                {
                    "type": "clip",
                    "source": "cam",
                    "start": 9,
                    "end": 15,
                    "mute": True,
                    "transition": {"type": "cut"},
                },
                {
                    "type": "clip",
                    "source": "cam",
                    "start": 18,
                    "end": 21,
                    "mute": True,
                    "transition": {"type": "cut"},
                },
            ],
            "audio": {
                "tracks": [{"source": "mesa", "volume": 0.5}],
                "music": {
                    "src": "musica.wav",
                    "volume": 0.2,
                    "ducking": False,
                    "spans": [{"start": 2, "end": 9, "fade_in": 0.5, "fade_out": 1.0}],
                },
                "normalize": "off",
            },
        }
    )
    project.base_dir = folder
    return project, folder


def test_preview_audio_matches_the_rendered_video(session, tmp_path):
    project, folder = session
    builder = PreviewAudioBuilder(
        offset_finder=no_audio_link, cache_dir=tmp_path / "preview-audio", jobs_dir=tmp_path / "jobs"
    )
    audio = builder.build(project)
    assert audio.path.exists() and audio.path.suffix == ".m4a"

    render = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=tmp_path / "render.mp4", thumbnail=False),
        offset_finder=no_audio_link,
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "render-jobs",
    ).run()

    assert audio.duration == pytest.approx(render.duration, abs=0.05)
    assert probe(audio.path).duration == pytest.approx(render.duration, abs=0.1)
    preview, rendered = decode(audio.path), decode(render.output)
    assert correlation(preview, rendered) > 0.98
    assert abs(best_lag_ms(rendered, preview)) <= 25  # alinhados no corte, na segunda parte e na emenda
    # a mesa tem o ruído a 0,5: o som existe de ponta a ponta e não é silêncio
    assert float(np.sqrt(np.mean(preview**2))) > 0.01


def test_preview_audio_changes_when_the_volume_changes_without_rendering_video(session, tmp_path):
    project, folder = session
    builder = PreviewAudioBuilder(
        offset_finder=no_audio_link, cache_dir=tmp_path / "preview-audio", jobs_dir=tmp_path / "jobs"
    )
    loud = builder.build(project)

    quieter = project.model_copy(deep=True)
    quieter.base_dir = folder
    quieter.audio.tracks[0].volume = 0.25
    soft = builder.build(quieter)

    assert soft.key != loud.key
    ratio = float(np.sqrt(np.mean(decode(soft.path) ** 2)) / np.sqrt(np.mean(decode(loud.path) ** 2)))
    assert 0.3 < ratio < 0.8  # a mesa caiu pela metade; a música não mudou
    assert not list((tmp_path / "preview-audio").glob("*.mp4")) and not list(
        (tmp_path / "preview-audio").glob("*.mov")
    )
