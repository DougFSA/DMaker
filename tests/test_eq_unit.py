"""Equalização e filtros sem ffmpeg: o projeto dos filtros IIR, a curva dos equalizadores por pontos, a resposta de
frequência, os construtores, as predefinições embutidas e as do usuário. O que precisa do ffmpeg de verdade (os cinco
critérios de aceite medidos no som) está em `test_eq_integration.py`."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from typer.testing import CliRunner

from dmaker import config
from dmaker.analysis import eq_curve, iir
from dmaker.cli import app as cli
from dmaker.domain.audio_effects import (
    EFFECT_CLASSES,
    EFFECT_PRESETS,
    catalog_payload,
    get_effect_preset,
    list_user_presets,
    parse_effect,
    remove_user_preset,
    save_user_preset,
)
from dmaker.domain.audio_effects.eq import GRAPHIC_BANDS_HZ, MAX_CURVE_POINTS
from dmaker.domain.edits import EditError
from dmaker.domain.effect_edits import apply_effect_op
from dmaker.domain.spec import Project
from dmaker.filtergraph.audio_effects import (
    EffectRequest,
    build_effect,
    builder_types,
    frequency_response,
    response_types,
)
from dmaker.filtergraph.audio_effects.eq import curve_of
from dmaker.pipeline.effect_response import effect_frequency_response

RATE = 48000
runner = CliRunner()

EQ_TYPES = [
    "bass_treble",
    "low_shelf",
    "high_shelf",
    "highpass",
    "lowpass",
    "notch",
    "classic_filter",
    "graphic_eq",
    "filter_curve_eq",
]


def gain_at(sections, hz: float) -> float:
    return float(iir.response_db(sections, np.array([hz]), RATE)[0])


def request(effect: dict, duration: float = 3.0) -> EffectRequest:
    return EffectRequest(parse_effect(effect), "[in]", "[out]", "fx0", duration)


# ---------- o projeto dos filtros IIR ----------


@pytest.mark.parametrize("family", ["butterworth", "chebyshev1", "chebyshev2"])
@pytest.mark.parametrize("band", ["lowpass", "highpass"])
@pytest.mark.parametrize("order", [1, 2, 3, 4, 7, 10])
def test_classic_filters_match_the_reference_design_to_numeric_precision(family, band, order):
    """Os coeficientes projetados aqui dão a mesma resposta que o `scipy.signal` (só o oráculo: o núcleo não o importa)."""
    signal = pytest.importorskip("scipy.signal")
    sections = iir.classic_sections(family, band, order, 1500.0, RATE, 1.5, 35.0)
    assert len(sections) == (order + 1) // 2
    probe = np.geomspace(20, 20000, 400)
    kind = "low" if band == "lowpass" else "high"
    reference = {
        "butterworth": lambda: signal.butter(order, 1500.0, kind, fs=RATE, output="sos"),
        "chebyshev1": lambda: signal.cheby1(order, 1.5, 1500.0, kind, fs=RATE, output="sos"),
        "chebyshev2": lambda: signal.cheby2(order, 35.0, 1500.0, kind, fs=RATE, output="sos"),
    }[family]()
    _, h = signal.sosfreqz(reference, worN=probe, fs=RATE)
    expected = 20 * np.log10(np.maximum(np.abs(h), 1e-15))
    mine = iir.response_db(sections, probe, RATE)
    loud = expected > -120  # abaixo disso os dois são só o chão numérico
    assert np.max(np.abs(mine[loud] - expected[loud])) < 1e-6


def test_butterworth_is_minus_3_db_at_the_cutoff_and_flat_in_the_passband():
    low = iir.classic_sections("butterworth", "lowpass", 4, 1000.0, RATE)
    assert gain_at(low, 1000.0) == pytest.approx(-3.0103, abs=1e-3)
    assert gain_at(low, 20.0) == pytest.approx(0.0, abs=1e-3)
    assert gain_at(low, 2000.0) == pytest.approx(-24.1, abs=0.3)  # 24 dB por oitava na ordem 4
    high = iir.classic_sections("butterworth", "highpass", 4, 1000.0, RATE)
    assert gain_at(high, 1000.0) == pytest.approx(-3.0103, abs=1e-3)
    assert gain_at(high, 500.0) == pytest.approx(-24.1, abs=0.3)


def test_chebyshev_one_ripples_inside_the_band_and_two_rejects_beyond_the_edge():
    one = iir.classic_sections("chebyshev1", "lowpass", 5, 2000.0, RATE, ripple_db=2.0)
    inside = iir.response_db(one, np.geomspace(20, 1990, 600), RATE)
    assert inside.max() <= 0.01 and inside.min() >= -2.0 - 0.01  # a ondulação não passa do pedido
    assert inside.min() == pytest.approx(-2.0, abs=0.05)
    assert gain_at(one, 2000.0) == pytest.approx(-2.0, abs=0.05)  # o corte é onde a ondulação termina
    two = iir.classic_sections("chebyshev2", "lowpass", 5, 2000.0, RATE, stopband_db=40.0)
    beyond = iir.response_db(two, np.geomspace(2010, 20000, 600), RATE)
    assert beyond.max() <= -40.0 + 0.05  # a rejeição pedida vale a partir do corte
    assert gain_at(two, 100.0) == pytest.approx(0.0, abs=0.01)


def test_the_slope_picks_the_butterworth_order_from_6_to_48_db_per_octave():
    for slope in (6, 12, 18, 24, 30, 36, 42, 48):
        sections = iir.slope_sections("highpass", slope, 1000.0, RATE)
        assert len(sections) == slope // 12 + slope // 6 % 2
        # uma oitava abaixo do corte o filtro já está perto da inclinação nominal
        assert gain_at(sections, 250.0) < -slope * 2 * 0.8


def test_the_80_hz_24_db_highpass_drops_40_hz_by_24_db_and_leaves_1_khz_alone():
    sections = iir.slope_sections("highpass", 24, 80.0, RATE)
    assert gain_at(sections, 40.0) == pytest.approx(-24.1, abs=0.1)
    assert abs(gain_at(sections, 1000.0)) < 1e-6


def test_the_notch_is_a_zero_at_its_frequency_and_flat_far_from_it():
    sections = [iir.notch(60.0, 10.0, RATE)]
    assert gain_at(sections, 60.0) < -120
    assert abs(gain_at(sections, 400.0)) < 0.01
    assert gain_at([iir.notch(60.0, 1.0, RATE)], 60.0) < -120
    narrow = gain_at([iir.notch(1000.0, 30.0, RATE)], 1100.0)
    wide = gain_at([iir.notch(1000.0, 1.0, RATE)], 1100.0)
    assert wide < narrow  # Q maior, corte mais estreito


def test_the_shelves_reach_their_gain_far_from_the_corner_and_the_slope_opens_the_transition():
    low = [iir.low_shelf(200.0, 9.0, 1.0, RATE)]
    assert gain_at(low, 20.0) == pytest.approx(9.0, abs=0.05)
    assert gain_at(low, 8000.0) == pytest.approx(0.0, abs=0.05)
    assert gain_at(low, 200.0) == pytest.approx(4.5, abs=0.05)  # metade do ganho no meio da transição
    high = [iir.high_shelf(4000.0, -6.0, 1.0, RATE)]
    assert gain_at(high, 20000.0) == pytest.approx(-6.0, abs=0.1)
    assert gain_at(high, 100.0) == pytest.approx(0.0, abs=0.05)
    gentle = [iir.high_shelf(4000.0, -6.0, 0.3, RATE)]
    assert abs(gain_at(gentle, 2000.0)) > abs(gain_at(high, 2000.0))


def test_a_frequency_at_or_above_nyquist_is_refused():
    with pytest.raises(ValueError, match="frequência fora do possível"):
        iir.notch(24000.0, 1.0, RATE)
    with pytest.raises(ValueError, match="ordem"):
        iir.classic_sections("butterworth", "lowpass", 0, 1000.0, RATE)


def test_the_ffmpeg_biquad_line_carries_all_the_coefficients_at_full_precision():
    section = iir.Biquad(0.5, -0.25, 0.125, -1.5, 0.75)
    line = section.ffmpeg_filter()
    assert line.startswith("biquad=b0=0.5:b1=-0.25:b2=0.125:a0=1:a1=-1.5:a2=0.75")
    assert "precision=f64" in line and "transform=tdii" in line


# ---------- a curva dos equalizadores por pontos ----------


@pytest.mark.parametrize("method", ["linear", "cosine", "cubic"])
@pytest.mark.parametrize("scale", ["log", "linear"])
def test_the_curve_passes_through_every_point_and_holds_the_ends(method, scale):
    hz = [50.0, 200.0, 1000.0, 5000.0]
    db = [-6.0, 4.0, -3.0, 8.0]
    assert eq_curve.interpolate_db(hz, db, np.array(hz), scale, method) == pytest.approx(db, abs=1e-9)
    outside = eq_curve.interpolate_db(hz, db, np.array([10.0, 20000.0]), scale, method)
    assert outside == pytest.approx([-6.0, 8.0])


def test_the_cubic_curve_never_overshoots_the_neighbouring_points():
    hz = list(GRAPHIC_BANDS_HZ)
    db = [0.0] * 31
    db[22] = 6.0
    dense = eq_curve.interpolate_db(hz, db, np.geomspace(20, 20000, 4000), "log", "cubic")
    assert dense.max() <= 6.0 + 1e-9 and dense.min() >= -1e-9  # um pico isolado não faz a vizinha cair


def test_linear_and_log_axes_draw_different_curves_between_the_same_points():
    hz, db = [100.0, 10000.0], [0.0, 10.0]
    middle = np.array([1000.0])
    log = eq_curve.interpolate_db(hz, db, middle, "log", "linear")[0]
    linear = eq_curve.interpolate_db(hz, db, middle, "linear", "linear")[0]
    assert log == pytest.approx(5.0) and linear == pytest.approx(10.0 * 900 / 9900)


def test_the_curve_written_for_ffmpeg_respects_the_hundred_entry_limit_and_keeps_every_point():
    """O `firequalizer` recusa montar o filtro com mais de 100 entradas (medido: 100 passa, 101 não)."""
    rng = np.random.default_rng(7)
    hz = np.sort(rng.uniform(20, 20000, MAX_CURVE_POINTS))
    db = rng.uniform(-20, 20, MAX_CURVE_POINTS)
    sampled, gains = eq_curve.curve_for_filter(list(hz), list(db), "log", "cubic")
    assert len(sampled) <= eq_curve.MAX_ENTRIES
    assert set(np.round(hz, 6)) <= set(sampled)
    entry = eq_curve.gain_entry(sampled, gains)
    assert entry.count("entry(") == len(sampled) and entry.startswith("entry(10,")
    assert np.all(np.diff(sampled) > 0)
    two = eq_curve.curve_for_filter([20.0, 20000.0], [0.0, 0.0], "log", "linear")[0]
    assert len(two) <= eq_curve.MAX_ENTRIES


def test_a_steep_stretch_gets_more_extra_samples_than_a_flat_one():
    hz = eq_curve.sample_frequencies([100.0, 1000.0, 10000.0], [0.0, 0.0, 12.0])
    flat = np.sum((hz > 100) & (hz < 1000))
    steep = np.sum((hz > 1000) & (hz < 10000))
    assert steep > flat


def test_display_frequencies_cover_20_hz_to_20_khz_in_octaves():
    hz = eq_curve.display_frequencies(256)
    assert hz[0] == pytest.approx(20.0) and hz[-1] == pytest.approx(20000.0)
    ratios = hz[1:] / hz[:-1]
    assert ratios.max() / ratios.min() == pytest.approx(1.0, abs=1e-9)


# ---------- as classes, o catálogo e a resposta ----------


def test_every_eq_effect_has_a_builder_and_a_frequency_response_and_nothing_else_does():
    with_response = {name for name, cls in EFFECT_CLASSES.items() if cls.has_response}
    assert with_response == set(EQ_TYPES)
    assert response_types() == with_response
    assert with_response <= builder_types()


def test_the_catalog_describes_the_new_parameter_kinds_and_the_response_flag():
    payload = catalog_payload()
    by_type = {info["type"]: info for info in payload["effects"]}
    assert all(by_type[name]["has_response"] for name in EQ_TYPES)
    assert not by_type["amplify"]["has_response"]
    graphic = {p["name"]: p for p in by_type["graphic_eq"]["parameters"]}["gains_db"]
    assert graphic["kind"] == "band_gains" and graphic["default"] == [0.0] * 31
    assert (graphic["minimum"], graphic["maximum"], graphic["unit"]) == (-20.0, 20.0, "dB")
    assert (
        len(graphic["options"]) == 31 and graphic["options"][0] == "20" and graphic["options"][22] == "3.15k"
    )
    assert graphic["options"][-1] == "20k"
    curve = {p["name"]: p for p in by_type["filter_curve_eq"]["parameters"]}
    assert curve["points"]["kind"] == "freq_points"
    assert curve["points"]["default"] == [{"hz": 20.0, "db": 0.0}, {"hz": 20000.0, "db": 0.0}]
    assert curve["scale"]["options"] == ["log", "linear"]
    assert curve["interpolation"]["options"] == ["cubic", "cosine", "linear"]
    assert (curve["length"]["minimum"], curve["length"]["maximum"], curve["length"]["default"]) == (
        21,
        8191,
        8191,
    )
    slope = {p["name"]: p for p in by_type["highpass"]["parameters"]}["slope_db"]
    assert slope["kind"] == "choice" and slope["options"] == ["6", "12", "18", "24", "30", "36", "42", "48"]
    assert slope["default"] == 6
    assert {p["name"] for p in by_type["classic_filter"]["parameters"]} == {
        "family",
        "mode",
        "order",
        "frequency_hz",
        "ripple_db",
        "stopband_db",
    }


def test_the_spec_accepts_the_choice_as_text_or_number_and_refuses_what_is_out_of_range():
    assert parse_effect({"type": "highpass", "slope_db": "24"}).slope_db == 24
    assert parse_effect({"type": "highpass", "slope_db": 24}).slope_db == 24
    for bad in (
        {"type": "highpass", "slope_db": 25},
        {"type": "notch", "q": 0},
        {"type": "bass_treble", "bass_db": 31},
        {"type": "graphic_eq", "gains_db": [0.0] * 30},
        {"type": "graphic_eq", "gains_db": [21.0] + [0.0] * 30},
        {"type": "filter_curve_eq", "points": []},
        {"type": "filter_curve_eq", "points": [{"hz": 10, "db": 0}]},
        {"type": "classic_filter", "order": 11},
    ):
        with pytest.raises(ValidationError):
            parse_effect(bad)


def test_the_curve_points_are_sorted_and_two_points_on_one_frequency_are_refused():
    effect = parse_effect(
        {
            "type": "filter_curve_eq",
            "points": [{"hz": 1000, "db": 3}, {"hz": 100, "db": -3}, {"hz": 5000, "db": 0}],
        }
    )
    assert [point.hz for point in effect.points] == [100, 1000, 5000]
    with pytest.raises(ValidationError, match="mesma frequência"):
        parse_effect({"type": "filter_curve_eq", "points": [{"hz": 100, "db": 1}, {"hz": 100, "db": 2}]})


def flat_or_known(effect: dict) -> dict:
    return effect_frequency_response(effect, 64)


@pytest.mark.parametrize(
    ("effect", "hz", "db"),
    [
        ({"type": "highpass", "frequency_hz": 80, "slope_db": 24}, 40.0, -24.1),
        ({"type": "lowpass", "frequency_hz": 1000, "slope_db": 12}, 2000.0, -12.3),
        ({"type": "notch", "frequency_hz": 1000, "q": 5}, 1000.0, None),
        ({"type": "low_shelf", "frequency_hz": 200, "gain_db": 6}, 20.0, 6.0),
        ({"type": "high_shelf", "frequency_hz": 4000, "gain_db": -6}, 20000.0, -6.0),
        ({"type": "bass_treble", "bass_db": 6, "volume_db": 3}, 20.0, 9.0),
        (
            {
                "type": "classic_filter",
                "family": "butterworth",
                "mode": "lowpass",
                "order": 2,
                "frequency_hz": 1000,
            },
            1000.0,
            -3.01,
        ),
    ],
)
def test_the_response_has_the_gain_the_filter_is_designed_for(effect, hz, db):
    spec = parse_effect(effect)
    value = float(frequency_response(spec, np.array([hz]))[0])
    if db is None:
        assert value < -100
    else:
        assert value == pytest.approx(db, abs=0.15)


def test_a_flat_equalizer_has_a_flat_response_and_the_service_returns_plain_lists():
    for effect in ({"type": "bass_treble"}, {"type": "graphic_eq"}, {"type": "filter_curve_eq"}):
        response = effect_frequency_response(effect, 64)
        assert len(response["hz"]) == len(response["db"]) == 64
        assert response["hz"][0] == 20.0 and response["hz"][-1] == 20000.0
        assert max(abs(v) for v in response["db"]) < 1e-9
        json.dumps(response)  # só números do Python, prontos para a rota


def test_the_response_service_refuses_what_has_no_response_or_does_not_parse():
    with pytest.raises(ValueError, match="não tem resposta de frequência"):
        effect_frequency_response({"type": "amplify", "gain_db": 3})
    with pytest.raises(ValueError, match="slope_db"):
        effect_frequency_response({"type": "highpass", "slope_db": 7})
    with pytest.raises(ValueError, match="desconhecido"):
        effect_frequency_response({"type": "eco"})
    with pytest.raises(ValueError, match="pontos do gráfico"):
        effect_frequency_response({"type": "notch"}, 2)


def test_the_graphic_eq_by_bands_holds_each_gain_across_the_third_octave_and_the_smooth_modes_do_not():
    gains = [0.0] * 31
    gains[22] = 6.0
    bands = curve_of(parse_effect({"type": "graphic_eq", "gains_db": gains}))
    at = lambda hz: float(bands.at(np.array([hz]))[0])  # noqa: E731
    assert at(3150.0) == pytest.approx(6.0)
    assert at(3150.0 * 2 ** (1 / 10)) == pytest.approx(6.0)  # dentro do patamar
    assert at(math.sqrt(3150.0 * 4000.0)) == pytest.approx(
        3.0, abs=0.05
    )  # a meio caminho entre o patamar de 3,15 k e o de 4 k
    assert at(4000.0) == pytest.approx(0.0)
    smooth = curve_of(parse_effect({"type": "graphic_eq", "gains_db": gains, "interpolation": "cubic"}))
    assert float(smooth.at(np.array([3150.0 * 2 ** (1 / 10)]))[0]) < 6.0 - 0.3


def test_the_graphic_eq_third_octave_band_averages_plus_6_db_in_every_mode_of_the_bands_design():
    gains = [0.0] * 31
    gains[22] = 6.0
    curve = curve_of(parse_effect({"type": "graphic_eq", "gains_db": gains}))
    inside = np.geomspace(3150 * 2 ** (-1 / 6), 3150 * 2 ** (1 / 6), 500)
    power = np.mean(10 ** (curve.at(inside) / 10))
    assert 10 * math.log10(power) == pytest.approx(6.0, abs=1.0)


# ---------- os construtores ----------


def test_the_biquad_builder_chains_one_filter_per_section_and_the_volume_after():
    line = build_effect(request({"type": "highpass", "frequency_hz": 80, "slope_db": 24}))
    assert line[0].count("biquad=") == 2 and line[0].startswith("[in]") and line[0].endswith("[out]")
    one = build_effect(request({"type": "bass_treble", "bass_db": 6, "treble_db": -3, "volume_db": 2}))[0]
    assert one.count("biquad=") == 2 and one.endswith("volume=2.000000dB[out]")
    flat = build_effect(request({"type": "bass_treble"}))
    assert flat == ["[in]anull[out]"]


def test_the_curve_builder_writes_the_firequalizer_and_trims_the_filter_delay_off_both_ends():
    effect = {
        "type": "filter_curve_eq",
        "points": [{"hz": 100, "db": 6}, {"hz": 1000, "db": -6}],
        "length": 1025,
    }
    line = build_effect(request(effect, duration=2.0))[0]
    assert "firequalizer=gain_entry='entry(10,6)" in line
    assert "atrim=start_sample=512:end_sample=96512" in line  # metade do filtro, e 2 s de amostras a 48 kHz
    assert "delay=0.010671875" in line  # (512 + 0,25 de folga) / 48000
    assert line.endswith("asetpts=PTS-STARTPTS[out]")
    assert build_effect(request({"type": "filter_curve_eq"})) == ["[in]anull[out]"]
    assert build_effect(request({"type": "graphic_eq"})) == ["[in]anull[out]"]


# ---------- predefinições ----------


def test_the_builtin_eq_presets_are_registered_and_every_effect_in_them_is_valid():
    ids = [
        "bass_boost",
        "bass_cut",
        "treble_boost",
        "treble_cut",
        "telephone",
        "am_radio",
        "rumble_100hz",
        "hum_60hz",
        "hum_50hz",
    ]
    assert set(ids) <= set(EFFECT_PRESETS)
    for preset in EFFECT_PRESETS.values():
        for effect in preset.effects:
            parse_effect(effect)  # nenhuma predefinição embutida sai quebrada
    assert [e["frequency_hz"] for e in get_effect_preset("hum_60hz").effects] == [60, 120, 180, 240, 300]
    assert [e["frequency_hz"] for e in get_effect_preset("hum_50hz").effects] == [50, 100, 150, 200, 250]
    assert {e["type"] for e in get_effect_preset("hum_60hz").effects} == {"notch"}
    assert (
        get_effect_preset("rumble_100hz").effects[0]["type"] == "highpass"
    )  # o nome que a receita do DMK-66 usa
    assert all(preset["origin"] == "builtin" for preset in catalog_payload()["presets"])


def test_an_eq_preset_goes_onto_an_item_one_effect_per_entry():
    done = apply_effect_op(
        Project.model_validate(
            {"name": "p", "timeline": [{"type": "clip", "src": "v.mp4", "start": 0, "end": 5}]}
        ),
        {"action": "preset", "target": "timeline.0", "preset": "hum_60hz"},
    )
    chain = done.timeline[0].effects
    assert [effect.type for effect in chain] == ["notch"] * 5


# ---------- predefinições do usuário ----------


def chain_of(*items: dict) -> list[dict]:
    return list(items)


def test_a_saved_preset_shows_in_the_catalog_with_origin_user_and_survives_a_restart():
    saved = save_user_preset(
        "Minha voz de celular",
        chain_of(
            {"type": "highpass", "frequency_hz": 90, "slope_db": 24},
            {"type": "notch", "frequency_hz": 60, "q": 20},
        ),
        "Limpa o grave e o zumbido",
    )
    assert saved.id == "minha-voz-de-celular" and saved.origin == "user"
    assert config.EFFECT_PRESETS_FILE.parent == config.DATA_DIR  # o arquivo mora na pasta de dados
    on_disk = json.loads(config.EFFECT_PRESETS_FILE.read_text(encoding="utf-8"))
    assert on_disk["presets"]["minha-voz-de-celular"]["label"] == "Minha voz de celular"
    # "reiniciar": nada fica em memória, o catálogo lê o arquivo de novo
    mine = [p for p in catalog_payload()["presets"] if p["origin"] == "user"]
    assert [p["id"] for p in mine] == ["minha-voz-de-celular"]
    assert [e["type"] for e in mine[0]["effects"]] == ["highpass", "notch"]
    assert get_effect_preset("minha-voz-de-celular").label == "Minha voz de celular"


def test_a_saved_preset_goes_onto_an_item_like_a_builtin_one():
    save_user_preset("Corte de ronco", [{"type": "highpass", "frequency_hz": 70, "slope_db": 36}])
    done = apply_effect_op(
        Project.model_validate(
            {"name": "p", "timeline": [{"type": "clip", "src": "v.mp4", "start": 0, "end": 5}]}
        ),
        {"action": "preset", "target": "timeline.0", "preset": "corte-de-ronco"},
    )
    assert done.timeline[0].effects[0].slope_db == 36


def test_saving_keeps_the_settings_but_drops_the_interval_and_the_bypass_that_belong_to_the_item():
    saved = save_user_preset(
        "Sem lugar",
        [
            {
                "type": "low_shelf",
                "frequency_hz": 150,
                "gain_db": 4,
                "start": 1.0,
                "end": 3.0,
                "enabled": False,
            }
        ],
    )
    effect = saved.effects[0]
    assert "start" not in effect and "end" not in effect and "enabled" not in effect
    assert effect["gain_db"] == 4 and effect["type"] == "low_shelf"
    assert effect["slope"] == 1.0  # explícito: mudar um padrão no futuro não muda a predefinição de ninguém


def test_saving_again_with_the_same_name_replaces_and_removing_deletes():
    save_user_preset("Ajuste", [{"type": "notch", "frequency_hz": 50}])
    replaced = save_user_preset("  ajuste ", [{"type": "notch", "frequency_hz": 60}])
    presets = list_user_presets()
    assert [p.id for p in presets] == ["ajuste"] and presets[0].effects[0]["frequency_hz"] == 60
    assert replaced.effects[0]["frequency_hz"] == 60
    assert remove_user_preset("ajuste").label == "ajuste"
    assert list_user_presets() == []


def test_saving_refuses_empty_names_builtin_names_bad_effects_and_removal_of_unknown_or_builtin_ones():
    good = [{"type": "notch"}]
    with pytest.raises(ValueError, match="dê um nome"):
        save_user_preset("   ", good)
    with pytest.raises(ValueError, match="embutida"):
        save_user_preset("Telephone", good)
    with pytest.raises(ValueError, match="1 a 20 efeitos"):
        save_user_preset("Vazia", [])
    with pytest.raises(ValueError, match="efeito inválido"):
        save_user_preset("Ruim", [{"type": "highpass", "slope_db": 7}])
    with pytest.raises(ValueError, match="desconhecido"):
        save_user_preset("Ruim", [{"type": "eco"}])
    with pytest.raises(ValueError, match="longo demais"):
        save_user_preset("n" * 61, good)
    with pytest.raises(ValueError, match="embutida"):
        remove_user_preset("telephone")
    with pytest.raises(ValueError, match="desconhecida"):
        remove_user_preset("nao-existe")
    assert not config.EFFECT_PRESETS_FILE.exists()  # nada recusado chegou ao disco


def test_a_broken_presets_file_hides_the_user_presets_but_is_never_overwritten():
    config.EFFECT_PRESETS_FILE.write_text("{ isto não é json", encoding="utf-8")
    assert [p["id"] for p in catalog_payload()["presets"] if p["origin"] == "user"] == []
    with pytest.raises(ValueError, match="não consegui ler"):
        save_user_preset("Nova", [{"type": "notch"}])
    assert config.EFFECT_PRESETS_FILE.read_text(encoding="utf-8") == "{ isto não é json"


def test_an_unknown_preset_id_lists_the_builtin_and_the_saved_ones():
    save_user_preset("Minha", [{"type": "notch"}])
    with pytest.raises(ValueError, match="minha"):
        get_effect_preset("nada")
    with pytest.raises(EditError, match="Predefinição desconhecida"):
        apply_effect_op(
            Project.model_validate(
                {"name": "p", "timeline": [{"type": "clip", "src": "v.mp4", "start": 0, "end": 5}]}
            ),
            {"action": "preset", "target": "timeline.0", "preset": "nada"},
        )


# ---------- os três adaptadores ----------


def test_the_routes_serve_the_response_and_keep_the_user_presets_across_server_instances():
    from dmaker.ui.server import app

    client = TestClient(app)
    reply = client.post(
        "/api/audio-effects/response",
        json={"effect": {"type": "highpass", "frequency_hz": 80, "slope_db": 24}, "points": 128},
    )
    assert reply.status_code == 200
    body = reply.json()
    assert len(body["hz"]) == len(body["db"]) == 128 and body["db"][0] < -20 and abs(body["db"][-1]) < 0.01
    assert client.post("/api/audio-effects/response", json={"effect": {"type": "amplify"}}).status_code == 422
    assert (
        client.post(
            "/api/audio-effects/response", json={"effect": {"type": "highpass", "slope_db": 5}}
        ).status_code
        == 422
    )

    assert client.get("/api/audio-effects/presets").json() == {"presets": []}
    saved = client.post(
        "/api/audio-effects/presets",
        json={"label": "Meu corte", "effects": [{"type": "highpass", "frequency_hz": 85, "slope_db": 24}]},
    )
    assert saved.status_code == 200 and saved.json()["origin"] == "user"
    # um servidor "novo" (outro cliente, nada em memória) enxerga a predefinição salva, no catálogo e na lista
    again = TestClient(app)
    listed = again.get("/api/audio-effects/presets").json()["presets"]
    assert [p["id"] for p in listed] == ["meu-corte"]
    assert any(
        p["id"] == "meu-corte" and p["origin"] == "user"
        for p in again.get("/api/audio-effects").json()["presets"]
    )
    assert (
        client.post(
            "/api/audio-effects/presets", json={"label": "Telephone", "effects": [{"type": "notch"}]}
        ).status_code
        == 422
    )
    assert again.delete("/api/audio-effects/presets/telephone").status_code == 404
    assert again.delete("/api/audio-effects/presets/meu-corte").status_code == 200
    assert again.get("/api/audio-effects/presets").json() == {"presets": []}
    assert again.delete("/api/audio-effects/presets/meu-corte").status_code == 404


def test_the_mcp_tools_answer_like_the_routes():
    from mcp.server.mcpserver.exceptions import ToolError

    from dmaker import mcp_server

    response = mcp_server.audio_effect_response({"type": "notch", "frequency_hz": 60, "q": 10}, 32)
    assert len(response["hz"]) == 32
    with pytest.raises(ToolError, match="não tem resposta"):
        mcp_server.audio_effect_response({"type": "reverse"})
    assert mcp_server.audio_effect_presets("list") == {"presets": []}
    saved = mcp_server.audio_effect_presets(
        "save", label="Pelo MCP", effects=[{"type": "notch"}], summary="oi"
    )
    assert saved["id"] == "pelo-mcp" and saved["summary"] == "oi"
    assert [p["id"] for p in mcp_server.audio_effect_presets("list")["presets"]] == ["pelo-mcp"]
    with pytest.raises(ToolError, match="informe"):
        mcp_server.audio_effect_presets("save", label="Sem efeitos")
    with pytest.raises(ToolError, match="informe"):
        mcp_server.audio_effect_presets("remove")
    with pytest.raises(ToolError, match="ação desconhecida"):
        mcp_server.audio_effect_presets("apagar")
    assert mcp_server.audio_effect_presets("remove", id="pelo-mcp")["label"] == "Pelo MCP"


def test_the_cli_saves_lists_and_removes_presets_and_prints_a_response():
    saved = runner.invoke(
        cli,
        [
            "audio",
            "preset",
            "save",
            "Pela CLI",
            "-e",
            '{"type": "highpass", "frequency_hz": 90, "slope_db": 24}',
        ],
    )
    assert saved.exit_code == 0, saved.output
    assert "pela-cli" in saved.output
    listed = runner.invoke(cli, ["audio", "preset", "list", "--json"])
    assert [p["id"] for p in json.loads(listed.output)["presets"]] == ["pela-cli"]
    assert "pela-cli" in runner.invoke(cli, ["audio", "preset", "list"]).output
    assert (
        runner.invoke(cli, ["audio", "preset", "save", "Telephone", "-e", '{"type": "notch"}']).exit_code == 1
    )
    assert runner.invoke(cli, ["audio", "preset", "save", "Quebrada", "-e", "{nao-json"]).exit_code == 1
    assert runner.invoke(cli, ["audio", "preset", "remove", "pela-cli"]).exit_code == 0
    assert "Nenhuma predefinição salva" in runner.invoke(cli, ["audio", "preset", "list"]).output
    assert runner.invoke(cli, ["audio", "preset", "remove", "pela-cli"]).exit_code == 1

    plot = runner.invoke(
        cli,
        ["audio", "effect", "response", "highpass", "-p", "frequency_hz=80", "-p", "slope_db=24", "--json"],
    )
    assert plot.exit_code == 0, plot.output
    assert len(json.loads(plot.output)["hz"]) == 256
    table = runner.invoke(cli, ["audio", "effect", "response", "notch"])
    assert table.exit_code == 0 and "Resposta de notch" in table.output
    assert runner.invoke(cli, ["audio", "effect", "response", "amplify"]).exit_code == 1


def test_the_preset_file_is_written_atomically_without_a_leftover_temp_file():
    save_user_preset("Atômica", [{"type": "notch"}])
    assert sorted(path.name for path in config.DATA_DIR.glob("effect-presets*")) == ["effect-presets.json"]
