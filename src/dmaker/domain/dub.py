"""Projeto de dublagem: o roteiro de um vídeo ou áudio traduzido, editável à mão e guardado em JSON.

Cada segmento traz a fala original, a tradução (que o usuário pode corrigir) e o tempo dela no arquivo de
origem. O projeto é o contrato entre a preparação (transcrever e traduzir) e a geração (sintetizar e
montar): editar o JSON e gerar de novo refaz só as falas que mudaram.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .spec import Strict

SpeakerMode = Literal["per_segment", "single"]
# O que fazer quando a fala traduzida não cabe no tempo da original:
# voz: avança na pausa, comprime na síntese e acelera a voz (o vídeo nunca muda);
# video: a voz fica na velocidade natural e o vídeo estica naquele trecho;
# misto: a voz acelera até o limite do `atempo` e o vídeo estica no que ainda faltar.
FitMode = Literal["voz", "video", "misto"]
FIT_MODES: tuple[str, ...] = ("voz", "video", "misto")
PROJECT_SUFFIX = ".dub.json"


class DubSegment(Strict):
    """Uma fala: o que foi dito entre `start` e `end` (segundos no arquivo) e como será dito no idioma alvo."""

    id: str = Field(min_length=1)
    start: float = Field(ge=0)
    end: float
    source_text: str
    text: str  # a tradução; é o que o usuário edita
    speaker: str | None = None  # reservado para a diarização futura; hoje nada o preenche
    locked: bool = False  # travada: traduzir de novo não mexe nesta tradução

    @model_validator(mode="after")
    def _end_after_start(self) -> DubSegment:
        if self.end <= self.start:
            raise ValueError(
                f"A fala {self.id}: o fim ({self.end}) precisa ser maior que o início ({self.start})."
            )
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start


class DubProject(Strict):
    source: str  # arquivo de origem (vídeo ou áudio)
    source_language: str = "pt"
    target_language: str
    segments: list[DubSegment]
    # Voz original por baixo da dublada, em dB (estilo voice-over, ex.: -18). None: só a voz dublada.
    keep_original_db: float | None = Field(default=None, le=0)
    # per_segment: cada fala clona a voz de quem fala naquele ponto do arquivo (vale para vários falantes);
    # single: um só clone para o arquivo todo (voz mais constante quando há um falante só).
    speaker_mode: SpeakerMode = "per_segment"
    voice: str | None = None  # voz da biblioteca no lugar do clone
    fit_mode: FitMode = "voz"  # o padrão mantém o comportamento de sempre: a voz se ajusta, o vídeo não
    translator_model: str = ""
    glossary: list[str] = Field(
        default_factory=list
    )  # termos que não se traduzem, além do dicionário de pronúncia
    brand: str | None = None  # marca cujo dicionário de pronúncia vale

    @field_validator("segments")
    @classmethod
    def _unique_ids(cls, segments: list[DubSegment]) -> list[DubSegment]:
        ids = [segment.id for segment in segments]
        repeated = sorted({i for i in ids if ids.count(i) > 1})
        if repeated:
            raise ValueError(f"Ids de fala repetidos: {', '.join(repeated)}.")
        return segments

    def edited(self, segment_id: str, text: str | None = None, locked: bool | None = None) -> DubProject:
        """Cópia do projeto com a tradução e/ou a trava de uma fala trocadas; a fala original não muda."""
        self.segment(segment_id)  # id desconhecido é erro, não silêncio
        changes = {k: v for k, v in {"text": text, "locked": locked}.items() if v is not None}
        segments = [s.model_copy(update=changes) if s.id == segment_id else s for s in self.segments]
        return self.model_copy(update={"segments": segments})

    def segment(self, segment_id: str) -> DubSegment:
        for segment in self.segments:
            if segment.id == segment_id:
                return segment
        known = ", ".join(s.id for s in self.segments)
        raise KeyError(f"Fala {segment_id!r} não existe no projeto. Ids: {known}.")


def load_dub_project(path: Path) -> DubProject:
    if not path.is_file():
        raise FileNotFoundError(f"Projeto de dublagem não encontrado: {path}")
    return DubProject.model_validate_json(path.read_text(encoding="utf-8"))


def save_dub_project(project: DubProject, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(project.model_dump(), ensure_ascii=False, indent=2)
    path.write_text(payload + "\n", encoding="utf-8")
    return path
