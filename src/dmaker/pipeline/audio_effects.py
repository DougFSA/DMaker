"""Efeitos de áudio por item: o item vira um arquivo de áudio processado em cache, e os quatro caminhos do som
(mezanino do clipe, mistura, PiP e prévia) trocam a fonte original por ele.

Por que um arquivo e não filtros dentro de cada caminho: a faixa externa é fatiada por clipe, e Reverter ou
Normalizar fatia por fatia daria som errado (cada pedaço invertido sozinho, cada um com o próprio pico). Com o
item inteiro processado antes de fatiar, o render e a prévia usam exatamente o mesmo resultado, e quem só
precisa de uma fatia lê o arquivo pronto. O grafo de cada cadeia é puro (`filtergraph.audio_effects`); aqui só
se decide o que processar, se mede o que precisa de medida e se executa pelo `FFmpegRunner` injetado.

Um efeito pode ser um filtro do ffmpeg ou uma função sobre as amostras (`register_sample_builder`). Quando a cadeia
mistura os dois, ela é partida em trechos: os filtros seguidos formam um comando do ffmpeg, cada efeito de amostras
é um estágio em numpy, e o sinal passa de um para o outro por um arquivo PCM temporário. Só o arquivo final fica no
cache; uma cadeia só de filtros continua sendo um comando só, o mesmo de sempre.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from .. import config
from ..domain.audio_effects import (
    EffectBase,
    active_effects,
    chain_duration,
    chain_refusal,
    chain_signature,
)
from ..domain.audio_effects.restoration import AUTO_PROFILE
from ..domain.audio_shift import shifted_window
from ..domain.music_tempo import music_chain
from ..domain.plugins import fit_params
from ..domain.spec import ClipSegment, GeneratedSound
from ..filtergraph.audio_effects import (
    SAMPLE_RATE,
    Measure,
    SampleRequest,
    Stage,
    apply_sample_effect,
    ingress_line,
    level_measure_lines,
    parse_level_measure,
    span_samples,
    split_stages,
    stage_lines,
)
from ..filtergraph.common import Inputs
from ..filtergraph.mezzanine import uses_camera_audio
from ..filtergraph.pip import ResolvedVideoOverlay, pip_audio_window
from ..media.ffmpeg import FFmpegCommand, FFmpegRunner
from ..media.reverb import ensure_impulse
from ..media.spectral import NoiseSpectrum, noise_spectrum, quiet_pause_window
from ..media.wavio import read_wav_float
from .cache_key import cache_key
from .context import RenderContext
from .noise_profiles import AUTO_PROFILE_SECONDS, ProfileLocator, measure_profile
from .plugins import PluginService, PluginUnavailable, ResolvedPlugin, plugin_service
from .sample_reader import FFmpegSampleReader, SampleReader
from .sources import Source
from .voiceover import PreparedVoiceover

EFFECTS_VERSION = "fx1"  # muda quando a receita do arquivo processado muda (invalida o cache)

# O arquivo processado é WAV de ponto flutuante de 32 bits: um ganho que passa de 0 dBFS no meio da cadeia não
# corta, e inverter duas vezes devolve a amostra exata. É o dobro do tamanho do 16 bits, em troca de não perder nada.
PROCESSED_CODEC = ["-c:a", "pcm_f32le"]
# O sinal que passa de um trecho da cadeia para o seguinte: PCM de ponto flutuante cru, estéreo, na taxa da mistura.
# Sem cabeçalho nem perda: o numpy lê e grava direto, e o ffmpeg o recebe com `-f f32le`.
STAGE_CODEC = ["-f", "f32le", "-ac", "2", "-ar", str(SAMPLE_RATE)]
STAGE_CHANNELS = 2


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
    os comandos só ficam registrados (a simulação do render). `profiles` resolve os perfis de ruído do projeto (sem
    ele, só o perfil `auto` funciona) e `reader` lê as amostras que a medida do perfil precisa. `plugins` resolve os efeitos de
    plugin (o serviço do processo, quando não vem outro) e `on_warning` recebe o aviso de cada plugin que não pode rodar: o
    efeito é pulado e o render segue."""

    def __init__(
        self,
        runner: FFmpegRunner,
        cache_dir: Path | None = None,
        profiles: ProfileLocator | None = None,
        reader: SampleReader | None = None,
        plugins: PluginService | None = None,
        on_warning: Callable[[str], None] | None = None,
    ) -> None:
        self.runner = runner
        self._cache_dir = cache_dir
        self.profiles = profiles
        self._plugins = plugins
        self._on_warning = on_warning
        self._resolved: dict[tuple[str, str], ResolvedPlugin | str] = {}
        self._warned: set[str] = set()  # cada aviso sai uma vez: key() e process() consultam o mesmo item
        self.reader: SampleReader = reader or FFmpegSampleReader(runner)
        self._spectra: dict[
            str, NoiseSpectrum
        ] = {}  # o espectro de cada perfil já medido, pela assinatura dele

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir or config.AUDIO_FX_DIR

    def key(self, item: AudioItem) -> str:
        item, hosts = self._available(item)
        return self._key(item, hosts)

    def _key(self, item: AudioItem, hosts: dict[int, ResolvedPlugin]) -> str:
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
            *self.profile_parts(item.effects),  # idem: sem perfil nomeado a chave é a de sempre
            *[hosts[index].signature() for index in sorted(hosts)],  # idem: sem plugin a chave é a de sempre
        )

    def process(self, item: AudioItem) -> ProcessedAudio | None:
        """O item processado, ou None quando nenhum efeito está ligado (o som segue pela fonte original). O efeito de plugin que
        não pode rodar aqui (não instalado, desabilitado) é pulado com um aviso."""
        item, hosts = self._available(item)
        if not active_effects(item.effects) or item.duration <= 0:
            return None
        reason = chain_refusal(item.effects, item.duration)
        if reason is not None:  # o teto de saída do Paulstretch: recusa antes de gastar memória e tempo
            raise ValueError(reason)
        out = self.cache_dir / f"{self._key(item, hosts)}.wav"
        if not out.exists():
            self._render(item, out, hosts)
        return ProcessedAudio(out, chain_duration(item.effects, item.duration))

    # ---------- plugins ----------

    def _service(self) -> PluginService:
        return self._plugins or plugin_service()

    def _plugin(self, format_name: str, ref: str) -> ResolvedPlugin | str:
        """O plugin resolvido, ou o motivo de ele não poder rodar (guardado: o mesmo plugin é perguntado uma vez por render)."""
        key = (format_name, ref)
        if key not in self._resolved:
            try:
                self._resolved[key] = self._service().resolve(format_name, ref)
            except PluginUnavailable as exc:
                self._resolved[key] = str(exc)
        return self._resolved[key]

    def _warn(self, message: str) -> None:
        """Avisa uma vez por mensagem: o mesmo item passa por `key()` e por `process()`."""
        if self._on_warning is not None and message not in self._warned:
            self._warned.add(message)
            self._on_warning(message)

    def _available(self, item: AudioItem) -> tuple[AudioItem, dict[int, ResolvedPlugin]]:
        """O item sem os efeitos de plugin que não podem rodar (desligados, para as posições da cadeia não mudarem), com os
        parâmetros dos que sobram ajustados à faixa do plugin, e os plugins resolvidos deles, pela posição. Sem nenhum efeito de plugin não consulta nada."""
        hosted = [
            (index, effect)
            for index, effect in active_effects(item.effects)
            if effect.host_format() is not None
        ]
        if not hosted:
            return item, {}
        hosts: dict[int, ResolvedPlugin] = {}
        effects = list(item.effects)
        for index, effect in hosted:
            resolved = self._plugin(effect.host_format() or "", effect.host_reference() or "")
            if isinstance(resolved, str):
                self._warn(f"efeito Plugin pulado: {resolved}")
                effects[index] = effect.model_copy(update={"enabled": False})
            else:
                fitted = fit_params(resolved.info, dict(effect.params))
                for problem in fitted.problems:
                    self._warn(f"efeito Plugin: {problem}")
                if fitted.params != effect.params:
                    effects[index] = effect.model_copy(update={"params": fitted.params})
                hosts[index] = resolved
        return replace(item, effects=tuple(effects)), hosts

    def host_parts(self, effects: Sequence[EffectBase]) -> list:
        """O que os plugins da cadeia decidem do som, para a chave de cache de quem usa o item (o mezanino do clipe, o pedaço
        da prévia): o arquivo de cada plugin, ou a ausência dele. Vazia sem efeito de plugin."""
        parts = []
        for _, effect in active_effects(effects):
            format_name = effect.host_format()
            if format_name is None:
                continue
            ref = effect.host_reference() or ""
            resolved = self._plugin(format_name, ref)
            parts.append(["ausente", format_name, ref] if isinstance(resolved, str) else resolved.signature())
        return parts

    # ---------- perfis de ruído ----------

    def _named_profiles(self, effects: Sequence[EffectBase]) -> list[str]:
        """Os perfis nomeados que a cadeia usa (o `auto` não é nomeado: ele sai do próprio item)."""
        names = {
            reference
            for _, effect in active_effects(effects)
            if (reference := effect.noise_profile()) not in (None, AUTO_PROFILE)
        }
        return sorted(names)  # type: ignore[type-var]

    def profile_parts(self, effects: Sequence[EffectBase]) -> list:
        """O que o espectro dos perfis nomeados decide, para a chave de cache: a definição de cada um e o arquivo."""
        return [
            self.profiles.signature(name) if self.profiles else name for name in self._named_profiles(effects)
        ]

    def _spectrum(self, effect: EffectBase, entering: np.ndarray) -> NoiseSpectrum | None:
        """O espectro do ruído para o efeito: o do perfil nomeado, medido no arquivo dele, ou o da janela mais quieta do
        sinal que entra (`auto`). None quando o perfil automático não cabe: o item é curto demais para uma média ou não tem
        uma pausa só de ruído (nada é tirado, em vez de tratar fala ou um tom contínuo como chiado)."""
        reference = effect.noise_profile()
        if reference == AUTO_PROFILE:
            found = quiet_pause_window(entering, SAMPLE_RATE, AUTO_PROFILE_SECONDS)
            if found is None:  # sem uma pausa só de ruído não há perfil: o efeito não tira nada
                return None
            window = entering[round(found[0] * SAMPLE_RATE) : round(found[1] * SAMPLE_RATE)]
            try:
                return noise_spectrum(window, SAMPLE_RATE)
            except ValueError:
                return None
        if self.profiles is None:
            raise ValueError(f"o perfil de ruído {reference!r} não está disponível neste contexto")
        assert reference is not None
        signature = repr(self.profiles.signature(reference))
        if signature not in self._spectra:
            self._spectra[signature] = measure_profile(self.reader, self.profiles.slice(reference))
        return self._spectra[signature]

    # ---------- execução ----------

    def _inputs(self, item: AudioItem) -> Inputs:
        inputs = Inputs()
        inputs.add(item.path, "-ss", f"{max(item.start, 0):.3f}", "-t", f"{item.duration - item.lead:.3f}")
        return inputs

    def _render(self, item: AudioItem, out: Path, hosts: dict[int, ResolvedPlugin]) -> None:
        out.parent.mkdir(parents=True, exist_ok=True)
        prepare_impulse_responses(item.effects)
        token = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        staging = out.with_name(f"{out.stem}.tmp-{token}{out.suffix}")
        scratch = out.with_name(f"{out.stem}.stages-{token}")
        try:
            self._run_stages(item, staging, scratch, hosts)
            if staging.exists():  # na simulação (RecordingRunner) nada é gravado
                staging.replace(out)
        finally:
            staging.unlink(missing_ok=True)
            shutil.rmtree(scratch, ignore_errors=True)

    def _run_stages(
        self, item: AudioItem, destination: Path, scratch: Path, hosts: dict[int, ResolvedPlugin]
    ) -> None:
        """Percorre os trechos da cadeia: cada um lê o sinal do anterior (o item, no primeiro) e grava o seguinte. O
        primeiro e o último trecho são sempre de ffmpeg: o que lê o item e o que grava o WAV final, mesmo que o
        efeito de amostras esteja numa ponta da cadeia."""
        stages = split_stages(item.effects)
        if stages[0].samples:
            stages.insert(0, Stage(()))
        if stages[-1].samples:
            stages.append(Stage(()))
        entering: Path | None = None  # None: o sinal é o próprio item
        duration = item.duration
        total = chain_duration(item.effects, item.duration)
        for position, stage in enumerate(stages):
            final = position == len(stages) - 1
            target = destination if final else scratch / f"estagio{position}.f32"
            if stage.samples:
                self._sample_pass(stage, entering, target)
            else:
                self._filter_pass(item, stage, entering, duration, target, final, total, hosts)
            entering = target
            for _, effect in stage.effects:
                duration = effect.output_duration(duration)

    def _filter_pass(
        self,
        item: AudioItem,
        stage: Stage,
        entering: Path | None,
        duration: float,
        target: Path,
        final: bool,
        total: float,
        hosts: dict[int, ResolvedPlugin],
    ) -> None:
        """Um comando do ffmpeg: os efeitos de filtro do trecho, do sinal que entra até `target`. Um trecho de plugin roda com o
        ffmpeg que hospeda o formato dele, na pasta e com o ambiente que o plugin pede."""
        if entering is None:
            inputs = self._inputs(item)
            ingress = ingress_line(0, item.stream, "[fx_in]", item.lead)
        else:
            inputs = Inputs()
            inputs.add(entering, *STAGE_CODEC)
            ingress = "[0:a]anull[fx_in]"
        measures = self._measures(inputs, ingress, stage, duration, item.stream if entering is None else 0)
        ports = {index: hosts[index].ports for index, _ in stage.effects if index in hosts}
        lines = [ingress, *stage_lines("[fx_in]", "[fx_out]", stage.effects, duration, measures, ports=ports)]
        target.parent.mkdir(parents=True, exist_ok=True)
        args = [*inputs.args, "-filter_complex", ";".join(lines), "-map", "[fx_out]"]
        args += PROCESSED_CODEC if final else STAGE_CODEC
        args.append(str(target))
        where: dict = {}
        if stage.host is not None:
            plugin = hosts[stage.effects[0][0]]
            where = {"binary": plugin.ffmpeg, "cwd": plugin.cwd, "env": plugin.env or None}
        self.runner.run(FFmpegCommand(args, label="efeitos de áudio", total=total, **where))

    def _sample_pass(self, stage: Stage, entering: Path | None, target: Path) -> None:
        """O estágio de amostras: lê o sinal do trecho anterior, aplica o efeito em numpy e grava o seguinte. O arquivo
        de entrada é mapeado em disco (só o que o efeito toca vai à memória)."""
        ((_, effect),) = stage.effects
        if (
            entering is None or not entering.exists()
        ):  # na simulação (RecordingRunner) não há sinal para processar
            return
        if entering.stat().st_size == 0:  # nada a processar (o arquivo vazio nem pode ser mapeado)
            shutil.copyfile(entering, target)
            return
        entering_samples = np.memmap(entering, dtype="<f4", mode="r").reshape(-1, STAGE_CHANNELS)
        measure = None
        if effect.noise_profile() is not None:
            spectrum = self._spectrum(effect, entering_samples)
            if spectrum is None:  # item curto demais para medir o ruído: o efeito não tem o que tirar
                shutil.copyfile(entering, target)
                return
            measure = Measure(noise=spectrum)
        side = self._carrier(effect, len(entering_samples))
        result = apply_sample_effect(SampleRequest(effect, entering_samples, SAMPLE_RATE, measure, side))
        np.asarray(result, dtype="<f4").tofile(target)

    def _carrier(self, effect: EffectBase, frames: int) -> np.ndarray | None:
        """A segunda entrada de um efeito de amostras que pede uma (a portadora do Vocoder): o gerador de som dele, na duração do
        sinal que entra, `(quadros, 2)` na taxa da mistura. Passa pelo mesmo cache dos sons gerados (`cache/generated`), então a
        prévia e o render dividem o arquivo. None quando o efeito não usa segunda entrada."""
        found = effect.carrier_sound()
        if found is None:
            return None
        from .generated_sounds import GeneratedSoundRenderer  # import tardio: aquele módulo importa este

        generator, params = found
        sound = GeneratedSound(generator=generator, params=params, duration=frames / SAMPLE_RATE)
        path = GeneratedSoundRenderer(self.runner).render(sound, lambda name: Path(name))
        samples, _ = read_wav_float(path)
        return _fitted(samples, frames)

    def _measures(
        self, inputs: Inputs, ingress: str, stage: Stage, duration: float, item_stream: int = 0
    ) -> dict[int, Measure]:
        """A medida do sinal que entra em cada efeito do trecho que a pede: uma passada de análise até aquele ponto do
        trecho. Os efeitos anteriores já entram com as próprias medidas, na ordem. O que se mede (pico, LUFS ou RMS) é
        o `measure_kind()` do efeito; `item_stream` é a faixa do arquivo que o item usa, que diz se ele é mono."""
        measures: dict[int, Measure] = {}
        for index, effect in stage.effects:
            if not effect.needs_measure():
                continue
            before = [(i, e) for i, e in stage.effects if i < index]
            reaching = duration
            for _, earlier in before:
                reaching = earlier.output_duration(reaching)
            lines = [ingress]
            lines += stage_lines("[fx_in]", "[fx_pre]", before, duration, measures)
            kind = effect.measure_kind()
            lines += level_measure_lines(kind, "[fx_pre]", "[fx_meas]", span_samples(effect, reaching))
            args = [*inputs.args, "-filter_complex", ";".join(lines), "-map", "[fx_meas]", "-f", "null", "-"]
            report = self.runner.capture(args, label="medida do efeito de áudio")
            measure = parse_level_measure(kind, report, item_stream)
            if measure is not None:
                measures[index] = measure
        return measures


