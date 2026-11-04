"""Os grafos da cadeia de efeitos de áudio: funções puras, sem ffmpeg."""

from __future__ import annotations

import math

import pytest

from dmaker.domain.audio_effects import EFFECT_CLASSES
from dmaker.domain.audio_effects.basic import Amplify, Invert, Normalize, Repeat, Reverse
from dmaker.domain.spec import AudioSettings
from dmaker.filtergraph.audio import AudioTaps, audio_graph
from dmaker.filtergraph.audio_effects import (
    SAMPLE_RATE,
    SEAM_SECONDS,
    ChannelLevels,
    EffectRequest,
    Measure,
    apply_effect,
    build_effect,
    builder_types,
    chain_lines,
    ingress_line,
    measure_lines,
    parse_astats,
    sample_builder_types,
    span_samples,
)
from dmaker.filtergraph.common import Inputs

STEREO_SILENT = Measure((ChannelLevels(0.0, 0.0, 0.0, -math.inf), ChannelLevels(0.0, 0.0, 0.0, -math.inf)))


def levels(peak: float, dc: float = 0.0) -> ChannelLevels:
    return ChannelLevels(-peak + dc, peak + dc, dc, 20 * math.log10(max(abs(peak + dc), abs(-peak + dc))))


def request(effect, measure=None, duration=3.0) -> EffectRequest:
    return EffectRequest(effect, "[in]", "[out]", "t", duration, measure)


# ---------- o registro ----------


def test_every_registered_effect_class_has_a_builder_and_the_other_way_around():
    """O catálogo (as classes) e os dois registros de construtores (filtro e amostras) listam os mesmos tipos, e um tipo
    não está nos dois: o estágio de amostras e o de filtro são mundos separados."""
    assert set(EFFECT_CLASSES) == builder_types() | sample_builder_types()
    assert not builder_types() & sample_builder_types()
    assert {name for name, cls in EFFECT_CLASSES.items() if cls.sample_stage} == sample_builder_types()


# os efeitos que só existem com um intervalo (o Cortar tira "do instante tal ao instante tal")
REQUIRED_FIELDS = {"cut": {"start": 1.0, "end": 2.0}, "repair": {"start": 1.0, "end": 1.001}}


def test_every_effect_builds_a_graph_that_runs_from_the_input_to_the_output_label():
    for name, cls in EFFECT_CLASSES.items():
        if cls.sample_stage:  # esses não têm grafo: são contas em numpy (test_audio_restoration.py)
            continue
        lines = build_effect(
            request(cls(**REQUIRED_FIELDS.get(name, {})), measure=Measure((levels(0.5), levels(0.5))))
        )
        assert lines[0].startswith("[in]") or "[in]" in lines[0]
        assert lines[-1].endswith("[out]")


def test_a_builder_that_was_never_registered_fails_loudly():
    class Fake:
        type = "inexistente"

    with pytest.raises(ValueError, match="sem construtor registrado"):
        build_effect(EffectRequest(Fake(), "[a]", "[b]", "t", 1.0))  # type: ignore[arg-type]


def test_request_helpers_name_labels_after_the_tag_and_chain_filters_in_one_line():
    req = request(Reverse())
    assert req.label("w") == "[t_w]"
    assert req.chain("a=1", "b") == ["[in]a=1,b[out]"]
    assert req.samples == 3 * SAMPLE_RATE


# ---------- os cinco efeitos ----------


def test_amplify_applies_the_gain_in_db():
    assert build_effect(request(Amplify(gain_db=6))) == ["[in]volume=6.000000dB[out]"]
    assert build_effect(request(Amplify(gain_db=-12.5))) == ["[in]volume=-12.500000dB[out]"]


def test_amplify_without_clipping_limits_the_gain_to_the_headroom_of_the_measured_peak():
    effect = Amplify(gain_db=12, prevent_clipping=True)
    peak_minus_3 = Measure((levels(0.7079),))  # cerca de -3 dBFS
    gain = float(build_effect(request(effect, peak_minus_3))[0].split("volume=")[1].split("dB")[0])
    assert gain == pytest.approx(3.0, abs=0.01)  # só dá 3 dB de folga até 0 dBFS
    roomy = Measure((levels(0.01),))
    assert (
        "volume=12.000000dB" in build_effect(request(effect, roomy))[0]
    )  # com folga de sobra, o ganho pedido


