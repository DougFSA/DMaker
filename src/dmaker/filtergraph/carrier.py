"""O grafo que renderiza, inteira e no tempo do projeto, uma trilha feita de pedaços de arquivos (a câmera dos clipes `A1` e as
faixas externas `A2`, `A3`...), para o Vocoder ouvir como portadora. Função pura: recebe os pedaços e devolve as entradas e as
linhas do grafo; quem executa é o `FFmpegRunner`.

Cada pedaço vira um `-i` com `-ss` e `-t` (é como o `audio_only_graph` lê os mezaninos): o ffmpeg só decodifica o trecho que o
clipe usa. O som passa pela velocidade do clipe por `atempo` (o mesmo filtro do mezanino, então o tom e o ritmo batem com o que
se ouve), vai para o lugar dele na linha do tempo por `adelay` e os pedaços se somam por `amix` sem normalizar.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .audio_effects import SAMPLE_RATE
from .common import Inputs, atempo_chain


@dataclass(frozen=True)
class CarrierPiece:
    """Um pedaço de arquivo na trilha: a faixa `stream` de `path`, ouvida a partir de `file_in` por `length` segundos da linha do
    tempo (que consomem `length * speed` segundos do arquivo), a partir de `at`. `lead` é o silêncio, em segundos de arquivo, que
    antecede o som dentro do pedaço (o som deslocado para antes do arquivo)."""

    path: Path
    stream: int
    volume: float
    file_in: float
    at: float
    length: float
    speed: float = 1.0
    lead: float = 0.0


def piece_line(index: int, piece: CarrierPiece, label: str) -> str:
    """A linha de grafo de um pedaço já lido pela entrada `index`: estéreo na taxa da mistura, volume, silêncio inicial,
    velocidade do clipe e posição na linha do tempo, terminando em `label`."""
    chain = [
        f"[{index}:a:{piece.stream}]aresample={SAMPLE_RATE}",
        "aformat=sample_fmts=fltp:channel_layouts=stereo",
        f"volume={piece.volume:.6f}",
    ]
    if piece.lead > 0:
        chain.append(f"adelay={round(piece.lead * SAMPLE_RATE)}S:all=1")
    if abs(piece.speed - 1.0) > 1e-9:
        chain.append(atempo_chain(piece.speed))
    if piece.at > 0:
        chain.append(f"adelay={round(piece.at * SAMPLE_RATE)}S:all=1")
    return ",".join(chain) + label


def stretch_filter(speed: float) -> str:
    """O filtro que leva um trecho da trilha, que soa depois da velocidade `speed` do clipe, de volta ao tempo do item (que o
    Vocoder lê antes da velocidade): dura `speed` vezes mais e mantém o tom, para a voz cantar na mesma nota depois que o clipe
    acelerar. É o `rubberband` com `transients=crisp:window=short`, e não o `atempo`: o `atempo` borra o ataque de uma nota em até
    20 ms (medido numa rajada a 1,5x), o que o Vocoder, que iguala a energia da portadora, amplifica; assim o erro fica em 7,5 ms."""
    return (
        f"rubberband=tempo={1.0 / speed:.9f}:pitchq=quality:transients=crisp:channels=together:window=short"
    )


def carrier_graph(pieces: list[CarrierPiece], total: float) -> tuple[Inputs, list[str], str]:
    """As entradas, as linhas do grafo e o rótulo da saída da trilha de `total` segundos, no tempo do projeto. Sem pedaços
    a trilha é um silêncio."""
    inputs = Inputs()
    lines: list[str] = []
    labels: list[str] = []
    for position, piece in enumerate(pieces):
        consumed = max(piece.length * piece.speed - piece.lead, 0.001)
        index = inputs.add(piece.path, "-ss", f"{max(piece.file_in, 0):.6f}", "-t", f"{consumed:.6f}")
        label = f"[cr{position}]"
        lines.append(piece_line(index, piece, label))
        labels.append(label)
    if not labels:
        index = inputs.add_silence(total)
        lines.append(f"[{index}:a]aformat=sample_fmts=fltp:channel_layouts=stereo[cr_mix]")
    elif len(labels) == 1:
        lines.append(f"{labels[0]}anull[cr_mix]")
    else:
        lines.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest[cr_mix]")
    lines.append(f"[cr_mix]apad=whole_dur={total:.6f},atrim=end={total:.6f},asetpts=PTS-STARTPTS[cr_out]")
    return inputs, lines, "[cr_out]"
