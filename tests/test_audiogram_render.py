"""Audiograma renderizado de verdade com ffmpeg (DMK-34): o que nenhum teste de string enxerga. A onda para no
silêncio e se mexe na fala, o pico do desenho cai no quadro do pico do som, as barras não piscam, o desenho nunca
chega à saída de áudio e a voz de um arquivo de áudio fala por cima de um fundo parado."""

from __future__ import annotations

import re
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from dmaker.domain.spec import Project
from dmaker.filtergraph import audiogram as audiogram_module
from dmaker.media import ffmpeg
from dmaker.media.ffmpeg import SubprocessRunner, ffmpeg_path
from dmaker.media.probe import probe
from dmaker.media.wavio import write_wav
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.report import build_report
from dmaker.text.captions import Cue, Word
from dmaker.text.transcribe import Transcript

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

RATE = 48_000
WIDTH, HEIGHT = 540, 960  # o preview do instagram/reels
STYLES = ("wave", "bars", "circle")

# a caixa de cada estilo no preview, para recortar só o desenho: (esquerda, topo, largura, altura)
BOX = {"wave": (54, 360, 432, 240), "bars": (54, 360, 432, 240), "circle": (108, 318, 324, 324)}
OVERLAY = {
    "wave": {"x": 0.5, "y": 0.5, "width": 0.8, "height": 0.25},
    "bars": {"x": 0.5, "y": 0.5, "width": 0.8, "height": 0.25},
    "circle": {"x": 0.5, "y": 0.5, "width": 0.6},
}


# ---------- sinais de teste ----------


def _syllables(first: float, last: float, rng, out: np.ndarray) -> None:
    """Sílabas de timbre harmônico (110 a 210 Hz) entre `first` e `last`, como a fala sintética do DMK-25."""
    cursor = first
    while cursor < last - 0.15:
        length = min(rng.uniform(0.12, 0.28), last - cursor)
        a, b = int(cursor * RATE), int((cursor + length) * RATE)
        t = np.arange(b - a) / RATE
        pitch = rng.uniform(110, 210)
        voiced = sum(np.sin(2 * np.pi * pitch * k * t) / k for k in range(1, 12))
        out[a:b] += voiced * np.sin(np.pi * t / length) ** 2 * rng.uniform(0.5, 1.0)
        cursor += length + float(rng.choice([0.0, 0.0, 0.05, 0.1]))


SPEECH = ((1.0, 4.0), (6.0, 9.0), (11.0, 13.0))  # onde há fala, em segundos
PAUSES = ((0.15, 0.7), (4.5, 5.5), (9.5, 10.5), (13.4, 13.9))  # janelas de silêncio, longe das bordas da fala
TOTAL = 14.0


def _speech_wav(path: Path, noise_db: float | None = -55.0, seed: int = 3) -> Path:
    """Fala com pausas (e um ruído de fundo de sala, quando `noise_db` é dado) no pico de -6 dBFS."""
    rng = np.random.default_rng(seed)
    signal = np.zeros(int(TOTAL * RATE))
    for first, last in SPEECH:
        _syllables(first, last, rng, signal)
    signal = signal / np.max(np.abs(signal)) * 0.5
    if noise_db is not None:
        noise = rng.standard_normal(len(signal))
        signal = signal + noise * 10 ** (noise_db / 20) / noise.std()
    return write_wav(path, signal, RATE)


def _pulse_wav(path: Path, instants, freq: float = 250.0, total: float = 7.0) -> Path:
    """Silêncio com um pulso de 30 ms de tom em cada instante, para medir o atraso do desenho."""
    signal = np.zeros(int(total * RATE))
    length = int(0.03 * RATE)
    t = np.arange(length) / RATE
    for at in instants:
        start = int(at * RATE) - length // 2
        signal[start : start + length] = 0.8 * np.hanning(length) * np.sin(2 * np.pi * freq * t)
    return write_wav(path, signal, RATE)


