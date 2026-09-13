"""FFmpeg: localização, capacidades e execução.

A execução passa por um `FFmpegRunner` (protocolo). O pipeline recebe o runner por injeção:
`SubprocessRunner` executa de verdade (com barra de progresso e quadros pelo stdin);
`RecordingRunner` só registra os comandos, o que serve para `--dry-run` e para testes unitários.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from ..config import find_tool

GLOBAL_FLAGS = ["-hide_banner", "-y", "-loglevel", "error", "-nostats", "-progress", "pipe:1"]


class FFmpegError(RuntimeError):
    def __init__(self, message: str, cmd: list[str] | None = None, stderr: str = ""):
        super().__init__(message)
        self.cmd = cmd or []
        self.stderr = stderr

    def __str__(self) -> str:  # pragma: no cover - formatação
        tail = self.stderr.strip().splitlines()[-12:]
        return (
            f"{self.args[0]}\n--- stderr ---\n"
            + "\n".join(tail)
            + f"\n--- comando ---\n{format_cmd(self.cmd)}"
        )


class FFmpegNotFound(FFmpegError):
    pass


def _quote(arg: str) -> str:
    needs = (" " in arg) or (";" in arg) or (arg == "")
    return f'"{arg}"' if needs else arg


def format_cmd(cmd: list[str]) -> str:
    return " ".join(_quote(c) for c in cmd)


def ffmpeg_path() -> Path:
    p = find_tool("ffmpeg")
    if not p:
        raise FFmpegNotFound(
            "ffmpeg não encontrado. Rode `dmaker setup` para baixar o FFmpeg em bin/ffmpeg, "
            "ou defina DMAKER_FFMPEG_DIR."
        )
    return p


def ffprobe_path() -> Path:
    p = find_tool("ffprobe")
    if not p:
        raise FFmpegNotFound("ffprobe não encontrado. Rode `dmaker setup`.")
    return p


# ---------- comando ----------


@dataclass
class FFmpegCommand:
    """Um comando ffmpeg sem o executável e sem as flags globais."""

    args: list[str]
    label: str = "ffmpeg"
    total: float | None = None  # segundos de saída, para a barra de progresso
    cwd: Path | None = None
    frames: Iterable[bytes] | None = None  # quadros rawvideo escritos no stdin (entrada `-i pipe:0`)

    def full(self) -> list[str]:
        return [str(ffmpeg_path()), *GLOBAL_FLAGS, *self.args]


class FFmpegRunner(Protocol):
    def run(self, command: FFmpegCommand) -> list[str]:
        """Executa e devolve o comando completo (para registro)."""

    def capture(self, args: list[str], label: str = "ffmpeg") -> str:
        """Executa com log em nível info e devolve o stderr (medições como o loudnorm imprimem ali)."""


class SubprocessRunner:
    """Executa o ffmpeg de verdade."""

    def __init__(self, quiet: bool = False):
        self.quiet = quiet

    def run(self, command: FFmpegCommand) -> list[str]:
        cmd = command.full()
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if command.frames is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(command.cwd) if command.cwd else None,
        )
        stderr_chunks: list[bytes] = []
        progress_state = {"done": 0.0}

        def drain_stderr() -> None:
            assert proc.stderr is not None
            stderr_chunks.append(proc.stderr.read())

        def drain_stdout() -> None:
            assert proc.stdout is not None
            for raw in proc.stdout:
                m = re.match(rb"out_time_us=(\d+)", raw) or re.match(rb"out_time_ms=(\d+)", raw)
                if m:
                    progress_state["done"] = int(m.group(1)) / 1_000_000

        threads = [
            threading.Thread(target=drain_stderr, daemon=True),
            threading.Thread(target=drain_stdout, daemon=True),
        ]
        for t in threads:
            t.start()

        with self._progress(command) as update:
            try:
                if command.frames is not None:
                    assert proc.stdin is not None
                    for frame in command.frames:
                        proc.stdin.write(frame)
                        update(progress_state["done"])
                    proc.stdin.close()
                while proc.poll() is None:
                    update(progress_state["done"])
                    try:
                        proc.wait(timeout=0.2)
                    except subprocess.TimeoutExpired:
                        pass
            except BrokenPipeError:
                pass
        proc.wait()
        for t in threads:
            t.join(timeout=5)
        if proc.returncode != 0:
            stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
            raise FFmpegError(f"ffmpeg falhou (código {proc.returncode}) em: {command.label}", cmd, stderr)
        return cmd

    def _progress(self, command: FFmpegCommand):
        """Context manager que devolve uma função update(segundos)."""
        total = command.total
        if self.quiet or not total:
            return _NoProgress()
        return _RichProgress(command.label, total)

    def capture(self, args: list[str], label: str = "ffmpeg") -> str:
        cmd = [str(ffmpeg_path()), "-hide_banner", "-nostats", "-y", *args]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode != 0:
            raise FFmpegError(f"ffmpeg falhou em: {label}", cmd, res.stderr)
        return res.stderr


class _NoProgress:
    def __enter__(self) -> Callable[[float], None]:
        return lambda _done: None

    def __exit__(self, *exc: object) -> None:
        return None


class _RichProgress:
    def __init__(self, label: str, total: float):
        self.progress = Progress(
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            transient=True,
        )
        self.label, self.total = label, max(total, 0.01)

    def __enter__(self) -> Callable[[float], None]:
        self.progress.start()
        task = self.progress.add_task(self.label, total=self.total)
        return lambda done: self.progress.update(task, completed=min(done, self.total))

    def __exit__(self, *exc: object) -> None:
        self.progress.stop()


@dataclass
class RecordingRunner:
    """Registra os comandos sem executar. `on_run` pode simular efeitos (criar o arquivo de saída)."""

    on_run: Callable[[FFmpegCommand], None] | None = None
    capture_stderr: str = ""
    commands: list[list[str]] = field(default_factory=list)
    frames_consumed: int = 0

    def run(self, command: FFmpegCommand) -> list[str]:
        cmd = command.full() if find_tool("ffmpeg") else ["ffmpeg", *GLOBAL_FLAGS, *command.args]
        self.commands.append(cmd)
        if command.frames is not None:
            self.frames_consumed += sum(1 for _ in command.frames)
        if self.on_run:
            self.on_run(command)
        return cmd

    def capture(self, args: list[str], label: str = "ffmpeg") -> str:
        self.commands.append(["ffmpeg", *args])
        return self.capture_stderr


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    total: float | None = None,
    label: str = "ffmpeg",
    quiet: bool = False,
) -> list[str]:
    """Atalho para comandos avulsos (thumbnail, grade de quadros)."""
    return SubprocessRunner(quiet=quiet).run(FFmpegCommand(args, label=label, total=total, cwd=cwd))


# ---------- probe e capacidades ----------


def probe_json(path: Path | str) -> dict:
    cmd = [
        str(ffprobe_path()),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise FFmpegError(f"ffprobe falhou para {path}", cmd, res.stderr)
    return json.loads(res.stdout or "{}")


@dataclass
class Capabilities:
    version: str = "?"
    libass: bool = False
    encoders: set[str] = field(default_factory=set)
    filters: set[str] = field(default_factory=set)

    def has_encoder(self, name: str) -> bool:
        return name in self.encoders

    def has_filter(self, name: str) -> bool:
        return name in self.filters


@lru_cache(maxsize=1)
def capabilities() -> Capabilities:
    exe = str(ffmpeg_path())
    caps = Capabilities()
    out = subprocess.run([exe, "-version"], capture_output=True, text=True, errors="replace").stdout
    m = re.search(r"ffmpeg version (\S+)", out)
    caps.version = m.group(1) if m else "?"
    caps.libass = "--enable-libass" in out
    enc = subprocess.run(
        [exe, "-hide_banner", "-encoders"], capture_output=True, text=True, errors="replace"
    ).stdout
    caps.encoders = {line.split()[1] for line in enc.splitlines() if re.match(r"^\s[VAS][.A-Z]{5}\s", line)}
    flt = subprocess.run(
        [exe, "-hide_banner", "-filters"], capture_output=True, text=True, errors="replace"
    ).stdout
    caps.filters = {
        m.group(1) for m in (re.match(r"^\s*[.TSC]{2,3}\s+(\S+)\s", line) for line in flt.splitlines()) if m
    }
    return caps


def filter_complex_file_args(filename: str) -> list[str]:
    """Grafo lido de arquivo: `-/filter_complex` (ffmpeg >= 7.1) ou `-filter_complex_script` (antigos)."""
    m = re.match(r"n?(\d+)\.(\d+)", capabilities().version)
    if m and (int(m.group(1)), int(m.group(2))) < (7, 1):
        return ["-filter_complex_script", filename]
    return ["-/filter_complex", filename]


def encoder_works(name: str) -> bool:
    """Testa de verdade um encoder de hardware (nvenc/amf/qsv) codificando 1 quadro."""
    try:
        cmd = [
            str(ffmpeg_path()),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=256x256:d=0.1",
            "-frames:v",
            "1",
            "-c:v",
            name,
            "-f",
            "null",
            "-",
        ]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).returncode == 0
    except Exception:
        return False
