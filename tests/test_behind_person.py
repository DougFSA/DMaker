"""Texto atrás da pessoa (DMK-28), sem ffmpeg de verdade: o campo da spec, as contas puras da janela da linha do
tempo, os grafos, o ajuste do alfa e o pipeline com recortador, runner e probe falsos. O que só o render real
mostra (ordem das camadas, borda sem halo, quadro a quadro) fica em `test_behind_person_render.py`."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from dmaker.domain.spec import Project, TextOverlay, Transition
from dmaker.domain.timeline import (
    behind_person_intervals,
    frame_range,
    merge_intervals,
    timeline_spans,
    timeline_window,
)
from dmaker.filtergraph.behind_person import (
    AssBehindLayer,
    ResolvedPersonLayer,
    behind_person_graph,
)
from dmaker.filtergraph.common import Inputs
from dmaker.filtergraph.person_layer import floor_seconds, person_layer_command, window_command
from dmaker.filtergraph.timeline import timeline_graph
from dmaker.media.ffmpeg import FFmpegError, RecordingRunner
from dmaker.media.matting import (
    ALPHA_CEILING,
    ALPHA_FLOOR,
    INTERIOR_FROM,
    PersonRequest,
    interior_weight,
    person_rgba,
    refine_alpha,
)
from dmaker.media.probe import MediaInfo
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.lint import lint
from dmaker.pipeline.person_layer import PERSON_LAYER_VERSION, WARMUP_FRAMES, PersonLayerBuilder
from tests.test_audiogram import GRAPH_BEFORE_DMK_34, _render_unit
from tests.test_pipeline_unit import LOUDNORM_JSON, FakeTranscriber, touch_output

FADE = Transition(type="fade", duration=0.5)


# ---------- o campo da spec ----------


def test_the_text_layer_defaults_to_front_and_takes_behind_person():
    assert TextOverlay(text="x").layer == "front"
    behind = TextOverlay.model_validate({"type": "text", "text": "x", "layer": "behind-person"})
    assert behind.layer == "behind-person"
    assert behind.model_dump(mode="json")["layer"] == "behind-person"
    with pytest.raises(ValidationError):
        TextOverlay.model_validate({"type": "text", "text": "x", "layer": "middle"})


def test_the_layer_survives_a_save_and_load_of_the_project(tmp_path: Path):
    spec = {
        "name": "camadas",
        "timeline": [{"type": "card", "title": "x", "duration": 1}],
        "overlays": [{"type": "text", "text": "ATRÁS", "layer": "behind-person"}],
    }
    path = Project.model_validate(spec).save(tmp_path / "spec.json")
    assert Project.load(path).overlays[0].layer == "behind-person"


# ---------- intervalos ----------


def test_overlapping_and_touching_intervals_merge_and_separate_ones_stay_apart():
    assert merge_intervals([(5, 7), (0, 2), (1.5, 3), (3, 4)]) == [(0, 4), (5, 7)]
    assert merge_intervals([]) == []
    assert merge_intervals([(0, 10), (2, 3)]) == [(0, 10)]


def test_only_behind_person_texts_make_intervals_and_they_are_cut_at_the_end_of_the_video():
    overlays = [
        TextOverlay(text="a", start=1, end=3, layer="behind-person"),
        TextOverlay(text="b", start=2, end=4, layer="behind-person"),
        TextOverlay(text="frente", start=0, end=9),
        TextOverlay(text="c", start=8, layer="behind-person"),  # sem fim: vai até o fim do vídeo
        TextOverlay(text="d", start=12, end=13, layer="behind-person"),  # depois do fim
    ]
    assert behind_person_intervals(overlays, 10.0) == [(1, 4), (8, 10.0)]
    assert behind_person_intervals([TextOverlay(text="x")], 10.0) == []


def test_frame_range_follows_the_libass_rule_even_when_the_product_is_not_exact():
    assert frame_range(1.0, 3.0, 30) == (30, 90)
    assert frame_range(0.1, 0.3, 30) == (3, 9)  # 0.1 * 30 = 3.0000000000000004
    assert frame_range(1.01, 1.02, 30) == (31, 31)  # nenhum quadro cai dentro: vazio
    assert frame_range(0.0, 1 / 30, 30) == (0, 1)


# ---------- janela da linha do tempo ----------


def test_a_window_inside_a_long_clip_seeks_to_just_before_the_warmup():
    window = timeline_window([10.0], [None], 4.0, 7.0, 30, WARMUP_FRAMES)
    assert window is not None
    assert (window.first, window.last, window.first_frame, window.frame_count) == (0, 0, 120, 90)
    assert window.warmup_frames == 12 and window.rendered_frames == 102
    assert window.seek == pytest.approx(3.6) and window.origin == pytest.approx(3.6)
    assert window.durations == (pytest.approx(6.4),) and window.transitions == (None,)
    assert window.overlaps == ()


def test_a_window_at_the_start_has_no_seek_and_the_warmup_only_as_long_as_what_exists_before():
    at_start = timeline_window([10.0], [None], 0.0, 2.0, 30, 12)
    assert at_start and (at_start.seek, at_start.warmup_frames, at_start.origin) == (0.0, 0, 0.0)
    close = timeline_window([10.0], [None], 0.2, 1.0, 30, 12)
    assert close and (close.seek, close.warmup_frames, close.first_frame) == (0.0, 6, 6)


def test_a_window_that_crosses_a_transition_takes_both_clips_and_keeps_the_final_offsets():
    durations, transitions = [3.0, 3.0], [None, FADE]
    window = timeline_window(durations, transitions, 2.6, 3.4, 30, 12)
    assert window is not None and (window.first, window.last) == (0, 1)
    assert window.transitions == (None, FADE) and window.seek == pytest.approx(2.2)
    assert window.overlaps == (pytest.approx(0.5),)  # o que a transição dura no vídeo final
    # o segundo trecho começa em 2,5 s no vídeo final; no grafo da janela (que abre em 2,2 s) o xfade fica a 0,3 s
    full = timeline_spans(durations, transitions)
    assert full[1][0] == pytest.approx(2.5)
    graph = timeline_graph(
        2, list(window.durations), list(window.transitions), 30, want_audio=False, lead_in=window.origin
    )
    assert "duration=0.500:offset=0.300" in next(line for line in graph.lines if "xfade" in line)
    assert window.origin + 0.3 == pytest.approx(full[1][0])


def test_a_window_that_starts_after_a_transition_leaves_the_previous_clip_out():
    window = timeline_window([3.0, 3.0], [None, FADE], 3.2, 4.0, 30, 12)
    assert window is not None and (window.first, window.last) == (1, 1)
    assert window.seek == pytest.approx(0.3) and window.origin == pytest.approx(2.8)
    assert window.durations == (pytest.approx(2.7),) and window.transitions == (None,)


def test_clips_joined_by_a_cut_stay_in_one_window_without_a_transition():
    window = timeline_window([2.0, 2.0], [None, None], 1.5, 2.5, 30, 12)
    assert window is not None and (window.first, window.last) == (0, 1)
    assert window.transitions == (None, None) and window.durations == (pytest.approx(0.9), 2.0)
    assert window.overlaps == (0.0,)


def test_an_interval_with_no_frame_or_outside_the_video_has_no_window():
    assert timeline_window([5.0], [None], 3.0, 3.0, 30, 12) is None
    assert timeline_window([5.0], [None], 1.01, 1.02, 30, 12) is None
    assert timeline_window([5.0], [None], 20.0, 21.0, 30, 12) is None


def test_the_timeline_graph_is_the_same_with_the_new_options_at_their_defaults():
    durations, transitions = [3.0, 2.0, 2.5], [None, FADE, None]
    plain = timeline_graph(3, durations, transitions, 30, want_video=True, size=(540, 960))
    explicit = timeline_graph(
        3, durations, transitions, 30, want_video=True, size=(540, 960), lead_in=0.0, want_audio=True
    )
    assert plain.lines == explicit.lines and plain.video == explicit.video


def test_the_lead_in_keeps_the_transition_as_long_as_in_the_full_render():
    # a janela abre no trecho de 1,2 s: sem o tempo que veio antes, a metade do que existe (0,4) encurtaria a
    # transição de 0,5 s do trecho seguinte; no render completo ela dura os 0,5 s inteiros
    durations, transitions = [10.0, 1.2, 5.0], [None, Transition(type="fade", duration=0.3), FADE]
    full = timeline_spans(durations, transitions)
    window = timeline_window(durations, transitions, 10.5, 11.5, 30, 12)
    assert window is not None and (window.first, window.last) == (1, 2)

    def transition_line(lead_in: float) -> str:
        graph = timeline_graph(
            2,
            list(window.durations),
            list(window.transitions),
            30,
            want_audio=False,
            lead_in=lead_in,
        )
        return next(line for line in graph.lines if "xfade" in line)

    assert "duration=0.500:offset=0.300" in transition_line(window.origin)
    assert "duration=0.400" in transition_line(0.0)  # o erro que o `lead_in` evita
    assert window.origin + 0.3 == pytest.approx(full[2][0])


def test_the_audioless_timeline_graph_leaves_no_dangling_output():
    graph = timeline_graph(
        4,
        [2.0, 2.0, 2.0, 2.0],
        [None, None, FADE, None],
        30,
        want_audio=False,
    )
    text = ";".join(graph.lines)
    assert "[ta" not in text and "acrossfade" not in text and "a=1" not in text
    labels = re.findall(r"\[([^\]]+)\]", text)
    alone = {label for label in labels if labels.count(label) == 1}
    assert alone == {"0:v", "1:v", "2:v", "3:v", graph.video.strip("[]")}


# ---------- comandos e pilha do grafo ----------


def test_the_window_command_renders_only_video_without_loss_from_the_mezzanines_of_the_window(tmp_path: Path):
    window = timeline_window([10.0, 3.0], [None, FADE], 9.0, 10.5, 30, 12)
    assert window is not None
    command = window_command(
        [tmp_path / "a.mov", tmp_path / "b.mov"], window, 30, (540, 960), tmp_path / "w.mkv"
    )
    args = command.args
    assert args[: args.index("-filter_complex")].count("-i") == 2
    assert args[args.index("-ss") + 1] == f"{floor_seconds(window.seek):.6f}"  # só o primeiro entra com busca
    assert args.count("-ss") == 1 and args[args.index("-ss") + 2] == "-i"
    assert "-an" in args and "ffv1" in args and "[vwin]" in args
    assert args[args.index("-frames:v") + 1] == str(window.rendered_frames)
    assert "acrossfade" not in " ".join(args) and command.frames is None


def test_a_window_at_the_start_of_the_video_is_opened_without_seek(tmp_path: Path):
    window = timeline_window([10.0], [None], 0.0, 1.0, 30, 12)
    assert window is not None
    command = window_command([tmp_path / "a.mov"], window, 30, (540, 960), tmp_path / "w.mkv")
    assert "-ss" not in command.args


def test_the_seek_rounds_down_so_the_first_frame_of_the_window_is_not_skipped():
    assert floor_seconds(1.0666667) == pytest.approx(1.066666)
    assert floor_seconds(1.0666667) <= 1.0666667
    assert f"{floor_seconds(2.2):.6f}" == "2.200000"


def test_the_person_command_writes_rgba_frames_from_stdin_as_png_video(tmp_path: Path):
    frames = iter([b"x"])
    command = person_layer_command(frames, 540, 960, 30, 60, tmp_path / "p.mov")
    args = command.args
    assert args[args.index("-i") + 1] == "pipe:0" and "rgba" in args and "540x960" in args
    assert "png" in args and command.frames is frames and command.total == 2.0


def test_the_stack_puts_the_back_layers_first_and_the_person_over_them_only_in_the_interval():
    lines: list[str] = []
    inputs = Inputs()
    person = ResolvedPersonLayer(Path("p.mov"), 1.0, 3.0)
    out = behind_person_graph(
        lines, inputs, "[tv0]", [AssBehindLayer("overlay_behind.ass", "FONTS")], [person], 30
    )
    assert out == "[v_person0]"
    assert lines == [
        "[tv0]ass=filename='overlay_behind.ass':fontsdir='FONTS'[v_behind0]",
        "[0:v]tpad=stop_mode=clone:stop=1,setpts=PTS-STARTPTS+0.991667/TB[person0]",
        "[v_behind0][person0]overlay=eof_action=pass:enable='gte(t,0.983333)*lt(t,2.983333)':format=yuv420[v_person0]",
    ]
    assert inputs.args == ["-i", "p.mov"]


def test_the_stack_starts_a_person_at_zero_with_a_negative_quarter_frame_without_breaking_the_expression():
    lines: list[str] = []
    behind_person_graph(lines, Inputs(), "[tv0]", [], [ResolvedPersonLayer(Path("p.mov"), 0.0, 1.0)], 30)
    assert "PTS-STARTPTS-0.008333/TB" in lines[0]


def test_the_stack_takes_any_number_of_back_layers_in_order():
    class Marker:
        def attach(self, lines, inputs, source, tag):
            lines.append(f"{source}null[{tag}]")
            return f"[{tag}]"

    lines: list[str] = []
    out = behind_person_graph(lines, Inputs(), "[v]", [Marker(), Marker()], [], 30)
    assert out == "[v_behind1]" and lines == ["[v]null[v_behind0]", "[v_behind0]null[v_behind1]"]


# ---------- o ajuste do alfa e a cor da pessoa ----------


def test_the_alpha_levels_clear_the_noise_outside_and_close_the_veil_inside():
    alpha = np.array([[[0.0, 0.01, ALPHA_FLOOR, 0.5, ALPHA_CEILING, 0.99, 1.0]]], np.float32)
    refined = refine_alpha(alpha)[0, 0]
    assert refined[:3].tolist() == [0.0, 0.0, 0.0]  # ruído de baixo some
    assert refined[4:].tolist() == [1.0, 1.0, 1.0]  # o alfa quase cheio fecha
    assert refined[3] == pytest.approx(0.5)  # o meio da borda não anda (o ajuste é simétrico)
    assert np.all(np.diff(refined) >= 0)  # e a curva é monótona: não inventa borda


def _colour(red: float, green: float, blue: float, width: int = 1) -> np.ndarray:
    return np.array([red, green, blue], np.float32).reshape(3, 1, 1) * np.ones((3, 1, width), np.float32)


def test_the_person_frame_takes_its_colour_from_the_foreground_on_the_edge_and_from_the_video_inside():
    foreground = _colour(1.0, 0.0, 0.0, 4)  # o primeiro plano que o modelo prevê é vermelho
    source = _colour(0.0, 1.0, 0.0, 4)  # o pixel do vídeo é verde (na borda, a parede misturada)
    alpha = np.array([[[1.0, 0.5, 0.2, 0.0]]], np.float32)
    frame = np.frombuffer(person_rgba(foreground, alpha, source), np.uint8).reshape(1, 4, 4)
    assert frame[0, 0].tolist() == [0, 255, 0, 255]  # dentro do corpo: o pixel do vídeo, que não tem manchas
    assert frame[0, 1, :3].tolist() == [255, 0, 0] and frame[0, 1, 3] == 128  # na borda: só o primeiro plano
    assert (
        frame[0, 2, :3].tolist() == [255, 0, 0] and frame[0, 2, 3] == 46
    )  # o alfa vai direto, após os níveis
    assert frame[0, 3, 3] == 0


def test_the_colour_changes_smoothly_between_the_edge_and_the_inside_of_the_body():
    weights = interior_weight(np.array([0.0, INTERIOR_FROM, 0.925, 1.0], np.float32))
    assert weights[0] == 0 and weights[1] == 0 and weights[3] == 1
    assert 0.4 < weights[2] < 0.6 and np.all(np.diff(weights) >= 0)  # sem degrau entre a borda e o corpo


def test_the_transparent_pixels_get_one_flat_colour_so_the_file_compresses_and_the_edge_stays_clean():
    rng = np.random.default_rng(1)
    foreground = rng.random((3, 4, 4), dtype=np.float32)  # ruído onde não há pessoa
    source = rng.random((3, 4, 4), dtype=np.float32)
    alpha = np.zeros((1, 4, 4), np.float32)
    alpha[0, :2, :2] = 1.0  # a pessoa ocupa o canto
    frame = np.frombuffer(person_rgba(foreground, alpha, source), np.uint8).reshape(4, 4, 4)
    outside = frame[2:, 2:, :3].reshape(-1, 3)
    assert (outside == outside[0]).all()  # uma cor só
    mean = (source[:, :2, :2].mean(axis=(1, 2)) * 255).round()
    assert np.abs(outside[0].astype(float) - mean).max() <= 1  # a média da pessoa, não o preto


def test_a_frame_with_nobody_is_fully_transparent():
    ones = np.ones((3, 2, 2), np.float32)
    frame = np.frombuffer(person_rgba(ones, np.zeros((1, 2, 2), np.float32), ones), np.uint8).reshape(2, 2, 4)
    assert (frame[..., 3] == 0).all() and (frame[..., :3] == 0).all()


# ---------- lint ----------


def _lint(project: Project, durations: list[float]) -> list[str]:
    from dmaker.domain.brand import load_theme
    from dmaker.domain.presets import get_preset

    infos = [
        MediaInfo(Path("x.mp4"), d, 1080, 1920, 30.0, True, True, False) if seg.type == "clip" else None
        for seg, d in zip(project.timeline, durations, strict=True)
    ]
    total = sum(durations)
    return lint(
        project, load_theme(None), get_preset("instagram/reels"), total, durations, infos, [0.0] * len(infos)
    )


def _lint_project(layer: str, start: float, end: float) -> Project:
    return Project.model_validate(
        {
            "name": "lint-camada",
            "timeline": [
                {"type": "card", "title": "Abertura", "duration": 3.0, "motion": "none"},
                {"type": "clip", "src": "take.mp4", "start": 0, "end": 5},
            ],
            "overlays": [{"type": "text", "text": "x", "start": start, "end": end, "layer": layer}],
        }
    )


def test_lint_warns_when_the_text_behind_the_person_only_covers_a_card():
    warnings = _lint(_lint_project("behind-person", 0.5, 2.5), [3.0, 5.0])
    assert len(warnings) == 1 and warnings[0].startswith(
        'overlays[0].layer: "behind-person" entre 0.5s e 2.5s'
    )
    assert "cartão ou foto" in warnings[0] and "—" not in warnings[0] and "–" not in warnings[0]


def test_lint_is_quiet_when_the_interval_reaches_a_video_clip_or_the_text_is_in_front():
    assert _lint(_lint_project("behind-person", 2.0, 4.0), [3.0, 5.0]) == []  # pega o começo do clipe
    assert _lint(_lint_project("behind-person", 4.0, 6.0), [3.0, 5.0]) == []
    assert _lint(_lint_project("front", 0.5, 2.5), [3.0, 5.0]) == []


# ---------- o pipeline com tudo falso ----------


class FakeMatter:
    """Devolve quadros transparentes e registra o que foi pedido, como o recortador de verdade pede."""

    def __init__(self) -> None:
        self.person_requests: list[PersonRequest] = []

    def frames(self, request):  # pragma: no cover - o recorte de fundo não entra aqui
        raise AssertionError("o recorte de fundo não devia ser pedido")

    def person_frames(self, request: PersonRequest):
        self.person_requests.append(request)
        frame = bytes(request.width * request.height * 4)
        for _ in range(round(request.length * request.fps) - request.warmup_frames):
            yield frame


def _prober(path: Path) -> MediaInfo:
    return MediaInfo(path, 20.0, 1080, 1920, 30.0, True, True, False)


def _spec(*overlays: dict, timeline: list[dict] | None = None) -> dict:
    return {
        "name": "atras",
        "output": {"preset": "instagram/reels"},
        "timeline": timeline or [{"type": "clip", "src": "take.mp4", "start": 2, "end": 8}],
        "overlays": [
            {"type": "text", "text": "CINCO CAMADAS", "layer": "behind-person", **o} for o in overlays
        ],
        "audio": {"normalize": "off"},
    }


def _render(
    tmp_path: Path,
    spec: dict,
    matter: FakeMatter | None = None,
    runner: RecordingRunner | None = None,
    builder: PersonLayerBuilder | None = None,
    **options,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    if not (tmp_path / "take.mp4").exists():  # reescrever mudaria o `mtime`, que a chave do mezanino enxerga
        (tmp_path / "take.mp4").write_bytes(b"x")
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    matter = matter or FakeMatter()
    runner = runner or RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    result = RenderPipeline(
        project,
        RenderOptions(**{"preview": True, "quiet": True, "out": tmp_path / "out.mp4", **options}),
        runner=runner,
        prober=_prober,
        transcriber_factory=lambda captions: FakeTranscriber(),
        matter=matter,
        person_layers=builder,
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
    ).run()
    return result, runner, matter


def _final_graph(result) -> str:
    return (result.job_dir / "graph.txt").read_text(encoding="utf-8")


def test_the_pipeline_cuts_the_person_out_of_the_final_timeline_window_and_stacks_it_over_the_text(
    tmp_path: Path,
):
    result, runner, matter = _render(tmp_path, _spec({"start": 1.0, "end": 3.0}))

    request = matter.person_requests[0]
    assert (request.width, request.height, request.fps) == (540, 960, 30)  # o preview
    assert request.model == "mobilenetv3" and request.warmup_frames == 12
    assert request.length == pytest.approx((12 + 60) / 30)
    assert request.src.name.endswith("_window.mkv")

    commands = [" ".join(c) for c in runner.commands]
    window = next(i for i, c in enumerate(commands) if "_window.mkv" in c and "ffv1" in c)
    person = next(i for i, c in enumerate(commands) if "_person.part.mov" in c)
    final = next(i for i, c in enumerate(commands) if "graph.txt" in c)
    assert window < person < final  # a janela, depois o recorte, depois a montagem
    assert "_person.mov" in commands[final]  # a montagem lê a camada já com o nome final
    assert "-ss" in commands[window]  # a janela abre a 12 quadros do intervalo, que está dentro do trecho

    graph = _final_graph(result)
    assert "ass=filename='overlay_behind.ass'" in graph
    assert "overlay=eof_action=pass:enable='gte(t,0.983333)*lt(t,2.983333)'" in graph
    assert graph.index("overlay_behind") < graph.index("eof_action") < graph.index("[vout]")
    behind = (result.job_dir / "overlay_behind.ass").read_text(encoding="utf-8-sig")
    front = (result.job_dir / "overlay.ass").read_text(encoding="utf-8-sig")
    assert "CINCO CAMADAS" in behind.upper() and "CINCO CAMADAS" not in front.upper()
    cache = tmp_path / "mez"
    assert list(cache.glob("*_person.mov")) and not list(cache.glob("*.part.mov"))
    assert not list(cache.glob("*_window.mkv"))  # a janela é descartável: some quando a camada fica pronta


def test_only_the_behind_person_texts_go_to_the_back_ass_and_the_style_names_do_not_collide(tmp_path: Path):
    spec = _spec({"start": 1.0, "end": 3.0})
    spec["overlays"] += [
        {"type": "text", "text": "FRENTE", "role": "hook", "start": 0, "end": 5},
        {"type": "text", "text": "OUTRO ATRÁS", "layer": "behind-person", "start": 4.0, "end": 5.0},
    ]
    result, _, matter = _render(tmp_path, spec)
    behind = (result.job_dir / "overlay_behind.ass").read_text(encoding="utf-8-sig")
    front = (result.job_dir / "overlay.ass").read_text(encoding="utf-8-sig")
    assert "FRENTE" in front.upper() and "FRENTE" not in behind.upper()
    styles = lambda doc: set(re.findall(r"^Style: (T\d+),", doc, re.M))  # noqa: E731
    assert not styles(behind) & styles(front) and len(styles(behind)) == 2
    assert len(matter.person_requests) == 2  # 1 a 3 s e 4 a 5 s: dois intervalos separados


def test_overlapping_texts_behind_the_person_share_one_cutout(tmp_path: Path):
    _, _, matter = _render(
        tmp_path, _spec({"start": 1.0, "end": 3.0}, {"start": 2.5, "end": 4.0, "text": "SEGUNDO"})
    )
    assert len(matter.person_requests) == 1
    assert matter.person_requests[0].length == pytest.approx((12 + 90) / 30)  # 1 a 4 s


def test_a_second_render_without_changes_does_not_cut_the_person_again(tmp_path: Path):
    spec = _spec({"start": 1.0, "end": 3.0})
    _, first_runner, matter = _render(tmp_path, spec)
    _, second_runner, _ = _render(tmp_path, spec, matter=matter)
    assert len(matter.person_requests) == 1
    assert not any("_person.part.mov" in " ".join(c) for c in second_runner.commands)
    assert not any("_window.mkv" in " ".join(c) for c in second_runner.commands)
    assert sum("_person.part.mov" in " ".join(c) for c in first_runner.commands) == 1


def test_the_cache_key_follows_the_interval_the_model_and_the_clip_but_not_the_text(tmp_path: Path):
    def person_files(base: Path) -> set[str]:
        return {p.name for p in (base / "mez").glob("*_person.mov")}

    spec = _spec({"start": 1.0, "end": 3.0})
    _render(tmp_path, spec)
    first = person_files(tmp_path)
    assert len(first) == 1

    retexted = _spec({"start": 1.0, "end": 3.0, "text": "OUTRA FRASE"})
    _render(tmp_path, retexted)
    assert person_files(tmp_path) == first  # o texto não muda a pessoa: a camada é reaproveitada

    _render(tmp_path, _spec({"start": 1.0, "end": 3.5}))
    assert len(person_files(tmp_path)) == 2  # outro intervalo, outra camada

    _render(tmp_path, spec, preview=False)  # render final: outro tamanho e o modelo resnet50
    assert len(person_files(tmp_path)) == 3

    clip = spec["timeline"][0]
    other = {**spec, "timeline": [{**clip, "color": {"brightness": 0.1}}]}
    _render(tmp_path, other)
    assert len(person_files(tmp_path)) == 4  # o look mudou o quadro: a pessoa precisa ser recortada de novo


def test_the_final_render_uses_the_default_model_and_the_preview_the_light_one(tmp_path: Path):
    _, _, final = _render(tmp_path / "a", _spec({"start": 1.0, "end": 2.0}), preview=False)
    _, _, draft = _render(tmp_path / "b", _spec({"start": 1.0, "end": 2.0}), preview=True)
    assert final.person_requests[0].model == "resnet50" and draft.person_requests[0].model == "mobilenetv3"
    _, _, custom = _render(
        tmp_path / "c",
        _spec({"start": 1.0, "end": 2.0}),
        builder=PersonLayerBuilder(preview_model="resnet50"),
    )
    assert custom.person_requests[0].model == "resnet50"


def test_the_dry_run_records_the_commands_but_never_asks_the_model_for_frames(tmp_path: Path):
    runner = RecordingRunner(capture_stderr=LOUDNORM_JSON)
    _, _, matter = _render(tmp_path, _spec({"start": 1.0, "end": 3.0}), runner=runner, dry_run=True)
    assert matter.person_requests == []
    assert any("_person.part.mov" in " ".join(c) for c in runner.commands)


def test_a_failed_cutout_leaves_neither_a_partial_file_nor_a_cache_entry(tmp_path: Path):
    class FailingRunner(RecordingRunner):
        def run(self, command):
            out = Path(command.args[-1])
            if out.name.endswith("_person.part.mov"):
                out.write_bytes(b"pela metade")
                raise FFmpegError("o recorte caiu")
            return super().run(command)

    runner = FailingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    with pytest.raises(FFmpegError):
        _render(tmp_path, _spec({"start": 1.0, "end": 3.0}), runner=runner)
    cache = tmp_path / "mez"
    assert not list(cache.glob("*_person*.mov")) and not list(cache.glob("*_window.mkv"))


def test_a_text_in_front_never_asks_for_a_cutout_and_leaves_the_graph_as_it_was(tmp_path: Path):
    result, runner, matter = _render(
        tmp_path, {**_spec(), "overlays": [{"type": "text", "text": "FRENTE", "layer": "front"}]}
    )
    assert matter.person_requests == []
    assert "overlay_behind" not in _final_graph(result) and "eof_action" not in _final_graph(result)
    assert not any("_person" in " ".join(c) for c in runner.commands)


def test_the_assembly_graph_of_a_project_with_no_text_behind_the_person_is_the_one_from_before(
    tmp_path: Path,
):
    """O mesmo projeto e a mesma montagem do teste do DMK-34, gravados da `develop` antes do DMK-28, com um texto
    explicitamente na frente: o grafo sai idêntico, letra por letra."""
    spec = {
        "name": "unit",
        "output": {"preset": "instagram/reels"},
        "brand": "medlycare",
        "timeline": [
            {"type": "card", "title": "Abertura", "duration": 1.0, "motion": "none"},
            {
                "type": "clip",
                "src": "take.mp4",
                "start": 1,
                "end": 3,
                "transition": {"type": "fade", "duration": 0.4},
            },
            {
                "type": "image",
                "src": "print.png",
                "duration": 1.0,
                "motion": "zoom-in",
                "transition": {"type": "cut"},
            },
        ],
        "overlays": [
            {"type": "image", "src": "logo:symbol", "position": "top-right", "width": 0.1},
            {"type": "text", "text": "Gancho", "role": "hook", "start": 0, "end": 0.9, "layer": "front"},
            {"type": "progress-bar"},
        ],
        "captions": {"source": "auto", "language": "pt"},
        "audio": {"normalize": "two-pass", "music": {"src": "trilha.mp3", "volume": 0.2}},
    }
    from PIL import Image

    (tmp_path / "take.mp4").write_bytes(b"x")
    Image.new("RGB", (1000, 620), "#3366CC").save(tmp_path / "print.png")
    result, _, _ = _render_unit(tmp_path, spec)
    graph = re.sub(r"fontsdir='[^']*'", "fontsdir='FONTS'", _final_graph(result))
    assert graph == GRAPH_BEFORE_DMK_34


def test_the_front_graph_keeps_the_behind_stack_before_images_pip_and_front_text(tmp_path: Path):
    spec = _spec({"start": 1.0, "end": 3.0})
    spec["overlays"] += [
        {"type": "text", "text": "FRENTE", "role": "hook", "start": 0, "end": 5},
        {"type": "progress-bar"},
    ]
    result, _, _ = _render(tmp_path, spec)
    graph = _final_graph(result)
    order = [graph.index(s) for s in ("overlay_behind.ass", "eof_action=pass", "overlay.ass", "[vout]")]
    assert order == sorted(order)


def test_the_window_covers_a_transition_between_two_clips_in_the_pipeline(tmp_path: Path):
    timeline = [
        {"type": "clip", "src": "take.mp4", "start": 0, "end": 3},
        {
            "type": "clip",
            "src": "take.mp4",
            "start": 5,
            "end": 8,
            "transition": {"type": "fade", "duration": 0.5},
        },
    ]
    _, runner, matter = _render(tmp_path, _spec({"start": 2.6, "end": 3.4}, timeline=timeline))
    window = next(" ".join(c) for c in runner.commands if "_window.mkv" in " ".join(c))
    assert window.count(" -i ") == 2 and "xfade=transition=fade:duration=0.500:offset=0.300" in window
    assert matter.person_requests[0].warmup_frames == 12


def test_the_layer_version_and_the_warmup_are_pinned_constants():
    # mexer neles invalida o cache só da camada da pessoa (o `MATTE_VERSION` e o `MEZZ_VERSION` ficam)
    assert PERSON_LAYER_VERSION == "p1" and WARMUP_FRAMES == 12
