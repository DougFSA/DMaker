"""Cortar no ritmo: propõe, para cada fronteira entre clipes, a batida da música mais perto, e com `apply` anda o corte.

Por padrão só PROPÕE e devolve a lista (nada é gravado). Com `apply`, cada fronteira anda pelas operações de apara que o
editor já tem: a saída do clipe que termina e a entrada do que começa andam o mesmo tanto, então a duração do vídeo não
muda, e os marcadores acompanham pelo mapa de tempo de cada apara. As batidas vêm do Achar Batidas sobre a música (ou
de um grupo de marcadores que a pessoa já tem).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..analysis.rhythm import BoundaryProposal, propose_beat_cuts
from ..domain.spec import ClipSegment, Project
from .analysis_items import TargetError
from .audio_analysis import AnalysisRequest, AudioAnalysisService
from .edit_time import owned_intervals
from .edits import apply_edit_report
from .layout import aggregate_by_origin, project_layout
from .missing import MissingMedia
from .projects import load_project, project_path, save_project

DEFAULT_TOLERANCE = 0.2  # 200 ms: mais que isso o corte já mudaria o que a pessoa escolheu mostrar
DEFAULT_BEAT_GROUP = "batidas"


@dataclass
class BeatCutOutcome:
    beats: int
    bpm: float | None
    tolerance: float
    applied: bool
    proposals: list[BoundaryProposal]
    moved: int = 0
    warnings: list[str] = field(default_factory=list)
    project: Project | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "beats": self.beats,
            "bpm": self.bpm,
            "tolerance_s": self.tolerance,
            "applied": self.applied,
            "moved": self.moved,
            "proposals": [proposal.to_dict() for proposal in self.proposals],
            "warnings": self.warnings,
        }


def _boundaries(
    project: Project, service: AudioAnalysisService
) -> tuple[list[tuple[int, float]], dict[int, str]]:
    """As fronteiras entre trechos seguidos (índice do trecho que termina, instante) e as que não podem andar."""
    layout = aggregate_by_origin(
        project, project_layout(project, service.prober, service.offset_finder, MissingMedia.scan(project))
    )
    owned = owned_intervals(layout.spans)
    boundaries = [(index, owned[index][1]) for index in range(len(owned) - 1)]
    skipped: dict[int, str] = {}
    for index, _ in boundaries:
        before, after = project.timeline[index], project.timeline[index + 1]
        if not isinstance(before, ClipSegment) or not isinstance(after, ClipSegment):
            skipped[index] = "só anda o corte entre dois clipes de vídeo"
        elif after.transition is not None:
            skipped[index] = "há uma transição entre os trechos"
    return boundaries, skipped


def _beat_instants(
    project: Project, service: AudioAnalysisService, source: str, group: str | None, params: dict
) -> tuple[list[float], float | None]:
    """As batidas no tempo do projeto: as do grupo de marcadores pedido, ou as do Achar Batidas sobre `source`."""
    if group is not None:
        marked = sorted(marker.begin for marker in project.markers if marker.group == group)
        if marked:
            return marked, None
    request = AnalysisRequest("beats", params, target=source)
    outcome = service.analyze(project, request)
    if outcome.clock is None:
        raise TargetError(
            "as batidas desse alvo não têm lugar na linha do tempo: use a música ou a saída final"
        )
    times = [outcome.clock.to_project(outcome.interval[0] + beat) for beat in outcome.result.beats]  # type: ignore[attr-defined]
    return times, outcome.result.bpm  # type: ignore[attr-defined]


def _move(
    project: Project, proposal: BoundaryProposal, service: AudioAnalysisService
) -> tuple[Project, list[str]]:
    """Anda uma fronteira: a saída do clipe que termina e a entrada do que começa andam `shift` segundos."""
    shift = proposal.shift
    assert shift is not None and proposal.beat is not None
    warnings: list[str] = []
    for side, index in (("out", proposal.index), ("in", proposal.index + 1)):
        report = apply_edit_report(
            project,
            {"type": "trim", "index": index, "side": side, "delta": shift},
            service.prober,
            service.offset_finder,
        )
        project = report.project
        warnings += report.warnings
    return project, warnings


def cut_on_beat(
    name_or_path: str | Path,
    *,
    source: str = "audio.music",
    tolerance: float = DEFAULT_TOLERANCE,
    apply: bool = False,
    group: str | None = None,
    params: dict | None = None,
    service: AudioAnalysisService | None = None,
    save: Callable[[Project], Any] | None = None,
) -> BeatCutOutcome:
    """Propõe (e, com `apply`, aplica) o corte de cada fronteira entre clipes na batida mais perto."""
    if tolerance <= 0:
        raise ValueError("a tolerância precisa ser maior que zero")
    project = load_project(name_or_path)
    service = service or AudioAnalysisService()
    beats, bpm = _beat_instants(project, service, source, group, dict(params or {}))
    boundaries, skipped = _boundaries(project, service)
    if not boundaries:
        raise ValueError("o projeto tem um trecho só: não há fronteira para cortar no ritmo")
    proposals = propose_beat_cuts(boundaries, beats, tolerance, skipped)
    outcome = BeatCutOutcome(len(beats), bpm, tolerance, apply, proposals)
    if not beats:
        outcome.warnings.append(
            "nenhuma batida encontrada: ajuste o limiar do Achar Batidas ou escolha outro alvo."
        )
    if not apply:
        return outcome
    for position, proposal in enumerate(proposals):
        if not proposal.moves:
            continue
        # os cortes que já andaram podem ter mudado esta fronteira (o arquivo limita a apara): reconta o quanto falta
        current = dict(_boundaries(project, service)[0])[proposal.index]
        assert proposal.beat is not None
        shift = proposal.beat - current
        if abs(shift) > tolerance:
            proposals[position] = BoundaryProposal(
                proposal.index, current, None, None, "o corte anterior mudou esta fronteira"
            )
            continue
        revised = BoundaryProposal(proposal.index, current, proposal.beat, shift)
        project, notes = _move(project, revised, service)
        outcome.warnings += notes
        outcome.moved += 1
        proposals[position] = revised
        landed = dict(_boundaries(project, service)[0])[proposal.index]
        if abs(landed - proposal.beat) > 0.01:
            outcome.warnings.append(
                f"trecho {proposal.index + 1}: o arquivo do clipe acabou antes da batida e o corte parou em {landed:.2f} s."
            )
    outcome.project = project
    if outcome.moved:
        (save or (lambda changed: save_project(changed, project_path(name_or_path).parent)))(project)
    return outcome
