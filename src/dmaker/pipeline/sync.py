"""Deslocamento de cada fonte sincronizada no relógio da fonte principal, com cache por projeto.

Fonte de um arquivo só: `sync` numérico usa o valor; "auto" mede pelo áudio contra a principal
(como sempre foi). Fonte com `parts` (vários arquivos em sequência): a parte 0 usa `sync` do mesmo
jeito; as demais são sempre encadeadas por áudio (`partsync.chain_parts`), podendo se ligar a
qualquer parte já posicionada de QUALQUER outra fonte, não só à principal.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..domain.spec import Project
from ..media.audiosync import SyncResult, sync_offset, sync_offset_near
from ..media.ffmpeg import FFmpegRunner
from ..media.probe import probe
from .context import Prober
from .partsync import CLOCK_TOLERANCE_S, LinkFinder, PartInfo, PartOffsets, chain_parts

OffsetFinder = Callable[[Path, Path, int, int], SyncResult]


@dataclass(frozen=True)
class _FfmpegLinks:
    """`OffsetFinder` de verdade (busca cega, arquivo inteiro) que também expõe `near`, a busca
    guiada por vizinhança que `_cached_links` usa quando já sabe onde procurar; fakes de teste, sem
    `near`, fazem a cadeia de partes cair sem confiança nesse passo em vez de quebrar."""

    runner: FFmpegRunner
    workdir: Path

    def __call__(
        self, master: Path, other: Path, master_stream: int = 0, other_stream: int = 0
    ) -> SyncResult:
        return sync_offset(self.runner, master, other, self.workdir, master_stream, other_stream)

    def near(self, master: Path, other: Path, expected: float, tolerance: float) -> SyncResult:
        return sync_offset_near(self.runner, master, other, self.workdir, expected, tolerance)


def ffmpeg_offset_finder(runner: FFmpegRunner) -> OffsetFinder:
    return _FfmpegLinks(runner, config.CACHE_DIR / "audio" / "sync")


@dataclass(frozen=True)
class SyncResolution:
    offsets: dict[str, float]  # fonte -> início no relógio da sessão (parte 0, para fontes com `parts`)
    parts: PartOffsets = field(default_factory=dict)  # fonte com `parts` -> início de cada parte
    warnings: list[str] = field(default_factory=list)


@dataclass
class SyncResolver:
    """`sync` numérico usa o valor; "auto" mede pelo áudio e guarda em <projeto>/sync.json."""

    finder: OffsetFinder
    log: Callable[[str], None] = lambda message: None  # noqa: E731
    prober: Prober = probe  # só usado para as fontes com `parts` (duração e relógio de cada arquivo)

    def resolve(self, project: Project, store: Path | None) -> SyncResolution:
        master_name = project.master_source
        if master_name is None:
            return SyncResolution({})
        master = project.sources[master_name]
        cache = self._load(store)
        offsets: dict[str, float] = {master_name: 0.0}
        changed = False

        if not master.parts and not any(ref.parts for ref in project.sources.values()):
            master_path = project.resolve(master.src)
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
            return SyncResolution(offsets)

        # alguma fonte (talvez a própria principal) grava em várias partes: a correlação simples só
        # compararia um arquivo com outro, então toda fonte "auto" (partida ou não) entra na cadeia,
        # que pode ligar qualquer parte a qualquer parte já posicionada de outra fonte.
        for name, source in project.sources.items():
            if name != master_name and not source.parts and source.sync != "auto":
                offsets[name] = float(source.sync)
        parts, warnings, changed = self._resolve_parts(project, master_name, offsets, cache)
        for name in project.sources:
            offsets[name] = parts[name][0]
        if changed and store is not None:
            store.parent.mkdir(parents=True, exist_ok=True)
            store.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        parted_only = {name: values for name, values in parts.items() if project.sources[name].parts}
        return SyncResolution(offsets, parted_only, warnings)

    def _resolve_parts(
        self, project: Project, master_name: str, offsets: dict[str, float], cache: dict
    ) -> tuple[PartOffsets, list[str], bool]:
        infos: dict[str, list[PartInfo]] = {}
        seed: dict[str, float] = {}
        for name, ref in project.sources.items():
            files = [project.resolve(f) for f in ref.files]
            infos[name] = [self._part_info(f) for f in files]
            if not ref.parts and ref.sync != "auto":
                seed[name] = offsets[name]
            elif ref.parts and ref.sync != "auto":
                seed[name] = float(ref.sync)
            # senão (sync == "auto"): sem posição conhecida, entra na cadeia por áudio
        changed = [False]
        links = self._cached_links(cache, changed)
        positions, warnings = chain_parts(infos, links, master_name, seed)
        return positions, warnings, changed[0]

    def _part_info(self, path: Path) -> PartInfo:
        if not path.exists():
            raise FileNotFoundError(f"parte não encontrada: {path}")
        info = self.prober(path)
        return PartInfo(path, info.duration, info.creation_time)

    def _cached_links(self, cache: dict, changed: list[bool]) -> LinkFinder:
        """Envolve `finder` com cache por par de arquivos e deslocamento esperado (a cadeia testa
        muitos pares, às vezes o mesmo par cego e depois guiado por um `expected` diferente)."""
        store = cache.setdefault("_parts", {})
        near = getattr(self.finder, "near", None)

        def call(a: Path, b: Path, expected: float | None) -> SyncResult:
            key = self._key(a, b)
            bucket = "blind" if expected is None else round(expected, 1)
            cache_id = f"{a}|{b}|{bucket}"
            entry = store.get(cache_id)
            if entry and entry.get("key") == key:
                return SyncResult(float(entry["offset"]), float(entry["confidence"]))
            if expected is None:
                result = self.finder(a, b, 0, 0)
            elif near is not None:
                result = near(a, b, expected, CLOCK_TOLERANCE_S)
            else:  # finder sem busca guiada (ex.: fake de teste): sem como refinar, sem confiança
                result = SyncResult(expected, 0.0)
            store[cache_id] = {"key": key, "offset": result.offset, "confidence": result.confidence}
            changed[0] = True
            return result

        return call

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
