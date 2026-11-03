"""Modelo "explicativo": planejamento dos assuntos (puro) e o template que monta o projeto no formato de
reel, com o quadro do rosto e a área de cima dentro da zona segura do Reels."""

from __future__ import annotations

import asyncio
import dataclasses
import json

import pytest
from pydantic import ValidationError

from dmaker import mcp_server
from dmaker.domain.explainer import (
    background_segment,
    hex_tone,
    plan_sounds,
    plan_topics,
    prepare_explainer,
)
from dmaker.domain.presets import get_preset
from dmaker.domain.regions import region_pixels
from dmaker.domain.sfx import plan_sfx
from dmaker.domain.spec import (
    SFX_VOLUME_MAX,
    CardSegment,
    ImageOverlay,
    ImageSegment,
    Project,
    SfxCue,
    VideoOverlay,
)
from dmaker.domain.templates import TemplateError, find_template, render_template
from dmaker.sfx import library_names

THREE = [
    {"fim": 20, "fundo": "escuro", "imagem": "a.png"},
    {"fim": 40, "fundo": "bege", "imagem": "b.png"},
    {"fim": 60, "fundo": "claro"},
]


# ---------- planejamento dos assuntos ----------


def test_topics_are_chained_and_each_gets_its_duration():
    topics = plan_topics(THREE)
    assert [(t["inicio"], t["fim"], t["duracao"]) for t in topics] == [
        (0, 20, 20),
        (20, 40, 20),
        (40, 60, 20),
    ]
    assert [t["imagem"] for t in topics] == ["a.png", "b.png", ""]  # sem imagem fica vazio, para o `$if`
    assert [t["segmento"]["duration"] for t in topics] == [20, 20, 20]


def test_start_is_optional_but_when_given_it_has_to_chain_with_the_previous_end():
    assert plan_topics([{"inicio": 0, "fim": 5}, {"inicio": 5, "fim": 9}])[1]["duracao"] == 4
    with pytest.raises(ValueError, match=r"assunto 2: começa em 6 s, mas o assunto 1 termina em 5 s"):
        plan_topics([{"fim": 5}, {"inicio": 6, "fim": 9}])  # vão: a fala ficaria sem fundo
    with pytest.raises(ValueError, match="assunto 2: começa em 4 s"):
        plan_topics([{"fim": 5}, {"inicio": 4, "fim": 9}])  # sobreposição
    with pytest.raises(ValueError, match="o primeiro assunto começa em 0 s"):
        plan_topics([{"inicio": 2, "fim": 9}])


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (None, "lista com pelo menos um assunto"),
        ([], "lista com pelo menos um assunto"),
        (["texto"], "assunto 1: esperava um objeto"),
        ([{"inicio": 0}], "`fim` é obrigatório"),
        ([{"fim": "dez"}], "`fim` é obrigatório"),
        ([{"fim": 0}], "precisa ser maior que o início"),
        ([{"fim": 5, "cor": "escuro"}], "campo.*desconhecido.*cor"),
        ([{"fim": 5, "fundo": 3}], "`fundo` precisa ser um texto"),
        ([{"fim": 5, "imagem": 3}], "`imagem` precisa ser o caminho"),
    ],
)
def test_topic_errors_say_which_topic_and_what_is_wrong(raw, message):
    with pytest.raises(ValueError, match=message):
        plan_topics(raw)


def test_background_defaults_alternate_so_every_change_of_subject_changes_the_color():
    colors = [t["segmento"]["background"] for t in plan_topics([{"fim": n} for n in range(1, 7)])]
    assert colors[:3] == ["#0F172A", "#F1E8D8", "#F8FAFC"] and colors[3:] == colors[:3]
    assert all(a != b for a, b in zip(colors, colors[1:], strict=False))


