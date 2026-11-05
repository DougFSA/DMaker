"""Sons gerados (`audio.generated`): produz o WAV de cada item e o entrega à mixagem como um efeito sonoro.

O WAV de cada item é feito uma vez e guardado em `cache/generated` pelo hash do gerador, dos parâmetros, da duração e da taxa
(mais a data e o tamanho dos arquivos que ele lê): o render, a prévia da linha do tempo e a exportação por trilha partem do
mesmo arquivo. Daí em diante o item é tratado como um efeito sonoro (`SfxTrack`), com a cadeia de efeitos dele já aplicada
pelo `EffectProcessor`, o mesmo dos outros itens de áudio.

Quem diz o que soa é o registro de geradores (`filtergraph/generators`): uma fonte do ffmpeg, que aqui vira um comando, ou as
amostras em numpy, que aqui viram o WAV. O ffmpeg entra por injeção (`runner`), então a simulação do render não executa nada.
"""

from __future__ import annotations

import math
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import config
from ..domain.audio_effects import active_effects
from ..domain.carrier_tracks import PlacedRun
from ..domain.generators import GENERATOR_SAMPLE_RATE, parse_generator
from ..domain.spec import GeneratedSound, Project
from ..filtergraph.generators import FilterSource, GeneratorRequest, build_generator
from ..media.ffmpeg import FFmpegCommand, FFmpegRunner
from ..media.wavio import read_wav_float, write_wav_float
from .audio_effects import AudioItem, effect_processor
from .cache_key import cache_key
from .context import RenderContext
from .sfx import SfxTrack

GENERATORS_VERSION = "gen1"  # muda quando a receita de um gerador muda (invalida o cache dos sons gerados)
CHANNELS = 2
# A fonte do ffmpeg é mono; o `pan` copia o canal para os dois lados sem ganho (o `aformat` do mixer o rebaixaria 3 dB)
STEREO_FROM_MONO = "pan=stereo|c0=c0|c1=c0"
SILENT_DB = -120.0  # abaixo disto o item não soa (o volume 0 da spec)


