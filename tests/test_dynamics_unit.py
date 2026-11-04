"""Volume e dinâmica sem ffmpeg: o gate em numpy, os construtores de filtro, a medida de loudness, as predefinições, as
ações de efeito e as rotas. O que precisa do ffmpeg de verdade está em `test_dynamics_integration.py`."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from dmaker.domain.audio_effects import (
    EFFECT_CLASSES,
    EFFECT_PRESETS,
    catalog_payload,
    check_preset_fits,
    get_effect_preset,
    parse_effect,
)
from dmaker.domain.edits import EditError
from dmaker.domain.effect_edits import apply_effect_op
from dmaker.domain.spec import Project
from dmaker.filtergraph.audio_effects import (
    EffectRequest,
    Measure,
    build_effect,
    builder_types,
    level_measure_lines,
    parse_level_measure,
    sample_builder_types,
)
from dmaker.filtergraph.audio_effects.dynamics import TRUE_PEAK_MARGIN_DB, loudness_gain_db
from dmaker.media.gate import (
    apply_gate,
    detector_levels_db,
    gate_openness,
    noise_level_db,
    suggested_threshold_db,
)
from dmaker.pipeline.effect_actions import registered_actions

RATE = 48000


def request(effect: dict, duration: float = 3.0, measure: Measure | None = None) -> EffectRequest:
    return EffectRequest(parse_effect(effect), "[in]", "[out]", "fx0", duration, measure)


def project(**audio) -> Project:
    return Project.model_validate(
        {"name": "p", "timeline": [{"type": "clip", "src": "v.mp4", "start": 0, "end": 5}], "audio": audio}
    )


# ---------- catálogo ----------


def test_the_new_effects_are_in_the_catalog_with_their_actions_and_presets():
    payload = catalog_payload()
    types = {info["type"]: info for info in payload["effects"]}
    assert {"compressor", "limiter", "noise_gate", "loudness_normalize"} <= set(types)
    assert [action["id"] for action in types["noise_gate"]["actions"]] == ["analyze_noise"]
    assert types["noise_gate"]["actions"][0]["fills"] == ["threshold_db"]
    assert types["compressor"]["actions"] == []
    assert {"podcast_voice", "reels_voice", "hold_peaks"} <= {
        preset["id"] for preset in payload["presets"]
    }  # e as de equalização do DMK-54
    knee = next(p for p in types["compressor"]["parameters"] if p["name"] == "knee_db")
    assert (knee["minimum"], knee["maximum"]) == (0.0, 18.0)  # a faixa do joelho do acompressor, em dB


def test_every_declared_action_has_a_body_and_every_body_a_declaration():
    declared = {(name, action.id) for name, cls in EFFECT_CLASSES.items() for action in cls.actions}
    assert declared == registered_actions()


def test_every_effect_has_exactly_one_builder_filter_or_samples():
    assert set(EFFECT_CLASSES) == builder_types() | sample_builder_types()
    assert not builder_types() & sample_builder_types()


# ---------- construtores de filtro ----------


def test_the_compressor_converts_db_to_the_linear_scale_of_acompressor():
    lines = build_effect(
        request(
            {
                "type": "compressor",
                "threshold_db": -20,
                "ratio": 4,
                "knee_db": 6,
                "makeup_db": 6,
                "lookahead_ms": 0,
            }
        )
    )
    text = lines[0]
    assert "acompressor=threshold=0.100000000" in text and "ratio=4" in text
    assert f"knee={10 ** (6 / 20):.6f}" in text and f"makeup={10 ** (6 / 20):.6f}" in text
    assert len(lines) == 1


def test_the_compressor_lookahead_detects_on_the_copy_without_delay():
    lines = build_effect(request({"type": "compressor", "lookahead_ms": 5}))
    text = ";".join(lines)
    assert "asplit=2" in text and "adelay=240S:all=1" in text  # 5 ms a 48 kHz
    assert text.count("sidechaincompress") == 1 and "atrim=start_sample=240:end_sample=144240" in text


def test_the_limiter_runs_oversampled_without_the_automatic_level_and_under_the_margin():
    text = build_effect(request({"type": "limiter", "ceiling_db": -1}))[0]
    assert "aresample=192000" in text and "level=0" in text and "latency=1" in text
    assert f"limit={10 ** ((-1 - TRUE_PEAK_MARGIN_DB) / 20):.9f}" in text
    soft = build_effect(request({"type": "limiter", "limit_type": "soft"}))[0]
    assert soft.index("acompressor") < soft.index("alimiter")
    assert "acompressor" not in text


def test_the_loudness_gain_follows_the_target_the_mode_and_the_dual_mono_choice():
    lufs = parse_effect({"type": "loudness_normalize", "target_db": -16})
    assert loudness_gain_db(lufs, Measure(loudness=-26.0)) == pytest.approx(10.0)
    assert loudness_gain_db(lufs, Measure(loudness=-26.0, mono_source=True)) == pytest.approx(
        10.0
    )  # dual-mono: igual
    single = parse_effect({"type": "loudness_normalize", "target_db": -16, "dual_mono": False})
    assert loudness_gain_db(single, Measure(loudness=-26.0, mono_source=True)) == pytest.approx(
        13.0103, abs=1e-3
    )
    assert loudness_gain_db(single, Measure(loudness=-26.0)) == pytest.approx(
        10.0
    )  # estéreo de verdade não muda
    rms = parse_effect({"type": "loudness_normalize", "mode": "rms", "target_db": -20})
    assert loudness_gain_db(rms, Measure(rms_db=-30.5)) == pytest.approx(10.5)
    assert loudness_gain_db(lufs, None) is None and loudness_gain_db(lufs, Measure()) is None
    assert build_effect(request({"type": "loudness_normalize"}, measure=None))[0].endswith("anull[out]")


# ---------- medida ----------

EBUR = """Input #0, wav, from 'a.wav':
  Stream #0:0: Audio: pcm_f32le ([3][0][0][0] / 0x0003), 44100 Hz, mono, flt, 1411 kb/s
