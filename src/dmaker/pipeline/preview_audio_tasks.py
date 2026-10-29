"""As mixagens de áudio da prévia em andamento: uma por projeto e chave, em segundo plano.

Fora da lista de jobs de propósito: o editor pede uma mixagem a cada edição, e cada uma apareceria na barra
de jobs e avisaria "Concluído". Aqui a página consulta o estado de uma chave pelo `GET`, sem abrir uma conexão
de eventos (o navegador só aguenta seis por servidor, e o player disputa essas conexões com os vídeos).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field

from ..domain.spec import Project
from ..media.ffmpeg import FFmpegRunner, SubprocessRunner
from .preview_audio import PreviewAudio, PreviewAudioBuilder

BuilderFactory = Callable[[FFmpegRunner, Callable[[str], None]], PreviewAudioBuilder]

KEEP_STATUSES = 48  # estados guardados na memória; os mais antigos saem primeiro


@dataclass
class PreviewAudioStatus:
    """Onde a mixagem de uma chave está: pronta, sendo feita (com a etapa e o andamento) ou falhou."""

    state: str  # ready | building | failed
    key: str
    audio: PreviewAudio | None = None
    error: str | None = None
    label: str = ""
    percent: int = 0
    warnings: list[str] = field(default_factory=list)


class _StatusSink:
    """Leva o andamento de cada comando ffmpeg para o estado da mixagem."""

    def __init__(self, status: PreviewAudioStatus) -> None:
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


class PreviewAudioTasks:
    """Pede, acompanha e entrega as mixagens. Duas mixagens do mesmo projeto não rodam juntas (disputariam o
    ffmpeg e o disco): uma pedida enquanto outra roda espera a vez, e se enquanto espera chega um pedido mais novo
    do mesmo projeto ela nem começa, porque a edição que ela mixaria já foi superada."""

    def __init__(self) -> None:
        self._statuses: OrderedDict[tuple[str, str], PreviewAudioStatus] = OrderedDict()
        self._project_locks: dict[str, threading.Lock] = {}
        self._latest: dict[str, str] = {}  # a chave mais nova pedida de cada projeto
        self._lock = threading.Lock()

    def request(self, project: Project, make_builder: BuilderFactory) -> PreviewAudioStatus:
        """O estado da mixagem do projeto como está agora: já pronta (cache), em andamento ou recém-iniciada."""
        builder = make_builder(SubprocessRunner(quiet=True), lambda message: None)
        key = builder.key(project)
        with self._lock:
            self._latest[project.name] = key
            known = self._statuses.get((project.name, key))
            if (
                known is not None
                and known.state != "failed"
                and self._still_valid(known, builder, project.name)
            ):
                return known
        ready = builder.cached(project.name, key)
        status = PreviewAudioStatus("ready" if ready else "building", key, ready)
        if ready:
            status.warnings = list(ready.warnings)
        with self._lock:
            self._remember(project.name, key, status)
        if not ready:
            threading.Thread(
                target=self._run,
                args=(project, key, status, make_builder),
                daemon=True,
                name=f"dmaker-paudio-{key}",
            ).start()
        return status

    def status(self, name: str, key: str, builder: PreviewAudioBuilder) -> PreviewAudioStatus | None:
        """O estado de uma chave já pedida; depois de reiniciar o servidor, a mixagem em disco ainda vale."""
        with self._lock:
            known = self._statuses.get((name, key))
        if known is not None:
            return known
        ready = builder.cached(name, key)
        if ready is None:
            return None
        return PreviewAudioStatus("ready", key, ready, warnings=list(ready.warnings))

    @staticmethod
    def _still_valid(known: PreviewAudioStatus, builder: PreviewAudioBuilder, name: str) -> bool:
        """Uma mixagem "pronta" cujo arquivo foi apagado (limpeza do cache) precisa ser refeita."""
        return known.state == "building" or builder.cached(name, known.key) is not None

    def _remember(self, name: str, key: str, status: PreviewAudioStatus) -> None:
        self._statuses[(name, key)] = status
        self._statuses.move_to_end((name, key))
        while len(self._statuses) > KEEP_STATUSES:
            self._statuses.popitem(last=False)

    def _run(
        self, project: Project, key: str, status: PreviewAudioStatus, make_builder: BuilderFactory
    ) -> None:
        def log(message: str) -> None:
            status.label = message

        builder = make_builder(SubprocessRunner(sink=_StatusSink(status)), log)
        with self._lock:
            project_lock = self._project_locks.setdefault(project.name, threading.Lock())
        with project_lock:
            if self._latest.get(project.name) != key:
                status.error = "Substituída por uma edição mais nova."
                status.state = "failed"
                return
            try:
                audio = builder.build(project, key)
            except Exception as exc:  # noqa: BLE001 - o erro vai para quem consulta o estado
                status.error = f"{type(exc).__name__}: {exc}"
                status.state = "failed"
                return
            status.audio = audio
            status.warnings = list(audio.warnings)
            status.percent = 100
            status.state = "ready"
