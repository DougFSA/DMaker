"""Os analisadores de áudio como funções puras: sinais gerados no teste, com a resposta conhecida de antemão.

Cada critério de aceite do card é uma conta, não uma comparação com uma execução anterior: o tom de 1 kHz tem o pico na
divisão de 1 kHz, o estouro inserido em 0,40 s começa em 0,40 s, a faixa de 120 BPM tem uma batida a cada 0,5 s.
"""

from __future__ import annotations

import numpy as np
import pytest

from dmaker.analysis import ANALYZER_CLASSES, Signal, analyzer_catalog, parse_analyzer
from dmaker.analysis.analyzers.beats import envelope, pick_beats
from dmaker.analysis.analyzers.clipping import clipped_regions
from dmaker.analysis.analyzers.contrast import WCAG_CONTRAST_DB, contrast_db
from dmaker.analysis.analyzers.spectrum import (
    autocorrelation,
    cepstrum,
    decimate_curve,
    enhanced_autocorrelation,
    lag_peak,
    spectrum_curve,
)
from dmaker.analysis.fft import (
    WINDOW_NAMES,
    amplitude_spectrum_db,
    averaged_power,
    bin_frequencies,
    frame_count,
    peak_frequency,
    window_coefficients,
    windowed_frames,
)
from dmaker.analysis.notes import note_for
from dmaker.analysis.plot import png_bytes, spectrum_image
from dmaker.analysis.signal import DB_FLOOR, frame_levels_db, linear_to_db, rms_db

RATE = 48000


def tone(hz: float, seconds: float, amp: float = 0.5, rate: int = RATE, phase: float = 0.0) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return amp * np.sin(2 * np.pi * hz * t + phase)


def mono(samples: np.ndarray, rate: int = RATE) -> Signal:
    return Signal(samples.reshape(-1, 1).astype(np.float32), rate)


def rms_amplitude(level_db: float) -> float:
    """A amplitude de um seno cujo RMS é `level_db` dBFS."""
    return 10 ** (level_db / 20) * np.sqrt(2)


# ---------- a FFT e as janelas (o que o espectrograma reaproveita) ----------


@pytest.mark.parametrize("name", WINDOW_NAMES)
def test_every_window_is_nonnegative_and_peaks_in_the_middle(name):
    window = window_coefficients(name, 1024)
    assert window.shape == (1024,)
    assert window.min() >= -1e-9
    assert int(np.argmax(window)) in (512, 511, 513) or name == "rectangular"


def test_hann_window_matches_the_definition():
    window = window_coefficients("hann", 8)
    assert window[0] == pytest.approx(0.0)
    assert window[4] == pytest.approx(1.0)
    assert window[2] == pytest.approx(0.5)


def test_unknown_window_and_bad_fft_size_say_what_is_valid():
    with pytest.raises(ValueError, match="janela desconhecida"):
        window_coefficients("triangulo", 256)
    with pytest.raises(ValueError, match="potência de dois"):
        parse_analyzer("spectrum", {"size": 1000})


def test_frames_cover_the_signal_and_a_short_signal_still_gives_one_frame():
    window = window_coefficients("rectangular", 256)
    assert frame_count(1000, 256) == 1 + int(np.ceil((1000 - 256) / 128))
    assert windowed_frames(np.ones(1000), 256, window).shape[1] == 256
    assert windowed_frames(np.ones(10), 256, window).shape == (1, 256)
    assert frame_count(10, 256) == 1


def test_frames_in_batches_equal_the_whole_matrix():
    window = window_coefficients("hann", 256)
    samples = np.random.default_rng(1).standard_normal(5000)
    whole = windowed_frames(samples, 256, window)
    parts = np.vstack(
        [windowed_frames(samples, 256, window, None, first, 7) for first in range(0, len(whole), 7)]
    )
    assert np.allclose(whole, parts)


