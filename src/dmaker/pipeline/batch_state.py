"""Estado de um lote no disco: cada linha da planilha, em que ponto está e o que saiu dela.

O lote vive em `projects/_lotes/<nome>.json`, ao lado dos projetos que ele cria (um por linha). Toda mudança
lê o arquivo, altera e grava de volta por inteiro (escreve num temporário e renomeia), então um processo que
cai no meio nunca deixa o arquivo pela metade. O pedido de pausa é um arquivo à parte (`<nome>.pausar`): quem
pausa e quem renderiza são processos diferentes (a CLI e a interface), e gravar no mesmo JSON dos dois lados
perderia uma das mudanças. A pasta vem do `config` na hora do uso, como as demais.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .. import config

FOLDER_NAME = "_lotes"
FORMAT_VERSION = 1
REPLACE_ATTEMPTS = (
    5  # o Windows recusa renomear sobre um arquivo que outro processo está lendo naquele instante
)
REPLACE_WAIT_SECONDS = 0.05

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
INVALID = "invalid"  # linha com problema que a pessoa mandou seguir sem; nunca vira projeto
ROW_LABELS = {
    PENDING: "Pendente",
    RUNNING: "Renderizando",
    DONE: "Pronto",
    FAILED: "Falhou",
    INVALID: "Pulada",
}

# o lote não grava seu estado geral: ele vem das linhas e de a trava de execução estar tomada ou não
BATCH_RUNNING = "running"
BATCH_PAUSED = "paused"
BATCH_FINISHED = "finished"
BATCH_LABELS = {BATCH_RUNNING: "Rodando", BATCH_PAUSED: "Pausado", BATCH_FINISHED: "Concluído"}

# leitores (a tela, a cada segundo) e o executor rodam em threads do mesmo processo
_PROCESS_LOCK = threading.RLock()


class BatchNotFoundError(KeyError):
    """Nenhum lote com esse nome."""

    def __str__(self) -> str:
        return str(self.args[0])


class BatchFileError(RuntimeError):
    """O arquivo do lote existe mas não pôde ser lido (editado à mão, por exemplo)."""


@dataclass
class BatchRow:
    index: int  # posição entre as linhas de dados, a partir de 1
    line: int  # linha na planilha
    title: str  # texto da coluna do nome
    slug: str  # nome do arquivo de saída, sem extensão
    project: str | None  # projeto salvo desta linha; None numa linha pulada
    state: str = PENDING
    issues: list[dict[str, Any]] = field(default_factory=list)  # problemas e avisos da validação
    error: str | None = None
    output: str | None = None
    signature: str | None = None  # impressão digital do que foi renderizado: spec e opções
    duration_s: float | None = None  # duração do vídeo pronto
    size_mb: float | None = None
    render_s: float | None = None  # quanto levou para renderizar
    warnings: list[str] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatchRow:
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})


@dataclass
class Batch:
    name: str
    template: str
    sheet: str | None
    name_column: str | None
    preview: bool = False
    preset: str | None = None
    rows: list[BatchRow] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["version"] = FORMAT_VERSION
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Batch:
        known = {f.name for f in fields(cls)} - {"rows"}
        rows = [BatchRow.from_dict(raw) for raw in data.get("rows", [])]
        return cls(rows=rows, **{key: value for key, value in data.items() if key in known})

    def row(self, index: int) -> BatchRow:
        for row in self.rows:
            if row.index == index:
                return row
        raise KeyError(f"O lote {self.name!r} não tem a linha {index}.")


def _atomic_write(path: Path, content: str) -> None:
    """Grava num temporário e renomeia: quem lê vê sempre o arquivo antigo ou o novo, nunca metade."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_WAIT_SECONDS)


def _read_text(path: Path) -> str:
    """Lê o arquivo; o Windows nega a leitura por um instante se outro processo está trocando o arquivo."""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_WAIT_SECONDS)
    raise AssertionError("inalcançável")  # pragma: no cover


class BatchStore:
    def __init__(self, folder: Path | None = None) -> None:
        self._fixed_folder = folder

    @property
    def folder(self) -> Path:
        """Lido a cada uso: os testes e `DMAKER_DATA_DIR` diferentes apontam o config para outra pasta."""
        return self._fixed_folder or config.PROJECTS_DIR / FOLDER_NAME

    def path(self, name: str) -> Path:
        return self.folder / f"{name}.json"

    def lock_path(self, name: str) -> Path:
        return self.folder / f"{name}.lock"

    def _pause_path(self, name: str) -> Path:
        return self.folder / f"{name}.pausar"

    # ---------- leitura e gravação ----------

    def exists(self, name: str) -> bool:
        return self.path(name).is_file()

    def load(self, name: str) -> Batch:
        path = self.path(name)
        if not path.is_file():
            raise BatchNotFoundError(f'Não existe o lote "{name}".')
        try:
            return Batch.from_dict(json.loads(_read_text(path)))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise BatchFileError(f"Não consegui ler o lote em {path}: {exc}") from exc

    def save(self, batch: Batch) -> None:
        batch.updated_at = time.time()
        _atomic_write(self.path(batch.name), json.dumps(batch.to_dict(), ensure_ascii=False, indent=1))

    def change(self, name: str, apply: Callable[[Batch], Any]) -> Any:
        """Lê o lote, aplica a mudança e grava de volta, sem ninguém entrar no meio (neste processo)."""
        with _PROCESS_LOCK:
            batch = self.load(name)
            result = apply(batch)
            self.save(batch)
            return result

    def list_names(self) -> list[str]:
        if not self.folder.is_dir():
            return []
        paths = sorted(self.folder.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        return [path.stem for path in paths]

    # ---------- pausa ----------

    def request_pause(self, name: str) -> None:
        if not self.exists(name):
            raise BatchNotFoundError(f'Não existe o lote "{name}".')
        _atomic_write(self._pause_path(name), "pausar")

    def pause_requested(self, name: str) -> bool:
        return self._pause_path(name).exists()

    def clear_pause(self, name: str) -> None:
        self._pause_path(name).unlink(missing_ok=True)

    # ---------- limpeza ----------

    def remove(self, name: str) -> None:
        """Esquece o lote (o arquivo de estado); projetos e vídeos que ele criou ficam onde estão."""
        for path in (self.path(name), self._pause_path(name), self.lock_path(name)):
            path.unlink(missing_ok=True)