def test_background_by_name_hex_theme_key_or_image():
    dark = background_segment("escuro", 4, "x")
    assert (dark["type"], dark["flat"], dark["variant"], dark["logo"], dark["motion"]) == (
        "card",
        True,
        "dark",
        False,
        "none",
    )
    assert background_segment("Bege", 4, "x")["variant"] == "light"
    custom = background_segment("#112233", 4, "x")
    assert (custom["background"], custom["variant"]) == ("#112233", "dark")
    assert background_segment("#FFEECC", 4, "x")["variant"] == "light"
    theme_key = background_segment("accent", 4, "x")
    assert (
        theme_key["background"] == "accent" and "variant" not in theme_key
    )  # o tom só se sabe ao renderizar
    image = background_segment("C:/fundos/mesa.JPG", 4, "x")
    assert (image["type"], image["src"], image["reframe"]) == (
        "image",
        "C:/fundos/mesa.JPG",
        {"mode": "crop"},
    )


def test_hex_tone_follows_perceived_luminance():
    assert hex_tone("#000000") == "dark" and hex_tone("#FFFFFF") == "light"
    assert hex_tone("#0F172A") == "dark" and hex_tone("#F1E8D8") == "light"


def test_background_segments_are_valid_timeline_segments():
    for topic in plan_topics([{"fim": 5, "fundo": "bege"}, {"fim": 9, "fundo": "mesa.png"}]):
        segment = Project.model_validate({"name": "t", "timeline": [topic["segmento"]]}).timeline[0]
        assert isinstance(segment, CardSegment | ImageSegment)


def test_prepare_explainer_adds_the_total_duration_and_keeps_other_params():
    params = prepare_explainer({"gravacao": "g.mp4", "assuntos": THREE})
    assert params["duracao_total"] == 60 and params["gravacao"] == "g.mp4"
    assert params["assuntos"][0]["segmento"]["type"] == "card"


# ---------- o template ----------


def _render(**params) -> Project:
    template = find_template("explicativo")
    spec = render_template(template, {"gravacao": "gravacao.mp4", "assuntos": THREE, **params})
    return Project.model_validate(spec)


def test_template_builds_one_continuous_recording_over_three_backgrounds_with_an_image_each():
    project = _render()
    assert project.output.preset == "instagram/reels"
    assert [type(s).__name__ for s in project.timeline] == ["CardSegment"] * 3
    assert sum(s.duration for s in project.timeline) == pytest.approx(60)
    assert all(not s.transition for s in project.timeline)  # corte seco: os limites dos assuntos não se movem
    # a gravação é UMA sobreposição, do começo ao fim: a troca de fundo nunca corta a fala
    videos = [o for o in project.overlays if isinstance(o, VideoOverlay)]
    assert len(videos) == 1
    recording = videos[0]
    assert (recording.src, recording.region, recording.start, recording.end) == (
        "gravacao.mp4",
        "rosto",
        0,
        None,
    )
    assert (recording.shape, recording.volume, recording.animation) == ("rounded", 1, "none")
    # uma imagem por assunto que a tem, na região de cima, no intervalo do assunto
    images = [o for o in project.overlays if isinstance(o, ImageOverlay)]
    assert [(i.src, i.region, i.start, i.end) for i in images] == [
        ("a.png", "topo", 0, 20),
        ("b.png", "topo", 20, 40),
    ]


def test_template_without_images_or_captions_has_only_the_recording_and_the_backgrounds():
    project = _render(assuntos=[{"fim": 8}, {"fim": 16}], legendas=False)
    assert project.captions is None
    assert [type(o).__name__ for o in project.overlays] == ["VideoOverlay"]


def test_template_captions_keep_the_video_style_over_every_background():
    captions = _render(legenda_modo="karaoke").captions
    assert captions and captions.style.mode == "karaoke" and captions.style.follow_background is False
    assert _render().captions.style.mode == "rounded"


def test_template_uses_the_brand_only_when_asked():
    assert _render().brand is None
    assert _render(marca="medlycare").brand == "medlycare"