Stream mapping:
  Stream #0:0 -> #0:0 (pcm_f32le (native) -> pcm_s16le (native))
[Parsed_ebur128_1 @ 0000] Summary:

  Integrated loudness:
    I:         -23.4 LUFS
    Threshold: -33.4 LUFS
"""


def test_the_loudness_measure_reads_the_summary_and_knows_a_mono_input():
    measure = parse_level_measure("lufs", EBUR)
    assert measure is not None and measure.loudness == -23.4 and measure.mono_source
    assert not parse_level_measure("lufs", EBUR.replace("mono", "stereo")).mono_source
    assert parse_level_measure("lufs", EBUR.replace("-23.4", "-inf")).loudness is None
    assert parse_level_measure("lufs", "") is None


def test_the_rms_measure_reads_the_overall_block_and_the_peak_measure_line_is_the_old_one():
    report = "[Parsed_astats_1 @ 0] Channel: 1\n[Parsed_astats_1 @ 0] RMS level dB: -30.0\n[Parsed_astats_1 @ 0] Overall\n[Parsed_astats_1 @ 0] RMS level dB: -27.5\n"
    assert parse_level_measure("rms", report).rms_db == -27.5
    assert level_measure_lines("peak", "[a]", "[b]") == ["[a]astats=metadata=0:reset=0[b]"]
    assert level_measure_lines("lufs", "[a]", "[b]", (0, 480)) == [
        "[a]atrim=start_sample=0:end_sample=480,ebur128=framelog=quiet[b]"
    ]
    with pytest.raises(ValueError):
        level_measure_lines("xyz", "[a]", "[b]")


def test_only_the_loudness_effect_asks_for_another_measure():
    kinds = {
        name: parse_effect({"type": name, **extra}).measure_kind()
        for name, extra in [("amplify", {}), ("normalize", {}), ("loudness_normalize", {"mode": "rms"})]
    }
    assert kinds == {"amplify": "peak", "normalize": "peak", "loudness_normalize": "rms"}


# ---------- o gate ----------


def hiss_and_words(rng: np.random.Generator) -> tuple[np.ndarray, list[int]]:
    parts, starts, position = [], [], 0
    for k in range(4):
        t = np.arange(round(0.4 * RATE)) / RATE
        word = np.sin(2 * np.pi * (150 + 30 * k) * t) * np.minimum(t / 0.003, 1.0) * 0.1
        starts.append(position)
        parts.append(word)
        noise = rng.standard_normal(round(0.6 * RATE)) * 0.004
        parts.append(noise)
        position += len(word) + len(noise)
    mono = np.concatenate(parts).astype(np.float32)
    return np.stack([mono, mono], axis=1), starts


def test_the_gate_opens_before_the_word_so_its_first_20_ms_survive_and_closes_the_hiss():
    signal, starts = hiss_and_words(np.random.default_rng(2))
    out = apply_gate(
        signal, RATE, threshold_db=-28, reduction_db=18, attack_ms=10, hold_ms=50, release_ms=100, link=True
    )
    assert out.shape == signal.shape and out.dtype == np.float32
    for start in starts:
        head = slice(start, start + round(0.02 * RATE))
        assert np.abs(out[head] - signal[head]).max() < 1e-6  # aberto antes do primeiro quadro da palavra
        gap = slice(start + round(0.65 * RATE), start + round(0.95 * RATE))
        drop = 20 * np.log10(np.sqrt(np.mean(signal[gap] ** 2)) / np.sqrt(np.mean(out[gap] ** 2)))
        assert drop == pytest.approx(18.0, abs=0.1)


def test_hold_keeps_the_gate_open_across_a_short_dip():
    levels = np.full(400, -60.0)
    levels[100:150] = -10.0
    levels[160:200] = -10.0  # uma queda de 10 ms entre as duas partes
    held = gate_openness(levels, -30, attack_blocks=1, hold_blocks=50, release_blocks=20)
    assert held[155] == pytest.approx(1.0)
    short = gate_openness(levels, -30, attack_blocks=1, hold_blocks=0, release_blocks=1)
    assert short[155] < 0.5


def test_unlinked_channels_gate_on_their_own_and_linked_ones_follow_the_louder():
    left = np.zeros(RATE, dtype=np.float32)
    right = (0.2 * np.sin(2 * np.pi * 200 * np.arange(RATE) / RATE)).astype(np.float32)
    stereo = np.stack([left + 0.0005, right], axis=1)
    linked = apply_gate(
        stereo, RATE, threshold_db=-30, reduction_db=40, attack_ms=5, hold_ms=10, release_ms=20, link=True
    )
    split = apply_gate(
        stereo, RATE, threshold_db=-30, reduction_db=40, attack_ms=5, hold_ms=10, release_ms=20, link=False
    )
    assert abs(linked[RATE // 2, 0]) == pytest.approx(0.0005, rel=1e-3)  # o esquerdo vai aberto com o direito
    assert abs(split[RATE // 2, 0]) < 0.0005 * 0.05  # sozinho, o esquerdo é chiado e fecha


def test_the_noise_analysis_suggests_the_level_plus_six_db_inside_the_field_range():
    rng = np.random.default_rng(4)
    hiss = np.stack([rng.standard_normal(RATE) * 0.005] * 2, axis=1).astype(np.float32)
    level = noise_level_db(hiss, RATE)
    assert -45.0 < level < -30.0  # o pico de 5 ms do chiado fica acima do RMS (-46 dB)
    assert suggested_threshold_db(level) == pytest.approx(level + 6.0)
    assert suggested_threshold_db(-120.0) == -96.0 and suggested_threshold_db(0.0) == -6.0
    assert noise_level_db(np.zeros((0, 2), dtype=np.float32), RATE) == -120.0
    assert detector_levels_db(np.zeros((10, 2), dtype=np.float32), RATE).shape == (0, 2)


# ---------- predefinições ----------


def test_a_preset_adds_each_effect_separately_at_the_end_of_the_chain():
    start = project(narration=[{"text": "oi"}])
    done = apply_effect_op(
        start, {"action": "preset", "target": "audio.narration.0", "preset": "podcast_voice"}
    )
    assert [effect.type for effect in done.audio.narration[0].effects] == [
        "noise_gate",
        "compressor",
        "loudness_normalize",
        "limiter",
    ]
    again = apply_effect_op(
        done, {"action": "preset", "target": "audio.narration.0", "preset": "hold_peaks", "index": 0}
    )
    assert [effect.type for effect in again.audio.narration[0].effects][
        0
    ] == "limiter"  # entra na posição pedida


def test_the_voice_presets_have_the_chains_the_planner_asked_for():
    podcast = {e["type"]: e for e in get_effect_preset("podcast_voice").effects}
    assert (podcast["compressor"]["ratio"], podcast["compressor"]["threshold_db"]) == (3.0, -18.0)
    assert (podcast["loudness_normalize"]["target_db"], podcast["limiter"]["ceiling_db"]) == (-16.0, -1.0)
    reels = {e["type"]: e for e in get_effect_preset("reels_voice").effects}
    assert (
        reels["compressor"]["ratio"],
        reels["compressor"]["threshold_db"],
        reels["loudness_normalize"]["target_db"],
    ) == (4.0, -20.0, -14.0)
    assert get_effect_preset("hold_peaks").effects[0]["limit_type"] == "soft"


def test_a_preset_with_the_gate_is_refused_on_the_master_with_the_reason_and_the_others_are_not():
    start = project()
    with pytest.raises(EditError, match="Noise Gate.*não vale"):
        apply_effect_op(start, {"action": "preset", "target": "audio.master", "preset": "podcast_voice"})
    assert apply_effect_op(
        start, {"action": "preset", "target": "audio.master", "preset": "reels_voice"}
    ).audio.master_effects
    with pytest.raises(EditError, match="Predefinição desconhecida"):
        apply_effect_op(start, {"action": "preset", "target": "audio.master", "preset": "nada"})
    with pytest.raises(ValueError):
        check_preset_fits(EFFECT_PRESETS["podcast_voice"], False, "o master")


# ---------- rotas ----------


def test_the_effect_routes_serve_the_catalog_the_action_and_refuse_a_missing_one(monkeypatch):
    from dmaker.ui.server import app

    client = TestClient(app)
    body = client.get("/api/audio-effects").json()
    assert "presets" in body and any(info["actions"] for info in body["effects"])
    spec = {"timeline": [{"type": "clip", "src": "v.mp4", "start": 0, "end": 5}]}
    refused = client.post(
        "/api/projects/p/audio-effect-action", json={"spec": spec, "effect": "noise_gate", "action": "nada"}
    )
    assert refused.status_code == 422 and "desconhecida" in refused.json()["detail"]
    broken = client.post(
        "/api/projects/p/audio-effect-action",
        json={"spec": {"timeline": []}, "effect": "noise_gate", "action": "analyze_noise"},
    )
    assert broken.status_code == 400
