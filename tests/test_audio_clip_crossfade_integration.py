"""O crossfade de som no corte entre dois clipes (J-cut e L-cut), com ffmpeg de verdade.

Um quadro claro e um escuro, cada um com o seu bipe (1000 Hz e 2000 Hz, amplitudes iguais), dão as duas medidas do
critério: a imagem troca no quadro exato do corte e o som cruza meio segundo em volta dele. Cada bipe é medido por um
filtro de Goertzel na frequência dele, em blocos curtos, então o nível de um não se mistura com o do outro.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.domain.spec import Project
from dmaker.media import ffmpeg
from dmaker.media.audiosync import SyncResult
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.preview_audio import PreviewAudioBuilder

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

RATE = 16000
FPS = 30
CUT_AT = 4.0  # o clipe A dura 4 s: o corte seco cai aqui
AMPLITUDE = 0.4
# o bipe sai igual nos dois canais e a decodificação em mono soma os dois com 0,707 cada: o nível medido é 1,414 vezes maior
LEVEL = AMPLITUDE * math.sqrt(2)


def make_clip_source(
    path: Path, color: str, hz: float, seconds: float = 10.0, amp: float = AMPLITUDE
) -> Path:
    """Vídeo de uma cor só com um bipe contínuo: a cor diz de que lado do corte o quadro é, a frequência de quem é o som."""
    ffmpeg.run(
        ["-f", "lavfi", "-i", f"color=c={color}:size=160x90:rate={FPS}:d={seconds}"]
        + ["-f", "lavfi", "-i", f"aevalsrc={amp}*sin(2*PI*{hz}*t)|{amp}*sin(2*PI*{hz}*t):s=48000:d={seconds}"]
        + [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        quiet=True,
    )
    return path


def no_sync(master: Path, other: Path, master_stream: int, other_stream: int) -> SyncResult:
    return SyncResult(0.0, confidence=0.0)


def decode_audio(path: Path) -> np.ndarray:
    command = [
        str(config.find_tool("ffmpeg")),
        "-v",
        "error",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(RATE),
    ]
    command += ["-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(command, capture_output=True, check=True).stdout, dtype="<f4")


def frame_brightness(path: Path) -> list[float]:
    """A média de cinza de cada quadro, na ordem."""
    command = [
        str(config.find_tool("ffmpeg")),
        "-v",
        "error",
        "-i",
        str(path),
        "-an",
        "-vf",
        "scale=16:9,format=gray",
    ]
    command += ["-f", "rawvideo", "-"]
    data = np.frombuffer(subprocess.run(command, capture_output=True, check=True).stdout, dtype=np.uint8)
    return [float(frame.mean()) for frame in data.reshape(-1, 16 * 9)]


def tone_level(samples: np.ndarray, hz: float, at: float, block: float = 0.05) -> float:
    """A amplitude do tom de `hz` num bloco centrado em `at`, por Goertzel (o nível de um tom puro de amplitude A é A)."""
    half = int(block * RATE / 2)
    centre = int(at * RATE)
    chunk = samples[centre - half : centre + half].astype(np.float64)
    t = np.arange(len(chunk)) / RATE
    window = np.hanning(len(chunk))
    real = float(np.sum(chunk * window * np.cos(2 * np.pi * hz * t)))
    imag = float(np.sum(chunk * window * np.sin(2 * np.pi * hz * t)))
    return 2.0 * math.hypot(real, imag) / float(np.sum(window))


@pytest.fixture
def media(tmp_path) -> Path:
    make_clip_source(tmp_path / "a.mp4", "white", 1000.0)
    make_clip_source(tmp_path / "b.mp4", "black", 2000.0)
    return tmp_path


def spec(folder: Path, crossfade: dict | None, transition: dict | None = None) -> Project:
    second: dict = {"type": "clip", "src": "b.mp4", "start": 3, "end": 7}
    if crossfade is not None:
        second["audio_crossfade"] = crossfade
    if transition is not None:
        second["transition"] = transition
    project = Project.model_validate(
        {
            "name": "cruza",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "timeline": [{"type": "clip", "src": "a.mp4", "start": 2, "end": 6}, second],
            "audio": {"normalize": "off"},
        }
    )
    project.base_dir = folder
    return project


def render(project: Project, folder: Path, name: str):
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=folder / f"{name}.mp4", thumbnail=False),
        offset_finder=no_sync,
        cache_dir=folder / f"mez-{name}",
        jobs_dir=folder / f"jobs-{name}",
    ).run()
    return result


def test_a_hard_image_cut_with_a_half_second_sound_crossfade_swaps_the_frame_on_time_and_crosses_the_sound(
    media,
):
    result = render(spec(media, {"duration": 0.5}), media, "jl")
    brightness = frame_brightness(result.output)
    swap = next(index for index, value in enumerate(brightness) if value < 128)
    assert swap == round(CUT_AT * FPS)  # a imagem troca no quadro exato do corte
    assert (
        brightness[swap - 1] > 200 and brightness[swap] < 50
    )  # sem quadro intermediário: continua um corte seco

    sound = decode_audio(result.output)
    # antes do crossfade só o bipe do clipe A; depois, só o do B
    assert tone_level(sound, 1000, CUT_AT - 0.6) == pytest.approx(LEVEL, rel=0.08)
    assert tone_level(sound, 2000, CUT_AT - 0.6) < 0.02
    assert tone_level(sound, 2000, CUT_AT + 0.6) == pytest.approx(LEVEL, rel=0.08)
    assert tone_level(sound, 1000, CUT_AT + 0.6) < 0.02
    # no corte, os dois tons juntos (potência constante: cada um a 1/raiz(2) da amplitude)
    middle = LEVEL / math.sqrt(2)
    assert tone_level(sound, 1000, CUT_AT) == pytest.approx(middle, rel=0.12)
    assert tone_level(sound, 2000, CUT_AT) == pytest.approx(middle, rel=0.12)
    # o som de A ainda se ouve DEPOIS do corte (L-cut) e o de B já se ouve ANTES (J-cut)
    assert tone_level(sound, 1000, CUT_AT + 0.15) > 0.02
    assert tone_level(sound, 2000, CUT_AT - 0.15) > 0.02
    # e o cruzamento dura os 0,5 s pedidos: fora de CUT_AT +- 0,25 s o som é de um lado só
    assert tone_level(sound, 1000, CUT_AT + 0.35) < 0.03
    assert tone_level(sound, 2000, CUT_AT - 0.35) < 0.03


def test_the_sound_without_a_crossfade_is_a_hard_cut_like_the_image(media):
    result = render(spec(media, None), media, "seco")
    sound = decode_audio(result.output)
    assert tone_level(sound, 1000, CUT_AT - 0.1) == pytest.approx(LEVEL, rel=0.08)
    assert tone_level(sound, 2000, CUT_AT - 0.1) < 0.02
    assert tone_level(sound, 2000, CUT_AT + 0.1) == pytest.approx(LEVEL, rel=0.08)


def test_the_preview_audio_crosses_the_sound_like_the_render(media, tmp_path_factory):
    project = spec(media, {"duration": 0.5})
    builder = PreviewAudioBuilder(
        runner=SubprocessRunner(quiet=True),
        offset_finder=no_sync,
        cache_dir=tmp_path_factory.mktemp("prev"),
        jobs_dir=tmp_path_factory.mktemp("jobs"),
    )
    mixed = builder.build(project)
    sound = decode_audio(mixed.path)
    assert tone_level(sound, 1000, CUT_AT + 0.15) > 0.02
    assert tone_level(sound, 2000, CUT_AT - 0.15) > 0.02
    middle = LEVEL / math.sqrt(2)
    assert tone_level(sound, 1000, CUT_AT) == pytest.approx(middle, rel=0.15)


def test_the_crossfade_shortens_to_the_sound_the_source_has_and_warns(media):
    """O clipe B começa a 0,1 s do início do arquivo: só há 0,1 s de som antes do ponto de entrada."""
    project = spec(media, {"duration": 0.5})
    project.timeline[1].start = 0.1
    project.timeline[1].end = 4.1
    result = render(project, media, "curto")
    assert any("encurtou" in warning for warning in result.warnings)
    sound = decode_audio(result.output)
    assert tone_level(sound, 2000, CUT_AT - 0.15) < 0.02  # o som de B só começa 0,1 s antes do corte
    assert tone_level(sound, 2000, CUT_AT - 0.05) > 0.02


def test_a_real_image_transition_ignores_the_sound_crossfade(media):
    project = spec(media, {"duration": 0.5}, {"type": "fade", "duration": 0.5})
    result = render(project, media, "transicao")
    assert any("ignorado" in warning for warning in result.warnings)


def test_a_project_without_the_field_keeps_the_same_mezzanine_hash(media):
    one = spec(media, None)
    two = spec(media, None)
    first = render(one, media, "igual-a")
    second = render(two, media, "igual-b")

    def names(folder: str) -> list[str]:
        return sorted(path.name for path in (media / folder).glob("*.mov"))

    assert names("mez-igual-a") == names("mez-igual-b") and names("mez-igual-a")
    assert first.duration == second.duration