def test_template_reports_topic_errors_as_template_errors():
    template = find_template("explicativo")
    with pytest.raises(TemplateError, match="explicativo.*assunto 2: começa em 7 s"):
        render_template(template, {"gravacao": "g.mp4", "assuntos": [{"fim": 5}, {"inicio": 7, "fim": 9}]})


def test_template_regions_respect_the_reels_safe_zone():
    """O quadro do rosto e a área de cima ficam acima da faixa coberta pela interface do app, e a de cima
    também fora das laterais; o quadro está centrado e ocupa quase toda a largura."""
    preset = get_preset("instagram/reels")
    safe, width, height = preset.safe, preset.width, preset.height
    project = _render()
    topo = region_pixels(project.regions["topo"], width, height)
    rosto = region_pixels(project.regions["rosto"], width, height)

    def box(region):
        left, top, w, h = region
        return left, top, left + w, top + h

    t_left, t_top, t_right, t_bottom = box(topo)
    assert t_left >= safe.left and t_right <= width - safe.right  # nada do infográfico sob os botões
    assert t_top >= safe.top  # nem sob o nome do perfil
    r_left, r_top, r_right, r_bottom = box(rosto)
    assert r_bottom <= height - safe.bottom  # o rosto termina onde a interface do app começa
    assert r_left >= safe.left and abs((r_left + r_right) / 2 - width / 2) <= 1
    assert t_bottom < r_top  # a área de cima fica livre, acima do quadro
    assert (r_right - r_left) / width >= 0.85  # quase toda a largura
    assert (
        0.5 < (r_bottom - r_top) / (height - safe.top - safe.bottom) < 0.6
    )  # pouco mais da metade da área útil


def test_template_caption_sits_inside_the_face_frame_in_the_safe_zone():
    preset = get_preset("instagram/reels")
    project = _render()
    _, top, _, h = region_pixels(project.regions["rosto"], preset.width, preset.height)
    caption_y = project.captions.style.y * preset.height
    margin = project.captions.style.size * 2  # duas linhas de legenda cabem acima e abaixo do centro
    assert top + margin <= caption_y <= top + h - margin  # dentro do quadro, na parte de baixo dele
    assert caption_y > top + h / 2
    assert caption_y + margin <= preset.height - preset.safe.bottom  # e acima da interface do app


def test_template_text_is_free_of_dashes():
    template = find_template("explicativo")
    raw = template.path.read_text(encoding="utf-8")
    assert "—" not in raw and "–" not in raw


# ---------- sons por assunto (DMK-46) ----------

FAKE_LIBRARY = ("whoosh", "pop", "ding")  # biblioteca falsa: o plano puro não depende dos arquivos de som


def test_a_topic_sound_plays_at_the_start_of_the_topic_plus_em():
    cues = plan_sounds([{"som": "whoosh"}, {"som": "ding", "em": 8.5}], 2, 20.0, 20.0, FAKE_LIBRARY)
    assert cues == [{"sound": "whoosh", "at": 20.0}, {"sound": "ding", "at": 28.5}]


def test_volume_goes_through_only_when_given_and_null_means_omitted():
    cues = plan_sounds(
        [{"som": "pop", "volume": 0.8}, {"som": "pop", "volume": None, "em": None}],
        1,
        0.0,
        10.0,
        FAKE_LIBRARY,
    )
    assert cues == [{"sound": "pop", "at": 0.0, "volume": 0.8}, {"sound": "pop", "at": 0.0}]


def test_the_name_ignores_case_and_spaces_and_the_cue_keeps_the_library_spelling():
    assert plan_sounds([{"som": " Ding "}], 1, 3.0, 5.0, FAKE_LIBRARY) == [{"sound": "ding", "at": 3.0}]


def test_em_may_reach_the_end_of_the_topic_but_not_pass_it():
    assert plan_sounds([{"som": "pop", "em": 20}], 2, 20.0, 20.0, FAKE_LIBRARY)[0]["at"] == 40.0
    with pytest.raises(
        ValueError, match=r"assunto 2, som 1: `em` \(20.5 s\) cai fora do assunto, que dura 20 s"
    ):
        plan_sounds([{"som": "pop", "em": 20.5}], 2, 20.0, 20.0, FAKE_LIBRARY)


