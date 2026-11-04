"""As contas da limpeza e do reparo do áudio: funções puras sobre amostras, sem ffmpeg e sem disco.

Os sinais têm nível conhecido (tons com envoltória de fala e ruído branco de RMS dado), então cada critério sai de uma
medida e não da comparação com uma execução anterior.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from dmaker.domain.audio_effects import parse_effect
from dmaker.filtergraph.audio_effects import Measure, SampleRequest, apply_sample_effect
from dmaker.media.repair import repair_interval
from dmaker.media.spectral import (
    FFT_SIZE,
    band_levels,
    noise_spectrum,
    quiet_pause_window,
    quietest_window,
    reduce_noise,
)
from dmaker.voice.silence import find_silences, kept_length, plan_truncation

RATE = 48000


def db(value: float) -> float:
    return 20 * math.log10(max(value, 1e-12))


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(samples, dtype=np.float64) ** 2)))


def white_noise(seconds: float, level_db: float, seed: int = 7) -> np.ndarray:
    noise = np.random.default_rng(seed).standard_normal(round(seconds * RATE))
    return (noise / rms(noise) * 10 ** (level_db / 20)).astype(np.float32)


def voice(seconds: float) -> np.ndarray:
    """Uma "fala": três tons (180, 540 e 1210 Hz) sob uma envoltória silábica de 4 Hz, com amplitude de ~0,3."""
    t = np.arange(round(seconds * RATE)) / RATE
    tones = (
        np.sin(2 * np.pi * 180 * t)
        + 0.6 * np.sin(2 * np.pi * 540 * t + 0.7)
        + 0.3 * np.sin(2 * np.pi * 1210 * t)
    )
    envelope = 0.55 + 0.45 * np.sin(2 * np.pi * 4 * t) ** 2
    return (0.17 * tones * envelope).astype(np.float32)


def stereo(mono: np.ndarray) -> np.ndarray:
    return np.stack([mono, mono * 0.9], axis=1)


# ---------- o perfil e a redução de ruído ----------


def test_the_profile_of_white_noise_reports_the_level_per_third_octave_band():
    noise = white_noise(1.0, -45.0)
    spectrum = noise_spectrum(stereo(noise), RATE)
    levels = dict(band_levels(spectrum))
    assert (
        min(levels) == 100.0 and max(levels) == 16000.0
    )  # as bandas de 100 Hz a 16 kHz, todas abaixo de Nyquist
    # ruído branco: a banda de um terço de oitava carrega a fração da potência que cabe nela (largura de 23% da frequência)
    expected = -45.0 + 10 * math.log10((2 ** (1 / 6) - 2 ** (-1 / 6)) * 1000 / (RATE / 2))
    assert levels[1000.0] == pytest.approx(expected, abs=1.0)


def test_a_tone_shows_up_in_its_band_at_its_level():
    t = np.arange(RATE) / RATE
    tone = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    levels = dict(band_levels(noise_spectrum(tone, RATE)))
    assert levels[1000.0] == pytest.approx(db(0.5 / math.sqrt(2)), abs=0.3)  # -9 dBFS RMS
    assert levels[250.0] < levels[1000.0] - 40


def test_a_noise_profile_shorter_than_a_window_is_refused_with_the_reason():
    with pytest.raises(ValueError, match="use pelo menos"):
        noise_spectrum(white_noise(0.02, -45.0), RATE)


def test_twelve_db_of_reduction_takes_at_least_ten_db_off_the_noise_and_keeps_the_voice():
    quiet = round(1.5 * RATE)
    speech = voice(6.0)
    speech[:quiet] = 0
    noisy = stereo(speech + white_noise(6.0, -45.0))
    profile = noise_spectrum(noisy[round(0.2 * RATE) : round(1.4 * RATE)], RATE)
    cleaned = reduce_noise(noisy, profile, reduction_db=12.0, sensitivity=6.0, smoothing_bands=3)
    assert cleaned.shape == noisy.shape and cleaned.dtype == np.float32
    window = slice(round(0.3 * RATE), quiet)
    drop = db(rms(noisy[window, 0])) - db(rms(cleaned[window, 0]))
    assert drop >= 10.0
    assert drop == pytest.approx(12.0, abs=0.5)  # entrega a redução pedida, e não só "mais que 10"
    assert abs(db(rms(cleaned[quiet:, 0])) - db(rms(noisy[quiet:, 0]))) < 0.2  # a fala fica onde estava


@pytest.mark.parametrize("reduction", [6.0, 24.0])
def test_the_measured_drop_follows_the_requested_reduction(reduction):
    quiet = round(1.5 * RATE)
    noisy = stereo(white_noise(3.0, -45.0))
    profile = noise_spectrum(noisy[:quiet], RATE)
    cleaned = reduce_noise(noisy, profile, reduction_db=reduction)
    drop = db(rms(noisy[quiet:, 0])) - db(rms(cleaned[quiet:, 0]))
    assert drop == pytest.approx(reduction, abs=0.7)


def test_a_clean_recording_changes_by_less_than_half_a_db_even_with_a_profile_of_silence():
    speech = stereo(voice(4.0))
    profile = noise_spectrum(stereo(white_noise(1.0, -80.0)), RATE)
    cleaned = reduce_noise(speech, profile, reduction_db=12.0)
    assert abs(db(rms(cleaned)) - db(rms(speech))) < 0.5


def test_no_reduction_gives_the_signal_back_untouched_and_the_input_never_changes():
    noisy = stereo(white_noise(1.0, -45.0))
    before = noisy.copy()
    profile = noise_spectrum(noisy, RATE)
    assert reduce_noise(noisy, profile, reduction_db=0.0) is noisy
    reduce_noise(noisy, profile, reduction_db=12.0)
    assert np.array_equal(noisy, before)


def test_the_channels_open_together_so_the_stereo_image_of_a_voice_does_not_move():
    speech = voice(3.0)
    noisy = np.stack([speech + white_noise(3.0, -45.0, 1), 0.5 * speech + white_noise(3.0, -45.0, 2)], axis=1)
    profile = noise_spectrum(
        noisy[: RATE // 2], RATE
    )  # o começo é fala também: o que importa é a relação entre canais
    cleaned = reduce_noise(noisy, profile, reduction_db=12.0)
    ratio_in = rms(noisy[:, 1]) / rms(noisy[:, 0])
    ratio_out = rms(cleaned[:, 1]) / rms(cleaned[:, 0])
    assert ratio_out == pytest.approx(ratio_in, rel=0.1)


def test_a_signal_shorter_than_one_window_still_comes_back_with_the_same_length():
    short = stereo(white_noise(FFT_SIZE / RATE / 2, -45.0))
    profile = noise_spectrum(stereo(white_noise(0.5, -45.0)), RATE)
    assert reduce_noise(short, profile, reduction_db=12.0).shape == short.shape


def test_the_quietest_window_finds_the_pause_and_the_automatic_profile_needs_a_real_pause():
    speech = voice(6.0)
    speech[RATE * 2 : RATE * 3] = 0
    noisy = stereo(speech + white_noise(6.0, -50.0))
    first, last = quietest_window(noisy, RATE, 0.5)
    assert 2.0 <= first and last <= 3.0 + 0.01
    assert quiet_pause_window(noisy, RATE, 0.5) == (first, last)
    # um tom contínuo (sem pausa) não tem trecho só de ruído: o perfil automático se recusa, em vez de tratar o tom como chiado
    t = np.arange(6 * RATE) / RATE
    steady = stereo((0.3 * np.sin(2 * np.pi * 300 * t)).astype(np.float32))
    assert quiet_pause_window(steady, RATE, 0.5) is None
    # e uma gravação mais curta que a janela também não tem de onde tirar o perfil
    assert quiet_pause_window(noisy[: RATE // 4], RATE, 0.5) is None


# ---------- o estágio de amostras: intervalo e emenda ----------


def test_a_sample_effect_with_an_interval_changes_only_the_interval_and_blends_the_seams():
    noisy = stereo(white_noise(4.0, -40.0))
    profile = noise_spectrum(noisy, RATE)
    effect = parse_effect({"type": "noise_reduction", "reduction_db": 30, "start": 1.0, "end": 3.0})
    result = apply_sample_effect(SampleRequest(effect, noisy, RATE, Measure(noise=profile)))
    assert np.array_equal(result[: RATE - 10], noisy[: RATE - 10])  # antes da emenda: intacto
    assert np.array_equal(result[3 * RATE + 10 :], noisy[3 * RATE + 10 :])  # depois dela: intacto
    inside = slice(round(1.2 * RATE), round(2.8 * RATE))
    assert db(rms(result[inside, 0])) < db(rms(noisy[inside, 0])) - 20
    # a emenda não tem degrau: o maior salto entre amostras vizinhas não passa do que o ruído já tinha
    assert np.abs(np.diff(result[:, 0])).max() <= np.abs(np.diff(noisy[:, 0])).max() * 1.01


def test_the_repair_effect_owns_its_interval_and_refuses_a_stretch_longer_than_128_samples():
    t = np.arange(RATE) / RATE
    tone = (0.4 * np.sin(2 * np.pi * 220 * t) + 0.2 * np.sin(2 * np.pi * 660 * t)).astype(np.float32)
    broken = tone.copy()
    broken[20000:20064] = 0.9
    effect = parse_effect({"type": "repair", "start": 20000 / RATE, "end": 20064 / RATE})
    fixed = apply_sample_effect(SampleRequest(effect, stereo(broken), RATE))
    assert rms(fixed[20000:20064, 0] - tone[20000:20064]) < 0.01 * rms(
        broken[20000:20064] - tone[20000:20064]
    )
    assert np.array_equal(fixed[:20000, 0], broken[:20000])  # fora do trecho, nada muda
    with pytest.raises(ValueError, match="no máximo 128"):
        parse_effect({"type": "repair", "start": 1.0, "end": 1.01})
    with pytest.raises(ValueError, match="informe `start` e `end`"):
        parse_effect({"type": "repair"})


# ---------- reparar ----------


def test_repair_rebuilds_a_gap_from_the_wave_around_it_much_better_than_a_straight_line():
    t = np.arange(RATE) / RATE
    tone = (
        0.4 * np.sin(2 * np.pi * 180 * t)
        + 0.25 * np.sin(2 * np.pi * 540 * t + 0.7)
        + 0.1 * np.sin(2 * np.pi * 1210 * t)
    ).astype(np.float32)
    for width in (16, 64, 128):
        broken = tone.copy()
        broken[20000 : 20000 + width] = np.random.default_rng(width).uniform(-0.8, 0.8, width)
        fixed = repair_interval(broken, 20000, 20000 + width)
        gap = slice(20000, 20000 + width)
        line = np.linspace(broken[19999], broken[20000 + width], width)
        assert rms(fixed[gap] - tone[gap]) < 0.2 * rms(line - tone[gap])
        assert np.array_equal(fixed[:20000], tone[:20000]) and np.array_equal(
            fixed[20000 + width :], tone[20000 + width :]
        )
        assert broken[gap].std() > 0.1  # a entrada não foi mexida


def test_repair_works_per_channel_at_the_edges_of_the_signal_and_in_silence():
    t = np.arange(8000) / RATE
    tone = (0.5 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    both = np.stack([tone, -tone], axis=1)
    broken = both.copy()
    broken[0:20] = 1.0  # o trecho começa no primeiro sample: só há som de um lado
    fixed = repair_interval(broken, 0, 20)
    assert rms(fixed[:20, 0] - tone[:20]) < 0.05 and rms(fixed[:20, 1] + tone[:20]) < 0.05
    silent = np.zeros((4000, 2), dtype=np.float32)
    assert np.array_equal(repair_interval(silent, 100, 160), silent)  # contexto mudo: continua mudo
    assert repair_interval(tone, 5, 5) is not tone  # trecho vazio: cópia igual
    assert np.array_equal(repair_interval(tone, 5, 5), tone)


# ---------- truncar silêncio ----------


def test_silences_are_runs_below_the_threshold_longer_than_the_minimum_duration():
    rate = 16000
    tone = 0.3 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate)
    gap = np.zeros(2 * rate)
    short = np.zeros(rate // 4)  # 0,25 s: abaixo da duração mínima
    signal = np.concatenate([tone, gap, tone, short, tone, gap]).astype(np.float32)
    found = find_silences(signal, rate, threshold_db=-40.0, min_duration=0.5)
    assert found == [(1.0, 3.0), (5.25, 7.25)]  # o silêncio que vai até o fim também conta
    assert find_silences(signal, rate, threshold_db=-40.0, min_duration=2.5) == []


def test_truncating_two_second_pauses_to_half_a_second_removes_the_middle_of_each():
    rate = 16000
    tone = 0.3 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate)
    signal = np.concatenate([tone, np.zeros(2 * rate), tone, np.zeros(2 * rate), tone]).astype(np.float32)
    silences = find_silences(signal, rate, -40.0, 0.5)
    removed = plan_truncation(signal, rate, silences, "truncate", 0.5, 0.5, 50.0)
    assert len(removed) == 2
    for (start, end), (silence_start, silence_end) in zip(removed, silences, strict=True):
        assert end - start == pytest.approx(1.5, abs=0.01)  # 2 s - 0,5 s
        assert silence_start + 0.2 < start < end < silence_end - 0.2  # sobra um respiro de cada lado
    assert signal.size / rate - sum(end - start for start, end in removed) == pytest.approx(
        7.0 - 3.0, abs=0.02
    )


def test_the_two_modes_keep_the_time_the_audacity_manual_describes():
    assert kept_length(2.0, "truncate", 0.5, 0.5, 50.0) == 0.5
    assert kept_length(0.4, "truncate", 0.3, 1.0, 50.0) == 0.4  # nunca mais que a própria pausa
    assert kept_length(2.0, "compress", 0.5, 0.5, 50.0) == pytest.approx(
        0.5 + 1.5 * 0.5
    )  # a mínima + metade do excesso
    assert kept_length(2.0, "compress", 0.5, 0.5, 0.0) == 0.5  # 0%: o mesmo que truncar para a mínima
    assert kept_length(2.0, "compress", 0.5, 0.5, 100.0) == 2.0  # 100%: não muda nada


def test_with_a_frame_grid_what_is_kept_before_each_cut_is_a_whole_number_of_frames():
    rate = 16000
    tone = 0.3 * np.sin(2 * np.pi * 440 * np.arange(round(1.37 * rate)) / rate)
    signal = np.concatenate([tone, np.zeros(2 * rate), tone, np.zeros(round(1.8 * rate)), tone]).astype(
        np.float32
    )
    grid = 1 / 30
    removed = plan_truncation(
        signal, rate, find_silences(signal, rate, -40.0, 0.5), "truncate", 0.5, 0.5, 50.0, grid
    )
    cursor = 0.0
    for start, end in removed:
        frames = (start - cursor) / grid
        assert frames == pytest.approx(round(frames), abs=0.03)
        cursor = end


def test_the_cut_points_land_on_the_quietest_sample_so_the_seam_does_not_click():
    rate = 16000
    noise = (np.random.default_rng(3).standard_normal(3 * rate) * 0.01).astype(
        np.float32
    )  # chiado a -40 dBFS
    signal = np.concatenate([0.3 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate), noise]).astype(
        np.float32
    )
    # o limiar é de pico (como o do Audacity): o chiado de -40 dB RMS chega a -28 dB de pico, então -20 dB é o limiar certo
    removed = plan_truncation(
        signal, rate, find_silences(signal, rate, -20.0, 0.5), "truncate", 0.5, 0.5, 50.0
    )
    ((start, end),) = removed
    for instant in (start, end):
        around = np.abs(signal[round(instant * rate) - 40 : round(instant * rate) + 40])
        assert (
            abs(signal[round(instant * rate)]) <= np.sort(around)[3]
        )  # entre as 4 menores amostras num raio de 2,5 ms