def file_stamp(path: Path) -> tuple[int, int] | None:
    """Data e tamanho do arquivo que o gerador lê: trocar o conteúdo troca a chave. None se ele não existe."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def stereo_frames(samples: np.ndarray, frames: int) -> np.ndarray:
    """As amostras de um construtor como `(frames, 2)`: mono vira os dois canais iguais, e o que sobra ou falta no fim é
    cortado ou completado com silêncio, para o som ter exatamente a duração do item."""
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim == 1:
        data = data[:, None]
    if data.shape[1] == 1:
        data = np.repeat(data, CHANNELS, axis=1)
    if data.shape[0] >= frames:
        return data[:frames]
    return np.vstack([data, np.zeros((frames - data.shape[0], data.shape[1]), dtype=np.float32)])


def source_args(source: FilterSource, frames: int, out: Path) -> list[str]:
    """O comando que grava uma fonte do ffmpeg em WAV de ponto flutuante, estéreo e com `frames` quadros exatos (`apad` completa
    o que a fonte entregar a menos, `atrim` corta o que entregar a mais)."""
    graph = f"{source.graph},apad=whole_len={frames},atrim=end_sample={frames},{STEREO_FROM_MONO}[generated]"
    return ["-filter_complex", graph, "-map", "[generated]", "-c:a", "pcm_f32le", str(out)]


class GeneratedSoundRenderer:
    """Faz (ou acha no cache) o WAV de um som gerado. O ffmpeg entra por injeção, como no resto do pipeline."""

    def __init__(
        self, runner: FFmpegRunner, cache_dir: Path | None = None, *, write_files: bool = True
    ) -> None:
        self.runner = runner
        self._cache_dir = cache_dir
        self.write_files = (
            write_files  # False na simulação: nenhum arquivo nasce, só os comandos ficam registrados
        )

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir or config.GENERATED_DIR

    def key(self, sound: GeneratedSound, resolve: Callable[[str], Path]) -> str:
        generator = parse_generator(sound.generator, sound.params)
        return cache_key(
            GENERATORS_VERSION,
            sound.generator,
            sound.params,
            round(sound.duration, 6),
            GENERATOR_SAMPLE_RATE,
            [file_stamp(resolve(name)) for name in generator.files()],
        )

    def path_for(self, sound: GeneratedSound, resolve: Callable[[str], Path]) -> Path:
        return self.cache_dir / f"{self.key(sound, resolve)}.wav"

    def render(self, sound: GeneratedSound, resolve: Callable[[str], Path]) -> Path:
        """O WAV do som, criado se ainda não está no cache. Um gerador que falha (arquivo de amostras ausente, valor fora da
        faixa) levanta o erro dele, e o chamador diz a que item da spec ele pertence."""
        out = self.path_for(sound, resolve)
        if out.exists():
            return out
        generator = parse_generator(sound.generator, sound.params)
        request = GeneratorRequest(generator, sound.duration, GENERATOR_SAMPLE_RATE, resolve)
        built = build_generator(request)
        frames = request.frames
        out.parent.mkdir(parents=True, exist_ok=True)
        staging = out.with_name(f"{out.stem}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}{out.suffix}")
        try:
            if isinstance(built, FilterSource):
                self.runner.run(
                    FFmpegCommand(
                        source_args(built, frames, staging), label="som gerado", total=sound.duration
                    )
                )
            elif self.write_files:
                write_wav_float(staging, stereo_frames(built, frames), GENERATOR_SAMPLE_RATE)
            if staging.exists():  # na simulação (RecordingRunner) nada é gravado
                staging.replace(out)
        finally:
            staging.unlink(missing_ok=True)
        return out


def volume_db(volume: float) -> float:
    """O `volume` linear da spec em dB; o 0 vira o piso, que o ffmpeg trata como mudo."""
    return 20.0 * math.log10(volume) if volume > 0 else SILENT_DB


def generated_tracks(ctx: RenderContext, renderer: GeneratedSoundRenderer | None = None) -> list[SfxTrack]:
    """Os sons gerados do projeto como efeitos sonoros prontos para a mixagem: o WAV de cada um (com a cadeia de efeitos
    dele aplicada), o instante e o ganho. O ganho é o `volume` do item mais o ganho da trilha SFX, sem nivelar contra a voz:
    o `amplitude_db` do gerador é o nível de verdade do som. Item de volume 0 não soa e não é gerado.

    É a mesma conta para o render e para a prévia da linha do tempo.
    """
    audio = ctx.project.audio
    if not audio.generated:
        return []
    renderer = renderer or GeneratedSoundRenderer(ctx.runner, write_files=not ctx.options.dry_run)
    resolve = ctx.project.resolve
    tracks: list[SfxTrack] = []
    for index, sound in enumerate(audio.generated):
        if sound.volume <= 0:
            continue
        origin = f"audio.generated[{index}]"
        try:
            path = renderer.render(sound, resolve)
        except (FileNotFoundError, ValueError) as exc:
            raise type(exc)(f"{origin}: {exc}") from exc
        if active_effects(sound.effects):
            done = effect_processor(ctx).process(
                AudioItem(
                    path,
                    sound.duration,
                    tuple(sound.effects),
                    placement=(PlacedRun(0.0, sound.start, sound.duration),),
                )
            )
            path = done.path if done else path
        pan = max(-1.0, min(1.0, sound.pan + audio.sfx_pan))
        tracks.append(SfxTrack(path, sound.start, volume_db(sound.volume) + audio.sfx_gain_db, origin, pan))
    ctx.log(f"sons gerados: {len(tracks)}")
    return tracks


def generated_files(project: Project) -> list[str]:
    """Os arquivos que os sons gerados do projeto leem (os textos do Importar Amostras), como a spec os escreve."""
    found: list[str] = []
    for sound in project.audio.generated:
        found.extend(parse_generator(sound.generator, sound.params).files())
    return found


def check_generated_files(project: Project) -> None:
    """Falha antes de qualquer trabalho pesado quando um texto de amostras não existe, dizendo de qual item da spec ele é."""
    for index, sound in enumerate(project.audio.generated):
        for name in parse_generator(sound.generator, sound.params).files():
            if not project.resolve(name).exists():
                raise FileNotFoundError(f"audio.generated[{index}]: arquivo não encontrado: {name}")


# ---------- um som solto, em arquivo ----------


class GeneratedFileExists(FileExistsError):
    """O arquivo de destino já existe e o pedido não autorizou trocá-lo."""


@dataclass(frozen=True)
class GeneratedFile:
    """O que a geração de um som solto devolve: o arquivo, a duração, o gerador com os parâmetros completos e o pico medido."""

    path: Path
    duration: float
    generator: str
    params: dict
    peak_db: float

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "duration_s": round(self.duration, 3),
            "generator": self.generator,
            "params": self.params,
            "peak_dbfs": None
            if math.isinf(self.peak_db)
            else round(self.peak_db, 2),  # o silêncio não tem pico
        }


def generate_sound_file(
    generator: str,
    params: dict | None,
    duration: float | None,
    out: Path,
    *,
    overwrite: bool = False,
    resolve: Callable[[str], Path] | None = None,
    runner: FFmpegRunner | None = None,
    cache_dir: Path | None = None,
) -> GeneratedFile:
    """Gera um som e o grava em `out` como WAV estéreo de ponto flutuante de 32 bits (sem projeto: é o `dmaker audio generate`).
    Sem `duration`, vale a que o gerador pede. `resolve` leva o caminho de um texto de amostras ao arquivo (padrão: o caminho
    como veio, relativo à pasta de onde se roda). Um arquivo que já existe só é trocado com `overwrite`."""
    from ..media.ffmpeg import SubprocessRunner

    resolve = resolve or Path
    if out.suffix.lower() != ".wav":
        raise ValueError(
            f"o som gerado sai em WAV: use um destino .wav (recebi {out.name!r}); outros formatos saem por `dmaker audio export`"
        )
    if out.exists() and not overwrite:
        raise GeneratedFileExists(f"{out} já existe; use overwrite para trocá-lo")
    chosen = parse_generator(generator, params)
    seconds = duration if duration is not None else chosen.natural_duration(resolve)
    sound = GeneratedSound(generator=generator, params=chosen.model_dump(exclude={"type"}), duration=seconds)
    renderer = GeneratedSoundRenderer(runner or SubprocessRunner(quiet=True), cache_dir)
    made = renderer.render(sound, resolve)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(made, out)
    samples, _ = read_wav_float(out)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    peak_db = 20.0 * math.log10(peak) if peak > 0 else float("-inf")
    return GeneratedFile(out, seconds, generator, sound.params, peak_db)