def test_the_absolute_time_has_no_floating_point_noise():
    cue = plan_sounds([{"som": "pop", "em": 0.2}], 3, 20.1, 5.0, FAKE_LIBRARY)[0]
    assert cue["at"] == 20.3  # 20.1 + 0.2 em ponto flutuante dá 20.299999999999997


@pytest.mark.parametrize("raw", [None, []])
def test_a_topic_without_sounds_plans_nothing(raw):
    assert plan_sounds(raw, 1, 0.0, 5.0, FAKE_LIBRARY) == []


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("whoosh", "assunto 1: `sons` precisa ser uma lista"),
        (["whoosh"], "assunto 1, som 1: esperava um objeto"),
        ([{"em": 1}], "assunto 1, som 1: `som` é obrigatório"),
        ([{"som": "  "}], "`som` é obrigatório"),
        ([{"som": 3}], "`som` é obrigatório"),
        ([{"som": "pop"}, {"som": "pop", "tempo": 1}], "assunto 1, som 2: campo.*desconhecido.*tempo"),
        ([{"som": "pop", "em": "cedo"}], "`em` precisa ser um número"),
        ([{"som": "pop", "em": True}], "`em` precisa ser um número"),
        ([{"som": "pop", "em": float("nan")}], "`em` precisa ser um número"),
        ([{"som": "pop", "em": -1}], r"`em` \(-1 s\) cai fora do assunto"),
        ([{"som": "pop", "volume": "alto"}], "`volume` precisa ser um número de 0 a 1.5"),
        ([{"som": "pop", "volume": 1.6}], "`volume` precisa ser um número de 0 a 1.5"),
        ([{"som": "pop", "volume": -0.1}], "`volume` precisa ser um número de 0 a 1.5"),
    ],
)
def test_sound_errors_say_the_topic_the_sound_and_what_is_wrong(raw, message):
    with pytest.raises(ValueError, match=message):
        plan_sounds(raw, 1, 0.0, 5.0, FAKE_LIBRARY)


def test_an_unknown_sound_lists_the_available_ones():
    with pytest.raises(ValueError) as error:
        plan_sounds([{"som": "pop"}, {"som": "apito"}], 3, 0.0, 5.0, FAKE_LIBRARY)
    assert str(error.value) == (
        'assunto 3, som 2: o som "apito" não existe na biblioteca de efeitos (disponíveis: whoosh, pop, ding)'
    )


@pytest.mark.parametrize("volume", [0, 0.5, 1, SFX_VOLUME_MAX, SFX_VOLUME_MAX + 0.01, -0.01, 2])
def test_the_volume_limit_is_the_one_of_audio_sfx(volume):
    """`sons` e `audio.sfx` recusam o mesmo volume: o limite mora num lugar só."""
    try:
        SfxCue(sound="pop", at=0, volume=volume)
        valid = True
    except ValidationError:
        valid = False
    try:
        plan_sounds([{"som": "pop", "volume": volume}], 1, 0.0, 5.0, FAKE_LIBRARY)
        planned = True
    except ValueError:
        planned = False
    assert planned == valid


def test_topics_carry_their_sounds_and_the_library_is_injectable():
    topics = plan_topics(
        [
            {"fim": 10, "sons": [{"som": "whoosh"}]},
            {"fim": 30, "sons": [{"som": "ding", "em": 5}]},
            {"fim": 40},
        ],
        FAKE_LIBRARY,
    )
    assert [t["sons"] for t in topics] == [
        [{"sound": "whoosh", "at": 0.0}],
        [{"sound": "ding", "at": 15.0}],
        [],
    ]
    with pytest.raises(ValueError, match="assunto 1, som 1"):
        plan_topics([{"fim": 10, "sons": [{"som": "click"}]}], FAKE_LIBRARY)


