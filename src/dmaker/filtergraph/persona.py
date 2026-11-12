"""Comandos da persona: o trecho de tela cheia (fundo + persona + fala) e o quadro com fundo da persona sobreposta.

Funções puras: recebem caminhos e medidas e devolvem o comando; só o runner executa. O clipe da persona (vídeo com
alfa, ou opaco) vem pronto do motor; aqui ele é composto sobre o fundo e junto da fala, no formato do mezanino.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..domain.spec import ColorAdjust
from ..media.ffmpeg import FFmpegCommand
from .common import AUDIO_FMT_MEZZ, Inputs
from .encode import mezzanine_output_args
from .finish import post_video_lines
from .person_layer import PERSON_VIDEO


@dataclass(frozen=True)
class Backdrop:
    """O fundo atrás da persona: uma cor lisa (`#RRGGBB`), uma imagem ou um clipe (repetido se for mais curto)."""

    kind: str  # "color" | "image" | "clip"
    value: str  # a cor, ou o caminho do arquivo
    start: float = 0.0  # ponto de entrada no clipe

    @staticmethod
    def color(hex_color: str) -> Backdrop:
        return Backdrop("color", hex_color)


def _cover(size: tuple[int, int], fps: float) -> str:
    """Enche o quadro cortando o excesso, sem distorcer: o fundo nunca mostra faixas pretas."""
    width, height = size
    return f"fps={fps:g},scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"


def _fit_clip(size: tuple[int, int]) -> str:
    """Leva o clipe ao tamanho do quadro: o motor o guarda no tamanho em que desenhou (às vezes menor, para o cache
    ocupar pouco) e a ampliação acontece só aqui. No tamanho certo o filtro não muda nada."""
    return f"scale={size[0]}:{size[1]}:flags=lanczos"


def _backdrop_input(
    inputs: Inputs, backdrop: Backdrop, size: tuple[int, int], fps: float, duration: float
) -> str:
    """Põe o fundo nas entradas e devolve o rótulo do vídeo dele, já no tamanho e no ritmo do quadro."""
    width, height = size
    if backdrop.kind == "color":
        index = inputs.add(
            f"color=c=0x{backdrop.value.lstrip('#')}:s={width}x{height}:r={fps:g}",
            "-f",
            "lavfi",
            "-t",
            f"{duration:.3f}",
        )
        return f"[{index}:v]setsar=1"
    if backdrop.kind == "image":
        index = inputs.add_looped_image(Path(backdrop.value), fps, duration)
        return f"[{index}:v]{_cover(size, fps)}"
    index = inputs.add(
        backdrop.value, "-stream_loop", "-1", "-ss", f"{max(backdrop.start, 0):.3f}", "-t", f"{duration:.3f}"
    )
    return f"[{index}:v]setpts=PTS-STARTPTS,{_cover(size, fps)}"


def persona_mezzanine(
    clip: Path,
    speech: Path | None,
    backdrop: Backdrop | None,
    duration: float,
    size: tuple[int, int],
    fps: float,
    out: Path,
    *,
    color: ColorAdjust,
    look: ColorAdjust | None = None,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    label: str = "trecho",
    still: bool = False,
) -> FFmpegCommand:
    """O mezanino do trecho da persona: o clipe dela sobre o `backdrop`, com a fala como áudio.

    `backdrop` None é o clipe opaco (o motor já desenhou o fundo): ele só entra no quadro. Sem `speech` (fala só de
    texto que o dry-run não sintetizou) o áudio é silêncio. O áudio completa com silêncio o que a fala não cobre."""
    inputs = Inputs()
    lines: list[str] = []
    # `still`: o clipe é uma imagem só (o quadro de um instante), repetida pela duração do trecho
    clip_index = inputs.add_looped_image(clip, fps, duration) if still else inputs.add(clip)
    if backdrop is None:
        lines.append(f"[{clip_index}:v]setpts=PTS-STARTPTS,{_fit_clip(size)},format=yuv420p[mz_v1]")
    else:
        lines.append(f"{_backdrop_input(inputs, backdrop, size, fps, duration)}[mz_bg]")
        lines.append(f"[{clip_index}:v]setpts=PTS-STARTPTS,{_fit_clip(size)},format=rgba[mz_persona]")
        lines.append("[mz_bg][mz_persona]overlay=x=0:y=0:eof_action=pass:format=auto[mz_v1]")
    lines += post_video_lines("[mz_v1]", "[vout]", color, look, fade_in, fade_out, duration, size, fps)
    if speech is None:
        lines.append(f"[{inputs.add_silence(duration)}:a]{AUDIO_FMT_MEZZ}[aout]")
    else:
        index = inputs.add(speech)
        lines.append(f"[{index}:a]asetpts=PTS-STARTPTS,{AUDIO_FMT_MEZZ},apad=whole_dur={duration:.3f}[aout]")
    args = inputs.args + ["-filter_complex", ";".join(lines), "-map", "[vout]", "-map", "[aout]"]
    args += mezzanine_output_args(fps, duration, str(out))
    return FFmpegCommand(args, label=label, total=duration)


def persona_frame_command(
    clip: Path,
    mask: Path,
    background_hex: str | None,
    duration: float,
    size: tuple[int, int],
    fps: float,
    out: Path,
    label: str = "quadro da persona",
) -> FFmpegCommand:
    """A persona sobreposta recortada pela máscara (retângulo, cantos redondos ou círculo) e escrita como vídeo com
    alfa, para entrar na montagem como as composições em HTML. Com `background_hex` o clipe (com alfa) vai sobre
    uma cor lisa; sem ela o clipe já é opaco (a persona realista, com a foto de fundo) e só ganha o recorte."""
    width, height = size
    inputs = Inputs()
    if background_hex is None:
        persona = inputs.add(clip)
        lines = [f"[{persona}:v]setpts=PTS-STARTPTS,{_fit_clip(size)},format=rgba[fr_flat]"]
    else:
        background = inputs.add(
            f"color=c=0x{background_hex.lstrip('#')}:s={width}x{height}:r={fps:g}",
            "-f",
            "lavfi",
            "-t",
            f"{duration:.3f}",
        )
        persona = inputs.add(clip)
        lines = [
            f"[{background}:v]format=rgba[fr_bg]",
            f"[{persona}:v]setpts=PTS-STARTPTS,{_fit_clip(size)},format=rgba[fr_persona]",
            "[fr_bg][fr_persona]overlay=x=0:y=0:eof_action=pass:format=auto[fr_flat]",
        ]
    shape = inputs.add_looped_image(mask, fps, duration)
    lines += [f"[{shape}:v]format=gray[fr_mask]", "[fr_flat][fr_mask]alphamerge[fr_out]"]
    args = [*inputs.args, "-filter_complex", ";".join(lines), "-map", "[fr_out]", "-an", *PERSON_VIDEO]
    args += ["-r", f"{fps:g}", "-fps_mode", "cfr", "-t", f"{duration:.3f}", str(out)]
    return FFmpegCommand(args, label=label, total=duration)


def realistic_clip_command(
    frames: Iterable[bytes],
    size: tuple[int, int],
    source_fps: float,
    fps: float,
    duration: float,
    out: Path,
    label: str = "persona realista",
) -> FFmpegCommand:
    """Grava os quadros RGB do ditto (pelo stdin, a `source_fps`) como o clipe opaco da persona, no ritmo do projeto.

    O clipe é opaco e longo (um quadro de 1080x1920 sem compressão pesa 6 MB), então vai em x264 com CRF 12, quase sem
    perdas e sem o peso do PNG do clipe com alfa; o mezanino o reencoda depois. A conversão de RGB para YUV declara
    BT.709, o padrão do vídeo HD, para a cor da foto não mudar. `fps` leva os 25 quadros do ditto ao ritmo do
    projeto (repete quadros, não inventa movimento) e `tpad` repete o último, para a duração nunca ficar um quadro
    abaixo do pedido."""
    inputs = Inputs()
    inputs.add(
        "pipe:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}", "-r", f"{source_fps:g}"
    )
    video_filter = (
        f"fps={fps:g},tpad=stop_mode=clone:stop=1,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"
    )
    args = [
        *inputs.args,
        "-an",
        "-vf",
        video_filter,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "12",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-color_range",
        "tv",
        "-r",
        f"{fps:g}",
        "-fps_mode",
        "cfr",
        "-t",
        f"{duration:.3f}",
        str(out),
    ]
    return FFmpegCommand(args, label=label, total=duration, frames=frames)
