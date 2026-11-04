"""Detectar o andamento (BPM) da música do projeto e, a pedido, gravá-lo na spec.

Usa o analisador `beats` (Achar Batidas) sobre o ARQUIVO da música, e não sobre o item do projeto: o item já passou pelos
efeitos e, com o esticamento ligado, já está no andamento do projeto, e o que se quer saber é o andamento do arquivo. O
valor é uma SUGESTÃO: vem com a confiança e as outras leituras possíveis (a metade e o dobro), e a pessoa pode trocá-lo. Gravar
é uma edição do histórico (`music_tempo_set`), então o desfazer devolve a spec como estava.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.edits import EditError
from ..domain.spec import Project
from ..domain.tempo_grid import TempoError, grid_bars, grid_beats
from .analysis_items import TargetError
from .audio_analysis import AnalysisRequest, AudioAnalysisService
from .edit_history import edit_and_record
from .projects import load_project

# O andamento de uma música não muda com os minutos: os cinco primeiros bastam, e a análise fica leve numa faixa longa
DETECTION_SECONDS = 300.0
# Abaixo desta confiança o andamento é um palpite: a resposta avisa para a pessoa conferir de ouvido
LOW_CONFIDENCE = 0.3


@dataclass
class TempoDetection:
    """O andamento sugerido para a música: `bpm`, onde cai o primeiro tempo no arquivo (`beat_offset`), a confiança, as
    outras leituras e se foi gravado (`applied`)."""

    source: str
    bpm: float
    beat_offset: float
    confidence: float
    alternatives: list[float] = field(default_factory=list)
    applied: bool = False
    warnings: list[str] = field(default_factory=list)
    project: Project | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "bpm": self.bpm,
            "beat_offset": self.beat_offset,
            "confidence": self.confidence,
            "alternatives": self.alternatives,
            "applied": self.applied,
            "warnings": self.warnings,
        }


def detect_music_file(project: Project, service: AudioAnalysisService | None = None) -> TempoDetection:
    """Sugere o andamento do arquivo da música do projeto, sem gravar nada."""
    music = project.audio.music
    if music is None:
        raise TargetError("o projeto não tem música (audio.music) para detectar o andamento")
    path = project.resolve(music.src)
    service = service or AudioAnalysisService()
    request = AnalysisRequest("beats", file=str(path), end=DETECTION_SECONDS, mark=False)
    result = service.analyze(project, request).result
    bpm = getattr(result, "bpm", None)
    offset = getattr(result, "beat_offset", None)
    if bpm is None or offset is None:
        raise TargetError(
            f"não achei um andamento em {Path(music.src).name}: o trecho não tem ataques que se repitam "
            "(informe o BPM à mão)"
        )
    confidence = float(getattr(result, "bpm_confidence", 0.0) or 0.0)
    detection = TempoDetection(
        source=Path(music.src).name,
        bpm=float(bpm),
        beat_offset=float(offset),
        confidence=confidence,
        alternatives=list(getattr(result, "bpm_alternatives", [])),
    )
    if confidence < LOW_CONFIDENCE:
        detection.warnings.append(
            f"confiança baixa ({confidence:.2f}): o ritmo não é regular ou tem pouco ataque; confira o valor de ouvido"
        )
    return detection


def detect_music_tempo(
    name_or_path: str | Path, *, apply: bool = False, service: AudioAnalysisService | None = None
) -> TempoDetection:
    """Detecta o andamento da música do projeto; com `apply`, grava `audio.music.bpm` e `beat_offset` num passo do
    histórico (o esticamento até o andamento do projeto continua uma escolha: `stretch_to_tempo`)."""
    project = load_project(name_or_path)
    detection = detect_music_file(project, service)
    if not apply:
        return detection
    try:
        report, _ = edit_and_record(
            name_or_path,
            {"type": "music_tempo_set", "bpm": detection.bpm, "beat_offset": detection.beat_offset},
        )
    except EditError as exc:
        raise ValueError(str(exc)) from exc
    detection.applied = True
    detection.project = report.project
    return detection


def tempo_summary(project: Project) -> dict[str, Any]:
    """O andamento do projeto e o da música, lado a lado, com a razão do esticamento quando ele está ligado."""
    tempo, music = project.audio.tempo, project.audio.music
    data: dict[str, Any] = {"tempo": None, "music": None}
    if tempo is not None:
        data["tempo"] = {
            "bpm": tempo.bpm,
            "time_signature": tempo.time_signature,
            "offset": tempo.offset,
            "beat_seconds": round(tempo.period, 6),
            "bar_seconds": round(tempo.bar_period, 6),
        }
    if music is not None:
        data["music"] = {
            "bpm": music.bpm,
            "beat_offset": music.beat_offset,
            "stretch_to_tempo": music.stretch_to_tempo,
        }
        if music.stretch_to_tempo and music.bpm is not None and tempo is not None:
            data["music"]["duration_ratio"] = round(music.bpm / tempo.bpm, 6)
    return data


def grid_listing(project: Project, start: float, end: float, level: str = "beat") -> dict[str, Any]:
    """Os instantes da grade em [start, end] (tempos ou inícios de compasso), com o número de cada um (a partir de 1)."""
    tempo = project.audio.tempo
    if tempo is None:
        raise TargetError("o projeto não tem andamento (audio.tempo): defina-o com a operação tempo_set")
    if level not in ("beat", "bar"):
        raise ValueError("`level` é beat ou bar")
    try:
        instants = grid_bars(tempo, start, end) if level == "bar" else grid_beats(tempo, start, end)
    except TempoError as exc:
        raise ValueError(str(exc)) from exc
    step = tempo.bar_period if level == "bar" else tempo.period
    return {
        "level": level,
        "count": len(instants),
        "points": [{"number": round((at - tempo.offset) / step) + 1, "at": at} for at in instants],
    }
