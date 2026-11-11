"""O efeito Desenhar (a Draw Tool do painel Áudio): a classe e as recusas, o construtor puro, o recorte quando o item é
dividido e o efeito de verdade numa cadeia, com as amostras desenhadas conferidas uma a uma."""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from dmaker.domain.audio_effects import EFFECT_CLASSES, catalog_payload, parse_effect
from dmaker.domain.audio_effects.base import EFFECT_SAMPLE_RATE
from dmaker.domain.audio_effects.draw import MAX_DRAW_SAMPLES, Draw
from dmaker.domain.spec import Project
from dmaker.filtergraph.audio_effects.draw import build_draw
from dmaker.filtergraph.audio_effects.registry import SampleRequest, sample_builder_types
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.media.wavio import read_wav_float, write_wav_channels
from dmaker.pipeline.audio_effects import AudioItem, EffectProcessor

from .conftest import requires_ffmpeg

RATE = EFFECT_SAMPLE_RATE


def draw(start: float = 0.5, values: list[float] | None = None, **extra) -> Draw:
    effect = parse_effect({"type": "draw", "start": start, "values": values or [0.1, 0.2, 0.3], **extra})
    assert isinstance(effect, Draw)
    return effect


# ---------- a classe ----------


def test_the_end_is_derived_from_the_start_and_the_number_of_samples():
    effect = draw(1.0, [0.0] * 48)
    assert effect.end == pytest.approx(1.001)
    assert effect.channel == "both"
    assert Draw.sample_stage and Draw.owns_interval and Draw.needs_selection


def test_the_effect_needs_the_start_and_refuses_values_outside_full_scale_and_too_many():
    with pytest.raises(ValidationError, match="informe `start`"):
        parse_effect({"type": "draw", "values": [0.1]})
    with pytest.raises(ValidationError, match="fora de -1 a 1"):
        parse_effect({"type": "draw", "start": 0, "values": [0.5, 1.5]})
    with pytest.raises(ValidationError):
        parse_effect({"type": "draw", "start": 0, "values": [0.0] * (MAX_DRAW_SAMPLES + 1)})
    with pytest.raises(ValidationError):
        parse_effect({"type": "draw", "start": 0, "values": []})
    assert len(draw(0, [0.0] * MAX_DRAW_SAMPLES).values) == MAX_DRAW_SAMPLES


def test_the_sample_effect_is_refused_in_the_master_and_accepted_in_an_item():
    base = {"name": "d", "timeline": [{"type": "card", "title": "x", "duration": 2.0}]}
    item = {"type": "draw", "start": 0.1, "values": [0.2, 0.4]}
    Project.model_validate({**base, "audio": {"voiceover": [{"src": "v.wav", "effects": [item]}]}})
    with pytest.raises(ValidationError):
        Project.model_validate({**base, "audio": {"master_effects": [item]}})


def test_the_catalog_lists_the_effect_as_needing_a_selection_and_the_registries_agree():
    info = next(entry for entry in catalog_payload()["effects"] if entry["type"] == "draw")
    assert info["needs_selection"] is True and info["sample_stage"] is True
    assert {parameter["name"]: parameter["kind"] for parameter in info["parameters"]} == {
        "channel": "choice",
        "values": "points",
    }
    assert "draw" in EFFECT_CLASSES and "draw" in sample_builder_types()


# ---------- o construtor ----------


def stereo(frames: int = 100) -> np.ndarray:
    return np.stack([np.full(frames, 0.5, np.float32), np.full(frames, -0.5, np.float32)], axis=1)


def test_the_drawn_samples_replace_exactly_those_samples_and_nothing_else():
    signal = stereo()
    out = build_draw(SampleRequest(draw(10 / RATE, [0.1, 0.2, 0.3]), signal, RATE))
    assert out[10:13, 0].tolist() == pytest.approx([0.1, 0.2, 0.3])
    assert out[10:13, 1].tolist() == pytest.approx([0.1, 0.2, 0.3])
    untouched = np.ones(len(out), bool)
    untouched[10:13] = False
    assert np.array_equal(out[untouched], signal[untouched])
    assert signal[10, 0] == 0.5  # o sinal que entrou não é mexido


def test_one_channel_only_when_asked_and_the_mono_signal_takes_the_drawing_in_its_only_column():
    left = build_draw(SampleRequest(draw(5 / RATE, [0.9, 0.9], channel="left"), stereo(), RATE))
    assert left[5:7, 0].tolist() == pytest.approx([0.9, 0.9]) and left[5:7, 1].tolist() == [-0.5, -0.5]
    right = build_draw(SampleRequest(draw(5 / RATE, [0.9, 0.9], channel="right"), stereo(), RATE))
    assert right[5:7, 1].tolist() == pytest.approx([0.9, 0.9]) and right[5:7, 0].tolist() == [0.5, 0.5]
    mono = build_draw(
        SampleRequest(draw(5 / RATE, [0.7], channel="right"), np.zeros((20, 1), np.float32), RATE)
    )
    assert mono[5, 0] == pytest.approx(0.7)