@pytest.mark.parametrize("window_name", ["hann", "hamming", "blackman", "rectangular"])
def test_a_tone_in_the_middle_of_a_bin_reads_its_own_amplitude(window_name):
    size = 2048
    centre = 43 * RATE / size  # exatamente no centro da divisão 43
    window = window_coefficients(window_name, size)
    power = averaged_power(tone(centre, 1.0, 0.5), size, window)
    levels = amplitude_spectrum_db(power, window)
    assert int(np.argmax(levels)) == 43
    assert levels[43] == pytest.approx(20 * np.log10(0.5), abs=0.05)


def test_one_khz_tone_peaks_at_the_one_khz_bin():
    """Critério do card: o pico do espectro de um tom de 1 kHz cai na divisão de 1 kHz."""
    size = 4096
    frequencies, levels = spectrum_curve(tone(1000.0, 2.0, 0.5), RATE, size, "hann")
    bin_hz = RATE / size
    peak_bin, peak_hz = peak_frequency(levels, frequencies)
    assert peak_bin == round(1000.0 / bin_hz)
    assert abs(frequencies[peak_bin] - 1000.0) <= bin_hz / 2
    assert peak_hz == pytest.approx(1000.0, abs=1.0)  # refinado entre divisões
    assert levels[peak_bin] > levels[peak_bin + 5] + 40


def test_averaged_power_of_noise_is_flat_and_stable():
    noise = np.random.default_rng(2).standard_normal(RATE * 2) * 0.1
    window = window_coefficients("hann", 1024)
    levels = amplitude_spectrum_db(averaged_power(noise, 1024, window), window)
    middle = levels[50:450]
    assert middle.std() < 1.5  # a média dos quadros alisa o ruído


# ---------- espectro, autocorrelação e cepstro ----------


def test_spectrum_analyzer_finds_the_tone_the_note_and_exports_csv():
    result = parse_analyzer("spectrum", {"size": 4096}).analyze(mono(tone(1000.0, 1.0, 0.5)))
    assert result.peak_hz == pytest.approx(1000.0, abs=1.0)
    assert result.peak_bin == 85
    assert result.peak_db == pytest.approx(20 * np.log10(0.5), abs=1.5)
    assert result.peak_note is not None and result.peak_note.startswith("Si5")
    lines = result.table().splitlines()
    assert lines[0] == "frequencia_hz,nivel_db"
    assert len(lines) == 4096 // 2 + 1 + 1
    frequency, level = lines[1 + 85].split(",")
    assert float(frequency) == pytest.approx(85 * RATE / 4096, abs=1e-3)
    assert float(level) == pytest.approx(result.levels_db[85], abs=1e-3)
    assert result.peaks[0].frequency == pytest.approx(result.peak_hz, abs=0.01)  # o pico da lista é refinado como o principal
    assert all(peak.frequency >= 20 for peak in result.peaks)  # o piso de baixa frequência não é um pico


def test_spectrum_json_is_compact_and_keeps_the_peak():
    result = parse_analyzer("spectrum", {"size": 8192}).analyze(mono(tone(3000.0, 1.0, 0.5)))
    data = result.to_dict(limit=300)
    assert len(data["curve"]["frequencies"]) == 300
    assert data["curve"]["points_total"] == 4097
    assert max(data["curve"]["levels_db"]) == pytest.approx(result.peak_db, abs=0.01)
    assert "frequencies" not in data and "levels_db" not in data
    assert len(result.to_dict("full")["curve"]["frequencies"]) == 4097


def test_decimation_keeps_a_narrow_peak():
    frequencies = [float(i) for i in range(2000)]
    levels = [-90.0] * 2000
    levels[1234] = -3.0
    kept_frequencies, kept_levels = decimate_curve(frequencies, levels, 100)
    assert len(kept_frequencies) == 100
    assert -3.0 in kept_levels
    assert kept_frequencies[kept_levels.index(-3.0)] == 1234.0