def test_amplify_without_clipping_does_not_limit_a_cut_nor_a_silent_signal_nor_a_missing_measure():
    assert (
        "volume=-6.000000dB"
        in build_effect(request(Amplify(gain_db=-6, prevent_clipping=True), Measure((levels(0.9),))))[0]
    )
    assert (
        "volume=6.000000dB"
        in build_effect(request(Amplify(gain_db=6, prevent_clipping=True), STEREO_SILENT))[0]
    )
    assert "volume=6.000000dB" in build_effect(request(Amplify(gain_db=6, prevent_clipping=True)))[0]


def test_only_amplify_with_a_positive_gain_and_the_option_on_asks_for_a_measure():
    assert Amplify(gain_db=6, prevent_clipping=True).needs_measure()
    assert not Amplify(gain_db=6).needs_measure()
    assert not Amplify(gain_db=-6, prevent_clipping=True).needs_measure()
    assert Normalize().needs_measure()
    assert not Invert().needs_measure() and not Reverse().needs_measure() and not Repeat().needs_measure()


def test_normalize_scales_both_channels_by_the_loudest_one_and_keeps_the_balance():
    measure = Measure((levels(0.5), levels(0.25)))
    line = build_effect(request(Normalize(peak_db=-1, remove_dc=False), measure))[0]
    gain = float(line.split("volume=")[1].split("[")[0])
    assert gain == pytest.approx(10 ** (-1 / 20) / 0.5, rel=1e-6)


def test_normalize_stereo_independent_gives_each_channel_its_own_gain():
    measure = Measure((levels(0.5), levels(0.25)))
    line = build_effect(request(Normalize(peak_db=0, remove_dc=False, stereo_independent=True), measure))[0]
    assert "aeval=exprs=(val(0)-(0.000000000))*(2.000000000)|(val(1)-(0.000000000))*(4.000000000)" in line
    assert "channel_layout=stereo" in line


def test_normalize_removes_the_dc_offset_before_scaling_and_measures_the_peak_after_it():
    measure = Measure((levels(0.5, dc=0.1), levels(0.5, dc=0.1)))  # a onda vai de -0.4 a 0.6
    assert measure.channels[0].peak_after_dc(True) == pytest.approx(0.5)
    assert measure.channels[0].peak_after_dc(False) == pytest.approx(0.6)
    line = build_effect(request(Normalize(peak_db=0, remove_dc=True), measure))[0]
    assert "(val(0)-(0.100000000))*(2.000000000)" in line


def test_normalize_leaves_silence_and_a_missing_measure_alone():
    assert build_effect(request(Normalize(), STEREO_SILENT)) == ["[in]anull[out]"]
    assert build_effect(request(Normalize())) == ["[in]anull[out]"]


def test_invert_reverse_and_repeat():
    assert build_effect(request(Invert())) == ["[in]volume=-1[out]"]
    assert build_effect(request(Reverse())) == ["[in]areverse[out]"]
    repeat = build_effect(request(Repeat(times=3)))[0]
    assert repeat.startswith("[in]aloop=loop=2:size=") and repeat.endswith(
        "[out]"
    )  # `loop` conta além da primeira
    assert "loop=0" in build_effect(request(Repeat(times=1)))[0]


# ---------- a cadeia ----------


def test_a_chain_without_enabled_effects_is_a_straight_pass():
    assert chain_lines("[a]", "[b]", [], 2.0) == ["[a]anull[b]"]
    assert chain_lines("[a]", "[b]", [Invert(enabled=False)], 2.0) == ["[a]anull[b]"]


def test_the_chain_links_each_effect_output_to_the_next_input_in_order():
    lines = chain_lines("[a]", "[b]", [Amplify(gain_db=3), Invert(enabled=False), Reverse()], 2.0)
    assert lines == [
        "[a]volume=3.000000dB[fx0]",
        "[fx0]areverse[b]",
    ]  # o desligado some, o rótulo usa a posição na lista


def test_the_chain_hands_each_measure_to_the_effect_in_that_position():
    measures = {1: Measure((levels(0.5), levels(0.5)))}
    lines = chain_lines("[a]", "[b]", [Invert(), Normalize(peak_db=0, remove_dc=False)], 2.0, measures)
    assert lines[1].startswith("[fx0]volume=2.000000000")


