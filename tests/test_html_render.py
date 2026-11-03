"""Composição em HTML renderizada de verdade (DMK-26): o Chromium do Playwright e o ffmpeg reais.

O que nenhum teste com renderizador falso enxerga: o relógio virtual (temporizadores, `requestAnimationFrame`,
`Date`, animações CSS e Web Animations no instante exato, inclusive o do meio), o WebGL por software, o Lottie, a
rede fechada (e o que não sai da máquina), a transparência sem borda escura, a suavidade do movimento, o borrão e a
composição atrás da pessoa. Pulam, com o motivo, quando o Playwright ou o Chromium não estão instalados
(`pip install -e ".[html]"` e `dmaker setup --html`)."""

from __future__ import annotations

import hashlib
import io
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from dmaker.domain.spec import Project
from dmaker.media.browser import browser_problem
from dmaker.media.html_render import (
    EPOCH_MS,
    HtmlComposition,
    HtmlRenderError,
    PlaywrightHtmlRenderer,
    _CompositionPage,
    _Warnings,
)
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.html_layer import HtmlLayerBuilder

from .conftest import requires_ffmpeg

PROBLEM = browser_problem()
pytestmark = pytest.mark.skipif(PROBLEM is not None, reason=f"Chromium do Playwright indisponível: {PROBLEM}")

FPS = 30
WALL = (64, 112, 160)


# ---------- o navegador e as páginas de teste ----------


@pytest.fixture(scope="module")
def renderer() -> Iterator[PlaywrightHtmlRenderer]:
    """Um Chromium só para o módulo todo: abrir leva um segundo e cada teste abriria o seu."""
    with PlaywrightHtmlRenderer() as shared:
        yield shared


@pytest.fixture(scope="module")
def make(tmp_path_factory):
    """`make(html, **arquivos)` grava uma pasta de composição e devolve o caminho."""

    def build(html: str, **files: str | bytes) -> Path:
        folder = tmp_path_factory.mktemp("comp")
        (folder / "index.html").write_text(html, encoding="utf-8")
        for name, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            (folder / name.replace("__", "/")).write_bytes(data)
        return folder

    return build


def comp(source: Path, size=(200, 100), **fields) -> HtmlComposition:
    return HtmlComposition(source=source, size=size, **fields)


@contextmanager
def open_page(renderer: PlaywrightHtmlRenderer, composition: HtmlComposition):
    """A página aberta e parada no instante 0, com o que ela avisou até agora. `page.seek(t)` anda; `page.js(...)`
    lê o estado dela."""
    warnings: list[str] = []
    with _CompositionPage(renderer._browser, composition, _Warnings(warnings.append)) as page:
        page.js = page._page.evaluate
        yield page, warnings


def seek_through(page, last: float, step: float = 1 / FPS) -> None:
    """Anda de quadro em quadro até `last`, como o render faz."""
    for index in range(1, round(last / step) + 1):
        page.seek(index * step)


def png_to_array(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))


# ---------- o relógio virtual ----------


def test_timers_intervals_and_frame_callbacks_fire_at_the_virtual_instants_in_order(renderer, make):
    source = make("""<script>
      window.log = [];
      setTimeout(() => log.push(['t0', performance.now()]), 0);
      setTimeout(() => log.push(['t100', performance.now()]), 100);
      const id = setInterval(() => log.push(['i', performance.now()]), 50);
      setTimeout(() => clearInterval(id), 260);
      requestAnimationFrame(function f(ts) { log.push(['raf', ts]); if (ts < 190) requestAnimationFrame(f); });
    </script>""")
    with open_page(renderer, comp(source)) as (page, _):
        seek_through(page, 0.3)
        log = page.js("window.log")
    by_name = {name: [value for key, value in log if key == name] for name in ("t0", "t100", "i", "raf")}
    assert by_name["t0"] == [0] and by_name["t100"] == [100]
    assert by_name["i"] == [50, 100, 150, 200, 250]  # cada um com o relógio no seu instante, não no do quadro
    assert by_name["raf"] == pytest.approx(
        [k * 1000 / FPS for k in range(7)]
    )  # um por quadro, no instante dele
    assert [key for key, _ in log].index("t0") < [key for key, _ in log].index("t100")


