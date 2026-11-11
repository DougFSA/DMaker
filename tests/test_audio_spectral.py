"""Os efeitos espectrais (Apagar Espectral, Multiferramenta, EQ Paramétrico e Prateleiras): a máscara em numpy, as regras de
faixa da spec, os filtros e, com ffmpeg de verdade, o que cada um faz medido por FFT num tom de 3 kHz dentro de uma fala
sintética. O mesmo pedido feito pela edição (com um marcador espectral) dá o mesmo arquivo processado que a spec escrita à mão."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker.domain.audio_effects import EFFECT_CLASSES, parse_effect
from dmaker.domain.edits import EditError
from dmaker.domain.spec import Project
from dmaker.filtergraph.audio_effects import EffectRequest, build_effect
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.media.probe import MediaInfo
from dmaker.media.spectral import delete_rectangle
from dmaker.media.wavio import read_wav_float, write_wav_channels
from dmaker.pipeline.audio_effects import AudioItem, EffectProcessor
from dmaker.pipeline.edits import apply_edit

from .conftest import requires_ffmpeg

RATE = 48000
FAMILY = ("spectral_delete", "spectral_multi_tool", "spectral_eq", "spectral_shelves")


def speech(seconds: float = 4.0) -> np.ndarray:
    """Uma fala sintética (tons de 180 Hz a 4,4 kHz com sílabas a 3 Hz e um pouco de chiado), sem nada perto de 3 kHz."""
    rng = np.random.default_rng(5)
    t = np.arange(int(seconds * RATE)) / RATE
    tones = sum(
        0.06 * np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) for f in (180, 420, 900, 1500, 2300, 3700, 4400)
    )
    return ((tones * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))) + 0.004 * rng.standard_normal(len(t))).astype(
        np.float32
    )


def with_tone(base: np.ndarray, start: float = 1.5, end: float = 2.0, hz: float = 3000.0) -> np.ndarray:
    t = np.arange(len(base)) / RATE
    hit = (t >= start) & (t < end)
    result = base.copy()
    result[hit] += 0.25 * np.sin(2 * np.pi * hz * t[hit]).astype(np.float32)
    return result


def band_db(samples: np.ndarray, start: float, end: float, low: float, high: float) -> float:
    """A energia, em dB, entre `low` e `high` Hz no trecho (primeiro canal, janela de Hann)."""
    segment = np.asarray(samples[int(start * RATE) : int(end * RATE)], dtype=np.float64)
    if segment.ndim > 1:
        segment = segment[:, 0]
    power = np.abs(np.fft.rfft(segment * np.hanning(len(segment)))) ** 2
    frequency = np.fft.rfftfreq(len(segment), 1 / RATE)
    return 10 * np.log10(power[(frequency >= low) & (frequency < high)].sum() + 1e-20)


# ---------- a máscara em numpy ----------


def test_deleting_the_rectangle_drops_the_tone_by_more_than_30_db_and_leaves_the_rest_alone():
    original = with_tone(speech())
    deleted = delete_rectangle(original[:, None], RATE, int(1.4 * RATE), int(2.1 * RATE), 2800.0, 3200.0)[
        :, 0
    ]
    assert band_db(original, 1.5, 2.0, 2800, 3200) - band_db(deleted, 1.5, 2.0, 2800, 3200) > 30
    # a fala em volta, fora do retângulo, muda menos de 1 dB em cada faixa
    for low, high in ((100, 2000), (3800, 6000), (6000, 12000)):
        assert abs(band_db(deleted, 1.45, 2.05, low, high) - band_db(original, 1.45, 2.05, low, high)) < 1.0
    # o tempo fora do retângulo fica igual, amostra por amostra
    assert np.array_equal(deleted[: int(0.9 * RATE)], original[: int(0.9 * RATE)])
    assert np.array_equal(deleted[int(2.6 * RATE) :], original[int(2.6 * RATE) :])


def test_the_mask_edges_are_soft_so_no_musical_noise_is_left_just_outside_the_band():
    original = with_tone(speech())
    deleted = delete_rectangle(original[:, None], RATE, int(1.4 * RATE), int(2.1 * RATE), 2800.0, 3200.0)[
        :, 0
    ]
    # bem rente à borda (de 100 a 400 Hz fora): a energia é a do original, a menos de meio dB, dos dois lados
    for low, high in ((2400, 2700), (3300, 3600)):
        assert abs(band_db(deleted, 1.45, 2.05, low, high) - band_db(original, 1.45, 2.05, low, high)) < 0.5
    # e fora do retângulo no tempo, com a mesma faixa apagada, nada do que existe ali some
    assert abs(band_db(deleted, 2.3, 3.0, 2800, 3200) - band_db(original, 2.3, 3.0, 2800, 3200)) < 0.1


def test_deleting_works_on_stereo_and_keeps_shape_dtype_and_an_empty_rectangle_untouched():
    stereo = np.stack([with_tone(speech(2.0), 0.5, 1.0), speech(2.0)], axis=1)
    out = delete_rectangle(stereo, RATE, int(0.4 * RATE), int(1.1 * RATE), 2800.0, 3200.0)
    assert out.shape == stereo.shape and out.dtype == np.float32
    assert band_db(out[:, 0], 0.5, 1.0, 2800, 3200) < band_db(stereo[:, 0], 0.5, 1.0, 2800, 3200) - 30
    assert abs(band_db(out[:, 1], 0.5, 1.0, 100, 2000) - band_db(stereo[:, 1], 0.5, 1.0, 100, 2000)) < 1.0
    untouched = delete_rectangle(stereo, RATE, 1000, 1000, 2800.0, 3200.0)
    assert np.array_equal(untouched, stereo)


# ---------- a spec ----------


def test_the_family_is_registered_with_the_audacity_names():
    for name in FAMILY:
        assert name in EFFECT_CLASSES and EFFECT_CLASSES[name].needs_selection
    assert EFFECT_CLASSES["spectral_delete"].audacity_name == "Spectral Delete"
    assert EFFECT_CLASSES["spectral_delete"].sample_stage and not EFFECT_CLASSES["spectral_eq"].sample_stage


def test_the_band_rules_name_what_is_missing_or_backwards():
    with pytest.raises(ValueError, match="low_hz"):
        parse_effect({"type": "spectral_multi_tool"})
    with pytest.raises(ValueError, match="as duas bordas"):
        parse_effect({"type": "spectral_eq", "low_hz": 1000})
    with pytest.raises(ValueError, match="maior que low_hz"):
        parse_effect({"type": "spectral_delete", "start": 1, "end": 2, "low_hz": 3000, "high_hz": 2000})
    with pytest.raises(ValueError, match="start. e .end"):
        parse_effect({"type": "spectral_delete", "low_hz": 100, "high_hz": 200})
    assert parse_effect({"type": "spectral_multi_tool", "high_hz": 4000}).edges() == (0.0, 4000.0)


def test_rebasing_a_deletion_keeps_both_ends_written():
    effect = parse_effect(
        {"type": "spectral_delete", "start": 1.0, "end": 3.0, "low_hz": 100, "high_hz": 200}
    )
    moved = effect.rebased(1.0, 5.0)
    assert (moved.start, moved.end) == (0.0, 2.0)
    again = parse_effect(moved.model_dump())  # a spec revalida: sem intervalo aberto
    assert again.start == 0.0
    assert effect.rebased(5.0, 2.0) is None


# ---------- os filtros ----------


def graph(effect: dict) -> str:
    lines = build_effect(EffectRequest(parse_effect(effect), "[in]", "[out]", "fx0", 4.0))
    return ";".join(lines)


def test_the_multi_tool_picks_the_filter_from_the_edges_given():
    band = graph({"type": "spectral_multi_tool", "low_hz": 2800, "high_hz": 3200})
    assert band.count("bandreject=f=2993.3") == 2 and ":w=400" in band
    assert graph({"type": "spectral_multi_tool", "low_hz": 500}).count("highpass=f=500") == 2
    assert graph({"type": "spectral_multi_tool", "high_hz": 4000}).count("lowpass=f=4000") == 2


def test_the_shelves_follow_the_audacity_rule_for_one_or_two_edges():
    only_low = graph({"type": "spectral_shelves", "low_hz": 5000, "gain_db": -12})
    assert "highshelf=f=5000" in only_low and "g=-12" in only_low
    only_high = graph({"type": "spectral_shelves", "high_hz": 300, "gain_db": -12})
    assert "lowshelf=f=300" in only_high
    both = graph({"type": "spectral_shelves", "low_hz": 1000, "high_hz": 4000, "gain_db": 6})
    assert "highshelf=f=1000.000000:g=6" in both and "highshelf=f=4000.000000:g=-6" in both


def test_the_equalizer_uses_the_geometric_center_and_the_width_in_hz():
    text = graph({"type": "spectral_eq", "low_hz": 1000, "high_hz": 4000, "gain_db": 9})
    assert "equalizer=f=2000.000000:t=h:w=3000.000000:g=9" in text


# ---------- ffmpeg de verdade ----------


@pytest.fixture
def source(tmp_path) -> Path:
    path = tmp_path / "fala.wav"
    mono = with_tone(speech())
    write_wav_channels(path, np.stack([mono, mono], axis=1), RATE)
    return path


def process(tmp_path: Path, source: Path, *chain: dict) -> tuple[np.ndarray, Path]:
    processor = EffectProcessor(SubprocessRunner(quiet=True), tmp_path / "fx")
    done = processor.process(AudioItem(source, 4.0, tuple(parse_effect(item) for item in chain)))
    assert done is not None
    samples, _ = read_wav_float(done.path)
    return samples[:, 0], done.path


@requires_ffmpeg
def test_spectral_delete_through_the_chain_removes_the_tone_and_keeps_the_voice(tmp_path, source):
    original = read_wav_float(source)[0][:, 0]
    effect = {"type": "spectral_delete", "start": 1.4, "end": 2.1, "low_hz": 2800, "high_hz": 3200}
    result, _ = process(tmp_path, source, effect)
    drop = band_db(original, 1.5, 2.0, 2800, 3200) - band_db(result, 1.5, 2.0, 2800, 3200)
    around = abs(band_db(result, 1.45, 2.05, 100, 2000) - band_db(original, 1.45, 2.05, 100, 2000))
    assert drop > 30 and around < 1.0


@requires_ffmpeg
def test_the_multi_tool_rejects_the_band_with_a_ten_millisecond_seam(tmp_path, source):
    original = read_wav_float(source)[0][:, 0]
    effect = {"type": "spectral_multi_tool", "start": 1.4, "end": 2.1, "low_hz": 2800, "high_hz": 3200}
    result, _ = process(tmp_path, source, effect)
    # o filtro de dois polos derruba o miolo da faixa (onde está o tom) e deixa o resto do espectro como estava
    assert band_db(original, 1.5, 2.0, 2950, 3050) - band_db(result, 1.5, 2.0, 2950, 3050) > 30
    assert abs(band_db(result, 1.5, 2.0, 100, 2000) - band_db(original, 1.5, 2.0, 100, 2000)) < 0.5
    assert np.array_equal(result[: int(1.3 * RATE)], original[: int(1.3 * RATE)]) or (
        np.abs(result[: int(1.3 * RATE)] - original[: int(1.3 * RATE)]).max() < 1e-6
    )


@requires_ffmpeg
def test_the_equalizer_and_the_shelves_change_the_band_by_about_the_gain_asked(tmp_path, source):
    original = read_wav_float(source)[0][:, 0]
    equalized, _ = process(
        tmp_path,
        source,
        {"type": "spectral_eq", "start": 1.4, "end": 2.1, "low_hz": 2000, "high_hz": 4500, "gain_db": -15},
    )
    change = band_db(equalized, 1.5, 2.0, 2900, 3100) - band_db(original, 1.5, 2.0, 2900, 3100)
    assert -17 < change < -12
    shelved, _ = process(tmp_path, source, {"type": "spectral_shelves", "low_hz": 6000, "gain_db": -20})
    high = band_db(shelved, 0.2, 1.2, 9000, 12000) - band_db(original, 0.2, 1.2, 9000, 12000)
    low = band_db(shelved, 0.2, 1.2, 100, 1000) - band_db(original, 0.2, 1.2, 100, 1000)
    assert high < -15 and abs(low) < 0.5


# ---------- a mesma operação pela spec e pela edição ----------


def prober(path: Path) -> MediaInfo:
    return MediaInfo(path, 4.0 if path.suffix == ".wav" else 8.0, 0, 0, 0.0, False, True, False)


def make_project(folder: Path, effects=None, markers=None) -> Project:
    voice: dict = {"src": "fala.wav", "start": 1.0}
    if effects:
        voice["effects"] = effects
    project = Project.model_validate(
        {
            "name": "espectral",
            "timeline": [{"type": "card", "title": "x", "duration": 8.0}],
            "audio": {"voiceover": [voice], "normalize": "off"},
            "markers": markers or [],
        }
    )
    project.base_dir = folder
    return project


def test_the_region_of_a_spectral_marker_fills_the_interval_and_the_band_of_the_effect(source):
    folder = source.parent
    marker = {"start": 2.5, "end": 3.1, "text": "plim", "low_hz": 2800, "high_hz": 3200}
    project = make_project(folder, markers=[marker])
    edited = apply_edit(
        project,
        {
            "type": "audio_effect",
            "action": "add",
            "target": "audio.voiceover.0",
            "region": "marker:plim",
            "effect": {"type": "spectral_delete"},
        },
        prober=prober,
    )
    effect = edited.audio.voiceover[0].effects[0]
    # a voz começa em 1 s do vídeo: 2,5 s do vídeo são 1,5 s da fala
    assert (effect.start, effect.end, effect.low_hz, effect.high_hz) == (1.5, 2.1, 2800.0, 3200.0)
    explicit = apply_edit(
        project,
        {
            "type": "audio_effect",
            "action": "add",
            "target": "audio.voiceover.0",
            "region": "marker:plim",
            "effect": {"type": "spectral_delete", "low_hz": 2900, "high_hz": 3100},
        },
        prober=prober,
    )
    assert (
        explicit.audio.voiceover[0].effects[0].low_hz == 2900.0
    )  # o que o pedido diz vale mais que o marcador


def test_a_region_that_is_an_instant_or_used_without_add_is_refused(source):
    project = make_project(source.parent, markers=[{"at": 2.0, "text": "ponto"}])
    op = {
        "type": "audio_effect",
        "action": "add",
        "target": "audio.voiceover.0",
        "effect": {"type": "spectral_delete"},
    }
    with pytest.raises(EditError, match="instante"):
        apply_edit(project, {**op, "region": "marker:ponto"}, prober=prober)
    with pytest.raises(EditError, match="action=add"):
        apply_edit(project, {**op, "action": "remove", "index": 0, "region": "marker:ponto"}, prober=prober)


@requires_ffmpeg
def test_the_edit_and_the_hand_written_spec_give_the_same_processed_file(tmp_path, source):
    marker = {"start": 2.4, "end": 3.1, "text": "plim", "low_hz": 2800, "high_hz": 3200}
    by_edit = apply_edit(
        make_project(source.parent, markers=[marker]),
        {
            "type": "audio_effect",
            "action": "add",
            "target": "audio.voiceover.0",
            "region": "marker:plim",
            "effect": {"type": "spectral_delete"},
        },
        prober=prober,
    )
    by_hand = make_project(
        source.parent,
        effects=[{"type": "spectral_delete", "start": 1.4, "end": 2.1, "low_hz": 2800, "high_hz": 3200}],
    )
    results = []
    for index, project in enumerate((by_edit, by_hand)):
        processor = EffectProcessor(SubprocessRunner(quiet=True), tmp_path / f"fx{index}")
        item = project.audio.voiceover[0]
        done = processor.process(AudioItem(source, 4.0, tuple(item.effects)))
        assert done is not None
        results.append((processor.key(AudioItem(source, 4.0, tuple(item.effects))), done.path.read_bytes()))
    assert results[0][0] == results[1][0]  # a mesma chave de cache
    assert results[0][1] == results[1][1]  # e o mesmo arquivo, byte a byte


@requires_ffmpeg
def test_the_cli_adds_a_spectral_effect_from_a_marker_region(source):
    import json

    from typer.testing import CliRunner

    from dmaker.cli import app

    project = make_project(
        source.parent, markers=[{"start": 2.4, "end": 3.1, "text": "plim", "low_hz": 2800, "high_hz": 3200}]
    )
    spec = project.save(source.parent / "spec.json")
    result = CliRunner().invoke(
        app,
        [
            "audio",
            "effect",
            "add",
            str(spec),
            "audio.voiceover.0",
            "spectral_delete",
            "--region",
            "marker:plim",
        ],
    )
    assert result.exit_code == 0, result.output
    effect = json.loads(spec.read_text(encoding="utf-8"))["audio"]["voiceover"][0]["effects"][0]
    assert (effect["type"], effect["start"], effect["end"]) == ("spectral_delete", 1.4, 2.1)
    assert (effect["low_hz"], effect["high_hz"]) == (2800.0, 3200.0)
