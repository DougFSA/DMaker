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

SpeakerMode = Literal["per_speaker", "per_segment", "single"]
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
    speaker: str | None = (
        None  # "Falante 1"...: quem fala; só o modo per_speaker preenche (e o usuário corrige)
    )
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


class DubSpeaker(Strict):
    """Um falante achado na diarização e o trecho do arquivo que serve de referência da voz clonada dele."""

    name: str = Field(min_length=1)  # "Falante 1"
    # Trecho de 3 a 15 s só com a fala dele, escolhido na preparação. Fica gravado no projeto para que corrigir o
    # falante de uma fala não mude a referência e, com ela, a voz de todas as outras falas da pessoa.
    reference_start: float | None = Field(default=None, ge=0)
    reference_end: float | None = None
    reference_text: str | None = None

    @model_validator(mode="after")
    def _reference_is_a_span(self) -> DubSpeaker:
        has_start, has_end = self.reference_start is not None, self.reference_end is not None
        if has_start != has_end:
            raise ValueError(f"{self.name}: a referência precisa de início e fim juntos.")
        if self.reference_start is not None and self.reference_end is not None:
            if self.reference_end <= self.reference_start:
                raise ValueError(f"{self.name}: o fim da referência precisa ser maior que o início.")
            if not (self.reference_text or "").strip():
                raise ValueError(f"{self.name}: a referência precisa do texto falado nela.")
        return self

    @property
    def has_reference(self) -> bool:
        return self.reference_start is not None


class DubProject(Strict):
    source: str  # arquivo de origem (vídeo ou áudio)
    source_language: str = "pt"
    target_language: str
    segments: list[DubSegment]
    # Voz original por baixo da dublada, em dB (estilo voice-over, ex.: -18). None: só a voz dublada.
    keep_original_db: float | None = Field(default=None, le=0)
    # per_speaker: um clone por pessoa, montado dos melhores trechos dela (com 1 falante vale como single);
    # per_segment: cada fala clona a voz de quem fala naquele ponto do arquivo (aproximação para vários falantes);
    # single: um só clone para o arquivo todo (voz mais constante quando há um falante só).
    # O padrão do modelo continua per_segment: é o que os projetos antigos, sem este campo, sempre usaram.
    speaker_mode: SpeakerMode = "per_segment"
    speakers: list[DubSpeaker] = Field(default_factory=list)  # preenchido pela diarização (modo per_speaker)
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

    @model_validator(mode="after")
    def _speakers_are_known(self) -> DubProject:
        names = self.speaker_names
        if len(set(names)) != len(names):
            raise ValueError(f"Falantes repetidos: {', '.join(names)}.")
        unknown = sorted({s.speaker for s in self.segments if s.speaker and s.speaker not in names})
        if unknown:
            raise ValueError(
                f"Falante(s) {', '.join(unknown)} sem cadastro no projeto. Falantes: {', '.join(names) or 'nenhum'}."
            )
        return self

    @property
    def speaker_names(self) -> list[str]:
        return [speaker.name for speaker in self.speakers]

    def edited(
        self,
        segment_id: str,
        text: str | None = None,
        locked: bool | None = None,
        speaker: str | None = None,
    ) -> DubProject:
        """Cópia do projeto com a tradução, a trava e/ou o falante de uma fala trocados; a fala original não muda."""
        self.segment(segment_id)  # id desconhecido é erro, não silêncio
        if speaker is not None and speaker not in self.speaker_names:
            known = ", ".join(self.speaker_names) or "nenhum (prepare o projeto no modo per_speaker)"
            raise ValueError(f"Falante {speaker!r} não existe no projeto. Falantes: {known}.")
        changes = {
            k: v for k, v in {"text": text, "locked": locked, "speaker": speaker}.items() if v is not None
        }
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
