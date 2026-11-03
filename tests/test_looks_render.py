"""Looks e acabamento renderizados de verdade (ffmpeg) e medidos nos quadros.

Cada teste mede o que o olho veria: o grão estável (sem bloco piscando), o render determinístico (framemd5 igual),
o tamanho do arquivo, o look do projeto que não atropela a cor própria de um trecho e cada efeito no seu lugar. As
fontes são sintéticas e estáticas (feitas para serem medidas); a variação que aparece nos números é toda do efeito.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from dmaker.domain.presets import get_preset
from dmaker.domain.spec import ClipSegment, ColorAdjust, Project
from dmaker.filtergraph.encode import encode_args
from dmaker.filtergraph.mezzanine import clip_mezzanine
from dmaker.media.ffmpeg import SubprocessRunner, ffmpeg_path
from dmaker.media.probe import probe
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.look_preview import TILE_WIDTH, LookPreview

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

W, H = 540, 960
FPS = 30
SECONDS = 3.0
# Área lisa da cena estática (só o degradê de fundo), onde o que se mede é o efeito e não o conteúdo.
FLAT = (slice(700, 940), slice(40, 500))


def _ffmpeg(*args: str) -> bytes:
    return subprocess.run(
        [str(ffmpeg_path()), "-hide_banner", "-loglevel", "error", "-nostdin", *args],
        capture_output=True,
        check=True,
    ).stdout


def _scene(path: Path, size: tuple[int, int], seconds: float) -> Path:
    """Cena estática e lisa (degradê suave com duas caixas): nada se mexe, então a variação medida é do acabamento."""
    width, height = size
    source = (
        f"gradients=size={width}x{height}:rate={FPS}:duration={seconds}:nb_colors=3:c0=0x405868:c1=0x806848"
        f":c2=0x304050:x0=0:y0=0:x1={width}:y1={height}:speed=0.0001:seed=3,"
        f"drawbox=x=iw*0.12:y=ih*0.15:w=iw*0.3:h=iw*0.3:color=0xd8a07c:t=fill,"
        f"drawbox=x=iw*0.55:y=ih*0.35:w=iw*0.3:h=iw*0.3:color=0x203040:t=fill,format=yuv420p"
    )
    _ffmpeg(
        "-y", "-f", "lavfi", "-i", source, "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p", str(path)
    )
    return path


def _mezzanine(
    src: Path,
    out: Path,
    color: ColorAdjust | None = None,
    look: ColorAdjust | None = None,
    size: tuple[int, int] = (W, H),
    seconds: float = SECONDS,
) -> Path:
    segment = ClipSegment(src=str(src), start=0, end=seconds, color=color or ColorAdjust())
    command = clip_mezzanine(segment, probe(src), src, seconds, size[0], size[1], FPS, out, look=look)
    SubprocessRunner(quiet=True).run(command)
    return out


def _gray(path: Path, size: tuple[int, int] = (W, H)) -> np.ndarray:
    data = _ffmpeg("-i", str(path), "-f", "rawvideo", "-pix_fmt", "gray", "-")
    return np.frombuffer(data, np.uint8).reshape(-1, size[1], size[0]).astype(np.float32)


def _rgb(path: Path, size: tuple[int, int] = (W, H)) -> np.ndarray:
    data = _ffmpeg("-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-")
    return np.frombuffer(data, np.uint8).reshape(-1, size[1], size[0], 3).astype(np.float32)


def _framemd5(path: Path) -> list[str]:
    out = _ffmpeg("-i", str(path), "-map", "0:v", "-f", "framemd5", "-").decode()
    return [line.split(",")[-1].strip() for line in out.splitlines() if line and not line.startswith("#")]


@pytest.fixture(scope="module")
def scene(tmp_path_factory) -> Path:
    return _scene(tmp_path_factory.mktemp("cena") / "cena.mp4", (W, H), SECONDS)


@pytest.fixture(scope="module")
def base(scene, tmp_path_factory) -> Path:
    return _mezzanine(scene, tmp_path_factory.mktemp("base") / "base.mov")


# ---------- granulação: visível, animada e estável ----------


def _residual(frames: np.ndarray, block: int = 32) -> float:
    """Desvio-padrão do que sobra depois de tirar a média local de cada bloco: a textura fina da área."""
    area = frames[(slice(None), *FLAT)]
    n, h, w = area.shape
    h, w = h // block * block, w // block * block
    tiles = area[:, :h, :w].reshape(n, h // block, block, w // block, block)
    return float((tiles - tiles.mean(axis=(2, 4), keepdims=True)).std())


def _block_flicker(frames: np.ndarray, block: int = 16) -> tuple[float, float]:
    """Oscilação, no tempo, da média de cada bloco de 16x16: (desvio-padrão da média de cada bloco ao longo do
    vídeo, pior salto entre quadros vizinhos). Grão fino e bem espalhado soma a zero dentro do bloco; um bloco que
    pisca (o x264 codificando o grão em uns blocos e em outros não) aparece aqui."""
    area = frames[(slice(None), *FLAT)]
    n, h, w = area.shape
    h, w = h // block * block, w // block * block
    means = area[:, :h, :w].reshape(n, h // block, block, w // block, block).mean(axis=(2, 4))
    return float(means.std(axis=0).mean()), float(np.abs(np.diff(means, axis=0)).max())


def test_grain_is_visible_and_stable_without_blocks_blinking(scene, base, tmp_path):
    grainy = _mezzanine(scene, tmp_path / "grao.mov", ColorAdjust(grain=0.3))
    clean_frames, grain_frames = _gray(base), _gray(grainy)

    # visível: a textura fina da área lisa passa de 1 nível (de 255); na fonte limpa ela é quase zero
    assert _residual(clean_frames) < 0.4
    assert _residual(grain_frames) > 1.0

    # animada: cada quadro tem um grão novo (a diferença entre quadros vizinhos é da ordem do próprio grão)
    step = np.abs(np.diff(grain_frames[(slice(None), *FLAT)], axis=0)).mean()
    assert step > 0.8

    # estável: a média de cada bloco de 16x16 quase não oscila, e nenhum bloco salta de um quadro para o outro
    spread, worst_jump = _block_flicker(grain_frames)
    assert spread < 0.5, f"blocos oscilando no tempo (desvio {spread:.2f})"
    assert worst_jump < 2.0, f"um bloco saltou {worst_jump:.1f} níveis entre dois quadros"
    assert _block_flicker(clean_frames)[0] < 0.05  # a fonte limpa não oscila: o que se mediu é do grão

    # sem mudar a cor: a média da cena é a mesma de antes, com folga de 1 nível de 255 (o `noise` do ffmpeg trunca os
    # valores e a média desce uns 0,05 nível por ponto de força, o que ninguém vê)
    assert abs(grain_frames[(slice(None), *FLAT)].mean() - clean_frames[(slice(None), *FLAT)].mean()) < 1.0


def test_the_same_spec_rendered_twice_gives_identical_frames_with_every_effect_on(scene, tmp_path):
    color = ColorAdjust(grain=0.3, light_leak=0.5, glow=0.3, aberration=0.3, vignette=0.4)
    first = _mezzanine(scene, tmp_path / "a.mov", color)
    second = _mezzanine(scene, tmp_path / "b.mov", color)
    hashes = _framemd5(first)
    assert len(hashes) == round(SECONDS * FPS) and hashes == _framemd5(second)
    assert len(set(hashes)) == len(
        hashes
    )  # e nenhum quadro repete outro: grão e vazamento andam a cada quadro
    assert _framemd5(first) != _framemd5(_mezzanine(scene, tmp_path / "c.mov", ColorAdjust(grain=0.4)))


def test_default_looks_are_deterministic_too(scene, tmp_path):
    from dmaker.domain.looks import DEFAULT_LOOKS

    look = DEFAULT_LOOKS["vintage"].color  # o que liga mais efeitos: grão, vazamento, aberração e vinheta
    assert _framemd5(_mezzanine(scene, tmp_path / "a.mov", look=look)) == _framemd5(
        _mezzanine(scene, tmp_path / "b.mov", look=look)
    )


# ---------- tamanho do arquivo ----------


def test_the_cinema_grain_grows_the_final_file_by_less_than_30_percent_on_detailed_footage(tmp_path):
    """Medido como a entrega: mezanino de 1080x1920 recodificado com os parâmetros do preset (CRF 18 e teto de
    bitrate do Reels), numa cena de detalhe (padrão de teste em movimento, mais de 8 Mbps). Em cena parada e limpa o
    grão custa os mesmos poucos MB em números absolutos, mas em porcentagem pesa muito mais; o guia diz isso."""
    from dmaker.domain.looks import DEFAULT_LOOKS

    size, seconds = (1080, 1920), 4.0
    src = tmp_path / "detalhe.mp4"
    _ffmpeg(
        "-y", "-f", "lavfi", "-i", f"testsrc2=size=1080x1920:rate={FPS}:duration={seconds}",
        "-c:v", "libx264", "-crf", "14", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(src),
    )  # fmt: skip
    preset = get_preset("instagram/reels")
    sizes = {}
    for name, grain in (("limpo", 0.0), ("cinema", DEFAULT_LOOKS["cinema"].color.grain)):
        mezzanine = _mezzanine(
            src, tmp_path / f"{name}.mov", ColorAdjust(grain=grain), size=size, seconds=seconds
        )
        final = tmp_path / f"{name}.mp4"
        _ffmpeg("-y", "-i", str(mezzanine), "-an", *encode_args(preset, "high", "x264", FPS), str(final))
        sizes[name] = final.stat().st_size
    growth = sizes["cinema"] / sizes["limpo"] - 1
    assert 0.0 < growth < 0.30, f"o arquivo cresceu {growth:.0%} ({sizes})"


# ---------- cada efeito no seu lugar ----------


def test_vignette_intensity_darkens_the_corners_more_as_it_grows_and_true_keeps_its_old_strength(
    scene, base, tmp_path
):
    def corner_loss(path: Path) -> float:
        frames = _gray(path)[0]
        return float(
            frames[H // 2 - 30 : H // 2 + 30, W // 2 - 30 : W // 2 + 30].mean() - frames[:60, :60].mean()
        )

    plain = corner_loss(base)
    weak = corner_loss(_mezzanine(scene, tmp_path / "fraca.mov", ColorAdjust(vignette=0.2)))
    strong = corner_loss(_mezzanine(scene, tmp_path / "forte.mov", ColorAdjust(vignette=0.8)))
    classic = corner_loss(_mezzanine(scene, tmp_path / "true.mov", ColorAdjust(vignette=True)))
    same_as_true = corner_loss(_mezzanine(scene, tmp_path / "quatro.mov", ColorAdjust(vignette=0.4)))
    assert plain < weak < classic < strong
    assert abs(classic - same_as_true) < 3  # 0.4 é o `true` (o ângulo é o mesmo; só o dither muda)


def test_glow_lifts_the_area_around_highlights_without_touching_the_chroma(tmp_path):
    lit = tmp_path / "luz.mp4"  # fundo marrom médio e uma caixa branca: a luz forte que o brilho espalha
    _ffmpeg(
        "-y", "-f", "lavfi",
        "-i", f"color=c=0x806040:s={W}x{H}:r={FPS}:d=1,drawbox=x=200:y=300:w=200:h=200:color=white:t=fill,format=yuv420p",
        "-c:v", "libx264", "-crf", "8", "-pix_fmt", "yuv420p", str(lit),
    )  # fmt: skip
    plain = _mezzanine(lit, tmp_path / "limpo.mov", seconds=1.0)
    glowing = _mezzanine(lit, tmp_path / "brilho.mov", ColorAdjust(glow=1.0), seconds=1.0)
    before, after = _gray(plain)[0], _gray(glowing)[0]
    near = (slice(350, 450), slice(404, 424))  # logo à direita da caixa
    far = (slice(700, 940), slice(20, 150))  # longe da luz, bem além do raio do halo
    assert after[near].mean() > before[near].mean() + 5  # o halo clareia a vizinhança da luz
    assert abs(after[far].mean() - before[far].mean()) < 0.3  # e longe dela não muda nada
    colors_before, colors_after = _rgb(plain)[0], _rgb(glowing)[0]
    warmth = lambda frame: frame[far][..., 0] - frame[far][..., 2]  # noqa: E731 - vermelho menos azul: o croma
    assert np.abs(warmth(colors_after) - warmth(colors_before)).mean() < 0.5  # o halo é só de luma


def test_aberration_pulls_red_and_blue_apart_horizontally_in_proportion_to_the_width(tmp_path):
    edges = (
        tmp_path / "bordas.mp4"
    )  # fundo preto e uma caixa branca de borda dura, onde cada canal se lê sem dúvida
    _ffmpeg(
        "-y", "-f", "lavfi",
        "-i", f"color=c=black:s={W}x{H}:r={FPS}:d=1,drawbox=x=200:y=300:w=200:h=300:color=white:t=fill,format=yuv420p",
        "-c:v", "libx264", "-crf", "8", "-pix_fmt", "yuv420p", str(edges),
    )  # fmt: skip

    def left_edge(path: Path) -> dict[str, int]:
        """Primeira coluna em que cada canal passa do meio, na altura do meio da caixa."""
        row = _rgb(path)[0][450]
        return {channel: int(np.nonzero(row[:, i] > 127)[0][0]) for i, channel in enumerate("rgb")}

    plain = left_edge(_mezzanine(edges, tmp_path / "limpo.mov", seconds=1.0))
    split = left_edge(_mezzanine(edges, tmp_path / "ab.mov", ColorAdjust(aberration=1.0), seconds=1.0))
    expected = round(0.005 * W)  # 0,5% da largura: 3 px a 540
    assert split["g"] == plain["g"]  # o verde fica no lugar
    assert abs(split["r"] - plain["r"]) == pytest.approx(expected, abs=1)
    assert abs(split["b"] - plain["b"]) == pytest.approx(expected, abs=1)
    assert (split["r"] - plain["r"]) * (split["b"] - plain["b"]) < 0  # um para cada lado


def test_light_leak_enters_and_leaves_with_the_light_off_and_is_warm_at_the_peak(scene, base, tmp_path):
    leaking = _mezzanine(scene, tmp_path / "vaza.mov", ColorAdjust(light_leak=1.0))
    plain, with_leak = _rgb(base), _rgb(leaking)
    n = len(plain)
    assert np.abs(with_leak[0] - plain[0]).mean() < 1.0  # o primeiro quadro está sem luz: entra sem degrau
    assert (
        np.abs(with_leak[-1] - plain[-1]).mean() < 1.5
    )  # e o último também: o corte não pega o vazamento aceso
    peak = n // 2
    warmth = lambda frames: float((frames[peak][..., 0] - frames[peak][..., 2]).mean())  # noqa: E731
    assert warmth(with_leak) > warmth(plain) + 15  # no meio da passagem a luz quente cobre o quadro
    brightness = np.array([f.mean() for f in with_leak])
    assert brightness.argmax() in range(n // 2 - 8, n // 2 + 9)  # o pico é no meio da passagem


# ---------- ponta a ponta: o look do projeto e o trecho de cor própria ----------


def _project_render(tmp_path: Path, name: str, **extra) -> tuple[Path, Project]:
    for clip, colors in (("a.mp4", ("0x2060c0", "0xc08040")), ("b.mp4", ("0x40a060", "0xe0d0a0"))):
        _ffmpeg(
            "-y", "-f", "lavfi",
            "-i", f"gradients=size=360x640:rate=30:duration=2:nb_colors=2:c0={colors[0]}:c1={colors[1]}:seed=2:speed=0.0001,format=yuv420p",
            "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(tmp_path / clip),
        )  # fmt: skip
    project = Project.model_validate(
        {
            "name": name,
            "output": {"preset": "instagram/reels"},
            "audio": {"normalize": "off"},
            "timeline": [
                {"type": "clip", "src": "a.mp4", "start": 0, "end": 2},
                {"type": "clip", "src": "b.mp4", "start": 0, "end": 2, "color": {"brightness": 0.1}},
                {"type": "clip", "src": "b.mp4", "start": 0, "end": 2},
            ],
            **extra,
        }
    )
    project.base_dir = tmp_path
    out = tmp_path / f"{name}.mp4"
    RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, no_captions=True, thumbnail=False, out=out),
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
    ).run()
    return out, project


def _segment_means(video: Path) -> list[np.ndarray]:
    """Cor média (RGB) do meio de cada um dos três trechos de 2 s."""
    info = probe(video)
    frames = _rgb(video, (info.width, info.height))
    rate = len(frames) / info.duration
    return [frames[int(rate * t)].reshape(-1, 3).mean(axis=0) for t in (1.0, 3.0, 5.0)]


def test_cinema_on_the_whole_project_changes_every_segment_but_the_one_with_its_own_color(tmp_path):
    plain_video, _ = _project_render(tmp_path, "sem")
    cinema_video, _ = _project_render(tmp_path, "com", look="cinema")
    plain, graded = _segment_means(plain_video), _segment_means(cinema_video)
    shift = [float(np.abs(a - b).max()) for a, b in zip(plain, graded, strict=True)]
    assert shift[0] > 4 and shift[2] > 4, f"o look não mudou os trechos sem cor própria: {shift}"
    assert shift[1] < 1.5, f"o trecho com cor própria foi atropelado pelo look: {shift}"
    # o look empurra para o tom do cinema: no trecho verde-claro, o azul sobe em relação ao vermelho nas sombras e o
    # laranja nas luzes; o que se vê no total é a cor média ter andado, e isso já está nas medidas acima
    assert graded[0].tolist() != plain[0].tolist()


def test_look_nenhum_renders_the_same_frames_as_a_project_with_no_look_at_all(tmp_path):
    """`nenhum` não é um look: o projeto sai com os mesmos quadros do projeto sem o campo (o filtro do mezanino sem
    look é o de sempre, o que `test_looks.py` confere texto a texto)."""
    old_video, _ = _project_render(tmp_path, "antigo")
    off_video, _ = _project_render(tmp_path, "desligado", look="nenhum")
    assert _framemd5(old_video) == _framemd5(off_video)


# ---------- a folha de contato ----------


def test_the_look_sheet_is_a_real_jpeg_with_the_scene_and_every_look_side_by_side(tmp_path):
    from PIL import Image

    from dmaker.domain.looks import DEFAULT_LOOKS

    preview = LookPreview(SubprocessRunner(quiet=True), cache_dir=tmp_path / "cache")
    overview = preview.overview()
    with Image.open(overview) as image:
        assert image.format == "JPEG" and image.width == TILE_WIDTH * (len(DEFAULT_LOOKS) + 1)
    one = preview.sheet("cinema")
    with Image.open(one) as image:
        assert image.width == TILE_WIDTH * 2  # original e o look
    assert preview.sheet("cinema") == one  # a segunda vez vem do cache