@pytest.mark.parametrize("algorithm", ["autocorrelation", "enhanced_autocorrelation"])
def test_autocorrelation_finds_the_pitch(algorithm):
    result = parse_analyzer("spectrum", {"algorithm": algorithm, "size": 2048}).analyze(
        mono(tone(200.0, 1.0, 0.5))
    )
    assert result.peak_hz == pytest.approx(200.0, rel=0.01)


def test_enhanced_autocorrelation_removes_the_subharmonic_peak():
    """Um tom de 200 Hz também correlaciona no atraso de 100 Hz (o dobro do período): a aprimorada o tira."""
    values = autocorrelation(tone(200.0, 1.0, 0.5), 2048, "hann")
    period = RATE / 200.0
    assert values[int(round(2 * period))] > 0.4  # o dobro do atraso correlaciona quase tanto quanto o atraso
    enhanced = enhanced_autocorrelation(values)
    assert enhanced[int(round(2 * period))] < 0.6 * enhanced[int(round(period))]
    assert lag_peak(values, True) == pytest.approx(period, abs=2.0)  # a janela puxa o pico um pouco para trás


def test_cepstrum_peaks_at_the_period_of_a_harmonic_sound():
    pulses = np.zeros(RATE)
    pulses[::240] = 1.0  # 200 Hz de pulsos: rico em harmônicos regulares
    values = cepstrum(pulses, 2048, "hann")
    lag = lag_peak(values, False, min_lag=24)
    assert lag is not None and RATE / lag == pytest.approx(200.0, rel=0.02)


def test_note_names_and_cents():
    assert note_for(440.0).name == "Lá4" and note_for(440.0).cents == pytest.approx(0.0, abs=1e-6)
    assert note_for(261.63).name == "Dó4"
    assert note_for(466.16).name == "Lá#4"
    flat = note_for(430.0)
    assert flat is not None and flat.name == "Lá4" and flat.cents < -30
    assert note_for(1000.0).name == "Si5"
    assert note_for(0.0) is None and note_for(-5.0) is None
    assert note_for(880.0, a4=432.0).cents > 0  # outra afinação muda a nota mais próxima


# ---------- medidas de nível ----------


def test_db_helpers_floor_the_silence():
    assert linear_to_db(0.0) == DB_FLOOR
    assert linear_to_db(1.0) == pytest.approx(0.0)
    assert rms_db(np.zeros(100)) == DB_FLOOR
    assert rms_db(tone(440.0, 1.0, 1.0)) == pytest.approx(-3.01, abs=0.01)


def test_rms_analyzer_measures_each_channel():
    left, right = tone(440.0, 1.0, 0.5), tone(440.0, 1.0, 0.25)
    signal = Signal(np.column_stack([left, right]).astype(np.float32), RATE)
    result = parse_analyzer("rms", {}).analyze(signal)
    assert [c.channel for c in result.channels] == [1, 2]
    assert result.channels[0].rms_db == pytest.approx(-9.03, abs=0.02)
    assert result.channels[1].rms_db == pytest.approx(-15.05, abs=0.02)
    assert result.channels[0].peak_db == pytest.approx(-6.02, abs=0.02)
    assert result.overall_peak_db == pytest.approx(-6.02, abs=0.02)
    assert result.windows == []


def test_rms_in_windows_follows_the_level_over_time():
    samples = np.concatenate([tone(440.0, 1.0, 0.5), tone(440.0, 1.0, 0.05)])
    result = parse_analyzer("rms", {"window": 0.5}).analyze(mono(samples))
    levels = [item["rms_db"] for item in result.windows]
    assert len(levels) == 4
    assert levels[0] == pytest.approx(-9.03, abs=0.05) and levels[3] == pytest.approx(-29.03, abs=0.05)
    assert result.windows[2]["start"] == pytest.approx(1.0)
    assert result.table().splitlines()[0] == "tempo_s,rms_db"


def test_frame_levels_db_drops_the_remainder():
    assert frame_levels_db(np.ones((1000, 1)), RATE, 0.01).shape == (2,)
    assert frame_levels_db(np.ones((10, 1)), RATE, 0.01).shape == (0,)


