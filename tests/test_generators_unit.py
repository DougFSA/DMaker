"""Geradores de som sem ffmpeg: o registro, as contas puras de cada gerador, a spec e as operações do `edit_project`.

Os sinais saem dos próprios construtores e a medida é conta em numpy (FFT, Goertzel), então o que se espera vem da definição
do sinal e não de uma execução anterior. O som de verdade, passando pelo ffmpeg e pela mixagem, está em
`test_generators_integration.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.domain.audio_effects import effect_info
from dmaker.domain.edits import EditError
from dmaker.domain.generators import (
    GENERATOR_CLASSES,
    catalog,
    catalog_payload,
    normalized_params,
    parse_generator,
)
from dmaker.domain.generators.telephony import DTMF_FREQUENCIES, dtmf_pair
from dmaker.domain.spec import Project
from dmaker.filtergraph.generators import GeneratorRequest, build_generator, builder_types
from dmaker.filtergraph.generators.instruments import midi_to_hz
from dmaker.filtergraph.generators.rhythm import beat_positions
from dmaker.filtergraph.generators.samples import (
    conformed_values,
    read_sample_values,
    resampled,
)
from dmaker.filtergraph.generators.tones import bandlimited_square, db_to_linear, sweep_cycles
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.media.wavio import read_wav_float, write_wav_float
from dmaker.pipeline.edits import apply_edit
from dmaker.pipeline.generated_sounds import (
    GeneratedSoundRenderer,
    source_args,
    stereo_frames,
)

RATE = 48000


def build(name: str, seconds: float, resolve=None, **params) -> np.ndarray:
    request = GeneratorRequest(parse_generator(name, params), seconds, RATE, resolve)
    built = build_generator(request)
    assert isinstance(built, np.ndarray), f"{name} devolveu uma fonte do ffmpeg, esperava amostras"
    return built


def peak_db(samples: np.ndarray) -> float:
    return 20 * np.log10(float(np.max(np.abs(samples))))


def spectrum_peak_hz(samples: np.ndarray) -> float:
    windowed = samples * np.hanning(len(samples))
    magnitude = np.abs(np.fft.rfft(windowed))
    return float(np.argmax(magnitude) * RATE / len(samples))


def goertzel(samples: np.ndarray, frequency: float) -> float:
    """A potência de uma frequência pelo algoritmo de Goertzel (o decodificador de DTMF dos telefones)."""
    coefficient = 2 * np.cos(2 * np.pi * frequency / RATE)
    previous = previous2 = 0.0
    for value in samples:
        previous, previous2 = value + coefficient * previous - previous2, previous
    return previous2**2 + previous**2 - coefficient * previous * previous2


def decode_dtmf(samples: np.ndarray, keys: int) -> str:
    """Um dígito por fatia igual: o par (linha, coluna) de maior potência nas oito frequências do padrão."""
    rows, columns = (
        sorted({low for low, _ in DTMF_FREQUENCIES.values()}),
        sorted({high for _, high in DTMF_FREQUENCIES.values()}),
    )
    table = {pair: key for key, pair in DTMF_FREQUENCIES.items()}
    slot = len(samples) // keys
    out = []
    for position in range(keys):
        piece = samples[position * slot : (position + 1) * slot]
        low = max(rows, key=lambda hz: goertzel(piece, hz))
        high = max(columns, key=lambda hz: goertzel(piece, hz))
        out.append(table[(low, high)])
    return "".join(out)


# ---------- o registro ----------


def test_every_generator_class_has_a_builder_and_the_other_way_around():
    assert set(GENERATOR_CLASSES) == builder_types()


def test_the_catalog_lists_the_nine_audacity_generators():
    expected = {
        "tone",
        "chirp",
        "noise",
        "dtmf",
        "silence",
        "pluck",
        "risset_drum",
        "rhythm_track",
        "sample_data",
    }
    assert expected <= {info.type for info in catalog()}  # `<=`: os outros cards acrescentam os deles


def test_the_catalog_payload_gives_name_range_and_default_of_each_parameter():
    payload = catalog_payload("tone")
    (tone,) = payload["generators"]
    parameters = {item["name"]: item for item in tone["parameters"]}
    assert tone["audacity_name"] == "Tone"
    assert parameters["waveform"]["kind"] == "choice"
    assert parameters["waveform"]["options"] == ["sine", "square", "sawtooth", "square_bandlimited"]
    assert parameters["frequency_hz"]["default"] == 440.0
    assert (parameters["frequency_hz"]["minimum"], parameters["frequency_hz"]["maximum"]) == (1.0, 20000.0)
    assert json.dumps(payload)  # é JSON de verdade, igual na API, no MCP e na CLI


def test_an_unknown_generator_is_an_error_that_lists_the_known_ones():
    with pytest.raises(ValueError, match="desconhecido.*tone"):
        parse_generator("violino")
    with pytest.raises(ValueError, match="desconhecido"):
        catalog_payload("violino")


def test_a_parameter_out_of_range_names_the_generator_and_the_field():
    with pytest.raises(ValueError, match=r"gerador tone: frequency_hz"):
        parse_generator("tone", {"frequency_hz": 50000})


def test_normalized_params_complete_the_defaults_so_two_equal_requests_have_one_json():
    assert normalized_params("tone", {"frequency_hz": 1000}) == normalized_params(
        "tone", {"frequency_hz": 1000, "waveform": "sine", "amplitude_db": -2.0}
    )


# ---------- a spec ----------


def project_with(*sounds: dict, **audio) -> Project:
    return Project.model_validate(
        {
            "name": "gerados",
            "timeline": [],
            "output": {"preset": "audio/wav"},
            "audio": {"generated": list(sounds), **audio},
        }
    )


def test_a_project_without_generated_sounds_dumps_exactly_as_before():
    plain = Project.model_validate({"name": "x", "timeline": [], "output": {"preset": "audio/wav"}})
    assert "generated" not in json.loads(plain.to_bytes())["audio"]
    assert plain.to_bytes() == Project.model_validate(json.loads(plain.to_bytes())).to_bytes()


def test_a_generated_sound_keeps_the_completed_params_and_drops_the_default_pan():
    project = project_with({"generator": "tone", "params": {"frequency_hz": 1000}, "duration": 2})
    sound = project.audio.generated[0]
    assert sound.params == {"waveform": "sine", "frequency_hz": 1000.0, "amplitude_db": -2.0}
    dumped = json.loads(project.to_bytes())["audio"]["generated"][0]
    assert "pan" not in dumped and "effects" not in dumped


def test_a_generated_sound_needs_a_known_generator_and_valid_parameters():
    with pytest.raises(ValueError, match="audio.generated.*desconhecido"):
        project_with({"generator": "violino", "duration": 1})
    with pytest.raises(ValueError, match="audio.generated.*frequency_hz"):
        project_with({"generator": "tone", "params": {"frequency_hz": 0}, "duration": 1})
    with pytest.raises(ValueError, match="duration"):
        project_with({"generator": "silence", "duration": 0})


def test_the_effect_chain_is_valid_on_a_generated_sound_but_not_one_that_changes_its_duration():
    project_with(
        {"generator": "tone", "duration": 1, "effects": [{"type": "amplify", "gain_db": -3}]},
    )
    with pytest.raises(ValueError, match="som gerado"):
        project_with({"generator": "tone", "duration": 1, "effects": [{"type": "repeat", "times": 2}]})


def test_the_effect_catalog_offers_the_generated_sound_as_a_target():
    from dmaker.domain.audio_effects import catalog_payload as effect_catalog

    assert "audio.generated.N" in {target["target"] for target in effect_catalog()["targets"]}
    assert effect_info  # a importação acima não é só para o catálogo


# ---------- tom, chirp, ruído, silêncio ----------


def test_the_tone_source_is_an_aevalsrc_with_the_amplitude_and_the_frequency():
    built = build_generator(
        GeneratorRequest(parse_generator("tone", {"frequency_hz": 1000, "amplitude_db": -6}), 1.0, RATE)
    )
    assert built.graph.startswith("aevalsrc=exprs='")
    assert "1000*t" in built.graph and f"{db_to_linear(-6):.6f}" in built.graph[:60]
    assert f"sample_rate={RATE}" in built.graph and "duration=1" in built.graph


def test_the_chirp_phase_is_the_integral_of_the_frequency():
    chirp = parse_generator("chirp", {"start_hz": 100, "end_hz": 300})
    cycles = sweep_cycles(chirp, 2.0)
    # linear: f0·t + (f1-f0)/(2T)·t²  =  100·t + 50·t²
    assert cycles == "100*t+50*t*t"
    log = parse_generator("chirp", {"start_hz": 100, "end_hz": 400, "interpolation": "logarithmic"})
    assert "pow(4," in sweep_cycles(log, 2.0)


def test_noise_and_silence_sources():
    noise = build_generator(
        GeneratorRequest(parse_generator("noise", {"noise_type": "pink", "seed": 7}), 2.0, RATE)
    )
    assert noise.graph.startswith("anoisesrc=color=pink:") and ":seed=7:" in noise.graph
    silent = build("silence", 0.5)
    assert silent.shape == (24000,) and not silent.any()


def test_the_bandlimited_square_has_far_less_energy_between_the_harmonics_than_the_naive_one():
    frequency = 1737.0  # não divide a taxa: o aliasing do quadrado ingênuo cai fora dos harmônicos
    cycles = frequency * np.arange(RATE * 2) / RATE
    naive = np.where(np.mod(cycles, 1.0) < 0.5, 1.0, -1.0)
    clean = bandlimited_square(cycles, frequency / RATE)

    def inharmonic_energy(signal: np.ndarray) -> float:
        magnitude = np.abs(np.fft.rfft(signal * np.hanning(len(signal)))) ** 2
        bins = np.fft.rfftfreq(len(signal), 1 / RATE)
        ratio = bins / frequency
        off = np.abs(ratio - np.round(ratio)) > 0.15  # longe de qualquer harmônico
        return float(magnitude[off].sum() / magnitude.sum())

    assert inharmonic_energy(clean) < inharmonic_energy(naive) / 20
    assert abs(np.max(clean)) < 1.2  # a correção não estoura a onda


def test_the_bandlimited_square_tone_peak_is_the_requested_level():
    samples = build("tone", 1.0, waveform="square_bandlimited", frequency_hz=440, amplitude_db=-6)
    assert peak_db(samples) == pytest.approx(-6, abs=0.8)


# ---------- DTMF ----------


def test_the_dtmf_table_has_the_sixteen_keys_with_the_standard_pairs():
    assert len(DTMF_FREQUENCIES) == 16
    assert dtmf_pair("1") == (697.0, 1209.0)
    assert dtmf_pair("5") == (770.0, 1336.0)
    assert dtmf_pair("#") == (941.0, 1477.0)
    assert dtmf_pair("d") == (941.0, 1633.0)
    with pytest.raises(ValueError, match="tecla DTMF"):
        dtmf_pair("x")


def test_a_goertzel_decoder_reads_123_digit_by_digit():
    samples = build("dtmf", 0.9, sequence="123", tone_percent=55)
    assert decode_dtmf(samples, 3) == "123"


def test_the_decoder_reads_the_whole_keypad_including_the_letters():
    keys = "0123456789*#ABCD"
    samples = build("dtmf", 0.25 * len(keys), sequence=keys)
    assert decode_dtmf(samples, len(keys)) == keys


def test_the_dtmf_tone_fraction_and_silence_between_keys_follow_the_ratio():
    samples = build("dtmf", 1.0, sequence="12", tone_percent=50)
    slot = RATE // 2
    loud = np.abs(samples) > 1e-6
    assert loud[: slot // 2 - 100].any() and not loud[slot // 2 + 100 : slot].any()
    assert peak_db(samples) == pytest.approx(-2.0, abs=0.7)


def test_dtmf_refuses_a_key_the_keypad_does_not_have():
    with pytest.raises(ValueError, match="tecla DTMF"):
        parse_generator("dtmf", {"sequence": "12x"})


# ---------- Faixa de Ritmo ----------


def test_a_beat_every_half_second_at_120_bpm():
    positions = beat_positions(120, 8, RATE)
    assert positions == [index * 24000 for index in range(8)]


def test_the_beat_positions_do_not_drift_at_a_tempo_that_does_not_divide_the_rate():
    positions = beat_positions(113, 200, RATE)
    assert positions[199] == round(199 * 60 / 113 * RATE)


def test_the_first_beat_of_each_measure_is_louder_and_the_others_are_equal():
    samples = build("rhythm_track", 4.0, tempo_bpm=120, beats=8, beats_per_measure=4, beat_sound="ping")
    peaks = [np.max(np.abs(samples[start : start + 12000])) for start in beat_positions(120, 8, RATE)]
    assert peaks[0] == pytest.approx(peaks[4], rel=0.01) and peaks[0] > 1.8 * peaks[1]
    assert peaks[1] == pytest.approx(peaks[2], rel=0.01) == pytest.approx(peaks[3], rel=0.01)
    assert peak_db(samples) == pytest.approx(-2.0, abs=0.1)


def test_without_the_accent_every_beat_has_the_same_level():
    samples = build("rhythm_track", 2.0, beats=4, accent_first=False)
    peaks = [np.max(np.abs(samples[start : start + 6000])) for start in beat_positions(120, 4, RATE)]
    assert max(peaks) == pytest.approx(min(peaks), rel=0.01)


def test_silence_between_the_beats_and_after_the_last_one():
    samples = build("rhythm_track", 4.0, tempo_bpm=120, beats=2, beat_sound="metronome")
    assert not np.abs(samples[12000:24000]).any()
    assert not np.abs(samples[36000:]).any()  # depois das duas batidas, silêncio até o fim do item


@pytest.mark.parametrize("sound", ["metronome", "ping", "cowbell", "noise_click", "drip"])
def test_every_beat_sound_makes_a_finite_burst_that_fits_in_the_beat(sound):
    samples = build("rhythm_track", 1.0, tempo_bpm=300, beats=4, beat_sound=sound)
    assert np.isfinite(samples).all() and np.max(np.abs(samples)) > 0.1


def test_the_rhythm_natural_duration_is_the_length_of_its_beats():
    assert parse_generator("rhythm_track", {"tempo_bpm": 120, "beats": 16}).natural_duration() == 8.0


# ---------- Pluck e Risset ----------


def test_the_midi_note_69_is_440_hz_and_the_pluck_is_tuned_to_it():
    assert midi_to_hz(69) == 440.0 and midi_to_hz(60) == pytest.approx(261.6256, abs=1e-3)
    samples = build("pluck", 1.0, midi_note=69, amplitude_db=-6)
    assert spectrum_peak_hz(samples) == pytest.approx(440.0, abs=1.0)
    assert peak_db(samples) == pytest.approx(-6.0, abs=0.01)


def test_the_gradual_pluck_dies_out_and_the_abrupt_one_is_cut_while_still_sounding():
    gradual = build("pluck", 1.0, fade="gradual")
    abrupt = build("pluck", 1.0, fade="abrupt")
    tail = slice(-2400, None)
    assert np.max(np.abs(gradual[tail])) < 0.01 * np.max(np.abs(gradual))
    assert np.max(np.abs(abrupt[tail])) > 0.05 * np.max(np.abs(abrupt))  # ainda soando no corte


def test_the_risset_drum_decays_and_keeps_the_requested_peak():
    drum = build("risset_drum", 2.0, frequency_hz=100, decay_s=1.0, amplitude_db=-6)
    assert peak_db(drum) == pytest.approx(-6.0, abs=0.01)
    early = np.sqrt(np.mean(drum[:4800] ** 2))
    late = np.sqrt(np.mean(drum[-4800:] ** 2))
    assert late < early / 100  # perdeu mais de 40 dB em 2 s com decaimento de 60 dB em 1 s
    assert np.array_equal(drum, build("risset_drum", 2.0, frequency_hz=100, decay_s=1.0, amplitude_db=-6))


def test_the_drum_noise_band_sits_around_its_center():
    pure_noise = build("risset_drum", 2.0, noise_percent=100, noise_center_hz=2000, noise_width_hz=400)
    spectrum = np.abs(np.fft.rfft(pure_noise)) ** 2
    bins = np.fft.rfftfreq(len(pure_noise), 1 / RATE)
    inside = spectrum[(bins > 1800) & (bins < 2200)].sum()
    assert inside / spectrum.sum() > 0.9


# ---------- Importar Amostras ----------


def write_text(tmp_path: Path, text: str, name: str = "dados.txt") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_the_sample_text_ignores_blank_lines_and_comments_and_accepts_a_decimal_comma(tmp_path):
    path = write_text(tmp_path, "# cabeçalho\n0\n0,5\n\n-0.25\n")
    assert list(read_sample_values(path)) == [0.0, 0.5, -0.25]


def test_a_line_that_is_not_a_number_is_an_error_with_its_line_number(tmp_path):
    path = write_text(tmp_path, "0\n0.5\nabc\n")
    with pytest.raises(ValueError, match=r"dados.txt, linha 3: 'abc'"):
        read_sample_values(path)


def test_an_empty_or_missing_text_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="nenhum valor"):
        read_sample_values(write_text(tmp_path, "# só comentário\n"))
    with pytest.raises(FileNotFoundError, match="não encontrado"):
        read_sample_values(tmp_path / "nao-existe.txt")


def test_a_value_outside_minus_one_to_one_is_refused_unless_normalizing():
    values = np.array([0.0, 2.0, -4.0])
    with pytest.raises(ValueError, match=r"fora de -1 a 1.*4"):
        conformed_values(values, False, "dados.txt")
    assert list(conformed_values(values, True, "dados.txt")) == [0.0, 0.5, -1.0]
    assert list(conformed_values(np.zeros(3), True, "dados.txt")) == [0.0, 0.0, 0.0]


def test_the_samples_play_at_the_rate_of_the_text_resampled_to_the_mix_rate():
    values = np.sin(2 * np.pi * 100 * np.arange(8000) / 8000)  # 100 Hz a 8 kHz
    out = resampled(values, 8000, RATE)
    assert len(out) == 48000 and spectrum_peak_hz(out) == pytest.approx(100.0, abs=1.0)
    assert resampled(values, RATE, RATE) is values


def test_the_sample_data_generator_reads_the_text_of_the_project(tmp_path):
    write_text(tmp_path, "\n".join(["0.5"] * 100))
    samples = build(
        "sample_data", 1.0, resolve=lambda name: tmp_path / name, src="dados.txt", sample_rate=48000
    )
    assert len(samples) == 100 and np.allclose(samples, 0.5)
    with pytest.raises(ValueError, match="precisa do projeto"):
        build("sample_data", 1.0)


def test_the_sample_data_natural_duration_is_the_lines_over_the_rate(tmp_path):
    write_text(tmp_path, "\n".join(["0.1"] * 8000))
    data = parse_generator("sample_data", {"src": "dados.txt", "sample_rate": 8000})
    assert data.natural_duration(lambda name: tmp_path / name) == 1.0
    assert data.files() == ["dados.txt"]


# ---------- o arquivo ----------


def test_the_float_wav_keeps_the_exact_peak_and_values_above_full_scale(tmp_path):
    samples = np.array([[0.5012, 0.5012], [-1.5, 1.5], [0.0, 0.0]], dtype=np.float32)
    path = write_wav_float(tmp_path / "f.wav", samples, RATE)
    read, rate = read_wav_float(path)
    assert rate == RATE and read.shape == (3, 2) and np.allclose(read, samples)


def test_stereo_frames_make_mono_stereo_and_fit_the_exact_length():
    mono = np.ones(10, dtype=np.float32)
    assert stereo_frames(mono, 10).shape == (10, 2)
    assert stereo_frames(mono, 4).shape == (4, 2)
    padded = stereo_frames(mono, 15)
    assert padded.shape == (15, 2) and not padded[10:].any()


def test_the_ffmpeg_source_command_pads_trims_and_copies_the_channel_without_gain():
    request = GeneratorRequest(parse_generator("tone"), 1.0, RATE)
    args = source_args(build_generator(request), 48000, Path("saida.wav"))
    graph = args[args.index("-filter_complex") + 1]
    assert "apad=whole_len=48000,atrim=end_sample=48000,pan=stereo|c0=c0|c1=c0[generated]" in graph
    assert args[-3:] == ["-c:a", "pcm_f32le", "saida.wav"]


def test_the_renderer_records_the_command_in_a_simulation_and_writes_nothing(tmp_path):
    runner = RecordingRunner()
    renderer = GeneratedSoundRenderer(runner, tmp_path / "gen", write_files=False)
    project = project_with({"generator": "tone", "duration": 1}, {"generator": "silence", "duration": 1})
    for sound in project.audio.generated:
        renderer.render(sound, project.resolve)
    assert len(runner.commands) == 1  # o tom é uma fonte do ffmpeg; o silêncio são zeros em numpy
    assert not list((tmp_path / "gen").glob("*.wav"))


def test_the_cache_key_changes_with_the_params_the_duration_and_the_text_file(tmp_path):
    renderer = GeneratedSoundRenderer(RecordingRunner(), tmp_path / "gen")
    resolve = lambda name: tmp_path / name  # noqa: E731
    base = project_with({"generator": "tone", "duration": 1}).audio.generated[0]
    louder = project_with(
        {"generator": "tone", "duration": 1, "params": {"amplitude_db": -1}}
    ).audio.generated[0]
    longer = project_with({"generator": "tone", "duration": 2}).audio.generated[0]
    later = project_with({"generator": "tone", "duration": 1, "start": 9}).audio.generated[0]
    keys = {renderer.key(item, resolve) for item in (base, louder, longer)}
    assert len(keys) == 3
    assert renderer.key(base, resolve) == renderer.key(later, resolve)  # o instante não muda o som
    text = write_text(tmp_path, "0.1\n0.2\n")
    data = project_with(
        {"generator": "sample_data", "duration": 1, "params": {"src": "dados.txt"}}
    ).audio.generated[0]
    before = renderer.key(data, resolve)
    text.write_text("0.1\n0.2\n0.3\n", encoding="utf-8")
    assert renderer.key(data, resolve) != before


# ---------- as operações do edit_project ----------

DURATIONS = {"fala.wav": 12.0, "video.mp4": 10.0}


def prober(path: Path) -> MediaInfo:
    video = path.suffix == ".mp4"
    return MediaInfo(
        path,
        DURATIONS.get(path.name, 5.0),
        1280 if video else 0,
        720 if video else 0,
        30.0,
        video,
        True,
        False,
    )


@pytest.fixture
def folder(tmp_path) -> Path:
    for name in DURATIONS:
        (tmp_path / name).write_bytes(b"\x00" * 16)
    return tmp_path


def make(folder: Path, **audio) -> Project:
    project = Project.model_validate(
        {
            "name": "geracao",
            "timeline": [],
            "output": {"preset": "audio/wav"},
            "audio": {"voiceover": [{"src": "fala.wav", "start": 2}], **audio},
        }
    )
    project.base_dir = folder
    return project


def edit(project: Project, **op) -> Project:
    return apply_edit(project, op, prober=prober)


def test_generated_add_puts_a_sound_at_the_given_instant_with_the_generator_default_duration(folder):
    project = make(folder)
    edited = edit(project, type="generated_add", generator="rhythm_track", params={"beats": 8}, start=3)
    sound = edited.audio.generated[0]
    assert (sound.generator, sound.start, sound.duration) == ("rhythm_track", 3.0, 4.0)
    assert project.audio.generated == []  # a spec original não muda


def test_generated_add_takes_the_duration_from_end_or_from_a_marker_region(folder):
    project = make(folder, **{})
    project = project.model_copy(update={"markers": []})
    with_end = edit(project, type="generated_add", generator="tone", start=1, end=2.5)
    assert with_end.audio.generated[0].duration == 1.5
    marked = Project.model_validate(
        {**json.loads(project.to_bytes()), "markers": [{"start": 4, "end": 6, "text": "palavrão"}]}
    )
    marked.base_dir = folder
    from_region = edit(marked, type="generated_add", generator="tone", region="marker:palavrão")
    assert (from_region.audio.generated[0].start, from_region.audio.generated[0].duration) == (4.0, 2.0)


def test_generated_add_refuses_what_makes_no_sense_with_a_clear_message(folder):
    project = make(folder)
    with pytest.raises(EditError, match="informe `generator`"):
        edit(project, type="generated_add", start=1)
    with pytest.raises(EditError, match="frequency_hz"):
        edit(project, type="generated_add", generator="tone", params={"frequency_hz": 0})
    with pytest.raises(EditError, match="desconhecido"):
        edit(project, type="generated_add", generator="tone", volumen=2)


def test_generated_set_merges_params_and_resets_them_when_the_generator_changes(folder):
    project = edit(
        make(folder), type="generated_add", generator="tone", params={"frequency_hz": 880}, duration=2
    )
    louder = edit(project, type="generated_set", index=0, params={"amplitude_db": -6}, start=5)
    sound = louder.audio.generated[0]
    assert (
        sound.params["frequency_hz"] == 880.0 and sound.params["amplitude_db"] == -6.0 and sound.start == 5.0
    )
    noisy = edit(project, type="generated_set", index=0, generator="noise")
    assert noisy.audio.generated[0].params == {"noise_type": "white", "amplitude_db": -2.0, "seed": 0}
    with pytest.raises(EditError, match="fora do intervalo"):
        edit(project, type="generated_set", index=3, start=1)
    with pytest.raises(EditError, match="informe o que mudar"):
        edit(project, type="generated_set", index=0)


def test_generated_remove_drops_the_item_by_index(folder):
    project = edit(make(folder), type="generated_add", generator="tone", duration=1)
    project = edit(project, type="generated_add", generator="silence", duration=1)
    removed = edit(project, type="generated_remove", index=0)
    assert [sound.generator for sound in removed.audio.generated] == ["silence"]
    with pytest.raises(EditError, match="`index`"):
        edit(project, type="generated_remove")


def test_the_effect_chain_of_a_generated_sound_is_edited_by_audio_effect(folder):
    project = edit(make(folder), type="generated_add", generator="tone", duration=2)
    edited = edit(
        project,
        type="audio_effect",
        action="add",
        target="audio.generated.0",
        effect={"type": "fade_out", "duration": 1},
    )
    assert [effect.type for effect in edited.audio.generated[0].effects] == ["fade_out"]


class FakeWords:
    """A transcrição falsa: devolve as palavras já na linha do tempo, como a `SpeechWordSource` faria."""

    def __init__(self, words):
        self.words_given = words
        self.asked = []

    def words(self, project, target, language, search_from, search_to):
        self.asked.append((target, language, search_from, search_to))
        return self.words_given


def words_of(*items):
    from dmaker.text.captions import Word

    return [Word(start, end, text) for text, start, end in items]


def test_censor_beep_silences_the_word_in_the_item_and_puts_a_1_khz_tone_on_the_same_interval(folder):
    from dmaker.pipeline.edits import apply_edit_report

    project = make(folder)
    source = FakeWords(words_of(("isso", 2.2, 2.6), ("é", 2.6, 2.8), ("droga", 4.0, 4.5)))
    report = apply_edit_report(
        project,
        {"type": "censor_beep", "target": "audio.voiceover.0", "word": "droga"},
        prober=prober,
        words=source,
    )
    edited = report.project
    silence = edited.audio.voiceover[0].effects[0]
    assert (silence.type, silence.start, silence.end) == ("silence", 2.0, 2.5)  # tempo do item: 4.0-2 e 4.5-2
    beep = edited.audio.generated[0]
    assert (beep.generator, beep.start, beep.duration) == ("tone", 4.0, 0.5)
    assert beep.params["frequency_hz"] == 1000.0 and beep.params["waveform"] == "sine"
    assert source.asked == [("audio.voiceover.0", "pt", None, None)]


def test_censor_beep_by_interval_needs_no_transcription(folder):
    from dmaker.pipeline.edits import apply_edit_report

    edited = apply_edit_report(
        make(folder),
        {"type": "censor_beep", "target": "audio.voiceover.0", "start": 3, "end": 3.4, "frequency_hz": 800},
        prober=prober,
        words=FakeWords([]),
    ).project
    assert (edited.audio.generated[0].start, edited.audio.generated[0].duration) == (3.0, 0.4)
    assert edited.audio.generated[0].params["frequency_hz"] == 800.0


def test_censor_beep_margin_widens_the_interval_on_both_sides(folder):
    from dmaker.pipeline.edits import apply_edit_report

    edited = apply_edit_report(
        make(folder),
        {"type": "censor_beep", "target": "audio.voiceover.0", "word": "droga", "margin": 0.05},
        prober=prober,
        words=FakeWords(words_of(("droga", 4.0, 4.5))),
    ).project
    beep = edited.audio.generated[0]
    assert (beep.start, beep.duration) == (3.95, 0.6)


def test_censor_beep_with_a_repeated_word_asks_which_one_and_accepts_the_occurrence(folder):
    from dmaker.pipeline.edits import apply_edit_report

    words = words_of(("droga", 3.0, 3.4), ("e", 3.4, 3.5), ("droga", 5.0, 5.4))
    op = {"type": "censor_beep", "target": "audio.voiceover.0", "word": "droga"}
    with pytest.raises(EditError, match="aparece 2 vezes"):
        apply_edit_report(make(folder), op, prober=prober, words=FakeWords(words))
    edited = apply_edit_report(
        make(folder), {**op, "occurrence": 2}, prober=prober, words=FakeWords(words)
    ).project
    assert edited.audio.generated[0].start == 5.0


def test_censor_beep_says_what_is_missing_and_where_the_word_was_not_found(folder):
    from dmaker.pipeline.edits import apply_edit_report

    with pytest.raises(EditError, match="diga o que bipar"):
        apply_edit_report(
            make(folder),
            {"type": "censor_beep", "target": "audio.voiceover.0"},
            prober=prober,
            words=FakeWords([]),
        )
    with pytest.raises(EditError, match="Não achei"):
        apply_edit_report(
            make(folder),
            {"type": "censor_beep", "target": "audio.voiceover.0", "word": "droga"},
            prober=prober,
            words=FakeWords(words_of(("oi", 2.0, 2.2))),
        )
    with pytest.raises(EditError, match="`target`"):
        apply_edit_report(
            make(folder), {"type": "censor_beep", "start": 1, "end": 2}, prober=prober, words=FakeWords([])
        )


def test_censor_beep_outside_the_item_is_refused_by_the_silence_it_makes(folder):
    from dmaker.pipeline.edits import apply_edit_report

    with pytest.raises(EditError, match="fora de|não pega"):
        apply_edit_report(
            make(folder),
            {"type": "censor_beep", "target": "audio.voiceover.0", "start": 30, "end": 31},
            prober=prober,
            words=FakeWords([]),
        )


# ---------- a vista, o lint e a duração ----------


def test_the_timeline_view_shows_the_generated_sounds_in_the_sfx_track(folder):
    from dmaker.pipeline.layout import project_layout
    from dmaker.pipeline.timeline_view import build_timeline_view

    project = edit(
        make(folder),
        type="generated_add",
        generator="tone",
        params={"frequency_hz": 1000},
        start=4,
        duration=0.5,
    )
    view = build_timeline_view(project, project_layout(project, prober))
    (track,) = [track for track in view.tracks if track.id == "SFX"]
    (item,) = track.items
    assert (item.id, item.kind, item.label, item.start, item.end) == (
        "SFX-0",
        "generated",
        "Tom 1000 Hz",
        4.0,
        4.5,
    )
    assert item.extra["generator"] == "tone" and item.extra["duration"] == 0.5


def test_a_project_without_generated_sounds_has_no_sfx_track(folder):
    from dmaker.pipeline.layout import project_layout
    from dmaker.pipeline.timeline_view import build_timeline_view

    project = make(folder)
    view = build_timeline_view(project, project_layout(project, prober))
    assert "SFX" not in {track.id for track in view.tracks}


def test_the_lint_warns_about_a_sound_after_the_end_and_one_with_volume_zero(folder):
    from dmaker.pipeline.lint import _generated_warnings

    project = make(
        folder,
        generated=[
            {"generator": "tone", "start": 30, "duration": 1},
            {"generator": "tone", "start": 9.9, "duration": 1},
            {"generator": "tone", "volume": 0, "duration": 1},
            {"generator": "sample_data", "duration": 1, "params": {"src": "falta.txt"}},
        ],
    )
    texts = _generated_warnings(project, 10.0)
    assert any("audio.generated[0]" in text and "depois do fim" in text for text in texts)
    assert any("audio.generated[1]" in text and "passa do fim" in text for text in texts)
    assert any("audio.generated[2]" in text and "volume 0" in text for text in texts)
    assert any("audio.generated[3]" in text and "falta.txt" in text for text in texts)


def test_an_audio_only_project_lasts_until_the_end_of_its_generated_sounds(folder):
    from dmaker.pipeline.audio_duration import audio_extent

    project = Project.model_validate(
        {
            "name": "so-tom",
            "timeline": [],
            "output": {"preset": "audio/wav"},
            "audio": {"generated": [{"generator": "tone", "start": 2, "duration": 3}]},
        }
    )
    assert audio_extent(project, prober) == 5.0


def test_the_cache_folder_of_the_generated_sounds_is_in_the_data_folder_of_the_test():
    assert config.GENERATED_DIR.is_relative_to(config.DATA_DIR)
