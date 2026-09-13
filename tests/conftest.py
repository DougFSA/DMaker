from __future__ import annotations

import os
from pathlib import Path

import pytest

from dmaker import config
from dmaker.media import ffmpeg

# cache e saída dos testes ficam fora dos diretórios de trabalho normais
_TEST_CACHE = config.ROOT / "cache" / "_tests"
os.environ.setdefault("DMAKER_TEST", "1")


def ffmpeg_available() -> bool:
    return config.find_tool("ffmpeg") is not None and config.find_tool("ffprobe") is not None


requires_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg não instalado (dmaker setup)")


@pytest.fixture(scope="session")
def synthetic_media(tmp_path_factory) -> dict[str, Path]:
    """Dois clipes de teste (padrão de cores + tom), uma imagem, uma música e um SRT."""
    if not ffmpeg_available():
        pytest.skip("ffmpeg não instalado")
    d = tmp_path_factory.mktemp("media")
    clip_a = d / "a.mp4"
    clip_b = d / "b.mp4"
    music = d / "music.wav"
    photo = d / "photo.png"
    srt = d / "falas.srt"
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(clip_a),
        ],
        quiet=True,
    )
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "smptebars=size=720x1280:rate=30",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(clip_b),
        ],
        quiet=True,
    )
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:sample_rate=48000",
            "-t",
            "20",
            "-c:a",
            "pcm_s16le",
            str(music),
        ],
        quiet=True,
    )
    ffmpeg.run(
        ["-f", "lavfi", "-i", "testsrc=size=1600x900:rate=1", "-frames:v", "1", str(photo)], quiet=True
    )
    srt.write_text(
        "1\n00:00:00,200 --> 00:00:01,600\nOlá, este é um teste\n\n"
        "2\n00:00:01,700 --> 00:00:03,400\nde legendas curtas no DMaker.\n\n"
        "3\n00:00:03,500 --> 00:00:05,000\nFuncionou?\n",
        encoding="utf-8",
    )
    return {"clip_a": clip_a, "clip_b": clip_b, "music": music, "photo": photo, "srt": srt, "dir": d}
