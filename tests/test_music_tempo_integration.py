"""A música no andamento do projeto com ffmpeg de verdade: as medidas de cada critério do card DMK-67.

- um loop de 100 BPM num projeto de 120 BPM é esticado na razão 100/120 sem mudar o tom, e as batidas caem na grade (±15 ms);
- a detecção de BPM acerta numa Faixa de Ritmo gerada a 90, 120 e 128 BPM (±1 BPM);
- o corte arrastado a um tempo cai nele (a conta pura está em `test_tempo_grid.py`; aqui, o Cortar no ritmo pela grade);
- o projeto sem `audio.tempo` se comporta como antes.

Os arquivos são gerados no teste (a Faixa de Ritmo do gerador, tons do `sine`); a saída é WAV, onde a duração e a posição de
cada batida se medem sem a perda do AAC.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.analysis.tempo import estimate_tempo
from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.media.probe import probe
from dmaker.media.wavio import read_wav_float
from dmaker.pipeline import RenderOptions, create_renderer
from dmaker.pipeline.audio_analysis import AudioAnalysisService
from dmaker.pipeline.beat_cut import cut_on_beat
from dmaker.pipeline.edit_history import history_listing, undo_edit
from dmaker.pipeline.generated_sounds import generate_sound_file
from dmaker.pipeline.layout import project_layout
from dmaker.pipeline.projects import load_project
from dmaker.pipeline.tempo_detect import detect_music_file, detect_music_tempo

from .conftest import requires_ffmpeg
from .test_audio_effects_integration import make_video_with_tone, no_sync

pytestmark = requires_ffmpeg

RATE = 48000
LENGTH = 20.0


def ffmpeg(*args: str) -> None:
    subprocess.run([str(config.find_tool("ffmpeg")), "-y", "-loglevel", "error", *args], check=True)


def rhythm(folder: Path, bpm: float, beats: int = 16, name: str | None = None) -> Path:
    """Uma Faixa de Ritmo do gerador (um clique de metrônomo por tempo, sem destaque) no andamento `bpm`."""
    path = folder / (name or f"ritmo{bpm:g}.wav")
    generate_sound_file(
        "rhythm_track",
        {"tempo_bpm": bpm, "beats": beats, "beat_sound": "metronome", "accent_first": False},
        None,
        path,
        overwrite=True,
    )
    return path


def silence(folder: Path, seconds: float = LENGTH) -> Path:
    ffmpeg(
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(seconds), str(folder / "silencio.wav")
    )
    return folder / "silencio.wav"


def audio_project(folder: Path, music: dict, tempo: dict | None = None) -> Project:
    """Um projeto só de áudio (WAV) de 20 s: o silêncio dá a duração e a música toca por cima, em loop."""
    silence(folder)
    audio: dict = {
        "normalize": "off",
        "music": {"volume": 1.0, "ducking": False, "fade_in": 0, "fade_out": 0, **music},
        "voiceover": [{"src": "silencio.wav"}],
    }
    if tempo is not None:
        audio["tempo"] = tempo
    project = Project.model_validate(
        {"name": "andamento", "timeline": [], "output": {"preset": "audio/wav"}, "audio": audio}
    )
    project.base_dir = folder
    return project


def render(project: Project, folder: Path, name: str = "saida") -> np.ndarray:
    out = folder / f"{name}.wav"
    create_renderer(project, RenderOptions(quiet=True, out=out), runner=SubprocessRunner(quiet=True)).run()
    samples, _ = read_wav_float(out)
    return samples


def mono(samples: np.ndarray) -> np.ndarray:
    return samples.mean(axis=1) if samples.ndim == 2 else samples


def envelope(samples: np.ndarray) -> np.ndarray:
    """O módulo médio a cada milissegundo, suavizado por 9 ms: o relógio das batidas para comparar duas mixagens."""
    blocks = np.abs(mono(samples))
    count = len(blocks) // (RATE // 1000)
    values = blocks[: count * (RATE // 1000)].reshape(count, RATE // 1000).mean(axis=1)
    kernel = np.hanning(9)
    return np.convolve(values, kernel / kernel.sum(), mode="same")


def lag_ms(a: np.ndarray, b: np.ndarray) -> int:
    """Quantos milissegundos `a` anda depois de `b` (positivo: `a` está atrasado), pelo pico da correlação cruzada."""
    first, second = envelope(a), envelope(b)
    size = min(len(first), len(second))
    first, second = first[:size] - first[:size].mean(), second[:size] - second[:size].mean()
    fft = 1 << (2 * size).bit_length()
    corr = np.fft.irfft(np.fft.rfft(first, fft) * np.conj(np.fft.rfft(second, fft)), fft)
    window = np.concatenate([corr[-100:], corr[:100]])
    return int(np.argmax(window)) - 100


def frequency(samples: np.ndarray, start: float, stop: float) -> float:
    window = mono(samples)[int(start * RATE) : int(stop * RATE)]
    rising = np.nonzero(np.diff(np.signbit(window).astype(np.int8)) == 1)[0]
    crossing = rising + window[rising] / (window[rising] - window[rising + 1])
    return float((len(crossing) - 1) / ((crossing[-1] - crossing[0]) / RATE))


@pytest.fixture
def work(tmp_path) -> Path:
    return tmp_path


# ---------- critério 1: esticar de 100 para 120 BPM ----------


def test_a_100_bpm_loop_in_a_120_bpm_project_is_stretched_by_100_over_120_and_lands_on_the_grid(work):
    loop = rhythm(work, 100.0)
    assert probe(loop).duration == pytest.approx(9.6, abs=0.01)
    stretched = render(
        audio_project(
            work,
            {"src": loop.name, "bpm": 100.0, "stretch_to_tempo": True},
            {"bpm": 120.0},
        ),
        work,
        "esticada",
    )
    native = render(audio_project(work, {"src": rhythm(work, 120.0).name}, {"bpm": 120.0}), work, "nativa")
    assert len(stretched) / RATE == pytest.approx(LENGTH, abs=0.02)

    estimate = estimate_tempo(mono(stretched), RATE)
    assert estimate is not None and estimate.bpm == pytest.approx(120.0, abs=0.5)  # 100 x 120/100
    # as batidas caem na grade: o primeiro tempo em 0 s e a correlação com o metrônomo nativo a 120 BPM
    assert min(estimate.beat_offset, 0.5 - estimate.beat_offset) <= 0.015
    assert abs(lag_ms(stretched, native)) <= 15

    # a razão de duração: o loop de 9,6 s dura 8,0 s, e a emenda cai no segundo 8 (a batida volta ao compasso)
    once = render(
        audio_project(
            work, {"src": loop.name, "bpm": 100.0, "stretch_to_tempo": True, "loop": False}, {"bpm": 120.0}
        ),
        work,
        "uma-volta",
    )
    levels = envelope(once)
    last_click = int(np.nonzero(levels > levels.max() * 0.3)[0][-1])
    assert last_click / 1000 == pytest.approx(7.5, abs=0.06)  # 15 x 0,5 s: o 16º tempo do loop esticado
    assert levels[int(8.2 * 1000) :].max() < levels.max() * 0.05  # sem loop, depois de 8 s é silêncio


def test_the_stretch_does_not_change_the_pitch(work):
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "sine=f=440:d=9.6:r=48000",
        "-af",
        "aformat=channel_layouts=stereo",
        str(work / "tom.wav"),
    )
    out = render(
        audio_project(work, {"src": "tom.wav", "bpm": 100.0, "stretch_to_tempo": True}, {"bpm": 120.0}),
        work,
    )
    assert frequency(out, 1.0, 7.0) == pytest.approx(440.0, abs=1.0)  # o Mudar Andamento não mexe no tom


def test_changing_the_project_tempo_stretches_again_and_the_users_chain_is_untouched(work):
    loop = rhythm(work, 100.0)
    music = {"src": loop.name, "bpm": 100.0, "stretch_to_tempo": True}
    at_120 = estimate_tempo(mono(render(audio_project(work, music, {"bpm": 120.0}), work, "a")), RATE)
    at_90 = estimate_tempo(mono(render(audio_project(work, music, {"bpm": 90.0}), work, "b")), RATE)
    assert at_120.bpm == pytest.approx(120.0, abs=0.5) and at_90.bpm == pytest.approx(90.0, abs=0.5)
    project = audio_project(work, music, {"bpm": 90.0})
    assert project.audio.music.effects == []  # o esticamento derivado nunca vira efeito da pessoa


def test_the_first_beat_of_the_music_is_aligned_with_the_grid_by_the_entry_delay(work):
    """Um loop com 0,2 s de silêncio antes do primeiro clique (beat_offset 0,2) entra na batida da grade, e não 0,2 s depois."""
    ffmpeg(
        "-i",
        str(rhythm(work, 120.0, name="seco.wav")),
        "-af",
        "adelay=200:all=1",
        str(work / "atrasado.wav"),
    )
    aligned = render(
        audio_project(
            work,
            {
                "src": "atrasado.wav",
                "bpm": 120.0,
                "beat_offset": 0.2,
                "stretch_to_tempo": True,
                "loop": False,
            },
            {"bpm": 120.0},
        ),
        work,
        "alinhada",
    )
    reference = render(
        audio_project(work, {"src": "seco.wav", "loop": False}, {"bpm": 120.0}), work, "referencia"
    )
    assert abs(lag_ms(aligned, reference)) <= 15


# ---------- a emenda do loop ----------


def test_the_loop_seam_of_a_file_that_does_not_close_whole_beats_has_no_click(work):
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "sine=f=221.3:d=9.65:r=48000",
        "-af",
        "aformat=channel_layouts=stereo,volume=0.5",
        str(work / "tom.wav"),
    )
    out = mono(
        render(
            audio_project(work, {"src": "tom.wav", "bpm": 100.0, "stretch_to_tempo": True}, {"bpm": 120.0}),
            work,
        )
    ).astype(np.float64)
    step = np.abs(np.diff(out))
    normal = step[int(1.0 * RATE) : int(3.0 * RATE)].max()
    for seam_seconds in (8.0, 16.0):  # 9,65 s x 100/120 = 8,04 s: o loop vale 8,0 s
        seam = int(round(seam_seconds * RATE))
        assert (
            step[seam - 960 : seam + 960].max() <= normal * 1.5
        )  # o salto na emenda é o passo normal do tom


# ---------- critério 2: a detecção do BPM ----------


@pytest.mark.parametrize("bpm", [90.0, 120.0, 128.0])
def test_the_detection_finds_the_bpm_of_a_generated_rhythm_track_within_one_bpm(work, bpm):
    path = rhythm(work, bpm, beats=32)
    project = audio_project(work, {"src": path.name})
    detection = detect_music_file(project, AudioAnalysisService(SubprocessRunner(quiet=True), probe, no_sync))
    assert detection.bpm == pytest.approx(bpm, abs=1.0)
    assert (
        detection.beat_offset == pytest.approx(0.0, abs=0.015) or detection.beat_offset > 60.0 / bpm - 0.015
    )
    assert detection.confidence > 0.3 and not detection.warnings


def test_detecting_with_apply_writes_the_music_fields_in_one_undoable_step(work):
    path = rhythm(work, 128.0, beats=32)
    audio_project(work, {"src": path.name}).save(work / "spec.json")
    service = AudioAnalysisService(SubprocessRunner(quiet=True), probe, no_sync)
    suggestion = detect_music_tempo(work / "spec.json", service=service)
    assert not suggestion.applied and load_project(work / "spec.json").audio.music.bpm is None  # só sugeriu
    applied = detect_music_tempo(work / "spec.json", apply=True, service=service)
    music = load_project(work / "spec.json").audio.music
    assert applied.applied and music.bpm == pytest.approx(128.0, abs=1.0) and not music.stretch_to_tempo
    assert history_listing(work / "spec.json")["undo"][0]["label"] == "Andamento da música"
    undo_edit(work / "spec.json")
    assert load_project(work / "spec.json").audio.music.bpm is None


# ---------- critério 3: cortar no ritmo pela grade ----------


def test_cut_on_beat_with_the_grid_source_lands_each_cut_exactly_on_a_beat(work):
    make_video_with_tone(work / "video.mp4", seconds=8.0)
    project = Project.model_validate(
        {
            "name": "grade",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "timeline": [
                {"type": "clip", "src": "video.mp4", "start": 0.0, "end": 2.1, "mute": True},
                {"type": "clip", "src": "video.mp4", "start": 2.1, "end": 4.15, "mute": True},
                {"type": "clip", "src": "video.mp4", "start": 4.15, "end": 6.3, "mute": True},
            ],
            "audio": {"tempo": {"bpm": 120}, "normalize": "off"},
        }
    )
    project.base_dir = work
    project.save(work / "spec.json")
    service = AudioAnalysisService(SubprocessRunner(quiet=True), probe, no_sync)

    proposal = cut_on_beat(work / "spec.json", source="grid", service=service)
    assert proposal.bpm == 120.0 and not proposal.applied
    assert [round(p.beat, 3) for p in proposal.proposals] == [
        2.0,
        4.0,
    ]  # os tempos da grade mais perto de 2,1 e 4,15
    assert [round(p.shift, 3) for p in proposal.proposals] == [-0.1, -0.15]

    applied = cut_on_beat(work / "spec.json", source="grid", apply=True, service=service)
    assert applied.moved == 2
    after = load_project(work / "spec.json")
    ends = [span[1] for span in project_layout(after, probe, no_sync).spans[:-1]]
    assert ends == [
        pytest.approx(2.0, abs=0.03),
        pytest.approx(4.0, abs=0.03),
    ]  # nos tempos, a um quadro de erro

    bars = cut_on_beat(work / "spec.json", source="grid", params={"level": "bar"}, service=service)
    assert [round(p.beat, 3) for p in bars.proposals if p.beat is not None] == [2.0, 4.0]  # compassos de 2 s


def test_cut_on_beat_with_the_grid_needs_the_project_tempo(work):
    make_video_with_tone(work / "video.mp4", seconds=8.0)
    project = Project.model_validate(
        {
            "name": "sem-grade",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "timeline": [
                {"type": "clip", "src": "video.mp4", "start": 0.0, "end": 2.0, "mute": True},
                {"type": "clip", "src": "video.mp4", "start": 2.0, "end": 4.0, "mute": True},
            ],
        }
    )
    project.base_dir = work
    project.save(work / "spec.json")
    service = AudioAnalysisService(SubprocessRunner(quiet=True), probe, no_sync)
    with pytest.raises(ValueError, match="audio.tempo"):
        cut_on_beat(work / "spec.json", source="grid", service=service)


# ---------- critério 4: o projeto sem audio.tempo se comporta como antes ----------


def test_a_project_without_tempo_renders_the_same_sound_whether_or_not_the_fields_exist(work):
    loop = rhythm(work, 100.0)
    plain = render(audio_project(work, {"src": loop.name}), work, "sem")
    with_tempo_only = render(audio_project(work, {"src": loop.name}, {"bpm": 120.0}), work, "so-grade")
    with_bpm_only = render(
        audio_project(work, {"src": loop.name, "bpm": 100.0}, {"bpm": 120.0}), work, "so-bpm"
    )
    assert plain.shape == with_tempo_only.shape == with_bpm_only.shape
    assert np.array_equal(plain, with_tempo_only) and np.array_equal(plain, with_bpm_only)  # mesmas amostras
    # nenhum efeito novo no cache: a música foi lida direto do arquivo, sem processar
    assert estimate_tempo(mono(plain), RATE).bpm == pytest.approx(100.0, abs=0.5)