def test_a_drawing_past_the_end_or_before_the_start_is_cut_and_one_fully_outside_changes_nothing():
    signal = stereo(10)
    past = build_draw(SampleRequest(draw(8 / RATE, [0.1, 0.2, 0.3, 0.4]), signal, RATE))
    assert past[8:, 0].tolist() == pytest.approx([0.1, 0.2]) and past.shape == signal.shape
    outside = build_draw(SampleRequest(draw(50 / RATE, [0.1]), signal, RATE))
    assert np.array_equal(outside, signal)


# ---------- dividir e juntar ----------


def test_splitting_the_item_keeps_the_drawn_samples_on_the_same_samples_of_each_piece():
    effect = draw(1.0, [float(i) / 100 for i in range(10)])  # as amostras 48000 a 48009
    second = effect.rebased(1.0 + 4 / RATE, 1.0)  # o pedaço de depois começa na quinta amostra
    assert isinstance(second, Draw)
    assert second.start == pytest.approx(0.0) and second.values == pytest.approx(
        [0.04, 0.05, 0.06, 0.07, 0.08, 0.09]
    )
    first = effect.rebased(0.0, 1.0 + 4 / RATE)
    assert isinstance(first, Draw) and first.values == pytest.approx([0.0, 0.01, 0.02, 0.03])
    assert effect.rebased(5.0, 1.0) is None and effect.rebased(0.0, 0.5) is None


def test_joining_moves_the_second_piece_later_and_two_drawings_never_merge():
    effect = draw(0.0, [0.5, 0.5])
    moved = effect.shifted(2.0)
    assert (
        isinstance(moved, Draw)
        and moved.start == pytest.approx(2.0)
        and moved.end == pytest.approx(2.0 + 2 / RATE)
    )
    assert effect.stitched(moved, 2.0) is None


# ---------- na cadeia de verdade ----------


@requires_ffmpeg
def test_the_effect_in_a_real_chain_draws_those_samples_in_the_processed_file(tmp_path):
    source = tmp_path / "v.wav"
    tone = (0.25 * np.sin(2 * np.pi * 220 * np.arange(RATE) / RATE)).astype(np.float32)
    write_wav_channels(source, tone[:, None], RATE)
    values = [round(0.9 * np.sin(i / 8), 5) for i in range(200)]
    effect = draw(0.5, values, channel="left")
    done = EffectProcessor(SubprocessRunner(quiet=True), tmp_path / "fx").process(
        AudioItem(source, 1.0, (effect,))
    )
    assert done is not None
    processed, rate = read_wav_float(done.path)
    first = round(0.5 * rate)
    assert rate == RATE and processed.shape[1] == 2
    assert (
        np.abs(processed[first : first + 200, 0] - np.array(values)).max() < 1e-6
    )  # o canal esquerdo é o desenho
    reference, _ = read_wav_float(
        EffectProcessor(SubprocessRunner(quiet=True), tmp_path / "fx2")
        .process(AudioItem(source, 1.0, (parse_effect({"type": "amplify", "gain_db": 0.0}),)))
        .path
    )
    assert np.array_equal(processed[:first, 0], reference[:first, 0])  # antes do desenho, o som é o mesmo
    assert np.array_equal(processed[first + 200 :, 0], reference[first + 200 :, 0])
    assert np.array_equal(
        processed[first : first + 200, 1], reference[first : first + 200, 1]
    )  # o direito não mudou


@requires_ffmpeg
def test_the_panel_shows_the_drawn_samples_one_by_one_at_the_deepest_zoom(tmp_path):
    from dmaker.pipeline.audio_panel import AudioPanelService, PeakTasks, wave_payload

    source = tmp_path / "voz.wav"
    write_wav_channels(source, np.zeros((RATE * 2, 1), np.float32), RATE)
    values = [0.0, 0.5, -0.5, 0.25, -0.25, 0.75]
    project = Project.model_validate(
        {
            "name": "d",
            "timeline": [{"type": "card", "title": "x", "duration": 3.0}],
            "audio": {
                "voiceover": [
                    {"src": "voz.wav", "effects": [{"type": "draw", "start": 1.0, "values": values}]}
                ],
                "normalize": "off",
            },
        }
    )
    project.base_dir = tmp_path
    service = AudioPanelService()
    plan = service.plan(project, "audio.voiceover.0")
    build = PeakTasks(lambda: tmp_path / "picos").request(lambda runner: AudioPanelService(runner), plan)
    assert build.done.wait(60) and build.state == "ready", build.error
    reader = service.reader(plan)
    payload = wave_payload(plan, build, reader, 1.0, 1.0 + 6 / RATE, 24)
    assert payload["mode"] == "samples"
    assert payload["samples"][0] == pytest.approx(values, abs=1e-5)