def test_the_page_sees_a_virtual_performance_now_and_a_fixed_date(renderer, make):
    source = make("<p>x</p>")
    with open_page(renderer, comp(source)) as (page, _):
        seek_through(page, 1.5)
        now, date_now, iso, constructed, epoch0, is_date, as_text = page.js(
            "[performance.now(), Date.now(), new Date().toISOString(), new Date(2026, 0, 1).getFullYear(),"
            " new Date(0).getTime(), new Date() instanceof Date, typeof Date()]"
        )
    assert now == pytest.approx(1500) and date_now == EPOCH_MS + 1500
    assert iso == "2026-01-01T15:00:01.500Z" and constructed == 2026 and epoch0 == 0
    assert is_date and as_text == "string"


def test_math_random_and_the_seeded_generator_give_the_same_numbers_in_every_render(renderer, make):
    source = make("<p>x</p>")
    runs = []
    for _ in range(2):
        with open_page(renderer, comp(source)) as (page, _):
            runs.append(
                page.js("[Math.random(), Math.random(), dmaker.random(7)(), dmaker.noise3(0.3, 0.7, 1.1)]")
            )
    assert runs[0] == runs[1] and runs[0][0] != runs[0][1]


def test_css_animation_is_frozen_from_birth_and_seeking_goes_straight_to_the_middle(renderer, make):
    source = make("""<style>#a{position:absolute;width:10px;height:10px;background:red;animation:s 2s linear forwards}
      @keyframes s{from{transform:translateX(0)}to{transform:translateX(100px)}}</style><div id=a></div>""")

    def x(page) -> float:
        return page.js("new DOMMatrix(getComputedStyle(document.getElementById('a')).transform).m41")

    with open_page(renderer, comp(source)) as (page, _):
        time.sleep(0.4)  # em tempo real a animação já teria andado
        assert x(page) == 0
        page.seek(1.0)  # direto ao meio, sem passar pelos quadros de antes
        assert x(page) == pytest.approx(50)
        page.seek(9.0)
        assert x(page) == pytest.approx(100)  # `forwards`: fica no fim


def test_an_animation_the_page_creates_later_counts_from_the_frame_where_it_is_seen(renderer, make):
    source = make("""<div id=a style="width:10px;height:10px"></div><script>
      setTimeout(() => document.getElementById('a').animate(
        [{transform: 'translateX(0)'}, {transform: 'translateX(100px)'}], {duration: 1000, fill: 'forwards'}), 1000);
    </script>""")
    with open_page(renderer, comp(source)) as (page, _):
        seek_through(page, 1.5)
        assert page.js("new DOMMatrix(getComputedStyle(document.getElementById('a')).transform).m41") == (
            pytest.approx(50, abs=0.01)
        )


def test_the_page_function_is_called_with_the_instant_and_awaited(renderer, make):
    source = make(
        """<script>window.dmakerSeek = async (t) => { await new Promise(r => queueMicrotask(r)); window.seen = t; };</script>"""
    )
    with open_page(renderer, comp(source)) as (page, _):
        page.seek(1.25)
        assert page.js("window.seen") == 1.25


def test_the_first_frame_waits_for_the_promise_the_page_exposes(renderer, make):
    source = make(
        "<script>window.dmakerReady = fetch('dados.json').then(r => r.json()).then(d => { window.loaded = d; });</script>",
        **{"dados.json": '{"pronto": true}'},
    )
    with open_page(renderer, comp(source)) as (page, _):
        assert page.js("window.loaded") == {"pronto": True}


def test_gsap_is_told_not_to_smooth_the_big_jump_to_the_middle_of_the_composition(renderer, make):
    source = make(
        "<script>window.gsap = {ticker: {lagSmoothing: (...args) => { window.lag = args; }}};</script>"
    )
    with open_page(renderer, comp(source)) as (page, _):
        page.seek(2.0)
        assert page.js("window.lag") == [0]


def test_the_clock_never_runs_backwards(renderer, make):
    with open_page(renderer, comp(make("<p>x</p>"))) as (page, _):
        page.seek(2.0)
        with pytest.raises(HtmlRenderError, match="não anda para trás"):
            page.seek(1.0)