def _tone_wav(path: Path, freq: float, seconds: float, amplitude: float = 0.5) -> Path:
    t = np.arange(int(seconds * RATE)) / RATE
    return write_wav(path, amplitude * np.sin(2 * np.pi * freq * t), RATE)


# ---------- render e medição ----------


def _project(tmp: Path, name: str, voice: Path, style: str, *, fps: float = 30.0, **extra) -> Project:
    """Cartão preto com o audiograma e `voice` como voiceover; `audio=` e `overlay=` ajustam o que há de áudio e de
    desenho, e o resto vira campo da spec."""
    overlay = {
        "type": "audiogram",
        "style": style,
        "color": "#FFFFFF",
        **OVERLAY[style],
        **extra.pop("overlay", {}),
    }
    spec = {
        "name": name,
        "output": {"preset": "instagram/reels", "fps": fps, "quality": "draft"},
        "timeline": [
            {
                "type": "card",
                "flat": True,
                "background": "#000000",
                "logo": False,
                "motion": "none",
                "duration": TOTAL,
            }
        ],
        "overlays": [overlay],
        "audio": {"voiceover": [{"src": str(voice)}], "normalize": "two-pass", **extra.pop("audio", {})},
        **extra,
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp
    return project


def _render(project: Project, out: Path, **options) -> Path:
    RenderPipeline(
        project, RenderOptions(preview=True, quiet=True, out=out, thumbnail=False, **options)
    ).run()
    return out


def _region_frames(video: Path, style: str) -> np.ndarray:
    """Os quadros da caixa do desenho, em cinza (n, altura, largura)."""
    left, top, width, height = BOX[style]
    command = [
        str(ffmpeg_path()),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-vf",
        f"crop={width}:{height}:{left}:{top},format=gray",
        "-f",
        "rawvideo",
        "-",
    ]
    data = subprocess.run(command, capture_output=True, check=True).stdout
    return np.frombuffer(data, dtype=np.uint8).reshape(-1, height, width).astype(np.int16)


def _motion(frames: np.ndarray, windows, fps: float) -> float:
    """Mudança média de um quadro para o outro (0 a 255) dentro das janelas de tempo: é o que se vê mexer."""
    steps = [
        np.abs(np.diff(frames[int(a * fps) : int(b * fps)], axis=0)).mean(axis=(1, 2)) for a, b in windows
    ]
    return float(np.concatenate(steps).mean())


def _ink(frames: np.ndarray, windows, fps: float) -> float:
    """Quanto do desenho está aceso (pixels claros por quadro) dentro das janelas de tempo."""
    return float(
        np.mean([(frames[int(a * fps) : int(b * fps)] > 127).sum(axis=(1, 2)).mean() for a, b in windows])
    )


# ---------- parada no silêncio, em movimento na fala ----------


@pytest.mark.parametrize("style", STYLES)
def test_the_drawing_stands_still_in_the_silence_and_moves_with_the_speech(style, tmp_path):
    """Critério do chamado, com um ruído de sala de -55 dBFS nas pausas: a mudança de um quadro para o outro na
    região do desenho é desprezível no silêncio e grande na fala."""
    audio = _speech_wav(tmp_path / "fala.wav")
    video = _render(_project(tmp_path, f"parada_{style}", audio, style), tmp_path / f"{style}.mp4")
    frames = _region_frames(video, style)
    assert len(frames) == pytest.approx(TOTAL * 30, abs=2)
    in_speech = _motion(frames, [(1.4, 3.6), (6.4, 8.6), (11.4, 12.6)], 30)
    in_silence = _motion(frames, PAUSES, 30)
    assert in_speech > 0.05, "a fala não mexeu o desenho"
    assert in_silence < 0.03 * in_speech, f"{in_silence:.4f} no silêncio contra {in_speech:.4f} na fala"


@pytest.mark.parametrize("style", ["bars", "circle"])
def test_the_bars_rest_as_a_thin_line_in_the_silence_and_grow_with_the_speech(style, tmp_path):
    audio = _speech_wav(tmp_path / "fala.wav")
    frames = _region_frames(
        _render(_project(tmp_path, f"altura_{style}", audio, style), tmp_path / f"{style}.mp4"), style
    )
    resting = _ink(frames, PAUSES, 30)
    speaking = _ink(frames, [(1.4, 3.6), (6.4, 8.6), (11.4, 12.6)], 30)
    assert 0 < resting and speaking > 2.5 * resting


# ---------- sem atraso ----------


@pytest.mark.parametrize("fps", [24.0, 30.0])
@pytest.mark.parametrize("style", STYLES)
def test_a_pulse_in_the_audio_peaks_the_drawing_in_the_same_frame(style, fps, tmp_path):
    """Critério do chamado: um pulso de áudio num instante conhecido produz o pico do desenho no mesmo quadro (a
    tolerância é de 1 quadro; o centro de massa do desenho erra menos de meio)."""
    instants = (1.0, 2.5167, 4.05, 5.4833)
    audio = _pulse_wav(tmp_path / "pulsos.wav", instants)
    project = _project(tmp_path, f"pulso_{style}", audio, style, fps=fps)
    project.timeline[0] = project.timeline[0].model_copy(update={"duration": 7.0})
    frames = _region_frames(_render(project, tmp_path / "pulsos.mp4"), style)
    ink = (np.abs(frames - frames[0]) > 40).sum(axis=(1, 2)).astype(float)
    for at in instants:
        expected = at * fps
        lo, hi = int(expected) - 8, int(expected) + 10
        window = ink[lo:hi]
        peak = lo + int(np.argmax(window))
        weights = window - window.min()
        centroid = lo + float((np.arange(len(window)) * weights).sum() / weights.sum())
        assert abs(peak - expected) <= 1, (
            f"{style} {fps:g} fps, pulso em {at}s: pico no quadro {peak}, devia ser {expected:.1f}"
        )
        assert abs(centroid - expected) < 0.5, (
            f"{style} {fps:g} fps, pulso em {at}s: centro no quadro {centroid:.2f}"
        )


# ---------- sem tremor ----------

# Variação média de um quadro para o outro (0 a 255) das barras na fala. Com a média de 160 ms fica por volta de
# 4,7; sem ela passa de 7 (o teste confere os dois lados, para o limite significar alguma coisa).
FLICKER_LIMIT = 5.5


def _bars_flicker(tmp_path: Path, name: str) -> float:
    audio = _speech_wav(tmp_path / "fala.wav")
    video = _render(_project(tmp_path, name, audio, "bars"), tmp_path / f"{name}.mp4")
    return _motion(_region_frames(video, "bars"), [(1.4, 3.6), (6.4, 8.6), (11.4, 12.6)], 30)


def test_the_bars_do_not_flicker_and_without_the_time_average_they_would(tmp_path, monkeypatch):
    smoothed = _bars_flicker(tmp_path, "suave")
    monkeypatch.setattr(audiogram_module, "SMOOTHING_SECONDS", 0)
    raw = _bars_flicker(tmp_path, "cru")
    assert smoothed < FLICKER_LIMIT < raw, (
        f"com média {smoothed:.3f}, sem média {raw:.3f}, limite {FLICKER_LIMIT}"
    )


# ---------- o desenho segue o áudio que se ouve ----------


def test_following_the_voice_keeps_the_drawing_still_in_the_pauses_under_a_music_bed_and_following_the_mix_does_not(
    tmp_path,
):
    """Com trilha de fundo, a onda que segue a mistura se mexe no silêncio da fala: `voice` é o que a deixa parada."""
    audio = _speech_wav(tmp_path / "fala.wav", noise_db=None)
    music = _tone_wav(tmp_path / "trilha.wav", 440.0, TOTAL + 1)
    bed = {"music": {"src": str(music), "volume": 0.5, "ducking": False}}
    rest = {}
    for follow in ("voice", "mix"):
        project = _project(tmp_path, f"seguir_{follow}", audio, "bars", audio=bed, overlay={"follow": follow})
        frames = _region_frames(_render(project, tmp_path / f"{follow}.mp4"), "bars")
        rest[follow] = _ink(frames, PAUSES, 30)
    assert rest["mix"] > 2.0 * rest["voice"], (
        rest
    )  # a música enche as barras nas pausas só quando se segue a mistura


# ---------- o desenho nunca chega à saída de áudio ----------


def _decoded_audio(video: Path, tmp: Path) -> np.ndarray:
    wav = tmp / f"{video.stem}.decoded.wav"
    ffmpeg.run(
        ["-i", str(video), "-vn", "-ar", str(RATE), "-ac", "2", "-c:a", "pcm_s16le", str(wav)], quiet=True
    )
    with wave.open(str(wav)) as handle:
        return np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)


