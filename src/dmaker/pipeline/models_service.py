"""Gerenciador dos modelos em `cache/models`: o que está baixado, quanto ocupa, e baixar, apagar e limpar sobras.

O diretório é lido na hora do uso (`config.MODELS_DIR`) e tudo o que apaga passa por `_inside`, que recusa
qualquer caminho que saia dele. CLI, MCP e interface são adaptadores finos sobre `ModelService`; a decisão de
perguntar antes de apagar é deles, mas o serviço também exige `confirm=True` para não depender de ninguém.
"""

from __future__ import annotations

import functools
import os
import shutil
import stat
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .. import config
from ..domain.models import (
    INCOMPLETE_SUFFIXES,
    REGISTRY,
    RESERVED_ENTRIES,
    ModelSpec,
    ModelState,
    classify,
    exclusive_paths,
    format_size,
    is_safe_relative,
)
from .jobs import Job
from .model_fetchers import Fetcher, resolve_fetcher

ProgressCallback = Callable[[int, int], None]  # (bytes no disco, bytes esperados)

# Intervalo entre as medições do disco durante um download. Meio segundo mostra o avanço sem
# percorrer a pasta (poucos arquivos grandes) a todo instante.
POLL_SECONDS = 0.5

_is_junction = getattr(os.path, "isjunction", None)  # só existe a partir do Python 3.12


class ModelError(Exception):
    """Erro de uso do gerenciador, com mensagem pronta para o usuário."""


class UnknownModel(ModelError):
    pass


class ModelBusy(ModelError):
    pass


class InsufficientSpace(ModelError):
    pass


class ConfirmationRequired(ModelError):
    """Apagar sem `confirm=True`; o aviso do que será apagado vem na mensagem."""


# ---------- medição ----------


def is_link(path: Path | os.DirEntry) -> bool:
    """Link simbólico ou junção do Windows: apontam para fora da pasta, então nunca se atravessam ao apagar."""
    target = path.path if isinstance(path, os.DirEntry) else str(path)
    return os.path.islink(target) or bool(_is_junction and _is_junction(target))


@dataclass(frozen=True)
class Measure:
    size: int
    exists: bool
    incomplete: bool  # sobrou arquivo de download em andamento (.part, .incomplete)


def measure_path(path: Path) -> Measure:
    """Bytes de um arquivo ou pasta (sem atravessar links aninhados) e se há resto de download dentro."""
    if not os.path.lexists(path):
        return Measure(0, False, False)
    # a raiz pode ser um link que o usuário criou para mover o modelo de disco: mede o destino
    root = path.resolve() if is_link(path) else path
    if root.is_file():
        return Measure(root.stat().st_size, True, root.name.endswith(INCOMPLETE_SUFFIXES))
    size, incomplete = 0, False
    stack = [root]
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            if is_link(entry):
                continue
            if entry.is_dir(follow_symlinks=False):
                stack.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                size += entry.stat(follow_symlinks=False).st_size
                incomplete = incomplete or entry.name.endswith(INCOMPLETE_SUFFIXES)
    return Measure(size, True, incomplete)


# ---------- resultados ----------


@dataclass(frozen=True)
class ModelStatus:
    spec: ModelSpec
    state: ModelState
    size_bytes: int

    def to_dict(self) -> dict:
        spec = self.spec
        return {
            "id": spec.id,
            "name": spec.name,
            "purpose": spec.purpose,
            "engine": spec.engine,
            "license": spec.license,
            "required_by": list(spec.required_by),
            "state": self.state,
            "size_bytes": self.size_bytes,
            "size_label": format_size(self.size_bytes),
            "expected_bytes": spec.expected_size,
            "expected_label": format_size(spec.expected_size),
        }


@dataclass(frozen=True)
class Leftover:
    """Pasta ou arquivo em `cache/models` que nenhum modelo do registro reivindica."""

    path: str  # relativo a cache/models, com barras normais
    size_bytes: int
    is_dir: bool

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "size_label": format_size(self.size_bytes),
            "is_dir": self.is_dir,
        }


@dataclass(frozen=True)
class Inventory:
    models_dir: Path
    models: list[ModelStatus]
    leftovers: list[Leftover]
    total_bytes: int
    disk_free_bytes: int | None

    @property
    def leftover_bytes(self) -> int:
        return sum(item.size_bytes for item in self.leftovers)

    def to_dict(self) -> dict:
        return {
            "models_dir": str(self.models_dir),
            "models": [status.to_dict() for status in self.models],
            "leftovers": [item.to_dict() for item in self.leftovers],
            "total_bytes": self.total_bytes,
            "total_label": format_size(self.total_bytes),
            "leftover_bytes": self.leftover_bytes,
            "leftover_label": format_size(self.leftover_bytes),
            "disk_free_bytes": self.disk_free_bytes,
            "disk_free_label": format_size(self.disk_free_bytes)
            if self.disk_free_bytes is not None
            else None,
        }


