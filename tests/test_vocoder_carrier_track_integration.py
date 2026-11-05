"""O Vocoder com a portadora vinda de outra trilha do projeto, com ffmpeg de verdade (DMK-70).

O critério do card é o alinhamento: a voz modula o trecho da trilha que toca JUNTO com ela na linha do tempo, com tolerância de
10 ms. O sinal é conhecido: um modulador contínuo de banda larga (ruído branco) e uma portadora em rajadas de início conhecido,
com `noise_level=0` e `original_level=0`. Sem som na portadora o Vocoder é mudo, então a energia do arquivo só aparece quando a
rajada começa, e a medida é o instante em que ela aparece. A música (a portadora) entra na mixagem com volume baixo para o nível
dela não mascarar o do Vocoder, que sai no nível da voz.
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
from .test_dynamics_integration import RATE, decode, no_sync, write_wav
from .test_narration import FakeSynthesizer

pytestmark = requires_ffmpeg

TOLERANCE = 0.010  # o critério do card: a energia começa onde a rajada começa, com 10 ms de folga
BURST_HZ = 220.0
# o Vocoder pede a voz e a portadora no nível em que se ouvem; a música baixa (-34 dB) deixa a rajada dela, que também toca na
# mixagem, 25 dB abaixo do Vocoder, que sai no nível da voz
MUSIC_VOLUME = 0.02
VOCODER = {"type": "vocoder", "noise_level": 0, "original_level": 0, "carrier_track": "MUS"}


def noise(seconds: float, amplitude: float = 0.3, seed: int = 3) -> np.ndarray:
    return (amplitude * np.random.default_rng(seed).standard_normal(round(seconds * RATE))).astype(np.float32)


def harmonic_burst(seconds: float, bursts: list[tuple[float, float]], f0: float = BURST_HZ) -> np.ndarray:
    """Dentes de serra somadas (harmônicos de `f0` até 4 kHz) em rajadas que começam e acabam em instantes conhecidos."""
    t = np.arange(round(seconds * RATE)) / RATE
    wave = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, int(4000 / f0)))
    gate = np.zeros_like(t)
    for first, last in bursts:
        gate[(t >= first) & (t < last)] = 1.0
    return (0.5 * wave / np.abs(wave).max() * gate).astype(np.float32)


def make_video(
    folder: Path, seconds: float = 10.0, name: str = "video.mp4", sound: np.ndarray | None = None
) -> Path:
    """Um vídeo cinza de `seconds` s; com `sound`, a trilha de áudio dele (a câmera que o Vocoder do clipe trata)."""
    command = ["-f", "lavfi", "-i", f"color=c=gray:size=320x180:rate=15:d={seconds}"]
    if sound is not None:
        write_wav(folder / f"{name}.wav", sound)
        command += ["-i", str(folder / f"{name}.wav")]
    else:
        command += ["-f", "lavfi", "-i", f"anullsrc=r={RATE}:cl=stereo"]
    # o som da câmera vai sem perda (.mov com PCM): o AAC espalha o início de uma rajada alguns milissegundos para trás, e a
    # medida de 10 ms seria do codec e não do Vocoder
    codec = "pcm_s16le" if name.endswith(".mov") else "aac"
    command += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", codec, "-shortest"]
    ffmpeg.run([*command, str(folder / name)], quiet=True)
    return folder / name


def render_pcm(project: Project, folder: Path, name: str, cache: str | None = None) -> np.ndarray:
    runner = SubprocessRunner(quiet=True)
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=folder / f"{name}.mp4", thumbnail=False),
        runner=runner,
        offset_finder=no_sync,
        narrator=NarrationService(FakeSynthesizer(), runner, folder / f"voz-{name}"),
        cache_dir=folder / (cache or f"mez-{name}"),
        jobs_dir=folder / f"jobs-{name}",
    ).run()
    return decode(result.output, RATE, 1)[:, 0]


def preview_pcm(project: Project, folder: Path) -> np.ndarray:
    builder = PreviewAudioBuilder(offset_finder=no_sync, cache_dir=folder / "pa", jobs_dir=folder / "pj")
    return decode(builder.build(project).path, RATE, 1)[:, 0]


def energy_onset(samples: np.ndarray, after: float, before: float) -> float:
    """O instante, em [after, before], em que a energia do trecho passa a metade do patamar dele (RMS em janelas de 2,5 ms)."""
    window = 120
    first, last = round(after * RATE), round(before * RATE)
    piece = samples[first:last].astype(np.float64)
    usable = len(piece) // window * window
    rms = np.sqrt((piece[:usable].reshape(-1, window) ** 2).mean(axis=1))
    level = np.percentile(rms, 90)
    assert level > 1e-3, "o trecho está em silêncio: o Vocoder não soou"
    index = int(np.argmax(rms > level * 0.5))
    return after + index * window / RATE


def only_processed_file() -> Path:
    """O único arquivo processado pelo `EffectProcessor` neste teste (os de `carriers/` e `levels/` ficam em pastas à parte)."""
    from dmaker import config

    found = sorted(Path(config.AUDIO_FX_DIR).glob("*.wav"))
    assert len(found) == 1, found
    return found[0]


def project_for(folder: Path, timeline: list[dict], audio: dict, sources: dict | None = None) -> Project:
    project = Project.model_validate(
        {
            "name": "portadora",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "sources": sources or {},
            "timeline": timeline,
            "audio": {"normalize": "off", **audio},
        }
    )
    project.base_dir = folder
    return project


def voice_case(folder: Path, start: float = 3.0, burst: tuple[float, float] = (4.0, 6.0)) -> Project:
    """A voz gravada (ruído) de 3 s em `start`, com o Vocoder ouvindo a música, que tem uma rajada em `burst`."""
    make_video(folder)
    write_wav(folder / "fala.wav", noise(3.0))
    write_wav(folder / "musica.wav", harmonic_burst(10.0, [burst]))
    return project_for(
        folder,
        [{"type": "clip", "src": "video.mp4", "start": 0, "end": 10, "mute": True}],
        {
            "voiceover": [{"src": "fala.wav", "start": start, "effects": [VOCODER]}],
            "music": {"src": "musica.wav", "volume": MUSIC_VOLUME, "ducking": False},
        },
    )


def test_the_vocoder_on_a_recorded_voice_starts_when_the_carrier_burst_starts(tmp_path):
    samples = render_pcm(voice_case(tmp_path), tmp_path, "mix")
    assert energy_onset(samples, 3.0, 6.5) == pytest.approx(4.0, abs=TOLERANCE)


# ---------- o alinhamento em cada trilha que hospeda o Vocoder ----------


def test_the_vocoder_on_a_recorded_voice_at_the_start_of_the_timeline_aligns_too(tmp_path):
    samples = render_pcm(voice_case(tmp_path, start=0.0, burst=(1.0, 2.5)), tmp_path, "mix")
    assert energy_onset(samples, 0.0, 3.0) == pytest.approx(1.0, abs=TOLERANCE)


def clip_case(folder: Path, speed: float = 1.0, burst: tuple[float, float] = (7.0, 9.0)) -> Project:
    """Dois clipes: o primeiro mudo e o segundo, que NÃO é o primeiro da linha do tempo, com a câmera em ruído e o Vocoder."""
    make_video(folder, 5.0, "mudo.mp4")
    make_video(folder, 5.0 * speed, "camera.mov", noise(5.0 * speed))
    write_wav(folder / "musica.wav", harmonic_burst(10.0, [burst]))
    return project_for(
        folder,
        [
            {"type": "clip", "src": "mudo.mp4", "start": 0, "end": 5, "mute": True},
            {
                "type": "clip",
                "src": "camera.mov",
                "start": 0,
                "end": 5 * speed,
                "speed": speed,
                "effects": [VOCODER],
            },
        ],
        {"music": {"src": "musica.wav", "volume": MUSIC_VOLUME, "ducking": False}},
    )


def test_the_vocoder_on_a_clip_that_is_not_the_first_aligns_with_the_timeline(tmp_path):
    samples = render_pcm(clip_case(tmp_path), tmp_path, "mix")
    assert energy_onset(samples, 5.0, 9.5) == pytest.approx(7.0, abs=TOLERANCE)


def test_the_vocoder_on_a_clip_at_one_and_a_half_times_keeps_the_carrier_where_it_sounds(tmp_path):
    """O clipe acelera depois do Vocoder; a portadora é esticada de volta para o tempo do clipe, então a rajada aparece onde a
    música a toca (aos 7 s do projeto) e o tom dela se mantém."""
    samples = render_pcm(clip_case(tmp_path, speed=1.5), tmp_path, "mix")
    # o arquivo processado do clipe está no tempo do item (antes da velocidade): a rajada de 7 s do projeto cai em 2 s de clipe,
    # que são 3 s de fonte. É onde o critério dos 10 ms vale; no arquivo final o `atempo` do próprio mezanino borra o ataque
    # mais uns 20 ms, com ou sem Vocoder
    processed = decode(only_processed_file(), RATE, 1)[:, 0]
    assert energy_onset(processed, 2.0, 5.0) == pytest.approx(3.0, abs=TOLERANCE)
    assert energy_onset(samples, 5.0, 9.5) == pytest.approx(7.0, abs=0.03)
    heard = samples[round(7.3 * RATE) : round(8.7 * RATE)].astype(np.float64)
    spectrum = np.abs(np.fft.rfft(heard * np.hanning(len(heard))))
    hz = np.fft.rfftfreq(len(heard), 1 / RATE)
    low = (hz > 150) & (hz < 1500)
    strongest = hz[low][int(np.argmax(spectrum[low]))]
    assert strongest / BURST_HZ == pytest.approx(
        round(strongest / BURST_HZ), abs=0.06
    )  # um harmônico da nota original


def test_the_vocoder_on_an_external_track_used_in_two_clips_aligns_in_both(tmp_path):
    """A faixa externa é processada inteira, no tempo do arquivo, e cada clipe a ouve em outro lugar da linha do tempo."""
    make_video(tmp_path, 10.0)
    write_wav(tmp_path / "gravador.wav", noise(10.0))
    # a linha do tempo é 0 a 4 s e 6 a 10 s da sessão: as rajadas da música caem em 1 a 3 s e em 5 a 7 s do projeto
    write_wav(tmp_path / "musica.wav", harmonic_burst(10.0, [(1.0, 3.0), (5.0, 7.0)]))
    project = project_for(
        tmp_path,
        [
            {"type": "clip", "source": "cam", "start": 0, "end": 4},
            {"type": "clip", "source": "cam", "start": 6, "end": 10},
        ],
        {
            "tracks": [{"source": "gravador", "effects": [VOCODER]}],
            "music": {"src": "musica.wav", "volume": MUSIC_VOLUME, "ducking": False},
        },
        {"cam": {"src": "video.mp4"}, "gravador": {"src": "gravador.wav", "sync": 0.0}},
    )
    samples = render_pcm(project, tmp_path, "mix")
    assert energy_onset(samples, 0.0, 3.9) == pytest.approx(1.0, abs=TOLERANCE)
    assert energy_onset(samples, 4.0, 7.9) == pytest.approx(5.0, abs=TOLERANCE)


def test_the_carrier_can_be_the_camera_of_the_clips(tmp_path):
    make_video(tmp_path, 10.0, "camera.mov", harmonic_burst(10.0, [(4.0, 6.0)]))
    write_wav(tmp_path / "fala.wav", noise(3.0))
    project = project_for(
        tmp_path,
        [{"type": "clip", "src": "camera.mov", "start": 0, "end": 10, "volume": 0.02}],
        {"voiceover": [{"src": "fala.wav", "start": 3.0, "effects": [{**VOCODER, "carrier_track": "A1"}]}]},
    )
    samples = render_pcm(project, tmp_path, "mix")
    assert energy_onset(samples, 3.0, 6.5) == pytest.approx(4.0, abs=TOLERANCE)
