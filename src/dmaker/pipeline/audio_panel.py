"""O áudio de um item do projeto como o painel Áudio da interface o mostra, toca e prova: a onda por zoom, uma janela
para tocar e a prévia de um efeito ainda não gravado.

O item é visto "como soa", igual à análise (`audio_analysis`) e ao render: se tem efeitos ligados, o painel lê o arquivo
já processado pelo `EffectProcessor` (o mesmo cache do render); se não tem, lê a fonte. O tempo do painel é o tempo em
que os efeitos falam (`start` e `end` de um efeito): segundos do item e, nos itens que o render processa inteiros
(música e faixa externa), segundos do arquivo. `clock` leva esse tempo para o da linha do tempo do projeto.

Ler o áudio todo para construir os picos de uma hora leva alguns segundos, então a construção roda em segundo plano
(`PeakTasks`) e vai mostrando o que já tem; o ffmpeg e o leitor de amostras entram por injeção, como no resto do pipeline.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

from .. import config
from ..domain.audio_effects import EffectBase, active_effects, chain_duration
from ..domain.edits import EditError
from ..domain.effect_edits import apply_effect_op
from ..domain.spec import Project
from ..media.ffmpeg import FFmpegRunner, SubprocessRunner
from ..media.peak_levels import BlockAccumulator, build_levels, quantize, sample_columns
from ..media.probe import probe
from ..media.sample_reader import MAX_CHANNELS, SampleReader, open_reader
from ..media.waveform import (
    PYRAMID_VERSION,
    PeakPyramid,
    build_pyramid,
    load_pyramid,
    save_pyramid,
)
from ..media.wavio import wav_bytes
from .analysis_items import ItemAudio, ItemClock, TargetError, resolve_item
from .audio_effects import AudioItem, EffectProcessor
from .cache_key import cache_key
from .context import Prober
from .layout import project_layout
from .missing import MissingMedia
from .sync import OffsetFinder

PANEL_VERSION = "ap1"  # muda quando o que o painel lê do áudio muda (invalida o cache dos picos)
# O maior pedaço tocado de uma vez. A reprodução anda em janelas (nunca baixa o áudio inteiro) e o scrub pede pedaços
# pequenos; 40 s de estéreo em 16 bits são uns 7 MB.
MAX_WINDOW_SECONDS = 40.0
# Até esta duração a prévia de um efeito processa o item inteiro (é exata e fica em cache); acima, só um trecho em volta.
PREVIEW_FULL_LIMIT = 120.0
# Quanto de áudio antes e depois da janela a prévia de um item longo processa, para o filtro assentar e o efeito com
# intervalo ter o entorno de que precisa.
PREVIEW_PAD = 4.0
# Acima disto, um efeito que muda a duração ou troca o tempo de lugar (Repetir, Reverter) não tem prévia: processar
# uma hora para ouvir dez segundos não compensa.
PREVIEW_LONGEST = 1800.0
# Quantas amostras de verdade a resposta traz, no máximo, por pixel (o desenho em linha e a Draw Tool precisam delas)
SAMPLES_PER_COLUMN = 4


class AudioPanelError(ValueError):
    """O pedido do painel não pode ser atendido (janela grande demais, prévia sem resposta...)."""


@dataclass(frozen=True)
class HeardPlan:
    """O que o painel mostra de um alvo: o item, a duração do eixo, o que é processado e a chave dos picos."""

    target: str
    item: ItemAudio
    duration: float  # segundos do eixo do painel (o tempo em que os efeitos falam)
    origin: float  # instante do eixo em que o item começa a soar (a música com `start_at` começa no meio do arquivo)
    processed: bool  # há efeito ligado: o som vem do arquivo processado
    key: str
    rate: int  # estimativa antes de abrir o arquivo; o leitor traz o valor de verdade
    channels: int

    @property
    def clock(self) -> ItemClock | None:
        return self.item.clock

    def to_project(self, axis_time: float) -> float | None:
        """O instante do eixo como instante da linha do tempo do projeto, ou None se o item não tem lugar nela."""
        clock = self.item.clock
        return None if clock is None else clock.to_project(axis_time - self.origin)


@dataclass
class PyramidBuild:
    """A construção dos picos de um alvo: pronta, em andamento (com a pirâmide parcial) ou falha."""

    key: str
    plan: HeardPlan
    state: str = "building"  # building | ready | failed
    label: str = ""
    percent: int = 0
    error: str | None = None
    pyramid: PeakPyramid | None = None
    accumulator: BlockAccumulator | None = None
    reader: SampleReader | None = None
    done: threading.Event = field(default_factory=threading.Event)
    stop: threading.Event = field(default_factory=threading.Event)

    def snapshot(self) -> PeakPyramid | None:
        """A pirâmide pronta ou, durante a construção, a do que já foi lido."""
        if self.pyramid is not None:
            return self.pyramid
        if self.accumulator is None or self.reader is None:
            return None
        base = self.accumulator.base()
        return PeakPyramid(
            self.reader.rate,
            self.reader.channels,
            self.accumulator.frames,
            build_levels(base),
            complete=False,
        )


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


class AudioPanelService:
    """Planeja, lê e prova o áudio de um alvo. As dependências do mundo entram por injeção."""

    def __init__(
        self,
        runner: FFmpegRunner | None = None,
        prober: Prober = probe,
        offset_finder: OffsetFinder | None = None,
    ) -> None:
        self.runner: FFmpegRunner = runner or SubprocessRunner(quiet=True)
        self.prober = prober
        self.offset_finder = offset_finder

    # ---------- o alvo ----------

    def plan(self, project: Project, target: str) -> HeardPlan:
        """O plano do alvo, ou `TargetError` dizendo por que ele não tem som para mostrar."""
        layout = project_layout(project, self.prober, self.offset_finder, MissingMedia.scan(project))
        item = resolve_item(project, layout, target, prober=self.prober, runner=self.runner)
        return self._plan_item(target, item)

    def _plan_item(self, target: str, item: ItemAudio) -> HeardPlan:
        processed = bool(active_effects(item.effects))
        if item.whole_file:
            # o arquivo inteiro depois da cadeia: com o esticamento até o andamento do projeto (ou um Mudar Andamento) ele
            # dura outra coisa, e o painel mostra o som que o render toca
            duration, origin = chain_duration(item.effects, item.file_duration), item.offset
        else:
            duration, origin = chain_duration(item.effects, item.duration), 0.0
        rate = self.prober(item.path).sample_rate or 48000
        channels = MAX_CHANNELS  # sempre estéreo: o leitor mostra o mono nos dois canais, como a mixagem
        if processed:
            source: object = EffectProcessor(self.runner).key(self._audio_item(item))
        else:
            source = (
                str(item.path),
                _stamp(item.path),
                item.stream,
                0.0 if item.whole_file else round(item.offset, 3),
            )
        key = cache_key(PANEL_VERSION, PYRAMID_VERSION, source, round(duration, 3), rate, channels)
        return HeardPlan(target, item, duration, origin, processed, key, rate, channels)

    @staticmethod
    def _audio_item(item: ItemAudio) -> AudioItem:
        """O item como o `EffectProcessor` o recebe: o arquivo inteiro na música e na faixa externa, o trecho nos outros."""
        if item.whole_file:
            return AudioItem(item.path, item.file_duration, item.effects, 0.0, item.stream)
        return AudioItem(item.path, item.duration, item.effects, item.offset, item.stream)

    # ---------- ler ----------

    def processed_file(self, plan: HeardPlan, *, create: bool) -> Path | None:
        """O arquivo processado do item. Com `create` falso devolve None se ele ainda não existe (não processa)."""
        processor = EffectProcessor(self.runner)
        audio_item = self._audio_item(plan.item)
        if not create:
            path = processor.cache_dir / f"{processor.key(audio_item)}.wav"
            return path if path.exists() else None
        done = processor.process(audio_item)
        return done.path if done else None

    def reader(self, plan: HeardPlan, *, create: bool = True) -> SampleReader | None:
        """O leitor do som do alvo como ele soa. Com `create` falso devolve None se os efeitos ainda não foram
        processados (nada é processado)."""
        if plan.processed:
            path = self.processed_file(plan, create=create)
            if path is None:
                return None
            return open_reader(self.runner, path, prober=self.prober, stream=0, base=0.0)
        base = 0.0 if plan.item.whole_file else plan.item.offset
        return open_reader(
            self.runner, plan.item.path, prober=self.prober, stream=plan.item.stream, base=base
        )

    # ---------- tocar ----------

    def window_wav(
        self, plan: HeardPlan, start: float, end: float, reader: SampleReader | None = None
    ) -> tuple[bytes, float]:
        """O trecho [start, end) do alvo como um WAV de 16 bits, com o ganho (volume) do item. Devolve também quantos
        segundos o WAV tem (o fim do áudio corta a janela)."""
        stop = min(end, plan.duration)
        if start < 0 or stop <= start:
            raise AudioPanelError(
                f"a janela de {start:g} a {end:g} s não cabe no áudio (que dura {plan.duration:g} s)"
            )
        if stop - start > MAX_WINDOW_SECONDS:
            raise AudioPanelError(f"a janela passa de {MAX_WINDOW_SECONDS:g} s: peça pedaços menores")
        reader = reader or self.reader(plan)
        assert reader is not None
        samples = reader.read(start, stop - start)
        if plan.item.gain != 1.0:
            samples = samples * np.float32(plan.item.gain)
        return wav_bytes(samples, reader.rate), stop - start

    # ---------- prova de efeito ----------

    def preview(
        self, project: Project, target: str, effect: dict[str, Any], start: float, end: float
    ) -> tuple[HeardPlan, float, bool, str]:
        """O alvo com o `effect` proposto ao fim da cadeia, sem gravar nada, e a janela [start, end) dele para tocar.
        Devolve o plano a ler, o quanto a janela anda no plano (0 quando é o item inteiro), se a prévia é exata e um
        aviso quando não é. O item curto é processado inteiro (como o render, em cache); o longo, só um trecho em volta."""
        try:
            proposed = apply_effect_op(project, {"action": "add", "target": target, "effect": effect})
        except EditError as exc:
            raise AudioPanelError(str(exc)) from exc
        plan = self.plan(proposed, target)
        chain = plan.item.effects
        moves_time = any(e.alters_duration() or e.reorders_time for _, e in active_effects(chain))
        if plan.duration <= PREVIEW_FULL_LIMIT:
            return plan, 0.0, True, ""
        if moves_time:
            if plan.duration > PREVIEW_LONGEST:
                raise AudioPanelError(
                    "este efeito muda a duração ou a ordem do som, e o item é longo demais para a prévia: "
                    "selecione um trecho menor e aplique, ou use um item mais curto"
                )
            return plan, 0.0, True, ""
        return self._excerpt(plan, start, end)

    def _excerpt(self, plan: HeardPlan, start: float, end: float) -> tuple[HeardPlan, float, bool, str]:
        """O plano de um trecho em volta de [start, end): a cadeia entra com os intervalos deslocados e o trecho é
        processado sozinho. É exato quando todo efeito que mede o sinal tem o intervalo dentro do trecho."""
        first = max(start - PREVIEW_PAD, 0.0)
        last = min(end + PREVIEW_PAD, plan.duration)
        rebased: list[EffectBase] = []
        exact = True
        for effect in plan.item.effects:
            if not effect.enabled:
                continue
            moved = effect.rebased(first, last - first)
            if effect.needs_measure() and (
                effect.start is None
                or effect.end is None
                or effect.start < first - 1e-6
                or effect.end > last + 1e-6
            ):
                exact = False
            if moved is not None:
                rebased.append(moved)
        item = plan.item
        excerpt = replace(
            item,
            offset=first if item.whole_file else item.offset + first,
            duration=last - first,
            effects=tuple(rebased),
            whole_file=False,
            file_duration=0.0,
        )
        sub = self._plan_item(plan.target, excerpt)
        note = (
            ""
            if exact
            else (
                "Prévia aproximada: o efeito mede o som do item inteiro e aqui só viu o trecho em volta da janela. "
                "Marque um trecho (a medida passa a ser a dele) para a prévia ficar igual ao render."
            )
        )
        return replace(sub, origin=0.0), first, exact, note


# ---------- a resposta da onda ----------


def wave_payload(
    plan: HeardPlan,
    build: PyramidBuild | None,
    reader: SampleReader | None,
    start: float,
    end: float,
    columns: int,
) -> dict[str, Any]:
    """A resposta da onda para a janela [start, end): os mínimos e máximos de cada coluna, por canal, em inteiros de
    -127 a 127 (o valor 1,0 é 127), e as amostras de verdade quando a janela é pequena. `ready_until` diz até onde a
    pirâmide já foi construída (o resto vem zerado e a tela pede de novo)."""
    start = max(start, 0.0)
    end = min(end, plan.duration)
    pyramid = build.snapshot() if build is not None else None
    rate = reader.rate if reader is not None else (pyramid.rate if pyramid else plan.rate)
    channels = reader.channels if reader is not None else (pyramid.channels if pyramid else plan.channels)
    ready_until = plan.duration
    state = "ready"
    if build is not None and build.state != "ready":
        state = build.state
        ready_until = (pyramid.frames / pyramid.rate) if pyramid else 0.0
    payload: dict[str, Any] = {
        "target": plan.target,
        "label": plan.item.label,
        # o que identifica o som: muda com um efeito, um corte ou a troca do arquivo, e a tela esquece os blocos baixados
        "key": plan.key,
        "gain": plan.item.gain,
        "state": state,
        "percent": build.percent if build is not None else 100,
        "stage": build.label if build is not None else "",
        "error": build.error if build is not None else None,
        "duration": round(plan.duration, 6),
        "origin": round(plan.origin, 6),
        "rate": rate,
        "channels": channels,
        "frames": int(round(plan.duration * rate)),
        "clock": None
        if plan.clock is None
        else {"start": round(plan.clock.start, 6), "speed": plan.clock.speed},
        "notes": list(plan.item.notes),
        "start": round(start, 6),
        "end": round(end, 6),
        "columns": columns,
        "ready_until": round(min(ready_until, plan.duration), 6),
    }
    if end <= start or columns <= 0:
        return {**payload, "mode": "peaks", "mins": [], "maxs": []}
    peaks = pyramid.window(start, end, columns) if pyramid is not None else None
    samples: np.ndarray | None = None
    if peaks is not None:
        low, high = peaks
        mode = "peaks"
    elif reader is not None:
        window = reader.read(start, end - start)
        low, high = sample_columns(window, columns)
        samples = window if window.shape[0] <= columns * SAMPLES_PER_COLUMN else None
        mode = "samples" if samples is not None else "raw"
    else:  # os efeitos ainda estão sendo processados: sem som para ler, a tela espera
        zeros = [[0] * columns for _ in range(channels)]
        return {**payload, "mode": "peaks", "mins": zeros, "maxs": zeros}
    payload.update(mode=mode, mins=quantize(low).T.tolist(), maxs=quantize(high).T.tolist())
    if samples is not None:
        payload["samples"] = np.round(samples.T, 5).tolist()
    return payload


# ---------- construção em segundo plano ----------


class _StageSink:
    """Leva o andamento do ffmpeg (a etapa de efeitos) para o estado da construção."""

    def __init__(self, build: PyramidBuild) -> None:
        self.build = build
        self.total: float | None = None

    def start(self, label: str, total: float | None) -> None:
        self.total = total
        self.build.percent = 0

    def update(self, done: float) -> None:
        if self.total:
            self.build.percent = int(min(done / self.total, 1.0) * 100)

    def finish(self) -> None:
        self.build.percent = 100


class PeakTasks:
    """As construções de picos em andamento, uma por chave. Só uma roda por vez: construir lê o áudio inteiro e
    disputaria o disco e o ffmpeg com a outra e com o render."""

    def __init__(self, cache_dir: Callable[[], Path] | None = None) -> None:
        self._builds: OrderedDict[str, PyramidBuild] = OrderedDict()
        self._lock = threading.Lock()
        self._slot = threading.Semaphore(1)
        self._cache_dir = cache_dir or (lambda: config.WAVEFORM_DIR)

    def path(self, key: str) -> Path:
        return self._cache_dir() / f"pyr-{key}.npz"

    def request(
        self, make_service: Callable[[FFmpegRunner], AudioPanelService], plan: HeardPlan
    ) -> PyramidBuild:
        """A construção da chave: já pronta (cache em disco), em andamento ou recém-iniciada."""
        with self._lock:
            known = self._builds.get(plan.key)
            if known is not None and known.state != "failed":
                self._builds.move_to_end(plan.key)
                return known
            cached = load_pyramid(self.path(plan.key))
            if cached is not None:
                build = PyramidBuild(plan.key, plan, "ready", percent=100, pyramid=cached)
                build.done.set()
                self._remember(plan.key, build)
                return build
            build = PyramidBuild(plan.key, plan, label="Preparando a onda")
            self._remember(plan.key, build)
        threading.Thread(
            target=self._run, args=(build, make_service), daemon=True, name=f"dmaker-onda-{plan.key}"
        ).start()
        return build

    def _remember(self, key: str, build: PyramidBuild) -> None:
        self._builds[key] = build
        while len(self._builds) > 24:
            self._builds.popitem(last=False)

    def _run(self, build: PyramidBuild, make_service: Callable[[FFmpegRunner], AudioPanelService]) -> None:
        with self._slot:
            try:
                # o andamento do ffmpeg só vale para a etapa de efeitos: a decodificação em pedaços da etapa seguinte
                # roda vários comandos ao mesmo tempo e cada um zeraria o andamento da construção
                staging = make_service(SubprocessRunner(sink=_StageSink(build)))
                if build.plan.processed and staging.processed_file(build.plan, create=False) is None:
                    build.label = "Aplicando os efeitos"
                    staging.processed_file(build.plan, create=True)
                reader = make_service(SubprocessRunner(quiet=True)).reader(build.plan)
                assert reader is not None
                build.label = "Calculando a onda"
                build.percent = 0
                accumulator = BlockAccumulator(reader.channels)
                build.accumulator, build.reader = accumulator, reader
                duration = build.plan.duration
                pyramid = build_pyramid(
                    reader,
                    duration,
                    accumulator=accumulator,
                    on_progress=lambda seconds: setattr(
                        build, "percent", int(min(seconds / max(duration, 1e-9), 1) * 100)
                    ),
                    should_stop=build.stop.is_set,
                )
                if not build.stop.is_set():
                    save_pyramid(self.path(build.key), pyramid)
                build.pyramid = pyramid
                build.percent = 100
                build.state = "ready"
            except Exception as exc:  # noqa: BLE001 - o erro vai para quem consulta o estado
                build.error = f"{type(exc).__name__}: {exc}"
                build.state = "failed"
            finally:
                build.done.set()


# ---------- planos em memória ----------


class PlanCache:
    """Os planos já resolvidos: abrir um alvo sonda os arquivos, e a tela pede a onda de novo a cada passo de zoom.
    A chave é a spec inteira (editada ou não) mais o alvo, então editar o projeto sempre refaz o plano. Guarda também
    o leitor de cada som (abrir um arquivo comprimido consulta o ffprobe, e a tela faz dezenas de pedidos por segundo)."""

    def __init__(self, size: int = 16) -> None:
        self._plans: OrderedDict[tuple[str, str], HeardPlan] = OrderedDict()
        self._readers: OrderedDict[str, SampleReader] = OrderedDict()
        self._lock = threading.Lock()
        self.size = size

    def reader(self, plan: HeardPlan, make: Callable[[], SampleReader | None]) -> SampleReader | None:
        """O leitor do som do plano: o guardado ou o que `make` abrir. Só guarda quando `make` devolve um (o arquivo
        tratado de um item com efeitos pode ainda não existir)."""
        with self._lock:
            known = self._readers.get(plan.key)
            if known is not None:
                self._readers.move_to_end(plan.key)
                return known
        opened = make()
        if opened is not None:
            with self._lock:
                self._readers[plan.key] = opened
                while len(self._readers) > self.size * 2:
                    self._readers.popitem(last=False)
        return opened

    def get(self, project: Project, target: str, make: Callable[[], HeardPlan]) -> HeardPlan:
        digest = hashlib.sha1(project.model_dump_json(exclude_none=True).encode("utf-8")).hexdigest()
        key = (digest, target)
        with self._lock:
            known = self._plans.get(key)
            if known is not None and known.item.path.exists():
                self._plans.move_to_end(key)
                return known
        plan = make()
        with self._lock:
            self._plans[key] = plan
            while len(self._plans) > self.size:
                self._plans.popitem(last=False)
        return plan


__all__ = [
    "MAX_WINDOW_SECONDS",
    "AudioPanelError",
    "AudioPanelService",
    "HeardPlan",
    "PeakTasks",
    "PlanCache",
    "PyramidBuild",
    "TargetError",
    "wave_payload",
]