# ---------- contraste ----------


def contrast_signal(background_db: float) -> Signal:
    speech = tone(300.0, 1.0, rms_amplitude(-20.0))
    background = tone(120.0, 1.0, rms_amplitude(background_db))
    return mono(np.concatenate([speech, background]))


CONTRAST_WINDOWS = {
    "foreground_start": 0.0,
    "foreground_end": 1.0,
    "background_start": 1.0,
    "background_end": 2.0,
}


def test_contrast_of_speech_at_minus_20_over_background_at_minus_45_is_25_and_passes():
    result = parse_analyzer("contrast", CONTRAST_WINDOWS).analyze(contrast_signal(-45.0))
    assert result.foreground_db == pytest.approx(-20.0, abs=0.1)
    assert result.background_db == pytest.approx(-45.0, abs=0.1)
    assert result.difference_db == pytest.approx(25.0, abs=0.5)
    assert result.passes and not result.warnings


def test_contrast_with_background_at_minus_30_fails_with_the_warning():
    result = parse_analyzer("contrast", CONTRAST_WINDOWS).analyze(contrast_signal(-30.0))
    assert result.difference_db == pytest.approx(10.0, abs=0.5)
    assert not result.passes
    assert "reprova" in result.summary
    assert result.warnings and "10" in result.warnings[0]


def test_contrast_needs_both_intervals_and_checks_the_signal():
    with pytest.raises(ValueError, match="background_start"):
        parse_analyzer("contrast", {"foreground_start": 0, "foreground_end": 1}).analyze(
            contrast_signal(-45.0)
        )
    with pytest.raises(ValueError, match="fora do som"):
        parse_analyzer(
            "contrast", {**CONTRAST_WINDOWS, "background_start": 5.0, "background_end": 6.0}
        ).analyze(contrast_signal(-45.0))
    assert contrast_db(tone(300.0, 1.0, 0.5), tone(300.0, 1.0, 0.05)) == pytest.approx(20.0, abs=0.01)
    assert WCAG_CONTRAST_DB == 20.0


# ---------- achar clipping ----------


def clipped_signal(spans: list[tuple[float, float]], rate: int = RATE, seconds: float = 2.0) -> np.ndarray:
    samples = tone(220.0, seconds, 0.4, rate)
    for start, end in spans:
        samples[int(start * rate) : int(end * rate)] = 1.0
    return samples


def test_find_clipping_finds_the_three_clipped_stretches_within_one_millisecond():
    """Critério do card: 3 trechos estourados, com início e fim certos (±1 ms)."""
    spans = [(0.400, 0.4005), (1.000, 1.002), (1.500, 1.5008)]
    result = parse_analyzer("clipping", {}).analyze(mono(clipped_signal(spans)))
    assert len(result.regions) == 3
    for region, (start, end) in zip(result.regions, spans, strict=True):
        assert region.start == pytest.approx(start, abs=0.001)
        assert region.end == pytest.approx(end, abs=0.001)
        assert region.channel == 1
    assert result.clipped_samples == sum(int(e * RATE) - int(s * RATE) for s, e in spans)
    assert "3 trecho" in result.summary


def test_a_lone_sample_at_the_ceiling_does_not_count_but_three_do():
    samples = clipped_signal([])
    samples[1000] = 1.0  # uma amostra só
    samples[5000:5002] = 1.0  # duas
    assert parse_analyzer("clipping", {}).analyze(mono(samples)).regions == []
    samples[9000:9003] = -1.0  # três, e negativas
    result = parse_analyzer("clipping", {}).analyze(mono(samples))
    assert [(r.start, r.end) for r in result.regions] == [pytest.approx((9000 / RATE, 9003 / RATE), abs=1e-6)]