def test_the_audiogram_does_not_change_a_single_sample_of_the_output_audio(tmp_path):
    audio = _speech_wav(tmp_path / "fala.wav")
    music = _tone_wav(tmp_path / "trilha.wav", 330.0, TOTAL + 1, 0.3)
    bed = {"music": {"src": str(music), "volume": 0.2}}
    with_drawing = _render(_project(tmp_path, "com", audio, "circle", audio=bed), tmp_path / "com.mp4")
    plain = _project(tmp_path, "sem", audio, "circle", audio=bed)
    plain.overlays = []
    without = _render(plain, tmp_path / "sem.mp4")
    a, b = _decoded_audio(with_drawing, tmp_path), _decoded_audio(without, tmp_path)
    assert len(a) == len(b)
    # o último meio segundo fica de fora: com ou sem audiograma, as amostras dos últimos ~0,2 s variam de uma execução
    # para a outra (a cauda do loudnorm e do ducking no fim do arquivo), o que não tem a ver com o desenho
    body = int((TOTAL - 0.5) * RATE) * 2
    assert np.array_equal(a[:body], b[:body])


# ---------- a voz de um arquivo de áudio ----------


def _rms_db(samples: np.ndarray) -> float:
    return 20 * np.log10(max(float(np.sqrt(np.mean(samples.astype(float) ** 2))), 1e-9))


