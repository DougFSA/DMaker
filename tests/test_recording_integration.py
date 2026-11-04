"""Gravar e regravar com o ffmpeg de verdade: uma gravação recebida em pedaços entra na mixagem, e o punch-in de 3 s troca só
aquele trecho sem estalo nas emendas, com o take antigo ainda disponível.

Os sinais são tons de fase conhecida. O "salto" é a maior diferença entre amostras vizinhas, em fração do pico: um seno
limpo de 300 Hz a 48 kHz anda 0,039 por amostra; uma emenda seca entre dois tons de fase diferente salta uns 0,4.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.pipeline import RenderOptions, create_renderer
from dmaker.pipeline.edits import apply_edit
from dmaker.pipeline.recordings import RecordingStore, edit_for_recording

from .conftest import requires_ffmpeg
from .test_audio_effects_integration import decode

pytestmark = requires_ffmpeg

RATE = 48000
SMOOTH_STEP = 0.06  # um tom limpo de até 400 Hz fica abaixo disto
VOICE_HZ, TAKE_HZ, TAKE_PHASE = 220.0, 300.0, 1.0


def ffmpeg(*args: str) -> None:
    subprocess.run([str(config.find_tool("ffmpeg")), "-y", "-loglevel", "error", *args], check=True)


def voice_file(folder: Path, seconds: float = 8.0) -> Path:
    path = folder / "voz.wav"
    ffmpeg(
        "-f", "lavfi", "-i", f"aevalsrc=0.5*sin(2*PI*{VOICE_HZ}*t)|0.5*sin(2*PI*{VOICE_HZ}*t):s={RATE}:d={seconds}",
        "-c:a", "pcm_f32le", str(path),
    )  # fmt: skip
    return path


def record_take(folder: Path, *, seconds: float, start: float) -> dict:
    """Um tom de outra frequência e fase "gravado" em pedaços de 1 s, como o navegador manda, e finalizado."""
    store = RecordingStore(folder)
    status = store.create(
        RATE, 1, start=start, label="Take 2", punch={"target": "audio.voiceover.0", "start": 3.0, "end": 6.0}
    )
    t = np.arange(round(seconds * RATE)) / RATE
    wave = (0.5 * np.sin(2 * np.pi * TAKE_HZ * t + TAKE_PHASE)).astype("<f4")
    for seq in range(int(np.ceil(seconds))):
        store.put_chunk(status.id, seq, wave[seq * RATE : (seq + 1) * RATE].tobytes())
    return edit_for_recording(store.finish(status.id))


def project_with(folder: Path, voiceover: list[dict]) -> Project:
    project = Project.model_validate(
        {
            "name": "regravacao",
            "output": {"preset": "audio/wav"},
            "timeline": [],
            "audio": {"voiceover": voiceover},
        }
    )
    project.base_dir = folder
    return project


def render(project: Project, folder: Path, name: str) -> np.ndarray:
    out = folder / f"{name}.wav"
    create_renderer(project, RenderOptions(quiet=True, out=out), runner=SubprocessRunner(quiet=True)).run()
    return decode(out, RATE, 1)[:, 0]


def max_step(samples: np.ndarray) -> float:
    """O maior salto entre amostras vizinhas, em fração do pico do próprio trecho."""
    return float(np.max(np.abs(np.diff(samples))) / np.max(np.abs(samples)))


def dominant_hz(samples: np.ndarray) -> float:
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return float(np.argmax(spectrum) * RATE / len(samples))


def test_punch_in_de_3_s_troca_so_o_trecho_sem_estalo_e_guarda_o_take_antigo(tmp_path):
    voice_file(tmp_path)
    original = project_with(tmp_path, [{"src": "voz.wav", "start": 0}])
    baseline = render(original, tmp_path, "base")
    op = record_take(tmp_path, seconds=5.0, start=2.0)  # a regravação começou em 2 s e vai até 7 s
    assert op["type"] == "audio_punch"
    punched = apply_edit(original, op)
    heard = render(punched, tmp_path, "punch")

    # só o trecho de 3 a 6 s mudou: antes e depois soam como o original (mesma frequência, mesmo nível)
    scale = np.max(np.abs(baseline)) / np.max(np.abs(heard[: 2 * RATE]))
    outside = np.r_[0 : int(2.9 * RATE), int(6.1 * RATE) : int(7.9 * RATE)]
    assert np.max(np.abs(heard[outside] * scale - baseline[outside])) < 0.02
    inside = heard[int(3.2 * RATE) : int(5.8 * RATE)]
    assert dominant_hz(inside) == pytest.approx(TAKE_HZ, abs=3)
    assert len(heard) == pytest.approx(len(baseline), abs=RATE * 0.05)

    # sem estalo: nas duas emendas o maior salto fica dentro do de um tom limpo
    for seam in (3.0, 6.0):
        around = heard[int((seam - 0.05) * RATE) : int((seam + 0.05) * RATE)]
        assert max_step(around) < SMOOTH_STEP, f"estalo na emenda de {seam} s"
    assert max_step(heard) < SMOOTH_STEP

    # o take antigo continua disponível, e trocar de volta devolve o original no trecho
    middle = punched.audio.voiceover[1]
    assert [take.label for take in middle.takes] == ["Original"]
    restored = render(
        apply_edit(punched, {"type": "voiceover_take_set", "target": "audio.voiceover.1", "take": 0}),
        tmp_path,
        "volta",
    )
    assert dominant_hz(restored[int(3.2 * RATE) : int(5.8 * RATE)]) == pytest.approx(VOICE_HZ, abs=3)


def test_a_emenda_seca_sem_o_fade_estala_e_prova_que_a_medida_enxerga(tmp_path):
    """O controle: os mesmos três pedaços sem o fade de 10 ms saltam muito mais, então o teste acima não passa por acaso."""
    voice_file(tmp_path)
    record_take(tmp_path, seconds=5.0, start=2.0)
    store = RecordingStore(tmp_path)
    src = store.list()[0].src
    seamed = project_with(
        tmp_path,
        [
            {"src": "voz.wav", "start": 0, "end": 3.0},
            {"src": src, "start": 3.0, "offset": 1.0, "end": 4.0},
            {"src": "voz.wav", "start": 6.0, "offset": 6.0},
        ],
    )
    # só as primeiras amostras de cada lado da emenda de 3 s: um seno com fase trocada salta de uma vez
    heard = render(seamed, tmp_path, "seca")
    around = heard[int(2.95 * RATE) : int(3.05 * RATE)]
    assert max_step(around) > 0.2


def test_a_gravacao_nova_entra_na_mixagem_no_instante_compensado(tmp_path):
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={RATE}:cl=mono",
        "-t",
        "6",
        "-c:a",
        "pcm_f32le",
        str(tmp_path / "silencio.wav"),
    )
    op = record_take(tmp_path, seconds=3.0, start=1.5)
    plain = {**op, "type": "audio_record_add"}
    plain.pop("target", None)
    for key in ("end", "recorded_at", "label"):
        plain.pop(key, None)
    plain["start"] = 1.5
    project = apply_edit(project_with(tmp_path, []), plain)
    heard = render(project, tmp_path, "nova")
    before = heard[: int(1.4 * RATE)]
    during = heard[int(1.7 * RATE) : int(4.3 * RATE)]
    assert np.max(np.abs(before)) < 1e-3
    assert dominant_hz(during) == pytest.approx(TAKE_HZ, abs=3)
