"""A edição de onda com ffmpeg de verdade: tons gerados no teste, cada critério de aceite medido em número.

Os sinais têm amplitude conhecida, então o resultado esperado sai de conta. O arquivo processado é WAV de ponto
flutuante (medida exata); o render e a prévia saem em AAC, onde a tolerância é de décimos de dB.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.domain.audio_effects import parse_effect
from dmaker.domain.spec import Project
from dmaker.media import ffmpeg
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.audio_effects import AudioItem, EffectProcessor
from dmaker.pipeline.edit_history import edit_and_record, undo_edit
from dmaker.pipeline.preview_audio import PreviewAudioBuilder
from dmaker.pipeline.projects import save_project

from .conftest import requires_ffmpeg
from .test_audio_effects_integration import RATE, db, decode, make_tone, no_sync, rms

pytestmark = requires_ffmpeg

FPS = 15


def make_video(path: Path, *, audio: str, seconds: float = 8.0) -> Path:
    """Vídeo cinza com o áudio dado por uma expressão do `aevalsrc` (uma por canal, separadas por `|`)."""
    ffmpeg.run(
        ["-f", "lavfi", "-i", f"color=c=gray:size=320x180:rate={FPS}:d={seconds}"]
        + ["-f", "lavfi", "-i", f"aevalsrc={audio}:s={RATE}:d={seconds}"]
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


def moving_video(path: Path, *, seconds: float = 8.0) -> Path:
    """Vídeo com imagem que muda a cada quadro (o `testsrc`) e um tom, para provar que a imagem não é tocada."""
    ffmpeg.run(
        ["-f", "lavfi", "-i", f"testsrc=size=320x180:rate={FPS}:d={seconds}"]
        + ["-f", "lavfi", "-i", f"aevalsrc=0.3*sin(2*PI*330*t)|0.3*sin(2*PI*330*t):s={RATE}:d={seconds}"]
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


def render_stereo(project: Project, folder: Path, name: str) -> tuple[np.ndarray, object]:
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=folder / f"{name}.mp4", thumbnail=False),
        offset_finder=no_sync,
        cache_dir=folder / f"mez-{name}",
        jobs_dir=folder / f"jobs-{name}",
    ).run()
    return decode(result.output, RATE, 2), result


def frame_at(path: Path, seconds: float) -> np.ndarray:
    """O quadro de um instante do vídeo, em pixels RGB."""
    command = [str(config.find_tool("ffmpeg")), "-v", "error", "-ss", f"{seconds}", "-i", str(path)]
    command += ["-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    return np.frombuffer(subprocess.run(command, capture_output=True, check=True).stdout, dtype=np.uint8)


def spec(folder: Path, video: str = "video.mp4", seconds: float = 8.0, **parts) -> Project:
    data = {
        "name": "edicao-de-onda",
        "output": {"preset": "instagram/reels", "quality": "draft"},
        "timeline": [{"type": "clip", "src": video, "start": 0, "end": seconds}],
        "audio": {"normalize": "off"},
        **parts,
    }
    project = Project.model_validate(data)
    project.base_dir = folder
    return project


def edited(project: Project, folder: Path, *operations: dict) -> Project:
    """O projeto depois das operações, pelo mesmo caminho do MCP e da CLI (que também grava o histórico)."""
    save_project(project, folder)
    for operation in operations:
        edit_and_record(folder / "spec.json", operation)
    return Project.load(folder / "spec.json")


def between(samples: np.ndarray, start: float, end: float, rate: int = RATE) -> np.ndarray:
    """Os segundos de `start` a `end` de um sinal decodificado à taxa dada (48 kHz, a do render)."""
    return samples[int(start * rate) : int(end * rate)]


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    size = min(len(a), len(b))
    a, b = a[:size] - a[:size].mean(), b[:size] - b[:size].mean()
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


@pytest.fixture
def media(tmp_path) -> Path:
    tone = "0.3*sin(2*PI*330*t)"
    make_video(tmp_path / "video.mp4", audio=f"{tone}|{tone}", seconds=16.0)
    moving_video(tmp_path / "imagem.mp4", seconds=8.0)
    # a lapela gravada só no canal esquerdo: o direito é silêncio
    make_video(tmp_path / "lapela.mp4", audio=f"{tone}|0", seconds=8.0)
    # o som só começa em 2 s: dá para medir quanto ele anda
    pulse = f"{tone}*gte(t\\,2)"  # a vírgula escapada: dentro do `-i lavfi` ela separaria filtros
    make_video(tmp_path / "pulso.mp4", audio=f"{pulse}|{pulse}", seconds=8.0)
    # "fala" que não se repete: uma varredura de frequência (a correlação só é alta com o trecho certo)
    ffmpeg.run(
        ["-f", "lavfi", "-i", f"aevalsrc=0.4*sin(2*PI*(200+60*t)*t)|0.4*sin(2*PI*(200+60*t)*t):s={RATE}:d=6"]
        + ["-c:a", "pcm_f32le", str(tmp_path / "fala.wav")],
        quiet=True,
    )
    make_tone(tmp_path / "musica.wav", amp=0.2, hz=220, seconds=16.0)
    return tmp_path


# ---------- silenciar: zera só o intervalo, sem estalo, e a imagem não muda ----------


def test_the_silenced_stretch_is_exactly_zero_and_the_rest_is_untouched_in_the_processed_file(
    media, tmp_path
):
    tone = make_tone(tmp_path / "tom.wav", amp=0.5, hz=440, seconds=4.0)
    processor = EffectProcessor(SubprocessRunner(quiet=True), tmp_path / "fx")
    chain = (parse_effect({"type": "silence", "start": 1.0, "end": 3.0}),)
    done = processor.process(AudioItem(tone, 4.0, chain))
    assert done is not None
    original, silenced = decode(tone), decode(done.path)
    first, last = round(1.0 * RATE), round(3.0 * RATE)
    ramp = round(0.010 * RATE)
    assert np.abs(silenced[first + ramp : last - ramp]).max() == 0.0  # o miolo é zero exato
    assert np.array_equal(silenced[: first - 1], original[: first - 1])  # fora do intervalo, a mesma onda
    assert np.array_equal(silenced[last + 1 :], original[last + 1 :])
    # sem estalo: a maior diferença entre amostras vizinhas não passa da de um tom limpo (0,5 * 2pi * 440 / 48000)
    smooth = 0.5 * 2 * np.pi * 440 / RATE
    for edge in (first, last):
        around = silenced[edge - 2 * ramp : edge + 2 * ramp, 0]
        assert np.abs(np.diff(around)).max() <= smooth * 1.05


def test_silencing_two_seconds_in_the_middle_of_a_clip_zeroes_only_that_stretch_and_the_image_does_not_change(
    media,
):
    plain = spec(media, "imagem.mp4")
    plain.timeline[0].mute = False
    base, base_result = render_stereo(plain, media, "base")
    silenced_project = edited(
        spec(media, "imagem.mp4"),
        media,
        {"type": "audio_silence", "target": "timeline.0", "start": 3, "end": 5},
    )
    silenced_project.timeline[0].mute = False
    out, result = render_stereo(silenced_project, media, "silenciado")

    assert 20 * np.log10(rms(between(out[:, 0], 3.1, 4.9)) + 1e-12) < -70  # 2 s de silêncio de verdade
    assert db(rms(between(out[:, 0], 0.5, 2.8)) / rms(between(base[:, 0], 0.5, 2.8))) == pytest.approx(
        0.0, abs=0.2
    )
    assert db(rms(between(out[:, 0], 5.3, 7.5)) / rms(between(base[:, 0], 5.3, 7.5))) == pytest.approx(
        0.0, abs=0.2
    )
    smooth = 0.3 * 2 * np.pi * 330 / RATE  # a maior diferença entre amostras vizinhas de um tom limpo
    for edge in (3.0, 5.0):
        around = out[round((edge - 0.05) * RATE) : round((edge + 0.05) * RATE), 0]
        assert np.abs(np.diff(around)).max() <= smooth * 1.6  # com a perda do AAC, sem degrau de 0,3
    for instant in (1.0, 3.5, 6.0):  # a imagem é igual antes e depois, quadro a quadro
        assert np.array_equal(frame_at(base_result.output, instant), frame_at(result.output, instant))


# ---------- copiar e colar: o trecho colado soa igual ao original ----------


def test_pasting_three_seconds_of_speech_somewhere_else_sounds_like_the_original(media):
    project = spec(
        media, seconds=16.0, audio={"normalize": "off", "voiceover": [{"src": "fala.wav", "start": 1.0}]}
    )
    project.timeline[0].mute = True
    pasted = edited(
        project,
        media,
        {"type": "audio_paste", "target": "audio.voiceover.0", "start": 2, "end": 5, "at": 9},
    )
    out, _ = render_stereo(pasted, media, "colado")
    original = between(out[:, 0], 2.0, 5.0)
    copy = between(out[:, 0], 9.0, 12.0)
    assert correlation(original, copy) > 0.99
    assert db(rms(copy) / rms(original)) == pytest.approx(0.0, abs=0.2)
    assert (
        rms(between(out[:, 0], 7.3, 8.8)) < 1e-3
    )  # entre a fala (acaba em 7 s) e a cópia (começa em 9 s): silêncio
    wrong = between(out[:, 0], 9.5, 12.5)  # meio segundo fora de lugar não correlaciona
    assert correlation(original, wrong) < 0.9


def test_the_sound_of_a_video_clip_pasted_as_a_voice_sounds_like_the_clip(media):
    project = spec(media, seconds=8.0)
    pasted = edited(
        project,
        media,
        {"type": "audio_paste", "target": "timeline.0", "start": 1, "end": 4, "at": 4},
    )
    pasted.timeline[0].mute = True  # só a colagem soa
    out, _ = render_stereo(pasted, media, "colado-clipe")
    assert rms(between(out[:, 0], 4.2, 6.8)) == pytest.approx(
        0.3 / np.sqrt(2), rel=0.1
    )  # 3 s do clipe, em 4 a 7 s
    assert rms(between(out[:, 0], 0.5, 3.5)) < 1e-3
    assert rms(between(out[:, 0], 7.2, 7.9)) < 1e-3


# ---------- envelope: a rampa no RMS em janelas ----------


def test_an_envelope_from_0_to_minus_12_db_between_10_and_12_seconds_measures_the_ramp_in_windowed_rms(media):
    base, _ = render_stereo(spec(media, seconds=16.0), media, "env-base")
    project = edited(
        spec(media, seconds=16.0),
        media,
        {
            "type": "audio_envelope",
            "target": "timeline.0",
            "points": [{"at": 10, "db": 0}, {"at": 12, "db": -12}],
        },
    )
    out, _ = render_stereo(project, media, "env")
    step = 0.1
    for center, expected in [
        (9.0, 0.0),
        (10.0, 0.0),
        (10.5, -3.0),
        (11.0, -6.0),
        (11.5, -9.0),
        (12.0, -12.0),
        (14.0, -12.0),
    ]:
        low, high = center - step / 2, center + step / 2
        measured = db(rms(between(out[:, 0], low, high)) / rms(between(base[:, 0], low, high)))
        assert measured == pytest.approx(expected, abs=0.6), f"em {center} s"
    steps = [
        db(rms(between(out[:, 0], t, t + step)) / rms(between(base[:, 0], t, t + step)))
        for t in np.arange(10.0, 12.0, step)
    ]
    assert all(a >= b - 0.1 for a, b in zip(steps, steps[1:], strict=False))  # desce sem subir


def test_raising_the_music_at_the_end_is_an_envelope_on_the_music(media):
    project = spec(
        media,
        seconds=16.0,
        audio={
            "normalize": "off",
            "music": {"src": "musica.wav", "volume": 0.5, "ducking": False, "fade_out": 0},
        },
    )
    project.timeline[0].mute = True
    raised = edited(
        project,
        media,
        {
            "type": "audio_envelope",
            "target": "audio.music",
            "points": [{"at": 0, "db": -12}, {"at": 12, "db": -12}, {"at": 14, "db": 0}],
        },
    )
    out, _ = render_stereo(raised, media, "musica-sobe")
    quiet, loud = rms(between(out[:, 0], 5.0, 7.0)), rms(between(out[:, 0], 14.5, 15.5))
    assert db(loud / quiet) == pytest.approx(12.0, abs=0.6)


# ---------- pan, solo, ganho ----------


def test_a_track_panned_all_the_way_left_leaves_the_right_channel_silent(media):
    project = spec(media, tracks={"A1": {"pan": -1}})
    out, _ = render_stereo(project, media, "pan")
    assert 20 * np.log10(rms(between(out[:, 1], 1.0, 7.0)) + 1e-12) < -70
    assert rms(between(out[:, 0], 1.0, 7.0)) == pytest.approx(0.3 / np.sqrt(2), rel=0.1)


def test_track_gain_and_solo_change_the_mix_like_the_audacity_track_header(media):
    both = spec(
        media, audio={"normalize": "off", "music": {"src": "musica.wav", "volume": 0.5, "ducking": False}}
    )
    both.timeline[0].end = 8.0
    plain, _ = render_stereo(both, media, "mix")

    louder = Project.model_validate({**both.model_dump(), "tracks": {"MUS": {"gain_db": 6}}})
    louder.base_dir = media
    soaked, _ = render_stereo(louder, media, "mix-ganho")
    music_only = Project.model_validate(
        {**both.model_dump(), "timeline": [{**both.model_dump()["timeline"][0], "mute": True}]}
    )
    music_only.base_dir = media
    reference, _ = render_stereo(music_only, media, "so-musica")
    assert rms(between(soaked[:, 0], 1, 7)) > rms(between(plain[:, 0], 1, 7))
    assert db(
        rms(between(soaked[:, 0], 1, 7) - between(plain[:, 0], 1, 7)) / rms(between(reference[:, 0], 1, 7))
    ) == pytest.approx(0.0, abs=0.6)  # a diferença é a música sozinha, +6 dB - 0 dB = 1x a música

    soloed = Project.model_validate({**both.model_dump(), "tracks": {"MUS": {"solo": True}}})
    soloed.base_dir = media
    only_music, _ = render_stereo(soloed, media, "solo")
    assert (
        correlation(between(only_music[:, 0], 1, 7), between(reference[:, 0], 1, 7)) > 0.99
    )  # o clipe calou
    assert db(rms(between(only_music[:, 0], 1, 7)) / rms(between(reference[:, 0], 1, 7))) == pytest.approx(
        0.0, abs=0.3
    )


# ---------- canais: a lapela só no esquerdo ----------


def test_a_lapel_recorded_only_on_the_left_channel_with_left_comes_out_on_both_channels(media):
    plain, _ = render_stereo(spec(media, "lapela.mp4"), media, "lapela-pura")
    assert 20 * np.log10(rms(between(plain[:, 1], 1.0, 7.0)) + 1e-12) < -70  # gravada só do lado esquerdo
    fixed = edited(
        spec(media, "lapela.mp4"), media, {"type": "audio_channels", "target": "timeline.0", "mode": "left"}
    )
    out, _ = render_stereo(fixed, media, "lapela-esquerdo")
    left, right = between(out[:, 0], 1.0, 7.0), between(out[:, 1], 1.0, 7.0)
    assert db(rms(right) / rms(left)) == pytest.approx(0.0, abs=0.1)
    assert correlation(left, right) > 0.999
    assert rms(left) == pytest.approx(0.3 / np.sqrt(2), rel=0.1)


# ---------- deslocar no tempo ----------


def test_shifting_the_sound_of_a_clip_moves_the_onset_and_leaves_the_image_alone(media):
    def onset(samples: np.ndarray) -> float:
        energy = np.abs(samples[:, 0]) > 0.05
        return float(np.argmax(energy)) / RATE

    base, base_result = render_stereo(spec(media, "pulso.mp4"), media, "pulso-base")
    assert onset(base) == pytest.approx(2.0, abs=0.06)
    later = edited(
        spec(media, "pulso.mp4"), media, {"type": "audio_shift", "target": "timeline.0", "delta": 0.5}
    )
    out, result = render_stereo(later, media, "pulso-atrasado")
    assert onset(out) == pytest.approx(2.5, abs=0.06)
    earlier = edited(
        spec(media, "pulso.mp4"), media, {"type": "audio_shift", "target": "timeline.0", "delta": -0.5}
    )
    out, _ = render_stereo(earlier, media, "pulso-adiantado")
    assert onset(out) == pytest.approx(1.5, abs=0.06)
    assert np.array_equal(frame_at(base_result.output, 3.0), frame_at(result.output, 3.0))


def test_a_shifted_sound_that_starts_before_the_file_is_silent_there(media):
    project = edited(spec(media), media, {"type": "audio_shift", "target": "timeline.0", "delta": 1.0})
    out, result = render_stereo(project, media, "atraso-no-inicio")
    assert (
        20 * np.log10(rms(between(out[:, 0], 0.1, 0.9)) + 1e-12) < -70
    )  # o primeiro segundo não tem som ainda
    assert rms(between(out[:, 0], 2.0, 6.0)) == pytest.approx(0.3 / np.sqrt(2), rel=0.1)
    assert result.duration == pytest.approx(8.0, abs=0.1)  # o vídeo não ficou mais curto nem mais longo


# ---------- desfazer, de ponta a ponta ----------


def test_undoing_an_audio_edit_gives_back_the_same_sound(media):
    base, _ = render_stereo(spec(media), media, "antes")
    project = edited(
        spec(media),
        media,
        {"type": "audio_silence", "target": "timeline.0", "start": 2, "end": 4},
        {"type": "audio_shift", "target": "timeline.0", "delta": 0.3},
    )
    assert project.timeline[0].audio_offset == 0.3
    undo_edit(media / "spec.json")
    undo_edit(media / "spec.json")
    back = Project.load(media / "spec.json")
    out, _ = render_stereo(back, media, "depois")
    assert np.array_equal(base, out)


# ---------- projeto antigo igual; prévia e render iguais ----------


def test_a_project_with_the_new_fields_at_their_defaults_renders_the_same_mezzanine_and_sound(media):
    plain = spec(media)
    explicit = Project.model_validate(
        {
            **spec(media).model_dump(),
            "timeline": [{**spec(media).model_dump()["timeline"][0], "audio_offset": 0, "pan": 0}],
            "tracks": {"A1": {"gain_db": 0, "pan": 0, "solo": False}},
        }
    )
    explicit.base_dir = media
    one, _ = render_stereo(plain, media, "padrao-a")
    two, _ = render_stereo(explicit, media, "padrao-b")

    def mezzanines(folder: str) -> list[str]:
        return sorted(path.name for path in (media / folder).glob("*.mov"))

    assert mezzanines("mez-padrao-a") == mezzanines("mez-padrao-b") and mezzanines("mez-padrao-a")
    assert np.array_equal(one, two)
    assert b"audio_offset" not in explicit.to_bytes() and b"gain_db" not in explicit.to_bytes()


def test_the_preview_sounds_like_the_render_with_offset_pan_gain_solo_and_edits(media):
    project = edited(
        spec(
            media,
            "pulso.mp4",
            audio={"normalize": "off", "music": {"src": "musica.wav", "volume": 0.4, "ducking": False}},
        ),
        media,
        {"type": "audio_shift", "target": "timeline.0", "delta": 0.4},
        {"type": "audio_silence", "target": "timeline.0", "start": 4, "end": 5},
        {
            "type": "audio_envelope",
            "target": "audio.music",
            "points": [{"at": 1, "db": -6}, {"at": 6, "db": 0}],
        },
        {"type": "track_set", "track": "A1", "gain_db": -3, "pan": 0.5},
        {"type": "track_set", "track": "MUS", "pan": -0.5},
    )
    builder = PreviewAudioBuilder(offset_finder=no_sync, cache_dir=media / "pa", jobs_dir=media / "pj")
    first = builder.build(project)
    rendered, result = render_stereo(project, media, "paridade")
    played = decode(first.path, 16000, 1)[:, 0]
    reference = decode(result.output, 16000, 1)[:, 0]
    assert first.duration == pytest.approx(result.duration, abs=0.05)
    assert correlation(played, reference) > 0.98
    assert abs(db(rms(played[: len(reference)]) / rms(reference[: len(played)]))) < 0.3

    # cada campo novo invalida o cache da prévia
    keys = {first.key}
    for change in (
        {"type": "audio_shift", "target": "timeline.0", "delta": 0.1},
        {"type": "track_set", "track": "A1", "pan": -0.5},
        {"type": "track_set", "track": "A1", "gain_db": 0},
        {"type": "track_set", "track": "MUS", "solo": True},
    ):
        edit_and_record(media / "spec.json", change)
        keys.add(builder.key(Project.load(media / "spec.json")))
    assert len(keys) == 5