def test_the_voiceover_is_the_voice_of_a_video_made_of_a_still_background_and_ducks_the_music(tmp_path):
    audio = _speech_wav(tmp_path / "fala.wav", noise_db=None)
    music = _tone_wav(tmp_path / "trilha.wav", 3000.0, TOTAL + 1, 0.6)  # acima das harmônicas da voz
    bed = {"music": {"src": str(music), "volume": 0.5, "ducking": True, "fade_in": 0, "fade_out": 0}}
    out = _render(_project(tmp_path, "voz", audio, "wave", audio=bed), tmp_path / "voz.mp4")
    info = probe(out)
    assert info.has_audio and abs(info.duration - TOTAL) < 0.3
    mono = _decoded_audio(out, tmp_path).reshape(-1, 2).mean(axis=1)

    def tone_level(first: float, last: float) -> float:
        """Nível do tom de 3 kHz da música numa janela (a voz não tem energia ali)."""
        window = mono[int(first * RATE) : int(last * RATE)]
        spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window)))) / len(window)
        bin_ = int(round(3000 * len(window) / RATE))
        return float(spectrum[bin_ - 2 : bin_ + 3].max())

    def voice_level(first: float, last: float) -> float:
        """Energia na faixa da voz (100 a 400 Hz), onde a música não tem nada."""
        window = mono[int(first * RATE) : int(last * RATE)]
        power = np.abs(np.fft.rfft(window * np.hanning(len(window)))) ** 2
        freqs = np.fft.rfftfreq(len(window), 1 / RATE)
        return float(power[(freqs >= 100) & (freqs <= 400)].sum())

    speaking, pausing = tone_level(2.0, 3.5), tone_level(9.6, 10.4)
    assert 20 * np.log10(pausing / speaking) > 3.0, "a música não abaixou sob a voz"
    # a fala do arquivo é audível por cima do fundo parado e some nas pausas dela
    assert 10 * np.log10(voice_level(2.0, 3.5) / voice_level(9.6, 10.4)) > 30


