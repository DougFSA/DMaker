"""Comandos que produzem a camada da pessoa: a janela da linha do tempo sem perdas, que o recortador lê, e o
vídeo com alfa que ele escreve. Quem junta a pessoa ao vídeo final é `behind_person.py`."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from pathlib import Path

from ..domain.timeline import TimelineWindow
from ..media.ffmpeg import FFmpegCommand
from .common import Inputs
from .timeline import timeline_graph

# FFV1 é sem perdas: o recortador vê exatamente os pixels que a montagem final terá (um H.264 aqui faria a pessoa
# do recorte diferir do vídeo, e a borda apareceria em dobro). `level 3` divide o quadro em fatias que codificam em
# paralelo, o que deixa a escrita mais rápida que o recorte, que é o gargalo. O formato é o da linha do tempo.
WINDOW_VIDEO = ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "yuv420p"]
# PNG dentro do .mov: RGBA de 8 bits sem perdas e sem conversão para YUV na escrita (a conversão fica para o
# `overlay`, como nas imagens com transparência). A pessoa ocupa uma parte do quadro e o resto tem uma cor só,
# que o deflate do PNG quase não paga; num teste de 30 quadros de 1080x1920 (pessoa sintética) o PNG ficou com 3,3 MB,
# o ProRes 4444 com 19,8 MB e o QuickTime Animation com 92,8 MB.
PERSON_VIDEO = ["-c:v", "png", "-pix_fmt", "rgba"]


def floor_seconds(value: float) -> float:
    """Arredonda para baixo na casa do microssegundo. O `-ss` pula o que vem antes do instante dado, e o `.3f`
    de um tempo como 1,0666667 viraria 1,067, que está depois do quadro e o pularia junto."""
    return math.floor(value * 1_000_000) / 1_000_000


def window_command(
    mezzanines: Sequence[Path],
    window: TimelineWindow,
    fps: float,
    size: tuple[int, int],
    out: Path,
    label: str = "janela da pessoa",
) -> FFmpegCommand:
    """Renderiza só a janela da linha do tempo, sem textos, imagens nem áudio, a partir dos mezaninos dela.

    O grafo é o da montagem final (`timeline_graph`) sobre os trechos da janela, com `lead_in` igual ao início do
    primeiro trecho no tempo final, para as transições durarem o mesmo que no render completo. O primeiro
    mezanino é aberto com `-ss` (não decodifica a gravação inteira até o intervalo) e a saída para no último
    quadro da janela com `-frames:v`."""
    inputs = Inputs()
    for index, path in enumerate(mezzanines):
        pre = ["-ss", f"{floor_seconds(window.seek):.6f}"] if index == 0 and window.seek > 0 else []
        inputs.add(path, *pre)
    graph = timeline_graph(
        len(mezzanines),
        list(window.durations),
        list(window.transitions),
        fps,
        want_video=True,
        size=size,
        lead_in=window.origin,
        want_audio=False,
    )
    lines = [*graph.lines, f"{graph.video}setpts=PTS-STARTPTS[vwin]"]
    args = [*inputs.args, "-filter_complex", ";".join(lines), "-map", "[vwin]", "-an", *WINDOW_VIDEO]
    args += ["-r", f"{fps:g}", "-fps_mode", "cfr", "-frames:v", str(window.rendered_frames), str(out)]
    return FFmpegCommand(args, label=label, total=window.rendered_frames / fps)


def person_layer_command(
    frames: Iterable[bytes],
    width: int,
    height: int,
    fps: float,
    frame_count: int,
    out: Path,
    label: str = "camada da pessoa",
) -> FFmpegCommand:
    """Escreve os quadros RGBA do recortador (pelo stdin) como vídeo com alfa."""
    inputs = Inputs()
    inputs.add("pipe:0", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{width}x{height}", "-r", f"{fps:g}")
    args = [*inputs.args, "-an", *PERSON_VIDEO, "-r", f"{fps:g}", "-fps_mode", "cfr", str(out)]
    return FFmpegCommand(args, label=label, total=frame_count / fps, frames=frames)
