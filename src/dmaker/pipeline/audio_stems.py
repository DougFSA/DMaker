"""As trilhas da mixagem como sinais leves, para medir: voz, música e som dos clipes, cada uma como sai do `audio_graph`.

Usa os mesmos pontos de cópia (`StemTaps`) da exportação por trilha, então cada trilha é a que entra na mixagem, e a
música já vem abaixada pelo ducking que sofre sob a voz: é o que a pessoa ouve, e não o arquivo da música sozinho. Para
medir basta uma taxa baixa e um canal só (a razão entre dois níveis não depende do resto), o que deixa a conferência de
um vídeo de minutos leve.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from ..filtergraph.audio import StemTaps
from ..media.ffmpeg import FFmpegCommand
from ..media.wavio import read_wav_float
from .assembly import graph_args
from .audio_render import AudioRenderPipeline, PreparedAudio

ANALYSIS_RATE = 16000  # basta para medir nível e achar fala; mais que isso só pesa na memória
SPEECH_STEMS = ("NAR", "VO")


def render_stem_levels(
    pipeline: AudioRenderPipeline, job: PreparedAudio, tracks: tuple[str, ...]
) -> dict[str, np.ndarray]:
    """Cada trilha pedida como amostras mono em `ANALYSIS_RATE` Hz, todas do tamanho do projeto. As trilhas que o
    projeto não tem (sem narração, sem música) ficam de fora do resultado."""
    taps = StemTaps(frozenset(tracks))
    inputs, lines, aout = pipeline.mix_graph(job, plan=None, stems=taps)
    lines.append(
        f"{aout}anullsink"
    )  # a mixagem em si não é gravada aqui; sem consumir a saída o ffmpeg recusa
    with tempfile.TemporaryDirectory(prefix="dmaker-trilhas-") as folder:
        args: list[str] = []
        paths: dict[str, Path] = {}
        for track in tracks:
            label = taps.labels.get(track)
            if label is None:
                continue
            chain = f"apad=whole_dur={job.total:.6f},aresample={ANALYSIS_RATE},aformat=sample_fmts=flt:channel_layouts=mono"
            lines.append(f"{label}{chain}[stem_level_{track}]")
            paths[track] = Path(folder) / f"{track}.wav"
            # `-t` fecha cada arquivo no fim do projeto: a cópia da música abaixada vem de um ramo que o `apad` do ducking
            # deixa sem fim, e sem o corte o ffmpeg gravaria silêncio para sempre
            args += [
                "-map",
                f"[stem_level_{track}]",
                "-c:a",
                "pcm_f32le",
                "-t",
                f"{job.total:.6f}",
                str(paths[track]),
            ]
        if not paths:
            return {}
        command = [*graph_args(job.ctx, inputs, lines, "audio_stem_levels.txt"), *args]
        job.ctx.runner.run(
            FFmpegCommand(command, label="trilhas para conferir", total=job.total, cwd=job.ctx.job_dir)
        )
        # num ensaio (RecordingRunner) o ffmpeg não gravou nada: sem arquivo não há o que medir
        return {track: read_wav_float(path)[0][:, 0] for track, path in paths.items() if path.exists()}