def test_clipped_regions_merge_over_short_gaps_and_split_over_long_ones():
    mask = np.zeros(100, dtype=bool)
    mask[10:15] = True
    mask[16:20] = True  # um vão de 1 amostra: o mesmo trecho
    mask[40:50] = True  # um vão de 20: outro trecho
    assert clipped_regions(mask, 3, 3) == [(10, 19), (40, 49)]
    assert clipped_regions(mask, 3, 1) == [(10, 14), (16, 19), (40, 49)]
    assert clipped_regions(mask, 6, 3) == [
        (40, 49)
    ]  # nenhuma das duas sequências curtas abre um trecho sozinha
    assert clipped_regions(np.zeros(10, dtype=bool), 3, 3) == []


def test_clipping_is_reported_per_channel_and_markers_merge_the_channels():
    left, right = clipped_signal([(0.5, 0.51)]), clipped_signal([(0.505, 0.52), (1.2, 1.21)])
    signal = Signal(np.column_stack([left, right]).astype(np.float32), RATE)
    result = parse_analyzer("clipping", {}).analyze(signal)
    assert [r.channel for r in result.regions] == [1, 2, 2]
    markers = result.markers()
    assert (
        len(markers) == 2 and markers[0].start == pytest.approx(0.5) and markers[0].end == pytest.approx(0.52)
    )
    assert markers[1].text == "Clipping 2"


def test_clipping_sees_the_full_scale_of_a_sixteen_bit_file_and_honours_the_ceiling():
    pcm = clipped_signal([]).astype(np.float32)
    pcm[2000:2010] = 32767 / 32768  # o maior valor de um WAV de 16 bits
    assert len(parse_analyzer("clipping", {}).analyze(mono(pcm)).regions) == 1
    quiet = np.clip(tone(220.0, 1.0, 0.95), -0.9, 0.9)
    assert parse_analyzer("clipping", {}).analyze(mono(quiet)).regions == []
    assert len(parse_analyzer("clipping", {"ceiling_db": -1.0}).analyze(mono(quiet)).regions) >= 1


# ---------- marcar sons ----------


def sound_signal() -> Signal:
    """1 s de silêncio, 2 s de som, 1,5 s de silêncio, 0,2 s de estalo, 1 s de silêncio, 1 s de som."""
    parts = [
        np.zeros(RATE),
        tone(300.0, 2.0, 0.3),
        np.zeros(int(1.5 * RATE)),
        tone(300.0, 0.2, 0.3),
        np.zeros(RATE),
        tone(300.0, 1.0, 0.3),
    ]
    return mono(np.concatenate(parts))


def test_label_sounds_marks_the_regions_above_the_threshold():
    result = parse_analyzer("sounds", {"min_silence": 1.0, "min_sound": 0.5}).analyze(sound_signal())
    assert [(round(r.start, 2), round(r.end, 2)) for r in result.regions] == [(1.0, 3.0), (5.7, 6.7)]
    markers = result.markers()
    assert markers[0].end is not None and markers[0].text == "Som 1"


def test_label_sounds_merges_close_sounds_and_drops_short_ones():
    merged = parse_analyzer("sounds", {"min_silence": 2.0, "min_sound": 0.1}).analyze(sound_signal())
    assert [(round(r.start, 2), round(r.end, 2)) for r in merged.regions] == [(1.0, 6.7)]
    kept_all = parse_analyzer("sounds", {"min_silence": 0.5, "min_sound": 0.1}).analyze(sound_signal())
    assert len(kept_all.regions) == 3  # o estalo de 0,2 s conta quando a duração mínima o permite


def test_label_sounds_positions_and_silences():
    before = parse_analyzer("sounds", {"position": "start"}).analyze(sound_signal()).markers()
    after = parse_analyzer("sounds", {"position": "end"}).analyze(sound_signal()).markers()
    assert [m.end for m in before] == [None, None] and [round(m.start, 2) for m in before] == [1.0, 5.7]
    assert [round(m.start, 2) for m in after] == [3.0, 6.7]
    silences = parse_analyzer("sounds", {"mode": "silences", "min_silence": 1.0, "text": "Pausa"}).analyze(
        sound_signal()
    )
    assert [(round(r.start, 2), round(r.end, 2)) for r in silences.regions] == [(0.0, 1.0), (3.0, 5.7)]
    assert silences.markers()[1].text == "Pausa 2"


