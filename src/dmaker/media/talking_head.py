"""A cabeça falante: uma foto e uma fala viram os quadros de uma pessoa falando (o motor da persona realista).

`TalkingHead` é o protocolo, no estilo do `Matter`: o motor da persona só conhece ele e recebe a implementação por
injeção, então os testes usam uma falsa. `DittoTalkingHead` roda o ditto-talkinghead (Apache-2.0) num subprocesso
(`ditto_worker.py`), acelerado pelo OpenVINO na GPU integrada Intel quando há uma. Só um ditto roda por vez, nesta
máquina: o hubert ocupa 1,4 GB e a GPU integrada não divide bem.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .. import config
from .ditto_worker import WorkerArguments

TALKING_HEAD_FPS = 25  # o ditto desenha a 25 quadros por segundo
DEFAULT_STEPS = 15  # passos da difusão: 15 dão a mesma imagem de 50 para o olho e custam menos de um terço
DEFAULT_SEED = 7
LOG_EVERY_FRAMES = 10  # a cada tantos quadros uma linha no log do render (cada quadro leva ~4 s)
LOCK_POLL_SECONDS = 2.0
KEEP_OUTPUT_LINES = 12  # as últimas linhas do processo, para a mensagem de erro

# A estimativa do tempo de render é por quadro desenhado, porque o ritmo do preset muda o custo. Vem das medições do
# DMK-74 num i5-1235U com Iris Xe, com o computador livre: 6 s de fala (132 quadros) levaram 657 s, com um preparo de
# 125 s e 3,6 s por quadro em regime. O preparo fixo é arredondado para 150 s e o custo por quadro leva 25% de
# margem (3,6 x 1,25 = 4,5 s), para a estimativa errar para mais e não para menos. A CPU tem uma só medição
# (45 s por quadro, 180 s de preparo).
GPU_FIXED_SECONDS = 150.0
GPU_SECONDS_PER_FRAME = 4.5
CPU_FIXED_SECONDS = 180.0
CPU_SECONDS_PER_FRAME = 45.0
# O pico de memória medido no DMK-74 foi de 4,5 GB; abaixo disto de memória livre o render pode travar o computador.
PEAK_MEMORY_GB = 4.5
LOW_MEMORY_GB = 5.0


def frame_count(duration: float) -> int:
    """Quantos quadros o ditto desenha para `duration` segundos de fala."""
    return max(round(duration * TALKING_HEAD_FPS), 0)


def estimate_seconds(frames: int, has_gpu: bool) -> float:
    """Quanto tempo o render de um clipe de `frames` quadros leva (função pura, só uma estimativa)."""
    if has_gpu:
        return GPU_FIXED_SECONDS + GPU_SECONDS_PER_FRAME * frames
    return CPU_FIXED_SECONDS + CPU_SECONDS_PER_FRAME * frames


def free_memory_gb() -> float | None:
    """A memória livre em GB (psutil); None quando o psutil não está instalado."""
    try:
        import psutil
    except ImportError:
        return None
    return psutil.virtual_memory().available / 1024**3


def total_memory_gb() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    return psutil.virtual_memory().total / 1024**3


def low_memory_warning(free_gb: float | None) -> str | None:
    """O aviso de pouca memória livre (não bloqueia), ou None se há de sobra ou não dá para medir."""
    if free_gb is None or free_gb >= LOW_MEMORY_GB:
        return None
    return (
        f"Pouca memória livre ({free_gb:.1f} GB): feche outros programas, "
        f"o render da persona realista usa uns {PEAK_MEMORY_GB:g} GB."
    )


def format_duration(seconds: float) -> str:
    """`2 min 15 s`, `1 h 05 min`: para o log do render."""
    total = round(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min {secs:02d} s"
    return f"{secs} s"


@dataclass(frozen=True)
class TalkingHeadRequest:
    """O que desenhar: a foto já enquadrada no tamanho do quadro, a fala e a duração do clipe."""

    photo: Path
    audio: Path
    duration: float
    size: tuple[int, int]
    seed: int = DEFAULT_SEED
    steps: int = DEFAULT_STEPS

    @property
    def frame_bytes(self) -> int:
        return self.size[0] * self.size[1] * 3


class TalkingHeadError(RuntimeError):
    """O desenho falhou (a mensagem diz por quê)."""


class TalkingHead(Protocol):
    def frames(
        self, request: TalkingHeadRequest, log: Callable[[str], None], warn: Callable[[str], None]
    ) -> Iterator[bytes]:
        """Os quadros RGB24 (largura x altura do pedido), a 25 por segundo, na ordem. `log` recebe o andamento e
        `warn` o que o usuário precisa saber."""

    def has_gpu(self) -> bool:
        """Se o desenho vai para a GPU integrada (muda a estimativa de tempo)."""


@dataclass(frozen=True)
class WorkerEvent:
    kind: str  # ETAPA, DISPOSITIVO, AVISO, QUADRO, PRONTO, ERRO
    text: str = ""
    frame: int = 0
    total: int = 0
    path: str = ""


def parse_event(line: str) -> WorkerEvent | None:
    """Uma linha do worker (veja `ditto_worker.py`) como evento; None para o que não é do protocolo (as
    bibliotecas também escrevem no stdout)."""
    kind, _, rest = line.strip().partition(" ")
    if kind in {"ETAPA", "DISPOSITIVO", "AVISO", "ERRO"}:
        return WorkerEvent(kind, rest)
    if kind == "QUADRO":
        index, total, path = rest.split(" ", 2) if rest.count(" ") >= 2 else ("", "", "")
        if index.isdigit() and total.isdigit() and path:
            return WorkerEvent(kind, frame=int(index), total=int(total), path=path)
        return None
    if kind == "PRONTO":
        count, _, seconds = rest.partition(" ")
        return WorkerEvent(kind, text=f"{count} quadros em {seconds} s")
    return None


def progress_message(event: WorkerEvent, elapsed: float) -> str | None:
    """A linha de log de um quadro pronto (a cada `LOG_EVERY_FRAMES`, e no último), com o tempo por quadro."""
    if event.kind != "QUADRO":
        return None
    if event.frame % LOG_EVERY_FRAMES and event.frame != event.total:
        return None
    return (
        f"persona realista: quadro {event.frame} de {event.total} ({elapsed / event.frame:.1f} s por quadro)"
    )


def worker_command(arguments: WorkerArguments) -> list[str]:
    return [sys.executable, "-m", "dmaker.media.ditto_worker", *arguments.to_command()]


class DittoTalkingHead:
    """O ditto num subprocesso Python, um por vez (trava de arquivo entre processos)."""

    def __init__(self, models_dir: Path | None = None, cache_dir: Path | None = None) -> None:
        self._models_dir = models_dir
        self._cache_dir = cache_dir

    @property
    def models_dir(self) -> Path:
        return self._models_dir or config.MODELS_DIR

    @property
    def cache_dir(self) -> Path:
        """Onde o OpenVINO guarda os kernels compilados da GPU: compilar leva minutos, carregar leva segundos."""
        return self._cache_dir or config.CACHE_DIR / "ovcache"

    def has_gpu(self) -> bool:
        try:
            import openvino  # noqa: F401 - só para saber se o extra está instalado
        except ImportError:
            return False
        from .ditto_fast import detect_accelerator

        return detect_accelerator().device != "CPU"

    def frames(
        self, request: TalkingHeadRequest, log: Callable[[str], None], warn: Callable[[str], None]
    ) -> Iterator[bytes]:
        from ..pipeline.filelock import FileLock

        lock = FileLock(config.CACHE_DIR / "ditto.lock")
        low_memory = low_memory_warning(free_memory_gb())
        if low_memory:
            warn(low_memory)
        announced = False
        while not lock.try_acquire():
            if not announced:
                log("persona realista: outro desenho está em andamento neste computador; aguardando a vez")
                announced = True
            time.sleep(LOCK_POLL_SECONDS)
        try:
            yield from self._run(request, log, warn)
        finally:
            lock.release()

    def _run(
        self, request: TalkingHeadRequest, log: Callable[[str], None], warn: Callable[[str], None]
    ) -> Iterator[bytes]:
        config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="ditto_", dir=config.CACHE_DIR) as frames_dir:
            arguments = WorkerArguments(
                models_dir=self.models_dir,
                cache_dir=self.cache_dir,
                photo=request.photo,
                audio=request.audio,
                frames_dir=Path(frames_dir),
                duration=request.duration,
                seed=request.seed,
                steps=request.steps,
            )
            process = subprocess.Popen(
                worker_command(arguments),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert process.stdout is not None
            tail: deque[str] = deque(maxlen=KEEP_OUTPUT_LINES)
            failure: str | None = None
            drawing_started: float | None = None
            try:
                for line in process.stdout:
                    event = parse_event(line)
                    if event is None:
                        tail.append(line.rstrip())
                        continue
                    if event.kind == "ERRO":
                        failure = event.text
                    elif event.kind in {"ETAPA", "DISPOSITIVO"}:
                        log(f"persona realista: {event.text}")
                        if event.kind == "ETAPA" and event.text.startswith("desenhando"):
                            drawing_started = time.perf_counter()
                    elif event.kind == "AVISO":
                        warn(event.text)
                    elif event.kind == "QUADRO":
                        frame = self._read_frame(Path(event.path), request)
                        elapsed = time.perf_counter() - (drawing_started or time.perf_counter())
                        message = progress_message(event, elapsed)
                        if message:
                            log(message)
                        yield frame
                    elif event.kind == "PRONTO":
                        log(f"persona realista: pronto, {event.text}")
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
            if process.returncode != 0:
                detail = failure or " | ".join(tail) or f"código {process.returncode}"
                raise TalkingHeadError(f"O ditto falhou: {detail}")

    @staticmethod
    def _read_frame(path: Path, request: TalkingHeadRequest) -> bytes:
        data = path.read_bytes()
        path.unlink(missing_ok=True)
        if len(data) != request.frame_bytes:
            raise TalkingHeadError(
                f"O ditto devolveu um quadro de {len(data)} bytes, mas {request.size[0]}x{request.size[1]} "
                f"pedem {request.frame_bytes}."
            )
        return data
