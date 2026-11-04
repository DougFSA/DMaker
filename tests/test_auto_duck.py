"""O Auto Duck sem ffmpeg: a regra da spec, as contas da curva, a expressão do ffmpeg, o grafo da mixagem e as edições."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from dmaker.domain.auto_duck import (
    AutoDuck,
    clip_points,
    duck_points,
    gain_at,
    key_regions,
    merge_runs,
    slice_points,
    sound_runs,
)
from dmaker.domain.duck_edits import add_duck, remove_duck, set_duck
from dmaker.domain.edits import EditError
from dmaker.domain.spec import AudioSettings, Music, Project
from dmaker.domain.tracks import apply_track_state
from dmaker.filtergraph.audio import audio_graph
from dmaker.filtergraph.common import Inputs
from dmaker.filtergraph.duck import DuckCurve, duck_filters, gain_expression


def rule(**fields) -> AutoDuck:
    return AutoDuck(**{"background": "MUS", "key": "VO", **fields})


def project(**audio) -> Project:
    return Project.model_validate(
        {
            "name": "duck",
            "timeline": [{"type": "clip", "src": "v.mp4", "start": 0, "end": 10}],
            "audio": audio,
        }
    )


# ---------- a regra ----------


def test_the_rule_has_the_audacity_defaults_and_stays_out_of_an_old_dump():
    default = rule()
    assert (default.amount_db, default.threshold_db, default.max_pause) == (-12.0, -30.0, 1.0)
    assert (
        default.outer_fade_down,
        default.inner_fade_down,
        default.inner_fade_up,
        default.outer_fade_up,
    ) == (0.5, 0, 0, 0.5)
    assert "ducks" not in AudioSettings().model_dump()
    assert "ducks" in AudioSettings(ducks=[default]).model_dump()


@pytest.mark.parametrize(
    "fields, expected",
    [
        ({"background": "MUS", "key": "MUS"}, "não abaixa sob ela mesma"),
        ({"background": "A2", "key": "NAR"}, "só abaixa sob outra faixa externa"),
        ({"background": "A1", "key": "A3"}, "já contém as faixas externas"),
        ({"background": "XX", "key": "VO"}, "trilha desconhecida"),
        ({"background": "MUS", "key": "VO", "amount_db": 3}, "less than or equal"),
    ],
)
def test_combinations_the_mix_cannot_do_are_refused_with_a_reason_a_layperson_can_read(fields, expected):
    with pytest.raises(ValidationError, match=expected):
        AutoDuck(**fields)


def test_every_other_combination_is_accepted():
    for background, key in [
        ("MUS", "A1"),
        ("MUS", "A2"),
        ("NAR", "VO"),
        ("A2", "A3"),
        ("A1", "NAR"),
        ("SFX", "VO"),
        ("VO", "MUS"),
    ]:
        AutoDuck(background=background, key=key)


# ---------- onde a chave soa ----------


def test_sound_runs_use_the_threshold_and_merge_across_a_short_pause():
    levels = [-60] * 10 + [-20] * 5 + [-60] * 20 + [-20] * 5 + [-60] * 60
    runs = sound_runs(levels, 0.1, -30)
    assert runs == [(1.0, 1.5), (3.5, 4.0)]
    assert merge_runs(runs, 1.0) == [(1.0, 1.5), (3.5, 4.0)]  # a pausa de 2 s é maior que 1 s
    assert merge_runs(runs, 2.0) == [(1.0, 4.0)]
    assert sound_runs([-80] * 5, 0.1, -30) == []


def test_the_pause_is_never_shorter_than_the_outer_fades():
    assert key_regions([(1.0, 1.5), (2.3, 3.0)], rule(max_pause=0.1)) == [
        (1.0, 3.0)
    ]  # 0,5 + 0,5 = 1 s > 0,8 s
    assert key_regions([(1.0, 1.5), (3.0, 4.0)], rule(max_pause=0.1)) == [(1.0, 1.5), (3.0, 4.0)]


# ---------- a curva de ganho ----------


def test_the_curve_goes_down_before_the_key_and_back_up_after_it():
    points = duck_points([(3.0, 5.0)], rule(amount_db=-12))
    assert points == [(2.5, 0.0), (3.0, -12.0), (5.0, -12.0), (5.5, 0.0)]
    assert gain_at(points, 2.0) == 0.0 and gain_at(points, 4.0) == -12.0 and gain_at(points, 6.0) == 0.0
    assert gain_at(points, 2.75) == pytest.approx(-6.0)  # reta em dB


def test_the_inner_fades_run_inside_the_region_and_never_pass_half_of_it():
    points = duck_points([(3.0, 4.0)], rule(inner_fade_down=0.2, inner_fade_up=5.0))
    assert points[1] == (3.2, -12.0) and points[2] == (3.5, -12.0)  # a subida de dentro limitou-se a metade


def test_a_fade_that_would_start_before_zero_starts_at_the_gain_the_curve_has_there():
    points = duck_points([(0.2, 1.0)], rule())
    assert points[0][0] == 0.0  # nenhum instante negativo
    assert gain_at(points, 0.0) == pytest.approx(-12.0 * (0.5 - 0.2) / 0.5)


def test_every_ramp_lasts_at_least_five_milliseconds():
    points = duck_points([(1.0, 2.0)], rule(outer_fade_down=0, outer_fade_up=0))
    assert points[1][0] - points[0][0] >= 0.005 - 1e-9 and points[3][0] - points[2][0] >= 0.005 - 1e-9


def test_a_clip_only_gets_the_part_of_the_curve_that_falls_in_it_in_source_time():
    points = duck_points([(10.0, 12.0), (50.0, 52.0)], rule())
    assert slice_points(points, 20.0, 30.0) == []  # nenhuma região cai no clipe: nada vai para o hash dele
    piece = slice_points(points, 9.0, 13.0, scale=2.0)  # velocidade 2: segundos de fonte
    assert piece[0] == (1.0, 0.0) and (piece[-1][0], piece[-1][1]) == (8.0, gain_at(points, 13.0))
    assert gain_at(piece, 2.0 * (11.0 - 9.0)) == pytest.approx(-12.0)
    assert clip_points([], 0, 1) == []


# ---------- a expressão do ffmpeg ----------


def evaluate(expression: str, instant: float) -> float:
    """Avalia a expressão (só `if`, `lt`, `t`, números e +-*) com o Python, para provar o que o ffmpeg vai calcular."""
    source = expression.replace("if(", "_if(").replace("lt(", "_lt(")
    return float(
        eval(source, {"_if": lambda c, a, b: a if c else b, "_lt": lambda a, b: a < b, "t": instant})
    )


def test_the_balanced_expression_equals_the_curve_everywhere():
    regions = [(1.0 + 3.0 * k, 2.0 + 3.0 * k) for k in range(40)]
    points = duck_points(regions, rule())
    expression = gain_expression(points)
    for instant in np.linspace(0, 125, 801):
        assert evaluate(expression, float(instant)) == pytest.approx(
            gain_at(points, float(instant)), abs=1e-4
        )


def test_the_expression_nests_logarithmically_so_300_regions_do_not_pile_up_ifs():
    points = duck_points(
        [(2.0 * k, 2.0 * k + 0.5) for k in range(300)], rule(outer_fade_down=0.1, outer_fade_up=0.1)
    )
    expression = gain_expression(points)
    depth = deepest = 0
    for char in expression:
        depth += char == "("
        depth -= char == ")"
        deepest = max(deepest, depth)
    assert len(points) > 1000 and deepest < 120  # uma escada teria mais de mil níveis


def test_filters_are_empty_for_no_curve_constant_for_a_flat_one_and_framed_for_the_rest():
    assert duck_filters([]) == []
    assert duck_filters([(0.0, -6.0), (5.0, -6.0)]) == ["volume=-6.000000dB"]
    assert duck_filters([(1.0, 0.0), (2.0, -12.0)])[0] == "asetnsamples=n=256:p=0"


# ---------- o grafo da mixagem ----------


def mix(audio: AudioSettings, curves=(), **kwargs) -> list[str]:
    lines: list[str] = []
    inputs = Inputs()
    audio_graph(lines, inputs, "[ta0]", audio, Path("m.wav"), 12.0, duck_curves=curves, **kwargs)
    return lines


def test_without_a_rule_the_graph_is_the_old_one_with_its_sidechain():
    audio = AudioSettings(music=Music(src="m.wav"))
    assert mix(audio) == mix(audio, ())
    text = ";".join(mix(audio))
    assert "sidechaincompress" in text and "pow(10" not in text


def test_the_graph_of_an_old_project_with_music_ducking_is_byte_for_byte_the_one_from_before_the_card():
    """Gerado com o código da `develop` anterior ao DMK-52 (o mesmo projeto, a mesma entrada): o `music.ducking` não mudou."""
    audio = AudioSettings(music=Music(src="m.wav"))
    assert mix(audio) == [
        "[0:a]atrim=start=0.000:duration=12.000,asetpts=PTS-STARTPTS,aresample=48000,"
        "aformat=sample_fmts=fltp:channel_layouts=stereo,volume=0.180,afade=t=in:st=0:d=1.000,"
        "afade=t=out:st=10.000:d=2.000[mus0]",
        "[ta0]asplit=2[voice][sc]",
        "[sc]apad[scp]",
        "[mus0]apad[musp]",
        "[musp][scp]sidechaincompress=threshold=0.0200:ratio=6:attack=20:release=350:makeup=1:level_sc=1[musd]",
        "[voice][musd]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[amix]",
        "[amix]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a_norm]",
        "[a_norm]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[aout]",
    ]


def test_a_music_rule_replaces_the_sidechain_and_lowers_only_the_music():
    audio = AudioSettings(music=Music(src="m.wav"))
    curve = DuckCurve("MUS", tuple(duck_points([(3.0, 5.0)], rule())))
    text = ";".join(mix(audio, [curve]))
    assert "sidechaincompress" not in text and "[mus_duck]" in text
    assert "amix=inputs=2" in text


def test_a_rule_for_another_track_does_not_touch_the_music_sidechain():
    audio = AudioSettings(music=Music(src="m.wav"))
    curve = DuckCurve("NAR", tuple(duck_points([(3.0, 5.0)], rule())))
    assert ";".join(mix(audio, [curve])) == ";".join(mix(audio))  # sem narração, a regra não acrescenta linha


# ---------- estado de trilha e edição ----------


def test_muting_a_track_drops_its_rules_and_renumbers_the_external_ones():
    base = {
        "tracks": [{"source": "a"}, {"source": "b"}, {"source": "c"}],
        "ducks": [{"background": "A3", "key": "A4"}, {"background": "A2", "key": "A4"}],
    }
    spec = Project.model_validate(
        {
            "name": "x",
            "sources": {name: {"src": f"{name}.wav", "sync": 0} for name in "abc"},
            "timeline": [{"type": "clip", "source": "a", "start": 0, "end": 1}],
            "audio": base,
            "tracks": {"A2": {"muted": True}},
        }
    )
    ducks = apply_track_state(spec).audio.ducks
    assert [(item.background, item.key) for item in ducks] == [
        ("A2", "A3")
    ]  # A3->A2, A4->A3; a regra da A2 muda caiu


def test_edits_add_set_and_remove_rules_and_refuse_a_bad_pair():
    start = project(narration=[{"text": "oi"}], voiceover=[{"src": "v.wav"}])
    added = add_duck(start, {"background": "MUS", "key": "VO", "amount_db": -9})
    assert added.audio.ducks[0].amount_db == -9
    changed = set_duck(added, 0, {"amount_db": -15})
    assert (changed.audio.ducks[0].amount_db, changed.audio.ducks[0].key) == (-15, "VO")
    assert remove_duck(changed, 0).audio.ducks == []
    with pytest.raises(EditError, match="só abaixa sob outra faixa externa"):
        add_duck(start, {"background": "A2", "key": "NAR"})
    with pytest.raises(EditError, match="informe"):
        add_duck(start, {"background": "MUS"})
    with pytest.raises(EditError, match="fora do intervalo"):
        remove_duck(start, 0)


def test_a_long_clip_graph_goes_to_a_file_and_a_short_one_stays_on_the_command_line(tmp_path):
    from dmaker.media.ffmpeg import FFmpegCommand
    from dmaker.pipeline.auto_duck import spill_long_graph

    short = FFmpegCommand(["-i", "a.wav", "-filter_complex", "[0:a]anull[o]", "-map", "[o]", "o.wav"])
    assert spill_long_graph(short, tmp_path, "g.txt") is short
    curve = duck_points([(2.0 * k, 2.0 * k + 0.5) for k in range(200)], rule())
    graph = "[0:a]" + ",".join(duck_filters(curve)) + "[o]"
    long = FFmpegCommand(["-i", "a.wav", "-filter_complex", graph, "-map", "[o]", "o.wav"])
    spilled = spill_long_graph(long, tmp_path, "g.txt")
    assert graph not in spilled.args and (tmp_path / "g.txt").read_text(encoding="utf-8") == graph
    assert spilled.args[-3:] == ["-map", "[o]", "o.wav"]
