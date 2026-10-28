"""Transições de movimento renderizadas de verdade (ffmpeg) em quadros 1080x1920 e medidas quadro a quadro.

Cada teste mede o que o olho veria: a posição da emenda no chicote, o tamanho do quadrado no zoom de passagem, a
nitidez nas pontas e a suavidade da luz. Os clipes são sintéticos e estáticos (feitos para serem medidos); o
movimento que aparece nos números é todo da transição.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache

import numpy as np
import pytest
from PIL import Image

from dmaker.domain.spec import Project, Transition
from dmaker.domain.timeline import effective_transition
from dmaker.filtergraph.expressions import lookup
from dmaker.filtergraph.lightleak import LeakLook, light_leak_source
from dmaker.filtergraph.timeline import timeline_graph
from dmaker.filtergraph.transitions.crosszoom import plan_crosszoom
from dmaker.filtergraph.transitions.push import plan_whippan
from dmaker.filtergraph.transitions.registry import first_frame_at, frame_count
from dmaker.media.ffmpeg import SubprocessRunner, ffmpeg_path
from dmaker.media.probe import probe
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.transition_preview import TransitionPreview

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

FPS = 30
WIDTH, HEIGHT = 1080, 1920
HALF = (WIDTH // 2, HEIGHT // 2)
CLIP_SECONDS = 1.0
DURATION = 0.5
MOTION = ["crosszoom", "whippan", "blurslide", "filmburn", "lightleak"]


def _solid(color: str) -> str:
    return f"color=c={color}:s={WIDTH}x{HEIGHT}:r={FPS}:d={CLIP_SECONDS}"


GRAY = _solid("0x808080")
# Branco com um quadrado preto no centro, e o inverso: o tamanho do quadrado mede o zoom em cada quadro.
SQUARE_ON_BLACK = _solid("black") + ",drawbox=x=340:y=760:w=400:h=400:color=white:t=fill"
SQUARE_ON_WHITE = _solid("white") + ",drawbox=x=340:y=760:w=400:h=400:color=black:t=fill"
# Cinza (A) e preto com uma coluna branca larga no meio (B): onde estão a emenda e a coluna diz onde a tira está.
BLACK_WITH_COLUMN = _solid("black") + ",drawbox=x=340:y=0:w=400:h=ih:color=white:t=fill"
# Detalhe fino (linhas de 1 px a cada 8 px) para medir nitidez: qualquer amaciamento ou pixelização aparece.
GRID_A = _solid("0x303030") + ",drawgrid=w=8:h=8:t=1:c=white"
GRID_B = _solid("0x404040") + ",drawgrid=w=10:h=10:t=1:c=yellow"


def _run(
    sources: tuple[str, str], graph_lines: list[str], out_label: str, pix_fmt: str, size: tuple[int, int]
):
    args = [str(ffmpeg_path()), "-hide_banner", "-loglevel", "error", "-nostdin"]
    for source in sources:
        args += ["-f", "lavfi", "-i", f"{source}[out0];anullsrc=r=48000:cl=stereo:d={CLIP_SECONDS}[out1]"]
    args += [
        "-filter_complex",
        ";".join(graph_lines),
        "-map",
        out_label,
        "-fps_mode",
        "passthrough",
        "-f",
        "rawvideo",
        "-pix_fmt",
        pix_fmt,
        "-",
    ]
    data = subprocess.run(args, capture_output=True, check=True).stdout
    channels = 1 if pix_fmt == "gray" else 3
    shape = (-1, size[1], size[0]) if channels == 1 else (-1, size[1], size[0], 3)
    return np.frombuffer(data, np.uint8).reshape(shape)


def _window(
    kind: str,
    curve: str,
    sources: tuple[str, str],
    pix_fmt: str = "gray",
    size: tuple[int, int] = HALF,
    duration: float = DURATION,
) -> np.ndarray:
    """Quadros de `kind` entre as duas fontes, do último antes da janela ao primeiro depois dela (índice 0 =
    antes, 1..N = a janela, N+1 = depois), reduzidos à metade para a leitura ser rápida."""
    return _cached_window(kind, curve, sources, pix_fmt, size, duration)


@lru_cache(maxsize=64)
def _cached_window(kind, curve, sources, pix_fmt, size, duration) -> np.ndarray:
    transition = Transition(type=kind, duration=duration, curve=curve)
    graph = timeline_graph(2, [CLIP_SECONDS, CLIP_SECONDS], [None, transition], FPS, True, (WIDTH, HEIGHT))
    window = effective_transition(transition, CLIP_SECONDS, CLIP_SECONDS)
    first, count = first_frame_at(CLIP_SECONDS - window, FPS), frame_count(window, FPS)
    lines = list(graph.lines)
    lines.append(f"{graph.audio}anullsink")
    lines.append(
        f"{graph.video}select='between(n,{first - 1},{first + count})',scale={size[0]}:{size[1]},format={pix_fmt}[out]"
    )
    return _run(sources, lines, "[out]", pix_fmt, size)


# ---------- chicote: a emenda e a coluna dizem onde a tira está ----------


def _strip_position(frame: np.ndarray, a_level: float) -> float | None:
    """Quanto da tira já andou (0 = só A, 1 = B no lugar), lido do quadro: pela emenda cinza/preto enquanto A
    aparece, e pela coluna branca de B quando a emenda já saiu (ou B passou do ponto). None se nenhuma aparece."""
    width = frame.shape[1]
    profile = frame.mean(axis=0)
    black = (a_level + 16) / 2
    if profile[0] > a_level - 20:
        dark = np.nonzero(profile < black)[0]
        if dark.size and dark[0] > 0.02 * width:
            return float((width - dark[0]) / width)
    feature = np.clip(profile - (a_level + 15), 0, None)
    columns = np.nonzero(feature > 0)[0]
    if columns.size < 20:
        return None
    centre = float((feature * np.arange(width)).sum() / feature.sum())
    if not 0.28 * width < centre < 0.72 * width:  # a coluna cortada pela borda dá centro torto
        return None
    return float((1.5 * width - centre) / width)  # a coluna de B está em 1,5 largura de tira (1620 de 1080)


@lru_cache(maxsize=8)
def _whip_track(curve: str) -> tuple[list[float | None], list[float]]:
    frames = _window("whippan", curve, (GRAY, BLACK_WITH_COLUMN))
    n = frame_count(DURATION, FPS)
    a_level = float(frames[0].mean())
    measured = [_strip_position(frames[1 + k].astype(float), a_level) for k in range(n)]
    return measured, plan_whippan(curve, n).shift


@pytest.mark.parametrize("curve", ["linear", "ease", "spring"])
def test_whippan_moves_the_strip_where_the_curve_says_without_jitter(curve):
    measured, planned = _whip_track(curve)
    blur = plan_whippan(curve, len(planned)).blur
    seen = [(m, p, b) for m, p, b in zip(measured, planned, blur, strict=True) if m is not None]
    assert len(seen) >= 12, "a posição da tira precisa ser legível na maior parte da janela"
    # 0,6% da largura (crop em pixel par e leitura em meia resolução) mais uma folga que cresce com o desfoque: o
    # gblur recursivo enviesa um degrau que está a menos de 3 sigmas da borda do quadro, e a emenda mede errado
    for measured_s, planned_s, sigma in seen:
        assert abs(measured_s - planned_s) < 0.006 + 0.15 * sigma
    seen = [(m, p) for m, p, _ in seen]
    positions = np.array([m for m, _ in seen])
    steps = np.diff(positions)
    if curve == "spring":
        reversal = np.nonzero(steps < -0.004)[0]
        assert reversal.size and reversal[0] > 2  # passa do ponto uma vez...
        assert (np.diff(np.sign(steps[np.abs(steps) > 0.004])) != 0).sum() == 1  # ...e só uma: sem tremer
    else:
        assert steps.min() > -0.004  # nunca anda para trás


def test_spring_accelerates_and_settles_while_ease_and_linear_keep_their_own_rhythm():
    """A mesma transição com as três curvas, medida quadro a quadro na imagem renderizada."""
    tracks = {curve: _whip_track(curve)[0] for curve in ("linear", "ease", "spring")}
    # as primeiras leituras da linear e da ease ainda não têm a coluna na tela: usa o plano onde falta leitura
    full = {
        curve: [m if m is not None else p for m, p in zip(track, _whip_track(curve)[1], strict=True)]
        for curve, track in tracks.items()
    }
    steps = {curve: np.diff(np.array(values)) for curve, values in full.items()}
    linear, ease, spring = steps["linear"], steps["ease"], steps["spring"]
    assert linear.max() - linear.min() < 0.02  # velocidade constante
    assert abs(int(np.argmax(ease)) - len(ease) / 2) <= 2  # a ease corre no meio da janela
    assert int(np.argmax(spring)) <= len(spring) / 3  # a mola corre logo na partida
    assert spring.max() > 2.5 * linear.max()  # e bem mais forte que a linear
    assert np.abs(spring[-4:]).max() < 0.05 * spring.max()  # e assenta: quase parada nos últimos quadros
    reach = {curve: next(k for k, v in enumerate(values) if v >= 0.9) for curve, values in full.items()}
    assert reach["spring"] < reach["ease"] < reach["linear"]
    assert max(full["spring"]) > 1.05 and max(full["ease"]) <= 1.01 and max(full["linear"]) <= 1.01


# ---------- zoom de passagem: o tamanho do quadrado mede o zoom ----------


def _square_width(frame: np.ndarray, white_square: bool) -> float:
    row = frame[frame.shape[0] // 2].astype(float)
    return (
        float((row > 125).sum() if white_square else (row < 125).sum()) * 2 / 400
    )  # meia resolução: x2, de 400 px


@pytest.mark.parametrize("curve", ["linear", "ease", "spring"])
def test_crosszoom_zoom_follows_the_plan_and_the_incoming_image_settles(curve):
    n = frame_count(DURATION, FPS)
    plan = plan_crosszoom(curve, n)
    out_frames = _window("crosszoom", curve, (SQUARE_ON_BLACK, SQUARE_ON_WHITE))
    leaving = [(k, _square_width(out_frames[1 + k], True)) for k in range(n) if plan.mix[k] < 0.08]
    for k, zoom in leaving:
        assert zoom == pytest.approx(plan.zoom_out[k], rel=0.03), f"quadro {k}"
    entering = [(k, _square_width(out_frames[1 + k], False)) for k in range(n) if plan.mix[k] > 0.92]
    for k, zoom in entering:
        assert zoom == pytest.approx(plan.zoom_in[k], rel=0.03), f"quadro {k}"
    zooms_out = np.array([z for _, z in leaving])
    zooms_in = np.array([z for _, z in entering])
    if curve != "spring":
        assert np.diff(zooms_out).min() > -0.02  # a que sai só amplia
        assert np.diff(zooms_in).max() < 0.02  # a que entra só reduz até assentar
    assert zooms_in[-1] == pytest.approx(1.0, abs=0.06 if curve == "linear" else 0.02)
    first_after = _square_width(out_frames[n + 1], False)
    assert first_after == pytest.approx(1.0, abs=0.01)  # o trecho seguinte entra exatamente no enquadramento


# ---------- nitidez: sem amaciar nem pixelar nas pontas ----------


def _sharpness(frame: np.ndarray) -> float:
    luma = frame.astype(float)
    return float(np.abs(np.diff(luma, axis=1)).mean() + np.abs(np.diff(luma, axis=0)).mean())


@pytest.mark.parametrize("kind", MOTION)
@pytest.mark.parametrize("curve", ["ease", "spring"])
def test_motion_transitions_leave_and_arrive_as_sharp_as_the_clips(kind, curve):
    frames = _window(kind, curve, (GRID_A, GRID_B))
    n = frame_count(DURATION, FPS)
    assert _sharpness(frames[1]) >= 0.97 * _sharpness(
        frames[0]
    )  # a primeira da janela ainda é o clipe que sai
    # a última já é o que entra. No chicote com ease ela ainda anda uns 5 px por quadro, e o traço de movimento
    # desse quadro (sigma de 1,5 px) é legítimo: numa grade de linhas de 1 px isso já tira um quarto da nitidez
    floor = 0.7 if (kind, curve) == ("whippan", "ease") else 0.93
    assert _sharpness(frames[n]) >= floor * _sharpness(frames[n + 1])


# ---------- vazamento de luz e queima de filme: quente, suave e sem degraus ----------


@pytest.mark.parametrize("kind", ["lightleak", "filmburn"])
def test_light_transitions_glow_warm_smoothly_and_fade_in_and_out(kind):
    frames = _window(kind, "ease", (GRAY, GRAY), pix_fmt="rgb24", size=(270, 480))
    n = frame_count(DURATION, FPS)
    gray = frames[0].astype(float)
    assert np.abs(frames[1].astype(float) - gray).max() <= 2  # começa igual ao clipe que sai
    assert np.abs(frames[n].astype(float) - gray).mean() < 8  # e termina quase igual ao que entra
    glow = [frames[1 + k].astype(float) for k in range(n)]
    peak = max(glow, key=lambda f: f.mean())
    assert peak.mean() > gray.mean() + 15 and (peak[..., 0] - peak[..., 2]).mean() > 25  # acende, e quente
    brightness = [f.mean() for f in glow]
    assert int(np.argmax(brightness)) in range(n // 3, 2 * n // 3 + 1)  # o pico fica no meio da troca
    luma = peak.mean(axis=2).mean(axis=0)
    assert np.abs(np.diff(luma, 2)).max() < 1.5  # gradiente liso: sem blocos de baixa resolução


# ---------- a linha do tempo inteira ----------


@pytest.mark.parametrize("kind", [*MOTION, "wipeleft"])
@pytest.mark.parametrize("curve", ["linear", "spring"])
def test_every_transition_keeps_the_timeline_length_and_a_steady_frame_rate(kind, curve):
    transition = Transition(type=kind, duration=0.4, curve=curve)
    graph = timeline_graph(2, [1.2, 1.3], [None, transition], FPS, True, (WIDTH, HEIGHT))
    lines = [*graph.lines, f"{graph.audio}anullsink", f"{graph.video}scale=64:112,format=gray[out]"]
    sources = (_solid("0x808080") + ",format=yuv420p", _solid("0x606060") + ",format=yuv420p")
    frames = _run(
        (sources[0].replace(f"d={CLIP_SECONDS}", "d=1.2"), sources[1].replace(f"d={CLIP_SECONDS}", "d=1.3")),
        lines,
        "[out]",
        "gray",
        (64, 112),
    )
    assert abs(len(frames) - graph.total * FPS) <= 1  # igual ao do xfade: a soma menos a troca
    assert graph.total == pytest.approx(2.1)


# ---------- o gerador do pipeline e a folha ----------


def _project(media: dict, tmp_path) -> Project:
    pairs = [("crosszoom", "linear"), ("whippan", "spring"), ("blurslide", "ease"), ("filmburn", "linear")]
    timeline: list[dict] = [{"type": "card", "title": "Abertura", "subtitle": "teste", "duration": 1.5}]
    sources = [
        {"type": "clip", "src": str(media["clip_a"]), "start": 0.0, "end": 2.0},
        {"type": "clip", "src": str(media["clip_b"]), "end": 1.5},
        {"type": "image", "src": str(media["photo"]), "duration": 1.5, "motion": "zoom-in"},
        {"type": "card", "title": "Fim", "subtitle": "teste", "duration": 1.5},
    ]
    for (kind, curve), segment in zip(pairs, sources, strict=True):
        timeline.append({**segment, "transition": {"type": kind, "duration": 0.4, "curve": curve}})
    timeline.append(
        {
            "type": "clip",
            "src": str(media["clip_a"]),
            "end": 2.0,
            "transition": {"type": "lightleak", "duration": 0.4, "curve": "spring"},
        }
    )
    project = Project.model_validate(
        {
            "name": "teste_transicoes",
            "output": {"preset": "instagram/reels", "quality": "medium"},
            "brand": "medlycare",
            "timeline": timeline,
            "audio": {"normalize": "fast"},
        }
    )
    project.base_dir = tmp_path
    return project


def test_pipeline_renders_every_motion_transition_at_the_expected_length(synthetic_media, tmp_path):
    project = _project(synthetic_media, tmp_path)
    out = tmp_path / "movimento.mp4"
    result = RenderPipeline(project, RenderOptions(preview=True, out=out, quiet=True)).run()
    assert out.exists() and result.size_bytes > 10_000
    # 1,5 + 2 + 1,5 + 1,5 + 1,5 + 2 menos as cinco trocas de 0,4 s
    assert result.duration == pytest.approx(10.0 - 5 * 0.4, abs=0.01)
    info = probe(out)
    assert (info.width, info.height) == (540, 960) and info.has_audio
    assert info.duration == pytest.approx(result.duration, abs=0.12)  # vídeo e áudio terminam juntos


def test_contact_sheet_is_rendered_for_real_and_cached(tmp_path):
    preview = TransitionPreview(SubprocessRunner(quiet=True), tmp_path / "cache")
    for name in ("crosszoom", "wipeleft"):
        sheet = preview.sheet(name, "spring")
        with Image.open(sheet) as image:
            assert image.size[0] > 1100 and 200 < image.size[1] < 330  # oito miniaturas 9:16 lado a lado
    before = sheet.stat().st_mtime_ns
    assert preview.sheet("wipeleft", "spring").stat().st_mtime_ns == before  # segunda vez vem do cache


def test_lookup_expressions_evaluate_in_ffmpeg_to_the_table_values():
    values = [0.0, 0.125, 0.5, 0.875, 1.0, 1.05, 0.5, -0.25, 12.5]
    expression = lookup(values, "n", 6)
    args = [
        str(ffmpeg_path()),
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"aevalsrc='{expression}':s=30:d={len(values) / 30:.6f}",
        "-f",
        "f32le",
        "-",
    ]
    data = subprocess.run(args, capture_output=True, check=True).stdout
    assert np.frombuffer(data, np.float32)[: len(values)] == pytest.approx(values, abs=1e-5)


def test_light_leak_source_shows_each_table_value_on_its_own_frame_with_alpha():
    """O `N` do geq conta de 0: a luz do quadro k é a da posição k das tabelas, nem uma antes nem uma depois."""
    look = LeakLook(
        edge=(255, 80, 20), mid=(255, 160, 40), core=(255, 240, 200), width=0.5, tilt=0.0, floor=1.0
    )
    intensity = [0.0, 0.0, 1.0, 0.0, 0.5, 0.0]
    lines = light_leak_source("[leak]", (WIDTH, HEIGHT), FPS, look, intensity, [0.5] * len(intensity))
    lines.append("[leak]alphaextract,scale=16:16,format=gray[out]")
    frames = _run(
        ("color=c=black:s=64x64:r=30:d=1",) * 2,
        lines + ["[0:a][1:a]amix[am];[am]anullsink"],
        "[out]",
        "gray",
        (16, 16),
    )
    assert len(frames) == len(intensity)
    alpha = frames.reshape(len(frames), -1).mean(axis=1) / 255
    assert alpha == pytest.approx(intensity, abs=0.03)
