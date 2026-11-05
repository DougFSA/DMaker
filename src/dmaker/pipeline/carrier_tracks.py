"""A portadora do Vocoder vinda de outra trilha do projeto: uma passada prévia renderiza a trilha INTEIRA, no tempo do projeto, para
um WAV em cache, e cada item lê dele só o trecho que lhe cabe.

Por que uma passada só e não uma por item: a trilha é a mesma para todos os itens que a ouvem, então todos dividem o arquivo e a
identidade dele (a chave de cache). O item sabe onde cai na linha do tempo pelo `placement` (`PlacedRun`), e `CarrierTracks.window`
monta o sinal que entra no Vocoder: silêncio onde o item não toca, o trecho da trilha onde toca.

A trilha é lida ANTES de qualquer abaixamento do Auto Duck (é a cópia que a mixagem tira de cada trilha, a mesma que o Auto Duck
mede), senão a voz abaixaria a música que é a portadora dela. As fontes (narração, voz gravada e música já processadas) entram
por funções preguiçosas (`Deferred`): a música pode ter um Vocoder cuja portadora é a narração, e a narração um cuja portadora é
a música de outro pedaço, então a ordem dos três pontos de entrada (render, prévia e render só de áudio) não decide a ordem em que
as trilhas ficam prontas. O ciclo já foi recusado na spec; a guarda daqui só levanta erro claro se um escapar.

O projeto que nenhum efeito liga a `carrier_track` não nasce com isto: não mede, não renderiza e não muda nada.
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generic, TypeVar

import numpy as np

from .. import config
from ..domain.auto_duck import external_index
from ..domain.carrier_tracks import PlacedRun
from ..domain.spec import ClipSegment, Project
from ..domain.timeline import segment_duration
from ..filtergraph.audio_effects import SAMPLE_RATE
from ..filtergraph.carrier import CarrierPiece, carrier_graph, stretch_filter
from ..media.ffmpeg import FFmpegCommand
from .auto_duck import CameraInput, camera_input, input_stamps, tap_graph
from .cache_key import cache_key
from .context import RenderContext
from .sfx import unleveled_effects
from .sources import Source
from .track_slices import clip_windows

CARRIER_VERSION = "cr1"  # muda quando a receita do WAV da trilha portadora muda (invalida os WAVs em cache)
WAV_CHANNELS = 2
FRAME_BYTES = WAV_CHANNELS * 4  # estéreo, ponto flutuante de 32 bits

T = TypeVar("T")


class Deferred(Generic[T]):
    """Uma conta que roda na primeira vez que alguém pede o resultado e guarda o valor. Pedir de novo enquanto ela ainda roda é
    um ciclo de portadoras: levanta erro em vez de entrar em laço."""

    def __init__(self, make: Callable[[], T], name: str) -> None:
        self._make = make
        self._name = name
        self._done = False
        self._running = False
        self._value: T | None = None

    def __call__(self) -> T:
        if not self._done:
            if self._running:
                raise ValueError(
                    f"Vocoder: as portadoras fecham um ciclo em {self._name}; deixe uma delas com a portadora gerada"
                )
            self._running = True
            try:
                self._value = self._make()
            finally:
                self._running = False
            self._done = True
        return self._value  # type: ignore[return-value]


@dataclass(frozen=True)
class CarrierInputs:
    """O que a passada prévia precisa saber, entregue pelo render, pela prévia e pelo render só de áudio: onde cada clipe cai na
    linha do tempo (`spans`), as fontes dos clipes, a duração do projeto, de que faixa da spec veio cada faixa física, e as
    funções que devolvem a narração, as vozes gravadas e a música já processadas."""

    spans: Sequence[tuple[float, float]]
    sources: Sequence[Source]
    total: float
    track_origin: Sequence[int] | None
    voiceovers: Callable[[], Sequence]
    voice_files: Callable[[], Sequence]
    music_path: Callable[[], Path | None]


@dataclass(frozen=True)
class CarrierTrack:
    """Uma trilha já renderizada: o WAV, a identidade dele (a chave de cache) e onde estão as amostras dentro do arquivo."""

    path: Path
    identity: str
    data_offset: int = 0
    frames: int = 0


def uses_carrier_tracks(project: Project) -> bool:
    """Se algum efeito ligado do projeto lê a portadora de outra trilha."""
    return any(
        effect.enabled and effect.carrier_track_id() is not None
        for _, _, effects in project.carrier_hosts()
        for effect in effects
    )


def install_carrier_tracks(ctx: RenderContext, inputs: CarrierInputs) -> None:
    """Põe em `ctx.carrier_tracks` a passada prévia deste render, ou None quando nenhum efeito usa `carrier_track`. Os três
    pontos de entrada chamam isto antes do primeiro `process`: o item que ouve outra trilha precisa dela na hora de ser processado."""
    ctx.carrier_tracks = CarrierTracks(ctx, inputs) if uses_carrier_tracks(ctx.project) else None


def wav_layout(path: Path) -> tuple[int, int]:
    """Onde ficam as amostras de um WAV estéreo de ponto flutuante e quantos quadros ele tem: percorre os blocos do arquivo até o
    `data`, porque o ffmpeg põe outros (`LIST`) antes dele."""
    size_on_disk = path.stat().st_size
    with path.open("rb") as handle:
        if handle.read(4) != b"RIFF":
            raise ValueError(f"{path.name} não é um WAV")
        handle.seek(12)
        while True:
            head = handle.read(8)
            if len(head) < 8:
                return 0, 0
            name, size = head[:4], struct.unpack("<I", head[4:])[0]
            if name == b"data":
                offset = handle.tell()
                # o tamanho de um WAV gravado em fluxo pode vir como 0xFFFFFFFF: vale o que há de fato no arquivo
                return offset, min(size, size_on_disk - offset) // FRAME_BYTES
            handle.seek(size + (size & 1), 1)


def _read_frames(track: CarrierTrack, first: int, count: int) -> np.ndarray:
    """`count` quadros do WAV a partir de `first`, `(count, 2)`; o que passa do fim do arquivo vira silêncio. Lê só o trecho, sem
    mapear o arquivo (um mapeamento aberto trava a troca do arquivo no Windows)."""
    out = np.zeros((count, WAV_CHANNELS), dtype=np.float32)
    first = max(first, 0)
    available = min(count, track.frames - first)
    if available > 0:
        read = np.fromfile(
            track.path,
            dtype="<f4",
            count=available * WAV_CHANNELS,
            offset=track.data_offset + first * FRAME_BYTES,
        )
        out[: len(read) // WAV_CHANNELS] = read.reshape(-1, WAV_CHANNELS)
    return out


@dataclass
class CarrierTracks:
    """As trilhas portadoras deste render, renderizadas sob demanda (uma vez cada) e lidas por janela."""

    ctx: RenderContext
    inputs: CarrierInputs
    _tracks: dict[str, CarrierTrack | None] = field(default_factory=dict)
    _building: set[str] = field(default_factory=set)
    _cameras: dict[int, CameraInput | None] = field(default_factory=dict)

    @property
    def spans(self) -> Sequence[tuple[float, float]]:
        return self.inputs.spans

    # ---------- a trilha inteira ----------

    def identity(self, track_id: str) -> str | None:
        """A identidade da trilha (a chave do WAV dela): muda quando o grafo ou o som de qualquer entrada muda. None quando a
        trilha não existe no projeto ou ainda não toca."""
        track = self.track(track_id)
        return track.identity if track else None

    def track(self, track_id: str) -> CarrierTrack | None:
        if track_id in self._tracks:
            return self._tracks[track_id]
        if track_id in self._building:
            raise ValueError(
                f"Vocoder: as portadoras fecham um ciclo na trilha {track_id}; deixe uma delas com a portadora gerada"
            )
        self._building.add(track_id)
        try:
            found = self._render(track_id)
        finally:
            self._building.discard(track_id)
        self._tracks[track_id] = found
        return found

    def _graph(self, track_id: str):
        """As entradas, as linhas e o rótulo de saída que dão a trilha antes de qualquer abaixamento, ou None quando ela não toca."""
        ctx, inputs = self.ctx, self.inputs
        if track_id in ("MUS", "NAR", "VO", "SFX"):
            if track_id == "MUS":
                music = ctx.project.audio.music
                path = inputs.music_path()
                if music is None or path is None or music.volume <= 0:
                    return None
                return tap_graph(ctx, "MUS", path, inputs.total, (), (), ())
            if track_id == "NAR":
                return tap_graph(ctx, "NAR", None, inputs.total, inputs.voiceovers(), (), ())
            if track_id == "VO":
                return tap_graph(ctx, "VO", None, inputs.total, (), (), inputs.voice_files())
            # os efeitos sonoros valem com o volume da spec, sem nivelar contra a voz (o mesmo que o Auto Duck mede antes dos mezaninos)
            return tap_graph(ctx, "SFX", None, inputs.total, (), unleveled_effects(ctx, inputs.spans), ())
        pieces = self._camera_pieces() if track_id == "A1" else self._external_pieces(track_id)
        if not pieces:
            return None
        return carrier_graph(pieces, inputs.total)

    def _camera_pieces(self) -> list[CarrierPiece]:
        """O som da câmera de cada clipe, só ele (sem as faixas externas e sem os PiPs), como o mezanino o recebe."""
        ctx = self.ctx
        if ctx.options.dry_run:  # a simulação não isola nem processa nada
            return []
        pieces = []
        for index, segment in enumerate(ctx.project.timeline):
            if (
                not isinstance(segment, ClipSegment)
                or index >= len(self.spans)
                or index >= len(self.inputs.sources)
            ):
                continue
            source = self.inputs.sources[index]
            if source.info is None:
                continue
            heard = camera_input(
                ctx,
                self._cameras,
                index,
                segment,
                source,
                segment_duration(segment, source.info, source.offset),
            )
            if heard is None:
                continue
            first, last = self.spans[index]
            pieces.append(
                CarrierPiece(
                    heard.path,
                    heard.stream,
                    heard.volume,
                    heard.file_in,
                    first,
                    last - first,
                    segment.speed,
                    heard.lead,
                )
            )
        return pieces

    def _external_pieces(self, track_id: str) -> list[CarrierPiece]:
        """O som da faixa externa `track_id` em cada clipe que a ouve, pela mesma conta do mezanino (`clip_windows`). Uma fonte com
        `parts` vira várias faixas físicas, e `track_origin` diz quais vêm da faixa da spec."""
        from .audio_effects import track_audio_overrides

        ctx = self.ctx
        wanted = external_index(track_id)
        origin = (
            list(self.inputs.track_origin)
            if self.inputs.track_origin is not None
            else list(range(len(ctx.project.audio.tracks)))
        )
        if wanted is None or ctx.options.dry_run:
            return []
        pieces: list[CarrierPiece] = []
        for position, original in enumerate(origin):
            if original != wanted or position >= len(ctx.project.audio.tracks):
                continue
            track = ctx.project.audio.tracks[position]
            source = ctx.session.get(track.source)
            if source is None or source.path is None or source.info is None:
                continue
            overrides = track_audio_overrides(ctx)
            override = overrides[position] if position < len(overrides) else None
            path, stream = (override, 0) if override is not None else (source.path, source.audio_stream)
            for segment, window in clip_windows(
                track, ctx.session, ctx.project.timeline, self.spans, override
            ):
                pieces.append(
                    CarrierPiece(
                        path,
                        stream,
                        track.volume,
                        window.file_in,
                        window.start,
                        window.end - window.start,
                        segment.speed,
                    )
                )
        return pieces

    def _render(self, track_id: str) -> CarrierTrack | None:
        from .assembly import graph_args

        ctx = self.ctx
        graph = self._graph(track_id)
        if graph is None:
            return None
        inputs, lines, label = graph
        identity = cache_key(
            CARRIER_VERSION,
            track_id,
            ";".join(lines),
            inputs.args,
            input_stamps(inputs.args),
            round(self.inputs.total, 3),
        )
        out = config.AUDIO_FX_DIR / "carriers" / f"{identity}.wav"
        if ctx.options.dry_run:
            return CarrierTrack(out, identity)
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            staging = out.with_name(f"{out.stem}.tmp{out.suffix}")
            args = [
                *graph_args(ctx, inputs, lines, f"portadora_{track_id}.txt"),
                *["-map", label, "-c:a", "pcm_f32le", "-ar", str(SAMPLE_RATE), "-ac", str(WAV_CHANNELS)],
                str(staging),
            ]
            ctx.log(f"portadora do Vocoder: trilha {track_id}")
            try:
                ctx.runner.run(FFmpegCommand(args, label="portadora do Vocoder", total=self.inputs.total))
                if staging.exists():  # na simulação (RecordingRunner) nada é gravado
                    staging.replace(out)
            finally:
                staging.unlink(missing_ok=True)
        if not out.exists():
            return CarrierTrack(out, identity)
        try:
            offset, frames = wav_layout(out)
        except ValueError:  # um arquivo que não é WAV não tem o que ler: a trilha vale como ausente
            offset, frames = 0, 0
        return CarrierTrack(out, identity, offset, frames)

    # ---------- a janela de um item ----------

    def window(self, track_id: str, placement: Sequence[PlacedRun], frames: int) -> np.ndarray | None:
        """Os `frames` quadros do sinal que entra no Vocoder de um item: silêncio onde nenhum trecho do `placement` cobre, e onde cobre o
        pedaço da trilha que toca naquele instante (esticado de volta ao tempo do item quando o clipe tem outra velocidade, para o
        tom da portadora se manter). None quando a trilha não existe, ainda não toca ou o WAV dela não foi gravado."""
        track = self.track(track_id)
        if track is None or not track.path.exists() or track.frames <= 0:
            return None
        out = np.zeros((frames, WAV_CHANNELS), dtype=np.float32)
        for run in placement:
            first = round(run.item_at * SAMPLE_RATE)
            if first >= frames:
                continue
            piece = self._piece(track, run)
            count = min(len(piece), frames - max(first, 0))
            if count > 0:
                out[max(first, 0) : max(first, 0) + count] = piece[:count]
        return out

    def _piece(self, track: CarrierTrack, run: PlacedRun) -> np.ndarray:
        """O trecho da trilha em que o item toca, no tempo do item: `run.length` segundos do projeto a partir de `run.timeline_at`,
        e, com velocidade diferente de 1, esticado por `stretch_filter` até `run.length * run.speed` segundos."""
        start = round(run.timeline_at * SAMPLE_RATE)
        length = round(run.length * SAMPLE_RATE)
        if abs(run.speed - 1.0) < 1e-9:
            return _read_frames(track, start, length)
        wanted = round(run.item_length * SAMPLE_RATE)
        raw = self._stretch(track, run)
        return _fitted_frames(raw, wanted)

    def _stretch(self, track: CarrierTrack, run: PlacedRun) -> np.ndarray:
        import shutil
        import tempfile

        scratch = Path(tempfile.mkdtemp(prefix="dmaker-carrier-"))
        try:
            raw = scratch / "trecho.f32"
            self.ctx.runner.run(
                FFmpegCommand(
                    [
                        *[
                            "-ss",
                            f"{max(run.timeline_at, 0):.6f}",
                            "-t",
                            f"{run.length:.6f}",
                            "-i",
                            str(track.path),
                        ],
                        *["-af", stretch_filter(run.speed)],
                        *["-f", "f32le", "-ac", str(WAV_CHANNELS), "-ar", str(SAMPLE_RATE), str(raw)],
                    ],
                    label="esticar a portadora do Vocoder",
                    total=run.length,
                )
            )
            if not raw.exists():  # na simulação (RecordingRunner) nada é gravado
                return np.zeros((0, WAV_CHANNELS), dtype=np.float32)
            return np.fromfile(raw, dtype="<f4").reshape(-1, WAV_CHANNELS)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


def _fitted_frames(samples: np.ndarray, frames: int) -> np.ndarray:
    """`samples` com exatamente `frames` quadros (o que sobra é cortado e o que falta vira silêncio)."""
    if len(samples) >= frames:
        return samples[:frames]
    return np.vstack([samples, np.zeros((frames - len(samples), samples.shape[1]), dtype=samples.dtype)])


__all__ = [
    "CarrierInputs",
    "CarrierTracks",
    "Deferred",
    "install_carrier_tracks",
    "uses_carrier_tracks",
]
