"""Picture-in-picture: máscara/moldura, posicionamento, animação e grafo (sem ffmpeg)."""

from pathlib import Path

import pytest

from dmaker.domain.presets import SafeZone
from dmaker.domain.spec import Project, VideoOverlay, parse_aspect
from dmaker.filtergraph import Inputs, ResolvedVideoOverlay, pip_position, video_overlay_graph
from dmaker.filtergraph.pip import _slide_expr
from dmaker.visuals.pip import render_pip_assets


def _pip(**kw) -> ResolvedVideoOverlay:
    overlay = VideoOverlay(src="cam.mp4", **kw)
    return ResolvedVideoOverlay(
        overlay,
        Path("cam.mp4"),
        0.0,
        overlay.start,
        overlay.end or 10.0,
        300,
        200,
        Path("m.png"),
        Path("f.png"),
        12,
    )


def test_spec_validation():
    with pytest.raises(ValueError, match="um dos dois"):
        VideoOverlay()
    with pytest.raises(ValueError, match="proporção"):
        VideoOverlay(src="a.mp4", aspect="banana")
    assert parse_aspect("4:3") == pytest.approx(4 / 3)
    with pytest.raises(ValueError, match="desconhecida"):
        Project.model_validate(
            {
                "name": "x",
                "timeline": [{"type": "card", "title": "t"}],
                "overlays": [{"type": "video", "source": "cam9"}],
            }
        )


def test_pip_assets_shapes():
    assets = render_pip_assets(
        200, 200, "circle", radius=0, softness=0, border=6, border_color="#FFFFFF", shadow=True
    )
    assert assets.mask.size == (200, 200) and assets.mask.mode == "L"
    assert (
        assets.mask.getpixel((100, 100)) == 255 and assets.mask.getpixel((3, 3)) == 0
    )  # círculo: canto fora
    assert assets.frame is not None and assets.pad > 6
    assert assets.frame.size == (200 + 2 * assets.pad, 200 + 2 * assets.pad)
    plain = render_pip_assets(120, 80, "rect", border=0, shadow=False)
    assert plain.frame is None and plain.pad == 0 and plain.mask.getpixel((0, 0)) == 255
    rounded = render_pip_assets(120, 80, "rounded", radius=20, softness=0, border=0, shadow=False)
    assert rounded.mask.getpixel((0, 0)) == 0 and rounded.mask.getpixel((60, 40)) == 255


def test_positions_respect_safe_zone():
    safe = SafeZone(100, 200, 30, 60)
    pip = _pip(position="bottom-right", margin=10)
    assert pip_position(pip, 1920, 1080, 1.0, safe) == (1920 - 60 - 10 - 300, 1080 - 200 - 10 - 200)
    assert pip_position(_pip(position="top"), 1920, 1080, 1.0, safe) == ((1920 - 300) // 2, 100 + 40)
    assert pip_position(_pip(x=0.5, y=0.5), 1920, 1080, 1.0, safe) == (960 - 150, 540 - 100)


def test_slide_expression_direction():
    right = _slide_expr(1500, 300, 1920, 2.0, "bottom-right", "x")
    assert right.startswith("1500+420*") and "t-2.000" in right
    left = _slide_expr(50, 300, 1920, 0.0, "top-left", "x")
    assert left.startswith("50-350*")
    assert _slide_expr(50, 300, 1920, 0.0, "top", "x") == "50"  # "top" desliza só no eixo y
    assert _slide_expr(40, 200, 1080, 0.0, "top", "y").startswith("40-240*")


def test_video_overlay_graph_builds_inputs_and_audio():
    lines: list[str] = []
    inputs = Inputs()
    inputs.add("timeline.mov")
    pip = _pip(start=2.0, end=6.0, volume=0.5, animation="slide", position="bottom-right", opacity=0.9)
    cur_v, audio = video_overlay_graph(lines, inputs, "[tv]", [pip], 1920, 1080, 30, 20.0, 1.0, SafeZone())
    text = ";".join(lines)
    assert cur_v == "[pv0]" and audio == ["[pipaud0]"]
    assert inputs.count == 4  # linha do tempo, vídeo do PiP, máscara, moldura
    assert "-ss" in inputs.args and "4.000" in inputs.args  # duração do PiP
    assert "alphamerge" in text and "colorchannelmixer=aa=0.900" in text
    assert "tpad=start_duration=2.000:start_mode=add:color=black@0.0" in text
    assert "eval=frame" in text and "enable='between(t,2.000,6.000)'" in text
    assert "adelay=2000:all=1" in text and "volume=0.500" in text
    assert "overlay=x='" in text  # expressões com vírgula ficam entre aspas


def test_video_overlay_without_audio_or_frame():
    lines: list[str] = []
    inputs = Inputs()
    inputs.add("timeline.mov")
    overlay = VideoOverlay(src="cam.mp4", start=0, end=3, animation="none", shadow=False, border=0)
    pip = ResolvedVideoOverlay(
        overlay, Path("cam.mp4"), 1.5, 0, 3, 300, 200, Path("m.png"), None, 0, has_audio=False
    )
    cur_v, audio = video_overlay_graph(lines, inputs, "[tv]", [pip], 1920, 1080, 30, 3.0, 1.0, SafeZone())
    text = ";".join(lines)
    assert audio == [] and inputs.count == 3 and "tpad" not in text and "fade" not in text
    assert inputs.args[inputs.args.index("-ss") + 1] == "1.500"  # ponto de entrada no arquivo
