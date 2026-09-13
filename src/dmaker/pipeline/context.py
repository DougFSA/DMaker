"""Objetos compartilhados entre as etapas do pipeline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..domain.brand import Theme
from ..domain.presets import Preset
from ..domain.spec import Project
from ..media.ffmpeg import FFmpegRunner
from ..media.probe import MediaInfo

if TYPE_CHECKING:  # pragma: no cover
    pass

Prober = Callable[[Path], MediaInfo]


@dataclass
class RenderOptions:
    preview: bool = False
    dry_run: bool = False
    force: bool = False
    quiet: bool = False
    guides: bool | None = None
    out: Path | None = None
    preset: str | None = None
    no_captions: bool = False
    thumbnail: bool = True
    segments: tuple[int, int] | None = None  # render parcial: só os trechos [primeiro, último] (índices)


@dataclass
class RenderResult:
    output: Path
    duration: float
    preset: Preset
    warnings: list[str]
    thumbnail: Path | None = None
    captions_file: Path | None = None
    commands: list[str] = field(default_factory=list)
    job_dir: Path | None = None
    size_bytes: int = 0


@dataclass
class RenderContext:
    """Tudo que as etapas precisam saber sobre o render em curso."""

    project: Project
    options: RenderOptions
    theme: Theme
    preset: Preset
    fps: float
    job_dir: Path
    cache_dir: Path
    runner: FFmpegRunner
    prober: Prober
    warnings: list[str] = field(default_factory=list)
    log: Callable[[str], None] = lambda message: None  # noqa: E731 - etapas do render (terminal, interface)
    session: dict[str, Any] = field(
        default_factory=dict
    )  # fontes sincronizadas por nome (pipeline.sources.Source)

    @property
    def width(self) -> int:
        return self.preset.width

    @property
    def height(self) -> int:
        return self.preset.height

    @property
    def scale(self) -> float:
        """Fator para medidas definidas na base 1080 (lado menor)."""
        return self.preset.short_side / 1080

    @property
    def has_brand(self) -> bool:
        return self.theme.key != "default"

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        self.log(f"aviso: {message}")