def test_label_sounds_threshold_changes_what_is_a_sound():
    loud_only = mono(np.concatenate([tone(300.0, 1.0, 0.5), tone(300.0, 1.0, 0.01), tone(300.0, 1.0, 0.5)]))
    loose = parse_analyzer("sounds", {"threshold_db": -60.0, "min_silence": 0.2}).analyze(loud_only)
    strict = parse_analyzer("sounds", {"threshold_db": -20.0, "min_silence": 0.2}).analyze(loud_only)
    assert len(loose.regions) == 1 and len(strict.regions) == 2


# ---------- achar batidas ----------


def click_track(bpm: float = 120.0, seconds: float = 8.0, offset: float = 0.25) -> np.ndarray:
    """Cliques de 5 ms (um seno de 1 kHz) a cada 60/bpm segundos, a partir de `offset`."""
    samples = np.zeros(int(seconds * RATE))
    click = tone(1000.0, 0.005, 0.8) * np.hanning(int(0.005 * RATE))
    step = 60.0 / bpm
    for k in range(int((seconds - offset) / step)):
        start = int((offset + k * step) * RATE)
        samples[start : start + len(click)] += click
    return samples


def test_beat_finder_marks_a_beat_every_half_second_on_a_120_bpm_track():
    """Critério do card: 120 BPM marca uma batida a cada 0,5 s (±20 ms)."""
    result = parse_analyzer("beats", {}).analyze(mono(click_track()))
    assert len(result.beats) == 15
    intervals = np.diff(result.beats)
    assert np.all(np.abs(intervals - 0.5) <= 0.02)
    assert result.beats[0] == pytest.approx(
        0.2525, abs=0.004
    )  # o centro do clique de 5 ms que começa em 0,25 s
    assert result.bpm == pytest.approx(120.0, abs=2.0)
    assert result.markers()[0].text == "Batida 1" and result.markers()[0].end is None


def test_beat_finder_handles_other_tempos_and_close_double_clicks():
    slow = parse_analyzer("beats", {}).analyze(mono(click_track(bpm=90.0)))
    assert slow.bpm == pytest.approx(90.0, abs=2.0)
    doubled = click_track()
    doubled += np.roll(doubled, int(0.1 * RATE))  # um segundo clique 100 ms depois de cada um
    default = parse_analyzer("beats", {}).analyze(mono(doubled))
    assert len(default.beats) == 15  # a distância mínima de 0,25 s junta o par
    loose = parse_analyzer("beats", {"min_distance": 0.05, "smoothing": 0.005}).analyze(mono(doubled))
    assert len(loose.beats) == 30


def test_beat_finder_threshold_ignores_weak_hits_and_silence_gives_none():
    track = click_track()
    track[int(0.74 * RATE) : int(0.76 * RATE)] *= 0.1  # o clique de 0,75 s fica fraco
    strict = parse_analyzer("beats", {"threshold_percent": 50.0}).analyze(mono(track))
    assert len(strict.beats) == 14
    assert parse_analyzer("beats", {}).analyze(mono(np.zeros(RATE))).beats == []
    levels, hop = envelope(np.zeros(100), RATE, 0.02)
    assert pick_beats(levels, 0.1, 5) == [] and hop == 240


# ---------- exportar amostras ----------