def test_the_page_gets_the_dmaker_object_the_brand_variables_and_poppins(renderer, make):
    source = make(
        """<style>#t{font:700 40px var(--dm-font);color:var(--dm-accent)}</style><span id=t>Olá</span>"""
    )
    composition = comp(
        source,
        size=(1080, 960),
        scale=0.5,
        fps=24,
        duration=4,
        data={"itens": [1, {"a": "b"}]},
        colors={"accent": "#FACC15", "bg_dark": "#0B1220"},
    )
    with open_page(renderer, composition) as (page, _):
        page.seek(1.0)
        info = page.js(
            """() => ({
              size: [dmaker.width, dmaker.height, dmaker.fps, dmaker.duration], data: dmaker.data,
              time: dmaker.time, frame: dmaker.frame, progress: dmaker.progress, accent: dmaker.brand.accent,
              css: getComputedStyle(document.documentElement).getPropertyValue('--dm-accent'),
              dark: getComputedStyle(document.documentElement).getPropertyValue('--dm-bg-dark'),
              family: dmaker.fontFamily, window: [innerWidth, innerHeight, devicePixelRatio],
              poppins: document.fonts.check('700 16px Poppins'),
              color: getComputedStyle(document.getElementById('t')).color,
            })"""
        )
    assert info["size"] == [1080, 960, 24, 4] and info["data"] == {"itens": [1, {"a": "b"}]}
    assert (info["time"], info["frame"], info["progress"]) == (1.0, 24, 0.25)
    assert info["accent"] == info["css"] == "#FACC15" and info["dark"] == "#0B1220"
    assert info["family"] == "Poppins" and info["poppins"] is True
    assert info["window"] == [1080, 960, 0.5]  # a prévia desenha a mesma página, só em menos pixels
    assert info["color"] == "rgb(250, 204, 21)"


def test_the_simplex_noise_is_smooth_bounded_seedable_and_the_same_in_every_render(renderer, make):
    with open_page(renderer, comp(make("<p>x</p>"))) as (page, _):
        samples = page.js("Array.from({length: 4000}, (_, i) => dmaker.noise3(i * 0.013, i * 0.007, 0.5))")
        flat = page.js("[dmaker.noise2(3, 4), dmaker.noise2(3, 4), dmaker.noise3(0, 0, 0)]")
        before = page.js("dmaker.noise3(1.3, 2.7, 0.5)")
        page.js("dmaker.noiseSeed(99)")
        reseeded = page.js("dmaker.noise3(1.3, 2.7, 0.5)")
    values = np.array(samples)
    assert values.min() >= -1 and values.max() <= 1 and values.max() > 0.5 and values.min() < -0.5
    assert abs(values.mean()) < 0.1
    assert np.abs(np.diff(values)).max() < 0.25  # passos curtos mudam pouco: é suave, não ruído branco
    assert flat[0] == flat[1] and flat[2] == 0
    assert reseeded != before


# ---------- WebGL, erros e arquivos ----------


def test_webgl_runs_in_software_and_keeps_the_drawing_buffer_for_the_capture(renderer, make):
    source = make("""<script>
      const gl = document.createElement('canvas').getContext('webgl2');
      const info = gl.getExtension('WEBGL_debug_renderer_info');
      console.error('GL:' + gl.getParameter(info.UNMASKED_RENDERER_WEBGL));
      window.keeps = document.createElement('canvas').getContext('webgl').getContextAttributes().preserveDrawingBuffer;
    </script>""")
    with open_page(renderer, comp(source)) as (page, warnings):
        assert page.js("window.keeps") is True
    assert any("GL:" in w and "SwiftShader" in w for w in warnings), warnings


def test_a_javascript_error_a_console_error_and_a_missing_file_become_warnings(renderer, make):
    source = make("""<img src="nao-existe.png"><script>
      setTimeout(() => { throw new Error('estourou aqui'); }, 10);
      console.error('mensagem de erro');
      console.log('conversa que não é aviso');
    </script>""")
    with open_page(renderer, comp(source)) as (page, warnings):
        seek_through(page, 0.1)
    assert any("erro de JavaScript na composição" in w and "estourou aqui" in w for w in warnings)
    assert any("console.error da composição: mensagem de erro" in w for w in warnings)
    assert any("pediu um arquivo que não existe nela: /nao-existe.png" in w for w in warnings)
    assert not any("conversa" in w or "favicon" in w for w in warnings)


