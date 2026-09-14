"""Proxy H.264 leve para a prévia ao vivo na interface.

O Chrome não decodifica HEVC/ProRes (comuns em câmeras e celulares), então cada fonte de vídeo do
projeto ganha uma cópia em H.264/AAC que o navegador toca direto pelo `<video>`.
"""

from __future__ import annotations

from pathlib import Path

from ..media.ffmpeg import FFmpegCommand
from ..media.probe import MediaInfo

PROXY_HEIGHT = 540


def proxy_command(src: Path, out: Path, info: MediaInfo) -> FFmpegCommand:
    """Recodifica `src` para um MP4 leve só para conferência visual, nunca para entrega:
    `preset ultrafast` e `crf 26` trocam qualidade por velocidade de geração (a receita de entrega de
    verdade está em `encode.py`). `-movflags +faststart` põe o índice no começo do arquivo, para o
    navegador buscar (seek) na linha do tempo sem baixar o arquivo inteiro antes.

    Reduz para altura 540 só quando a fonte é maior (fontes menores ficam do jeito que estão); a
    largura usa `-2` para o ffmpeg escolher o valor par mais próximo, exigido pelo `yuv420p`. O fps
    da fonte é mantido. `info.width`/`info.height` já vêm na orientação final (o probe troca os dois
    quando há rotação de 90/270 graus, e o ffmpeg aplica essa rotação ao decodificar por padrão), então
    não é preciso nenhum filtro extra de rotação aqui.
    """
    args = ["-i", str(src)]
    if info.height > PROXY_HEIGHT:
        args += ["-vf", f"scale=-2:{PROXY_HEIGHT}"]
    args += [
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "26",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]
    if info.has_audio:
        args += ["-c:a", "aac", "-b:a", "96k", "-ac", "2", "-ar", "48000"]
    else:
        args += ["-an"]
    args.append(str(out))
    return FFmpegCommand(args, label=f"proxy: {src.name}", total=info.duration)
