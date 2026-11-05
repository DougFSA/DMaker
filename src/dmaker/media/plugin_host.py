"""Quem hospeda os plugins: o ffmpeg que tem o filtro `lv2` ou `ladspa`, e a sondagem que pergunta a ele o que um plugin expõe.

O build principal do DMaker (o completo do gyan.dev) tem o `ladspa`; o `lv2` vem de um segundo ffmpeg (`bin/ffmpeg-lv2`, do
BtbN) que o `dmaker setup --plugins` instala. Os caminhos são lidos na hora do uso (`config.plugin_ffmpeg_candidates`), então
uma variável de ambiente os troca nos testes. A sondagem entra por protocolo (`PluginProbe`) para a varredura ser testada
sem plugin nem ffmpeg de verdade.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from .. import config

FILTER_OF_FORMAT = {"lv2": "lv2", "ladspa": "ladspa"}
PROBE_TIMEOUT_SECONDS = 30


@lru_cache(maxsize=32)
def _has_filter(executable: str, stamp: tuple[int, int], filter_name: str) -> bool:
    """Se o ffmpeg lista o filtro. A data e o tamanho do arquivo entram na chave: trocar o ffmpeg por outro build refaz a
    pergunta, e a resposta custa uma execução."""
    del stamp
    try:
        result = subprocess.run(
            [executable, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):  # um arquivo que não roda não tem filtro nenhum
        return False
    return (
        re.search(rf"^\s*[.TSC]{{2,3}}\s+{re.escape(filter_name)}\s", result.stdout, re.MULTILINE) is not None
    )


def has_filter(executable: Path, filter_name: str) -> bool:
    """Se o ffmpeg desse caminho lista o filtro (falso quando o arquivo não existe ou não roda)."""
    try:
        status = executable.stat()
    except OSError:
        return False
    return _has_filter(str(executable), (status.st_mtime_ns, status.st_size), filter_name)


def host_ffmpeg(format_name: str) -> Path | None:
    """O primeiro ffmpeg que tem o filtro do formato (`lv2` ou `ladspa`), ou None quando nenhum tem."""
    filter_name = FILTER_OF_FORMAT[format_name]
    for candidate in config.plugin_ffmpeg_candidates(format_name):
        if has_filter(candidate, filter_name):
            return candidate
    return None


class PluginProbe(Protocol):
    def report(
        self,
        ffmpeg: Path,
        graph: str,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> str:
        """Roda `graph` (um filtro `lv2` ou `ladspa` com `controls=help`, ou a listagem de uma biblioteca) e devolve o stderr, que
        é onde o ffmpeg imprime o que o plugin expõe."""


class SubprocessProbe:
    """A sondagem de verdade: o ffmpeg sobre meio segundo de silêncio, só para o filtro abrir o plugin e falar."""

    def report(
        self,
        ffmpeg: Path,
        graph: str,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> str:
        command = [
            str(ffmpeg),
            "-hide_banner",
            "-nostats",
            "-v",
            "info",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            "0.1",
            "-af",
            graph,
            "-f",
            "null",
            "-",
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(cwd) if cwd else None,
                env={**os.environ, **env} if env else None,
                timeout=PROBE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return f"[Parsed_probe @ 0] Failed to run: o plugin não respondeu em {PROBE_TIMEOUT_SECONDS} s"
        return result.stderr
