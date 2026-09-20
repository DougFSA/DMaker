"""Corte automático de multicâmera por regras: alternância por cadência, fases por termo na
transcrição, corte atraído para pausas e respeito à cobertura real de cada câmera."""

from __future__ import annotations

import pytest

from dmaker.domain.multicam import (
    Coverage,
    MulticamPlan,
    PhaseRule,
    Speech,
    default_wedding_phases,
    phase_windows,
    plan_cuts,
)


def _spans(clips):
    return [(c.camera, round(c.start, 3), round(c.end, 3)) for c in clips]


def test_alternation_without_speech_follows_cadence():
    plan = MulticamPlan(cameras=("a", "b"), main="a", audio="a", cadence=(45.0, 20.0), min_clip=4.0)
    coverage = [Coverage("a", 0, 1000), Coverage("b", 0, 1000)]

    clips, warnings = plan_cuts(plan, coverage, [], start=0.0, end=140.0)

    assert warnings == []
    assert _spans(clips) == [
        ("a", 0, 45),
        ("b", 45, 65),
        ("a", 65, 110),
        ("b", 110, 130),
        ("a", 130, 140),
    ]
    assert clips[-1].end - clips[-1].start >= plan.min_clip
    for prev, nxt in zip(clips, clips[1:], strict=False):
        assert prev.end == nxt.start


def test_cut_is_attracted_to_nearby_pause():
    plan = MulticamPlan(
        cameras=("a", "b"), main="a", audio="a", cadence=(10.0, 5.0), min_clip=1.0, snap_window=2.0
    )
    coverage = [Coverage("a", 0, 20), Coverage("b", 0, 20)]
    speech = [Speech(0.0, 9.0, "ola"), Speech(11.5, 20.0, "mundo")]  # pausa de 9 a 11.5 (meio: 10.25)

    clips, warnings = plan_cuts(plan, coverage, speech, start=0.0, end=20.0)

    assert warnings == []
    assert _spans(clips) == [("a", 0, 10.25), ("b", 10.25, 15), ("a", 15, 20)]


def test_phase_recognized_by_term_changes_main_camera_and_cadence():
    plan = MulticamPlan(
        cameras=("a", "b"),
        main="a",
        audio="a",
        cadence=(10.0, 4.0),
        min_clip=1.0,
        phases=(PhaseRule("consentimento", ("vos pergunto",), main="b", cadence=(6.0, 3.0)),),
    )
    coverage = [Coverage("a", 0, 40), Coverage("b", 0, 40)]
    # acento e caixa diferentes do termo da regra ("vos pergunto")
    speech = [Speech(20.0, 22.0, "Agora, VÓS PERGUNTO, se é da vossa livre vontade")]

    clips, warnings = plan_cuts(plan, coverage, speech, start=0.0, end=40.0)

    assert warnings == []
    labels = [c.label for c in clips]
    assert labels == [
        "geral",
        "geral",
        "geral",
        "consentimento",
        "consentimento",
        "consentimento",
        "consentimento",
        "consentimento",
    ]
    assert _spans(clips) == [
        ("a", 0, 10),
        ("b", 10, 14),
        ("a", 14, 20),
        ("b", 20, 26),
        ("a", 26, 29),
        ("b", 29, 35),
        ("a", 35, 38),
        ("b", 38, 40),
    ]


def test_coverage_gap_in_chosen_camera_switches_to_the_other():
    plan = MulticamPlan(cameras=("a", "b"), main="a", audio="a", cadence=(10.0, 5.0), min_clip=1.0)
    coverage = [Coverage("a", 0, 8), Coverage("a", 12, 30), Coverage("b", 0, 30)]

    clips, warnings = plan_cuts(plan, coverage, [], start=0.0, end=30.0)

    assert warnings == []
    # o clipe da câmera a (0-10) é partido em 8: dali em diante, sem cobertura de a, usa b
    covering_at = {round(c.start, 3): c.camera for c in clips}
    assert covering_at[0.0] == "a"
    assert covering_at[8.0] == "b"
    # continuidade total, sem sobreposição nem lacuna
    for prev, nxt in zip(clips, clips[1:], strict=False):
        assert prev.end == nxt.start
    assert clips[0].end == pytest.approx(8.0)
    assert clips[-1].end == pytest.approx(30.0)


