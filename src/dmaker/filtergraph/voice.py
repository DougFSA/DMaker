"""Grafo de montagem da narração: junta as falas com o silêncio de cada pausa."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..media.ffmpeg import FFmpegCommand
from .provenance import provenance_args

OUTPUT_SAMPLE_RATE = 48000  # mesma taxa do resto do pipeline (ver filtergraph/audio.py)
ATEMPO_MIN, ATEMPO_MAX = 0.5, 2.0  # a faixa que o filtro `atempo` aceita em cada instância

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


def atempo_filters(speed: float) -> list[str]:
    """`atempo` em quantas instâncias forem preciso: cada uma só aceita de 0,5 a 2,0 (mudar a velocidade sem o tom)."""
    filters: list[str] = []
    while speed > ATEMPO_MAX:
        filters.append(f"atempo={ATEMPO_MAX}")
        speed /= ATEMPO_MAX
    while speed < ATEMPO_MIN:
        filters.append(f"atempo={ATEMPO_MIN}")
        speed /= ATEMPO_MIN
    filters.append(f"atempo={speed:.6f}")
    return filters


@dataclass(frozen=True)
class SpeechFinish:
    """O que muda andamento ou dinâmica de UMA fala sintetizada, e por isso roda antes da marca d'água.

    A marca (AudioSeal) não sobrevive a compressor nem a `atempo`; ganho, mixagem, loudnorm e codificação
    ela aguenta. Então o acabamento broadcast e a aceleração da dublagem são aplicados fala a fala, aqui,
    e só depois a fala é marcada (invariante descrito em `voice/watermark.py`).
    """

    broadcast: bool = False  # acabamento broadcast do VoiceStudio (compressores, EQ e limitador)
    tempo: float = 1.0  # fator de andamento sem mudar o tom; 1.0 = velocidade natural

    @property
    def retimed(self) -> bool:
        return abs(self.tempo - 1.0) > 1e-4

    @property
    def is_plain(self) -> bool:
        """A fala fica como saiu do modelo: não há o que passar pelo ffmpeg."""
        return not self.broadcast and not self.retimed

    @property
    def cache_tag(self) -> str:
        """Entra na chave do cache: a mesma fala com acabamentos diferentes são arquivos diferentes."""
        if self.is_plain:
            return ""
        return f"acabamento:broadcast={int(self.broadcast)}:tempo={self.tempo:.4f}"


def speech_finish_filters(finish: SpeechFinish) -> list[str]:
    """Filtros do acabamento: primeiro o andamento e depois a dinâmica, que é o que fecha a fala."""
    filters: list[str] = []
    if finish.retimed:
        filters += atempo_filters(finish.tempo)
    if finish.broadcast:
        filters += BROADCAST_MASTER_FILTERS
    return filters


def speech_finish_command(source: Path, out: Path, finish: SpeechFinish) -> FFmpegCommand:
    """Passa a fala `source` pelo acabamento e grava `out` em WAV mono de 16 bits, na mesma taxa.

    A taxa fica a da fala (sem reamostrar) e o formato é o de 16 bits, os que o resto do núcleo de voz lê
    e grava: a marca d'água lê este arquivo logo em seguida.
    """
    chain = ",".join(speech_finish_filters(finish)) or "anull"
    args = ["-i", str(source), "-af", chain, "-ac", "1", "-c:a", "pcm_s16le", str(out)]
    return FFmpegCommand(args, label="acabamento da fala")


def narration_concat_graph(pauses: list[float], sample_rate: int = OUTPUT_SAMPLE_RATE) -> str:
    """Um ramo por fala (reamostra e, se houver pausa, acrescenta silêncio ao fim) e a concatenação.

    Sem acabamento aqui: a dinâmica da voz já foi decidida em cada fala, antes da marca d'água.
    """
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
    lines.append(f"{labels}concat=n={len(pauses)}:v=0:a=1[out]")
    return ";".join(lines)


def narration_concat_command(
    parts: list[tuple[Path, float]],
    out: Path,
    sample_rate: int = OUTPUT_SAMPLE_RATE,
    total: float | None = None,
    provenance: str = "",
) -> FFmpegCommand:
    """Concatena as falas (arquivo, pausa depois) numa narração mono; o formato sai da extensão de `out`.
    `provenance` é o texto da etiqueta de procedência gravada no arquivo (vazio = sem etiqueta).

    A montagem é seca: o acabamento broadcast é de cada fala (`SpeechFinish`), aplicado antes da marca
    d'água. O loudness final continua sendo ajustado na mixagem do projeto.
    """
    args: list[str] = []
    for path, _ in parts:
        args += ["-i", str(path)]
    graph = narration_concat_graph([pause for _, pause in parts], sample_rate)
    args += [
        "-filter_complex",
        graph,
        "-map",
        "[out]",
        *encoder_args(out),
        *provenance_args(provenance),
        str(out),
    ]
    return FFmpegCommand(args, label="narração", total=total)


def detection_audio_command(source: Path, out: Path, sample_rate: int) -> FFmpegCommand:
    """Extrai a faixa de áudio de `source` (WAV, MP3, M4A, MP4...) como WAV mono PCM 16 bits em `sample_rate`.

    É a entrada da verificação da marca d'água: o detector trabalha em mono e numa taxa só, e o
    ffmpeg decodifica qualquer contêiner que o resto do DMaker aceita.
    """
    args = ["-i", str(source), "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(out)]
    return FFmpegCommand(args, label="áudio para verificação")