@dataclass(frozen=True)
class RemovalPlan:
    """O que apagar um modelo (ou as sobras) levaria embora, para mostrar antes de confirmar."""

    title: str
    paths: list[str] = field(default_factory=list)  # relativos a cache/models
    freed_bytes: int = 0
    stops_working: list[str] = field(default_factory=list)  # funções do DMaker que dependem do modelo

    def warning(self) -> str:
        text = f"Vai apagar {self.title} e liberar {format_size(self.freed_bytes)}."
        if self.stops_working:
            text += (
                " Estas funções deixam de funcionar até o modelo ser baixado de novo (o que acontece sozinho "
                "no primeiro uso, com internet): " + "; ".join(self.stops_working) + "."
            )
        return text

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "paths": self.paths,
            "freed_bytes": self.freed_bytes,
            "freed_label": format_size(self.freed_bytes),
            "stops_working": self.stops_working,
            "warning": self.warning(),
        }


# ---------- remoção segura ----------


def _inside(models_dir: Path, relative: str) -> Path:
    """Caminho absoluto de `relative` garantidamente dentro de `models_dir` (sem `..`, raiz ou unidade)."""
    if not is_safe_relative(relative):
        raise ModelError(f"Caminho recusado, fora de cache/models: {relative!r}")
    base = models_dir.resolve()
    target = base.joinpath(*PurePosixPath(relative).parts)
    # resolve o pai e não o alvo: um link no último nível é apagado como link, sem seguir para o destino
    if not target.parent.resolve().is_relative_to(base):
        raise ModelError(f"Caminho recusado, fora de cache/models: {relative!r}")
    return target


def _delete_file(path: Path) -> None:
    try:
        path.unlink()
    except PermissionError:
        path.chmod(stat.S_IWRITE)  # arquivos do cache do Hugging Face podem vir somente leitura no Windows
        path.unlink()


def _delete_tree(path: Path) -> None:
    """Apaga a pasta sem seguir links: um link dentro dela some, o destino dele fica intacto."""
    for entry in list(os.scandir(path)):
        child = Path(entry.path)
        if is_link(entry):
            _delete_link(child)
        elif entry.is_dir(follow_symlinks=False):
            _delete_tree(child)
        else:
            _delete_file(child)
    path.rmdir()


def _delete_link(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        path.rmdir()  # junção do Windows: só rmdir remove o link sem tocar no destino


def _delete_entry(path: Path) -> None:
    if is_link(path):
        _delete_link(path)
    elif path.is_dir():
        _delete_tree(path)
    elif path.exists():
        _delete_file(path)


# ---------- reivindicação de caminhos ----------


def _partial_sibling(relative: str, claimed: set[str]) -> bool:
    """Um `.part` ao lado de um arquivo reivindicado é o download dele em andamento, não sobra."""
    if not relative.endswith(INCOMPLETE_SUFFIXES):
        return False
    pure = PurePosixPath(relative)
    return any(
        PurePosixPath(path).parent == pure.parent and pure.name.startswith(PurePosixPath(path).stem)
        for path in claimed
    )


def find_leftovers(models_dir: Path, specs: tuple[ModelSpec, ...]) -> list[Leftover]:
    """Entradas de `models_dir` que nenhum modelo reivindica. Desce só em pasta que contém um caminho
    reivindicado (como `kokoro/`), para achar o arquivo solto ao lado do modelo sem tocar no modelo."""
    claimed = {path for spec in specs for path in spec.paths}
    ancestors = {
        PurePosixPath(*PurePosixPath(path).parts[:depth]).as_posix()
        for path in claimed
        for depth in range(1, len(PurePosixPath(path).parts))
    }
    found: list[Leftover] = []

    def visit(directory: Path, prefix: str) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.lower())
        except OSError:
            return
        for entry in entries:
            relative = f"{prefix}{entry.name}"
            if not prefix and entry.name in RESERVED_ENTRIES:
                continue
            if relative in claimed or _partial_sibling(relative, claimed):
                continue
            is_dir = entry.is_dir(follow_symlinks=False)
            if is_dir and relative in ancestors:
                visit(Path(entry.path), f"{relative}/")
                continue
            size = 0 if is_link(entry) else measure_path(Path(entry.path)).size
            found.append(Leftover(relative, size, is_dir))

    if models_dir.is_dir():
        visit(models_dir, "")
    return found


# ---------- serviço ----------


