"""Comando ffmpeg da dublagem: o fundo inteiro, cada fala dublada na sua posição e, opcionalmente, a voz original.

O grafo é uma função pura. Como um vídeo longo tem dezenas de falas (uma entrada e uma cadeia de filtros para
cada), o grafo vai para um arquivo lido com `-/filter_complex`, e a linha de comando não estoura o limite de
32 mil caracteres do Windows.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from ..media.ffmpeg import FFmpegCommand
from ..voice.dub_retime import RetimePlan, VideoPiece
from ..voice.watermark import delay_on_detector_grid
from .speech_edit import FASTSTART_CONTAINERS, VIDEO_AUDIO_ARGS
from .voice import atempo_filters, encoder_args

MIX_SAMPLE_RATE = 48000  # mesma taxa do resto do pipeline (ver filtergraph/audio.py)
FADE_OUT_SECONDS = 0.08  # o corte de uma fala que não coube cai num fade curto, sem estalo
# Limitador a -1 dBFS (0,891 linear), o mesmo da narração: fundo e fala somados podem passar de 0 dBFS, e o
# `level=disabled` impede que ele renormalize o volume sozinho.
# `latency=1` compensa os 5 ms de antecipação do limitador: sem isso a fala marcada sai deslocada da grade de
# 20 ms do detector e a marca d'água some (ver `voice/watermark.py`).
LIMITER = "alimiter=limit=0.891:level=disabled:latency=1"

# Só quando algum trecho do vídeo é esticado a imagem precisa ser recodificada (senão continua `-c:v copy`).
# x264 em CRF 18 é visualmente transparente sobre uma fonte que já passou por compressão, `medium` dá a
# qualidade do preset `high` do resto do DMaker sem o custo do `slow`, e `yuv420p` toca em qualquer aparelho.
STRETCHED_VIDEO_ARGS = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]


@dataclass(frozen=True)
class DubClip:
    """Uma fala dublada já sintetizada e onde ela entra no arquivo.

    O arquivo já vem na velocidade final: a aceleração (`atempo`) é feita fala a fala antes da marca d'água
    (`SpeechFinish`), porque a marca não sobrevive a mudar o andamento depois de gravada.
    """

    path: Path
    start: float  # segundos no arquivo
    gain_db: float = 0.0  # iguala o volume da fala ao da voz original
    max_seconds: float | None = None  # corta (com fade) o que passar disso: a fala não cabia


@dataclass(frozen=True)
class DubMix:
    command: FFmpegCommand
    graph: str  # texto do filtergraph; quem executa o grava em `graph_file` antes de rodar o comando


def stereo_48k() -> str:
    """Mesma taxa, formato e canais em todos os ramos, que o amix exige iguais (a fala mono vira estéreo)."""
    return f"aresample={MIX_SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo"


def _clip_chain(clip: DubClip) -> str:
    """Cadeia de uma fala: ajusta o volume, corta com fade se não coube e atrasa até a posição."""
    chain = [f"volume={clip.gain_db:.2f}dB"]
    if clip.max_seconds is not None:
        fade_start = max(0.0, clip.max_seconds - FADE_OUT_SECONDS)
        chain.append(f"atrim=duration={clip.max_seconds:.3f}")
        chain.append(f"afade=t=out:st={fade_start:.3f}:d={FADE_OUT_SECONDS}")
    chain.append(stereo_48k())
    # em ms, na grade de 20 ms do detector da marca d'água; all=1: todos os canais
    chain.append(f"adelay=delays={delay_on_detector_grid(clip.start)}:all=1")
    return ",".join(chain)


def _frame_rate(fps: float) -> str:
    """A taxa de quadros como fração exata (29,97 vira 30000/1001), para o `fps` não derivar do original."""
    rate = Fraction(fps).limit_denominator(1001)
    return str(rate.numerator) if rate.denominator == 1 else f"{rate.numerator}/{rate.denominator}"


def video_retime_lines(plan: RetimePlan, video_input: int, fps: float) -> list[str]:
    """Linhas do grafo que cortam o vídeo nos trechos do plano, esticam os marcados e emendam; saída `[vout]`.

    `split` reparte a imagem decodificada uma só vez entre os trechos; `trim` pega cada um (ao quadro, porque os
    cortes do plano caem na grade); `setpts=(PTS-STARTPTS)*fator` zera o relógio do trecho e o alonga sem
    mexer nos quadros; `concat` emenda na ordem. `fps` ao final repete quadros para a taxa voltar a ser
    constante, e `tpad` + `trim` fixam a duração exata (a emenda pode errar meio quadro).
    """
    if fps <= 0:
        raise ValueError("Para esticar o vídeo é preciso saber a taxa de quadros do original.")
    pieces = plan.pieces
    split = "".join(f"[vs{index}]" for index in range(len(pieces)))
    lines = [f"[{video_input}:v]split={len(pieces)}{split}"]
    for index, piece in enumerate(pieces):
        clock = "PTS-STARTPTS" if not piece.stretched else f"(PTS-STARTPTS)*{piece.factor:.6f}"
        lines.append(f"[vs{index}]trim=start={piece.start:.6f}:end={piece.end:.6f},setpts={clock}[vp{index}]")
    joined = "".join(f"[vp{index}]" for index in range(len(pieces)))
    total = plan.total_seconds
    lines.append(
        f"{joined}concat=n={len(pieces)}:v=1:a=0,fps={_frame_rate(fps)},"
        f"tpad=stop_mode=clone:stop_duration=1,trim=end={total:.6f}[vout]"
    )
    return lines


def _audio_piece_chain(piece: VideoPiece) -> str:
    """Cadeia de um trecho do áudio: corta, zera o relógio e, se esticado, alonga na mesma proporção da imagem.

    `atempo` muda a duração sem mudar o tom (a música não desafina), e `apad` + `atrim` fixam o trecho na
    duração exata da imagem, porque o `atempo` trabalha em blocos e erra por alguns milissegundos.
    """
    chain = [f"atrim=start={piece.start:.6f}:end={piece.end:.6f}", "asetpts=PTS-STARTPTS"]
    if piece.stretched:
        chain += atempo_filters(1.0 / piece.factor)
        chain += [f"apad=whole_dur={piece.output_seconds:.6f}", f"atrim=duration={piece.output_seconds:.6f}"]
    return ",".join(chain)


def audio_retime_lines(plan: RetimePlan, source: str, tag: str) -> list[str]:
    """Linhas que passam o áudio `source` pelos mesmos trechos do vídeo; a saída é `[tag]`."""
    pieces = plan.pieces
    split = "".join(f"[{tag}s{index}]" for index in range(len(pieces)))
    lines = [f"{source}asplit={len(pieces)}{split}"]
    for index, piece in enumerate(pieces):
        lines.append(f"[{tag}s{index}]{_audio_piece_chain(piece)}[{tag}p{index}]")
    joined = "".join(f"[{tag}p{index}]" for index in range(len(pieces)))
    lines.append(f"{joined}concat=n={len(pieces)}:v=0:a=1[{tag}]")
    return lines


def _active(retime: RetimePlan | None) -> RetimePlan | None:
    return retime if retime is not None and not retime.is_identity else None


def dub_clip_lines(clips: list[DubClip], first_clip_input: int) -> tuple[list[str], list[str]]:
    """Uma cadeia por fala dublada, as mesmas na mixagem do vídeo e na trilha `voz-dublada`; devolve (linhas, rótulos)."""
    lines = [
        f"[{first_clip_input + index}:a]{_clip_chain(clip)}[dub{index}]" for index, clip in enumerate(clips)
    ]
    return lines, [f"[dub{index}]" for index in range(len(clips))]


def dub_mix_graph(
    clips: list[DubClip],
    first_clip_input: int,
    background_input: int,
    duration: float,
    original_voice_input: int | None = None,
    original_voice_db: float = -18.0,
    retime: RetimePlan | None = None,
    video_input: int | None = None,
    fps: float = 0.0,
    limit_peaks: bool = True,
) -> str:
    """Grafo da mixagem. A saída é `[out]`, com a duração do arquivo (a do original, ou a esticada).

    `amix` com `normalize=0` soma sem dividir pelo número de entradas (o padrão baixaria o fundo e as falas a
    cada fala nova); `duration=first` acompanha o fundo, que é a entrada mais longa; `apad` e `atrim` fixam
    a duração no original para a imagem e o som terminarem juntos. `limit_peaks=False` omite o limitador: é a
    mixagem anterior ao acabamento, a que as trilhas separadas devem reproduzir quando somadas.

    Com `retime` (e `video_input`), o vídeo vira `[vout]` esticado nos trechos do plano e o fundo e a voz
    original atenuada passam pelos mesmos trechos, para a música acompanhar a imagem; `duration` deve ser a do
    arquivo esticado e as `clips` já vêm posicionadas na linha do tempo nova.
    """
    plan = _active(retime)
    lines: list[str] = []
    if plan is not None and video_input is not None:
        lines += video_retime_lines(plan, video_input, fps)
    background = "[background]" if plan is None else "[backgroundfull]"
    lines.append(f"[{background_input}:a]{stereo_48k()}{background}")
    labels = ["[background]"]
    if plan is not None:
        lines += audio_retime_lines(plan, background, "background")
    if original_voice_input is not None:
        original = "[original]" if plan is None else "[originalfull]"
        lines.append(f"[{original_voice_input}:a]volume={original_voice_db:.1f}dB,{stereo_48k()}{original}")
        labels.append("[original]")
        if plan is not None:
            lines += audio_retime_lines(plan, original, "original")
    clip_lines, clip_labels = dub_clip_lines(clips, first_clip_input)
    lines += clip_lines
    labels += clip_labels
    limiter = f"{LIMITER}," if limit_peaks else ""
    lines.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:normalize=0,{limiter}"
        f"apad=whole_dur={duration:.3f},atrim=duration={duration:.3f},asetpts=PTS-STARTPTS[out]"
    )
    return ";".join(lines)


def dub_mix_command(
    source: Path,
    background: Path,
    clips: list[DubClip],
    out: Path,
    graph_file: Path,
    duration: float,
    has_video: bool,
    original_voice: Path | None = None,
    original_voice_db: float = -18.0,
    retime: RetimePlan | None = None,
    fps: float = 0.0,
) -> DubMix:
    """Grava `out` com o fundo, as falas dubladas e (se pedida) a voz original atenuada; com vídeo, copia a imagem.

    Entradas: [0 = vídeo de origem, se houver], fundo, [voz original], falas. A imagem passa sem recodificar
    (rápido e sem perda); o áudio sai em AAC 192 kb/s, transparente para fala com música. Com `retime` que estica
    algum trecho (e vídeo), a imagem é recodificada nos trechos emendados e `duration` passa a ser a do plano.
    """
    plan = _active(retime) if has_video else None
    if plan is not None:
        duration = plan.total_seconds
    inputs: list[Path] = [source] if has_video else []
    background_input = len(inputs)
    inputs.append(background)
    original_input = None
    if original_voice is not None:
        original_input = len(inputs)
        inputs.append(original_voice)
    first_clip = len(inputs)
    inputs += [clip.path for clip in clips]

    graph = dub_mix_graph(
        clips,
        first_clip,
        background_input,
        duration,
        original_input,
        original_voice_db,
        retime=plan,
        video_input=0 if has_video else None,
        fps=fps,
    )
    args: list[str] = []
    for path in inputs:
        args += ["-i", str(path)]
    args += ["-/filter_complex", str(graph_file)]
    if plan is not None:
        args += ["-map", "[vout]", *STRETCHED_VIDEO_ARGS, "-map", "[out]", *VIDEO_AUDIO_ARGS]
        if out.suffix.lower() in FASTSTART_CONTAINERS:
            args += ["-movflags", "+faststart"]
    elif has_video:
        args += ["-map", "0:v:0", "-c:v", "copy", "-map", "[out]", *VIDEO_AUDIO_ARGS]
        if out.suffix.lower() in FASTSTART_CONTAINERS:
            args += [
                "-movflags",
                "+faststart",
            ]  # o índice no começo deixa o arquivo tocar antes de baixar inteiro
    else:
        args += ["-map", "[out]", *encoder_args(out)]
    return DubMix(FFmpegCommand([*args, str(out)], label="dublagem", total=duration), graph)
