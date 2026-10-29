"""Composição animada em HTML (DMK-26), sem Chromium nem ffmpeg de verdade: o campo da spec, a área na região, os
arquivos que a origem falsa serve (e o que ela nega), o borrão de movimento, os grafos e o pipeline com um
renderizador falso. O que só o Chromium e o ffmpeg reais mostram fica em `test_html_render.py`."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from dmaker import config
from dmaker.domain.brand import load_theme
from dmaker.domain.edits import EditError
from dmaker.domain.presets import get_preset
from dmaker.domain.regions import box_pixels, html_box, region_pixels, resolve_region
from dmaker.domain.sfx import plan_sfx
from dmaker.domain.spec import HtmlOverlay, MotionBlur, Project, Region, TextOverlay
from dmaker.domain.timeline import behind_person_intervals
from dmaker.filtergraph.behind_person import AssBehindLayer, ResolvedPersonLayer, behind_person_graph
from dmaker.filtergraph.common import Inputs
from dmaker.filtergraph.html_layer import (
    HtmlBehindLayer,
    ResolvedHtmlLayer,
    attach_html_layer,
    html_layer_command,
    html_overlay_graph,
)
from dmaker.media import html_site
from dmaker.media.browser import BROWSERS_PATH_VAR, PlaywrightBrowser, browser_problem, playwright_env
from dmaker.media.ffmpeg import FFmpegError, RecordingRunner
from dmaker.media.html_render import (
    CHROMIUM_ARGS,
    EPOCH_MS,
    HtmlComposition,
    HtmlRenderError,
    runtime_script,
)
from dmaker.media.matting import PersonRequest
from dmaker.media.probe import MediaInfo
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.html_frame import (
    default_frame_path,
    insert_html_overlay,
    parse_size,
    render_html_frame,
)
from dmaker.pipeline.html_layer import (
    HTML_LAYER_VERSION,
    HtmlLayerBuilder,
    HtmlRenderFailed,
    content_digest,
    html_warnings,
)
from dmaker.pipeline.lint import lint
from dmaker.visuals.motion_blur import blend_premultiplied, blend_stream, blur_sample_times
from tests.test_audiogram import GRAPH_BEFORE_DMK_34, _render_unit
from tests.test_pipeline_unit import LOUDNORM_JSON, FakeTranscriber, touch_output

DASHES = ("—", "–")


# ---------- o campo da spec ----------


def _html(**fields) -> HtmlOverlay:
    return HtmlOverlay.model_validate({"type": "html", "src": "comp", **fields})


def test_an_html_overlay_has_defaults_that_cover_the_whole_frame_in_front_of_everything():
    overlay = _html()
    assert (overlay.start, overlay.end, overlay.layer) == (0.0, None, "front")
    assert (overlay.x, overlay.y, overlay.width, overlay.height) == (None, None, 1.0, 1.0)
    assert (
        overlay.size is None and overlay.data == {} and overlay.motion_blur is None and overlay.sound is None
    )


def test_the_overlay_takes_a_region_or_a_center_but_not_both_and_x_needs_y():
    assert _html(region="topo").region == "topo"
    assert _html(x=0.5, y=0.3, width=0.5, height=0.4).y == 0.3
    with pytest.raises(ValidationError, match="`x` e `y` juntos"):
        _html(x=0.5)
    with pytest.raises(ValidationError, match="não leva `x` nem `y`"):
        _html(region="topo", x=0.5, y=0.5)
    with pytest.raises(ValidationError, match="end precisa ser maior"):
        _html(start=3, end=2)
    with pytest.raises(ValidationError):
        _html(width=1.5)
    with pytest.raises(ValidationError):
        _html(src="")


def test_the_page_size_is_a_pair_of_sane_pixel_counts():
    assert _html(size=[1080, 960]).size == (1080, 960)
    for bad in ([10, 960], [1080, 9000], [1080]):
        with pytest.raises(ValidationError):
            _html(size=bad)


def test_motion_blur_takes_a_dict_or_true_and_false_turn_it_on_and_off():
    assert _html(motion_blur=True).motion_blur == MotionBlur(subframes=5, shutter=0.5)
    assert _html(motion_blur=False).motion_blur is None
    assert _html(motion_blur={"subframes": 8, "shutter": 0.25}).motion_blur == MotionBlur(
        subframes=8, shutter=0.25
    )
    for bad in ({"subframes": 1}, {"subframes": 40}, {"shutter": 0}, {"shutter": 1.5}):
        with pytest.raises(ValidationError):
            _html(motion_blur=bad)


def test_the_layer_field_is_the_same_alias_the_text_uses():
    assert _html(layer="behind-person").layer == "behind-person"
    with pytest.raises(ValidationError):
        _html(layer="no-meio")


def test_an_html_overlay_survives_a_save_and_load_and_an_old_project_loads_as_before(tmp_path: Path):
    spec = {
        "name": "html",
        "timeline": [{"type": "card", "title": "x", "duration": 1}],
        "regions": {"topo": {"x": 0.5, "y": 0.25, "width": 1.0, "height": 0.5}},
        "overlays": [
            {
                "type": "html",
                "src": "comp",
                "region": "topo",
                "start": 1,
                "end": 3,
                "data": {"titulo": "Oi", "itens": [1, 2, {"a": True}]},
                "motion_blur": {"subframes": 4, "shutter": 0.4},
                "layer": "behind-person",
                "sound": True,
            }
        ],
    }
    path = Project.model_validate(spec).save(tmp_path / "spec.json")
    loaded = Project.load(path).overlays[0]
    assert loaded.data == {"titulo": "Oi", "itens": [1, 2, {"a": True}]}
    assert loaded.motion_blur == MotionBlur(subframes=4, shutter=0.4)
    assert (loaded.layer, loaded.region, loaded.sound) == ("behind-person", "topo", True)
    old = {"name": "velho", "timeline": [{"type": "card", "title": "x", "duration": 1}]}
    assert Project.model_validate(old).overlays == []


def test_an_html_overlay_with_an_unknown_region_fails_when_the_project_loads():
    spec = {
        "name": "html",
        "timeline": [{"type": "card", "title": "x", "duration": 1}],
        "overlays": [{"type": "html", "src": "comp", "region": "nao-existe"}],
    }
    with pytest.raises(ValidationError, match="região desconhecida"):
        Project.model_validate(spec)


def test_the_html_overlay_gets_the_default_sound_of_a_whoosh_through_the_same_mechanism_as_the_others():
    project = Project.model_validate(
        {
            "name": "som",
            "timeline": [{"type": "card", "title": "x", "duration": 4}],
            "overlays": [{"type": "html", "src": "comp", "start": 1.5, "sound": True}],
        }
    )
    [item] = plan_sfx(project, [(0.0, 4.0)])
    assert (item.sound, item.at, item.origin) == ("whoosh", 1.5, "overlays[0]")


# ---------- a área ----------


def test_the_html_box_is_the_region_in_pixels_and_the_whole_frame_when_nothing_is_said():
    region = Region(x=0.5, y=0.25, width=1.0, height=0.5)
    assert region_pixels(region, 1080, 1920) == (0, 0, 1080, 960)
    topo = resolve_region(_html(region="topo"), {"topo": region}, 1080, 1920)
    assert (topo.region, topo.x, topo.y, topo.width, topo.height) == (None, 0.5, 0.25, 1.0, 0.5)
    assert html_box(topo, 1080, 1920) == region_pixels(region, 1080, 1920)
    assert html_box(_html(), 1080, 1920) == (0, 0, 1080, 1920)
    assert html_box(_html(x=0.75, y=0.5, width=0.5, height=0.25), 1080, 1920) == (540, 720, 540, 480)
    assert box_pixels(0.5, 0.5, 0.5, 0.5, 100, 200) == (25, 50, 50, 100)


def test_a_region_in_the_middle_of_the_frame_is_placed_by_its_corner():
    region = Region(x=0.5, y=0.7, width=0.8, height=0.3)
    overlay = resolve_region(_html(region="r"), {"r": region}, 1080, 1920)
    assert html_box(overlay, 1080, 1920) == (108, 1056, 864, 576)


# ---------- atrás da pessoa ----------


def test_html_overlays_behind_the_person_make_intervals_together_with_the_texts():
    overlays = [
        TextOverlay(text="a", start=1, end=3, layer="behind-person"),
        _html(start=2, end=5, layer="behind-person"),
        _html(start=6, end=7),  # na frente: sem recorte
        _html(start=8, layer="behind-person"),  # sem fim: vai até o fim do vídeo
    ]
    assert behind_person_intervals(overlays, 10.0) == [(1, 5), (8, 10.0)]


def _lint(project: Project, durations: list[float]) -> list[str]:
    infos = [None] * len(durations)
    return lint(
        project,
        load_theme(None),
        get_preset("instagram/reels"),
        sum(durations),
        durations,
        infos,
        [0.0] * len(infos),
    )


def test_lint_warns_when_an_html_overlay_behind_the_person_only_covers_a_card():
    project = Project.model_validate(
        {
            "name": "lint",
            "timeline": [
                {"type": "card", "title": "Abertura", "duration": 3.0, "motion": "none"},
                {"type": "clip", "src": "take.mp4", "start": 0, "end": 5},
            ],
            "overlays": [
                {"type": "html", "src": "comp", "start": 0.5, "end": 2.5, "layer": "behind-person"},
                {"type": "html", "src": "comp", "start": 4, "end": 6, "layer": "behind-person"},
            ],
        }
    )
    [warning] = _lint(project, [3.0, 5.0])
    assert warning.startswith('overlays[0].layer: "behind-person" entre 0.5s e 2.5s')
    assert "cartão ou foto" in warning and "a composição sobre um trecho de vídeo" in warning
    assert not any(dash in warning for dash in DASHES)


# ---------- a origem falsa ----------


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    root = tmp_path / "comp"
    (root / "img").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
    (root / "dados.json").write_text('{"a": 1}', encoding="utf-8")
    (root / "app.js").write_text("export const a = 1;", encoding="utf-8")
    (root / "img" / "foto 1.png").write_bytes(b"\x89PNG")
    (tmp_path / "segredo.txt").write_text("fora da pasta", encoding="utf-8")
    return root


@pytest.fixture
def site(folder: Path, tmp_path: Path) -> html_site.CompositionSite:
    assets, fonts = tmp_path / "assets-html", tmp_path / "fonts"
    assets.mkdir()
    fonts.mkdir()
    (assets / "lottie.min.js").write_text("/* lottie */", encoding="utf-8")
    (fonts / "Poppins-Bold.ttf").write_bytes(b"ttf")
    return html_site.CompositionSite(folder, assets_dir=assets, fonts_dir=fonts)


def test_the_site_serves_the_page_the_files_of_the_folder_the_libraries_and_the_font(site):
    assert site.lookup("/").body == site.lookup("/index.html").body == b"<!doctype html><title>x</title>"
    assert site.lookup("/index.html").content_type == "text/html; charset=utf-8"
    assert site.lookup("/dados.json").content_type.startswith("application/json")
    assert site.lookup("/app.js").content_type.startswith("text/javascript")
    assert site.lookup("/img/foto%201.png") == html_site.Served(b"\x89PNG", "image/png")
    assert site.lookup("/_dmaker/lottie.min.js").body == b"/* lottie */"
    assert site.lookup("/_dmaker/fonts/Poppins-Bold.ttf").content_type == "font/ttf"


def test_the_site_denies_what_does_not_exist_and_anything_outside_its_folders(site):
    assert site.lookup("/nao-existe.png") is None
    assert site.lookup("/img") is None  # pasta, não arquivo
    assert site.lookup("/../segredo.txt") is None
    assert site.lookup("/img/../../segredo.txt") is None
    assert site.lookup("/%2e%2e/segredo.txt") is None
    assert site.lookup("/_dmaker/../index.html") is None
    assert site.lookup("/_dmaker/fonts/../lottie.min.js") is None
    assert site.lookup("/_dmaker/three.module.min.js") is None  # não existe nesta pasta de teste


def test_a_single_html_file_is_the_whole_site_and_its_neighbours_are_not_served(tmp_path: Path):
    page = tmp_path / "solta.html"
    page.write_text("<p>oi</p>", encoding="utf-8")
    (tmp_path / "vizinho.png").write_bytes(b"png")
    site = html_site.CompositionSite(page)
    assert site.lookup("/index.html").body == b"<p>oi</p>"
    assert site.lookup("/vizinho.png") is None
    assert html_site.composition_files(page) == [page]


def test_the_entry_file_explains_what_is_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Composição HTML não encontrada"):
        html_site.entry_file(tmp_path / "nao-existe.html")
    (tmp_path / "vazia").mkdir()
    with pytest.raises(FileNotFoundError, match="não tem index.html"):
        html_site.entry_file(tmp_path / "vazia")
    (tmp_path / "texto.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="arquivo .html ou uma pasta"):
        html_site.entry_file(tmp_path / "texto.txt")


def test_only_the_fake_origin_is_served_and_data_urls_never_leave_the_machine():
    assert html_site.is_composition_origin("http://dmaker.composicao/index.html")
    assert html_site.is_composition_origin("http://dmaker.composicao:80/x.js?v=1")
    for outside in (
        "https://example.com/a.js",
        "http://dmaker.composicao.evil.com/a.js",
        "http://127.0.0.1:9/a",
        "file:///C:/x.html",
    ):
        assert not html_site.is_composition_origin(outside)
    assert html_site.is_local_scheme("data:text/plain,oi") and html_site.is_local_scheme("blob:null/1")
    assert not html_site.is_local_scheme("https://example.com/")


def test_content_types_do_not_depend_on_the_registry_of_the_machine():
    assert html_site.content_type_of("a.mjs").startswith("text/javascript")
    assert html_site.content_type_of("m.glb") == "model/gltf-binary"
    assert html_site.content_type_of("x.desconhecido") == "application/octet-stream"


def test_the_brand_reaches_the_page_as_css_variables_and_the_font_as_font_face(tmp_path: Path):
    css = html_site.brand_css({"primary": "#111827", "bg_dark": "#0B1220"}, "Poppins")
    assert css == ':root{--dm-bg-dark:#0B1220;--dm-primary:#111827;--dm-font:"Poppins",sans-serif}'
    (tmp_path / "Poppins-Bold.ttf").write_bytes(b"x")
    (tmp_path / "Poppins-Italic.ttf").write_bytes(b"x")
    faces = html_site.font_faces_css(tmp_path)
    assert faces.count("@font-face") == 2
    assert "font-weight:700;font-style:normal" in faces and "Poppins-Italic.ttf" in faces
    assert html_site.font_face_probes(tmp_path) == ['700 16px "Poppins"', 'italic 400 16px "Poppins"']
    assert "animation-play-state:paused" in html_site.FREEZE_CSS


def test_the_real_poppins_files_of_the_project_are_all_declared():
    faces = html_site.font_faces_css(config.FONTS_DIR)
    assert faces.count("@font-face") == len(html_site.POPPINS_FACES)


def test_the_vendored_libraries_and_their_licences_are_where_the_site_serves_them_from():
    folder = config.HTML_ASSETS_DIR
    for name in ("three.module.min.js", "three.core.min.js", "lottie.min.js"):
        assert (folder / name).is_file(), name
    # o módulo importa o núcleo pelo nome minificado: os dois arquivos têm que ficar lado a lado
    assert 'from"./three.core.min.js"' in (folder / "three.module.min.js").read_text(encoding="utf-8")
    for licence in ("LICENSE-three.txt", "LICENSE-lottie-web.txt"):
        assert "MIT License" in (folder / licence).read_text(encoding="utf-8")
    third_party = (config.ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
    assert "three.js" in third_party and "lottie-web" in third_party and "assets/html" in third_party


# ---------- o script que vai à página ----------


def test_the_page_script_carries_the_composition_settings_before_the_runtime():
    composition = HtmlComposition(
        source=Path("x"),
        size=(1080, 960),
        scale=0.5,
        fps=24,
        duration=5.5,
        data={"titulo": 'Oi "mundo" </script>', "n": 3},
        colors={"accent": "#FACC15"},
    )
    script = runtime_script(composition)
    prefix, runtime = script.split("\n", 1)
    assert prefix.startswith("window.__dmakerConfig = ")
    settings = json.loads(prefix.removeprefix("window.__dmakerConfig = ").rstrip(";"))
    assert (settings["width"], settings["height"], settings["fps"], settings["duration"]) == (
        1080,
        960,
        24,
        5.5,
    )
    assert settings["data"] == {"titulo": 'Oi "mundo" </script>', "n": 3}
    assert settings["brand"] == {"accent": "#FACC15"} and settings["epoch"] == EPOCH_MS
    assert "--dm-accent:#FACC15" in settings["css"] and "@font-face" in settings["css"]
    assert runtime.lstrip().startswith("/* Runtime do DMaker") and "__dmakerHost" in runtime
    assert composition.output_size == (540, 480)


def test_the_chromium_runs_with_software_webgl_a_fixed_colour_profile_and_a_closed_network():
    flags = " ".join(CHROMIUM_ARGS)
    assert "--use-angle=swiftshader" in flags and "--force-color-profile=srgb" in flags
    assert "--host-resolver-rules=MAP * ~NOTFOUND" in flags


# ---------- o navegador do DMaker mora dentro do clone ----------


def test_the_chromium_of_the_dmaker_lives_inside_the_clone(monkeypatch, tmp_path):
    assert config.PLAYWRIGHT_DIR == config.BIN_DIR / "playwright"
    monkeypatch.setattr(config, "PLAYWRIGHT_DIR", tmp_path / "pw")
    assert playwright_env()[BROWSERS_PATH_VAR] == str(tmp_path / "pw")  # lido de config na hora do uso


def test_the_problem_message_says_how_to_install_what_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PLAYWRIGHT_DIR", tmp_path / "pw")
    problem = browser_problem()
    assert problem is not None and "dmaker setup --html" in problem and str(tmp_path / "pw") in problem
    (tmp_path / "pw" / "chromium_headless_shell-1248").mkdir(parents=True)
    assert browser_problem() is None
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    assert "não está instalado" in browser_problem() and "[html]" in browser_problem()


def test_the_driver_gets_the_browsers_path_only_while_it_starts(monkeypatch, tmp_path):
    from dmaker.media import browser as browser_module

    monkeypatch.setattr(config, "PLAYWRIGHT_DIR", tmp_path / "pw")
    monkeypatch.delenv(BROWSERS_PATH_VAR, raising=False)
    seen = {}

    class Driver:
        def start(self):
            seen["during"] = browser_module.os.environ.get(BROWSERS_PATH_VAR)
            raise RuntimeError("parou aqui")

    import playwright.sync_api as sync_api

    monkeypatch.setattr(sync_api, "sync_playwright", lambda: Driver())
    with pytest.raises(RuntimeError, match="parou aqui"):
        PlaywrightBrowser().__enter__()
    assert seen["during"] == str(tmp_path / "pw")
    assert BROWSERS_PATH_VAR not in browser_module.os.environ  # o processo volta ao ambiente que tinha
    monkeypatch.setenv(BROWSERS_PATH_VAR, "outra-pasta")
    with pytest.raises(RuntimeError):
        PlaywrightBrowser().__enter__()
    assert browser_module.os.environ[BROWSERS_PATH_VAR] == "outra-pasta"


def test_setup_installs_the_chromium_into_the_clone_with_the_environment_that_points_there(
    monkeypatch, tmp_path
):
    from dmaker import setup_tools

    monkeypatch.setattr(config, "PLAYWRIGHT_DIR", tmp_path / "pw")
    calls = []

    def run(command, env=None):
        calls.append((command, env))
        (tmp_path / "pw" / "chromium-1").mkdir(parents=True)  # o que o playwright baixaria
        return type("Done", (), {"returncode": 0})()

    assert setup_tools.install_chromium(run=run) == tmp_path / "pw"
    [(command, env)] = calls
    assert command[1:] == ["-m", "playwright", "install", "chromium"]
    assert env[BROWSERS_PATH_VAR] == str(tmp_path / "pw")


def test_setup_reports_a_failed_download_and_a_browser_that_did_not_land_where_expected(
    monkeypatch, tmp_path
):
    from dmaker import setup_tools

    monkeypatch.setattr(config, "PLAYWRIGHT_DIR", tmp_path / "pw")
    with pytest.raises(RuntimeError, match="código 3"):
        setup_tools.install_chromium(run=lambda command, env=None: type("Done", (), {"returncode": 3})())
    with pytest.raises(RuntimeError, match="não está em"):
        setup_tools.install_chromium(run=lambda command, env=None: type("Done", (), {"returncode": 0})())


# ---------- borrão de movimento ----------


def test_the_blur_samples_the_shutter_around_each_frame_in_order():
    times = [1.0, 1.0 + 1 / 30]
    samples = blur_sample_times(times, 30, 4, 0.5)
    assert len(samples) == 8 and samples == sorted(samples)
    window = 0.5 / 30
    assert samples[0] == pytest.approx(1.0 - window * 3 / 8)
    assert samples[3] == pytest.approx(1.0 + window * 3 / 8)
    assert sum(samples[:4]) / 4 == pytest.approx(1.0)  # centrado no instante do quadro
    assert all(late > early for early, late in zip(samples[3:4], samples[4:5], strict=True))


def test_the_blur_never_asks_for_a_moment_before_the_composition_exists():
    samples = blur_sample_times([0.0], 30, 5, 1.0)
    assert min(samples) == 0.0 and samples == sorted(samples)


def _frame(color: tuple[int, int, int], alpha: int, shape=(2, 3)) -> np.ndarray:
    frame = np.zeros((*shape, 4), np.uint8)
    frame[..., :3], frame[..., 3] = color, alpha
    return frame


def test_the_blend_weights_the_colours_by_alpha_so_the_edge_does_not_darken():
    white_on, nothing = (
        _frame((255, 255, 255), 255),
        _frame((0, 0, 0), 0),
    )  # o transparente é preto no arquivo
    half = blend_premultiplied([white_on, nothing])
    assert (half[..., :3] == 255).all()  # continua branco: a conta direta dava cinza (128)
    assert (half[..., 3] == 128).all()  # 255 e 0 fazem 127,5, que arredonda para 128
    a_third = blend_premultiplied([white_on, nothing, nothing])
    assert (a_third[..., :3] == 255).all() and (a_third[..., 3] == 85).all()


def test_the_blend_mixes_two_colours_by_how_much_each_covers_the_pixel():
    red, blue = _frame((255, 0, 0), 255), _frame((0, 0, 255), 255)
    mixed = blend_premultiplied([red, blue])
    assert tuple(mixed[0, 0]) == (128, 0, 128, 255)
    soft_red = _frame((255, 0, 0), 64)
    weighted = blend_premultiplied([soft_red, blue])  # o azul, mais opaco, pesa mais
    assert weighted[0, 0, 2] > weighted[0, 0, 0] and weighted[0, 0, 3] == round((64 + 255) / 2)


def test_a_single_frame_blends_to_itself_and_an_empty_pixel_stays_empty():
    frame = _frame((10, 20, 30), 200)
    assert blend_premultiplied([frame]) is frame
    empty = blend_premultiplied([_frame((9, 9, 9), 0), _frame((7, 7, 7), 0)])
    assert (empty == 0).all()


def test_the_blend_stream_groups_the_raw_frames_and_drops_an_incomplete_group():
    size = (3, 2)
    raw = [_frame((c, 0, 0), 255).tobytes() for c in (0, 100, 200, 40, 60)]
    out = list(blend_stream(raw, 2, size))
    assert len(out) == 2  # o quinto quadro ficou sem par
    assert np.frombuffer(out[0], np.uint8).reshape(2, 3, 4)[0, 0, 0] == 50
    assert np.frombuffer(out[1], np.uint8).reshape(2, 3, 4)[0, 0, 0] == 120


# ---------- os grafos ----------


def _layer(**fields) -> ResolvedHtmlLayer:
    values = {"path": Path("c.mov"), "start": 1.0, "stop": 3.0, "x": "0", "y": "0"} | fields
    return ResolvedHtmlLayer(**values)


def test_the_front_graph_aligns_the_composition_to_the_frame_grid_like_the_person_layer():
    lines: list[str] = []
    inputs = Inputs()
    inputs.add("video.mp4")
    out = html_overlay_graph(lines, inputs, "[v0]", [_layer(x="100", y="240")], 30)
    assert out == "[v_html0]"
    assert lines == [
        "[1:v]tpad=stop_mode=clone:stop=1,setpts=PTS-STARTPTS+0.991667/TB[v_html0_src]",
        "[v0][v_html0_src]overlay=x=100:y=240:eof_action=pass:enable='gte(t,0.983333)*lt(t,2.983333)'"
        ":format=yuv420[v_html0]",
    ]
    assert inputs.args == ["-i", "video.mp4", "-i", "c.mov"]


def test_a_page_drawn_at_another_size_is_scaled_to_the_area_before_the_overlay():
    lines: list[str] = []
    attach_html_layer(lines, Inputs(), "[v]", _layer(scale_to=(540, 480)), 30, "t")
    assert lines[0].startswith("[0:v]scale=540:480:flags=lanczos,tpad=")


def test_two_front_compositions_chain_in_order_and_none_leaves_the_graph_alone():
    lines: list[str] = []
    inputs = Inputs()
    assert html_overlay_graph(lines, inputs, "[v0]", [], 30) == "[v0]" and lines == []
    out = html_overlay_graph(lines, inputs, "[v0]", [_layer(), _layer(path=Path("d.mov"))], 30)
    assert out == "[v_html1]" and "[v_html0][v_html1_src]overlay" in lines[3]


def test_a_composition_behind_the_person_enters_the_stack_before_the_person_and_before_the_text():
    lines: list[str] = []
    inputs = Inputs()
    person = ResolvedPersonLayer(Path("p.mov"), 1.0, 3.0)
    behind = [HtmlBehindLayer(_layer(behind=True), 30), AssBehindLayer("overlay_behind.ass", "fonts")]
    out = behind_person_graph(lines, inputs, "[v0]", behind, [person], 30)
    graph = ";".join(lines)
    assert out == "[v_person0]"
    assert (
        graph.index("[v0][v_behind0_src]overlay")
        < graph.index("ass=filename")
        < graph.index("[person0]overlay")
    )


def test_the_html_command_writes_png_with_alpha_from_stdin_like_the_person_layer(tmp_path: Path):
    command = html_layer_command(
        iter(()), (540, 480), 30, 60, tmp_path / "c.mov", label="composição html (comp)"
    )
    args = " ".join(command.args)
    assert "-f rawvideo -pix_fmt rgba -s 540x480 -r 30 -i pipe:0" in args
    assert "-c:v png -pix_fmt rgba" in args and command.total == pytest.approx(2.0)
    assert command.label == "composição html (comp)"


# ---------- o pipeline com o renderizador falso ----------

TOPO = {"topo": {"x": 0.5, "y": 0.25, "width": 1.0, "height": 0.5}}


class FakeHtmlRenderer:
    """Devolve quadros de uma cor por quadro e registra o que foi pedido, como o de verdade pede."""

    def __init__(self, warnings=(), fail_at: int | None = None, problem: str | None = None) -> None:
        self.calls: list[tuple[HtmlComposition, list[float]]] = []
        self.warnings, self.fail_at, self.problem = list(warnings), fail_at, problem
        self.stills: list[tuple[HtmlComposition, float]] = []

    def unavailable_reason(self) -> str | None:
        return self.problem

    def frames(self, composition, times, on_warning):
        self.calls.append((composition, list(times)))
        for warning in self.warnings:
            on_warning(warning)
        width, height = composition.output_size
        for index, _ in enumerate(times):
            if index == self.fail_at:
                raise HtmlRenderError("a página travou no quadro")
            yield bytes([index % 250]) * (width * height * 4)

    def still(self, composition, at, on_warning):
        self.stills.append((composition, at))
        for warning in self.warnings:
            on_warning(warning)
        from PIL import Image

        out = io.BytesIO()
        Image.new("RGBA", composition.output_size, (255, 0, 0, 128)).save(out, format="PNG")
        return out.getvalue()


class FakeMatter:
    def __init__(self) -> None:
        self.person_requests: list[PersonRequest] = []

    def frames(self, request):  # pragma: no cover
        raise AssertionError("o recorte de fundo não devia ser pedido")

    def person_frames(self, request: PersonRequest):
        self.person_requests.append(request)
        frame = bytes(request.width * request.height * 4)
        for _ in range(round(request.length * request.fps) - request.warmup_frames):
            yield frame


def _prober(path: Path) -> MediaInfo:
    return MediaInfo(path, 20.0, 1080, 1920, 30.0, True, True, False)


def _write_comp(tmp_path: Path, html: str = "<p>oi</p>", name: str = "comp") -> Path:
    folder = tmp_path / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text(html, encoding="utf-8")
    return folder


def _spec(*overlays: dict, timeline: list[dict] | None = None) -> dict:
    return {
        "name": "composicao",
        "output": {"preset": "instagram/reels"},
        "regions": TOPO,
        "timeline": timeline or [{"type": "clip", "src": "take.mp4", "start": 2, "end": 8}],
        "overlays": [{"type": "html", "src": "comp", "region": "topo", **o} for o in overlays],
        "audio": {"normalize": "off"},
    }


def _render(tmp_path: Path, spec: dict, renderer=None, runner=None, matter=None, **options):
    tmp_path.mkdir(parents=True, exist_ok=True)
    if not (tmp_path / "take.mp4").exists():  # reescrever mudaria o `mtime`, que a chave do mezanino enxerga
        (tmp_path / "take.mp4").write_bytes(b"x")
    if not (tmp_path / "comp").exists():
        _write_comp(tmp_path)
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    renderer = renderer or FakeHtmlRenderer()
    runner = runner or RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    result = RenderPipeline(
        project,
        RenderOptions(**{"preview": True, "quiet": True, "out": tmp_path / "out.mp4", **options}),
        runner=runner,
        prober=_prober,
        transcriber_factory=lambda captions: FakeTranscriber(),
        matter=matter or FakeMatter(),
        html_layers=HtmlLayerBuilder(renderer),
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
    ).run()
    return result, runner, renderer


def _final_graph(result) -> str:
    return (result.job_dir / "graph.txt").read_text(encoding="utf-8")


def test_the_pipeline_renders_the_page_at_the_base_1080_size_and_hands_the_frames_to_ffmpeg(tmp_path: Path):
    result, runner, renderer = _render(tmp_path, _spec({"start": 1.0, "end": 2.0, "data": {"a": 1}}))

    [(composition, times)] = renderer.calls
    # a região "topo" tem 1080x960 no render final; o preview (metade) desenha a MESMA página, menor
    assert composition.size == (1080, 960) and composition.scale == 0.5 and composition.fps == 30
    assert composition.output_size == (540, 480) and composition.duration == pytest.approx(1.0)
    assert composition.data == {"a": 1} and composition.source == tmp_path / "comp"
    assert len(times) == 30 and times[0] == 0.0 and times[-1] == pytest.approx(29 / 30)
    assert composition.colors["accent"] and composition.font_family == "Poppins"

    commands = [" ".join(c) for c in runner.commands]
    html = next(i for i, c in enumerate(commands) if "_html.part.mov" in c)
    final = next(i for i, c in enumerate(commands) if "graph.txt" in c)
    assert html < final and "-s 540x480" in commands[html] and "_html.mov" in commands[final]
    assert runner.frames_consumed == 30
    graph = _final_graph(result)
    assert "overlay=x=0:y=0:eof_action=pass:enable='gte(t,0.983333)*lt(t,1.983333)':format=yuv420" in graph
    cache = tmp_path / "mez"
    assert list(cache.glob("*_html.mov")) and not list(cache.glob("*.part.mov"))
    assert json.loads(next(cache.glob("*_html.json")).read_text(encoding="utf-8")) == {"warnings": []}


def test_the_composition_goes_in_front_of_images_and_before_pip_audiograms_and_text(tmp_path: Path):
    spec = _spec({"start": 1.0, "end": 2.0})
    spec["overlays"] += [
        {"type": "text", "text": "FRENTE", "role": "hook", "start": 0, "end": 5},
        {"type": "progress-bar"},
    ]
    result, _, _ = _render(tmp_path, spec)
    graph = _final_graph(result)
    order = [graph.index(s) for s in ("v_html0_src", "overlay.ass", "[vout]")]
    assert order == sorted(order)


def test_a_composition_not_aligned_to_the_frame_grid_follows_the_requested_start(tmp_path: Path):
    _, _, renderer = _render(tmp_path, _spec({"start": 1.01, "end": 2.0}))
    [(_, times)] = renderer.calls
    assert len(times) == 29  # os quadros 31 a 59: o quadro 30 (1,000 s) é anterior ao início pedido
    assert times[0] == pytest.approx(31 / 30 - 1.01, abs=1e-6)


def test_the_placement_by_center_and_size_needs_no_region(tmp_path: Path):
    spec = _spec({"start": 1.0, "end": 2.0, "x": 0.5, "y": 0.75, "width": 0.5, "height": 0.25})
    spec["overlays"][0].pop("region")
    result, _, renderer = _render(tmp_path, spec)
    [(composition, _)] = renderer.calls
    assert composition.size == (540, 480)
    assert "overlay=x=135:y=600:eof_action=pass" in _final_graph(result)


def test_a_page_with_its_own_size_is_drawn_at_that_size_and_scaled_to_the_area(tmp_path: Path):
    result, _, renderer = _render(tmp_path, _spec({"start": 1.0, "end": 2.0, "size": [1080, 1920]}))
    [(composition, _)] = renderer.calls
    assert composition.size == (1080, 1920) and composition.output_size == (540, 960)
    assert "scale=540:480:flags=lanczos,tpad=" in _final_graph(result)


def test_the_second_render_of_the_same_project_does_not_open_the_page_again(tmp_path: Path):
    spec = _spec({"start": 1.0, "end": 2.0})
    _, first_runner, renderer = _render(tmp_path, spec)
    _, second_runner, _ = _render(tmp_path, spec, renderer)
    assert len(renderer.calls) == 1
    assert not any("_html.part.mov" in " ".join(c) for c in second_runner.commands)
    assert any("_html.mov" in " ".join(c) for c in second_runner.commands if "graph.txt" in " ".join(c))


def test_force_renders_the_page_again_even_when_it_is_in_cache(tmp_path: Path):
    spec = _spec({"start": 1.0, "end": 2.0})
    _, _, renderer = _render(tmp_path, spec)
    _render(tmp_path, spec, renderer, force=True)
    assert len(renderer.calls) == 2


def _cache_key_of(tmp_path: Path, spec: dict, **options) -> str:
    _, _, _ = _render(tmp_path, spec, **options)
    names = sorted(p.name for p in (tmp_path / "mez").glob("*_html.mov"))
    return names[-1]


def test_the_cache_key_follows_the_html_the_files_the_data_the_size_and_the_blur_but_not_the_start(
    tmp_path: Path,
):
    base = _spec({"start": 1.0, "end": 2.0})
    keys = {"base": _cache_key_of(tmp_path / "a", base)}
    same_moved = _spec({"start": 3.0, "end": 4.0})
    keys["moved"] = _cache_key_of(tmp_path / "b", same_moved)
    assert keys["moved"] == keys["base"]  # só o conteúdo conta: a mesma composição noutro instante é a mesma

    def variant(label: str, spec: dict, html: str = "<p>oi</p>", extra_file: str | None = None) -> None:
        folder = tmp_path / label
        _write_comp(folder, html)
        if extra_file:
            (folder / "comp" / extra_file).write_bytes(b"dados")
        keys[label] = _cache_key_of(folder, spec)

    variant("html", base, html="<p>outro</p>")
    variant("arquivo", base, extra_file="foto.png")
    variant("dados", _spec({"start": 1.0, "end": 2.0, "data": {"a": 2}}))
    variant("tamanho", _spec({"start": 1.0, "end": 2.0, "size": [1000, 900]}))
    variant("duracao", _spec({"start": 1.0, "end": 2.5}))
    variant("borrao", _spec({"start": 1.0, "end": 2.0, "motion_blur": True}))
    assert len(set(keys.values())) == len(keys) - 1  # só "moved" repete a chave da base


def test_the_cache_key_follows_the_brand(tmp_path: Path):
    plain = _cache_key_of(tmp_path / "a", _spec({"start": 1.0, "end": 2.0}))
    spec = _spec({"start": 1.0, "end": 2.0})
    spec["brand"] = "medlycare"
    assert _cache_key_of(tmp_path / "b", spec) != plain


def test_the_preview_and_the_final_render_do_not_share_the_cached_video(tmp_path: Path):
    spec = _spec({"start": 1.0, "end": 2.0})
    _render(tmp_path, spec, preview=True)
    _, _, renderer = _render(tmp_path, spec, preview=False)
    assert len(list((tmp_path / "mez").glob("*_html.mov"))) == 2
    [(composition, _)] = renderer.calls
    assert composition.scale == 1.0 and composition.output_size == (1080, 960)


def test_the_motion_blur_asks_the_page_for_the_subframes_and_blends_them_into_one_frame_each(tmp_path: Path):
    _, runner, renderer = _render(
        tmp_path, _spec({"start": 1.0, "end": 2.0, "motion_blur": {"subframes": 4, "shutter": 0.5}})
    )
    [(_, times)] = renderer.calls
    assert len(times) == 30 * 4 and times == sorted(times)
    assert runner.frames_consumed == 30  # um quadro por quadro do vídeo, não um por subquadro


def test_the_blur_costs_time_in_proportion_to_the_subframes_and_leaves_a_sharp_page_alone(tmp_path: Path):
    _, _, sharp = _render(tmp_path / "a", _spec({"start": 1.0, "end": 2.0}))
    _, _, blurred = _render(
        tmp_path / "b", _spec({"start": 1.0, "end": 2.0, "motion_blur": {"subframes": 8}})
    )
    assert len(blurred.calls[0][1]) == 8 * len(sharp.calls[0][1])


def test_what_the_page_tried_and_was_denied_shows_up_in_the_render_result_and_again_from_the_cache(
    tmp_path: Path,
):
    warning = "a composição tentou acessar https://exemplo.com/a.js na internet; o pedido foi bloqueado"
    spec = _spec({"start": 1.0, "end": 2.0})
    first, _, renderer = _render(tmp_path, spec, FakeHtmlRenderer(warnings=[warning]))
    assert any(warning in w and w.startswith("overlays[0] (html comp):") for w in first.warnings)
    again, _, _ = _render(tmp_path, spec, renderer)
    assert len(renderer.calls) == 1  # veio do cache
    assert any(warning in w for w in again.warnings)  # e o aviso não sumiu


def test_a_dry_run_records_the_command_but_never_opens_the_page(tmp_path: Path):
    _, runner, renderer = _render(tmp_path, _spec({"start": 1.0, "end": 2.0}), dry_run=True)
    assert renderer.calls == [] and runner.frames_consumed == 0
    assert any("_html.part.mov" in " ".join(c) for c in runner.commands)


def test_a_page_that_stops_midway_ends_the_render_with_its_error_and_leaves_no_cache_entry(tmp_path: Path):
    with pytest.raises(HtmlRenderFailed, match="a página travou no quadro"):
        _render(tmp_path, _spec({"start": 1.0, "end": 2.0}), FakeHtmlRenderer(fail_at=10))
    cache = tmp_path / "mez"
    assert not list(cache.glob("*_html.mov")) and not list(cache.glob("*.part.mov"))
    assert not list(cache.glob("*_html.json"))


def test_when_ffmpeg_fails_because_of_the_page_the_error_of_the_page_is_the_one_reported(tmp_path: Path):
    class FailingRunner(RecordingRunner):
        def run(self, command):
            if "_html.part.mov" in " ".join(command.args):
                list(command.frames)  # o ffmpeg de verdade lê tudo e só então reclama do arquivo vazio
                raise FFmpegError("ffmpeg falhou em: composição html")
            return super().run(command)

    runner = FailingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    with pytest.raises(HtmlRenderFailed, match="a página travou"):
        _render(tmp_path, _spec({"start": 1.0, "end": 2.0}), FakeHtmlRenderer(fail_at=3), runner)


def test_a_missing_browser_stops_the_render_before_the_mezzanines_and_says_how_to_install_it(tmp_path: Path):
    from dmaker.media.browser import BrowserUnavailable

    renderer = FakeHtmlRenderer(problem="O Chromium não está em bin/playwright. Rode dmaker setup --html.")
    with pytest.raises(BrowserUnavailable, match="dmaker setup --html"):
        _render(tmp_path, _spec({"start": 1.0, "end": 2.0}), renderer)
    assert not (tmp_path / "mez").exists() or not list((tmp_path / "mez").glob("*.mov"))
    _render(
        tmp_path / "seco", _spec({"start": 1.0, "end": 2.0}), renderer, dry_run=True
    )  # no dry-run não faz falta


def test_a_missing_composition_stops_the_render_before_the_mezzanines(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "take.mp4").write_bytes(b"x")
    spec = _spec({"start": 1.0, "end": 2.0, "src": "nao-existe"})
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    pipeline = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=tmp_path / "out.mp4"),
        runner=RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON),
        prober=_prober,
        html_layers=HtmlLayerBuilder(FakeHtmlRenderer()),
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
    )
    with pytest.raises(FileNotFoundError, match="Composição HTML não encontrada"):
        pipeline.run()
    assert not list((tmp_path / "mez").glob("*.mov"))


def test_a_composition_after_the_end_of_the_video_is_dropped(tmp_path: Path):
    result, _, renderer = _render(tmp_path, _spec({"start": 30.0, "end": 31.0}))
    assert renderer.calls == [] and "_html" not in _final_graph(result)


def test_the_layer_version_is_a_pinned_constant():
    # mexer nela invalida o cache só das composições (o MEZZ_VERSION, o MATTE_VERSION e o da pessoa ficam)
    assert HTML_LAYER_VERSION == "h1"


# ---------- atrás da pessoa, no pipeline ----------


def test_a_composition_behind_the_person_asks_for_the_cutout_and_goes_under_the_person(tmp_path: Path):
    spec = _spec({"start": 1.0, "end": 2.0, "layer": "behind-person"})
    spec["overlays"].append(
        {"type": "text", "text": "ATRÁS", "layer": "behind-person", "start": 1.0, "end": 2.0}
    )
    matter = FakeMatter()
    result, _, _ = _render(tmp_path, spec, matter=matter)
    assert len(matter.person_requests) == 1  # a composição e o texto dividem a mesma janela de recorte
    graph = _final_graph(result)
    order = [
        graph.index(s)
        for s in (
            "v_behind0_src",
            "overlay_behind.ass",
            "eof_action=pass:enable='gte(t,0.983333)*lt(t,1.983333)':format=yuv420[v_person0]",
            "[vout]",
        )
    ]
    assert order == sorted(order) and graph.count("v_behind0_src") >= 2
    assert "v_html0" not in graph  # ela não é desenhada também na frente


def test_a_composition_in_front_never_asks_for_a_cutout(tmp_path: Path):
    matter = FakeMatter()
    _render(tmp_path, _spec({"start": 1.0, "end": 2.0}), matter=matter)
    assert matter.person_requests == []


# ---------- projeto sem composição ----------


def test_the_assembly_graph_of_a_project_without_html_is_the_one_from_before(tmp_path: Path):
    """O mesmo projeto e a mesma montagem do teste do DMK-34, gravados antes do DMK-26: sai idêntico, letra por letra."""
    from PIL import Image

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
            {"type": "text", "text": "Gancho", "role": "hook", "start": 0, "end": 0.9},
            {"type": "progress-bar"},
        ],
        "captions": {"source": "auto", "language": "pt"},
        "audio": {"normalize": "two-pass", "music": {"src": "trilha.mp3", "volume": 0.2}},
    }
    (tmp_path / "take.mp4").write_bytes(b"x")
    Image.new("RGB", (1000, 620), "#3366CC").save(tmp_path / "print.png")
    result, _, _ = _render_unit(tmp_path, spec)
    graph = re.sub(r"fontsdir='[^']*'", "fontsdir='FONTS'", _final_graph(result))
    assert graph == GRAPH_BEFORE_DMK_34
    assert "html" not in graph


def test_a_project_without_html_does_not_even_ask_the_renderer_whether_it_works(tmp_path: Path):
    renderer = FakeHtmlRenderer(problem="quebrado")
    spec = _spec()
    spec["overlays"] = []
    result, _, _ = _render(tmp_path, spec, renderer)
    assert renderer.calls == [] and result.output.name == "out.mp4"


# ---------- validação ----------


def test_the_validation_warns_about_a_missing_composition_and_a_missing_browser(tmp_path: Path):
    spec = _spec({"start": 1.0}, {"start": 2.0, "src": "nao-existe"})
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    _write_comp(tmp_path)
    warnings = html_warnings(
        project, lambda: "O Chromium não está em bin/playwright. Rode dmaker setup --html."
    )
    assert len(warnings) == 2
    assert warnings[0].startswith("overlays[1].src: Composição HTML não encontrada")
    assert "o render vai falhar" in warnings[1] and "dmaker setup --html" in warnings[1]
    assert html_warnings(project, lambda: None)[0].startswith("overlays[1].src")
    plain = Project.model_validate({"name": "x", "timeline": [{"type": "card", "title": "x", "duration": 1}]})
    assert html_warnings(plain, lambda: pytest.fail("não devia perguntar")) == []


def test_the_content_digest_follows_every_file_of_the_folder_and_ignores_a_touch(tmp_path: Path):
    folder = _write_comp(tmp_path)
    (folder / "a.json").write_text("{}", encoding="utf-8")
    first = content_digest(folder)
    (folder / "a.json").write_text("{}", encoding="utf-8")  # mesmo conteúdo, mtime novo
    assert content_digest(folder) == first
    (folder / "a.json").write_text('{"x": 1}', encoding="utf-8")
    assert content_digest(folder) != first
    (folder / "sub").mkdir()
    (folder / "sub" / "b.png").write_bytes(b"1")
    assert content_digest(folder) != content_digest(_write_comp(tmp_path, name="outra"))
    single = tmp_path / "solta.html"
    single.write_text("<p>a</p>", encoding="utf-8")
    assert content_digest(single) == content_digest(single)


# ---------- o quadro avulso (CLI e MCP) ----------


def test_parse_size_accepts_the_usual_spellings_and_explains_the_wrong_ones():
    assert parse_size("1080x1920") == (1080, 1920) and parse_size(" 540 X 960 ") == (540, 960)
    for bad in ("1080", "axb", "10x10", "9000x100"):
        with pytest.raises(ValueError):
            parse_size(bad)


def test_the_frame_service_hands_the_composition_the_brand_the_data_and_the_size(tmp_path: Path):
    renderer = FakeHtmlRenderer(warnings=["aviso da página"])
    out = tmp_path / "saida" / "q.png"
    frame = render_html_frame(
        _write_comp(tmp_path),
        out,
        at=1.5,
        size=(1080, 960),
        duration=4.0,
        scale=0.5,
        data={"a": 1},
        brand="medlycare",
        renderer=renderer,
    )
    [(composition, at)] = renderer.stills
    assert at == 1.5 and composition.size == (1080, 960) and composition.duration == 4.0
    assert (
        composition.data == {"a": 1}
        and composition.colors["accent"] == load_theme("medlycare").colors["accent"]
    )
    assert frame.size == (540, 480) and frame.warnings == ["aviso da página"]
    assert out.read_bytes().startswith(b"\x89PNG")


def test_the_frame_can_be_laid_over_a_solid_colour_so_the_transparent_part_can_be_seen(tmp_path: Path):
    from PIL import Image

    out = tmp_path / "q.png"
    render_html_frame(
        _write_comp(tmp_path), out, size=(40, 20), background="#00FF00", renderer=FakeHtmlRenderer()
    )
    pixel = Image.open(out).convert("RGBA").getpixel((5, 5))
    assert pixel[3] == 255 and pixel[1] > 120 and pixel[0] > 100  # o vermelho a 50% sobre o verde
    kept = tmp_path / "k.png"
    render_html_frame(_write_comp(tmp_path), kept, size=(40, 20), renderer=FakeHtmlRenderer())
    assert Image.open(kept).convert("RGBA").getpixel((5, 5)) == (255, 0, 0, 128)


def test_the_frame_service_refuses_nonsense_before_opening_a_browser(tmp_path: Path):
    renderer = FakeHtmlRenderer()
    with pytest.raises(ValueError, match="positivos"):
        render_html_frame(_write_comp(tmp_path), tmp_path / "q.png", at=-1, renderer=renderer)
    with pytest.raises(FileNotFoundError):
        render_html_frame(tmp_path / "nao-existe", tmp_path / "q.png", renderer=renderer)
    assert renderer.stills == []


def test_the_default_frame_path_is_named_after_the_composition_and_the_instant(tmp_path: Path):
    assert default_frame_path(tmp_path, tmp_path / "planta", 2.5) == tmp_path / "html" / "planta_002.50s.png"
    single = tmp_path / "titulo.html"
    single.write_text("x", encoding="utf-8")
    assert default_frame_path(tmp_path, single, 0) == tmp_path / "html" / "titulo_000.00s.png"


def test_the_cli_frame_command_writes_the_png_and_shows_the_warnings(monkeypatch, tmp_path: Path):
    from typer.testing import CliRunner

    from dmaker.cli import app
    from dmaker.pipeline import html_frame

    renderer = FakeHtmlRenderer(warnings=["bloqueado: https://x.y/z"])
    monkeypatch.setattr(html_frame, "PlaywrightHtmlRenderer", lambda: renderer)
    comp = _write_comp(tmp_path)
    out = tmp_path / "q.png"
    result = CliRunner().invoke(
        app,
        [
            "html",
            "frame",
            str(comp),
            "--at",
            "2",
            "--size",
            "1080x960",
            "--out",
            str(out),
            "--data",
            '{"t": "Oi"}',
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Quadro salvo" in result.output and "bloqueado" in result.output
    [(composition, at)] = renderer.stills
    assert at == 2.0 and composition.data == {"t": "Oi"} and out.exists()
    bad = CliRunner().invoke(app, ["html", "frame", str(comp), "--size", "tudo"])
    assert bad.exit_code == 1 and "tamanho inválido" in bad.output
    worse = CliRunner().invoke(app, ["html", "frame", str(comp), "--data", "[1]"])
    assert worse.exit_code == 1 and "objeto JSON" in worse.output
    missing = CliRunner().invoke(app, ["html", "frame", str(tmp_path / "nada")])
    assert missing.exit_code == 1 and "não encontrada" in missing.output


def test_the_setup_command_with_html_only_installs_the_chromium(monkeypatch):
    from typer.testing import CliRunner

    from dmaker import setup_tools
    from dmaker.cli import app

    called = []
    monkeypatch.setattr(setup_tools, "install_chromium", lambda: called.append("chromium"))
    monkeypatch.setattr(
        setup_tools, "install_ffmpeg", lambda force=False: pytest.fail("não devia baixar o ffmpeg")
    )
    result = CliRunner().invoke(app, ["setup", "--html"])
    assert result.exit_code == 0 and called == ["chromium"]
    monkeypatch.setattr(
        setup_tools, "install_chromium", lambda: (_ for _ in ()).throw(RuntimeError("falhou"))
    )
    assert CliRunner().invoke(app, ["setup", "--html"]).exit_code == 1


def test_the_mcp_tools_for_the_html_frame_and_the_overlay_are_registered_with_the_fixed_names():
    import asyncio

    from dmaker import mcp_server

    tools = {tool.name: tool for tool in asyncio.run(mcp_server.server.list_tools())}
    assert {"render_html_frame", "add_html_overlay"} <= set(tools)
    assert "dmaker.data" in tools["render_html_frame"].description
    assert "behind-person" in tools["add_html_overlay"].description


def test_the_mcp_frame_tool_returns_the_image_and_the_warnings(monkeypatch, tmp_path: Path):
    from dmaker import mcp_server
    from dmaker.pipeline import html_frame

    renderer = FakeHtmlRenderer(warnings=["aviso"])
    monkeypatch.setattr(html_frame, "PlaywrightHtmlRenderer", lambda: renderer)
    comp = _write_comp(tmp_path)
    info, image = mcp_server.render_html_frame(str(comp), at=1.0, size="1080x960", background="#808080")
    assert info["at_s"] == 1.0 and info["size"] == "1080x960" and info["warnings"] == ["aviso"]
    assert Path(info["image"]).exists() and Path(info["image"]).is_relative_to(config.OUTPUT_DIR / "html")
    assert image.__class__.__name__ == "Image"


def test_the_mcp_overlay_tool_adds_a_validated_overlay_to_the_saved_project():
    from dmaker import mcp_server
    from dmaker.pipeline.projects import load_project, save_project

    project = Project.model_validate(
        {"name": "para-html", "timeline": [{"type": "card", "title": "x", "duration": 4}], "regions": TOPO}
    )
    save_project(project)
    result = mcp_server.add_html_overlay(
        "para-html", "composicoes/titulo", start=1, end=3, region="topo", data={"t": "Oi"}, motion_blur=True
    )
    assert result["overlay_index"] == 0 and result["spec_path"].endswith("spec.json")
    added = load_project("para-html").overlays[0]
    assert (added.type, added.src, added.region, added.layer) == (
        "html",
        "composicoes/titulo",
        "topo",
        "front",
    )
    assert added.data == {"t": "Oi"} and added.motion_blur == MotionBlur()
    assert any("Composição HTML não encontrada" in w for w in result["warnings"])  # a pasta ainda não existe
    with pytest.raises(EditError, match="região desconhecida"):
        mcp_server.add_html_overlay("para-html", "composicoes/titulo", region="nao-existe")
    with pytest.raises(EditError):
        mcp_server.add_html_overlay("para-html", "x", x=0.5)


def test_insert_html_overlay_keeps_the_project_untouched_and_validates_the_result():
    project = Project.model_validate(
        {"name": "p", "timeline": [{"type": "card", "title": "x", "duration": 4}]}
    )
    changed = insert_html_overlay(project, {"src": "c", "start": 1})
    assert project.overlays == [] and changed.overlays[0].src == "c"
    with pytest.raises(EditError):
        insert_html_overlay(project, {"src": "c", "start": 3, "end": 2})


def test_an_html_overlay_survives_save_and_load_through_the_ui_api(tmp_path: Path):
    from fastapi.testclient import TestClient

    from dmaker.ui import server

    client = TestClient(server.app)
    spec = {
        "name": "html-ui",
        "timeline": [{"type": "card", "title": "x", "duration": 4}],
        "overlays": [
            {"type": "html", "src": "comp", "data": {"titulo": "Oi"}, "motion_blur": {"subframes": 3}}
        ],
    }
    assert client.put("/api/projects/html-ui", json=spec).json()["ok"]
    loaded = client.get("/api/projects/html-ui").json()["spec"]
    assert (
        loaded["overlays"][0]["data"] == {"titulo": "Oi"}
        and loaded["overlays"][0]["motion_blur"]["subframes"] == 3
    )
    loaded["overlays"][0]["start"] = 1.5  # a interface edita um campo e devolve o projeto inteiro
    assert client.put("/api/projects/html-ui", json=loaded).json()["ok"]
    again = client.get("/api/projects/html-ui").json()["spec"]["overlays"][0]
    assert again["start"] == 1.5 and again["data"] == {"titulo": "Oi"} and again["type"] == "html"


# ---------- a documentação ----------


def _guide_section() -> str:
    guide = (config.PACKAGE_DIR / "resources" / "guide.md").read_text(encoding="utf-8")
    start = guide.index("### Composição animada em HTML")
    return guide[start : guide.index("\n## ", start)]


def test_the_guide_documents_the_contract_the_tools_and_every_field_of_the_overlay():
    section = _guide_section()
    for field in set(HtmlOverlay.model_fields) - {"type"}:  # o `type` aparece no título da seção
        assert f"`{field}`" in section, f"o guia não descreve o campo {field} da composição"
    for name in (
        "window.dmakerSeek",
        "window.dmakerReady",
        "dmaker.data",
        "dmaker.noise3",
        "--dm-accent",
        "--dm-font",
        "/_dmaker/three.module.min.js",
        "/_dmaker/lottie.min.js",
        "render_html_frame",
        "add_html_overlay",
        "dmaker html frame",
        "dmaker setup --html",
    ):
        assert name in section, f"o guia não cita {name}"
    for rule in ("Gráfico maior e mais simples", "entrada e saída", "Sem estilo global", "variáveis CSS"):
        assert rule.lower() in section.lower(), f"o guia de boas práticas não traz: {rule}"
    assert not any(dash in section for dash in DASHES)
    assert section.count("```html") >= 3  # o número em CSS, o objeto three.js e o Lottie


def test_the_skill_points_to_the_html_composition_in_the_guide():
    skill = (config.ROOT / ".claude" / "skills" / "dmaker" / "SKILL.md").read_text(encoding="utf-8")
    assert "render_html_frame" in skill and "Composição animada em HTML" in skill


def test_the_cli_shows_the_install_hint_with_its_square_brackets_when_the_chromium_is_missing(
    monkeypatch, tmp_path
):
    """O Rich lê `[html]` como marcação e o apagaria da instrução: a mensagem sai com o extra inteiro."""
    from typer.testing import CliRunner

    from dmaker.cli import app

    monkeypatch.setattr(config, "PLAYWRIGHT_DIR", tmp_path / "sem-chromium")
    comp = _write_comp(tmp_path)
    result = CliRunner().invoke(app, ["html", "frame", str(comp), "--out", str(tmp_path / "q.png")])
    assert result.exit_code == 1
    flat = " ".join(result.output.split())
    assert 'pip install -e ".[html]"' in flat and "dmaker setup --html" in flat
