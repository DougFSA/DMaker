"""Os grafos e a spec dos efeitos de limpeza: funções puras, sem ffmpeg."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dmaker.domain.audio_effects import catalog_payload, parse_effect
from dmaker.domain.spec import AudioSettings, NoiseProfile, Project
from dmaker.filtergraph.audio_effects import (
    EffectRequest,
    build_effect,
    chain_lines,
    is_sample_effect,
    split_stages,
)
from dmaker.filtergraph.audio_effects.restoration import declick_parameters
from dmaker.pipeline.audio_lint import noise_profile_warnings


def request(effect: dict, duration: float = 3.0) -> EffectRequest:
    return EffectRequest(parse_effect(effect), "[in]", "[out]", "t", duration)


# ---------- cliques e clipping, sobre o adeclick e o adeclip ----------


def test_the_audacity_defaults_map_to_the_most_sensitive_adeclick_and_the_default_burst():
    assert declick_parameters(200, 20) == (1.0, 2.0)
    assert declick_parameters(900, 40) == (4.5, 4.0)  # menos sensível, e a fusão sobe com a largura
    assert declick_parameters(0, 0) == (1.0, 0.0)  # largura zero: só os cliques mais estreitos


def test_click_removal_runs_the_filter_behind_a_mirrored_preroll_and_returns_the_same_length():
    lines = build_effect(request({"type": "click_removal"}))
    graph = ";".join(lines)
    assert "adeclick=w=30:t=1:b=2" in graph
    assert "areverse" in graph and "atrim=end_sample=4800" in graph  # 100 ms espelhados na frente
    assert "atrim=start_sample=4800,asetpts=PTS-STARTPTS[out]" in graph  # e tirados depois
    assert lines[0].startswith("[in]") and lines[-1].endswith("[out]")


def test_the_preroll_never_passes_the_length_of_a_short_item():
    graph = ";".join(build_effect(request({"type": "click_removal"}, duration=0.05)))
    assert "atrim=end_sample=2400" in graph  # 50 ms a 48 kHz


def test_clip_fix_swaps_in_the_restored_samples_only_above_the_threshold_and_then_lowers_the_volume():
    graph = ";".join(build_effect(request({"type": "clip_fix", "threshold_percent": 70, "reduce_db": 3})))
    assert "adeclip" in graph and "amerge=inputs=2" in graph
    assert "if(lt(abs(val(0)),0.699000),val(0),val(2))" in graph  # 70% menos a folga de 0,1%
    assert "if(lt(abs(val(1)),0.699000),val(1),val(3))" in graph
    assert graph.endswith("volume=-3.000000dB[out]")
    assert "volume" not in ";".join(build_effect(request({"type": "clip_fix"})))  # sem redução, sem ganho


# ---------- a cadeia partida em estágios ----------


def test_a_chain_of_filters_only_is_one_stage_so_the_command_is_the_usual_one():
    effects = [parse_effect(item) for item in ({"type": "amplify", "gain_db": 3}, {"type": "click_removal"})]
    stages = split_stages(effects)
    assert len(stages) == 1 and not stages[0].samples
    assert [index for index, _ in stages[0].effects] == [0, 1]


def test_a_sample_effect_gets_a_stage_of_its_own_between_the_filter_stages():
    effects = [
        parse_effect(item)
        for item in (
            {"type": "amplify", "gain_db": 3},
            {"type": "invert"},
            {"type": "noise_reduction"},
            {"type": "amplify", "gain_db": -3, "enabled": False},
            {"type": "reverse"},
            {"type": "repair", "start": 1.0, "end": 1.001},
        )
    ]
    stages = split_stages(effects)
    shape = [(stage.samples, [index for index, _ in stage.effects]) for stage in stages]
    assert shape == [
        (False, [0, 1]),
        (True, [2]),
        (False, [4]),
        (True, [5]),
    ]  # o efeito desligado (3) não entra


def test_the_registry_tells_the_two_worlds_apart():
    assert is_sample_effect(parse_effect({"type": "noise_reduction"})) and is_sample_effect(
        parse_effect({"type": "repair", "start": 0, "end": 0.001})
    )
    assert not is_sample_effect(parse_effect({"type": "click_removal"})) and not is_sample_effect(
        parse_effect({"type": "amplify"})
    )
    with pytest.raises(ValueError, match="sem construtor registrado"):
        chain_lines("[a]", "[b]", [parse_effect({"type": "noise_reduction"})], 1.0)  # num grafo ao vivo, não


# ---------- a spec ----------


def test_the_noise_reduction_defaults_and_ranges_are_the_audacity_ones():
    effect = parse_effect({"type": "noise_reduction"})
    assert (effect.reduction_db, effect.sensitivity, effect.smoothing_bands, effect.profile) == (
        12.0,
        6.0,
        3,
        "auto",
    )
    for field, value in (("reduction_db", 49), ("sensitivity", 25), ("smoothing_bands", 13), ("profile", "")):
        with pytest.raises(ValidationError):
            parse_effect({"type": "noise_reduction", field: value})
    click = parse_effect({"type": "click_removal"})
    assert (click.threshold, click.max_spike_width) == (200, 20)
    clip = parse_effect({"type": "clip_fix"})
    assert (clip.threshold_percent, clip.reduce_db) == (100.0, 0.0)


def test_the_catalog_lists_the_four_effects_with_the_profile_parameter_as_its_own_kind():
    by_type = {effect["type"]: effect for effect in catalog_payload()["effects"]}
    assert {"noise_reduction", "click_removal", "clip_fix", "repair"} <= set(by_type)
    profile = next(p for p in by_type["noise_reduction"]["parameters"] if p["name"] == "profile")
    assert profile["kind"] == "profile" and profile["default"] == "auto"
    assert by_type["repair"]["needs_selection"] and by_type["repair"]["sample_stage"]
    assert by_type["noise_reduction"]["sample_stage"] and not by_type["click_removal"]["sample_stage"]
    reduction = next(p for p in by_type["noise_reduction"]["parameters"] if p["name"] == "reduction_db")
    assert (reduction["minimum"], reduction["maximum"], reduction["default"], reduction["unit"]) == (
        0.0,
        48.0,
        12.0,
        "dB",
    )


def test_the_master_refuses_an_effect_that_needs_the_samples_of_an_item():
    with pytest.raises(ValidationError, match="não vale na mistura inteira"):
        AudioSettings.model_validate({"master_effects": [{"type": "noise_reduction"}]})
    assert AudioSettings.model_validate({"master_effects": [{"type": "click_removal"}]}).master_effects


def test_a_project_without_profiles_dumps_exactly_as_before_and_one_with_profiles_round_trips():
    plain = Project.model_validate({"name": "a", "timeline": [{"type": "clip", "src": "a.mp4"}]})
    assert "noise_profiles" not in plain.to_bytes().decode()
    profiled = Project.model_validate(
        {
            "name": "a",
            "timeline": [{"type": "clip", "src": "a.mp4"}],
            "audio": {"noise_profiles": {"sala": {"target": "timeline.0", "start": 0.2, "end": 0.9}}},
        }
    )
    assert profiled.audio.noise_profiles["sala"] == NoiseProfile(target="timeline.0", start=0.2, end=0.9)
    assert Project.from_bytes(profiled.to_bytes(), None).audio.noise_profiles == profiled.audio.noise_profiles
    with pytest.raises(ValidationError, match="end"):
        NoiseProfile(target="timeline.0", start=1.0, end=0.5)


def test_the_cache_key_of_a_clip_only_gets_a_profile_part_when_it_uses_a_named_profile():
    """O hash do mezanino e o do pedaço da prévia de um clipe sem perfil nomeado ficam como sempre foram; com perfil, a
    definição dele entra, então mudar o trecho do perfil refaz o clipe."""
    from types import SimpleNamespace

    from dmaker.pipeline.audio_effects import noise_profile_parts

    def project(start: float) -> Project:
        return Project.model_validate(
            {
                "name": "a",
                "timeline": [{"type": "clip", "src": "a.mp4"}],
                "audio": {
                    "voiceover": [{"src": "voz.wav"}],
                    "noise_profiles": {"sala": {"target": "audio.voiceover.0", "start": start, "end": 1.5}},
                },
            }
        )

    def parts(candidate: Project, *chain: dict) -> list:
        ctx = SimpleNamespace(project=candidate, session={}, runner=None, audio_fx=None)
        return noise_profile_parts(ctx, tuple(parse_effect(item) for item in chain))  # type: ignore[arg-type]

    assert parts(project(0.2)) == []
    assert parts(project(0.2), {"type": "noise_reduction"}) == []  # o automático não cita perfil
    assert parts(project(0.2), {"type": "amplify"}, {"type": "click_removal"}) == []
    named = {"type": "noise_reduction", "profile": "sala"}
    assert parts(project(0.2), named) != parts(project(0.3), named)  # mudar o trecho muda a chave
    assert parts(project(0.2), {**named, "enabled": False}) == []  # desligado não conta


def test_validate_warns_about_a_reduction_pointing_to_a_profile_that_does_not_exist():
    project = Project.model_validate(
        {
            "name": "a",
            "timeline": [
                {
                    "type": "clip",
                    "src": "a.mp4",
                    "effects": [{"type": "noise_reduction", "profile": "fantasma"}],
                }
            ],
            "audio": {"noise_profiles": {"sala": {"target": "timeline.0", "start": 0, "end": 1}}},
        }
    )
    warnings = noise_profile_warnings(project)
    assert len(warnings) == 1 and "'fantasma'" in warnings[0] and "sala" in warnings[0]
    assert (
        noise_profile_warnings(
            Project.model_validate({"name": "a", "timeline": [{"type": "clip", "src": "a.mp4"}]})
        )
        == []
    )
