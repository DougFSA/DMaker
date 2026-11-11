"""Executor dos comandos externos do build (pip, npm, ISCC, git): real em produção, gravador nos testes."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class ReleaseError(RuntimeError):
    """Falha do build com mensagem pronta para quem roda o comando."""


@dataclass(frozen=True)
class RecordedCommand:
    command: tuple[str, ...]
    cwd: Path | None = None


class CommandRunner(Protocol):
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> str:
        """Roda o comando até o fim e devolve a saída; falhar é levantar `ReleaseError` (salvo com `check=False`)."""


class SubprocessCommandRunner:
    """Roda de verdade, repassando cada linha de saída para `on_line` (o build de um instalador leva minutos)."""

    def __init__(self, on_line: Callable[[str], None] | None = None) -> None:
        self.on_line = on_line

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> str:
        program = shutil.which(command[0]) or command[0]  # o `npm` do Windows é um .cmd
        merged = {**os.environ, **(env or {})}
        try:
            process = subprocess.Popen(
                [program, *command[1:]],
                cwd=cwd,
                env=merged,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise ReleaseError(f"Não consegui rodar {command[0]!r}: {exc}") from exc
        lines: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line)
            if self.on_line:
                self.on_line(line.rstrip("\n"))
        if process.wait() != 0 and check:
            tail = "".join(lines[-25:]).strip()
            raise ReleaseError(f"Falhou ({process.returncode}): {' '.join(command)}\n{tail}")
        return "".join(lines)


@dataclass
class RecordingCommandRunner:
    """Não executa nada: guarda os comandos na ordem e devolve a saída combinada por prefixo (`outputs`)."""

    outputs: dict[tuple[str, ...], str] = field(default_factory=dict)
    commands: list[RecordedCommand] = field(default_factory=list)

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> str:
        recorded = tuple(str(part) for part in command)
        self.commands.append(RecordedCommand(recorded, cwd))
        for prefix, output in self.outputs.items():
            if recorded[: len(prefix)] == prefix:
                return output
        return ""