def test_every_library_sound_is_accepted_by_default():
    sounds = [{"som": name} for name in library_names()]
    [topic] = plan_topics([{"fim": 5, "sons": sounds}])
    assert [cue["sound"] for cue in topic["sons"]] == list(library_names())


def test_prepare_explainer_joins_every_topic_sound_in_video_time_for_audio_sfx():
    params = prepare_explainer(
        {
            "gravacao": "g.mp4",
            "assuntos": [
                {"fim": 20, "sons": [{"som": "whoosh"}, {"som": "ding", "em": 8}]},
                {"fim": 40, "sons": [{"som": "pop", "volume": 0.7}]},
            ],
        }
    )
    assert params["sfx"] == [
        {"sound": "whoosh", "at": 0.0},
        {"sound": "ding", "at": 8.0},
        {"sound": "pop", "at": 20.0, "volume": 0.7},
    ]
    assert prepare_explainer({"gravacao": "g.mp4", "assuntos": THREE})["sfx"] == []


def _sounds_topics() -> list[dict]:
    return [
        {"fim": 20, "fundo": "escuro", "sons": [{"som": "whoosh"}, {"som": "ding", "em": 8}]},
        {"fim": 40, "fundo": "bege", "sons": [{"som": "pop", "volume": 0.7}]},
        {"fim": 60, "fundo": "claro", "sons": [{"som": "click", "em": 3}, {"som": "riser", "em": 13.5}]},
    ]


def test_template_turns_the_topic_sounds_into_audio_sfx_at_video_time():
    project = _render(assuntos=_sounds_topics())
    assert [(cue.sound, cue.at, cue.volume) for cue in project.audio.sfx] == [
        ("whoosh", 0, 1),
        ("ding", 8, 1),
        ("pop", 20, 0.7),
        ("click", 43, 1),
        ("riser", 53.5, 1),
    ]
    assert project.audio.normalize == "two-pass"  # o resto do bloco de áudio do modelo fica como era
    planned = plan_sfx(project, [])  # sem transições no modelo: o plano é só o `audio.sfx`
    assert [(item.sound, item.at) for item in planned] == [(c.sound, c.at) for c in project.audio.sfx]


def test_a_topic_without_sounds_gives_the_same_saved_spec_as_before_sounds_existed():
    """Prova de "sai como hoje": o modelo sem a chave `sfx` (como era) e o de agora geram o mesmo JSON salvo."""
    template = find_template("explicativo")
    body = json.loads(json.dumps(template.body))
    del body["audio"]["sfx"]
    legacy = dataclasses.replace(template, body=body)
    params = {"gravacao": "gravacao.mp4", "assuntos": THREE}

    def saved(model) -> str:
        project = Project.model_validate({**render_template(model, params), "name": "igual"})
        return project.model_dump_json(indent=2, exclude_none=True)

    assert saved(template) == saved(legacy)
    assert _render().audio.sfx == []


def test_template_reports_an_unknown_sound_as_a_template_error_with_the_available_names():
    template = find_template("explicativo")
    topics = [{"fim": 5}, {"fim": 9, "sons": [{"som": "apito"}]}]
    with pytest.raises(TemplateError, match=r'explicativo.*assunto 2, som 1.*"apito".*disponíveis: whoosh'):
        render_template(template, {"gravacao": "g.mp4", "assuntos": topics})


def test_the_template_example_renders_with_its_sounds():
    template = find_template("explicativo")
    project = Project.model_validate(
        render_template(template, {"gravacao": "g.mp4", "assuntos": template.params["assuntos"].example})
    )
    assert [(cue.sound, cue.at) for cue in project.audio.sfx] == [("whoosh", 0), ("ding", 8), ("pop", 20)]


def test_the_mcp_recipe_documents_sons_and_every_library_sound():
    tools = {tool.name: tool for tool in asyncio.run(mcp_server.server.list_tools())}
    description = tools["build_explainer_video"].description
    assert "'sons'" in description and "audio.sfx" in description
    assert all(name in description for name in library_names())
