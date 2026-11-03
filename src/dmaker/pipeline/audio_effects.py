"""Efeitos de áudio por item: o item vira um arquivo de áudio processado em cache, e os quatro caminhos do som
(mezanino do clipe, mistura, PiP e prévia) trocam a fonte original por ele.

Por que um arquivo e não filtros dentro de cada caminho: a faixa externa é fatiada por clipe, e Reverter ou
Normalizar fatia por fatia daria som errado (cada pedaço invertido sozinho, cada um com o próprio pico). Com o
item inteiro processado antes de fatiar, o render e a prévia usam exatamente o mesmo resultado, e quem só
precisa de uma fatia lê o arquivo pronto. O grafo de cada cadeia é puro (`filtergraph.audio_effects`); aqui só
se decide o que processar, se mede o que precisa de medida e se executa pelo `FFmpegRunner` injetado.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from .. import config
from ..domain.audio_effects import EffectBase, active_effects, chain_duration, chain_signature
from ..domain.audio_shift import shifted_window
from ..domain.spec import ClipSegment
from ..filtergraph.audio_effects import (
    Measure,
    chain_lines,
    ingress_line,
    measure_lines,
    parse_astats,
    span_samples,
)
from ..filtergraph.common import Inputs
from ..filtergraph.mezzanine import uses_camera_audio
from ..filtergraph.pip import ResolvedVideoOverlay, pip_audio_window
from ..media.ffmpeg import FFmpegCommand, FFmpegRunner
from .cache_key import cache_key
from .context import RenderContext
from .sources import Source
from .voiceover import PreparedVoiceover

EFFECTS_VERSION = "fx1"  # muda quando a receita do arquivo processado muda (invalida o cache)

# O arquivo processado é WAV de ponto flutuante de 32 bits: um ganho que passa de 0 dBFS no meio da cadeia não
# corta, e inverter duas vezes devolve a amostra exata. É o dobro do tamanho do 16 bits, em troca de não perder nada.
PROCESSED_CODEC = ["-c:a", "pcm_f32le"]


@dataclass(frozen=True)
class AudioItem:
    """O que recebe a cadeia: `duration` segundos do arquivo `path` a partir de `start` (na faixa `stream`).

    `origin` entra na chave quando o arquivo não identifica sozinho o que há nele (o áudio isolado de um trecho
    de câmera, por exemplo). `lead` completa o começo com silêncio: o item dura `duration`, dos quais `lead` são
    silêncio e o resto vem do arquivo."""

    path: Path
    duration: float
    effects: tuple[EffectBase, ...]
    start: float = 0.0
    stream: int = 0
    origin: str = ""
    lead: float = (
        0.0  # silêncio antes de o arquivo começar, dentro do item (som deslocado para antes do arquivo)
    )


@dataclass(frozen=True)
class ProcessedAudio:
    """O arquivo depois da cadeia e quanto ele dura (que muda com o Repetir)."""

    path: Path
    duration: float


def _stamp(path: Path) -> tuple[int, int] | None:
    """Data e tamanho do arquivo, para trocar o conteúdo trocar a chave. None se ele ainda não existe (simulação)."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


class EffectProcessor:
    """Processa um item com a cadeia de efeitos, guardando o resultado em cache pelo que decide o som.

    O ffmpeg entra por injeção (`runner`), como no resto do pipeline: com o `RecordingRunner` nada é executado e
    os comandos só ficam registrados (a simulação do render)."""

    def __init__(self, runner: FFmpegRunner, cache_dir: Path | None = None) -> None:
        self.runner = runner
        self._cache_dir = cache_dir

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir or config.AUDIO_FX_DIR

    def key(self, item: AudioItem) -> str:
        return cache_key(
            EFFECTS_VERSION,
            str(item.path),
            _stamp(item.path),
            item.stream,
            round(item.start, 3),
            round(item.duration, 3),
            item.origin,
            chain_signature(item.effects),
            *(
                [round(item.lead, 3)] if item.lead else []
            ),  # fora da chave sem deslocamento: cache antigo vale
        )

    def process(self, item: AudioItem) -> ProcessedAudio | None:
        """O item processado, ou None quando nenhum efeito está ligado (o som segue pela fonte original)."""
        if not active_effects(item.effects) or item.duration <= 0:
            return None
        out = self.cache_dir / f"{self.key(item)}.wav"
        if not out.exists():
            self._render(item, out)
        return ProcessedAudio(out, chain_duration(item.effects, item.duration))

    # ---------- execução ----------

    def _inputs(self, item: AudioItem) -> Inputs:
        inputs = Inputs()
        inputs.add(item.path, "-ss", f"{max(item.start, 0):.3f}", "-t", f"{item.duration - item.lead:.3f}")
        return inputs

    def _render(self, item: AudioItem, out: Path) -> None:
        measures = self._measures(item)
        inputs = self._inputs(item)
        lines = [ingress_line(0, item.stream, "[fx_in]", item.lead)]
        lines += chain_lines("[fx_in]", "[fx_out]", item.effects, item.duration, measures)
        out.parent.mkdir(parents=True, exist_ok=True)
        staging = out.with_name(f"{out.stem}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}{out.suffix}")
        args = [*inputs.args, "-filter_complex", ";".join(lines), "-map", "[fx_out]", *PROCESSED_CODEC]
        args.append(str(staging))
        total = chain_duration(item.effects, item.duration)
        try:
            self.runner.run(FFmpegCommand(args, label="efeitos de áudio", total=total))
            if staging.exists():  # na simulação (RecordingRunner) nada é gravado
                staging.replace(out)
        finally:
            staging.unlink(missing_ok=True)

    def _measures(self, item: AudioItem) -> dict[int, Measure]:
        """A medida do sinal que entra em cada efeito que a pede: uma passada de análise até aquele ponto da
        cadeia. Os efeitos anteriores já entram com as próprias medidas, na ordem."""
        measures: dict[int, Measure] = {}
        for index, effect in active_effects(item.effects):
            if not effect.needs_measure():
                continue
            before = item.effects[:index]
            reaching = chain_duration(before, item.duration)
            lines = [ingress_line(0, item.stream, "[fx_in]", item.lead)]
            lines += chain_lines("[fx_in]", "[fx_pre]", before, item.duration, measures)
            lines += measure_lines("[fx_pre]", "[fx_meas]", span_samples(effect, reaching))
            args = [
                *self._inputs(item).args,
                "-filter_complex",
                ";".join(lines),
                "-map",
                "[fx_meas]",
                "-f",
                "null",
                "-",
            ]
            measure = parse_astats(self.runner.capture(args, label="medida do efeito de áudio"))
            if measure is not None:
                measures[index] = measure
        return measures