def prepare_impulse_responses(effects: Sequence[EffectBase]) -> None:
    """Cria (se faltam) as respostas ao impulso que os efeitos ligados da cadeia leem: o grafo do Reverb as lê do cache por um
    `amovie`, então o arquivo precisa existir antes do comando."""
    for _, effect in active_effects(effects):
        settings = effect.impulse_settings()
        if settings is not None:
            ensure_impulse(settings, SAMPLE_RATE)


def _fitted(samples: np.ndarray, frames: int) -> np.ndarray:
    """`samples` com exatamente `frames` quadros: o que sobra é cortado e o que falta (arredondamento da duração) vira silêncio."""
    if len(samples) >= frames:
        return samples[:frames]
    return np.vstack([samples, np.zeros((frames - len(samples), samples.shape[1]), dtype=samples.dtype)])


# ---------- os caminhos do som ----------


def effect_processor(ctx: RenderContext) -> EffectProcessor:
    """O processador do render em curso, criado na primeira vez que algum item tem efeito."""
    if ctx.audio_fx is None:
        ctx.audio_fx = EffectProcessor(
            ctx.runner,
            profiles=ProfileLocator(ctx.project, ctx.session),
            on_warning=getattr(ctx, "warn", None),
        )
    return ctx.audio_fx


def uses_named_profile(effects: Sequence[EffectBase]) -> bool:
    """Se a cadeia tem uma Redução de ruído ligada que aponta para um perfil guardado no projeto (e não para o `auto`)."""
    return any(effect.noise_profile() not in (None, AUTO_PROFILE) for _, effect in active_effects(effects))


def noise_profile_parts(ctx: RenderContext, effects: Sequence[EffectBase]) -> list:
    """A parte da chave de cache de um item (o mezanino do clipe, o pedaço da prévia) que muda quando algo de fora da spec que a
    cadeia usa muda: o perfil de ruído nomeado, ou o arquivo de um plugin. Vazia sem nenhum dos dois: a chave de um projeto
    antigo é a de sempre."""
    parts: list = []
    if uses_named_profile(effects):  # a maioria dos itens não usa: nem cria o processador
        parts += effect_processor(ctx).profile_parts(effects)
    if any(effect.host_format() is not None for _, effect in active_effects(effects)):
        parts += effect_processor(ctx).host_parts(effects)
    return parts


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
    música inteira: as janelas, o ponto de entrada e o loop recortam o arquivo já processado. Com `stretch_to_tempo`, a
    cadeia começa pelo esticamento derivado até o andamento do projeto (`music_chain`)."""
    music = ctx.project.audio.music
    chain = music_chain(ctx.project.audio)
    if music_path is None or music is None or music.volume <= 0 or not active_effects(chain):
        return music_path
    item = AudioItem(music_path, ctx.prober(music_path).duration, chain)
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