def test_coverage_gap_in_all_cameras_is_skipped_with_warning():
    plan = MulticamPlan(cameras=("a", "b"), main="a", audio="a", cadence=(10.0, 5.0), min_clip=1.0)
    # nenhuma câmera cobre de 30 a 35
    coverage = [Coverage("a", 0, 8), Coverage("a", 12, 30), Coverage("b", 0, 30)]

    clips, warnings = plan_cuts(plan, coverage, [], start=0.0, end=35.0)

    assert any("sem imagem de 30.00 a 35.00" in w for w in warnings)
    assert clips[-1].end == pytest.approx(30.0)


def test_mute_follows_audio_camera_coverage_regardless_of_visible_camera():
    plan = MulticamPlan(cameras=("a", "b"), main="a", audio="b", cadence=(10.0, 5.0), min_clip=1.0)
    coverage = [Coverage("a", 0, 20), Coverage("b", 0, 10)]  # audio (b) só cobre até 10

    clips, warnings = plan_cuts(plan, coverage, [], start=0.0, end=20.0)

    assert warnings == []
    mutes = [(round(c.start, 3), round(c.end, 3), c.mute) for c in clips]
    assert (0.0, 10.0, True) in mutes
    assert all(mute is False for start, end, mute in mutes if start >= 10.0)


def test_short_trailing_clip_is_merged_into_the_previous_neighbor():
    plan = MulticamPlan(cameras=("a", "b"), main="a", audio="a", cadence=(10.0, 5.0), min_clip=4.0)
    coverage = [Coverage("a", 0, 33), Coverage("b", 0, 33)]

    clips, warnings = plan_cuts(plan, coverage, [], start=0.0, end=33.0)

    assert warnings == []
    assert _spans(clips) == [("a", 0, 10), ("b", 10, 15), ("a", 15, 25), ("b", 25, 33)]
    for prev, nxt in zip(clips, clips[1:], strict=False):
        assert prev.end == nxt.start
    assert clips[-1].end == pytest.approx(33.0)


def test_default_wedding_phases_recognizes_votos_and_leitura():
    plan = MulticamPlan(
        cameras=("a", "b"),
        main="a",
        audio="a",
        cadence=(100.0, 100.0),
        min_clip=1.0,
        phases=default_wedding_phases(),
    )
    coverage = [Coverage("a", 0, 80), Coverage("b", 0, 80)]
    speech = [
        Speech(5.0, 7.0, "Leitura do livro dos Gênesis"),
        Speech(50.0, 53.0, "Eu, Daniel, te recebo, Bruna"),
    ]

    clips, warnings = plan_cuts(plan, coverage, speech, start=0.0, end=80.0)

    assert warnings == []
    assert [c.label for c in clips] == ["geral", "leitura", "votos"]
    assert _spans(clips) == [("a", 0, 5), ("a", 5, 50), ("a", 50, 80)]


def test_repeated_term_of_the_current_phase_does_not_reopen_it():
    """Quatro casais dizem "te recebo" em sequência: a fase votos abre uma vez só, sem reiniciar a
    cadência a cada fala (o que picotaria o corte em clipes curtos)."""
    plan = MulticamPlan(
        cameras=("a", "b"),
        main="a",
        audio="a",
        cadence=(100.0, 100.0),
        min_clip=1.0,
        phases=(PhaseRule("votos", ("te recebo",), main="b", cadence=(60.0, 10.0)),),
    )
    speech = [Speech(10.0 + 20.0 * k, 12.0 + 20.0 * k, "Eu te recebo como esposa") for k in range(4)]

    windows = phase_windows(plan, speech, 0.0, 200.0)

    assert [w[0] for w in windows] == ["geral", "votos"]
    assert windows[1][1] == 10.0


def test_an_earlier_phase_does_not_reopen_after_a_later_one():
    """ "Em nome do Pai" dito a cada troca de alianças não volta para a saudação: o rito só anda."""
    plan = MulticamPlan(
        cameras=("a", "b"),
        main="a",
        audio="a",
        cadence=(100.0, 100.0),
        min_clip=1.0,
        phases=(
            PhaseRule("saudacao", ("em nome do pai",)),
            PhaseRule("aliancas", ("recebe esta alianca",)),
        ),
    )
    speech = [
        Speech(5.0, 7.0, "Em nome do Pai, do Filho e do Espírito Santo"),
        Speech(50.0, 52.0, "Recebe esta aliança em sinal do meu amor"),
        Speech(60.0, 62.0, "Em nome do Pai, do Filho e do Espírito Santo"),
    ]

    windows = phase_windows(plan, speech, 0.0, 100.0)

    assert [w[0] for w in windows] == ["geral", "saudacao", "aliancas"]
