"""Distorção, Phaser, Tremolo, Wahwah e Vocoder sem ffmpeg: as curvas, as respostas dos filtros e o vocoder, com sinais conhecidos.

O que passa pelo ffmpeg e pelo processador (a envoltória do Tremolo a 5 Hz, o Whisper depois do Vocoder) está em
`test_audio_creative_effects_integration.py`.
"""

from __future__ import annotations

import math
from typing import get_args

import numpy as np
import pytest
from pydantic import ValidationError

from dmaker.domain.audio_effects import EFFECT_CLASSES, EFFECT_PRESETS, catalog, parse_effect
from dmaker.domain.audio_effects.distortion_modulation import (
    DEFAULT_CARRIER_PARAMS,
    MAX_VOCODER_SECONDS,
    CarrierSound,
    Distortion,
    DistortionKind,
    Phaser,
    Vocoder,
)
from dmaker.filtergraph.audio_effects import EffectRequest, SampleRequest, build_effect, build_samples
from dmaker.filtergraph.audio_effects.distortion_modulation import tremolo_gain_expression
from dmaker.media.distortion import DC_BLOCK, DistortionSettings, distort, remove_dc, transfer_types
from dmaker.media.modulation import (
    PHASER_CENTER_HZ,
    WAH_HIGH_HZ,
    WAH_LOW_HZ,
    phaser_response,
    wah_centers,
    wah_response,
)
from dmaker.media.spectral import FFT_SIZE
from dmaker.media.stft_filter import apply_response, bin_omega
from dmaker.media.vocoder import band_weights, vocode

RATE = 48000


def sine(seconds: float, hz: float = 440.0, amplitude: float = 0.89, channels: int = 2) -> np.ndarray:
    t = np.arange(round(seconds * RATE)) / RATE
    return np.repeat((amplitude * np.sin(2 * np.pi * hz * t))[:, None], channels, axis=1).astype(np.float32)


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


# ---------- Distorção ----------


def test_every_distortion_kind_in_the_spec_has_a_curve_and_the_other_way_round():
    assert set(get_args(DistortionKind)) == transfer_types()


@pytest.mark.parametrize("kind", sorted(transfer_types()))
def test_no_distortion_kind_leaves_full_scale_with_the_default_settings_even_with_a_hot_input(kind):
    for drive in (0.0, 12.0, 24.0):
        settings = DistortionSettings(kind, drive_db=drive, dc_filter=False)
        out = distort(sine(0.2), settings, RATE)
        assert out.shape == (round(0.2 * RATE), 2) and out.dtype == np.float32
        assert float(np.abs(out).max()) <= 1.0 + 1e-6, (kind, drive)


@pytest.mark.parametrize(
    "kind",
    ["hard_clip", "soft_clip", "soft_overdrive", "medium_overdrive", "hard_overdrive", "cubic", "leveller"],
)
def test_the_odd_curves_are_symmetric_so_they_make_no_dc_offset(kind):
    wave = sine(0.2)
    settings = DistortionSettings(kind, dc_filter=False)
    assert np.allclose(distort(-wave, settings, RATE), -distort(wave, settings, RATE), atol=1e-6)


def test_the_hard_clip_holds_the_signal_at_the_threshold_and_leaves_what_is_below_it():
    settings = DistortionSettings("hard_clip", threshold_db=-6.0, dc_filter=False)
    out = distort(sine(0.2, amplitude=0.8), settings, RATE)
    assert float(np.abs(out).max()) == pytest.approx(10 ** (-6 / 20), rel=1e-5)
    quiet = sine(0.2, amplitude=0.3)
    assert np.allclose(distort(quiet, settings, RATE), quiet, atol=1e-7)


