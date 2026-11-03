"""Os quadros de instante em andamento: um trabalho por projeto, em segundo plano.

Fora da lista de jobs de propósito, como as mixagens da prévia: o editor pede um quadro a cada gesto, e cada um
apareceria na barra de jobs e avisaria "Concluído". A página consulta o estado de uma chave pelo `GET`, sem abrir
uma conexão de eventos. Um projeto tem um quadro sendo feito por vez; o pedido novo toma o lugar do anterior, que
fica `superseded`: se ainda esperava a vez ele nem começa, e se já roda ele para entre um comando do ffmpeg e o
seguinte (um comando em curso não é morto: o mezanino grava direto no cache, e um arquivo pela metade ficaria lá).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field

from ..domain.spec import Project
from ..media.ffmpeg import FFmpegError, FFmpegRunner, SubprocessRunner
from .instant_frame import InstantFrame, InstantFrameRenderer

RendererFactory = Callable[[FFmpegRunner, Callable[[str], None]], InstantFrameRenderer]

KEEP_STATUSES = 64  # estados guardados na memória; os mais antigos saem primeiro


class FrameSuperseded(Exception):
    """Um pedido mais novo do mesmo projeto tomou o lugar deste: o trabalho para sem entregar o quadro."""


@dataclass
class InstantFrameStatus:
    """Onde o quadro de uma chave está: pronto, sendo feito (com a etapa e o andamento), com erro ou superado."""

    state: str  # ready | pending | error | superseded
    key: str
    at: float | None = None  # o instante exato que o quadro mostra (múltiplo do quadro do vídeo)
    frame: InstantFrame | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)
    label: str = ""
    percent: int = 0


class _StatusSink:
    """Leva o andamento de cada comando ffmpeg para o estado do quadro."""

    def __init__(self, status: InstantFrameStatus) -> None:
        self.status = status
        self.total: float | None = None

    def start(self, label: str, total: float | None) -> None:
        self.total = total
        self.status.label = label
        self.status.percent = 0

    def update(self, done: float) -> None:
        if self.total:
            self.status.percent = int(min(done / self.total, 1.0) * 100)

    def finish(self) -> None:
        self.status.percent = 100


def failure_message(exc: Exception) -> str:
    """O erro em português para quem edita: a mensagem do próprio erro quando ela já explica (arquivo que falta,
    projeto sem duração), e o fim do que o ffmpeg disse quando foi ele que falhou."""
    if isinstance(exc, FFmpegError):
        tail = (getattr(exc, "stderr", "") or "").strip().splitlines()
        detail = f" ({tail[-1]})" if tail else ""
        return f"O ffmpeg falhou ao montar o quadro{detail}."
    if isinstance(exc, (FileNotFoundError, ValueError, KeyError)):
        return str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
    return f"Não foi possível montar o quadro: {type(exc).__name__}: {exc}"


class InstantFrameTasks:
    """Pede, acompanha e entrega os quadros. O pedido novo de um projeto supera o que ainda não terminou."""

    def __init__(self) -> None:
        self._statuses: OrderedDict[tuple[str, str], InstantFrameStatus] = OrderedDict()
        self._project_locks: dict[str, threading.Lock] = {}
        self._latest: dict[str, str] = {}  # a chave mais nova pedida de cada projeto
        self._lock = threading.Lock()

    def request(self, project: Project, t: float, make_renderer: RendererFactory) -> InstantFrameStatus:
        """O estado do quadro do projeto em `t` como está agora: já pronto (cache), em andamento ou recém-iniciado."""
        renderer = make_renderer(SubprocessRunner(quiet=True), lambda message: None)
        key = renderer.key(project, t)
        at = renderer.instant(project, t)
        with self._lock:
            self._supersede_older(project.name, key)
            self._latest[project.name] = key
            known = self._statuses.get((project.name, key))
            if known is not None and known.state == "pending":
                return known
        ready = renderer.cached(project.name, key)
        if ready is not None:
            status = InstantFrameStatus("ready", key, ready.at, ready, notes=list(ready.notes))
            with self._lock:
                self._remember(project.name, key, status)
            return status
        status = InstantFrameStatus("pending", key, at)
        with self._lock:
            self._remember(project.name, key, status)
        threading.Thread(
            target=self._run,
            args=(project, t, key, status, make_renderer),
            daemon=True,
            name=f"dmaker-frame-{key}",
        ).start()
        return status

    def status(self, name: str, key: str, renderer: InstantFrameRenderer) -> InstantFrameStatus | None:
        """O estado de uma chave já pedida; depois de reiniciar o servidor, o quadro em disco ainda vale."""
        with self._lock:
            known = self._statuses.get((name, key))
        if known is not None:
            if known.state == "ready" and renderer.cached(name, key) is None:
                return None  # o arquivo foi apagado (limpeza do cache): peça de novo com POST
            return known
        ready = renderer.cached(name, key)
        if ready is None:
            return None
        return InstantFrameStatus("ready", key, ready.at, ready, notes=list(ready.notes))

    def _supersede_older(self, name: str, key: str) -> None:
        """O que ainda não terminou do projeto, e não é este quadro, passa a `superseded` (com o lock em mãos)."""
        for (project_name, other), status in self._statuses.items():
            if project_name == name and other != key and status.state == "pending":
                status.state = "superseded"

    def _remember(self, name: str, key: str, status: InstantFrameStatus) -> None:
        self._statuses[(name, key)] = status
        self._statuses.move_to_end((name, key))
        while len(self._statuses) > KEEP_STATUSES:
            self._statuses.popitem(last=False)

    def _is_current(self, name: str, key: str, status: InstantFrameStatus) -> bool:
        with self._lock:
            return self._latest.get(name) == key and status.state == "pending"

    def _run(
        self, project: Project, t: float, key: str, status: InstantFrameStatus, make_renderer: RendererFactory
    ) -> None:
        def log(message: str) -> None:
            status.label = message

        def checkpoint() -> None:
            if not self._is_current(project.name, key, status):
                raise FrameSuperseded()

        renderer = make_renderer(SubprocessRunner(sink=_StatusSink(status), quiet=True), log)
        with self._lock:
            project_lock = self._project_locks.setdefault(project.name, threading.Lock())
        with project_lock:
            try:
                checkpoint()  # esperou a vez e foi superado: nem começa
                frame = renderer.render(project, t, key, checkpoint)
            except FrameSuperseded:
                status.state = "superseded"
                return
            except Exception as exc:  # noqa: BLE001 - o erro vai para quem consulta o estado
                status.error = failure_message(exc)
                status.state = "error"
                return
            status.frame = frame
            status.at = frame.at
            status.notes = list(frame.notes)
            status.percent = 100
            with self._lock:
                # um pedido mais novo chegou no meio do último comando: o quadro fica no cache, mas não é o atual
                if status.state == "pending":
                    status.state = "ready"
