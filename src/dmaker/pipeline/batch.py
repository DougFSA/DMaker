"""Serviço do lote: vários vídeos de uma planilha, um por linha, sobre um modelo de projeto.

Fluxo: `validate` confere a planilha inteira sem renderizar nada; `create` salva um projeto por linha válida
e o estado do lote; `run` renderiza as linhas uma a uma, grava o andamento depois de cada vídeo e, na
retomada, não refaz o que já saiu (mesma spec e arquivo de saída ainda lá). Pausar vale entre um vídeo e
outro. Se o processo cair no meio de um, a linha volta a pendente na próxima execução.

É o que a CLI, o MCP e a interface usam, para os três mostrarem os mesmos números. O render de cada vídeo
entra por `RowRenderer` e o ffmpeg por trás dele pelo `FFmpegRunner`, então o teste roda sem ffmpeg.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from .. import config
from ..domain.batch_sheet import slugify, unique_slugs
from ..domain.spec import Project
from ..domain.templates import find_template
from ..media.ffmpeg import FFmpegError, FFmpegRunner, ProgressSink, SubprocessRunner
from ..media.probe import probe
from .batch_files import read_sheet
from .batch_report import BatchReport, build_report
from .batch_state import (
    BATCH_FINISHED,
    BATCH_PAUSED,
    BATCH_RUNNING,
    DONE,
    FAILED,
    INVALID,
    PENDING,
    RUNNING,
    Batch,
    BatchRow,
    BatchStore,
)
from .batch_validation import BatchValidation, validate_sheet
from .context import Prober, RenderOptions
from .filelock import FileLock
from .jobs import Job, stage_progress
from .projects import load_project, save_project
from .renderer import RenderPipeline
from .sync import OffsetFinder

REPORT_FILE = "relatorio.txt"
PREVIEW_SUFFIX = "__preview"
LOCK_ATTEMPTS = 5  # quem só olha o estado (a tela) segura a trava por um instante; vale tentar de novo
LOCK_WAIT_SECONDS = 0.05

ProgressFn = Callable[[str, float], None]  # etapa em texto e fração do lote (0 a 1)


class BatchError(ValueError):
    """Pedido de lote que não dá para atender (nome repetido, nada para rodar)."""


class BatchExistsError(BatchError):
    """Já existe um lote com esse nome."""


class BatchInvalidError(BatchError):
    """A planilha tem problemas que impedem o lote; `validation` diz quais."""

    def __init__(self, message: str, validation: BatchValidation) -> None:
        super().__init__(message)
        self.validation = validation


class BatchBusyError(RuntimeError):
    """O lote já está rodando, neste ou em outro processo."""


@dataclass(frozen=True)
class RowOutcome:
    """O que um render devolve ao lote: onde ficou o vídeo e o que se pode dizer dele."""

    output: Path
    duration_s: float
    size_mb: float
    warnings: list[str]


class RowRenderer(Protocol):
    def render(
        self,
        project: Project,
        out: Path,
        *,
        preview: bool,
        preset: str | None,
        sink: ProgressSink | None,
        log: Callable[[str], None],
    ) -> RowOutcome: ...


def _subprocess_runner(sink: ProgressSink | None) -> FFmpegRunner:
    return SubprocessRunner(sink=sink) if sink else SubprocessRunner(quiet=True)


class PipelineRenderer:
    """Renderiza cada vídeo com a mesma `RenderPipeline` do `dmaker render`; runner e probe são injetáveis."""

    def __init__(
        self,
        prober: Prober = probe,
        runner_factory: Callable[[ProgressSink | None], FFmpegRunner] = _subprocess_runner,
    ) -> None:
        self.prober = prober
        self.runner_factory = runner_factory

    def render(
        self,
        project: Project,
        out: Path,
        *,
        preview: bool,
        preset: str | None,
        sink: ProgressSink | None,
        log: Callable[[str], None],
    ) -> RowOutcome:
        options = RenderOptions(preview=preview, preset=preset, quiet=True, out=out)
        pipeline = RenderPipeline(
            project, options, runner=self.runner_factory(sink), prober=self.prober, log=log
        )
        result = pipeline.run()
        return RowOutcome(result.output, result.duration, result.size_bytes / 1e6, list(result.warnings))


class _RowSink:
    """ProgressSink que conta cada comando do ffmpeg como uma etapa do vídeo em andamento."""

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


def project_signature(project: Project, preview: bool, preset: str | None) -> str:
    """Impressão digital do que vai ser renderizado: a spec (sem depender de como o JSON foi formatado) e as
    opções do lote. Igual à da última vez com o vídeo ainda lá, o vídeo não é refeito."""
    payload = {
        "spec": json.loads(project.model_dump_json(exclude_none=True)),
        "preview": preview,
        "preset": preset,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]


def _short_error(exc: BaseException) -> str:
    """Motivo da falha numa linha: a primeira frase e, no ffmpeg, a última linha que ele escreveu."""
    first = str(exc.args[0] if exc.args else exc).strip().splitlines()[0] if str(exc).strip() else ""
    message = f"{type(exc).__name__}: {first}" if first else type(exc).__name__
    if isinstance(exc, FFmpegError):
        tail = [line for line in exc.stderr.strip().splitlines() if line.strip()]
        if tail:
            message += f" ({tail[-1].strip()})"
    return message


class BatchService:
    def __init__(
        self,
        store: BatchStore | None = None,
        renderer: RowRenderer | None = None,
        prober: Prober = probe,
        offset_finder: OffsetFinder | None = None,
    ) -> None:
        self.store = store or BatchStore()
        self.prober = prober
        self.renderer = renderer or PipelineRenderer(prober)
        self.offset_finder = offset_finder

    # ---------- entrada ----------

    def validate(
        self, template_name: str, sheet_path: Path | str, name_column: str | None = None
    ) -> BatchValidation:
        """Confere a planilha contra o modelo. Não renderiza nem grava nada."""
        sheet_path = Path(sheet_path)
        template = find_template(template_name)
        sheet = read_sheet(sheet_path)
        return validate_sheet(
            template,
            sheet,
            base_dir=str(sheet_path.resolve().parent),
            name_column=name_column,
            prober=self.prober,
            offset_finder=self.offset_finder,
        )

    def create(
        self,
        template_name: str,
        sheet_path: Path | str,
        *,
        name: str | None = None,
        name_column: str | None = None,
        preview: bool = False,
        preset: str | None = None,
        skip_invalid: bool = False,
        replace: bool = False,
    ) -> Batch:
        """Valida e salva o lote: um projeto por linha válida e o estado de cada linha. Linha com problema
        impede tudo, a não ser que `skip_invalid` mande seguir sem ela. Com `replace`, um lote de mesmo nome
        é refeito a partir da planilha atual, sem refazer o vídeo que continua igual."""
        sheet_path = Path(sheet_path)
        batch_name = slugify(name or sheet_path.stem, "lote")
        previous = self._previous(batch_name, replace)
        validation = self.validate(template_name, sheet_path, name_column)
        self._require_runnable(validation, skip_invalid)

        slugs = unique_slugs(
            [slugify(row.title, f"video-{row.index:02d}") for row in validation.rows],
        )
        taken = self._project_names() - {row.project for row in previous.rows if row.project}
        project_names = iter(unique_slugs([f"{batch_name}-{slug}" for slug in slugs], taken))
        carried = {row.slug: row for row in previous.rows if row.state == DONE}

        rows: list[BatchRow] = []
        for check, slug in zip(validation.rows, slugs, strict=True):
            project_name = next(project_names)
            row = BatchRow(
                check.index,
                check.line,
                check.title,
                slug,
                project_name if check.valid else None,
                PENDING if check.valid else INVALID,
                [issue.to_dict() for issue in check.issues],
            )
            if check.valid and check.spec is not None:
                save_project(Project.model_validate({**check.spec, "name": project_name}))
                self._carry_over(row, carried.get(slug))
            rows.append(row)
        batch = Batch(
            batch_name,
            validation.template,
            str(sheet_path.resolve()),
            validation.name_column,
            preview,
            preset,
            rows,
        )
        self.store.save(batch)
        return batch

    def _previous(self, batch_name: str, replace: bool) -> Batch:
        if not self.store.exists(batch_name):
            return Batch(batch_name, "", None, None)
        if not replace:
            raise BatchExistsError(
                f'Já existe o lote "{batch_name}". Retome-o, escolha outro nome ou peça para refazê-lo (replace).'
            )
        return self.store.load(batch_name)

    @staticmethod
    def _require_runnable(validation: BatchValidation, skip_invalid: bool) -> None:
        if validation.sheet_errors or not validation.valid_rows:
            raise BatchInvalidError("Nenhuma linha da planilha pode ser renderizada.", validation)
        if validation.invalid_rows and not skip_invalid:
            raise BatchInvalidError(
                f"{len(validation.invalid_rows)} linha(s) com problema. Corrija a planilha ou mande seguir "
                "sem elas (skip_invalid).",
                validation,
            )

    @staticmethod
    def _carry_over(row: BatchRow, earlier: BatchRow | None) -> None:
        """Vídeo que o lote anterior já fez com o mesmo nome continua valendo: a assinatura é conferida na hora de rodar."""
        if earlier is None:
            return
        row.state, row.output, row.signature = earlier.state, earlier.output, earlier.signature
        row.duration_s, row.size_mb, row.render_s = earlier.duration_s, earlier.size_mb, earlier.render_s
        row.warnings, row.finished_at = list(earlier.warnings), earlier.finished_at

    @staticmethod
    def _project_names() -> set[str]:
        if not config.PROJECTS_DIR.is_dir():
            return set()
        return {path.name for path in config.PROJECTS_DIR.iterdir() if path.is_dir()}

    # ---------- estado ----------

    def output_dir(self, name: str) -> Path:
        return config.OUTPUT_DIR / name

    def output_path(self, batch: Batch, row: BatchRow) -> Path:
        suffix = PREVIEW_SUFFIX if batch.preview else ""
        return self.output_dir(batch.name) / f"{row.slug}{suffix}.mp4"

    def active(self, name: str) -> bool:
        """O lote está rodando agora (neste ou em outro processo): a trava de execução está tomada."""
        probe_lock = FileLock(self.store.lock_path(name))
        if probe_lock.try_acquire():
            probe_lock.release()
            return False
        return True

    def status(self, batch: Batch) -> str:
        if self.active(batch.name):
            return BATCH_RUNNING
        if any(row.state in (PENDING, RUNNING) for row in batch.rows):
            return BATCH_PAUSED
        return BATCH_FINISHED

    def report(self, name: str) -> BatchReport:
        batch = self.store.load(name)
        return build_report(batch, self.status(batch), self.output_dir(name))

    def reports(self) -> list[BatchReport]:
        reports = []
        for name in self.store.list_names():
            try:
                reports.append(self.report(name))
            except (KeyError, RuntimeError):  # um arquivo de lote ilegível não derruba a lista dos outros
                continue
        return reports

    def pause(self, name: str) -> None:
        """Pede para o lote parar depois do vídeo em andamento (vale também para outro processo)."""
        self.store.request_pause(name)

    # ---------- execução ----------

    def _acquire(self, lock: FileLock) -> bool:
        for attempt in range(LOCK_ATTEMPTS):
            if lock.try_acquire():
                return True
            if attempt < LOCK_ATTEMPTS - 1:
                time.sleep(LOCK_WAIT_SECONDS)
        return False

    def run(
        self,
        name: str,
        *,
        rows: Collection[int] | None = None,
        force: bool = False,
        should_stop: Callable[[], bool] | None = None,
        progress: ProgressFn | None = None,
        log: Callable[[str], None] | None = None,
    ) -> BatchReport:
        """Renderiza o que falta do lote (ou só as `rows` pedidas), uma linha por vez. O que já está pronto
        com a mesma spec não é refeito, a não ser com `force`. Devolve o relatório, mesmo se parou no meio."""
        log = log or (lambda message: None)
        progress = progress or (lambda label, fraction: None)
        stop = should_stop or (lambda: False)
        lock = FileLock(self.store.lock_path(name))
        if not self._acquire(lock):
            raise BatchBusyError(f'O lote "{name}" já está rodando (em outra janela ou processo).')
        try:
            self.store.clear_pause(name)
            requeued = self.store.change(name, self._requeue_interrupted)
            if requeued:
                log(f"{requeued} vídeo(s) que estavam em andamento voltam para a fila")
            todo = self._plan(self.store.load(name), rows, force)
            log(f"{len(todo)} vídeo(s) a renderizar" if todo else "Nada a renderizar: tudo já está pronto")
            try:
                self._render_rows(name, todo, stop, progress, log)
            finally:
                self._write_report(name)
            batch = self.store.load(name)
            return build_report(batch, self._status_after(batch), self.output_dir(name))
        finally:
            lock.release()

    @staticmethod
    def _requeue_interrupted(batch: Batch) -> int:
        stuck = [row for row in batch.rows if row.state == RUNNING]
        for row in stuck:
            row.state = PENDING
        return len(stuck)

    @staticmethod
    def _status_after(batch: Batch) -> str:
        """Estado ao fim de uma execução (a trava ainda é nossa): parou no meio ou acabou."""
        waiting = any(row.state in (PENDING, RUNNING) for row in batch.rows)
        return BATCH_PAUSED if waiting else BATCH_FINISHED

    def _plan(self, batch: Batch, rows: Collection[int] | None, force: bool) -> list[BatchRow]:
        todo = []
        for row in batch.rows:
            if row.state == INVALID or (rows is not None and row.index not in rows):
                continue
            if not force and self._is_current(batch, row):
                continue
            todo.append(row)
        return todo

    def _is_current(self, batch: Batch, row: BatchRow) -> bool:
        """O vídeo desta linha está pronto e corresponde ao projeto como ele está agora."""
        if row.state != DONE or not row.signature or not row.output or not Path(row.output).is_file():
            return False
        try:
            project = load_project(row.project or "")
        except (OSError, ValueError, ValidationError):
            return False
        return project_signature(project, batch.preview, batch.preset) == row.signature

    def _render_rows(
        self,
        name: str,
        todo: list[BatchRow],
        stop: Callable[[], bool],
        progress: ProgressFn,
        log: Callable[[str], None],
    ) -> None:
        for row in todo:
            if stop() or self.store.pause_requested(name):
                log("Lote pausado. Retome quando quiser: o que já saiu não é refeito")
                return
            self._render_row(name, row.index, progress, log)

    def _render_row(self, name: str, index: int, progress: ProgressFn, log: Callable[[str], None]) -> None:
        batch = self.store.load(name)
        row = batch.row(index)
        runnable = [other for other in batch.rows if other.state != INVALID]
        finished = sum(1 for other in runnable if other.state == DONE)
        title = row.title or f"linha {row.line}"
        prefix = f"Vídeo {finished + 1} de {len(runnable)}: {title}"

        def report(detail: str) -> None:
            progress(f"{prefix} · {detail}" if detail else prefix, finished / len(runnable))

        report("")
        log(prefix)
        started = time.time()
        self.store.change(name, lambda b: self._begin(b.row(index), started))
        try:
            project = load_project(row.project or "")
            signature = project_signature(project, batch.preview, batch.preset)
            out = self.output_path(batch, row)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.unlink(missing_ok=True)  # um vídeo pela metade nunca passa por pronto
            outcome = self.renderer.render(
                project,
                out,
                preview=batch.preview,
                preset=batch.preset,
                sink=_RowSink(report),
                log=log,
            )
        except KeyboardInterrupt:  # Ctrl+C: a linha volta para a fila e a retomada a refaz
            self.store.change(name, lambda b: self._reset(b.row(index)))
            raise
        except Exception as exc:  # noqa: BLE001 - o motivo vai para a linha e para o relatório
            message = _short_error(exc)
            self.store.change(name, lambda b: self._fail(b.row(index), message, started))
            log(f"Falhou: {title}: {message}")
            return
        self.store.change(name, lambda b: self._finish(b.row(index), outcome, signature, started))
        log(f"Pronto: {title} ({time.time() - started:.0f} s)")

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
    def _finish(row: BatchRow, outcome: RowOutcome, signature: str, started: float) -> None:
        row.state, row.error, row.finished_at = DONE, None, time.time()
        row.output, row.signature = str(outcome.output), signature
        row.duration_s, row.size_mb = round(outcome.duration_s, 2), round(outcome.size_mb, 2)
        row.render_s, row.warnings = round(row.finished_at - started, 1), list(outcome.warnings)

    def _write_report(self, name: str) -> None:
        """Deixa o relatório ao lado dos vídeos; falhar em gravá-lo não pode derrubar o lote."""
        try:
            batch = self.store.load(name)
            report = build_report(batch, self._status_after(batch), self.output_dir(name))
            folder = self.output_dir(name)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / REPORT_FILE).write_text(report.to_text() + "\n", encoding="utf-8")
        except OSError:
            return


def run_in_job(
    service: BatchService, name: str, job: Job, rows: Collection[int] | None = None, force: bool = False
) -> dict[str, Any]:
    """O lote ligado a um job (interface e MCP): log e andamento viram eventos, e cancelar o job pausa o lote."""
    report = service.run(
        name,
        rows=rows,
        force=force,
        should_stop=lambda: job.cancel_requested,
        progress=stage_progress(job),
        log=job.log,
    )
    return report.to_dict()
