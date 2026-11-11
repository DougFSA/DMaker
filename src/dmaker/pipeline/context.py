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
from ..media.matting import Matter
from ..media.probe import MediaInfo

if TYPE_CHECKING:  # pragma: no cover
    from ..filtergraph.audio_effects import Measure
    from .audio_effects import EffectProcessor
    from .auto_duck import DuckPlan
    from .carrier_tracks import CarrierTracks
    from .isolation import IsolationService
    from .narration import NarrationService

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
    matter: Matter | None = None  # recorte de pessoa para trocar o fundo (só quando um trecho pede)
    narrator: NarrationService | None = None  # síntese das narrações; criado na primeira que o projeto pede
    isolator: IsolationService | None = None  # isolamento vocal; criado no primeiro clipe com `audio_mode`
    warnings: list[str] = field(default_factory=list)
    log: Callable[[str], None] = lambda message: None  # noqa: E731 - etapas do render (terminal, interface)
    session: dict[str, Any] = field(
        default_factory=dict
    )  # fontes sincronizadas por nome (pipeline.sources.Source)
    # efeitos de áudio (ver `pipeline/audio_effects.py`): o processador, criado no primeiro item com efeito; os
    # arquivos já processados das faixas externas (um por faixa de `audio.tracks`); e a medida da mistura que
    # cada efeito do master pede, pela posição dele em `audio.master_effects`
    audio_fx: EffectProcessor | None = None
    track_audio: tuple[Path | None, ...] | None = None
    master_measures: dict[int, Measure] = field(default_factory=dict)
    # o plano do Auto Duck (ver `pipeline/auto_duck.py`); None quando o projeto não tem regra
    duck_plan: DuckPlan | None = None
    # as trilhas que o Vocoder ouve como portadora (ver `pipeline/carrier_tracks.py`); None quando nenhum efeito usa `carrier_track`
    carrier_tracks: CarrierTracks | None = None
    # a linha do tempo vista pelo crossfade de som entre clipes vizinhos (`pipeline.audio_crossfade.CutNeighbors`): o
    # preparador de um trecho precisa das fontes e das durações dos vizinhos. O construtor do mezanino a preenche
    cut_neighbors: Any = None
    # as personas do render (ver `pipeline/persona_render.py`): quem sintetiza a fala delas e desenha os clipes. O
    # `RenderPipeline` o preenche; quem monta o contexto sem ele ganha um serviço padrão na primeira persona
    personas: Any = None

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
        if (
            message in self.warnings
        ):  # o mesmo aviso do `lint` e do preparador (o crossfade de som) aparece uma vez
            return
        self.warnings.append(message)
        self.log(f"aviso: {message}")
