"""Tempo e afinação: spec, contas puras, grafo e onde cada efeito vale, sem ffmpeg.

A medida de som (frequência, duração, estalo) está em `test_audio_pitch_tempo_integration.py`.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from dmaker.domain.audio_effects import (
    EFFECT_CLASSES,
    catalog,
    catalog_payload,
    chain_duration,
    chain_refusal,
    parse_effect,
)
from dmaker.domain.audio_effects.base import SHOWN_WHEN_FILLED
from dmaker.domain.audio_effects.pitch_tempo import PAULSTRETCH_MAX_SECONDS, ChangeTempo
from dmaker.domain.edits import EditError
from dmaker.domain.effect_edits import apply_effect_op
from dmaker.domain.pitch_tempo import (
    bpm_ratio,
    effective_ratio,
    length_ratio,
    note_frequency,
    note_number,
    note_to_note_semitones,
    percent_ratio,
    resample_rate,
    rpm_ratio,
    semitone_ratio,
    sliding_duration,
    sliding_steps,
)
from dmaker.domain.spec import Project
from dmaker.filtergraph.audio_effects import (
    SampleRequest,
    builder_types,
    chain_lines,
    is_sample_effect,
    sample_builder_types,
)
from dmaker.filtergraph.audio_effects.pitch_tempo import sliding_command_text
from dmaker.media.paulstretch import paulstretch, stretched_length, window_size
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.projects import summarize
from dmaker.pipeline.timeline_service import project_timeline_view
from dmaker.pipeline.voicefiles import music_file_playtime

FAMILY = ("change_pitch", "change_speed", "change_tempo", "sliding_stretch", "paulstretch")
RATE = 48000


def graph(*effects: dict, duration: float = 4.0) -> str:
    return ";".join(chain_lines("[a]", "[b]", [parse_effect(effect) for effect in effects], duration))


# ---------- contas puras ----------


def test_twelve_semitones_double_the_frequency_and_two_give_493_9_hz_from_440():
    assert semitone_ratio(12) == pytest.approx(2.0)
    assert semitone_ratio(-12) == pytest.approx(0.5)
    assert 440 * semitone_ratio(2) == pytest.approx(493.883, abs=1e-3)


def test_note_numbers_and_frequencies_follow_the_a4_440_standard():
    assert note_number("C", 4) == 60 and note_number("A", 4) == 69 and note_number("C", -1) == 0
    assert note_frequency("A", 4) == pytest.approx(440.0)
    assert note_frequency("C", 4) == pytest.approx(261.626, abs=1e-3)
    assert note_to_note_semitones("A", 4, "B", 4) == 2.0
    assert note_to_note_semitones("C", 5, "C", 4) == -12.0


def test_the_ratios_of_each_unit():
    assert percent_ratio(50) == 1.5 and percent_ratio(-50) == 0.5
    assert bpm_ratio(120, 128) == pytest.approx(128 / 120)
    assert length_ratio(10, 8) == pytest.approx(1.25)
    assert rpm_ratio(45, 100 / 3) == pytest.approx(0.7407, abs=1e-4)


def test_the_resample_rate_is_an_integer_and_the_effective_ratio_follows_it():
    assert resample_rate(0.7407407, RATE) == 35556
    assert effective_ratio(0.7407407, RATE) == pytest.approx(35556 / RATE)
    assert resample_rate(1.0, RATE) == RATE


def test_the_sliding_plan_integrates_the_tempo_over_equal_steps():
    steps = sliding_steps(5.0, 1.0, 0.5, 0.0, -12.0)
    assert len(steps) == 100 and steps[0].at == 0.0
    assert sum(step.span for step in steps) == pytest.approx(5.0)
    tempos = [step.tempo for step in steps]
    assert tempos[0] > tempos[-1] and all(a > b for a, b in zip(tempos, tempos[1:], strict=False))
    # a integral exata de 1/tempo com o tempo linear de 1 a 0,5 em 5 s é 5 ln(2) / 0,5
    assert sliding_duration(steps) == pytest.approx(5 * math.log(2) / 0.5, rel=1e-3)
    assert steps[0].pitch > steps[-1].pitch and steps[-1].pitch == pytest.approx(semitone_ratio(-12 * 0.995))


def test_the_sliding_step_count_is_capped_for_long_items_and_floored_for_short_ones():
    assert len(sliding_steps(600.0, 1.0, 0.5, 0.0, 0.0)) == 120
    assert len(sliding_steps(0.1, 1.0, 0.5, 0.0, 0.0)) == 8


def test_a_constant_sliding_plan_lasts_the_same_as_a_plain_tempo_change():
    steps = sliding_steps(10.0, 2.0, 2.0, 0.0, 0.0)
    assert sliding_duration(steps) == pytest.approx(5.0)


# ---------- registro e catálogo ----------


def test_the_family_is_registered_with_a_builder_for_each_type():
    assert set(FAMILY) <= set(EFFECT_CLASSES)
    assert {"change_pitch", "change_speed", "change_tempo", "sliding_stretch"} <= builder_types()
    assert "paulstretch" in sample_builder_types() and "paulstretch" not in builder_types()


def test_the_catalog_tells_names_and_which_effects_change_the_duration():
    by_type = {info.type: info for info in catalog()}
    names = {t: (by_type[t].label, by_type[t].audacity_name, by_type[t].changes_duration) for t in FAMILY}
    assert names == {
        "change_pitch": ("Mudar Tom", "Change Pitch", False),
        "change_speed": ("Mudar Velocidade e Tom", "Change Speed", True),
        "change_tempo": ("Mudar Andamento", "Change Tempo", True),
        "sliding_stretch": ("Esticar Gradualmente", "Sliding Stretch", True),
        "paulstretch": ("Paulstretch", "Paulstretch", True),
    }
    assert by_type["paulstretch"].sample_stage and not by_type["change_tempo"].sample_stage


def test_the_unit_modes_are_choices_and_their_fields_carry_a_shown_when_condition():
    payload = catalog_payload("change_pitch")["effects"][0]
    params = {p["name"]: p for p in payload["parameters"]}
    assert params["mode"]["kind"] == "choice" and params["mode"]["options"] == [
        "semitones",
        "notes",
        "percent",
    ]
    assert params["mode"]["shown_when"] is None  # o seletor de unidade aparece sempre
    assert params["semitones"]["shown_when"] == {"mode": "semitones"}
    assert params["cents"]["shown_when"] == {"mode": "semitones"}
    assert params["from_note"]["shown_when"] == {"mode": "notes"}
    assert params["percent"]["shown_when"] == {"mode": "percent"}
    assert params["preserve_formants"]["shown_when"] is None
    tempo = {p["name"]: p for p in catalog_payload("change_tempo")["effects"][0]["parameters"]}
    assert tempo["bpm_from"]["shown_when"] == {"mode": "bpm"} and tempo["length_to"]["shown_when"] == {
        "mode": "duration"
    }
    speed = {p["name"]: p for p in catalog_payload("change_speed")["effects"][0]["parameters"]}
    assert speed["rpm_from"]["shown_when"] == {"mode": "rpm"} and speed["percent"]["shown_when"] == {
        "mode": "percent"
    }


def test_every_shown_when_names_a_choice_of_the_same_effect_and_one_of_its_options():
    for info in catalog():
        params = {p.name: p for p in info.parameters}
        for param in info.parameters:
            if param.shown_when:
                for field, value in param.shown_when.items():
                    # o Vocoder esconde a portadora gerada enquanto `carrier_track` tem uma trilha (valor nulo)
                    names_a_choice = params[field].kind == "choice" and value in params[field].options
                    # e mostra o campo da trilha escolhida (qualquer valor preenchido) com `SHOWN_WHEN_FILLED`
                    names_a_track = params[field].kind == "carrier_track" and (
                        value is None or value == SHOWN_WHEN_FILLED
                    )
                    assert names_a_choice or names_a_track, (
                        info.type,
                        param.name,
                    )


def test_the_default_of_each_effect_in_the_family_validates_and_is_not_a_no_op_except_the_pitch_and_speed():
    for name in FAMILY:
        effect = parse_effect({"type": name})
        assert effect.type == name
    assert chain_duration([parse_effect({"type": "change_pitch"})], 5.0) == 5.0
    assert chain_duration([parse_effect({"type": "paulstretch"})], 5.0) == 50.0


# ---------- Mudar Tom ----------


def test_change_pitch_in_semitones_and_cents_is_one_rubberband_with_the_pitch_ratio():
    text = graph({"type": "change_pitch", "semitones": 2})
    assert "rubberband=pitch=1.122462048:pitchq=quality:transients=mixed:channels=together" in text
    assert "formant" not in text and "tempo=" not in text
    assert (
        "apad=pad_dur=0.2," in text and ",atrim=end_sample=192000" in text
    )  # o degrau do fim cai no silêncio
    assert "pitch=1.122462048" not in graph({"type": "change_pitch", "semitones": 2, "mode": "percent"})
    fine = graph({"type": "change_pitch", "semitones": 1, "cents": 50})
    assert f"pitch={semitone_ratio(1.5):.9f}" in fine


def test_change_pitch_from_note_to_note_uses_the_distance_between_the_notes():
    text = graph({"type": "change_pitch", "mode": "notes", "from_note": "A", "to_note": "B"})
    assert f"pitch={semitone_ratio(2):.9f}" in text
    down = graph(
        {
            "type": "change_pitch",
            "mode": "notes",
            "from_note": "C",
            "from_octave": 5,
            "to_note": "C",
            "to_octave": 4,
        }
    )
    assert "pitch=0.500000000" in down


def test_change_pitch_by_percent_is_the_frequency_ratio():
    assert "pitch=2.000000000" in graph({"type": "change_pitch", "mode": "percent", "percent": 100})
    assert "pitch=0.500000000" in graph({"type": "change_pitch", "mode": "percent", "percent": -50})


def test_change_pitch_can_preserve_the_formants():
    assert ":formant=preserved" in graph({"type": "change_pitch", "semitones": 3, "preserve_formants": True})


def test_change_pitch_with_no_change_is_a_plain_pass_through():
    assert "anull" in graph({"type": "change_pitch"}) and "rubberband" not in graph({"type": "change_pitch"})


def test_change_pitch_refuses_a_note_pair_further_than_four_octaves():
    with pytest.raises(ValidationError, match="48"):
        parse_effect(
            {
                "type": "change_pitch",
                "mode": "notes",
                "from_note": "C",
                "from_octave": 0,
                "to_note": "C",
                "to_octave": 8,
            }
        )


# ---------- Mudar Velocidade e Tom ----------


def test_change_speed_is_an_asetrate_and_an_aresample_back_to_the_mix_rate():
    text = graph({"type": "change_speed", "mode": "rpm", "rpm_from": 45, "rpm_to": 33.333333})
    assert "asetrate=35556,aresample=48000" in text


def test_change_speed_by_percent_and_its_duration_follow_the_integer_rate():
    effect = parse_effect({"type": "change_speed", "percent": 100})
    assert "asetrate=96000,aresample=48000" in graph({"type": "change_speed", "percent": 100})
    assert effect.output_duration(10.0) == pytest.approx(5.0)
    slow = parse_effect({"type": "change_speed", "mode": "rpm", "rpm_from": 45, "rpm_to": 100 / 3})
    assert slow.output_duration(10.0) == pytest.approx(10.0 * RATE / 35556)  # a razão inteira, não a pedida


def test_change_speed_out_of_range_is_refused():
    with pytest.raises(ValidationError, match="fora do que o efeito aceita"):
        parse_effect({"type": "change_speed", "mode": "rpm", "rpm_from": 1, "rpm_to": 78})  # 78 vezes


# ---------- Mudar Andamento ----------


def test_change_tempo_in_bpm_shortens_the_item_by_the_inverse_ratio():
    effect = parse_effect({"type": "change_tempo", "mode": "bpm", "bpm_from": 120, "bpm_to": 128})
    assert effect.output_duration(5.0) == pytest.approx(5.0 * 120 / 128)
    assert f"tempo={128 / 120:.9f}" in graph(effect.model_dump())
    assert "pitch=" not in graph(effect.model_dump())  # o tom não é tocado


def test_change_tempo_by_percent_and_by_duration():
    assert parse_effect({"type": "change_tempo", "percent": 100}).output_duration(8.0) == pytest.approx(4.0)
    by_length = parse_effect({"type": "change_tempo", "mode": "duration", "length_from": 10, "length_to": 8})
    assert by_length.output_duration(10.0) == pytest.approx(8.0)
    assert "tempo=1.250000000" in graph(by_length.model_dump())


def test_change_tempo_helper_builds_the_effect_the_tempo_adjustment_of_the_project_uses():
    effect = ChangeTempo.between_bpm(100, 125)
    assert (effect.mode, effect.bpm_from, effect.bpm_to) == ("bpm", 100, 125)
    assert effect.tempo_ratio() == pytest.approx(1.25)
    assert parse_effect(effect.model_dump()) == effect


def test_change_tempo_inside_an_interval_changes_only_that_stretch_and_is_spliced_without_a_ramp():
    effect = parse_effect({"type": "change_tempo", "percent": 100, "start": 1.0, "end": 3.0})
    assert effect.output_duration(6.0) == pytest.approx(5.0)  # 2 s viram 1 s
    text = graph(effect.model_dump(), duration=6.0)
    assert "concat=n=3:v=0:a=1" in text and "rubberband=tempo=2.000000000" in text and "amix" not in text


def test_change_tempo_with_no_change_is_a_pass_through_and_the_range_is_checked():
    assert "rubberband" not in graph({"type": "change_tempo", "percent": 0})
    with pytest.raises(ValidationError, match="fora do que o efeito aceita"):
        parse_effect({"type": "change_tempo", "mode": "bpm", "bpm_from": 10, "bpm_to": 500})


# ---------- Esticar Gradualmente ----------


def test_sliding_stretch_drives_one_rubberband_with_asendcmd_commands_for_tempo_and_pitch():
    text = graph(
        {"type": "sliding_stretch", "tempo_start": 0, "tempo_end": -50, "pitch_end": -12}, duration=5.0
    )
    assert "asetnsamples=n=480:p=0" in text and "asendcmd=c='" in text
    assert "rubberband@fx0_rb=tempo=0.997500:pitch=0.996540:pitchq=consistency" in text  # o primeiro degrau
    assert (
        "0.0600 rubberband@fx0_rb tempo 0.997500" in text
        and "0.0600 rubberband@fx0_rb pitch 0.996540" in text
    )
    assert text.count("rubberband@fx0_rb tempo") == 100 and text.count("rubberband@fx0_rb pitch") == 100
    exact = round(parse_effect({"type": "sliding_stretch"}).output_duration(5.0) * RATE)
    assert f"atrim=end_sample={exact}" in text  # o arquivo sai na duração que a conta declara
    assert "asendcmd=c='" in text and text.index("apad=pad_dur=0.2") > text.index(
        "asendcmd"
    )  # silêncio no fim


def test_sliding_stretch_duration_is_the_same_sum_the_commands_are_made_from():
    effect = parse_effect({"type": "sliding_stretch", "tempo_start": 0, "tempo_end": -50})
    steps = sliding_steps(5.0, 1.0, 0.5, 0.0, -12.0)
    assert effect.output_duration(5.0) == pytest.approx(sliding_duration(steps))
    assert sliding_command_text("x", steps[:1], delay=0.0) == (
        f"0.0000 rubberband@x tempo {steps[0].tempo:.6f};0.0000 rubberband@x pitch {steps[0].pitch:.6f}"
    )
    # com intervalo só a parte coberta anda
    inside = parse_effect(
        {"type": "sliding_stretch", "tempo_start": 0, "tempo_end": -50, "start": 1, "end": 4}
    )
    assert inside.output_duration(5.0) == pytest.approx(
        2.0 + sliding_duration(sliding_steps(3.0, 1.0, 0.5, 0, -12))
    )


def test_the_sliding_command_list_has_a_line_the_command_line_can_hold_even_for_a_long_item():
    text = graph({"type": "sliding_stretch"}, duration=3600.0)
    assert len(text) < 20000  # 120 degraus no máximo, por mais longo que seja o item


# ---------- Paulstretch ----------


def test_paulstretch_is_a_sample_effect_and_its_duration_is_the_factor_times_the_input():
    effect = parse_effect({"type": "paulstretch", "stretch_factor": 8})
    assert is_sample_effect(effect) and effect.sample_stage
    assert effect.output_duration(5.0) == 40.0
    inside = parse_effect({"type": "paulstretch", "stretch_factor": 4, "start": 1, "end": 2})
    assert inside.output_duration(5.0) == pytest.approx(4.0 + 4.0)


def test_paulstretch_refuses_an_output_above_twenty_minutes_with_the_reason():
    effect = parse_effect({"type": "paulstretch", "stretch_factor": 100})
    assert effect.refusal(11.0) is None  # 1100 s
    reason = effect.refusal(13.0)
    assert reason and "20" in reason and "memória" in reason
    assert chain_refusal([effect], 13.0) == reason
    assert chain_refusal([parse_effect({"type": "change_tempo", "percent": 100})], 100000.0) is None
    off = parse_effect({"type": "paulstretch", "stretch_factor": 100, "enabled": False})
    assert chain_refusal([off], 13.0) is None
    assert PAULSTRETCH_MAX_SECONDS == 1200.0


def test_the_sample_builder_also_refuses_a_piece_that_would_pass_the_ceiling():
    from dmaker.filtergraph.audio_effects import build_samples

    effect = parse_effect({"type": "paulstretch", "stretch_factor": 1000})
    samples = np.zeros((RATE * 2, 2), dtype=np.float32)  # 2 s x 1000 = 33 min
    with pytest.raises(ValueError, match="teto"):
        build_samples(SampleRequest(effect, samples))


def test_paulstretch_output_length_window_size_and_reproducibility():
    t = np.arange(RATE) / RATE
    tone = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    samples = np.stack([tone, tone], axis=1)
    out = paulstretch(samples, RATE, 4.0, 0.25)
    assert out.shape == (RATE * 4, 2) and out.dtype == np.float32
    assert np.array_equal(out, paulstretch(samples, RATE, 4.0, 0.25))  # a semente é fixa
    assert stretched_length(RATE, 4.0) == RATE * 4
    assert window_size(0.25, RATE) == 16384 and window_size(0.001, RATE) == 64
    assert paulstretch(samples[:0], RATE, 4.0, 0.25).shape == (0, 2)
    assert paulstretch(samples[:50], RATE, 8.0, 0.25).shape == (400, 2)  # menor que a janela


def test_paulstretch_keeps_the_level_of_a_stationary_noise_and_has_no_gap():
    rng = np.random.default_rng(11)
    noise = (rng.standard_normal(RATE * 3) * 0.1).astype(np.float32)
    out = paulstretch(np.stack([noise, noise], axis=1), RATE, 8.0, 0.25)
    mono = out[:, 0].astype(np.float64)
    assert float(np.sqrt(np.mean(mono**2))) == pytest.approx(0.1, rel=0.03)
    block = RATE // 20  # 50 ms
    levels = [float(np.sqrt(np.mean(mono[i : i + block] ** 2))) for i in range(0, len(mono) - block, block)]
    assert min(levels) > 0.8 * float(np.median(levels))  # nenhum bloco de 50 ms cai
    assert not np.array_equal(out[:, 0], out[:, 1])  # a fase de cada canal é sorteada à parte


# ---------- onde cada efeito vale ----------


def make(folder: Path, **parts) -> Project:
    data = {
        "name": "tempo",
        "timeline": [{"type": "clip", "src": "video.mp4", "start": 0, "end": 8}],
        **parts,
    }
    project = Project.model_validate(data)
    project.base_dir = folder
    return project


def prober(path: Path) -> MediaInfo:
    video = path.suffix == ".mp4"
    duration = {"video.mp4": 20.0, "fala.wav": 6.0, "musica.wav": 30.0}.get(path.name, 5.0)
    return MediaInfo(path, duration, 1280 if video else 0, 720 if video else 0, 30.0, video, True, False)


@pytest.fixture
def folder(tmp_path) -> Path:
    for name in ("video.mp4", "fala.wav", "musica.wav"):
        (tmp_path / name).write_bytes(b"\x00" * 16)
    return tmp_path


@pytest.mark.parametrize("name", ["change_speed", "change_tempo", "sliding_stretch", "paulstretch"])
def test_a_clip_refuses_the_effects_that_change_the_duration_and_points_to_its_speed(folder, name):
    with pytest.raises(ValidationError) as caught:
        make(
            folder,
            timeline=[
                {"type": "clip", "src": "video.mp4", "start": 0, "end": 8, "effects": [{"type": name}]}
            ],
        )
    assert "`speed` do próprio clipe" in str(caught.value) and "voz gravada" in str(caught.value)


def test_a_pip_refuses_them_too_and_the_narration_and_the_master_follow_the_same_rule(folder):
    with pytest.raises(ValidationError, match="`speed`"):
        make(
            folder,
            overlays=[
                {
                    "type": "video",
                    "src": "video.mp4",
                    "start": 0,
                    "end": 3,
                    "effects": [{"type": "change_tempo"}],
                }
            ],
        )
    with pytest.raises(ValidationError, match="`speed`"):
        make(folder, audio={"narration": [{"text": "oi", "effects": [{"type": "change_speed"}]}]})
    with pytest.raises(ValidationError, match="`speed`"):
        make(folder, audio={"master_effects": [{"type": "change_tempo"}]})


def test_change_pitch_is_accepted_in_the_clip_the_pip_the_narration_and_the_master(folder):
    pitch = {"type": "change_pitch", "semitones": 2}
    clip = make(
        folder, timeline=[{"type": "clip", "src": "video.mp4", "start": 0, "end": 8, "effects": [pitch]}]
    )
    assert clip.timeline[0].effects[0].type == "change_pitch"
    make(folder, overlays=[{"type": "video", "src": "video.mp4", "start": 0, "end": 3, "effects": [pitch]}])
    make(folder, audio={"narration": [{"text": "oi", "effects": [pitch]}], "master_effects": [pitch]})


def test_the_recorded_voice_and_the_music_accept_every_effect_that_changes_the_duration(folder):
    chain = [{"type": name} for name in ("change_speed", "change_tempo", "sliding_stretch")]
    project = make(
        folder,
        audio={
            "voiceover": [{"src": "fala.wav", "effects": chain}],
            "music": {"src": "musica.wav", "effects": [*chain, {"type": "paulstretch", "stretch_factor": 2}]},
        },
    )
    assert len(project.audio.music.effects) == 4


def test_paulstretch_is_refused_in_the_master_because_it_runs_on_samples(folder):
    with pytest.raises(ValidationError, match="Paulstretch"):
        make(folder, audio={"master_effects": [{"type": "paulstretch"}]})


# ---------- a duração nova aparece na linha do tempo e no validate ----------


def view_item(project: Project, track: str) -> dict:
    tracks = project_timeline_view(project, prober=prober).to_dict()["tracks"]
    return next(t for t in tracks if t["id"] == track)["items"][0]


def test_the_timeline_view_shows_the_new_length_of_a_stretched_voice(folder):
    plain = make(folder, audio={"voiceover": [{"src": "fala.wav", "start": 1.0}]})
    tempo = make(
        folder,
        audio={
            "voiceover": [
                {
                    "src": "fala.wav",
                    "start": 1.0,
                    "effects": [{"type": "change_tempo", "mode": "bpm", "bpm_from": 120, "bpm_to": 128}],
                }
            ]
        },
    )
    stretched = make(
        folder,
        audio={
            "voiceover": [
                {"src": "fala.wav", "start": 1.0, "effects": [{"type": "paulstretch", "stretch_factor": 1.5}]}
            ]
        },
    )
    before = view_item(plain, "VO")
    assert before["end"] - before["start"] == pytest.approx(6.0)
    after = view_item(tempo, "VO")
    assert after["end"] - after["start"] == pytest.approx(6.0 * 120 / 128) and after["extra"]["duration"] == (
        pytest.approx(5.625)
    )
    longer = view_item(stretched, "VO")
    assert longer["end"] - longer["start"] == pytest.approx(9.0)


def test_the_timeline_view_tells_the_music_file_length_after_the_effects(folder):
    plain = make(folder, audio={"music": {"src": "musica.wav"}})
    stretched = make(
        folder, audio={"music": {"src": "musica.wav", "effects": [{"type": "change_speed", "percent": 100}]}}
    )
    assert "duration" not in view_item(plain, "MUS")["extra"]
    assert view_item(stretched, "MUS")["extra"]["duration"] == pytest.approx(15.0)
    assert music_file_playtime(stretched, prober) == pytest.approx(15.0)
    assert music_file_playtime(plain, prober) == pytest.approx(30.0)


def test_a_tail_window_of_the_music_is_resolved_against_the_length_after_the_effects(folder):
    project = make(
        folder,
        audio={
            "music": {
                "src": "musica.wav",
                "spans": [{"start": 0, "end": 4, "tail": True}],
                "effects": [{"type": "change_speed", "percent": 100}],
            }
        },
    )
    item = view_item(project, "MUS")
    assert item["in_point"] == pytest.approx(15.0 - 4.0)  # o fim da música de 15 s, não de 30 s


def test_validate_reports_the_new_length_of_voice_and_music_and_the_paulstretch_refusal(folder):
    project = make(
        folder,
        audio={
            "voiceover": [{"src": "fala.wav", "effects": [{"type": "paulstretch", "stretch_factor": 300}]}],
            "music": {"src": "musica.wav", "effects": [{"type": "change_tempo", "percent": 100}]},
        },
    )
    warnings = summarize(project, prober=prober).warnings
    assert any("audio.voiceover[0]" in w and "1800.0s" in w for w in warnings)
    assert any(w.startswith("audio.voiceover[0]: Paulstretch") and "teto" in w for w in warnings)
    assert any(w == "audio.music: com os efeitos, o arquivo da música toca por 15.0s." for w in warnings)


def test_a_music_without_a_time_effect_gets_no_length_warning_from_validate(folder):
    plain = make(
        folder, audio={"music": {"src": "musica.wav", "effects": [{"type": "amplify", "gain_db": 1}]}}
    )
    assert not any("o arquivo da música toca" in w for w in summarize(plain, prober=prober).warnings)


# ---------- a edição pelo audio_effect ----------


def test_the_audio_effect_edit_adds_the_time_effects_where_they_are_accepted_and_explains_the_refusal(folder):
    project = make(folder, audio={"music": {"src": "musica.wav"}, "voiceover": [{"src": "fala.wav"}]})
    edited = apply_effect_op(
        project,
        {
            "action": "add",
            "target": "audio.music",
            "effect": {"type": "change_tempo", "mode": "bpm", "bpm_from": 120, "bpm_to": 128},
        },
    )
    assert edited.audio.music.effects[0].tempo_ratio() == pytest.approx(128 / 120)
    pitched = apply_effect_op(
        edited, {"action": "add", "target": "timeline.0", "effect": {"type": "change_pitch", "semitones": 2}}
    )
    assert pitched.timeline[0].effects[0].type == "change_pitch"
    with pytest.raises(EditError, match="`speed` do próprio clipe"):
        apply_effect_op(
            project, {"action": "add", "target": "timeline.0", "effect": {"type": "change_tempo"}}
        )
    with pytest.raises(EditError, match="muda a duração"):
        apply_effect_op(
            project, {"action": "add", "target": "audio.master", "effect": {"type": "paulstretch"}}
        )
