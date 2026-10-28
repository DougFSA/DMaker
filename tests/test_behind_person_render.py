"""Texto atrás da pessoa renderizado de verdade com ffmpeg (DMK-28), com um recortador falso de alfa conhecido: o
que nenhum teste de string enxerga. A ordem das camadas (parede, texto, pessoa), a borda parcial sem a cor da
parede, a mão que passa na frente do texto quadro a quadro, a janela da linha do tempo igual ao vídeo final
(com corte, transição e busca dentro do trecho) e o resto do vídeo idêntico ao render sem o efeito."""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import FFmpegCommand, SubprocessRunner, ffmpeg_path, ffprobe_path
from dmaker.media.matting import PersonRequest
from dmaker.media.probe import probe
from dmaker.pipeline import RenderOptions, RenderPipeline

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg

FPS = 30
WIDTH, HEIGHT = 540, 960  # o preview do instagram/reels
WALL = (64, 112, 160)  # a parede atrás da pessoa
PERSON = (220, 40, 40)  # a cor que o recortador falso diz que a pessoa tem


# ---------- mídia, recortadores e render ----------


def _ffmpeg(*args: str) -> None:
    subprocess.run([str(ffmpeg_path()), "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def _wall_clip(path: Path, seconds: float = 4.0) -> Path:
    r, g, b = WALL
    source = f"color=c=0x{r:02x}{g:02x}{b:02x}:s=720x1280:r={FPS}:d={seconds}"
    _ffmpeg(
        "-f", "lavfi", "-i", source, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "8", "-an", str(path)
    )
    return path


def _pattern_clip(path: Path, source: str, seconds: float) -> Path:
    """Clipe com movimento e contador de quadro (testsrc2 ou testsrc): qualquer quadro fora do lugar aparece."""
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"{source}=size=720x1280:rate={FPS}:duration={seconds}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "8",
        "-an",
        str(path),
    )
    return path


class DrawingMatter:
    """Recortador falso: `draw(k, largura, altura)` devolve o quadro RGBA k do efeito (k conta a partir do primeiro
    quadro depois do aquecimento, como o de verdade entrega)."""

    def __init__(self, draw: Callable[[int, int, int], np.ndarray]) -> None:
        self.draw = draw
        self.requests: list[PersonRequest] = []

    def frames(self, request):  # pragma: no cover
        raise AssertionError("o recorte de fundo não devia ser pedido")

    def person_frames(self, request: PersonRequest):
        self.requests.append(request)
        for k in range(round(request.length * request.fps) - request.warmup_frames):
            yield self.draw(k, request.width, request.height).tobytes()


class WindowEchoMatter:
    """Recortador falso que devolve a própria janela como pessoa de alfa 1: o que passa por cima do texto é o
    quadro da linha do tempo, então o vídeo final tem que sair igual ao render sem o texto."""

    def __init__(self) -> None:
        self.requests: list[PersonRequest] = []

    def frames(self, request):  # pragma: no cover
        raise AssertionError("o recorte de fundo não devia ser pedido")

    def person_frames(self, request: PersonRequest):
        self.requests.append(request)
        raw = subprocess.run(
            [
                str(ffmpeg_path()),
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(request.src),
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            capture_output=True,
            check=True,
        ).stdout
        frames = np.frombuffer(raw, np.uint8).reshape(-1, request.height, request.width, 3)
        for index in range(request.warmup_frames, len(frames)):
            yield np.dstack(
                [frames[index], np.full((request.height, request.width), 255, np.uint8)]
            ).tobytes()


class LosslessRunner(SubprocessRunner):
    """Roda o ffmpeg de verdade, mas a montagem final sai em FFV1 (vídeo sem perdas): o que se compara é o grafo,
    sem o ruído do codificador."""

    def __init__(self) -> None:
        super().__init__(quiet=True)

    def run(self, command: FFmpegCommand) -> list[str]:
        if command.label == "montagem final":
            first_map = command.args.index("-map")
            head, maps = command.args[:first_map], command.args[first_map : first_map + 4]
            tail = ["-c:v", "ffv1", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", command.args[-1]]
            command = FFmpegCommand(
                [*head, *maps, *tail], label=command.label, total=command.total, cwd=command.cwd
            )
        return super().run(command)


def _title(layer: str = "behind-person", start: float = 1.0, end: float = 3.0, **style) -> dict:
    """Título grande numa caixa opaca (uma cor lisa em volta das letras: dá onde medir a mistura com a pessoa)."""
    box = {
        "size": 130,
        "box": True,
        "box_color": "#FFD400",
        "box_alpha": 1.0,
        "box_padding": 90,
        "color": "#101010",
    }
    return {
        "type": "text",
        "text": "CINCO CAMADAS",
        "role": "title",
        "position": "center",
        "animation": "none",
        "start": start,
        "end": end,
        "layer": layer,
        "style": {**box, **style},
    }


def _render(
    tmp_path: Path,
    name: str,
    timeline: list[dict],
    overlays: list[dict],
    matter,
    *,
    lossless: bool = True,
) -> Path:
    spec = {
        "name": name,
        "output": {"preset": "instagram/reels", "fps": FPS, "quality": "draft"},
        "timeline": timeline,
        "overlays": overlays,
        "audio": {"normalize": "off"},
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    out = tmp_path / f"{name}.{'mkv' if lossless else 'mp4'}"
    RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=out, thumbnail=False),
        runner=LosslessRunner() if lossless else SubprocessRunner(quiet=True),
        matter=matter,
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
    ).run()
    return out


def _frames(video: Path) -> np.ndarray:
    """Todos os quadros em RGB (n, altura, largura, 3)."""
    raw = subprocess.run(
        [
            str(ffmpeg_path()),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, HEIGHT, WIDTH, 3)


def _md5_per_frame(video: Path) -> list[str]:
    raw = subprocess.run(
        [
            str(ffmpeg_path()),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv420p",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    size = WIDTH * HEIGHT * 3 // 2
    return [hashlib.md5(raw[i : i + size]).hexdigest() for i in range(0, len(raw), size)]


def _rgba(color: tuple[int, int, int], alpha: np.ndarray) -> np.ndarray:
    frame = np.zeros((*alpha.shape, 4), np.uint8)
    frame[..., :3] = color
    frame[..., 3] = np.clip(alpha * 255 + 0.5, 0, 255).astype(np.uint8)
    return frame


@pytest.fixture(scope="module")
def wall(tmp_path_factory) -> Path:
    return _wall_clip(tmp_path_factory.mktemp("parede") / "wall.mp4")


def _wall_timeline(wall: Path, seconds: float = 4.0) -> list[dict]:
    return [{"type": "clip", "src": str(wall), "start": 0, "end": seconds}]


def _box_geometry(reference: np.ndarray) -> tuple[int, int, int, int, int]:
    """Da imagem do título sem a pessoa: (esquerda, topo, direita, base) da caixa e a primeira coluna de letra.
    A caixa é tudo que não é parede."""
    off_wall = np.abs(reference.astype(int) - np.array(WALL)).sum(axis=2) > 60
    ys, xs = np.nonzero(off_wall)
    left, top, right, bottom = xs.min(), ys.min(), xs.max(), ys.max()
    letters = reference[top : bottom + 1, left : right + 1].sum(axis=2) < 150  # as letras são #101010
    return int(left), int(top), int(right), int(bottom), int(left + np.nonzero(letters.any(axis=0))[0].min())


# ---------- ordem das camadas e borda sem halo ----------


def _edge_matter(left: int, glyph: int, top: int, bottom: int, halo: bool = False) -> DrawingMatter:
    """Alfa 0 à esquerda, uma rampa suave na margem da caixa (entre a borda e a primeira letra) e alfa 1 à direita.

    A cor do primeiro plano é a da pessoa em todo o quadro (como o RVM, que a prevê também onde não há pessoa). Com
    `halo`, a cor do primeiro plano na borda parcial é a do pixel do vídeo (pessoa misturada com a parede), que é o
    erro que o primeiro plano do modelo evita."""
    start, stop = left + 12, glyph - 6

    def draw(k: int, width: int, height: int) -> np.ndarray:
        x = np.arange(width, dtype=np.float32)
        ramp = np.clip((x - start) / (stop - start), 0.0, 1.0)
        alpha = np.tile(ramp, (height, 1))
        frame = _rgba(PERSON, alpha)
        if halo:
            mixed = alpha[..., None] * np.array(PERSON) + (1 - alpha[..., None]) * np.array(WALL)
            frame[..., :3] = np.clip(mixed + 0.5, 0, 255).astype(np.uint8)
        return frame

    return DrawingMatter(draw)


def _title_over_wall(tmp_path: Path, wall: Path, layer: str = "behind-person"):
    reference = _render(
        tmp_path, "referencia", _wall_timeline(wall), [_title("front")], DrawingMatter(lambda *a: None)
    )
    return _frames(reference)[60]  # o meio do intervalo


def test_the_text_sits_between_the_wall_and_the_person_and_the_soft_edge_has_no_wall_colour(
    tmp_path: Path, wall: Path
):
    still = _title_over_wall(tmp_path, wall)
    left, top, _, bottom, glyph = _box_geometry(still)
    assert glyph - left > 30  # a margem da caixa é larga o bastante para a rampa
    rows = slice(top + 8, bottom - 8)

    out = _frames(
        _render(tmp_path, "atras", _wall_timeline(wall), [_title()], _edge_matter(left, glyph, top, bottom))
    )
    assert len(out) == 120
    frame = out[60].astype(float)
    reference = still.astype(float)

    start, stop = left + 12, glyph - 6
    band = np.arange(start, stop)
    measured = frame[rows][:, band].mean(axis=0)  # a média das linhas: a rampa não varia na vertical
    untouched = slice(left + 6, left + 11)  # alfa 0, longe do contorno da caixa
    text_colour = reference[rows][:, untouched].mean(axis=(0, 1))  # o texto como é
    person_colour = frame[rows][:, glyph + 10 : glyph + 40].mean(
        axis=(0, 1)
    )  # alfa 1: a pessoa cobre até as letras
    alpha = (band - start) / (stop - start)
    expected = alpha[:, None] * person_colour + (1 - alpha[:, None]) * text_colour

    assert np.abs(person_colour - np.array(PERSON)).max() < 12  # onde o alfa é 1, o pixel é o da pessoa
    assert (
        np.abs(frame[rows][:, untouched].mean(axis=(0, 1)) - text_colour).max() < 2
    )  # onde é 0, aparece o texto
    clean = np.abs(measured - expected).max()
    assert clean < 6, f"a borda parcial se afastou da mistura texto + pessoa em {clean:.1f} níveis"

    # sensível ao erro que o teste existe para pegar: com a cor do pixel do vídeo na borda (a parede mistura) o
    # desvio é muito maior e passaria do limite
    other_cache = tmp_path / "outro"  # a camada fica em cache pelo quadro, não pelo recortador: pasta nova
    other_cache.mkdir()
    halo = _frames(
        _render(
            other_cache,
            "halo",
            _wall_timeline(wall),
            [_title()],
            _edge_matter(left, glyph, top, bottom, halo=True),
        )
    )[60].astype(float)
    halo_measured = halo[rows][:, band].mean(axis=0)
    assert np.abs(halo_measured - expected).max() > 2 * clean and np.abs(halo_measured - expected).max() > 12


def test_the_wall_is_untouched_where_there_is_no_text_and_the_person_is_on_top_of_the_text(
    tmp_path: Path, wall: Path
):
    still = _title_over_wall(tmp_path, wall)
    left, top, right, bottom, glyph = _box_geometry(still)

    def whole_box(k, width, height):
        alpha = np.zeros((height, width), np.float32)
        alpha[top : bottom + 1, left : right + 1] = 1.0  # a pessoa cobre a caixa inteira
        return _rgba(PERSON, alpha)

    out = _frames(_render(tmp_path, "cobre", _wall_timeline(wall), [_title()], DrawingMatter(whole_box)))
    frame = out[60].astype(int)
    inside = frame[top + 6 : bottom - 6, left + 6 : right - 6]
    assert np.abs(inside - np.array(PERSON)).max() < 12  # nenhuma letra aparece: a pessoa está por cima
    wall_rows = frame[: top - 6]
    assert np.abs(wall_rows - np.array(WALL)).max() < 4  # e a parede, fora da caixa, é a do vídeo


# ---------- a mão que passa na frente do texto ----------


def test_a_hand_crossing_the_title_stays_on_top_of_it_in_every_frame_of_the_interval(
    tmp_path: Path, wall: Path
):
    still = _title_over_wall(tmp_path, wall)
    left, top, right, bottom, _ = _box_geometry(still)
    reference = still.astype(int)
    step, hand_width = 8, 90  # a mão anda 8 px por quadro

    def hand_at(k: int) -> int:
        return left - 40 + k * step

    def draw(k: int, width: int, height: int) -> np.ndarray:
        alpha = np.zeros((height, width), np.float32)
        x0 = max(hand_at(k), 0)
        alpha[top - 20 : bottom + 20, x0 : max(hand_at(k) + hand_width, 0)] = 1.0
        return _rgba(PERSON, alpha)

    out = _frames(_render(tmp_path, "mao", _wall_timeline(wall), [_title()], DrawingMatter(draw)))
    ys = np.arange(top + 2, bottom - 2, 3)
    xs = np.arange(left + 2, right - 2, 3)
    guard = 6  # 4:2:0 borra o croma na quina da mão: os pontos colados nela não contam
    checked = covered_total = 0
    for k in range(60):
        frame = out[30 + k].astype(int)
        x0, x1 = hand_at(k), hand_at(k) + hand_width
        for x in xs:
            if abs(x - x0) <= guard or abs(x - x1) <= guard:
                continue
            on_top = x0 < x < x1
            expected = np.array(PERSON) if on_top else reference[ys, x]
            measured = frame[ys, x]
            assert np.abs(measured - expected).max() < 14, (
                f"quadro {k}, coluna {x}: {'mão' if on_top else 'texto'}"
            )
            checked += len(ys)
            covered_total += len(ys) if on_top else 0
    assert checked > 5000 and covered_total > 500  # a mão cobre texto de verdade durante o intervalo
    assert (
        np.abs(out[29].astype(int) - out[0].astype(int)).max() < 4
    )  # antes do intervalo não há mão nem texto
    assert np.abs(out[90].astype(int) - out[0].astype(int)).max() < 4  # nem depois


# ---------- o resto do vídeo fica igual ----------


def test_frames_outside_the_interval_are_bit_identical_to_the_render_without_the_effect(
    tmp_path: Path, wall: Path
):
    pattern = _pattern_clip(tmp_path / "padrao.mp4", "testsrc2", 5.0)
    timeline = [{"type": "clip", "src": str(pattern), "start": 0, "end": 5}]

    def edge(k, width, height):
        alpha = np.zeros((height, width), np.float32)
        alpha[:, width // 3 : 2 * width // 3] = 0.7
        return _rgba(PERSON, alpha)

    with_effect = _md5_per_frame(
        _render(tmp_path, "com", timeline, [_title(start=1.0, end=3.0)], DrawingMatter(edge))
    )
    without = _md5_per_frame(_render(tmp_path, "sem", timeline, [], DrawingMatter(edge)))
    assert len(with_effect) == len(without) == 150
    inside = range(30, 90)  # os quadros do intervalo [1 s, 3 s)
    assert all(a == b for i, (a, b) in enumerate(zip(with_effect, without, strict=True)) if i not in inside)
    assert all(
        with_effect[i] != without[i] for i in inside
    )  # e dentro dele o efeito existe, em todos os quadros


def test_an_encoded_render_keeps_the_frames_outside_the_interval_within_the_encoder_tolerance(
    tmp_path: Path,
):
    pattern = _pattern_clip(tmp_path / "padrao.mp4", "testsrc2", 5.0)
    timeline = [{"type": "clip", "src": str(pattern), "start": 0, "end": 5}]

    def edge(k, width, height):
        alpha = np.zeros((height, width), np.float32)
        alpha[:, width // 3 : 2 * width // 3] = 0.7
        return _rgba(PERSON, alpha)

    with_effect = _frames(
        _render(
            tmp_path, "cod_com", timeline, [_title(start=1.0, end=3.0)], DrawingMatter(edge), lossless=False
        )
    )
    without = _frames(_render(tmp_path, "cod_sem", timeline, [], DrawingMatter(edge), lossless=False))
    assert len(with_effect) == len(without) == 150
    outside = [i for i in range(150) if not 30 <= i < 90]
    diffs = np.array([np.abs(with_effect[i].astype(int) - without[i].astype(int)).mean() for i in outside])
    # O grafo é exato (o teste acima compara os bits); o que sobra aqui é o x264, que decide cada quadro olhando os
    # vizinhos (B-frames que apontam para dentro do intervalo, estado do VBV): o clipe de teste tem detalhe demais e
    # satura o maxrate do preset. Medido: até 0,93 nível médio (de 255) e 0,32 de mediana; o mesmo clipe com um texto
    # comum NA FRENTE (sem recorte nenhum, o caminho de sempre) já desvia até 0,54. A mesma codificação do mesmo
    # projeto sai bit a bit igual, então o desvio vem do conteúdo diferente do intervalo, não de acaso.
    assert diffs.max() < 1.5, f"maior desvio médio fora do intervalo: {diffs.max():.4f} níveis"
    inside = np.array(
        [np.abs(with_effect[i].astype(int) - without[i].astype(int)).mean() for i in range(30, 90)]
    )
    assert inside.min() > 5 * diffs.max()  # e dentro dele o efeito aparece muito acima desse ruído


# ---------- a janela é o vídeo final, quadro a quadro ----------


def _scenarios(tmp_path: Path) -> dict[str, tuple[list[dict], tuple[float, float]]]:
    a = _pattern_clip(tmp_path / "a.mp4", "testsrc2", 6.0)
    b = _pattern_clip(tmp_path / "b.mp4", "testsrc", 6.0)
    clip_a = {"type": "clip", "src": str(a), "start": 0, "end": 6}
    return {
        "dentro de um trecho longo (busca)": ([clip_a], (3.0, 4.5)),
        "no começo do vídeo (sem busca)": ([clip_a], (0.0, 1.5)),
        "atravessando um fade": (
            [
                {**clip_a, "end": 4},
                {
                    "type": "clip",
                    "src": str(b),
                    "start": 0,
                    "end": 4,
                    "transition": {"type": "fade", "duration": 0.5},
                },
            ],
            (3.3, 4.3),
        ),
        "atravessando um corte": (
            [{**clip_a, "end": 4}, {"type": "clip", "src": str(b), "start": 1, "end": 5}],
            (3.5, 4.5),
        ),
        "atravessando uma transição de movimento": (
            [
                {**clip_a, "end": 4},
                {
                    "type": "clip",
                    "src": str(b),
                    "start": 0,
                    "end": 4,
                    "transition": {"type": "whippan", "duration": 0.5},
                },
            ],
            (3.4, 4.2),
        ),
        "depois de um cartão": (
            [
                {
                    "type": "card",
                    "flat": True,
                    "background": "#203040",
                    "logo": False,
                    "motion": "none",
                    "duration": 2.0,
                },
                {**clip_a, "end": 4, "transition": {"type": "fade", "duration": 0.4}},
            ],
            (1.6, 3.0),
        ),
    }


@pytest.mark.parametrize(
    "scenario",
    [
        "dentro de um trecho longo (busca)",
        "no começo do vídeo (sem busca)",
        "atravessando um fade",
        "atravessando um corte",
        "atravessando uma transição de movimento",
        "depois de um cartão",
    ],
)
def test_the_window_is_the_final_timeline_frame_by_frame(tmp_path: Path, scenario: str):
    timeline, (start, end) = _scenarios(tmp_path)[scenario]
    title = [_title(start=start, end=end)]

    echo = WindowEchoMatter()
    with_effect = _frames(_render(tmp_path, "eco", timeline, title, echo))
    without = _frames(_render(tmp_path, "base", timeline, [], echo))
    assert len(echo.requests) == 1 and len(with_effect) == len(without)

    first, stop = round(start * FPS), round(end * FPS)
    diffs = np.array(
        [np.abs(with_effect[i].astype(int) - without[i].astype(int)).mean() for i in range(first, stop)]
    )
    motion = np.array(
        [np.abs(without[i].astype(int) - without[i - 1].astype(int)).mean() for i in range(first, stop)]
    )
    # a pessoa é a própria janela: se ela estivesse um quadro fora do lugar, o desvio seria o do movimento entre dois
    # quadros (3 a 38 níveis nos cenários, medido abaixo); o que sobra (0,7 a 1,6) é o ida e volta RGB <-> YUV 4:2:0
    assert diffs.max() < 2.0, f"{scenario}: maior desvio médio {diffs.max():.2f} níveis"
    assert motion.mean() > 2.5 * diffs.mean(), (
        f"{scenario}: o movimento entre quadros ({motion.mean():.2f}) não separa um quadro fora do lugar do ruído ({diffs.mean():.2f})"
    )
    outside = [i for i in range(len(without)) if not first <= i < stop]
    assert all(np.array_equal(with_effect[i], without[i]) for i in outside)  # e fora do intervalo, nada mudou


# ---------- o RVM de verdade ----------


def test_the_real_model_cuts_a_synthetic_clip_into_a_layer_of_the_right_size_length_and_alpha(tmp_path: Path):
    """Sem afirmar a qualidade da borda (o clipe sintético não tem pessoa): o encadeamento janela -> modelo ->
    PNG com alfa -> montagem, com o tamanho, a duração e o formato do alfa certos."""
    from dmaker.media.matting import RvmMatter, model_path
    from dmaker.pipeline.person_layer import PersonLayerBuilder

    if not model_path("resnet50").exists():
        pytest.skip("modelo resnet50 do RVM não baixado (DMAKER_VOICE_SMOKE=1 usa o de cache/models)")
    pattern = _pattern_clip(tmp_path / "padrao.mp4", "testsrc2", 4.0)
    timeline = [{"type": "clip", "src": str(pattern), "start": 0, "end": 4}]
    spec = {
        "name": "rvm",
        "output": {"preset": "instagram/reels", "fps": FPS, "quality": "draft"},
        "timeline": timeline,
        "overlays": [_title(start=1.0, end=2.0)],
        "audio": {"normalize": "off"},
    }
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    out = tmp_path / "rvm.mp4"
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=out, thumbnail=False),
        runner=SubprocessRunner(quiet=True),
        matter=RvmMatter(),
        person_layers=PersonLayerBuilder(preview_model="resnet50"),  # o leve não está baixado neste teste
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
    ).run()

    assert out.exists() and abs(result.duration - 4.0) < 0.05
    layers = list((tmp_path / "mez").glob("*_person.mov"))
    assert len(layers) == 1
    info = probe(layers[0])
    assert (info.width, info.height) == (WIDTH, HEIGHT) and abs(info.duration - 1.0) < 0.05
    stream = subprocess.run(
        [
            str(ffprobe_path()),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,nb_frames",
            "-of",
            "csv=p=0",
            str(layers[0]),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert stream.startswith("png,rgba") and stream.endswith(",30")  # PNG com alfa, 30 quadros (1 s a 30 fps)
    first = _frames(out)
    assert len(first) == 120
