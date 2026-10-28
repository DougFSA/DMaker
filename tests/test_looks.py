"""Looks e acabamento: nomes, precedência, validação, grafos puros dos efeitos e o contrato com o guia."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from dmaker import config
from dmaker.domain.brand import load_theme
from dmaker.domain.looks import (
    DEFAULT_LOOKS,
    NO_LOOK,
    UnknownLookError,
    available_looks,
    brand_look,
    effective_look_name,
    is_no_look,
    look_effects,
    normalize_look_name,
    resolve_look,
)
from dmaker.domain.spec import ClipSegment, ColorAdjust, Project
from dmaker.filtergraph import finish
from dmaker.filtergraph.common import color_chain, vignette_angle
from dmaker.filtergraph.finish import (
    EFFECTS,
    FinishContext,
    effect_amounts,
    grade_chain,
    leak_curves,
    leak_cycle,
    post_video_lines,
)
from dmaker.filtergraph.lightleak import LeakLook, light_leak_source

OWN_COLOR = ColorAdjust(brightness=0.1)
CTX = FinishContext((1080, 1920), 30.0, 4.0)


# ---------- campos novos da spec ----------


def test_vignette_accepts_a_switch_or_an_intensity_and_refuses_values_outside_zero_to_one():
    assert ColorAdjust(vignette=True).vignette is True
    assert ColorAdjust(vignette=0.5).vignette == 0.5
    assert ColorAdjust().vignette is False
    with pytest.raises(ValidationError, match="intensidade de 0 a 1"):
        ColorAdjust(vignette=1.5)


@pytest.mark.parametrize("field", ["glow", "aberration", "light_leak", "grain"])
def test_finishing_effects_are_between_zero_and_one(field):
    assert getattr(ColorAdjust(**{field: 0.4}), field) == 0.4
    for bad in (-0.1, 1.1):
        with pytest.raises(ValidationError):
            ColorAdjust(**{field: bad})


def test_finishing_effects_count_as_own_color_in_is_identity():
    assert ColorAdjust().is_identity()
    for field in ("glow", "aberration", "light_leak", "grain"):
        assert not ColorAdjust(**{field: 0.1}).is_identity(), field
    assert not ColorAdjust(vignette=0.2).is_identity()


def test_look_fields_exist_on_the_project_and_on_every_segment_type():
    spec = {
        "name": "p",
        "look": "cinema",
        "timeline": [
            {"type": "clip", "src": "a.mp4", "look": "frio"},
            {"type": "image", "src": "a.png", "look": NO_LOOK},
            {"type": "card", "title": "x", "look": "vintage"},
        ],
    }
    project = Project.model_validate(spec)
    assert project.look == "cinema"
    assert [seg.look for seg in project.timeline] == ["frio", NO_LOOK, "vintage"]
    assert Project.model_validate({"name": "q", "timeline": [{"type": "card", "title": "x"}]}).look is None


# ---------- nomes e resolução ----------


def test_the_five_default_looks_exist_and_are_all_distinct_from_each_other():
    assert list(DEFAULT_LOOKS) == ["cinema", "quente", "frio", "pb-contraste", "vintage"]
    colors = {name: look.color.model_dump_json() for name, look in DEFAULT_LOOKS.items()}
    assert len(set(colors.values())) == 5
    assert all(not look.color.is_identity() and look.summary for look in DEFAULT_LOOKS.values())


def test_default_looks_use_no_lut_and_no_third_party_file():
    assert all(look.color.lut is None for look in DEFAULT_LOOKS.values())


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("Cinema", "cinema"),
        ("  PB Contraste ", "pb-contraste"),
        ("pb_contraste", "pb-contraste"),
        ("Cinematográfico", "cinematografico"),
        ("Nenhum", "nenhum"),
    ],
)
def test_names_are_compared_without_case_accent_or_separator_differences(written, expected):
    assert normalize_look_name(written) == expected


def test_a_request_in_portuguese_resolves_to_a_default_look_through_its_aliases():
    assert resolve_look("Cinematográfico").name == "cinema"
    assert resolve_look("preto e branco").name == "pb-contraste"
    assert resolve_look("PB").name == "pb-contraste"
    assert resolve_look("retrô").name == "vintage"


def test_unknown_look_lists_what_exists_including_the_brand_ones():
    with pytest.raises(UnknownLookError) as caught:
        resolve_look("neon", {"minha": {"summary": "x"}})
    message = str(caught.value)
    assert "'neon'" in message and "cinema" in message and "minha" in message and NO_LOOK in message


def test_a_brand_look_overrides_the_default_with_the_same_name_and_adds_new_ones():
    brand = {
        "cinema": {"summary": "O cinema da marca", "color": {"saturation": 1.3, "grain": 0.05}},
        "Linha Verde": {"color": {"vignette": 0.3}},
    }
    looks = available_looks(brand)
    assert looks["cinema"].source == "marca" and looks["cinema"].color.saturation == 1.3
    assert looks["linha-verde"].color.vignette == 0.3 and looks["linha-verde"].source == "marca"
    assert looks["quente"] is DEFAULT_LOOKS["quente"]  # o resto continua o padrão
    assert resolve_look("cinema", brand).summary == "O cinema da marca"
    assert DEFAULT_LOOKS["cinema"].source == "padrão"  # os padrões não são tocados


def test_a_brand_look_with_a_bad_field_says_which_look_and_which_field():
    with pytest.raises(ValueError, match=r"look 'x' da marca: color\.grain"):
        brand_look("x", {"color": {"grain": 5}})
    with pytest.raises(ValueError, match="campo.*desconhecido"):
        brand_look("x", {"cor": {}})


def test_brand_json_looks_reach_the_theme(tmp_path, monkeypatch):
    folder = tmp_path / "brands" / "teste"
    folder.mkdir(parents=True)
    (folder / "brand.json").write_text(
        json.dumps({"name": "Teste", "looks": {"suave": {"color": {"grain": 0.1}}}}), encoding="utf-8"
    )
    monkeypatch.setattr(config, "BRANDS_DIR", tmp_path / "brands")
    import dmaker.domain.brand as brand_module

    monkeypatch.setattr(brand_module, "BRANDS_DIR", tmp_path / "brands")
    assert load_theme("teste").looks == {"suave": {"color": {"grain": 0.1}}}
    assert load_theme(None).looks == {}


def test_look_effects_lists_only_what_the_look_turns_on():
    assert look_effects(DEFAULT_LOOKS["frio"]) == {"vignette": 0.1}
    assert look_effects(DEFAULT_LOOKS["vintage"]) == {
        "vignette": 0.45,
        "aberration": 0.15,
        "light_leak": 0.3,
        "grain": 0.35,
    }
    old_style = brand_look("antigo", {"color": {"vignette": True}})
    assert look_effects(old_style) == {"vignette": 0.4}  # `true` é a vinheta de intensidade 0.4


# ---------- precedência: trecho > projeto, trecho com cor própria mantém a sua ----------


@pytest.mark.parametrize(
    ("segment_look", "project_look", "color", "expected"),
    [
        (None, None, ColorAdjust(), None),
        (None, "cinema", ColorAdjust(), "cinema"),  # o look do projeto vale em todo trecho
        ("frio", "cinema", ColorAdjust(), "frio"),  # o do trecho vence
        (NO_LOOK, "cinema", ColorAdjust(), None),  # o trecho desliga o do projeto
        ("Nenhum", "cinema", ColorAdjust(), None),  # sem diferenciar maiúsculas
        (None, NO_LOOK, ColorAdjust(), None),
        (None, "cinema", OWN_COLOR, None),  # cor própria mantém a sua
        (None, "cinema", ColorAdjust(grain=0.2), None),  # efeito pedido à mão também é cor própria
        ("frio", "cinema", OWN_COLOR, "frio"),  # pedindo o look no trecho, ele vale mesmo com cor própria
        ("frio", None, ColorAdjust(), "frio"),
    ],
)
def test_effective_look_follows_segment_over_project_and_keeps_a_segments_own_color(
    segment_look, project_look, color, expected
):
    assert effective_look_name(segment_look, project_look, color) == expected


def test_is_no_look():
    assert is_no_look("nenhum") and is_no_look(" NENHUM ")
    assert not is_no_look(None) and not is_no_look("cinema")


# ---------- vinheta: o `true` não mudou; o número ajusta a intensidade ----------


def test_vignette_true_still_generates_exactly_the_filter_it_always_did():
    assert color_chain(ColorAdjust(vignette=True)) == ["vignette=angle=PI/5"]


def test_vignette_intensity_maps_linearly_to_the_lens_angle_and_matches_true_at_point_four():
    assert vignette_angle(0.4) == f"{3.141592653589793 / 5:.4f}"
    assert float(vignette_angle(1.0)) == pytest.approx(1.5708, abs=1e-4)  # PI/2: canto preto
    chain = color_chain(ColorAdjust(vignette=0.35))
    assert chain == [f"vignette=angle={vignette_angle(0.35)}:dither=0"]


def test_a_clip_without_color_or_look_keeps_the_exact_legacy_post_chain():
    lines = post_video_lines("[mz_v1]", "[vout]", ColorAdjust(), None, 0.0, 0.0, 4.0, (1080, 1920), 30.0)
    assert lines == ["[mz_v1]format=yuv420p,setsar=1[vout]"]
    graded = ColorAdjust(brightness=0.1, vignette=True, sharpen=0.5)
    lines = post_video_lines(
        "[a]", "[b]", graded, None, 0.5, 0.25, 4.0, None, 30.0
    )  # sem tamanho: não precisa
    assert lines == [
        "[a]eq=brightness=0.100:contrast=1.000:saturation=1.000:gamma=1.000,unsharp=5:5:0.50:5:5:0,"
        "vignette=angle=PI/5,fade=t=in:st=0:d=0.500,fade=t=out:st=3.750:d=0.250,format=yuv420p,setsar=1[b]"
    ]


# ---------- efeitos de acabamento: construtores puros e registrados ----------


def test_effects_are_registered_in_graph_order_and_match_color_adjust_fields():
    assert list(EFFECTS) == ["glow", "aberration", "light_leak", "grain"]
    assert all(name in ColorAdjust.model_fields for name in EFFECTS)


def test_effect_amounts_take_the_segments_value_over_the_looks_and_skip_zeros():
    look = ColorAdjust(grain=0.3, glow=0.2)
    assert effect_amounts(ColorAdjust(), look) == {"glow": 0.2, "grain": 0.3}
    assert effect_amounts(ColorAdjust(grain=0.6), look) == {"glow": 0.2, "grain": 0.6}  # não soma duas vezes
    assert effect_amounts(ColorAdjust(), None) == {}
    assert effect_amounts(ColorAdjust(aberration=0.1), None) == {"aberration": 0.1}


def test_grade_chain_applies_the_segments_color_first_and_never_stacks_two_vignettes():
    own = ColorAdjust(brightness=0.1, vignette=True)
    look = ColorAdjust(saturation=0.8, vignette=0.5)
    chain = grade_chain(own, look)
    assert chain[0].startswith("eq=brightness=0.100")
    assert chain[1] == "vignette=angle=PI/5"  # a do trecho
    assert chain[2].startswith("eq=brightness=0.000:contrast=1.000:saturation=0.800")
    assert sum(step.startswith("vignette") for step in chain) == 1
    assert sum(step.startswith("vignette") for step in grade_chain(ColorAdjust(), look)) == 1


def test_every_effect_builder_links_its_input_label_to_its_output_label():
    for name, builder in EFFECTS.items():
        text = ";".join(builder("[in]", "[out]", 0.5, CTX))
        assert text.count("[in]") == 1 and text.endswith("[out]"), (
            name
        )  # entra uma vez e sai pelo rótulo pedido
        assert text.count("[out]") == 1, name


def test_effects_scale_with_the_frame_width_so_the_result_is_the_same_at_any_resolution():
    small, large = FinishContext((540, 960), 30.0, 2.0), FinishContext((1080, 1920), 30.0, 2.0)
    assert finish.aberration("[i]", "[o]", 1.0, small)[0] != finish.aberration("[i]", "[o]", 1.0, large)[0]
    assert "rh=-5:bh=5" in finish.aberration("[i]", "[o]", 1.0, large)[0]  # 0,5% de 1080
    assert "rh=-3:bh=3" in finish.aberration("[i]", "[o]", 1.0, small)[0]  # 0,5% de 540, arredondado
    assert "gblur=sigma=4.05" in ";".join(finish.glow("[i]", "[o]", 1.0, large))  # 1,5% de 1080 em 1/4
    assert f"gblur=sigma={0.015 * 540 / 4:.2f}" in ";".join(finish.glow("[i]", "[o]", 1.0, small))


def test_aberration_always_shifts_at_least_one_pixel_and_keeps_green_in_place():
    line = finish.aberration("[i]", "[o]", 0.01, CTX)[0]
    assert "rgbashift=rh=-1:bh=1:edge=smear" in line and "gh" not in line and "format=gbrp" in line


def test_glow_only_uses_the_luma_and_never_blends_the_chroma():
    text = ";".join(finish.glow("[i]", "[o]", 0.5, CTX))
    assert "blend=c0_mode=screen:c0_opacity=0.350:c1_opacity=0:c2_opacity=0[o]" in text
    assert f"lutyuv=y='clip((val-{finish.GLOW_KNEE})*{finish.GLOW_GAIN},0,255)'" in text


def test_grain_is_a_seeded_luma_only_texture_shifted_every_frame():
    text = ";".join(finish.grain("[i]", "[o]", 0.25, CTX))
    assert f"noise=c0s=3:allf=t:all_seed={finish.GRAIN_SEED}" in text  # luma só (c0s), semente fixa
    assert "lutyuv=y=128:u=128:v=128" in text and "blend=all_mode=grainmerge:shortest=1[o]" in text
    assert (
        "s=548x968" in text and "scale=1094:1934:flags=bilinear" in text
    )  # nasce em meia resolução e é ampliada
    assert "crop=w=1080:h=1920" in text  # e o recorte, deslocado a cada quadro, tem o tamanho do quadro
    assert "x='7+7*sin(n*2.4)'" in text and "random" not in text  # o deslocamento é fórmula, não sorteio
    assert f"trim=end_frame={CTX.frames + 2}" in text
    for amount, strength in ((0.02, 1), (0.1, 1), (0.25, 3), (0.5, 6), (1.0, 12)):  # força 1 a 12, nunca 0
        assert f"noise=c0s={strength}:" in ";".join(finish.grain("[i]", "[o]", amount, CTX))


def test_light_leak_cycle_fits_whole_passes_in_the_segment_and_ends_with_the_light_off():
    assert (
        leak_cycle(FinishContext((1080, 1920), 30.0, 2.0)) == 60
    )  # trecho curto: uma passagem do tamanho dele
    assert leak_cycle(FinishContext((1080, 1920), 30.0, 4.0)) == 120
    assert leak_cycle(FinishContext((1080, 1920), 30.0, 12.0)) == 120  # três passagens de 4 s
    assert leak_cycle(FinishContext((1080, 1920), 30.0, 10.0)) == 150  # 2,5 vira duas passagens de 5 s
    intensity, position = leak_curves(0.5, CTX)
    assert "pow(sin(PI*(mod(N,120)/119)),2)" in intensity  # sino: zero nas pontas
    assert intensity.startswith("0.35*")  # quantidade 0,5 * pico 0,7
    assert position == "(-0.3+1.6*(mod(N,120)/119))"


def test_light_leak_by_formula_keeps_the_command_line_short_and_reuses_the_transition_generator():
    lines = ";".join(finish.light_leak("[i]", "[o]", 1.0, FinishContext((1080, 1920), 30.0, 12.0)))
    assert len(lines) < 4000  # uma tabela de 120 quadros estourava os 32 mil caracteres do Windows
    assert "geq=" in lines and "overlay=format=yuv420[o]" in lines and "yuva420p" in lines
    assert "trim=end_frame=360" in lines  # 12 s a 30 fps


def test_light_leak_source_accepts_tables_as_before_and_formulas_with_an_explicit_length():
    look = LeakLook(edge=(0, 0, 0), mid=(1, 1, 1), core=(2, 2, 2), width=0.2, tilt=0.0, floor=0.0)
    by_table = light_leak_source("[x]", (64, 64), 30.0, look, [0.0, 0.5, 1.0], [0.0, 0.5, 1.0])
    assert "trim=end_frame=3" in by_table[0]
    by_formula = light_leak_source("[x]", (64, 64), 30.0, look, "0.5", "N/10", frames=7)
    assert "trim=end_frame=7" in by_formula[0] and "(N/10)" in by_formula[0]
    with pytest.raises(ValueError, match="quantos quadros"):
        light_leak_source("[x]", (64, 64), 30.0, look, "0.5", "N/10")
    with pytest.raises(ValueError, match="um valor por quadro"):
        light_leak_source("[x]", (64, 64), 30.0, look, [0.0, 1.0], [0.0])


def test_a_clip_with_effects_chains_them_in_order_and_ends_in_the_mezzanine_label():
    color = ColorAdjust(grain=0.2, glow=0.2, aberration=0.2, light_leak=0.2)
    lines = post_video_lines("[mz_v1]", "[vout]", color, None, 0.3, 0.0, 4.0, (1080, 1920), 30.0)
    text = ";".join(lines)
    order = [text.index(f"[fx_{name}]") for name in ("glow", "aberration", "light_leak", "grain")]
    assert order == sorted(order)  # brilho, aberração, vazamento e, por último, o grão
    assert lines[0].startswith("[mz_v1]format=yuv420p[fx_in]")
    assert lines[-1] == "[fx_grain]fade=t=in:st=0:d=0.300,format=yuv420p,setsar=1[vout]"


def test_effects_without_the_frame_size_are_refused_instead_of_guessing():
    with pytest.raises(ValueError, match="tamanho do quadro"):
        post_video_lines("[a]", "[b]", ColorAdjust(grain=0.2), None, 0, 0, 2.0, None, 30.0)


def test_two_finishes_can_live_in_the_same_graph_through_their_tags():
    first = post_video_lines("[a]", "[b]", ColorAdjust(grain=0.2), None, 0, 0, 2.0, (64, 64), 30.0, tag="one")
    second = post_video_lines(
        "[c]", "[d]", ColorAdjust(grain=0.2), None, 0, 0, 2.0, (64, 64), 30.0, tag="two"
    )
    assert "[one_grain]" in ";".join(first) and "[two_grain]" in ";".join(second)
    assert "[two_" not in ";".join(first) and "[one_" not in ";".join(second)


# ---------- contrato: o guia fala de todos os looks e efeitos ----------


def test_guide_documents_every_default_look_every_effect_and_the_preview_commands():
    guide = (config.PACKAGE_DIR / "resources" / "guide.md").read_text(encoding="utf-8")
    for name in DEFAULT_LOOKS:
        assert f"`{name}`" in guide, f"o guia não descreve o look {name}"
    for effect_name in ("glow", "aberration", "light_leak", "grain", "vignette"):
        assert f"`{effect_name}`" in guide, f"o guia não descreve o efeito {effect_name}"
    assert "dmaker looks sheet" in guide and "dmaker looks list" in guide and f'"{NO_LOOK}"' in guide


def test_clip_segment_color_round_trips_through_json_with_the_new_fields():
    segment = ClipSegment(src="a.mp4", color={"grain": 0.3, "vignette": 0.5, "light_leak": 0.2})
    again = ClipSegment.model_validate_json(segment.model_dump_json())
    assert again.color == segment.color and again.color.vignette == 0.5