def test_the_chain_tracks_the_duration_through_effects_that_change_it():
    # Repetir x2 sobre 2 s deixa 4 s: o Amplificar seguinte, com intervalo de 3 s em diante, enxerga os 4 s
    lines = chain_lines("[a]", "[b]", [Repeat(times=2), Amplify(gain_db=6, start=3)], 2.0)
    assert any("atrim=start_sample=144000:end_sample=192000" in line for line in lines)


# ---------- o intervalo ----------


def test_an_interval_in_the_middle_splits_the_item_in_three_and_crosses_the_seams_over_10_ms():
    ramp = round(SEAM_SECONDS * SAMPLE_RATE)
    assert ramp == 480
    lines = apply_effect(request(Amplify(gain_db=6, start=1.0, end=2.0)))
    text = "\n".join(lines)
    assert "asplit=3" in text
    assert "atrim=start_sample=48000:end_sample=96000" in text  # o trecho que recebe o efeito
    assert "volume=6.000000dB" in text
    assert f"afade=t=in:ss=0:ns={ramp}:curve=tri" in text  # o processado entra
    assert f"afade=t=out:ss={48000 - ramp}:ns={ramp}:curve=tri" in text  # e sai
    assert f"afade=t=out:ss=48000:ns={ramp}:curve=tri" in text  # o seco sai onde o processado entra
    assert (
        "adelay=48000S:all=1" in text and f"adelay={96000 - ramp}S:all=1" in text
    )  # em amostras, sem arredondar
    assert lines[-1].endswith("amix=inputs=3:duration=longest:dropout_transition=0:normalize=0[out]")


def test_an_interval_that_starts_at_zero_or_ends_at_the_end_has_no_seam_on_that_side():
    from_start = "\n".join(apply_effect(request(Amplify(gain_db=6, end=1.0))))
    assert "asplit=2" in from_start and "[t_h]" not in from_start and "adelay=0S" not in from_start
    # sem vizinho antes, o processado não entra por rampa: só o fim dele (sai) e o seco que volta (entra) têm uma
    assert from_start.count("afade=t=in") == 1 and from_start.count("afade=t=out") == 1
    until_end = "\n".join(apply_effect(request(Amplify(gain_db=6, start=2.0))))
    assert "asplit=2" in until_end and "[t_t]" not in until_end
    assert until_end.count("afade=t=in") == 1 and until_end.count("afade=t=out") == 1


def test_an_interval_covering_the_whole_item_is_just_the_effect():
    assert apply_effect(request(Amplify(gain_db=6, start=0, end=3.0))) == ["[in]volume=6.000000dB[out]"]
    assert apply_effect(request(Amplify(gain_db=6, start=0, end=99))) == ["[in]volume=6.000000dB[out]"]


def test_an_empty_interval_leaves_the_sound_as_it_is():
    assert apply_effect(request(Amplify(gain_db=6, start=1.0, end=1.00001))) == ["[in]anull[out]"]


def test_a_very_short_interval_shrinks_the_seam_to_fit():
    text = "\n".join(apply_effect(request(Reverse(start=1.0, end=1.01))))
    assert "ns=240" in text  # metade dos 480 amostras do intervalo, em vez dos 480 da emenda inteira


def test_an_interval_on_an_effect_that_changes_the_duration_splices_the_pieces_without_a_crossfade():
    lines = apply_effect(request(Repeat(times=3, start=1.0, end=2.0)))
    text = "\n".join(lines)
    assert "afade" not in text and "amix" not in text  # a emenda é a do próprio efeito
    assert "aloop=loop=2" in text
    assert lines[-1].endswith("concat=n=3:v=0:a=1[out]")


def test_the_span_in_samples_is_none_for_the_whole_item():
    assert span_samples(Amplify(), 3.0) is None
    assert span_samples(Amplify(start=0.5, end=1.5), 3.0) == (24000, 72000)


# ---------- medida ----------

