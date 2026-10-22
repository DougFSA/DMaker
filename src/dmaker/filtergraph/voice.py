"""Grafo de montagem da narração: junta as falas com o silêncio de cada pausa."""

from __future__ import annotations

from pathlib import Path

from ..media.ffmpeg import FFmpegCommand

OUTPUT_SAMPLE_RATE = 48000  # mesma taxa do resto do pipeline (ver filtergraph/audio.py)

# Codec por extensão. MP3 com -q:a 2 (~190 kb/s VBR) e AAC a 192 kb/s são transparentes para voz.
_CODEC_ARGS = {
    ".wav": ["-c:a", "pcm_s16le"],
    ".mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    ".m4a": ["-c:a", "aac", "-b:a", "192k"],
}


def encoder_args(out: Path) -> list[str]:
    try:
        return _CODEC_ARGS[out.suffix.lower()]
    except KeyError:
        raise ValueError(f"Formato de saída {out.suffix!r} não suportado; use .wav, .mp3 ou .m4a.") from None


# Acabamento "broadcast" do VoiceStudio (mastering + preset padrão), com os mesmos valores:
#  - highpass 60 Hz e compressor leve (-15 dB, 1.5:1, ataque 2 ms, soltura 100 ms) tiram o ronco e domam picos;
#  - highpass 80 Hz e compressor de rádio/podcast (-18 dB, 3:1, ataque 5 ms, soltura 80 ms) dão corpo e
#    regularidade à voz sintética;
#  - bass +1,5 dB e treble +2 dB são os ganhos de graves e agudos do EQ do preset (médios sem ganho);
#  - alimiter a -1 dBFS (0,891 linear) evita estouro; `level=disabled` impede o limiter de renormalizar o
#    volume por conta própria. O nivelamento final (-2 dBFS de pico, no VoiceStudio) fica a cargo do
#    loudnorm da mixagem do projeto.
BROADCAST_MASTER_FILTERS = (
    "highpass=f=60",
    "acompressor=threshold=-15dB:ratio=1.5:attack=2:release=100",
    "highpass=f=80",
    "acompressor=threshold=-18dB:ratio=3:attack=5:release=80",
    "bass=g=1.5",
    "treble=g=2",
    "alimiter=limit=0.891:level=disabled",
)


def narration_concat_graph(
    pauses: list[float], sample_rate: int = OUTPUT_SAMPLE_RATE, master: bool = True
) -> str:
    """Um ramo por fala (reamostra e, se houver pausa, acrescenta silêncio ao fim), a concatenação e,
    com `master`, o acabamento broadcast."""
    if not pauses:
        raise ValueError("A narração precisa de pelo menos uma fala.")
    lines: list[str] = []
    for index, pause in enumerate(pauses):
        # aresample: leva a fala (24 kHz) à taxa do pipeline antes de juntar;
        # aformat: garante mono em float planar, que o concat exige igual em todas as entradas;
        # apad=pad_dur: acrescenta `pause` segundos de silêncio depois da fala (pausa sem entrada extra).
        chain = [f"aresample={sample_rate}", "aformat=sample_fmts=fltp:channel_layouts=mono"]
        if pause > 0:
            chain.append(f"apad=pad_dur={pause:.3f}")
        lines.append(f"[{index}:a]{','.join(chain)}[p{index}]")
    labels = "".join(f"[p{index}]" for index in range(len(pauses)))
    # concat com v=0:a=1 emenda os ramos em sequência numa única faixa de áudio.
    lines.append(f"{labels}concat=n={len(pauses)}:v=0:a=1[{'joined' if master else 'out'}]")
    if master:
        lines.append(f"[joined]{','.join(BROADCAST_MASTER_FILTERS)}[out]")
    return ";".join(lines)


def narration_concat_command(
    parts: list[tuple[Path, float]],
    out: Path,
    sample_rate: int = OUTPUT_SAMPLE_RATE,
    total: float | None = None,
    master: bool = True,
) -> FFmpegCommand:
    """Concatena as falas (arquivo, pausa depois) numa narração mono; o formato sai da extensão de `out`.

    Com `master` (padrão) aplica o acabamento broadcast do VoiceStudio; sem ele, a voz sai crua do modelo.
    O loudness final continua sendo ajustado na mixagem do projeto.
    """
    args: list[str] = []
    for path, _ in parts:
        args += ["-i", str(path)]
    graph = narration_concat_graph([pause for _, pause in parts], sample_rate, master)
    args += ["-filter_complex", graph, "-map", "[out]", *encoder_args(out), str(out)]
    return FFmpegCommand(args, label="narração", total=total)