def test_the_voiceover_is_placed_and_trimmed_on_the_timeline(tmp_path):
    """`start` põe o áudio no instante do vídeo, `offset` e `end` aparam o arquivo."""
    audio = _speech_wav(tmp_path / "fala.wav", noise_db=None)
    project = _project(tmp_path, "aparado", audio, "wave", audio={"normalize": "off"})
    project.audio.voiceover[0] = project.audio.voiceover[0].model_copy(
        update={
            "start": 3.0,
            "offset": 1.0,
            "end": 4.0,
        }  # toca 3 s da fala (1 a 4 s do arquivo), a partir de 3 s
    )
    mono = _decoded_audio(_render(project, tmp_path / "aparado.mp4"), tmp_path).reshape(-1, 2).mean(axis=1)
    assert _rms_db(mono[int(2.0 * RATE) : int(2.8 * RATE)]) < -70  # antes de `start`: silêncio
    assert _rms_db(mono[int(3.3 * RATE) : int(5.7 * RATE)]) > -35  # a fala do arquivo (1,3 a 3,7 s dele)
    assert _rms_db(mono[int(6.4 * RATE) : int(10 * RATE)]) < -70  # depois de `end`: silêncio de novo


def test_the_automatic_captions_transcribe_the_voiceover_at_the_instant_it_plays(tmp_path):
    """Num projeto só de imagem de fundo e voiceover, o áudio entregue ao transcritor tem a fala no instante certo."""
    audio = _speech_wav(tmp_path / "fala.wav", noise_db=None)
    heard = {}

    class Listener:
        def transcribe(self, wav: Path, language: str, initial_prompt: str | None = None) -> Transcript:
            with wave.open(str(wav)) as handle:
                heard["rate"] = handle.getframerate()
                heard["samples"] = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
            return Transcript([Cue(0.5, 2.0, "fala", [Word(0.5, 2.0, "fala")])], {"language": language})

    project = _project(tmp_path, "legenda", audio, "wave", captions={"source": "auto", "language": "pt"})
    project.audio.voiceover[0] = project.audio.voiceover[0].model_copy(update={"start": 2.0})
    RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=tmp_path / "legenda.mp4", thumbnail=False),
        transcriber_factory=lambda captions: Listener(),
    ).run()
    rate, samples = heard["rate"], heard["samples"]
    assert rate == 16_000
    before = _rms_db(samples[int(0.2 * rate) : int(1.8 * rate)])  # antes de `start`: o fundo é mudo
    first_speech = _rms_db(samples[int(3.2 * rate) : int(5.8 * rate)])  # a primeira fala (1 a 4 s) +2 s
    pause = _rms_db(samples[int(6.6 * rate) : int(7.4 * rate)])  # a pausa de 4 a 6 s do arquivo, +2 s
    assert before < -80 and first_speech > before + 40 and pause < first_speech - 30


# ---------- foto em círculo ----------


