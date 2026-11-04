"""Atraso, Eco e Reverb sem ffmpeg: as contas puras, os grafos (texto), a resposta ao impulso e as predefinições.

O que depende do ffmpeg de verdade (o eco de um clique a 300 ms, o RT60 depois do `afir`) está em
`test_audio_creative_effects_integration.py`.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from pydantic import ValidationError

from dmaker import config
from dmaker.domain.audio_effects import (
    EFFECT_CLASSES,
    EFFECT_PRESETS,
    catalog,
    check_preset_fits,
    parse_effect,
)
from dmaker.domain.audio_effects.creative_presets import REVERB_RT60_RANGES
from dmaker.domain.audio_effects.delay_reverb import Delay, Echo, Reverb
from dmaker.domain.echo import (
    BOUNCE_RATIO,
    ECHO_FLOOR_DB,
    MAX_ECHO_TAIL_SECONDS,
    delay_echoes,
    doubling_blocks,
    doubling_stages,
    echo_repeats,
    echo_tail_seconds,
)
from dmaker.domain.reverb import MAX_T60, ReverbSettings, reverb_time
from dmaker.domain.spec import Project
from dmaker.filtergraph.audio_effects import EffectRequest, build_effect
from dmaker.filtergraph.audio_effects.delay_reverb import echo_stage_count
from dmaker.media.reverb import RATE, ensure_impulse, impulse_path, impulse_response

from .audio_measure import schroeder_rt60

SAMPLE_RATE = 48000


def request(effect, seconds: float = 3.0) -> EffectRequest:
    return EffectRequest(effect, "[in]", "[out]", "t", seconds)


# ---------- as contas do Atraso e do Eco ----------


def test_the_echo_stops_when_a_repetition_falls_below_minus_60_db():
    assert echo_repeats(0.5) == 10  # 0,5^10 = -60,2 dB
    assert echo_repeats(0.9) == 66
    assert echo_repeats(0.0) == 0
    assert echo_repeats(1.0) is None  # não cai nunca
    assert 20 * math.log10(0.5**10) < ECHO_FLOOR_DB < 20 * math.log10(0.5**9)


def test_the_echo_tail_is_the_time_of_the_last_repetition_with_a_ceiling():
    assert echo_tail_seconds(0.3, 0.5) == pytest.approx(3.0)
    assert echo_tail_seconds(2.0, 0.99) == MAX_ECHO_TAIL_SECONDS
    assert echo_tail_seconds(1.0, 1.0) == MAX_ECHO_TAIL_SECONDS


def test_the_doubling_stages_cover_exactly_the_repetitions_with_a_logarithmic_graph():
    assert [doubling_stages(n) for n in (1, 2, 3, 10, 15, 16, 687)] == [1, 1, 2, 3, 4, 4, 9]
    assert doubling_blocks(10) == [
        (3, 0),
        (1, 8),
        (0, 10),
    ]  # 8 parcelas, depois 2 deslocadas de 8, depois 1 de 10
    for repeats in range(1, 700):
        blocks = doubling_blocks(repeats)
        assert sum(2**stage for stage, _ in blocks) == repeats + 1  # o som e cada repetição, nem uma a mais
        assert [offset for _, offset in blocks] == [
            sum(2**s for s, _ in blocks[:i]) for i in range(len(blocks))
        ]
        assert blocks[0] == (doubling_stages(repeats), 0)


def test_a_regular_delay_repeats_at_equal_gaps_and_the_gain_and_pitch_follow_the_count():
    echoes = delay_echoes("regular", 0.25, 4, -6.0, 2.0, 2)
    assert [round(echo.at, 6) for echo in echoes] == [0.25, 0.5, 0.75, 1.0]
    assert [echo.gain_db for echo in echoes] == [-6.0, -12.0, -18.0, -24.0]
    assert [echo.semitones for echo in echoes] == [2.0, 2.0, 4.0, 4.0]  # o tom sobe a cada 2 ecos


def test_the_bouncing_delay_shortens_the_gaps_and_the_reverse_one_lengthens_them_to_the_same_total():
    bouncing = delay_echoes("bouncing", 0.5, 4, 0.0, 0.0, 1)
    reverse = delay_echoes("reverse_bouncing", 0.5, 4, 0.0, 0.0, 1)
    gaps = np.diff([0.0] + [echo.at for echo in bouncing])
    assert gaps == pytest.approx([0.5 * BOUNCE_RATIO**j for j in range(4)])
    assert np.diff([0.0] + [echo.at for echo in reverse]) == pytest.approx(gaps[::-1])
    assert bouncing[-1].at == pytest.approx(reverse[-1].at)
    with pytest.raises(ValueError, match="desconhecido"):
        delay_echoes("outro", 0.5, 2, 0.0, 0.0, 1)


# ---------- as classes ----------


def test_the_extended_tail_changes_the_duration_and_is_refused_where_the_item_cannot_grow():
    assert Echo().output_duration(5.0) == 5.0 and not Echo().alters_duration()
    assert Echo(delay_seconds=0.3, decay=0.5, extend_tail=True).output_duration(5.0) == pytest.approx(8.0)
    assert Delay(delay_seconds=0.5, echoes=3, extend_tail=True).output_duration(5.0) == pytest.approx(6.5)
    settings = Reverb(extend_tail=True).impulse_settings()
    assert Reverb(extend_tail=True).output_duration(5.0) == pytest.approx(5.0 + settings.tail_seconds())

    def with_clip_effect(effect: dict) -> Project:
        return Project.model_validate(
            {
                "name": "t",
                "timeline": [{"type": "clip", "src": "v.mp4", "start": 0, "end": 4, "effects": [effect]}],
                "audio": {"voiceover": []},
            }
        )

    with pytest.raises(ValidationError, match="extend_tail"):
        with_clip_effect({"type": "echo", "extend_tail": True})
    with_clip_effect({"type": "echo", "extend_tail": False})  # sem esticar, vale em qualquer item
    Project.model_validate(
        {
            "name": "t",
            "timeline": [{"type": "clip", "src": "v.mp4", "start": 0, "end": 4}],
            "audio": {"music": {"src": "m.wav", "effects": [{"type": "reverb", "extend_tail": True}]}},
        }
    )


def test_the_parameters_have_the_audacity_ranges():
    with pytest.raises(ValidationError):
        Echo(decay=1.5)
    with pytest.raises(ValidationError):
        Delay(echoes=0)
    with pytest.raises(ValidationError):
        Reverb(room_size=101)
    reverb = {p.name: p for info in catalog() if info.type == "reverb" for p in info.parameters}
    assert (reverb["room_size"].default, reverb["room_size"].minimum, reverb["room_size"].maximum) == (
        75.0,
        0.0,
        100.0,
    )
    assert (reverb["wet_db"].default, reverb["dry_db"].default) == (-1.0, -1.0)
    assert reverb["wet_only"].kind == "boolean" and reverb["stereo_width"].unit == "%"


def test_the_family_is_in_the_catalog_without_fixing_the_whole_set():
    types = {info.type for info in catalog()}
    assert {"delay", "echo", "reverb"} <= types
    assert {"delay", "echo", "reverb"} <= set(EFFECT_CLASSES)
    ids = set(EFFECT_PRESETS)
    assert set(REVERB_RT60_RANGES) <= ids
    assert {"phone_voice", "old_radio_voice", "room_narration", "ethereal_music"} <= ids


# ---------- os grafos ----------


def test_the_echo_is_a_log_number_of_doubling_stages_with_the_exact_delay_and_gain():
    lines = build_effect(request(Echo(delay_seconds=0.3, decay=0.5)))
    delays = [line for line in lines if "adelay" in line]
    assert len(delays) == doubling_stages(10) + 2 == 5  # três dobras e dois blocos deslocados na soma final
    assert "adelay=14400S:all=1,volume=0.5" in delays[0]  # 300 ms a 48 kHz, metade da amplitude
    assert "adelay=28800S:all=1,volume=0.25" in delays[1]
    assert any(
        "adelay=115200S:all=1,volume=0.00390625" in line for line in delays
    )  # a 9ª parcela: 8 atrasos, 0,5^8
    assert any(
        "adelay=144000S:all=1,volume=0.000976562" in line for line in delays
    )  # a 11ª: 10 atrasos, 0,5^10
    assert lines[0].startswith("[in]asplit=3") and lines[-1].endswith(
        "[out]"
    )  # a dobra, a cópia e o bloco de 1 da soma
    assert "atrim=end_sample=144000" in lines[-1]  # o item mantém a duração: a cauda é cortada


def test_the_echo_without_repetitions_is_a_passthrough_and_the_one_that_never_falls_stops_at_the_item():
    assert build_effect(request(Echo(decay=0.0))) == ["[in]anull[out]"]
    effect = Echo(delay_seconds=0.5, decay=1.0)
    assert echo_stage_count(effect, 3 * SAMPLE_RATE, SAMPLE_RATE) == 6  # cabem 6 repetições em 3 s
    long = Echo(delay_seconds=0.001, decay=0.99)
    assert echo_stage_count(long, 3 * SAMPLE_RATE, SAMPLE_RATE) == echo_repeats(0.99)


def test_the_extended_echo_graph_ends_at_the_tail_length():
    lines = build_effect(request(Echo(delay_seconds=0.3, decay=0.5, extend_tail=True)))
    assert f"atrim=end_sample={3 * SAMPLE_RATE + round(3.0 * SAMPLE_RATE)}" in lines[-1]


def test_the_delay_has_one_branch_per_echo_and_only_the_pitched_ones_use_the_rubberband():
    plain = build_effect(request(Delay(delay_seconds=0.3, echoes=3)))
    assert plain[0] == "[in]asplit=4[t_b0][t_b1][t_b2][t_b3]"
    assert not any("rubberband" in line for line in plain)
    assert any("adelay=43200S:all=1,volume=-18.000000dB" in line for line in plain)  # o terceiro eco
    pitched = build_effect(request(Delay(echoes=2, pitch_semitones=3.0)))
    assert sum("rubberband" in line for line in pitched) == 2
    assert any(f"pitch={2 ** (6 / 12):.9f}" in line for line in pitched)  # o segundo eco, 6 semitons acima
    assert "amix=inputs=3:normalize=0" in pitched[-1]


def test_the_reverb_reads_the_impulse_from_the_cache_and_mixes_the_dry_apart():
    effect = Reverb(wet_db=-3.0, dry_db=-6.0)
    lines = build_effect(request(effect))
    path = impulse_path(effect.impulse_settings(), SAMPLE_RATE)
    assert lines[0].startswith("[in]asplit=2")
    assert any(line.startswith("amovie=") and path.name in line for line in lines)
    assert any(
        "afir=gtype=none:irnorm=-1" in line for line in lines
    )  # convolução exata: nenhuma normalização
    assert any("volume=-6.000000dB" in line for line in lines)
    assert "amix=inputs=2:normalize=0" in lines[-1]
    only_wet = build_effect(request(Reverb(wet_only=True)))
    assert not any("amix" in line or "asplit" in line for line in only_wet)


def test_the_reverb_tail_pads_the_input_so_the_convolution_is_not_cut_at_the_item_end():
    effect = Reverb(extend_tail=True)
    length = 3 * SAMPLE_RATE + math.ceil(effect.impulse_settings().tail_seconds() * SAMPLE_RATE)
    lines = build_effect(request(effect))
    assert f"apad=whole_len={length}" in lines[0]
    assert f"atrim=end_sample={length}" in lines[-1]


# ---------- a resposta ao impulso ----------


def test_the_reverb_time_grows_with_the_room_and_the_reverberance_and_has_a_ceiling():
    assert reverb_time(20, 50) < reverb_time(60, 50) < reverb_time(100, 50)
    assert reverb_time(50, 10) < reverb_time(50, 50) < reverb_time(50, 90)
    assert reverb_time(100, 100) <= MAX_T60
    assert ReverbSettings().tail_seconds() == pytest.approx(0.01 + reverb_time(75, 50))


def test_the_impulse_response_has_the_asked_reverb_time():
    for room, reverberance in ((30, 50), (75, 50), (90, 80)):
        settings = ReverbSettings(room_size=room, reverberance=reverberance, damping=0.0)
        measured = schroeder_rt60(impulse_response(settings), 0)
        assert measured == pytest.approx(settings.reverb_time(), rel=0.25), (room, reverberance)


@pytest.mark.parametrize("preset_id", sorted(REVERB_RT60_RANGES))
def test_each_audacity_preset_has_a_reverb_time_inside_its_documented_range(preset_id):
    effect = parse_effect(dict(EFFECT_PRESETS[preset_id].effects[0]))
    ir = impulse_response(effect.impulse_settings())
    low, high = REVERB_RT60_RANGES[preset_id]
    assert low <= schroeder_rt60(ir, 0) <= high


def test_the_presets_are_ordered_like_the_names_say():
    def measured(preset_id: str) -> float:
        effect = parse_effect(dict(EFFECT_PRESETS[preset_id].effects[0]))
        return schroeder_rt60(impulse_response(effect.impulse_settings()), 0)

    small = measured("reverb_small_room_bright")
    assert (
        small < measured("reverb_medium_room") < measured("reverb_church_hall") < measured("reverb_cathedral")
    )
    assert measured("reverb_cathedral") > 4.0 > measured("reverb_bathroom")


def test_the_impulse_response_is_stereo_float32_deterministic_and_starts_after_the_pre_delay():
    settings = ReverbSettings(pre_delay_ms=20.0)
    ir = impulse_response(settings)
    assert ir.dtype == np.float32 and ir.shape[1] == 2
    assert np.array_equal(ir, impulse_response(settings))
    lead = round(0.020 * RATE)
    assert np.abs(ir[:lead]).max() == 0.0 and np.abs(ir[lead : lead + 4000]).max() > 0
    assert len(ir) == pytest.approx(lead + math.ceil(1.4 * settings.reverb_time() * RATE), abs=1)


def test_the_wet_gain_scales_the_response_and_zero_db_gives_the_dry_power():
    base = impulse_response(ReverbSettings(wet_db=0.0))
    louder = impulse_response(ReverbSettings(wet_db=6.0))
    assert np.sqrt(
        np.sum(louder.astype(np.float64) ** 2) / np.sum(base.astype(np.float64) ** 2)
    ) == pytest.approx(10 ** (6 / 20), rel=1e-3)
    power = float(np.mean(np.sum(base.astype(np.float64) ** 2, axis=0)))
    assert power == pytest.approx(1.0, rel=0.1)  # a cauda cortada e a rampa tiram uma fração


def test_the_stereo_width_goes_from_the_same_reverb_in_both_sides_to_independent_sides():
    mono = impulse_response(ReverbSettings(stereo_width=0.0))
    wide = impulse_response(ReverbSettings(stereo_width=100.0))
    assert np.allclose(mono[:, 0], mono[:, 1], atol=1e-6)
    correlation = float(np.corrcoef(wide[:, 0], wide[:, 1])[0, 1])
    assert abs(correlation) < 0.3


def test_the_tone_controls_only_take_energy_away_and_cut_the_band_they_name():
    flat = impulse_response(ReverbSettings())
    no_lows = impulse_response(ReverbSettings(tone_low=0.0))
    no_highs = impulse_response(ReverbSettings(tone_high=0.0))

    def band_energy(ir: np.ndarray, low: float, high: float) -> float:
        spectrum = np.abs(np.fft.rfft(ir[:, 0].astype(np.float64))) ** 2
        hz = np.fft.rfftfreq(len(ir), 1 / RATE)
        return float(spectrum[(hz >= low) & (hz < high)].sum())

    assert band_energy(no_lows, 20, 150) < 0.1 * band_energy(flat, 20, 150)
    assert band_energy(no_lows, 1000, 3000) == pytest.approx(band_energy(flat, 1000, 3000), rel=0.1)
    assert band_energy(no_highs, 8000, 20000) < 0.1 * band_energy(flat, 8000, 20000)
    assert np.sum(no_lows**2) < np.sum(flat**2) and np.sum(no_highs**2) < np.sum(flat**2)


def test_the_damping_makes_the_highs_die_before_the_lows():
    def band_decay(damping: float, low: float, high: float) -> float:
        ir = impulse_response(ReverbSettings(damping=damping, tone_low=100.0))
        late = ir[round(0.3 * RATE) : round(0.6 * RATE), 0].astype(np.float64)
        spectrum = np.abs(np.fft.rfft(late)) ** 2
        hz = np.fft.rfftfreq(len(late), 1 / RATE)
        return float(spectrum[(hz >= low) & (hz < high)].sum())

    dry = band_decay(0.0, 6000, 12000) / band_decay(0.0, 200, 1000)
    damped = band_decay(100.0, 6000, 12000) / band_decay(100.0, 200, 1000)
    assert damped < 0.2 * dry


# ---------- o arquivo em cache ----------


def test_the_impulse_file_lives_in_the_cache_folder_and_is_made_only_once():
    settings = ReverbSettings(room_size=20.0)
    path = impulse_path(settings)
    assert path.parent == config.REVERB_IR_DIR and not path.exists()
    made = ensure_impulse(settings)
    stamp = made.stat().st_mtime_ns
    assert made == path and path.exists()
    assert ensure_impulse(settings).stat().st_mtime_ns == stamp  # a segunda vez não refaz
    assert impulse_path(ReverbSettings(room_size=21.0)) != path
    assert impulse_path(settings, 44100) != path
    assert not list(config.REVERB_IR_DIR.glob("*.tmp-*"))


# ---------- as predefinições ----------


def test_the_presets_only_use_known_effects_and_the_reverb_ones_have_a_single_reverb():
    for preset_id in (
        *REVERB_RT60_RANGES,
        "phone_voice",
        "old_radio_voice",
        "room_narration",
        "ethereal_music",
    ):
        for effect in EFFECT_PRESETS[preset_id].effects:
            assert parse_effect(dict(effect)).type == effect["type"]
    for preset_id in REVERB_RT60_RANGES:
        assert [e["type"] for e in EFFECT_PRESETS[preset_id].effects] == ["reverb"]
    assert set(REVERB_RT60_RANGES) == {i for i in EFFECT_PRESETS if i.startswith("reverb_")}


def test_the_presets_that_work_on_samples_are_refused_in_the_master_but_the_reverb_ones_are_not():
    check_preset_fits(EFFECT_PRESETS["reverb_cathedral"], False, "o master")
    check_preset_fits(EFFECT_PRESETS["room_narration"], False, "o master")
    for preset_id in ("phone_voice", "old_radio_voice", "ethereal_music"):
        with pytest.raises(ValueError, match="amostras"):
            check_preset_fits(EFFECT_PRESETS[preset_id], False, "o master")


def test_the_phone_and_radio_presets_reuse_the_eq_curves_of_the_eq_presets():
    assert EFFECT_PRESETS["phone_voice"].effects[0] == EFFECT_PRESETS["telephone"].effects[0]
    assert EFFECT_PRESETS["old_radio_voice"].effects[0] == EFFECT_PRESETS["am_radio"].effects[0]
    assert EFFECT_PRESETS["old_radio_voice"].effects[1]["hiss_db"] < -40
    stretch, reverb = EFFECT_PRESETS["ethereal_music"].effects
    assert stretch == {"type": "paulstretch", "stretch_factor": 8.0}
    assert reverb["room_size"] >= 90 and reverb["reverberance"] >= 80
