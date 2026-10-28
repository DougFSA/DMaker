"""Operações de edição pontual: as funções puras em domain/edits.py e o dispatcher em pipeline/edits.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.edits import (
    EditError,
    duplicate_overlay,
    duplicate_segment,
    insert_segment,
    move_segment,
    remove_overlay,
    remove_segment,
    restore_gap,
    set_field,
    set_overlay_span,
    split_segment,
    trim_segment,
)
from dmaker.domain.spec import Project
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.edits import EDIT_OPERATIONS, apply_edit


def fake_prober(path: Path) -> MediaInfo:
    if path.suffix == ".png":
        return MediaInfo(path, 0.0, 1000, 620, 0.0, True, False, True)
    return MediaInfo(path, 5.0, 1920, 1080, 30.0, True, True, False)


def make_project(tmp_path: Path, timeline: list | None = None) -> Project:
    spec = {
        "name": "edits-teste",
        "timeline": timeline
        or [
            {
                "type": "clip",
                "src": "a.mp4",
                "start": 0,
                "end": 4,
                "speed": 2.0,
                "transition": {"type": "fade", "duration": 0.3},
            },
            {
                "type": "card",
                "title": "Cartão",
                "duration": 1.0,
                "transition": {"type": "fade", "duration": 0.2},
            },
            {"type": "image", "src": "b.png", "duration": 2.0},
        ],
        "overlays": [
            {"type": "text", "text": "Oi", "start": 0, "end": 2},
            {"type": "progress-bar"},
        ],
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    return project


DURATIONS = [2.0, 1.0, 2.0]  # clip (4s / speed 2), card 1s, imagem 2s


def touch_sources(tmp_path: Path) -> None:
    """Cria os arquivos que a timeline de `make_project` referencia (o prober é falso, mas
    `resolve_sources` confere que o arquivo existe antes de chamá-lo)."""
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "b.png").write_bytes(b"x")


# ---------- trechos ----------


def test_split_clip_with_speed(tmp_path):
    project = make_project(tmp_path)
    new = split_segment(project, 0, 1.0, DURATIONS)
    assert len(new.timeline) == 4
    first, second = new.timeline[0], new.timeline[1]
    assert first.start == 0 and first.end == 2.0  # start + at*speed
    assert second.start == 2.0 and second.end == 4  # end original preservado
    assert first.transition is not None and second.transition is None  # transição fica no primeiro
    assert second.speed == 2.0 and second.src == "a.mp4"  # demais campos copiados
    assert new.base_dir == project.base_dir


def test_split_card_divides_duration(tmp_path):
    project = make_project(tmp_path)
    new = split_segment(project, 1, 0.4, DURATIONS)
    first, second = new.timeline[1], new.timeline[2]
    assert first.duration == pytest.approx(0.4)
    assert second.duration == pytest.approx(0.6)
    assert second.transition is None  # o segundo trecho não herda a transição de entrada


def test_split_fade_out_goes_to_second_half(tmp_path):
    timeline = [
        {"type": "card", "title": "Único", "duration": 2.0, "fade_out": 0.5},
    ]
    project = make_project(tmp_path, timeline)
    new = split_segment(project, 0, 1.0, [2.0])
    assert new.timeline[0].fade_out == 0.0
    assert new.timeline[1].fade_out == 0.5


def test_split_rejects_out_of_range_at(tmp_path):
    project = make_project(tmp_path)
    with pytest.raises(EditError):
        split_segment(project, 0, 5.0, DURATIONS)
    with pytest.raises(EditError):
        split_segment(project, 0, 0.0, DURATIONS)


def test_remove_last_segment_errors(tmp_path):
    project = make_project(tmp_path, [{"type": "card", "title": "Só este", "duration": 1.0}])
    with pytest.raises(EditError):
        remove_segment(project, 0)


def test_remove_segment_ripples(tmp_path):
    project = make_project(tmp_path)
    new = remove_segment(project, 1)
    assert len(new.timeline) == 2
    assert new.timeline[0].type == "clip" and new.timeline[1].type == "image"


def test_remove_segment_invalid_index(tmp_path):
    project = make_project(tmp_path)
    with pytest.raises(EditError):
        remove_segment(project, 99)


def test_move_segment(tmp_path):
    project = make_project(tmp_path)
    new = move_segment(project, 0, 2)
    assert [s.type for s in new.timeline] == ["card", "image", "clip"]


def test_trim_clip_in_and_out(tmp_path):
    project = make_project(tmp_path)
    # aparar a entrada 0.5s de tempo final (speed 2 -> 1s no arquivo)
    trimmed_in = trim_segment(project, 0, "in", 0.5, DURATIONS, media_duration=5.0)
    assert trimmed_in.timeline[0].start == pytest.approx(1.0)
    # aparar a saída -0.5s de tempo final
    trimmed_out = trim_segment(project, 0, "out", -0.5, DURATIONS, media_duration=5.0)
    assert trimmed_out.timeline[0].end == pytest.approx(3.0)


def test_trim_clamps_to_media_and_min_duration(tmp_path):
    project = make_project(tmp_path)
    # tentar aparar a saída muito além da mídia: fica no limite (end = media_duration)
    trimmed = trim_segment(project, 0, "out", 100.0, DURATIONS, media_duration=5.0)
    assert trimmed.timeline[0].end == pytest.approx(5.0)
    # tentar aparar a entrada além do fim: fica em pelo menos 0.1s de duração final
    trimmed_in = trim_segment(project, 0, "in", 100.0, DURATIONS, media_duration=5.0)
    seg = trimmed_in.timeline[0]
    assert (seg.end - seg.start) / seg.speed == pytest.approx(0.1)
    # nunca abaixo de zero
    trimmed_neg = trim_segment(project, 0, "in", -100.0, DURATIONS, media_duration=5.0)
    assert trimmed_neg.timeline[0].start == 0.0


def test_trim_image_in_keeps_end_reduces_duration(tmp_path):
    project = make_project(tmp_path)
    trimmed = trim_segment(project, 2, "in", 0.5, DURATIONS, media_duration=None)
    assert trimmed.timeline[2].duration == pytest.approx(1.5)
    trimmed_out = trim_segment(project, 2, "out", 0.5, DURATIONS, media_duration=None)
    assert trimmed_out.timeline[2].duration == pytest.approx(2.5)
    trimmed_floor = trim_segment(project, 2, "in", 100.0, DURATIONS, media_duration=None)
    assert trimmed_floor.timeline[2].duration == pytest.approx(0.1)


def test_duplicate_segment_drops_transition(tmp_path):
    project = make_project(tmp_path)
    new = duplicate_segment(project, 1)
    assert len(new.timeline) == 4
    original, copy = new.timeline[1], new.timeline[2]
    assert original.transition is not None
    assert copy.transition is None
    assert copy.title == original.title


def test_insert_segment(tmp_path):
    project = make_project(tmp_path)
    new = insert_segment(project, 1, {"type": "card", "title": "Novo", "duration": 1.5})
    assert len(new.timeline) == 4
    assert new.timeline[1].title == "Novo"


def test_insert_invalid_segment_errors(tmp_path):
    project = make_project(tmp_path)
    with pytest.raises(EditError):
        insert_segment(project, 1, {"type": "card"})  # falta o title obrigatório
    with pytest.raises(EditError):
        insert_segment(project, 1, {"type": "not-a-type"})


# ---------- sobreposições ----------


def test_overlay_span_remove_duplicate(tmp_path):
    project = make_project(tmp_path)
    spanned = set_overlay_span(project, 0, 1.0, 3.0)
    assert spanned.overlays[0].start == 1.0 and spanned.overlays[0].end == 3.0

    duplicated = duplicate_overlay(project, 0)
    assert len(duplicated.overlays) == 3
    assert duplicated.overlays[1].text == duplicated.overlays[0].text

    removed = remove_overlay(project, 1)
    assert len(removed.overlays) == 1
    assert removed.overlays[0].type == "text"


def test_overlay_span_on_progress_bar_errors(tmp_path):
    project = make_project(tmp_path)
    with pytest.raises(EditError):
        set_overlay_span(project, 1, 0.0, 2.0)  # progress-bar não tem start/end


def test_overlay_invalid_index_errors(tmp_path):
    project = make_project(tmp_path)
    with pytest.raises(EditError):
        remove_overlay(project, 99)


# ---------- set_field ----------


def test_set_field_updates_nested_value(tmp_path):
    project = make_project(tmp_path)
    new = set_field(project, "timeline.0.speed", 1.5)
    assert new.timeline[0].speed == 1.5
    new2 = set_field(project, "overlays.0.style.size", 48)
    assert new2.overlays[0].style.size == 48


def test_set_field_none_reverts_to_default(tmp_path):
    project = make_project(tmp_path)
    with_size = set_field(project, "overlays.0.style.size", 48)
    back = set_field(with_size, "overlays.0.style.size", None)
    assert back.overlays[0].style.size is None


def test_set_field_invalid_value_errors(tmp_path):
    project = make_project(tmp_path)
    with pytest.raises(EditError):
        set_field(project, "timeline.0.speed", 999)  # acima do limite (le=8)


def test_set_field_invalid_path_errors(tmp_path):
    project = make_project(tmp_path)
    with pytest.raises(EditError):
        set_field(project, "timeline.99.speed", 1.0)
    with pytest.raises(EditError):
        set_field(project, "nao_existe.campo", 1.0)


def test_set_field_creates_missing_track_state(tmp_path):
    """`tracks.<id>` normalmente não existe até a primeira vez que a interface muda/oculta uma
    trilha: set_field precisa criar o dicionário no caminho, não só o campo final."""
    project = make_project(tmp_path)
    assert project.tracks == {}
    new = set_field(project, "tracks.A2.muted", True)
    assert new.tracks["A2"].muted is True
    assert new.tracks["A2"].hidden is False
    newer = set_field(new, "tracks.TX.hidden", True)
    assert newer.tracks["A2"].muted is True  # a trilha existente não se perde
    assert newer.tracks["TX"].hidden is True


def test_set_field_source_sync(tmp_path):
    spec = {
        "name": "multi",
        "sources": {"cam1": {"src": "cam1.mp4"}, "cam2": {"src": "cam2.mp4", "sync": "auto"}},
        "timeline": [{"type": "clip", "source": "cam1", "start": 0, "end": 2}],
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    new = set_field(project, "sources.cam2.sync", 1.25)
    assert new.sources["cam2"].sync == 1.25


# ---------- apply_edit (pipeline) ----------


def test_apply_edit_dispatches_split(tmp_path):
    project = make_project(tmp_path)
    touch_sources(tmp_path)
    new = apply_edit(project, {"type": "split", "index": 0, "at": 1.0}, prober=fake_prober)
    assert len(new.timeline) == 4


def test_apply_edit_clamps_trim_to_probed_media_duration(tmp_path):
    project = make_project(tmp_path)
    touch_sources(tmp_path)  # o probe é falso; só precisa existir
    new = apply_edit(project, {"type": "trim", "index": 0, "side": "out", "delta": 10.0}, prober=fake_prober)
    assert new.timeline[0].end == pytest.approx(5.0)  # duração do arquivo fake (fake_prober)


def test_apply_edit_unknown_operation_errors(tmp_path):
    project = make_project(tmp_path)
    touch_sources(tmp_path)
    with pytest.raises(EditError):
        apply_edit(project, {"type": "voar"}, prober=fake_prober)


def test_apply_edit_missing_param_errors(tmp_path):
    project = make_project(tmp_path)
    touch_sources(tmp_path)
    with pytest.raises(EditError):
        apply_edit(project, {"type": "split", "index": 0}, prober=fake_prober)  # falta "at"


def test_edit_operations_registry_is_open_for_extension():
    assert {
        "split",
        "remove",
        "move",
        "trim",
        "duplicate",
        "insert",
        "overlay_span",
        "overlay_remove",
        "overlay_duplicate",
        "set_field",
    } <= EDIT_OPERATIONS.keys()


# ---------- restore_gap: desfazer um corte automático ----------


def cut_project(tmp_path: Path) -> Project:
    """Gravação cortada em três clipes: [1, 3], [5, 8] e [10, até o fim]; os cortes são 3 a 5 e 8 a 10."""
    clips = [
        {"type": "clip", "src": "a.mp4", "start": 1.0, "end": 3.0, "audio_fade": 0.01},
        {"type": "clip", "src": "a.mp4", "start": 5.0, "end": 8.0, "audio_fade": 0.01},
        {"type": "clip", "src": "a.mp4", "start": 10.0, "audio_fade": 0.01},
    ]
    return make_project(tmp_path, clips)


def test_restore_gap_joins_the_two_clips_around_the_cut(tmp_path):
    restored = restore_gap(cut_project(tmp_path), 3.0, 5.0)
    assert [(c.start, c.end) for c in restored.timeline] == [(1.0, 8.0), (10.0, None)]


def test_restore_gap_can_undo_in_any_order(tmp_path):
    project = cut_project(tmp_path)
    after_second = restore_gap(restore_gap(project, 8.0, 10.0), 3.0, 5.0)
    assert [(c.start, c.end) for c in after_second.timeline] == [(1.0, None)]


def test_restore_gap_at_the_start_and_at_the_end_extends_the_edge_clip(tmp_path):
    project = cut_project(tmp_path)
    assert restore_gap(project, 0.0, 1.0).timeline[0].start == 0.0
    tail = make_project(tmp_path, [{"type": "clip", "src": "a.mp4", "start": 1.0, "end": 3.0}])
    assert restore_gap(tail, 3.0, None).timeline[0].end is None


def test_restore_gap_keeps_the_fade_out_of_the_last_joined_clip(tmp_path):
    clips = [
        {"type": "clip", "src": "a.mp4", "start": 0.0, "end": 2.0},
        {"type": "clip", "src": "a.mp4", "start": 4.0, "end": 6.0, "fade_out": 0.5},
    ]
    (joined,) = restore_gap(make_project(tmp_path, clips), 2.0, 4.0).timeline
    assert joined.fade_out == 0.5 and joined.end == 6.0


def test_restore_gap_does_not_mutate_the_original(tmp_path):
    project = cut_project(tmp_path)
    restore_gap(project, 3.0, 5.0)
    assert len(project.timeline) == 3


def test_restore_gap_refuses_when_the_neighbours_are_gone_or_changed(tmp_path):
    project = cut_project(tmp_path)
    with pytest.raises(EditError, match="não está mais"):
        restore_gap(project, 20.0, 30.0)
    separated = insert_segment(project, 1, {"type": "card", "title": "no meio", "duration": 1.0})
    with pytest.raises(EditError, match="vizinhos"):
        restore_gap(separated, 3.0, 5.0)
    faster = set_field(project, "timeline.1.speed", 2.0)
    with pytest.raises(EditError, match="vizinhos"):
        restore_gap(faster, 3.0, 5.0)


def test_restore_gap_only_touches_clips_of_the_given_recording(tmp_path):
    two_recordings = [
        {"type": "clip", "src": "b.mp4", "start": 0.0, "end": 3.0},
        {"type": "clip", "src": "a.mp4", "start": 5.0, "end": 8.0},
    ]
    project = make_project(tmp_path, two_recordings)
    with pytest.raises(EditError, match="vizinhos"):  # sem `origin`, os dois lados parecem o mesmo corte
        restore_gap(project, 3.0, 5.0)
    restored = restore_gap(project, 3.0, 5.0, origin="a.mp4")
    assert [(c.start, c.end) for c in restored.timeline] == [(0.0, 3.0), (3.0, 8.0)]