def test_sample_export_limits_and_converts_to_db():
    samples = np.column_stack([np.linspace(-1, 1, 1000), np.linspace(1, -1, 1000)]).astype(np.float32)
    result = parse_analyzer("samples", {"limit": 5}).analyze(Signal(samples, RATE))
    assert result.count == 5 and result.total_samples == 1000 and result.truncated
    assert result.values[0] == [-1.0, 1.0]
    lines = result.table().splitlines()
    assert lines[0] == "amostra,tempo_s,canal_1,canal_2" and len(lines) == 6
    assert lines[2].split(",")[0] == "1" and float(lines[2].split(",")[1]) == pytest.approx(
        1 / RATE, abs=1e-6
    )
    in_db = parse_analyzer("samples", {"limit": 3, "unit": "db"}).analyze(Signal(samples, RATE))
    assert in_db.values[0][0] == pytest.approx(0.0, abs=1e-6)
    assert result.table("\t").splitlines()[0].count("\t") == 3
    assert not parse_analyzer("samples", {"limit": 5000}).analyze(Signal(samples, RATE)).truncated


# ---------- registro e catálogo ----------


def test_the_seven_audacity_analyzers_are_registered():
    assert set(ANALYZER_CLASSES) == {"contrast", "clipping", "rms", "spectrum", "sounds", "beats", "samples"}
    for name, cls in ANALYZER_CLASSES.items():
        assert cls.model_fields["type"].default == name
        assert cls.label and cls.audacity_name and cls.summary


def test_catalog_describes_every_parameter_with_label_unit_and_range():
    catalog = analyzer_catalog()
    by_type = {item["type"]: item for item in catalog["analyzers"]}
    assert by_type["clipping"]["audacity_name"] == "Find Clipping"
    start = next(p for p in by_type["clipping"]["parameters"] if p["name"] == "start_threshold")
    assert (start["default"], start["minimum"], start["kind"]) == (3, 1, "integer")
    window = next(p for p in by_type["spectrum"]["parameters"] if p["name"] == "window")
    assert (
        window["kind"] == "choice" and "hann" in window["options"] and "blackman_harris" in window["options"]
    )
    assert by_type["beats"]["marks_by_default"] and by_type["beats"]["marker_group"] == "batidas"
    assert by_type["sounds"]["marker_group"] == "sons" and by_type["rms"]["marks"] is False
    assert by_type["spectrum"]["exports"] == ["csv", "png"]
    for item in catalog["analyzers"]:
        assert all(p["label"] for p in item["parameters"]), item["type"]
    assert {s["source"] for s in catalog["sources"]} >= {"timeline.N", "audio.music", "output", "file"}
    assert [a["type"] for a in analyzer_catalog("rms")["analyzers"]] == ["rms"]


def test_parse_analyzer_explains_a_bad_request_in_portuguese():
    with pytest.raises(ValueError, match="Analisador desconhecido"):
        parse_analyzer("wavelet", {})
    with pytest.raises(ValueError, match="start_threshold"):
        parse_analyzer("clipping", {"start_threshold": 0})
    with pytest.raises(ValueError, match="Parâmetros inválidos para beats"):
        parse_analyzer("beats", {"bpm": 120})


# ---------- o gráfico ----------


def test_spectrum_png_is_drawn_by_a_pure_function():
    frequencies, levels = spectrum_curve(tone(1000.0, 1.0, 0.5), RATE, 2048, "hann")
    image = spectrum_image(list(frequencies), list(levels), axis="log", width=640, height=320, title="1 kHz")
    assert image.size == (640, 320)
    colours = {image.getpixel((x, y)) for x in range(0, 640, 7) for y in range(0, 320, 7)}
    assert len(colours) > 3
    assert png_bytes(image)[:8] == b"\x89PNG\r\n\x1a\n"
    linear = spectrum_image(list(frequencies), list(levels), axis="linear", width=640, height=320)
    assert linear.tobytes() != image.tobytes()
    with pytest.raises(ValueError, match="mesmo tamanho"):
        spectrum_image([1.0, 2.0], [0.0])


def test_bin_frequencies_cover_zero_to_nyquist():
    frequencies = bin_frequencies(1024, RATE)
    assert frequencies[0] == 0.0 and frequencies[-1] == RATE / 2 and len(frequencies) == 513