def _disk_free(path: Path) -> int | None:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def job_progress_reporter(job: Job, name: str) -> ProgressCallback:
    """Bytes baixados viram o progresso do job (e evento SSE), com o tamanho legível no rótulo."""

    def report(done: int, total: int) -> None:
        percent = int(100 * done / max(total, 1))
        label = f"{name}: {format_size(done)} de {format_size(total)}"
        job.progress = {"label": label, "done": done, "total": total, "percent": percent}
        job.emit("progress", **job.progress)

    return report


class ModelService:
    """Inventário e ações sobre os modelos. Tudo o que toca o mundo entra por parâmetro (pasta, funções de
    download, espaço livre), para os testes usarem uma pasta temporária e funções falsas."""

    def __init__(
        self,
        models_dir: Path | Callable[[], Path] | None = None,
        specs: tuple[ModelSpec, ...] = REGISTRY,
        fetcher_for: Callable[[str], Fetcher] = resolve_fetcher,
        disk_free: Callable[[Path], int | None] = _disk_free,
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        if callable(models_dir):
            self._models_dir: Callable[[], Path] = models_dir
        elif models_dir is not None:
            self._models_dir = lambda: models_dir
        else:
            self._models_dir = lambda: config.MODELS_DIR  # lido a cada uso, não na importação
        self.specs = specs
        self._fetcher_for = fetcher_for
        self._disk_free = disk_free
        self._poll_seconds = poll_seconds
        self._downloading: set[str] = set()
        self._lock = threading.Lock()

    # -- leitura --

    def spec(self, model_id: str) -> ModelSpec:
        for spec in self.specs:
            if spec.id == model_id:
                return spec
        known = ", ".join(spec.id for spec in self.specs)
        raise UnknownModel(f"Modelo {model_id!r} não existe. Os modelos são: {known}.")

    @staticmethod
    def _partial_siblings(models_dir: Path, paths: Iterable[str]) -> list[str]:
        """Os `.part` que um download interrompido (ou em andamento) deixou ao lado de cada caminho."""
        found: list[str] = []
        for path in paths:
            pure = PurePosixPath(path)
            parent = _inside(models_dir, pure.parent.as_posix()) if pure.parent.parts else models_dir
            if not parent.is_dir():
                continue
            for entry in os.scandir(parent):
                relative = (pure.parent / entry.name).as_posix()
                if relative not in found and _partial_sibling(relative, {path}):
                    found.append(relative)
        return found

    def _status(self, spec: ModelSpec, models_dir: Path) -> ModelStatus:
        """Estado e tamanho em disco. O `.part` do download em andamento conta no tamanho (é o que faz a barra
        andar) e marca o modelo como incompleto."""
        own = exclusive_paths(spec, self.specs)
        own_files = [*own, *self._partial_siblings(models_dir, own)]
        every_file = {*spec.paths, *own_files, *self._partial_siblings(models_dir, spec.paths)}
        measures = {path: measure_path(_inside(models_dir, path)) for path in every_file}
        present = any(measures[path].exists for path in own_files)
        size = sum(mark.size for mark in measures.values()) if present else 0
        incomplete = any(mark.incomplete for mark in measures.values())
        return ModelStatus(spec, classify(present, size, spec.expected_size, incomplete), size)

    def status(self, model_id: str) -> ModelStatus:
        return self._status(self.spec(model_id), self._models_dir())

    def inventory(self) -> Inventory:
        models_dir = self._models_dir()
        free = self._disk_free(models_dir) if models_dir.exists() else None
        return Inventory(
            models_dir=models_dir,
            models=[self._status(spec, models_dir) for spec in self.specs],
            leftovers=find_leftovers(models_dir, self.specs),
            total_bytes=measure_path(models_dir).size,
            disk_free_bytes=free,
        )

    # -- baixar --

    @contextmanager
    def _downloading_now(self, model_id: str) -> Iterator[None]:
        with self._lock:
            if model_id in self._downloading:
                raise ModelBusy(f"O download de {model_id} já está em andamento.")
            self._downloading.add(model_id)
        try:
            yield
        finally:
            with self._lock:
                self._downloading.discard(model_id)

    def _watch_progress(
        self, spec: ModelSpec, models_dir: Path, report: ProgressCallback, stop: threading.Event
    ) -> None:
        """Mede o disco enquanto o motor baixa: todos os motores gravam na pasta do modelo, então o avanço
        é o mesmo para qualquer um, sem depender de callback de cada biblioteca."""
        while not stop.wait(self._poll_seconds):
            report(min(self._status(spec, models_dir).size_bytes, spec.expected_size), spec.expected_size)

    def download(self, model_id: str, on_progress: ProgressCallback | None = None) -> ModelStatus:
        """Baixa o que falta do modelo e confere que ficou inteiro; se já está instalado, não baixa nada."""
        spec = self.spec(model_id)
        models_dir = self._models_dir()
        with self._downloading_now(model_id):
            current = self._status(spec, models_dir)
            if current.state == "installed":
                return current
            models_dir.mkdir(parents=True, exist_ok=True)
            needed = max(spec.expected_size - current.size_bytes, 0)
            free = self._disk_free(models_dir)
            if free is not None and free < needed:
                raise InsufficientSpace(
                    f"Falta espaço para baixar {spec.name}: precisa de cerca de {format_size(needed)} "
                    f"e o disco tem {format_size(free)} livres."
                )
            fetch = self._fetcher_for(spec.fetch)
            stop = threading.Event()
            watcher = None
            if on_progress:
                on_progress(min(current.size_bytes, spec.expected_size), spec.expected_size)
                watcher = threading.Thread(
                    target=self._watch_progress,
                    args=(spec, models_dir, on_progress, stop),
                    daemon=True,
                    name=f"dmaker-model-progress-{spec.id}",
                )
                watcher.start()
            try:
                fetch(models_dir, spec.variant)
            finally:
                stop.set()
                if watcher:
                    watcher.join()
            result = self._status(spec, models_dir)
            if result.state != "installed":
                raise ModelError(
                    f"O download de {spec.name} terminou, mas os arquivos ficaram incompletos "
                    f"({format_size(result.size_bytes)} de {format_size(spec.expected_size)}). Tente de novo."
                )
            if on_progress:
                on_progress(spec.expected_size, spec.expected_size)
            return result

    # -- apagar um modelo --

    def _removal_paths(self, spec: ModelSpec, models_dir: Path) -> list[str]:
        """Caminhos que só este modelo usa, mais os que divide com outro que não está instalado (o arquivo de
        vozes do Kokoro some junto com o último dos dois), mais os `.part` de download interrompido."""
        keep: set[str] = set()
        for other in self.specs:
            if other.id == spec.id:
                continue
            others_present = any(
                measure_path(_inside(models_dir, path)).exists for path in exclusive_paths(other, self.specs)
            )
            if others_present:
                keep.update(other.paths)
        paths = [path for path in spec.paths if path not in keep]
        return paths + [p for p in self._partial_siblings(models_dir, paths) if p not in paths]

    def plan_removal(self, model_id: str) -> RemovalPlan:
        spec = self.spec(model_id)
        models_dir = self._models_dir()
        paths, freed = [], 0
        for relative in self._removal_paths(spec, models_dir):
            mark = measure_path(_inside(models_dir, relative))
            if mark.exists:
                paths.append(relative)
                freed += mark.size
        return RemovalPlan(spec.name, paths, freed, list(spec.required_by))

    def remove(self, model_id: str, confirm: bool = False) -> RemovalPlan:
        spec = self.spec(model_id)
        with self._lock:
            if spec.id in self._downloading:
                raise ModelBusy(f"{spec.name} está sendo baixado agora; espere terminar.")
        plan = self.plan_removal(model_id)
        if not plan.paths:
            raise ModelError(f"{spec.name} não está baixado; não há o que apagar.")
        if not confirm:
            raise ConfirmationRequired(f"{plan.warning()} Confirme para apagar.")
        models_dir = self._models_dir()
        for relative in plan.paths:
            target = _inside(models_dir, relative)
            if is_link(target):
                raise ModelError(
                    f"{relative} é um atalho (link) para outra pasta. Apague-o à mão, para o DMaker "
                    "não mexer no que está fora de cache/models."
                )
        for relative in plan.paths:
            _delete_entry(_inside(models_dir, relative))
        return plan

    # -- sobras --

    def plan_prune(self, only: list[str] | None = None) -> RemovalPlan:
        items = find_leftovers(self._models_dir(), self.specs)
        if only is not None:
            wanted = set(only)
            items = [item for item in items if item.path in wanted]
        return RemovalPlan(
            f"{len(items)} item(ns) que nenhum modelo usa",
            [item.path for item in items],
            sum(item.size_bytes for item in items),
        )

    def prune(self, confirm: bool = False, only: list[str] | None = None) -> RemovalPlan:
        """Apaga as sobras. Com `only`, só as que o usuário viu na lista e que continuam sendo sobras."""
        plan = self.plan_prune(only)
        if not confirm:
            raise ConfirmationRequired(f"{plan.warning()} Confirme para apagar.")
        with self._lock:
            if self._downloading:
                raise ModelBusy("Há um download em andamento; espere terminar para limpar as sobras.")
        models_dir = self._models_dir()
        for relative in plan.paths:
            _delete_entry(_inside(models_dir, relative))
        return plan


@functools.lru_cache(maxsize=1)
def shared_service() -> ModelService:
    """O serviço do processo: servidor da interface e MCP precisam de um só, para o aviso de "download em
    andamento" valer entre uma chamada e outra."""
    return ModelService()
