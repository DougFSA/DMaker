"""Deslocamento de cada fonte sincronizada no relógio da fonte principal, com cache por projeto."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import CACHE_DIR
from ..domain.spec import Project
from ..media.audiosync import SyncResult, sync_offset
from ..media.ffmpeg import FFmpegRunner

OffsetFinder = Callable[[Path, Path, int, int], SyncResult]


def ffmpeg_offset_finder(runner: FFmpegRunner) -> OffsetFinder:
    workdir = CACHE_DIR / "audio" / "sync"

    def find(master: Path, other: Path, master_stream: int, other_stream: int) -> SyncResult:
        return sync_offset(runner, master, other, workdir, master_stream, other_stream)

    return find


@dataclass
class SyncResolver:
    """`sync` numérico usa o valor; "auto" mede pelo áudio e guarda em <projeto>/sync.json."""

    finder: OffsetFinder
    log: Callable[[str], None] = lambda message: None  # noqa: E731

    def resolve(self, project: Project, store: Path | None) -> dict[str, float]:
        master_name = project.master_source
        if master_name is None:
            return {}
        master = project.sources[master_name]
        master_path = project.resolve(master.src)
        cache = self._load(store)
        offsets: dict[str, float] = {master_name: 0.0}
        changed = False
        for name, source in project.sources.items():
            if name == master_name:
                continue
            if source.sync != "auto":
                offsets[name] = float(source.sync)
                continue
            path = project.resolve(source.src)
            key = self._key(master_path, path)
            entry = cache.get(name)
            if entry and entry.get("key") == key:
                offsets[name] = float(entry["offset"])
                continue
            self.log(f"sincronizando {name} com {master_name} pelo áudio...")
            result = self.finder(master_path, path, master.audio_stream, source.audio_stream)
            note = "" if result.reliable else " (baixa confiança: confira e, se preciso, informe o valor)"
            self.log(f"{name}: começa em {result.offset:+.3f}s do relógio de {master_name}{note}")
            offsets[name] = result.offset
            cache[name] = {"key": key, "offset": result.offset, "confidence": result.confidence}
            changed = True
        if changed and store is not None:
            store.parent.mkdir(parents=True, exist_ok=True)
            store.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        return offsets

    @staticmethod
    def _key(master: Path, other: Path) -> list:
        return [str(master), master.stat().st_size, str(other), other.stat().st_size]

    @staticmethod
    def _load(store: Path | None) -> dict:
        if store is None or not store.exists():
            return {}
        try:
            return json.loads(store.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