ASTATS_STEREO = """\
[Parsed_astats_0 @ 000001fcac9cea00] Channel: 1
[Parsed_astats_0 @ 000001fcac9cea00] DC offset: 0.010000
[Parsed_astats_0 @ 000001fcac9cea00] Min level: -0.400000
[Parsed_astats_0 @ 000001fcac9cea00] Max level: 0.500000
[Parsed_astats_0 @ 000001fcac9cea00] Peak level dB: -6.020600
[Parsed_astats_0 @ 000001fcac9cea00] Bit depth: 27/32/32/32
[Parsed_astats_0 @ 000001fcac9cea00] Channel: 2
[Parsed_astats_0 @ 000001fcac9cea00] DC offset: -0.020000
[Parsed_astats_0 @ 000001fcac9cea00] Min level: -0.250000
[Parsed_astats_0 @ 000001fcac9cea00] Max level: 0.250000
[Parsed_astats_0 @ 000001fcac9cea00] Peak level dB: -12.041200
[Parsed_astats_0 @ 000001fcac9cea00] Overall
[Parsed_astats_0 @ 000001fcac9cea00] DC offset: 0.000000
[Parsed_astats_0 @ 000001fcac9cea00] Min level: -0.900000
[Parsed_astats_0 @ 000001fcac9cea00] Max level: 0.900000
[Parsed_astats_0 @ 000001fcac9cea00] Peak level dB: -0.915000
size=N/A time=00:00:03.00 bitrate=N/A speed= 325x elapsed=0:00:00.00
"""


def test_parse_astats_reads_each_channel_and_ignores_the_overall_block():
    measure = parse_astats(ASTATS_STEREO)
    assert measure is not None and len(measure.channels) == 2
    first, second = measure.channels
    assert (first.minimum, first.maximum, first.dc_offset, first.peak_db) == (-0.4, 0.5, 0.01, -6.0206)
    assert (second.minimum, second.maximum, second.dc_offset) == (-0.25, 0.25, -0.02)
    assert measure.peak_db == pytest.approx(-6.0206)  # o maior dos canais


def test_parse_astats_reads_a_silent_channel_and_gives_none_when_there_is_nothing_to_read():
    silent = ASTATS_STEREO.replace("-6.020600", "-inf").replace("-12.041200", "-inf")
    assert parse_astats(silent).peak_db == -math.inf  # type: ignore[union-attr]
    assert parse_astats("") is None
    assert parse_astats("ffmpeg falhou") is None


def test_the_measure_line_trims_to_the_interval_and_prints_once_at_the_end():
    assert measure_lines("[a]", "[m]") == ["[a]astats=metadata=0:reset=0[m]"]
    assert measure_lines("[a]", "[m]", (100, 200)) == [
        "[a]atrim=start_sample=100:end_sample=200,astats=metadata=0:reset=0[m]"
    ]


def test_the_ingress_line_brings_every_item_to_48khz_float_stereo():
    line = ingress_line(2, 1, "[fx_in]")
    assert line.startswith("[2:a:1]asetpts=PTS-STARTPTS,aresample=48000,")
    assert "sample_fmts=fltp" in line and "channel_layouts=stereo" in line and line.endswith("[fx_in]")


# ---------- master no grafo de áudio ----------


def master_graph(master: list, **kwargs) -> list[str]:
    lines: list[str] = []
    audio_graph(
        lines, Inputs(), "[a0]", AudioSettings(master_effects=master, normalize="fast"), None, 10.0, **kwargs
    )
    return lines


def test_the_master_chain_runs_after_the_mix_and_before_the_final_normalization():
    lines = master_graph([Amplify(gain_db=6)])
    text = ";".join(lines)
    assert text.index("volume=6.000000dB") < text.index("loudnorm")
    assert "[a0]aformat=sample_fmts=fltp" in text  # a cadeia recebe o formato da mixagem
    assert "[a_master]loudnorm" in text  # e a normalização final ainda vale por cima


def test_a_project_without_master_effects_builds_the_graph_it_always_built():
    plain = master_graph([])
    assert not any("a_master" in line for line in plain)
    assert plain == master_graph([Amplify(enabled=False)])  # desligado é como não ter


def test_master_effects_can_be_cut_short_or_left_out_for_the_measurement_passes():
    chain = [Amplify(gain_db=6), Reverse()]
    assert not any("areverse" in line for line in master_graph(chain, master_upto=1))
    assert any("areverse" in line for line in master_graph(chain))
    assert not any("volume=6" in line for line in master_graph(chain, include_master=False))


def test_the_master_effect_receives_the_measure_of_its_position_and_the_audiogram_tap_hears_the_result():
    measures = {0: Measure((levels(0.5), levels(0.5)))}
    taps = AudioTaps(frozenset({"mix"}))
    lines = master_graph([Normalize(peak_db=0, remove_dc=False)], master_measures=measures, taps=taps)
    text = ";".join(lines)
    assert "volume=2.000000000" in text
    assert text.index("[a_master]asplit=2[a_mix_main][a_mix_tap]") > text.index("volume=2.000000000")
