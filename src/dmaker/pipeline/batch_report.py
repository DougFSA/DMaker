"""Relatório de um lote: o que saiu, o que falhou e por quê, em texto para o terminal e em dados para a tela.

Puro: recebe o estado do lote (`Batch`) e a pasta de saída, devolve o relatório. Quem grava o arquivo
`relatorio.txt` ao lado dos vídeos é o serviço (`batch.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .batch_state import (
    BATCH_LABELS,
    DONE,
    FAILED,
    INVALID,
    PENDING,
    ROW_LABELS,
    RUNNING,
    Batch,
    BatchRow,
)


@dataclass(frozen=True)
class RowReport:
    index: int
    line: int
    title: str
    state: str
    project: str | None
    output: str | None
    duration_s: float | None
    render_s: float | None
    error: str | None
    warnings: list[str] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: BatchRow) -> RowReport:
        return cls(
            row.index,
            row.line,
            row.title,
            row.state,
            row.project,
            row.output,
            row.duration_s,
            row.render_s,
            row.error,
            list(row.warnings),
            list(row.issues),
        )

    @property
    def label(self) -> str:
        return self.title or f"linha {self.line}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "line": self.line,
            "title": self.title,
            "state": self.state,
            "state_label": ROW_LABELS[self.state],
            "project": self.project,
            "output": self.output,
            "duration_s": self.duration_s,
            "render_s": self.render_s,
            "error": self.error,
            "warnings": self.warnings,
            "issues": self.issues,
        }

    def to_text(self) -> str:
        where = f" (linha {self.line})" if self.title else ""
        head = f"{self.index:>3}. [{ROW_LABELS[self.state].lower()}] {self.label}{where}"
        if self.state == DONE:
            took = f", renderizou em {self.render_s:.0f} s" if self.render_s is not None else ""
            return f"{head}: {self.output}{took}"
        if self.state == FAILED:
            return f"{head}: {self.error or 'sem detalhe'}"
        if self.state == INVALID:
            reasons = "; ".join(i["message"] for i in self.issues if i.get("level") == "erro")
            return f"{head}: não renderizada. {reasons}"
        return head


@dataclass(frozen=True)
class BatchReport:
    name: str
    template: str
    status: str  # running | paused | finished
    preview: bool
    output_dir: str
    rows: list[RowReport]

    def count(self, state: str) -> int:
        return sum(1 for row in self.rows if row.state == state)

    @property
    def done(self) -> int:
        return self.count(DONE)

    @property
    def failed(self) -> int:
        return self.count(FAILED)

    @property
    def skipped(self) -> int:
        return self.count(INVALID)

    @property
    def waiting(self) -> int:
        return self.count(PENDING) + self.count(RUNNING)

    @property
    def total(self) -> int:
        """Vídeos que o lote tenta fazer: as linhas puladas por problema não entram na conta."""
        return len(self.rows) - self.skipped

    @property
    def paused(self) -> bool:
        return self.status == "paused"

    def summary(self) -> str:
        parts = [f"{self.done} de {self.total} vídeo(s) pronto(s)"]
        if self.failed:
            parts.append(f"{self.failed} falhou(aram)")
        if self.skipped:
            parts.append(f"{self.skipped} linha(s) pulada(s) por problema")
        if self.waiting:
            parts.append(f"{self.waiting} esperando")
        return ", ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "template": self.template,
            "status": self.status,
            "status_label": BATCH_LABELS[self.status],
            "preview": self.preview,
            "output_dir": self.output_dir,
            "total": self.total,
            "done": self.done,
            "failed": self.failed,
            "skipped": self.skipped,
            "waiting": self.waiting,
            "summary": self.summary(),
            "rows": [row.to_dict() for row in self.rows],
        }

    def to_text(self) -> str:
        """O relatório que a CLI mostra e o serviço grava: resumo, vídeo por vídeo e o motivo de cada falha."""
        kind = "prévias" if self.preview else "vídeos"
        lines = [
            f"Lote {self.name} (modelo {self.template}, {BATCH_LABELS[self.status].lower()}): {self.summary()}.",
            f"Saída ({kind}): {self.output_dir}",
            "",
        ]
        lines += [row.to_text() for row in self.rows]
        warned = [row for row in self.rows if row.warnings]
        if warned:
            lines += ["", "Avisos do render:"]
            lines += [f"  {row.label}: {warning}" for row in warned for warning in row.warnings]
        return "\n".join(lines)


def build_report(batch: Batch, status: str, output_dir: Path) -> BatchReport:
    return BatchReport(
        batch.name,
        batch.template,
        status,
        batch.preview,
        str(output_dir),
        [RowReport.from_row(row) for row in batch.rows],
    )