@pytest.fixture
def listener():
    """Uma porta local que conta quem tentou conectar: o que a página tentar alcançar na máquina aparece aqui."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    server.settimeout(0.2)
    attempts: list[str] = []
    stop = threading.Event()

    def accept() -> None:
        while not stop.is_set():
            try:
                connection, _ = server.accept()
            except OSError:
                continue
            attempts.append("conexão")
            connection.close()

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield server.getsockname()[1], attempts
    stop.set()
    thread.join()
    server.close()


def test_a_page_that_reaches_for_the_internet_still_renders_and_nothing_leaves_the_machine(
    renderer, make, listener
):
    port, attempts = listener
    source = make(f"""<p>segue renderizando</p><script>
      fetch('http://127.0.0.1:{port}/a').catch(() => {{}});
      const image = new Image(); image.src = 'http://127.0.0.1:{port}/b.png';
      const script = document.createElement('script'); script.src = 'https://cdn.exemplo.com/lib.js';
      document.head.appendChild(script);
      try {{ new WebSocket('ws://127.0.0.1:{port}/socket'); }} catch (error) {{}}
      navigator.sendBeacon('http://127.0.0.1:{port}/beacon', 'x');
      fetch('https://api.exemplo.com/dados').catch(() => {{}});
    </script>""")
    with open_page(renderer, comp(source)) as (page, warnings):
        seek_through(page, 0.2)
        time.sleep(0.5)  # dá tempo de uma conexão escapar, se algum pedido escapasse
        frame = page.png(optimize_for_speed=False)
    assert attempts == []  # nenhuma conexão chegou nem à própria máquina
    joined = "\n".join(warnings)
    for blocked in (
        f"http://127.0.0.1:{port}/a",
        f"http://127.0.0.1:{port}/b.png",
        f"ws://127.0.0.1:{port}/socket",
        "https://cdn.exemplo.com/lib.js",
        "https://api.exemplo.com/dados",
    ):
        assert blocked in joined, blocked
    assert "bloqueado" in joined and frame.startswith(b"\x89PNG")  # e o render seguiu


def test_local_files_json_and_es_modules_load_from_the_fake_origin(renderer, make):
    source = make(
        """<script>window.dmakerReady = new Promise((resolve) => { window.pronto = resolve; });</script>
        <script type="module">
          import { valor } from './modulo.js';
          const dados = await (await fetch('dados.json')).json();
          window.resultado = [valor, dados.nome, dmaker.data.extra];
          window.pronto();
        </script>""",
        **{"modulo.js": "export const valor = 41 + 1;", "dados.json": '{"nome": "Terra"}'},
    )
    with open_page(renderer, comp(source, data={"extra": 7})) as (page, warnings):
        assert page.js("window.resultado") == [42, "Terra", 7]
    assert warnings == []


def test_three_js_and_lottie_are_served_by_the_dmaker_without_any_network(renderer, make):
    source = make("""<script type="importmap">{"imports":{"three":"/_dmaker/three.module.min.js"}}</script>
      <script src="/_dmaker/lottie.min.js"></script>
      <script>window.dmakerReady = new Promise((resolve) => { window.pronto = resolve; });</script>
      <script type="module">import * as THREE from 'three'; window.three = THREE.REVISION; window.pronto();</script>""")
    with open_page(renderer, comp(source)) as (page, warnings):
        assert page.js("[window.three, typeof lottie.loadAnimation]") == ["185", "function"]
    assert warnings == []


# ---------- Lottie ----------

LOTTIE = (
    '{"v":"5.7.0","fr":30,"ip":0,"op":60,"w":200,"h":200,"nm":"t","ddd":0,"assets":[],"layers":[{"ddd":0,"ind":1,'
    '"ty":4,"nm":"q","sr":1,"ks":{"o":{"a":0,"k":100},"r":{"a":0,"k":0},"p":{"a":1,"k":[{"t":0,"s":[20,100,0],'
    '"i":{"x":[1,1,1],"y":[1,1,1]},"o":{"x":[0,0,0],"y":[0,0,0]}},{"t":60,"s":[180,100,0]}]},"a":{"a":0,'
    '"k":[0,0,0]},"s":{"a":0,"k":[100,100,100]}},"ao":0,"shapes":[{"ty":"gr","it":[{"ty":"rc","d":1,"s":{"a":0,'
    '"k":[20,20]},"p":{"a":0,"k":[0,0]},"r":{"a":0,"k":0}},{"ty":"fl","c":{"a":0,"k":[1,0,0,1]},"o":{"a":0,'
    '"k":100},"r":1},{"ty":"tr","p":{"a":0,"k":[0,0]},"a":{"a":0,"k":[0,0]},"s":{"a":0,"k":[100,100]},"r":{"a":0,'
    '"k":0},"o":{"a":0,"k":100}}],"nm":"g"}],"ip":0,"op":60,"st":0,"bm":0}]}'
)  # um quadrado vermelho de 20 px que vai de x=20 a x=180 em 2 s (60 quadros a 30 fps), em linha reta


def lottie_page(make, loop: bool = False) -> Path:
    return make(
        """<script src="/_dmaker/lottie.min.js"></script><style>html,body{margin:0}#a{width:200px;height:200px}</style>
        <div id=a></div><script>lottie.loadAnimation({container: document.getElementById('a'), renderer: 'svg',"""
        f""" loop: {str(loop).lower()}, autoplay: true, path: 'anim.json'}});</script>""",
        **{"anim.json": LOTTIE},
    )


def red_center_x(png: bytes) -> float | None:
    alpha = png_to_array(png)[..., 3]
    _, xs = np.nonzero(alpha > 128)
    return float(xs.mean()) if len(xs) else None


def test_lottie_plays_at_the_right_time_and_asking_for_the_middle_shows_the_middle(renderer, make):
    composition = comp(lottie_page(make), size=(200, 200), duration=3)
    at = {t: red_center_x(renderer.still(composition, t, print)) for t in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5)}
    assert at[0.0] == pytest.approx(19.5, abs=1) and at[1.0] == pytest.approx(99.5, abs=1)  # o meio é o meio
    assert at[0.5] == pytest.approx(59.5, abs=1) and at[1.5] == pytest.approx(139.5, abs=1)
    assert at[2.0] == at[2.5] == pytest.approx(176.5, abs=1.5)  # sem loop, para no último quadro dele
    walked = [red_center_x(png) for png in _png_frames(renderer, composition, [k / FPS for k in range(31)])]
    assert walked[15] == pytest.approx(at[0.5], abs=0.01) and walked[30] == pytest.approx(at[1.0], abs=0.01)


def test_a_looping_lottie_wraps_around_its_own_duration(renderer, make):
    composition = comp(lottie_page(make, loop=True), size=(200, 200), duration=4)
    first = red_center_x(renderer.still(composition, 0.5, print))
    wrapped = red_center_x(renderer.still(composition, 2.5, print))  # 2,5 s = 0,5 s da segunda volta
    assert first == pytest.approx(wrapped, abs=0.5)


def _png_frames(renderer, composition, times):
    """Os quadros em PNG (o `frames` do renderizador devolve RGBA cru: aqui se codifica para medir)."""
    width, height = composition.output_size
    for raw in renderer.frames(composition, times, print):
        out = io.BytesIO()
        Image.frombytes("RGBA", (width, height), raw).save(out, format="PNG")
        yield out.getvalue()


# ---------- determinismo ----------

COUNTER_AND_CUBE = """<script type="importmap">{"imports":{"three":"/_dmaker/three.module.min.js"}}</script>
<style>html,body{margin:0}#n{position:absolute;left:60px;top:40px;font:800 200px var(--dm-font);color:#fff}
#c{position:absolute;left:240px;top:700px}</style>
<div id=n>0</div><canvas id=c width=600 height=600></canvas>
<script type="module">
import * as THREE from "three";
const renderer = new THREE.WebGLRenderer({canvas: document.getElementById("c"), alpha: true, antialias: true});
renderer.setClearColor(0x000000, 0);
const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
camera.position.z = 4;
scene.add(new THREE.AmbientLight(0xffffff, 0.6));
const light = new THREE.DirectionalLight(0xffffff, 1.2); light.position.set(2, 3, 4); scene.add(light);
const cube = new THREE.Mesh(new THREE.BoxGeometry(1.4, 1.4, 1.4), new THREE.MeshStandardMaterial({color: 0x4f8cff}));
scene.add(cube);
window.dmakerSeek = (t) => {
  cube.rotation.set(t * 0.7, t * 2, 0);
  renderer.render(scene, camera);
  document.getElementById("n").textContent = Math.round(dmaker.progress * 100);
};
window.dmakerSeek(0);
</script>"""


def frame_hashes(renderer, composition, times) -> list[str]:
    return [hashlib.md5(raw).hexdigest() for raw in renderer.frames(composition, times, print)]


def test_a_counting_number_and_a_spinning_three_object_render_identically_twice_frame_by_frame(
    renderer, make
):
    composition = comp(make(COUNTER_AND_CUBE), size=(1080, 1920), scale=0.5, duration=5.0)
    times = [k / FPS for k in range(0, 150, 7)]  # espalhados pelos 5 s
    first, second = frame_hashes(renderer, composition, times), frame_hashes(renderer, composition, times)
    assert first == second
    assert len(set(first)) == len(first)  # e nenhum quadro repete o anterior: o número e o cubo andam


def test_the_frame_asked_for_directly_equals_the_one_reached_by_walking(renderer, make):
    composition = comp(make(COUNTER_AND_CUBE), size=(1080, 1920), scale=0.5, duration=5.0)
    walked = list(renderer.frames(composition, [k / FPS for k in range(46)], print))[45]
    direct = renderer.still(composition, 45 / FPS, print)
    assert np.array_equal(np.frombuffer(walked, np.uint8).reshape(960, 540, 4), png_to_array(direct))


def test_the_preview_is_the_same_drawing_in_fewer_pixels(renderer, make):
    source = make(COUNTER_AND_CUBE)
    full = renderer.still(comp(source, size=(1080, 1920), scale=1.0), 1.0, print)
    half = renderer.still(comp(source, size=(1080, 1920), scale=0.5), 1.0, print)
    reduced = np.asarray(
        Image.open(io.BytesIO(full)).convert("RGBA").resize((540, 960), Image.Resampling.BOX)
    )
    error = np.abs(reduced.astype(int) - png_to_array(half).astype(int)).mean()
    assert png_to_array(half).shape == (960, 540, 4) and error < 2.0  # mesmo desenho, menos pixels


# ---------- no vídeo, com o ffmpeg de verdade ----------


@pytest.fixture(scope="module")
def wall(tmp_path_factory) -> Path:
    from tests.test_behind_person_render import _wall_clip

    return _wall_clip(tmp_path_factory.mktemp("parede") / "wall.mp4", 3.0)


def render_video(tmp_path: Path, wall: Path, renderer, html: str, *overlays: dict, matter=None, seconds=2.0):
    """O projeto inteiro pelo pipeline, com o Chromium e o ffmpeg de verdade e a saída sem perdas, devolvendo os
    quadros em RGB (n, 960, 540, 3): o preview do reels."""
    from tests.test_behind_person_render import LosslessRunner, _frames

    folder = tmp_path / "comp"
    folder.mkdir()
    (folder / "index.html").write_text(html, encoding="utf-8")
    spec = {
        "name": "video-html",
        "output": {"preset": "instagram/reels", "fps": FPS, "quality": "draft"},
        "timeline": [{"type": "clip", "src": str(wall), "start": 0, "end": seconds}],
        "overlays": [{"type": "html", "src": "comp", **o} for o in overlays],
        "audio": {"normalize": "off"},
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    out = tmp_path / "out.mkv"
    kwargs = {"matter": matter} if matter is not None else {}
    RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=out, thumbnail=False),
        runner=LosslessRunner(),
        html_layers=HtmlLayerBuilder(renderer),
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
        **kwargs,
    ).run()
    return _frames(out)


@requires_ffmpeg
def test_the_video_shows_through_where_the_page_is_transparent_with_no_dark_edge(tmp_path, wall, renderer):
    html = """<style>html,body{margin:0}
      #a{position:absolute;left:0;top:0;width:1080px;height:300px;
         background:linear-gradient(to right, rgba(255,0,0,0), rgba(255,0,0,1))}
      #b{position:absolute;left:100px;top:400px;width:300px;height:300px;background:#fff;opacity:.5}
      #c{position:absolute;left:600px;top:400px;width:300px;height:300px;border-radius:150px;background:#fff;
         box-shadow:0 0 60px 20px rgba(255,255,255,.8)}
      #d{position:absolute;left:100px;top:900px;width:400px;height:400px;border-radius:200px;background:#000;
         box-shadow:0 0 60px 30px rgba(0,0,0,.8)}</style><div id=a></div><div id=b></div><div id=c></div><div id=d></div>"""
    frames = render_video(tmp_path, wall, renderer, html, {"start": 0, "end": 1.5})
    frame = frames[10].astype(int)
    wall_color = np.array(WALL)

    # onde a página é transparente, o vídeo aparece (a conta é a do alfa direto: parede + (cor - parede) x alfa)
    assert np.abs(frame[900:950, 20:60] - wall_color).max() <= 2
    column = frame[20:130, :, :].mean(axis=0)  # faixa do degradê vermelho, coluna a coluna
    alpha = (np.arange(540) + 0.5) / 540
    expected = wall_color + (np.array([255, 0, 0]) - wall_color) * alpha[:, None]
    assert np.abs(column[10:530] - expected[10:530]).max() <= 5
    # um bloco branco a 50%: a mistura exata
    assert np.abs(frame[260:340, 70:130] - (wall_color * 0.5 + 255 * 0.5)).max() <= 3

    # a sombra branca e suave: nenhum pixel mais escuro que a parede em nenhum canal (borda escura seria isso)
    glow = frame[170:370, 260:480]
    assert glow.min(axis=(0, 1)).tolist() >= (wall_color - 2).tolist()
    assert glow.max() > 240  # e o centro do círculo branco aparece
    # e a sombra preta e suave escurece de forma contínua, sem anel claro nem degrau no meio do caminho
    shade = frame[470:700, 20:300].mean(axis=2)[115, :]  # uma linha que cruza o círculo preto
    wall_luma = float(wall_color.mean())
    assert shade.max() <= wall_luma + 2 and shade.min() < 20
    assert (np.diff(shade[: int(np.argmin(shade))]) <= 2).all()  # do lado de fora para dentro, só desce


@requires_ffmpeg
def test_an_object_at_constant_speed_moves_the_same_distance_every_frame(tmp_path, wall, renderer):
    html = """<style>html,body{margin:0}#q{position:absolute;left:0;top:200px;width:100px;height:100px;
      background:#fff;animation:go 2s linear forwards}@keyframes go{from{transform:translateX(0)}
      to{transform:translateX(980px)}}</style><div id=q></div>"""
    frames = render_video(tmp_path, wall, renderer, html, {"start": 0, "end": 2.0}, seconds=3.0)
    # quanto de cada coluna o quadrado branco cobre (o vermelho vai de 64, da parede, a 255): precisão de subpixel
    coverage = np.clip((frames[:, 100:150, :, 0].astype(float) - 64) / 191, 0, 1).mean(axis=1)
    on = coverage[:60]
    centers = (on * np.arange(540)).sum(axis=1) / on.sum(axis=1)
    assert len(frames) == 90 and (on.sum(axis=1) > 20).all()  # o quadrado está em todos os 60 quadros
    steps = np.diff(centers)
    per_frame = 980 * 0.5 / 60  # 980 px da página são 490 px de saída, em 60 quadros
    assert per_frame == pytest.approx(8.1667, abs=1e-3)
    assert steps.min() > 7.8 and steps.max() < 8.55, (steps.min(), steps.max())  # nada repetido nem pulado
    line = np.polyfit(np.arange(60), centers, 1)
    assert line[0] == pytest.approx(per_frame, abs=0.05)
    assert np.abs(centers - np.polyval(line, np.arange(60))).max() < 0.3  # em linha reta, sem tremor
    assert centers[0] == pytest.approx(25, abs=0.5)  # entra no quadro 0 e
    assert coverage[60:].max() < 0.02  # some no quadro 60: o mesmo que o intervalo pedido (0 a 2 s)


@requires_ffmpeg
def test_motion_blur_smears_a_fast_object_along_its_path_and_a_sharp_one_stays_sharp(
    tmp_path, wall, renderer
):
    html = """<style>html,body{margin:0}#q{position:absolute;left:0;top:300px;width:100px;height:100px;
      background:#fff;animation:go .3s linear forwards}@keyframes go{from{transform:translateX(0)}
      to{transform:translateX(980px)}}</style><div id=q></div>"""

    def measure(frame: np.ndarray) -> tuple[int, int, int]:
        """Largura e altura do que cobre pixels e quantas colunas ficam só em parte cobertas."""
        coverage = np.clip(
            (frame[140:210, :, 0].astype(float) - 64) / 191, 0, 1
        )  # a faixa por onde ele passa
        columns = coverage.max(axis=0)
        wide = int((columns > 0.08).sum())
        partial = int(((columns > 0.15) & (columns < 0.85)).sum())
        rows = int((coverage.max(axis=1) > 0.08).sum())
        return wide, partial, rows

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    sharp = render_video(tmp_path / "a", wall, renderer, html, {"start": 0, "end": 1.0})
    blurred = render_video(
        tmp_path / "b",
        wall,
        renderer,
        html,
        {"start": 0, "end": 1.0, "motion_blur": {"subframes": 8, "shutter": 1.0}},
    )
    sharp_width, sharp_partial, sharp_rows = measure(
        sharp[4]
    )  # o quadro 4 está no meio do movimento (0,3 s = 9 quadros)
    blur_width, blur_partial, blur_rows = measure(blurred[4])
    assert sharp_width <= 52 and sharp_partial <= 3  # 50 px de quadrado e uma coluna de borda
    assert (
        blur_width >= sharp_width + 40 and blur_partial >= 25
    )  # o rastro de quase um quadro de movimento (54 px)
    assert abs(blur_rows - sharp_rows) <= 1  # borra na direção do movimento, não para os lados


@requires_ffmpeg
def test_a_composition_behind_the_person_goes_under_the_person_and_over_the_video(tmp_path, wall, renderer):
    from tests.test_behind_person_render import DrawingMatter, _rgba

    html = """<style>html,body{margin:0}#g{position:absolute;left:0;top:0;width:540px;height:1920px;background:#00C800}
      </style><div id=g></div>"""  # o lado esquerdo do quadro (540 de 1080 px) é verde

    def person(index: int, width: int, height: int) -> np.ndarray:
        alpha = np.zeros((height, width))
        alpha[400:560, 200:340] = 1.0  # um quadrado de pessoa que cruza a divisa entre o verde e a parede
        return _rgba((220, 40, 40), alpha)

    matter = DrawingMatter(person)
    frames = render_video(
        tmp_path, wall, renderer, html, {"start": 0.5, "end": 1.5, "layer": "behind-person"}, matter=matter
    )
    frame = frames[20].astype(int)
    near = lambda pixel, color: np.abs(pixel - np.array(color)).max() <= 4  # noqa: E731
    assert near(frame[480, 230], (220, 40, 40)) and near(
        frame[480, 310], (220, 40, 40)
    )  # a pessoa por cima de tudo
    assert near(frame[300, 100], (0, 200, 0)) and near(
        frame[800, 200], (0, 200, 0)
    )  # a composição sobre o vídeo
    assert near(frame[300, 400], WALL) and near(frame[480, 450], WALL)  # fora da composição, o vídeo
    assert near(frames[5][300, 100], WALL) and near(
        frames[50][300, 100], WALL
    )  # fora do intervalo, só o vídeo
    # os limites caem exatamente nos quadros: 0,5 s é o quadro 15 e 1,5 s é o primeiro depois do último (45)
    assert near(frames[14][300, 100], WALL) and near(frames[15][300, 100], (0, 200, 0))
    assert near(frames[44][300, 100], (0, 200, 0)) and near(frames[45][300, 100], WALL)
    assert len(matter.requests) == 1  # e o recorte só foi pedido para esse intervalo


# ---------- os exemplos do guia rodam de verdade ----------


def guide_pages() -> list[str]:
    """As páginas completas (`<!doctype html>`) que o guia mostra na seção da composição em HTML."""
    from dmaker import config

    guide = (config.PACKAGE_DIR / "resources" / "guide.md").read_text(encoding="utf-8")
    start = guide.index("### Composição animada em HTML")
    section = guide[start : guide.index("\n## ", start)]
    blocks = [block.split("```", 1)[0] for block in section.split("```html\n")[1:]]
    return [block for block in blocks if block.lstrip().startswith("<!doctype html>")]


@pytest.mark.parametrize("index", [0, 1], ids=["numero-em-css", "objeto-three"])
def test_the_two_examples_of_the_guide_render_without_warnings_over_a_transparent_background(
    renderer, make, index
):
    pages = guide_pages()
    assert len(pages) == 2
    warnings: list[str] = []
    composition = comp(make(pages[index]), size=(1080, 960), scale=0.5, duration=5.0)
    png = renderer.still(composition, 2.0, warnings.append)
    frame = png_to_array(png)
    assert warnings == []
    assert frame[0, 0, 3] == 0 and frame[..., 3].max() == 255  # o fundo é transparente e o desenho existe
    assert (frame[..., 3] > 0).sum() > 2000
    later = png_to_array(renderer.still(composition, 3.5, warnings.append))
    assert not np.array_equal(frame, later)  # e ele anda
