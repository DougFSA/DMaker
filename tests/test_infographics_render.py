"""Os infográficos prontos renderizados de verdade (DMK-24): o Chromium do Playwright e o ffmpeg reais.

O que nenhum teste com renderizador falso enxerga: o contador contando com easing e parando no valor exato, a barra
enchendo até 95 de 400 com a marca do limite, a linha se desenhando sem serrilhado, a imagem entrando nítida, a troca
de marca mudando cores e fonte sem editar o HTML, os cinco juntos no vídeo sem invadir a zona segura e o grifo que
circula a palavra da legenda no tempo dela, desenhado como traço. Pulam, com o motivo, quando o Chromium não está
instalado (`dmaker setup --html`)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from dmaker import config
from dmaker.domain.brand import load_theme
from dmaker.domain.infographics import find_infographic, resolve_infographic
from dmaker.domain.presets import get_preset
from dmaker.domain.spec import CaptionStyle, HtmlOverlay, Project
from dmaker.media.browser import browser_problem
from dmaker.media.html_render import HtmlComposition, PlaywrightHtmlRenderer
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.html_layer import brand_page_fields
from dmaker.pipeline.report import build_report
from dmaker.text.caption_layout import find_caption_word
from dmaker.text.captions import Cue, Word, to_json
from dmaker.text.overlays import Canvas

from .conftest import requires_ffmpeg
from .test_html_render import FPS, comp, open_page, png_to_array

PROBLEM = browser_problem()
pytestmark = pytest.mark.skipif(PROBLEM is not None, reason=f"Chromium do Playwright indisponível: {PROBLEM}")

MEDLYCARE_ACCENT = (0x75, 0xB9, 0xA2)
DEFAULT_ACCENT = (0xFA, 0xCC, 0x15)  # o casamento-azul não declara `accent`: vale o do tema padrão


@pytest.fixture(scope="module")
def renderer() -> Iterator[PlaywrightHtmlRenderer]:
    """Um Chromium só para o módulo todo: abrir leva um segundo e cada teste abriria o seu."""
    with PlaywrightHtmlRenderer() as shared:
        yield shared


def page(name: str, brand: str | None = None, *, size=None, duration: float = 4.0, theme=None, **params):
    """A composição de um modelo pronto com os parâmetros pedidos, como o pipeline a entrega ao renderizador."""
    model = find_infographic(name)
    resolved = resolve_infographic(HtmlOverlay(infographic=name, data=params), None)
    return HtmlComposition(
        source=model.folder,
        size=size or model.schema.size,
        duration=duration,
        data=resolved.data,
        files={key: Path(path) for key, path in resolved.files.items()},
        **brand_page_fields(theme or load_theme(brand)),
    )


def still(renderer, composition, at: float) -> np.ndarray:
    return png_to_array(renderer.still(composition, at, print))


def close_to(frame: np.ndarray, color, tolerance: int = 30) -> np.ndarray:
    """Pixels de alfa pleno cuja cor é a pedida (o traço ou a barra na cor da marca)."""
    return (np.abs(frame[..., :3].astype(int) - np.array(color)).sum(axis=2) <= tolerance) & (
        frame[..., 3] > 200
    )


# ---------- o contador ----------


def counter_text(opened) -> str:
    return opened.js("document.getElementById('numero').textContent")


def test_the_counter_goes_from_0_to_10000_in_1_2_s_with_easing_ends_exactly_and_stays_still(renderer):
    with open_page(renderer, page("contador", ate=10000, prefixo="+ de R$", duracao=1.2)) as (
        opened,
        warnings,
    ):
        shown = []
        for index in range(0, 121):  # 4 s, quadro a quadro, como o render
            opened.seek(index / FPS)
            shown.append(counter_text(opened))
        prefix = opened.js("document.getElementById('prefixo').textContent")
    numbers = [int(text.replace(".", "")) for text in shown]
    assert shown[0] == "0" and prefix == "+ de R$" and warnings == []
    assert (
        shown[36] == "10.000" and numbers[30] < 10000
    )  # chega exatamente no valor em 1,2 s, e não antes de 1 s
    assert set(shown[36:]) == {"10.000"}  # e fica parado até o fim
    assert numbers == sorted(numbers)  # só sobe
    assert numbers[18] > 8000  # com easing, a metade do tempo já passou de 80% (linear daria 5.000)
    steps = np.diff(numbers[:31])
    assert steps[0] > 4 * steps[-1] > 0  # começa rápido e desacelera até o valor


def test_the_counter_formats_decimals_and_negatives_the_brazilian_way(renderer):
    with open_page(renderer, page("contador", de=0, ate=1234.5, casas=1)) as (opened, _):
        opened.seek(3.0)
        assert counter_text(opened) == "1.234,5"
    with open_page(renderer, page("contador", de=100, ate=-2500)) as (opened, _):
        opened.seek(3.0)
        assert counter_text(opened) == "-2.500"


def test_the_counter_picture_stops_changing_when_it_reaches_the_value(renderer):
    composition = page("contador", "medlycare", ate=10000, prefixo="+ de R$")
    settled, later = still(renderer, composition, 1.5), still(renderer, composition, 3.0)
    # parado: o Chromium pode arredondar a cor de um pixel de borda em 1 nível de uma captura para outra, nada além
    assert np.abs(settled.astype(int) - later.astype(int)).max() <= 2
    assert (
        np.abs(still(renderer, composition, 0.6).astype(int) - settled.astype(int)).max() > 50
    )  # contando, não


# ---------- a barra ----------


def test_the_bar_fills_to_95_of_400_and_the_limit_mark_is_visible(renderer):
    composition = page(
        "barra", "medlycare", valor=95, maximo=400, limite=400, sufixo="mg", rotulo="de cafeína"
    )
    with open_page(renderer, composition) as (opened, warnings):
        opened.seek(0.0)
        empty = opened.js("document.getElementById('enche').getBoundingClientRect().width")
        opened.seek(2.4)
        geometry = opened.js(
            """(() => {
              const track = document.querySelector('.trilho').getBoundingClientRect();
              const fill = document.getElementById('enche').getBoundingClientRect();
              const mark = document.getElementById('limite').getBoundingClientRect();
              return {fill: fill.width / track.width, trackLeft: track.left, trackWidth: track.width,
                      trackMid: track.top + track.height / 2, markLeft: mark.left, markRight: mark.right,
                      markTop: mark.top, markBottom: mark.bottom, value: document.getElementById('valor').textContent,
                      shown: getComputedStyle(document.getElementById('limite')).display};
            })()"""
        )
    assert empty == 0 and warnings == []
    assert geometry["fill"] == pytest.approx(95 / 400, abs=0.002) and geometry["value"] == "95"
    assert (
        geometry["shown"] != "none" and 0 < geometry["markLeft"] and geometry["markRight"] <= 900
    )  # a marca cabe

    frame = still(renderer, composition, 2.4)
    row = int(geometry["trackMid"])
    painted = close_to(frame, MEDLYCARE_ACCENT)[row]
    left = geometry["trackLeft"]
    fill_pixels = painted[int(left) : int(left + geometry["trackWidth"])].sum()
    assert fill_pixels / geometry["trackWidth"] == pytest.approx(
        95 / 400, abs=0.01
    )  # o que se vê é o que a conta diz
    mark_x = int((geometry["markLeft"] + geometry["markRight"]) / 2)
    mark = frame[int(geometry["markTop"]) + 3 : int(geometry["markBottom"]) - 3, mark_x]
    assert (mark[:, 3] > 200).mean() > 0.9  # a haste do limite está desenhada, de ponta a ponta


@pytest.mark.parametrize(
    "size", [(778, 509), (900, 300), (778, 192)], ids=["topo-do-explicativo", "natural", "baixa"]
)
def test_the_bar_text_fits_inside_any_shape_of_region_without_the_labels_colliding(renderer, size):
    """A região "topo" do modelo explicativo é larga e alta (1080 x 509 no render final): a barra mede pela menor das
    proporções da página, e a descrição do valor e o nome do limite cabem sem se encostar."""
    composition = page(
        "barra", "medlycare", size=size, valor=95, maximo=400, limite=400, sufixo="mg", rotulo="de cafeína"
    )
    with open_page(renderer, composition) as (opened, warnings):
        opened.seek(2.4)
        boxes = opened.js(
            """(() => {
              const box = (selector) => { const r = document.querySelector(selector).getBoundingClientRect();
                                          return [r.left, r.top, r.right, r.bottom]; };
              return {value: box('#valor'), description: box('#rotulo'), limit: box('#limite-nome'),
                      track: box('.trilho'), scale: box('.escala')};
            })()"""
        )
    width, height = size
    assert warnings == []
    for name, (left, top, right, bottom) in boxes.items():
        assert 0 <= left and right <= width and 0 <= top and bottom <= height, f"{name} sai da página {size}"
    description, limit = boxes["description"], boxes["limit"]
    apart = description[2] < limit[0] or limit[2] < description[0] or description[3] < limit[1]
    assert apart, "a descrição do valor e o nome do limite se encostam"


# ---------- a linha ----------


def test_the_line_is_drawn_from_a_to_b_without_jaggies(renderer):
    composition = page("linha", "medlycare", rotulo="2 quadras da praia", pontas="nenhuma", espessura=8)
    a, b = np.array([0.12 * 900, 0.75 * 500]), np.array([0.88 * 900, 0.25 * 500])
    along = (b - a) / np.linalg.norm(b - a)

    def reach(frame) -> float:
        """Até onde a tinta da linha chega a partir de A, medido sobre a reta A-B (0 se não há linha)."""
        ys, xs = np.nonzero(close_to(frame, MEDLYCARE_ACCENT))
        return float(((np.stack([xs, ys], axis=1) - a) @ along).max()) if len(xs) else 0.0

    reaches = [reach(still(renderer, composition, at)) for at in (0.0, 0.3, 0.6, 1.0, 2.0)]
    length = float(np.linalg.norm(b - a))
    assert reaches[0] == 0  # antes de começar não há nada (e o rótulo ainda não surgiu)
    assert reaches[1] < reaches[2] < reaches[3]  # se desenha, e não aparece pronta
    assert reaches[3] == pytest.approx(length + 4, abs=6) and reaches[4] == reaches[3]  # chega em B e para

    final = still(renderer, composition, 2.0)
    alpha = final[..., 3]
    line = close_to(final, MEDLYCARE_ACCENT, 60) | ((alpha > 0) & (alpha <= 200))
    edge = (alpha > 0) & (alpha < 255) & line
    ink = (alpha > 0) & line
    assert edge.sum() / ink.sum() > 0.10  # a borda tem meios-tons: serrilhado teria alfa só 0 ou 255
    # e a transição atravessando a linha é suave: o perfil vertical no meio do traço sobe e desce por degraus finos
    x = int((a[0] + b[0]) / 2)
    profile = alpha[:, x][alpha[:, x] > 0].astype(int)
    assert len(profile) >= 9 and np.abs(np.diff(profile)).max() < 200


# ---------- a imagem ----------


def crisp_image(path: Path) -> Path:
    """Um PNG com transparência e bordas verticais nítidas, do tamanho da página (um pixel de imagem por pixel)."""
    image = Image.new("RGBA", (800, 600), (0, 0, 0, 0))
    block = Image.new("RGBA", (400, 300), (230, 30, 30, 255))
    image.paste(block, (200, 150))
    image.save(path)
    return path


def edge_sharpness(frame: np.ndarray, scale: float = 1.0) -> float:
    """A força média da borda esquerda do bloco: o maior salto de alfa entre pixels vizinhos nas linhas do meio
    (255 é uma borda de um pixel só; uma borda reamostrada, borrada, tem um salto menor)."""
    rows = frame[int(250 * scale) : int(450 * scale), :, 3].astype(int)
    return float(np.abs(np.diff(rows, axis=1)).max(axis=1).mean())


@pytest.mark.parametrize("scale", [1.0, 0.5], ids=["final", "previa"])
def test_an_image_with_alpha_slides_in_and_stays_as_sharp_in_the_middle_of_the_move_as_standing_still(
    renderer, tmp_path: Path, scale: float
):
    picture = crisp_image(tmp_path / "bloco.png")
    moving = page(
        "imagem", arquivo=str(picture), entrada="slide", direcao="esquerda", ken_burns=0, sombra=False
    )
    moving = HtmlComposition(**{**moving.__dict__, "scale": scale})
    mid = still(renderer, moving, 0.3)  # no meio do deslize (ele dura 0,7 s)
    done = still(renderer, moving, 2.0)
    assert not np.array_equal(mid, done)  # de fato estava em movimento
    assert (mid[..., 3] > 0).any() and (done[..., 3] > 0).any()
    still_edge, moving_edge = edge_sharpness(done, scale), edge_sharpness(mid, scale)
    assert still_edge > 100  # a imagem parada tem a borda nítida (esta é a régua)
    assert moving_edge >= 0.95 * still_edge  # e no meio do movimento não perdeu nitidez


def test_the_default_slow_zoom_keeps_the_edge_at_least_two_thirds_as_sharp_as_the_still_image(
    renderer, tmp_path: Path
):
    picture = crisp_image(tmp_path / "bloco.png")
    composition = page("imagem", arquivo=str(picture), sombra=False)  # entrada slide e Ken Burns padrão
    moving = edge_sharpness(still(renderer, composition, 0.3))
    resting = edge_sharpness(
        still(renderer, page("imagem", arquivo=str(picture), ken_burns=0, sombra=False), 2.0)
    )
    assert moving >= resting * 2 / 3


def test_the_three_entrances_land_on_the_same_resting_picture(renderer, tmp_path: Path):
    picture = crisp_image(tmp_path / "bloco.png")
    rested = [
        still(renderer, page("imagem", arquivo=str(picture), entrada=entrada, ken_burns=0), 2.0)
        for entrada in ("slide", "pop", "zoom")
    ]
    assert np.array_equal(rested[0], rested[1]) and np.array_equal(rested[0], rested[2])


# ---------- a marca ----------


def accent_pixels(frame: np.ndarray, color) -> int:
    return int(close_to(frame, color, 24).sum())


@pytest.mark.parametrize(
    "name, params",
    [
        ("contador", {"ate": 10000, "prefixo": "+ de R$"}),
        ("barra", {"valor": 95, "maximo": 400, "limite": 400, "sufixo": "mg"}),
        ("linha", {"rotulo": "2 quadras da praia"}),
        ("etiqueta", {"texto": "QUARTO"}),
    ],
)
def test_swapping_the_brand_changes_the_colors_of_the_model_without_touching_the_html(renderer, name, params):
    medlycare = still(renderer, page(name, "medlycare", **params), 2.4)
    azul = still(renderer, page(name, "casamento-azul", **params), 2.4)
    assert not np.array_equal(medlycare, azul)
    # as cores amostradas são as da marca: o verde do medlycare numa, o amarelo do tema padrão na outra
    assert accent_pixels(medlycare, MEDLYCARE_ACCENT) > 300 and accent_pixels(azul, MEDLYCARE_ACCENT) == 0
    assert accent_pixels(azul, DEFAULT_ACCENT) > 300 and accent_pixels(medlycare, DEFAULT_ACCENT) == 0


def test_the_brand_font_reaches_the_page_and_changes_the_drawing(renderer):
    windows_font = config.WINDOWS_FONTS_DIR / "bahnschrift.ttf"
    if not windows_font.exists():
        pytest.skip("a Bahnschrift do Windows não está nesta máquina")
    brand = load_theme("casamento-azul", {"fonts": {"family": "Bahnschrift"}})
    other = page("contador", theme=brand, ate=10000, prefixo="+ de R$")
    poppins = page("contador", "casamento-azul", ate=10000, prefixo="+ de R$")
    with open_page(renderer, other) as (opened, warnings):
        opened.seek(3.0)
        loaded = opened.js("[...document.fonts].filter(f => f.status === 'loaded').map(f => f.family)")
        css = opened.js("getComputedStyle(document.documentElement).getPropertyValue('--dm-font')")
    assert "Bahnschrift" in [name.strip('"') for name in loaded] and "Bahnschrift" in css and warnings == []
    swapped, original = still(renderer, other, 3.0), still(renderer, poppins, 3.0)
    assert not np.array_equal(swapped, original)
    # a conta é a mesma, a letra é outra: a tinta ocupa um espaço diferente
    assert swapped[..., 3].astype(bool).sum() != original[..., 3].astype(bool).sum()


def test_the_role_fonts_of_a_brand_become_css_variables_the_composition_can_use(renderer, tmp_path: Path):
    """O casamento-azul declara a fonte `script` (Great Vibes): chega à página como `--dm-font-script`."""
    html = (
        "<style>html,body{margin:0}p{font:80px var(--dm-font-script);color:#fff;margin:0}"
        "q{font:80px var(--dm-font);color:#fff}</style><p>Maria</p><q>Maria</q>"
    )
    folder = tmp_path / "script"
    folder.mkdir()
    (folder / "index.html").write_text(html, encoding="utf-8")
    composition = comp(folder, size=(500, 300), **brand_page_fields(load_theme("casamento-azul")))
    with open_page(renderer, composition) as (opened, warnings):
        opened.seek(0.0)
        family = opened.js("getComputedStyle(document.querySelector('p')).fontFamily")
        loaded = opened.js("[...document.fonts].filter(f => f.status === 'loaded').map(f => f.family)")
        script_width = opened.js("document.querySelector('p').getBoundingClientRect().width")
        sans_width = opened.js("document.querySelector('q').getBoundingClientRect().width")
    assert family.startswith("dm-script") and "dm-script" in [name.strip('"') for name in loaded]
    assert script_width != sans_width and warnings == []


# ---------- no vídeo ----------

WALL = (64, 112, 160)


@pytest.fixture(scope="module")
def wall(tmp_path_factory) -> Path:
    from tests.test_behind_person_render import _wall_clip

    return _wall_clip(tmp_path_factory.mktemp("parede") / "wall.mp4", 8.0)


def render(tmp_path: Path, spec: dict, renderer, *, fps: int = FPS) -> np.ndarray:
    """O projeto inteiro pelo pipeline, com o Chromium e o ffmpeg de verdade e a saída sem perdas: os quadros em
    RGB (n, 960, 540, 3), o preview do reels."""
    from dmaker.pipeline.html_layer import HtmlLayerBuilder
    from tests.test_behind_person_render import LosslessRunner, _frames

    project = Project.model_validate(
        {
            **spec,
            "output": {**spec.get("output", {}), "preset": "instagram/reels", "fps": fps, "quality": "draft"},
        }
    )
    project.base_dir = tmp_path
    out = tmp_path / "out.mkv"
    RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=out, thumbnail=False),
        runner=LosslessRunner(),
        html_layers=HtmlLayerBuilder(renderer),
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
    ).run()
    return _frames(out)


@requires_ffmpeg
def test_the_five_models_render_together_in_one_video_and_the_qa_finds_nothing_outside_the_safe_zone(
    tmp_path: Path, wall: Path, renderer
):
    picture = crisp_image(tmp_path / "bloco.png")
    spec = {
        "name": "cinco",
        "regions": {
            "um": {"x": 0.5, "y": 0.2, "width": 0.72, "height": 0.1},
            "dois": {"x": 0.5, "y": 0.32, "width": 0.72, "height": 0.1},
            "tres": {"x": 0.5, "y": 0.47, "width": 0.72, "height": 0.16},
            "quatro": {"x": 0.5, "y": 0.62, "width": 0.5, "height": 0.2},
            "cinco": {"x": 0.5, "y": 0.74, "width": 0.5, "height": 0.07},
        },
        "timeline": [{"type": "clip", "src": str(wall), "start": 0, "end": 6}],
        "overlays": [
            {"type": "html", "infographic": "contador", "region": "um", "start": 0.5, "end": 5.5, "data": {"ate": 10000, "prefixo": "+ de R$"}},
            {"type": "html", "infographic": "barra", "region": "dois", "start": 0.5, "end": 5.5, "data": {"valor": 95, "maximo": 400, "limite": 400, "sufixo": "mg"}},
            {"type": "html", "infographic": "linha", "region": "tres", "start": 0.5, "end": 5.5, "data": {"rotulo": "2 quadras da praia"}},
            {"type": "html", "infographic": "imagem", "region": "quatro", "start": 0.5, "end": 5.5, "data": {"arquivo": str(picture)}},
            {"type": "html", "infographic": "etiqueta", "region": "cinco", "start": 0.5, "end": 5.5, "data": {"texto": "QUARTO"}},
        ],
        "brand": "medlycare",
        "audio": {"normalize": "off"},
    }  # fmt: skip
    frames = render(tmp_path, spec, renderer, fps=10)
    assert frames.shape[1:] == (960, 540, 3)
    # cada região tem tinta que não existia no começo (a parede lisa): os cinco entraram, cada um no seu lugar
    start, end = frames[2].astype(int), frames[40].astype(int)
    for name, region in spec["regions"].items():
        top, bottom = (
            int((region["y"] - region["height"] / 2) * 960),
            int((region["y"] + region["height"] / 2) * 960),
        )
        changed = np.abs(end[top:bottom] - start[top:bottom]).sum(axis=2) > 40
        assert changed.mean() > 0.01, f"a região {name} ficou vazia"

    from dmaker.media.probe import probe

    report = build_report(
        Project.model_validate({**spec, "output": {"preset": "instagram/reels"}}), prober=probe
    )
    assert [f for f in report.findings if f.where.startswith("overlays")] == []


# ---------- o grifo na palavra da legenda ----------

WORDS = [Word(0.5, 1.0, "hoje"), Word(1.0, 1.6, "faz"), Word(1.6, 2.4, "frio"), Word(2.4, 3.5, "demais")]
HIGHLIGHT, RING = (255, 0, 255), (0, 255, 0)


def grifo_spec(tmp_path: Path, wall: Path, mode: str, **grifo) -> dict:
    (tmp_path / "legenda.json").write_text(
        to_json([Cue(0.5, 3.5, "hoje faz frio demais", WORDS)]), encoding="utf-8"
    )
    return {
        "name": "grifo",
        "timeline": [{"type": "clip", "src": str(wall), "start": 0, "end": 5}],
        "overlays": [
            {"type": "html", "infographic": "grifo", "data": {"palavra": "frio", "tipo": "circulo", "cor": "#00FF00", "passadas": 1, **grifo}}
        ],
        "captions": {
            "source": "legenda.json",
            "style": {"mode": mode, "size": 80, "color": "#FFFFFF", "highlight_color": "#FF00FF", "uppercase": False, "follow_background": False, "outline": 0, "shadow": 0, "max_words": 4, "max_chars": 30, "y": 0.5},
        },
        "audio": {"normalize": "off"},
    }  # fmt: skip


def bounding_box(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    return (xs.min(), ys.min(), xs.max(), ys.max()) if len(xs) else None


def near(frame: np.ndarray, color, tolerance: int) -> np.ndarray:
    return np.abs(frame.astype(int) - np.array(color)).sum(axis=2) < tolerance


@requires_ffmpeg
@pytest.mark.parametrize("mode", ["karaoke", "rounded"])
def test_the_layout_of_the_caption_word_matches_what_the_renderer_draws(
    tmp_path: Path, wall: Path, renderer, mode
):
    """A caixa que o DMaker calcula para a palavra é a que o libass desenha: a palavra da vez, em magenta, fica
    dentro dela (com a folga da conta, que usa a largura de avanço da letra)."""
    spec = grifo_spec(tmp_path, wall, mode)
    spec["overlays"] = []
    frames = render(tmp_path, spec, renderer)
    preset = get_preset("instagram/reels").preview()
    canvas = Canvas(preset.width, preset.height, preset.safe, load_theme(None), 5.0)
    cues = [Cue(0.5, 3.5, "hoje faz frio demais", WORDS)]
    for word in ("faz", "frio", "demais"):
        placed = find_caption_word(cues, word, CaptionStyle(**spec["captions"]["style"]), canvas)
        mid = (placed.start + placed.end) / 2
        left, top, right, bottom = bounding_box(near(frames[int(mid * FPS)], HIGHLIGHT, 60))
        assert placed.left - 4 <= left <= placed.left + 4 and placed.top - 4 <= top <= placed.top + 4, (
            word,
            mode,
        )
        assert right <= placed.right + 1 and right >= placed.right - 6 and bottom <= placed.bottom + 2, (
            word,
            mode,
        )


@requires_ffmpeg
def test_the_grifo_circles_the_caption_word_in_its_own_time_and_is_drawn_as_a_stroke(
    tmp_path: Path, wall: Path, renderer
):
    frames = render(tmp_path, grifo_spec(tmp_path, wall, "karaoke", duracao=0.7, espessura=6), renderer)
    ring = [int(near(frame, RING, 120).sum()) for frame in frames]
    word = bounding_box(near(frames[int(2.0 * FPS)], HIGHLIGHT, 60))  # "frio", em magenta enquanto é dito
    assert word is not None
    # no tempo da palavra: nada antes de ela ser dita (1,6 s), traço crescendo depois, círculo completo e parado
    assert max(ring[: int(1.6 * FPS) - 1]) == 0
    drawing = ring[int(1.6 * FPS) : int(2.4 * FPS)]
    assert (
        drawing[2] > 0 and drawing[3] < drawing[-1] * 0.7
    )  # não aparece pronto: começa por um pedaço do traço
    assert (np.diff(drawing) >= 0).all()  # o traço só cresce enquanto se desenha
    final = int(2.5 * FPS)
    assert ring[final] == ring[int(3.0 * FPS)] > 150  # parou de crescer
    assert ring[int(3.7 * FPS)] == 0  # saiu junto com a linha da legenda (3,5 s)

    # o círculo envolve a palavra: a tinta dele passa dos quatro lados, fora das letras
    circle = near(frames[final], RING, 120)
    left, top, right, bottom = bounding_box(circle)
    word_left, word_top, word_right, word_bottom = word
    assert left < word_left - 3 and right > word_right + 3 and top < word_top - 3 and bottom > word_bottom + 3
    center_x, center_y = (word_left + word_right) // 2, (word_top + word_bottom) // 2
    quadrants = {
        "alto à esquerda": circle[:center_y, :center_x],
        "alto à direita": circle[:center_y, center_x:],
        "baixo à esquerda": circle[center_y:, :center_x],
        "baixo à direita": circle[center_y:, center_x:],
    }
    for name, quadrant in quadrants.items():
        assert quadrant.any(), f"o círculo não passa {name} da palavra"
    assert not circle[
        word_top + 2 : word_bottom - 2, word_left + 6 : word_right - 6
    ].any()  # e o miolo não é coberto