def test_the_soft_clip_is_smooth_below_the_knee_and_never_reaches_the_threshold():
    wave = sine(0.2, amplitude=0.8)
    hard = distort(wave, DistortionSettings("hard_clip", threshold_db=-6.0, dc_filter=False), RATE)
    for amount in (0.0, 100.0):
        soft = distort(
            wave, DistortionSettings("soft_clip", threshold_db=-6.0, amount=amount, dc_filter=False), RATE
        )
        assert float(np.abs(soft).max()) < float(np.abs(hard).max())
    softer = distort(wave, DistortionSettings("soft_clip", amount=0.0, dc_filter=False), RATE)
    harder = distort(wave, DistortionSettings("soft_clip", amount=100.0, dc_filter=False), RATE)
    assert rms(harder) > rms(softer)  # a quantidade endurece o joelho: chega mais perto de um corte seco


def test_the_overdrives_saturate_earlier_as_they_get_harder():
    wave = sine(0.2, amplitude=0.3)
    levels = [
        rms(distort(wave, DistortionSettings(kind, threshold_db=-3.0, dc_filter=False), RATE))
        for kind in ("soft_overdrive", "medium_overdrive", "hard_overdrive")
    ]
    assert levels[0] < levels[1] < levels[2]


def test_the_even_harmonics_curve_adds_the_second_harmonic_and_the_dc_filter_removes_the_offset():
    wave = sine(1.0, hz=1000.0, amplitude=0.5, channels=1)
    raw = distort(wave, DistortionSettings("even_harmonics", amount=50.0, dc_filter=False), RATE)
    spectrum = np.abs(np.fft.rfft(raw[:, 0].astype(np.float64)))
    assert spectrum[2000] > 0.05 * spectrum[1000]  # 2 kHz aparece
    assert abs(float(raw.mean())) > 0.01  # o quadrado tem média
    filtered = distort(wave, DistortionSettings("even_harmonics", amount=50.0, dc_filter=True), RATE)
    assert abs(float(filtered[RATE // 2 :].mean())) < 1e-3


def test_the_rectifier_doubles_the_frequency_and_the_compander_changes_the_low_level_first():
    wave = sine(1.0, hz=500.0, amplitude=0.5, channels=1)
    full = distort(wave, DistortionSettings("rectifier", amount=100.0, dc_filter=True), RATE)
    spectrum = np.abs(np.fft.rfft(full[:, 0].astype(np.float64)))
    assert int(np.argmax(spectrum[100:])) + 100 == 1000  # o dobro de 500 Hz
    quiet = sine(0.2, amplitude=0.05)
    compressed = distort(quiet, DistortionSettings("expand_compress", amount=100.0, dc_filter=False), RATE)
    expanded = distort(quiet, DistortionSettings("expand_compress", amount=0.0, dc_filter=False), RATE)
    neutral = distort(quiet, DistortionSettings("expand_compress", amount=50.0, dc_filter=False), RATE)
    assert np.allclose(neutral, quiet, atol=1e-6)
    assert float(np.abs(compressed).max()) > 3 * 0.05 and float(np.abs(expanded).max()) < 0.05 / 3


def test_the_hard_limiter_lifts_the_ceiling_to_minus_one_dbfs():
    settings = DistortionSettings("hard_limiter", threshold_db=-12.0, dc_filter=False)
    out = distort(sine(0.2, amplitude=0.89), settings, RATE)
    assert 20 * math.log10(float(np.abs(out).max())) == pytest.approx(-1.0, abs=1e-4)


def test_the_bit_crusher_quantizes_to_the_bits_and_holds_samples_for_the_rate_reduction():
    wave = sine(0.2, amplitude=0.8, channels=1)
    out = distort(wave, DistortionSettings("bit_crusher", bits=4, dc_filter=False), RATE)
    assert len(np.unique(out)) <= 2**4
    assert np.allclose(out * 8, np.round(out * 8))
    held = distort(wave, DistortionSettings("bit_crusher", bits=16, downsample=8, dc_filter=False), RATE)
    assert np.array_equal(held[0:8], np.repeat(held[0:1], 8, axis=0))
    assert len(np.unique(held[:, 0])) < len(np.unique(wave[:, 0])) / 4


def test_the_repeats_apply_the_curve_again_and_the_output_level_scales_the_result():
    wave = sine(0.2, amplitude=0.3)
    once = distort(wave, DistortionSettings("leveller", repeats=1, dc_filter=False), RATE)
    thrice = distort(wave, DistortionSettings("leveller", repeats=3, dc_filter=False), RATE)
    assert rms(thrice) > rms(once) > rms(wave)
    louder = distort(wave, DistortionSettings("hard_clip", output_db=6.0, dc_filter=False), RATE)
    assert rms(louder) == pytest.approx(rms(wave) * 10 ** (6 / 20), rel=1e-4)


def test_the_hiss_is_seeded_white_noise_at_the_asked_level_and_off_by_default():
    silence = np.zeros((RATE, 2), dtype=np.float32)
    assert float(np.abs(distort(silence, DistortionSettings("hard_clip"), RATE)).max()) == 0.0
    hissy = distort(silence, DistortionSettings("hard_clip", hiss_db=-40.0, dc_filter=False), RATE)
    assert 20 * math.log10(rms(hissy)) == pytest.approx(-40.0, abs=0.3)
    assert np.array_equal(
        hissy, distort(silence, DistortionSettings("hard_clip", hiss_db=-40.0, dc_filter=False), RATE)
    )


def test_the_dc_filter_is_the_one_pole_recurrence_across_block_boundaries():
    rng = np.random.default_rng(1)
    signal = (0.3 + 0.2 * rng.standard_normal((DC_BLOCK * 2 + 777, 2))).astype(np.float64)
    pole = math.exp(-2 * math.pi * 10.0 / RATE)
    expected = np.zeros_like(signal)
    previous_in = np.zeros(2)
    previous_out = np.zeros(2)
    for n in range(len(signal)):
        previous_out = pole * previous_out + signal[n] - previous_in
        previous_in = signal[n]
        expected[n] = previous_out
    assert np.allclose(remove_dc(signal, RATE), expected, atol=1e-9)


def test_the_dc_filter_keeps_the_voice_band_and_kills_the_offset():
    t = np.arange(RATE * 2) / RATE
    wave = (0.4 + 0.3 * np.sin(2 * np.pi * 200 * t))[:, None]
    out = remove_dc(wave, RATE)
    assert abs(float(out[RATE:].mean())) < 1e-3
    assert rms(out[RATE:] - out[RATE:].mean()) == pytest.approx(0.3 / math.sqrt(2), rel=0.01)


def test_an_unknown_kind_and_a_range_error_are_refused_with_the_reason():
    with pytest.raises(ValueError, match="desconhecida"):
        distort(sine(0.1), DistortionSettings("inexistente"), RATE)
    with pytest.raises(ValidationError):
        Distortion(kind="inexistente")
    with pytest.raises(ValidationError):
        Distortion(threshold_db=3.0)


# ---------- Phaser ----------


def test_the_phaser_digs_one_notch_per_pair_of_stages_when_half_dry_half_wet():
    times = np.array([0.0])

    def notches(stages: int) -> int:
        magnitude = np.abs(phaser_response(times, RATE, stages, 255.0 / 2, 0.4, 0.0, 0.0, 0.0))[0]
        # com a profundidade em 0 a quebra fica no centro da varredura; uma queda é um mínimo bem abaixo da média
        below = magnitude < 0.1
        return int(np.sum(np.diff(below.astype(int)) == 1))

    assert [notches(n) for n in (2, 4, 6, 8)] == [1, 2, 3, 4]


def test_the_phaser_all_wet_is_an_all_pass_and_the_feedback_deepens_the_resonances():
    times = np.linspace(0, 1, 5)
    wet = np.abs(phaser_response(times, RATE, 6, 255.0, 0.4, 0.0, 100.0, 0.0))
    assert np.allclose(wet, 1.0, atol=1e-9)
    resonant = np.abs(phaser_response(times, RATE, 6, 255.0, 0.4, 0.0, 100.0, 80.0))
    assert resonant.max() > 3.0 > wet.max()
    dry = np.abs(phaser_response(times, RATE, 6, 0.0, 0.4, 0.0, 100.0, 80.0))
    assert np.allclose(dry, 1.0)


def test_the_phaser_sweep_follows_the_lfo_in_frequency_and_phase():
    def notch_hz(time: float, phase: float = 0.0, lfo: float = 0.5, depth: float = 255.0) -> float:
        magnitude = np.abs(phaser_response(np.array([time]), RATE, 2, 127.5, lfo, phase, depth, 0.0))[0]
        return float(np.argmin(magnitude[5:]) + 5) * RATE / FFT_SIZE

    # LFO de 0,5 Hz: o ponto mais agudo da varredura é em 0,5 s (seno em fase 0), o mais grave em 1,5 s
    assert notch_hz(0.5) > notch_hz(0.0) > notch_hz(1.5)
    assert notch_hz(0.0, phase=90.0) == pytest.approx(
        notch_hz(0.5), rel=0.05
    )  # 90 graus adiantam a varredura
    assert notch_hz(0.5, depth=0.0) == pytest.approx(
        notch_hz(1.5, depth=0.0), rel=0.05
    )  # sem profundidade, parada
    assert notch_hz(0.0, depth=0.0) < 2 * PHASER_CENTER_HZ


def test_the_phaser_stages_must_be_even_and_the_spec_checks_the_ranges():
    with pytest.raises(ValidationError, match="pares"):
        Phaser(stages=3)
    with pytest.raises(ValidationError):
        Phaser(lfo_hz=5.0)
    Phaser(stages=24, lfo_hz=4.0, dry_wet=255, depth=255, feedback_percent=-100)


# ---------- Wahwah ----------


def test_the_wah_sweeps_between_the_two_ends_of_the_pedal_range():
    times = np.linspace(0, 2, 2001)
    widest = wah_centers(times, 1.0, 0.0, 1.0, 0.0)
    assert widest.min() == pytest.approx(WAH_LOW_HZ, rel=0.01) and widest.max() == pytest.approx(
        WAH_HIGH_HZ, rel=0.01
    )
    narrow = wah_centers(times, 1.0, 0.0, 0.7, 0.3)
    assert narrow.min() == pytest.approx(WAH_LOW_HZ * (WAH_HIGH_HZ / WAH_LOW_HZ) ** 0.3, rel=0.01)
    assert narrow.max() < widest.max()
    assert wah_centers(np.array([0.0, 0.3]), 1.0, 0.0, 0.0, 0.5) == pytest.approx(
        WAH_LOW_HZ * (WAH_HIGH_HZ / WAH_LOW_HZ) ** 0.5
    )  # sem profundidade, o centro fica no deslocamento


def test_the_wah_filter_peaks_at_the_center_with_unity_gain_and_a_higher_q_is_narrower():
    times = np.array([0.0])
    center = float(wah_centers(times, 1.0, 0.0, 0.0, 0.5)[0])
    hz = np.arange(FFT_SIZE // 2 + 1) * RATE / FFT_SIZE

    def width(q: float) -> float:
        magnitude = np.abs(wah_response(times, RATE, 1.0, 0.0, 0.0, q, 0.5))[0]
        assert magnitude.max() == pytest.approx(1.0, abs=0.02)
        assert hz[int(np.argmax(magnitude))] == pytest.approx(center, rel=0.05)
        return float(np.sum(magnitude > 1 / math.sqrt(2)) * RATE / FFT_SIZE)

    assert width(8.0) < width(2.0) < width(0.5)


def test_the_frame_filter_applies_the_response_and_keeps_the_length_and_the_level_of_a_flat_one():
    wave = sine(1.0, hz=1000.0, amplitude=0.5, channels=2)
    flat = apply_response(wave, RATE, lambda times: np.ones((len(times), len(bin_omega()))))
    assert flat.shape == wave.shape
    assert np.allclose(flat[2000:-2000], wave[2000:-2000], atol=1e-4)  # fora das pontas, o mesmo sinal
    half = apply_response(wave, RATE, lambda times: 0.5 * np.ones((len(times), len(bin_omega()))))
    assert rms(half[2000:-2000]) == pytest.approx(rms(wave[2000:-2000]) / 2, rel=1e-3)
    mono = apply_response(wave[:, 0], RATE, lambda times: np.ones((len(times), len(bin_omega()))))
    assert mono.ndim == 1


# ---------- Tremolo ----------


def test_the_tremolo_gain_expression_runs_from_one_minus_the_depth_to_one():
    for waveform in ("sine", "triangle", "sawtooth", "inverse_sawtooth", "square"):
        expression = tremolo_gain_expression(waveform, 5.0, 90.0, 50.0)
        assert expression.startswith("1-0.5*(1-(") and "5*t+0.25" in expression
    assert "mod(" in tremolo_gain_expression("sawtooth", 4.0, 0.0, 40.0)
    assert "lt(mod(" in tremolo_gain_expression("square", 4.0, 0.0, 40.0)
    assert "sin(" in tremolo_gain_expression("sine", 4.0, 0.0, 40.0)
    assert build_effect(
        EffectRequest(parse_effect({"type": "tremolo", "depth": 0}), "[in]", "[out]", "t", 1.0)
    ) == ["[in]anull[out]"]
    line = build_effect(EffectRequest(parse_effect({"type": "tremolo"}), "[in]", "[out]", "t", 1.0))[0]
    assert "asetnsamples=n=64:p=0" in line and "eval=frame" in line


# ---------- Vocoder ----------


def test_the_band_weights_cover_every_bin_and_the_bands_are_log_spaced_triangles():
    weights = band_weights(RATE, 40, 20.0)
    assert weights.shape == (40, FFT_SIZE // 2 + 1)
    assert float(weights.sum(axis=0).min()) > 0  # nenhum bin fica sem banda
    centers = (weights * np.arange(weights.shape[1])).sum(axis=1) / weights.sum(axis=1)
    ratios = centers[2:20] / centers[1:19]
    assert float(ratios.std() / ratios.mean()) < 0.15  # centros em progressão geométrica
    narrow, wide = band_weights(RATE, 40, 5.0), band_weights(RATE, 40, 80.0)
    assert (wide > 0).sum() > (weights > 0).sum() > (narrow > 0).sum()
    assert float(narrow.sum(axis=0).min()) > 0  # mesmo estreita, cada bin tem a banda mais próxima


def test_the_vocoder_gives_the_carrier_the_spectral_envelope_of_the_voice():
    rng = np.random.default_rng(2)
    carrier = rng.standard_normal((RATE * 2, 2)).astype(np.float32) * 0.2
    voice = sine(2.0, hz=1000.0, amplitude=0.5, channels=1)
    out = vocode(voice, carrier, RATE, 40, 20.0, 0.0, 0.0, 0.0, 30.0)
    assert out.shape == (RATE * 2, 2) and out.dtype == np.float32
    spectrum = np.abs(np.fft.rfft(out[RATE // 2 : RATE * 3 // 2, 0].astype(np.float64) * np.hanning(RATE)))
    hz = np.fft.rfftfreq(RATE, 1 / RATE)
    peak_hz = hz[int(np.argmax(spectrum))]
    assert 800 <= peak_hz <= 1250  # o ruído plano saiu moldado em volta do tom da voz
    inside = spectrum[(hz > 800) & (hz < 1250)].sum()
    assert inside > 0.5 * spectrum[(hz > 100) & (hz < 8000)].sum()


def test_the_vocoder_is_silent_when_the_voice_is_and_follows_the_voice_loudness_in_time():
    carrier = sine(2.0, hz=110.0, amplitude=0.5)
    silent = vocode(np.zeros((RATE * 2, 1), dtype=np.float32), carrier, RATE, 40, 20.0, 0.0, 0.0, 0.0, 30.0)
    assert float(np.abs(silent).max()) < 1e-6
    voice = np.zeros((RATE * 2, 1), dtype=np.float32)
    voice[RATE:] = sine(1.0, hz=700.0, amplitude=0.5, channels=1)
    out = vocode(voice, carrier, RATE, 40, 20.0, 0.0, 0.0, 0.0, 30.0)
    assert rms(out[: RATE - 3000]) < 0.01 * rms(out[RATE + 3000 :])


def test_the_vocoder_noise_the_radar_and_the_original_add_what_they_are_asked_to():
    carrier = sine(1.0, hz=110.0, amplitude=0.4)
    voice = sine(1.0, hz=700.0, amplitude=0.5, channels=1)
    base = vocode(voice, carrier, RATE, 40, 20.0, 0.0, 0.0, 0.0, 30.0)
    assert not np.allclose(base, vocode(voice, carrier, RATE, 40, 20.0, 0.0, 0.5, 0.0, 30.0))
    assert not np.allclose(base, vocode(voice, carrier, RATE, 40, 20.0, 0.0, 0.0, 0.5, 30.0))
    with_original = vocode(voice, carrier, RATE, 40, 20.0, 0.5, 0.0, 0.0, 30.0)
    assert np.allclose(with_original - base, 0.5 * voice, atol=1e-5)
    assert np.array_equal(base, vocode(voice, carrier, RATE, 40, 20.0, 0.0, 0.0, 0.0, 30.0))  # semente fixa


def test_the_vocoder_accepts_a_mono_carrier_and_mixes_a_stereo_voice_to_mono():
    carrier = sine(1.0, hz=110.0, amplitude=0.4, channels=1)
    voice = sine(1.0, hz=700.0, amplitude=0.5, channels=2)
    out = vocode(voice, carrier, RATE, 20, 20.0, 0.0, 0.2, 0.0, 30.0)
    assert out.shape == (RATE, 2)


def test_the_vocoder_sample_builder_needs_the_carrier_and_the_effect_trims_by_the_interval():
    effect = parse_effect({"type": "vocoder"})
    with pytest.raises(ValueError, match="portadora"):
        build_samples(SampleRequest(effect, sine(1.0)))
    out = build_samples(SampleRequest(effect, sine(1.0, hz=700.0), RATE, None, sine(1.0, hz=110.0)))
    assert out.shape == (RATE, 2)


def test_the_vocoder_carrier_defaults_to_a_sawtooth_and_only_takes_signal_generators():
    effect = Vocoder()
    assert effect.carrier_sound() == ("tone", DEFAULT_CARRIER_PARAMS)
    assert effect.carrier.params["waveform"] == "sawtooth"
    custom = parse_effect({"type": "vocoder", "carrier": {"generator": "noise"}})
    assert custom.carrier_sound()[0] == "noise" and "amplitude_db" in custom.carrier_sound()[1]
    with pytest.raises(ValidationError, match="desconhecido"):
        CarrierSound(generator="inexistente")
    with pytest.raises(ValidationError, match="arquivos"):
        CarrierSound(generator="sample_data", params={"src": "x.txt"})
    assert effect.refusal(MAX_VOCODER_SECONDS) is None and "10" in effect.refusal(MAX_VOCODER_SECONDS + 1)


def test_the_catalog_lists_the_family_and_marks_the_carrier_and_the_sample_stage():
    by_type = {info.type: info for info in catalog()}
    for name in ("distortion", "phaser", "tremolo", "wahwah", "vocoder"):
        assert name in by_type and name in EFFECT_CLASSES
    assert [
        by_type[name].sample_stage for name in ("distortion", "phaser", "tremolo", "wahwah", "vocoder")
    ] == [
        True,
        True,
        False,
        True,
        True,
    ]
    parameters = {p.name: p for p in by_type["vocoder"].parameters}
    assert parameters["carrier"].kind == "carrier" and parameters["bands"].maximum == 50
    kind = {p.name: p for p in by_type["distortion"].parameters}["kind"]
    assert "bit_crusher" in kind.options and len(kind.options) == 12
    assert {p.name: p for p in by_type["distortion"].parameters}["bits"].shown_when == {"kind": "bit_crusher"}
    assert {"phone_voice", "old_radio_voice", "ethereal_music"} <= set(EFFECT_PRESETS)