def test_an_image_overlay_with_the_circle_shape_cuts_the_largest_central_square_into_a_circle(tmp_path):
    photo = tmp_path / "foto.png"
    image = Image.new("RGB", (900, 600), "#FF0000")  # largura maior que a altura: o recorte pega o meio
    image.paste((0, 0, 255), (0, 0, 150, 600))  # as faixas das pontas não entram no quadrado central
    image.paste((0, 0, 255), (750, 0, 900, 600))
    image.save(photo)
    project = Project.model_validate(
        {
            "name": "circulo",
            "output": {"preset": "instagram/reels", "fps": 15, "quality": "draft"},
            "timeline": [
                {
                    "type": "card",
                    "flat": True,
                    "background": "#000000",
                    "logo": False,
                    "motion": "none",
                    "duration": 1.5,
                }
            ],
            "overlays": [
                {
                    "type": "image",
                    "src": str(photo),
                    "x": 0.5,
                    "y": 0.5,
                    "width": 0.5,
                    "shape": "circle",
                    "fade": 0,
                }
            ],
        }
    )
    project.base_dir = tmp_path
    out = _render(project, tmp_path / "circulo.mp4")
    frame_path = tmp_path / "quadro.png"
    ffmpeg.run(["-ss", "1.0", "-i", str(out), "-frames:v", "1", str(frame_path)], quiet=True)
    pixels = np.asarray(Image.open(frame_path).convert("RGB")).astype(int)
    side = int(WIDTH * 0.5)
    left, top = (WIDTH - side) // 2, (HEIGHT - side) // 2
    red = np.array([255, 0, 0])
    assert np.abs(pixels[HEIGHT // 2, WIDTH // 2] - red).max() < 40  # o centro é a foto
    for x, y in (
        (left + 4, top + 4),
        (left + side - 5, top + 4),
        (left + 4, top + side - 5),
        (left + side - 5, top + side - 5),
    ):
        assert pixels[y, x].max() < 40, "o canto do quadrado devia estar fora do círculo"
    for x, y in (
        (left + side // 2, top + 6),
        (left + side // 2, top + side - 7),
        (left + 6, top + side // 2),
        (left + side - 7, top + side // 2),
    ):
        assert np.abs(pixels[y, x] - red).max() < 60, "o meio de cada lado devia estar dentro do círculo"
    assert not (pixels[:, :, 2] > 200).any()  # nada do azul das pontas da foto entrou no recorte


# ---------- o modelo, de ponta a ponta ----------


@pytest.mark.parametrize("style", STYLES)
def test_the_audiogram_template_turns_an_audio_into_a_vertical_video_with_captions_and_a_clean_qa(
    style, tmp_path
):
    from dmaker.domain.templates import find_template, render_template
    from dmaker.pipeline.projects import with_media_durations

    audio = _speech_wav(tmp_path / "episodio.wav")
    cover = tmp_path / "capa.png"
    Image.new("RGB", (900, 700), "#2B4C7E").save(cover)
    template = find_template("audiograma")
    params = with_media_durations(
        template, {"audio": str(audio), "capa": str(cover), "titulo": "Podcast Saude em Dia", "estilo": style}
    )
    assert params["duracao"] == pytest.approx(TOTAL, abs=0.05)  # o DMaker mediu o arquivo sozinho
    project = Project.model_validate({**render_template(template, params), "name": f"modelo_{style}"})
    project.base_dir = tmp_path
    project.output.quality = "draft"  # a resolução continua a do modelo (1080x1920): o QA a confere

    class Fake:
        def transcribe(self, wav: Path, language: str, initial_prompt: str | None = None) -> Transcript:
            words = [Word(1.0, 1.5, "bem-vindos"), Word(1.5, 2.0, "ao"), Word(2.0, 2.8, "podcast")]
            return Transcript([Cue(1.0, 2.8, "bem-vindos ao podcast", words)], {"language": language})

    out = tmp_path / f"modelo_{style}.mp4"
    result = RenderPipeline(
        project,
        RenderOptions(quiet=True, out=out, thumbnail=False),
        transcriber_factory=lambda captions: Fake(),
    ).run()
    info = probe(out)
    assert (info.width, info.height) == (1080, 1920) and info.has_audio
    assert abs(info.duration - TOTAL) < 0.3 and result.warnings == []
    ass = (result.job_dir / "overlay.ass").read_text(encoding="utf-8-sig")
    assert re.search(r"bem-vindos", ass, re.IGNORECASE) and "Podcast Saude em Dia" in ass
    report = build_report(project, output=out, runner=SubprocessRunner(quiet=True))
    errors = [f for f in report.findings if f.level == "erro"]
    assert not errors, [f.message for f in errors]