# ---------- os caminhos do som ----------


def effect_processor(ctx: RenderContext) -> EffectProcessor:
    """O processador do render em curso, criado na primeira vez que algum item tem efeito."""
    if ctx.audio_fx is None:
        ctx.audio_fx = EffectProcessor(ctx.runner)
    return ctx.audio_fx


def clip_camera_audio(
    ctx: RenderContext,
    segment: ClipSegment,
    source: Source,
    in_point: float,
    length: float,
    isolated: Path | None,
) -> Path | None:
    """O som da câmera do clipe depois dos efeitos do clipe, ou None quando não há efeito ligado ou a câmera não
    soa. O item é o trecho da fonte que o clipe usa (`length`, no tempo da fonte e antes do `speed`); quando o
    trecho vem do isolamento vocal, é o áudio isolado. Entra no mezanino no lugar do áudio da câmera."""
    info = source.info
    if not active_effects(segment.effects) or info is None or not uses_camera_audio(segment, info):
        return None
    effects = tuple(segment.effects)
    # com o som deslocado a janela do item começa antes (ou depois) da imagem; sem deslocamento é a de sempre
    window = shifted_window(in_point, segment.speed, segment.audio_offset) if segment.audio_offset else None
    if isolated is not None:
        item = AudioItem(isolated, length, effects, origin="isolado", lead=window.lead if window else 0.0)
    else:
        assert source.path is not None
        start = window.read_from if window else max(in_point, 0.0)
        item = AudioItem(
            source.path, length, effects, start, source.audio_stream, lead=window.lead if window else 0.0
        )
    done = effect_processor(ctx).process(item)
    return done.path if done else None


def track_audio_overrides(ctx: RenderContext) -> tuple[Path | None, ...]:
    """Para cada faixa externa de `audio.tracks`, o arquivo inteiro já processado (ou None, sem efeito ligado ou
    com o arquivo ausente). É calculado uma vez por render e vale para todos os clipes que fatiam a faixa."""
    if ctx.track_audio is None:
        overrides: list[Path | None] = []
        for track in ctx.project.audio.tracks:
            source = ctx.session.get(track.source)
            override = None
            if (
                active_effects(track.effects)
                and source is not None
                and source.path is not None
                and source.info is not None
                and source.path.exists()
            ):
                item = AudioItem(
                    source.path, source.info.duration, tuple(track.effects), 0.0, source.audio_stream
                )
                done = effect_processor(ctx).process(item)
                override = done.path if done else None
            overrides.append(override)
        ctx.track_audio = tuple(overrides)
    return ctx.track_audio


def processed_music(ctx: RenderContext, music_path: Path | None) -> Path | None:
    """O arquivo da música depois dos efeitos dela, ou o próprio arquivo quando não há efeito ligado. O item é a
    música inteira: as janelas, o ponto de entrada e o loop recortam o arquivo já processado."""
    music = ctx.project.audio.music
    if music_path is None or music is None or music.volume <= 0 or not active_effects(music.effects):
        return music_path
    item = AudioItem(music_path, ctx.prober(music_path).duration, tuple(music.effects))
    done = effect_processor(ctx).process(item)
    return done.path if done else music_path


def processed_voiceovers(
    ctx: RenderContext, voiceovers: Sequence[PreparedVoiceover]
) -> list[PreparedVoiceover]:
    """As narrações com o arquivo trocado pelo processado, quando a narração tem efeito ligado."""
    result = []
    for voiceover in voiceovers:
        done = None
        if active_effects(voiceover.effects):
            done = effect_processor(ctx).process(
                AudioItem(voiceover.path, voiceover.duration, voiceover.effects)
            )
        result.append(replace(voiceover, path=done.path) if done else voiceover)
    return result


def processed_pips(ctx: RenderContext, pips: Sequence[ResolvedVideoOverlay]) -> None:
    """Põe em cada PiP com som e com efeito ligado o arquivo do áudio já processado (`audio_path`): a mixagem lê
    dele no lugar da faixa de áudio do vídeo. O item é o trecho do vídeo que o PiP mostra."""
    for pip in pips:
        effects = tuple(pip.overlay.effects)
        if not (pip.has_audio and pip.overlay.volume > 0 and active_effects(effects)):
            continue
        window = pip_audio_window(pip)
        item = AudioItem(
            pip.path, pip.duration, effects, window.read_from, pip.audio_stream, lead=window.lead
        )
        done = effect_processor(ctx).process(item)
        pip.audio_path = done.path if done else None
