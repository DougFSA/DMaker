"""Aplicar uma macro de áudio a uma pasta de arquivos: cada arquivo passa pela cadeia da macro e sai no formato escolhido.

É o "Apply Macro to Files" do Audacity, pelo mesmo caminho do render de áudio (DMK-64): cada arquivo vira, na memória, um
projeto só de áudio com o arquivo como voz gravada (`audio.voiceover`) levando a cadeia da macro, e o `AudioExporter`
grava a mixagem. Assim o som é o do render, e a cadeia é a que a pessoa também poria no item (cada efeito já conhece o
próprio limite: o que muda a duração, o que trabalha sobre as amostras).

**Nada além do que a macro pede.** O projeto temporário sai com `audio.normalize = "off"`: o render de áudio não faz a
normalização final do master, então o nível do arquivo é o que a cadeia deu (uma macro sem `loudness_normalize` nem
`normalize` entrega o arquivo no nível em que entrou). Sem música, sem narração e sem marcadores: só a voz e a cadeia.

**Retomada.** O estado vive na pasta de saída (`.dmaker-macro/macro.json`), no mesmo formato do lote de vídeos
(`batch_state`): uma linha por arquivo, gravada depois de cada um, e a trava de arquivo (`filelock`) diz se outro
processo ainda roda. Cada arquivo é gravado como `nome.parcial.ext` e só vira `nome.ext` quando o ffmpeg termina, então um
arquivo pela metade nunca passa por pronto. `resume` pula as linhas prontas cuja impressão digital (a cadeia, o formato e o
arquivo de entrada, com tamanho e data) não mudou e cujo resultado ainda está lá; as outras são refeitas.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..domain.audio_effects import EffectPreset
from ..domain.audio_effects.macro_output import output_choices
from ..domain.audio_presets import AudioPreset, EncodingChoices, get_audio_preset, is_audio_preset
from ..domain.spec import AudioSettings, Output, Project, VoiceoverClip
from ..media.ffmpeg import FFmpegError, FFmpegRunner, ProgressSink, SubprocessRunner
from ..media.probe import probe
from .audio_lint import NORMALIZE_OFF_WARNING
from .audio_service import export_request
from .batch_report import BatchReport, build_report
from .batch_state import (
    BATCH_FINISHED,
    BATCH_PAUSED,
    DONE,
    FAILED,
    PENDING,
    RUNNING,
    Batch,
    BatchRow,
    BatchStore,
)
from .context import Prober, RenderOptions
from .filelock import FileLock
from .jobs import Job, stage_progress

STATE_FOLDER = ".dmaker-macro"
STATE_NAME = "macro"
REPORT_FILE = "relatorio.txt"
PARTIAL_MARK = ".parcial"
NOUN = "arquivo"
LOCK_ATTEMPTS = 5  # quem só olha o estado segura a trava por um instante; vale tentar de novo
LOCK_WAIT_SECONDS = 0.05
# o que a pasta de entrada entrega: arquivos de som comuns (o vídeo fica de fora; um arquivo dado por nome vale qualquer um)
AUDIO_EXTENSIONS = frozenset(
    {".wav", ".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".aiff", ".aif", ".wma", ".webm"}
)

ProgressFn = Callable[[str, float], None]  # etapa em texto e fração do trabalho (0 a 1)


class MacroRunError(ValueError):
    """Pedido que não dá para atender (nada na pasta, formato que falta, saída em cima da entrada)."""


class MacroRunBusyError(RuntimeError):
    """Já há um trabalho desta macro rodando nesta pasta de saída, neste ou em outro processo."""


@dataclass(frozen=True)
class FileOutcome:
    """O que o render de um arquivo devolve: onde ficou, quanto dura e o que se pode dizer dele."""

    output: Path
    duration_s: float
    size_mb: float
    warnings: list[str]


class MacroFileRenderer(Protocol):
    def render(
        self,
        source: Path,
        effects: Sequence[dict],
        out: Path,
        preset: AudioPreset,
        choices: EncodingChoices | None,
        *,
        sink: ProgressSink | None,
        log: Callable[[str], None],
    ) -> FileOutcome: ...


def _subprocess_runner(sink: ProgressSink | None) -> FFmpegRunner:
    return SubprocessRunner(sink=sink) if sink else SubprocessRunner(quiet=True)


def file_project(source: Path, effects: Sequence[dict], preset: AudioPreset, key: str) -> Project:
    """O projeto só de áudio de um arquivo: ele como voz gravada, com a cadeia da macro e sem normalização do master."""
    clip = VoiceoverClip.model_validate({"src": str(source), "effects": [dict(effect) for effect in effects]})
    return Project(
        name=f"macro-{key}",
        output=Output(preset=preset.id),
        audio=AudioSettings(normalize="off", voiceover=[clip]),
        timeline=[],
    )


class PipelineFileRenderer:
    """Renderiza cada arquivo com o mesmo `AudioExporter` do `dmaker audio export`; runner e probe são injetáveis."""

    def __init__(
        self,
        prober: Prober = probe,
        runner_factory: Callable[[ProgressSink | None], FFmpegRunner] = _subprocess_runner,
    ) -> None:
        self.prober = prober
        self.runner_factory = runner_factory

    def render(
        self,
        source: Path,
        effects: Sequence[dict],
        out: Path,
        preset: AudioPreset,
        choices: EncodingChoices | None,
        *,
        sink: ProgressSink | None,
        log: Callable[[str], None],
    ) -> FileOutcome:
        from .audio_export import AudioExporter
        from .audio_service import build_pipeline

        key = hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:8]
        project = file_project(source, effects, preset, key)
        project.base_dir = source.parent
        pipeline = build_pipeline(
            project,
            preset.id,
            choices=choices,
            options=RenderOptions(quiet=True),
            runner=self.runner_factory(sink),
            prober=self.prober,
            log=log,
        )
        result = AudioExporter(pipeline).run(export_request("mix"), out=out)
        written = result.files[0]
        return FileOutcome(
            out,
            written.duration,
            out.stat().st_size / 1e6 if out.exists() else 0.0,
            [warning for warning in result.warnings if warning != NORMALIZE_OFF_WARNING],  # é de propósito
        )


# ---------- o plano ----------


def expand_inputs(inputs: Sequence[str | Path]) -> list[Path]:
    """Os arquivos de entrada: cada pasta dá os arquivos de som dela (sem entrar nas subpastas, em ordem de nome) e cada
    caminho de arquivo vale como está. Repetidos saem uma vez; um caminho que não existe, ou uma pasta sem som, é erro."""
    files: list[Path] = []
    for raw in inputs:
        path = Path(raw).expanduser()
        if path.is_dir():
            found = sorted(
                (
                    item
                    for item in path.iterdir()
                    if item.is_file() and item.suffix.lower() in AUDIO_EXTENSIONS
                ),
                key=lambda item: item.name.lower(),
            )
            if not found:
                raise MacroRunError(
                    f"a pasta {path} não tem arquivos de áudio ({', '.join(sorted(AUDIO_EXTENSIONS))})"
                )
            files += found
        elif path.is_file():
            files.append(path)
        else:
            raise MacroRunError(f"não encontrei {path}")
    unique = list(dict.fromkeys(item.resolve() for item in files))
    if not unique:
        raise MacroRunError("informe a pasta ou os arquivos de áudio a tratar")
    return unique


def unique_names(stems: Sequence[str]) -> list[str]:
    """Os nomes de saída sem repetição entre si, sem diferenciar maiúscula (o Windows não diferencia): o repetido ganha
    -2, -3... (`voz.wav` e `voz.mp3` na entrada dão `voz` e `voz-2` na saída)."""
    used: set[str] = set()
    names: list[str] = []
    for stem in stems:
        candidate, number = stem, 1
        while candidate.lower() in used:
            number += 1
            candidate = f"{stem}-{number}"
        used.add(candidate.lower())
        names.append(candidate)
    return names


@dataclass(frozen=True)
class MacroRun:
    """O que vai ser feito: a macro, os arquivos, o formato e onde cada resultado cai."""

    macro: EffectPreset
    sources: tuple[Path, ...]
    out_dir: Path
    preset: AudioPreset
    choices: EncodingChoices | None
    names: tuple[str, ...]

    def output_path(self, index: int) -> Path:
        return self.out_dir / f"{self.names[index]}{self.preset.extension}"

    def outputs(self) -> list[Path]:
        return [self.output_path(index) for index in range(len(self.sources))]


def choose_format(macro: EffectPreset, requested: str | None) -> tuple[AudioPreset, EncodingChoices | None]:
    """O formato de saída: o pedido (`mp3`, `audio/flac`...) ou, sem ele, o da macro. As escolhas de codificação da macro
    só valem no formato dela (24 bits do WAV não fazem sentido num MP3 que a pessoa pediu no lugar)."""
    own = (macro.output or {}).get("preset")
    name = requested or own
    if not name:
        raise MacroRunError(
            f"a macro {macro.label!r} não traz formato de saída: informe o formato (mp3, wav, flac, ogg, opus, m4a ou aiff)"
        )
    if not is_audio_preset(name):
        raise MacroRunError(
            f"formato de áudio desconhecido: {name!r} (use mp3, wav, flac, ogg, opus, m4a ou aiff)"
        )
    preset = get_audio_preset(name)
    same = own is not None and get_audio_preset(own).id == preset.id
    return preset, output_choices(macro.output) if same else None


def plan_macro_run(
    macro: EffectPreset, inputs: Sequence[str | Path], out_dir: str | Path, format: str | None = None
) -> MacroRun:
    """Confere o pedido inteiro antes de gravar qualquer coisa. Recusa a saída que cairia em cima de um arquivo de entrada:
    o original nunca é sobrescrito."""
    if not macro.effects:
        raise MacroRunError(f"a macro {macro.label!r} não tem efeitos")
    sources = expand_inputs(inputs)
    preset, choices = choose_format(macro, format)
    folder = Path(out_dir).expanduser().resolve()
    names = unique_names([item.stem for item in sources])
    plan = MacroRun(macro, tuple(sources), folder, preset, choices, tuple(names))
    originals = set(sources)
    clash = [path for path in plan.outputs() if path.resolve() in originals]
    if clash:
        raise MacroRunError(
            f"a saída {clash[0]} é o próprio arquivo de entrada: escolha outra pasta de saída (o original não é sobrescrito)"
        )
    return plan


def row_signature(plan: MacroRun, index: int) -> str:
    """A impressão digital do que vira o arquivo: a cadeia, o formato com as escolhas e o arquivo de entrada (tamanho e
    data). Igual à da última vez, com o resultado ainda lá, o arquivo não é refeito."""
    source = plan.sources[index]
    info = source.stat()
    payload = {
        "effects": [dict(effect) for effect in plan.macro.effects],
        "preset": plan.preset.id,
        "choices": dict(plan.choices.__dict__) if plan.choices else None,
        "source": str(source),
        "size": info.st_size,
        "mtime": info.st_mtime_ns,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]


class _FileSink:
    """ProgressSink que conta cada comando do ffmpeg como uma etapa do arquivo em andamento."""

    def __init__(self, report: Callable[[str], None]) -> None:
        self._report = report
        self._label = ""
        self._total: float | None = None
        self._last = -1

    def start(self, label: str, total: float | None) -> None:
        self._label, self._total, self._last = label, total, -1
        self._report(label)

    def update(self, done: float) -> None:
        if not self._total:
            return
        percent = int(min(done / self._total, 1.0) * 100)
        if percent != self._last:  # um aviso por ponto percentual, não um por quadro
            self._last = percent
            self._report(f"{self._label} {percent}%")

    def finish(self) -> None:
        return None


def _short_error(exc: BaseException) -> str:
    """Motivo da falha numa linha: a primeira frase e, no ffmpeg, a última linha que ele escreveu."""
    first = str(exc.args[0] if exc.args else exc).strip().splitlines()[0] if str(exc).strip() else ""
    message = f"{type(exc).__name__}: {first}" if first else type(exc).__name__
    if isinstance(exc, FFmpegError):
        tail = [line for line in exc.stderr.strip().splitlines() if line.strip()]
        if tail:
            message += f" ({tail[-1].strip()})"
    return message


class MacroRunService:
    """Roda uma `MacroRun` arquivo por arquivo, com estado em disco, trava e retomada."""

    def __init__(self, renderer: MacroFileRenderer | None = None, prober: Prober = probe) -> None:
        self.renderer = renderer or PipelineFileRenderer(prober)

    # ---------- estado ----------

    @staticmethod
    def store(out_dir: Path) -> BatchStore:
        return BatchStore(out_dir / STATE_FOLDER)

    def _fresh_batch(self, plan: MacroRun) -> Batch:
        rows = [
            BatchRow(
                index=position,
                line=position,
                title=source.name,
                slug=plan.names[position - 1],
                project=None,
                signature=row_signature(plan, position - 1),
                source=str(source),
            )
            for position, source in enumerate(plan.sources, start=1)
        ]
        return Batch(
            name=STATE_NAME,
            template=plan.macro.id,
            sheet=None,
            name_column=None,
            preset=plan.preset.id,
            noun=NOUN,
            rows=rows,
        )

    def _carry_over(self, fresh: Batch, earlier: Batch | None) -> None:
        """Na retomada, o que já saiu inteiro (mesma impressão digital, arquivo ainda lá) continua pronto."""
        if earlier is None:
            return
        done = {row.source: row for row in earlier.rows if row.state == DONE and row.output}
        for row in fresh.rows:
            before = done.get(row.source)
            if before and before.signature == row.signature and Path(before.output or "").is_file():
                row.state, row.output = DONE, before.output
                row.duration_s, row.size_mb, row.render_s = before.duration_s, before.size_mb, before.render_s
                row.warnings, row.started_at, row.finished_at = (
                    list(before.warnings),
                    before.started_at,
                    before.finished_at,
                )

    def planned_outputs(self, plan: MacroRun, resume: bool) -> list[Path]:
        """Os arquivos que uma execução gravaria: o que o agente confere antes de sobrescrever (ele pergunta pelos que já
        existem). Na retomada, o que o estado já tem por pronto não é gravado de novo e não conta."""
        kept: set[str] = set()
        if resume and self.store(plan.out_dir).exists(STATE_NAME):
            try:
                earlier = self.store(plan.out_dir).load(STATE_NAME)
            except (KeyError, RuntimeError):
                earlier = None
            if earlier is not None:
                fresh = self._fresh_batch(plan)
                self._carry_over(fresh, earlier)
                kept = {row.output for row in fresh.rows if row.state == DONE and row.output}
        return [path for path in plan.outputs() if str(path) not in kept]

    def active(self, out_dir: Path) -> bool:
        """A macro está rodando agora nesta pasta (neste ou em outro processo): a trava está tomada."""
        probe_lock = FileLock(self.store(out_dir).lock_path(STATE_NAME))
        if probe_lock.try_acquire():
            probe_lock.release()
            return False
        return True

    def report(self, out_dir: str | Path) -> BatchReport:
        """O estado da pasta de saída: o que saiu, o que falhou e o que espera."""
        folder = Path(out_dir).expanduser().resolve()
        batch = self.store(folder).load(STATE_NAME)
        status = "running" if self.active(folder) else self._status_after(batch)
        return build_report(batch, status, folder)

    @staticmethod
    def _status_after(batch: Batch) -> str:
        waiting = any(row.state in (PENDING, RUNNING) for row in batch.rows)
        return BATCH_PAUSED if waiting else BATCH_FINISHED

    # ---------- execução ----------

    @staticmethod
    def _acquire(lock: FileLock) -> bool:
        for attempt in range(LOCK_ATTEMPTS):
            if lock.try_acquire():
                return True
            if attempt < LOCK_ATTEMPTS - 1:
                time.sleep(LOCK_WAIT_SECONDS)
        return False

    def run(
        self,
        plan: MacroRun,
        *,
        resume: bool = False,
        should_stop: Callable[[], bool] | None = None,
        progress: ProgressFn | None = None,
        log: Callable[[str], None] | None = None,
    ) -> BatchReport:
        """Trata o que falta e devolve o relatório, mesmo que tenha parado no meio. Sem `resume`, tudo é refeito (o estado
        anterior da pasta é descartado); com `resume`, o que já saiu inteiro não é refeito."""
        log = log or (lambda message: None)
        progress = progress or (lambda label, fraction: None)
        stop = should_stop or (lambda: False)
        plan.out_dir.mkdir(parents=True, exist_ok=True)
        store = self.store(plan.out_dir)
        lock = FileLock(store.lock_path(STATE_NAME))
        if not self._acquire(lock):
            raise MacroRunBusyError(
                f"já há um tratamento rodando em {plan.out_dir} (em outra janela ou processo)"
            )
        try:
            earlier = None
            if resume and store.exists(STATE_NAME):
                try:
                    earlier = store.load(STATE_NAME)
                except (KeyError, RuntimeError):
                    log("o estado anterior não pôde ser lido: tudo será refeito")
            batch = self._fresh_batch(plan)
            self._carry_over(batch, earlier)
            store.clear_pause(STATE_NAME)
            store.save(batch)
            todo = [row for row in batch.rows if row.state != DONE]
            skipped = len(batch.rows) - len(todo)
            if skipped:
                log(f"{skipped} arquivo(s) já estavam prontos e não serão refeitos")
            log(f"{len(todo)} arquivo(s) a tratar" if todo else "Nada a tratar: tudo já está pronto")
            try:
                self._run_rows(plan, store, todo, stop, progress, log)
            finally:
                self._write_report(plan, store)
            final = store.load(STATE_NAME)
            return build_report(final, self._status_after(final), plan.out_dir)
        finally:
            lock.release()

    def _run_rows(
        self,
        plan: MacroRun,
        store: BatchStore,
        todo: list[BatchRow],
        stop: Callable[[], bool],
        progress: ProgressFn,
        log: Callable[[str], None],
    ) -> None:
        for row in todo:
            if stop() or store.pause_requested(STATE_NAME):
                log("Tratamento pausado. Retome com resume: o que já saiu não é refeito")
                return
            self._run_row(plan, store, row.index, progress, log)

    def _run_row(
        self, plan: MacroRun, store: BatchStore, index: int, progress: ProgressFn, log: Callable[[str], None]
    ) -> None:
        batch = store.load(STATE_NAME)
        row = batch.row(index)
        total = len(batch.rows)
        finished = sum(1 for other in batch.rows if other.state == DONE)
        prefix = f"Arquivo {finished + 1} de {total}: {row.title}"

        def report(detail: str) -> None:
            progress(f"{prefix} · {detail}" if detail else prefix, finished / total)

        report("")
        log(prefix)
        started = time.time()
        store.change(STATE_NAME, lambda b: self._begin(b.row(index), started))
        out = plan.output_path(index - 1)
        partial = out.with_name(f"{out.stem}{PARTIAL_MARK}{out.suffix}")
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            partial.unlink(missing_ok=True)
            outcome = self.renderer.render(
                Path(row.source or ""),
                plan.macro.effects,
                partial,
                plan.preset,
                plan.choices,
                sink=_FileSink(report),
                log=log,
            )
            os.replace(partial, out)  # só agora o arquivo existe com o nome final
        except KeyboardInterrupt:  # Ctrl+C: a linha volta para a fila e a retomada a refaz
            partial.unlink(missing_ok=True)
            store.change(STATE_NAME, lambda b: self._reset(b.row(index)))
            raise
        except Exception as exc:  # noqa: BLE001 - o motivo vai para a linha e para o relatório
            partial.unlink(missing_ok=True)
            message = _short_error(exc)
            store.change(STATE_NAME, lambda b: self._fail(b.row(index), message, started))
            log(f"Falhou: {row.title}: {message}")
            return
        store.change(STATE_NAME, lambda b: self._finish(b.row(index), outcome, out, started))
        log(f"Pronto: {row.title} ({time.time() - started:.0f} s)")

    @staticmethod
    def _begin(row: BatchRow, started: float) -> None:
        row.state, row.error, row.started_at, row.finished_at = RUNNING, None, started, None

    @staticmethod
    def _reset(row: BatchRow) -> None:
        row.state, row.started_at = PENDING, None

    @staticmethod
    def _fail(row: BatchRow, message: str, started: float) -> None:
        row.state, row.error, row.finished_at = FAILED, message, time.time()
        row.render_s = round(row.finished_at - started, 1)

    @staticmethod
    def _finish(row: BatchRow, outcome: FileOutcome, out: Path, started: float) -> None:
        row.state, row.error, row.finished_at = DONE, None, time.time()
        row.output = str(out)
        row.duration_s, row.size_mb = round(outcome.duration_s, 2), round(outcome.size_mb, 2)
        row.render_s, row.warnings = round(row.finished_at - started, 1), list(outcome.warnings)

    @staticmethod
    def _write_report(plan: MacroRun, store: BatchStore) -> None:
        """Deixa o relatório ao lado dos arquivos; falhar em gravá-lo não pode derrubar o trabalho."""
        try:
            batch = store.load(STATE_NAME)
            report = build_report(batch, MacroRunService._status_after(batch), plan.out_dir)
            (plan.out_dir / REPORT_FILE).write_text(report.to_text() + "\n", encoding="utf-8")
        except OSError:
            return

    def pause(self, out_dir: str | Path) -> None:
        """Pede para o tratamento parar depois do arquivo em andamento (vale também para outro processo)."""
        self.store(Path(out_dir).expanduser().resolve()).request_pause(STATE_NAME)


def run_in_job(service: MacroRunService, plan: MacroRun, job: Job, *, resume: bool = False) -> dict:
    """A macro ligada a um job (MCP): log e andamento viram eventos, e cancelar o job pausa o tratamento."""
    report = service.run(
        plan,
        resume=resume,
        should_stop=lambda: job.cancel_requested,
        progress=stage_progress(job),
        log=job.log,
    )
    return report.to_dict()
