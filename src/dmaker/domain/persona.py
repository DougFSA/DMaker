"""Personas: personagens reutilizáveis que falam no vídeo (ilustrada 2D, 3D e, depois, realista).

O modelo é dado puro, sem disco nem motor: o cadastro mora em `persona/library.py` e cada tipo é desenhado por um
motor registrado em `persona/engine.py`. Aqui ficam também os pedaços da spec que o trecho e a sobreposição da
persona compartilham (fala e marcas), para a spec do projeto só montá-los.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PersonaKind = Literal["2d", "3d", "realistic"]
PERSONA_FILE = "persona.json"
DEFAULT_EXPRESSION = "neutral"
MAX_SPEECH_SPEED = 2.0
# Ritmo médio da fala em português a velocidade 1 (o mesmo de `pipeline/voiceover.py`): só estima a duração antes de
# sintetizar, para a vista da linha do tempo. A duração real vem do áudio.
CHARS_PER_SECOND = 14.0
MIN_ESTIMATE_SECONDS = 0.5


def estimate_speech_seconds(text: str, speed: float = 1.0) -> float:
    """Duração aproximada da fala de `text`, sem sintetizar."""
    return max(len(text.strip()) / CHARS_PER_SECOND / speed, MIN_ESTIMATE_SECONDS)


class PersonaModel(BaseModel):
    """Base estrita, como a `Strict` da spec (que não pode ser importada aqui: a spec importa este módulo)."""

    model_config = ConfigDict(extra="forbid")


class Persona(PersonaModel):
    """Uma persona cadastrada: quem ela é, que voz tem e como se parece.

    `appearance` é livre aqui e validada pelo motor do tipo (cada tipo tem os seus campos). `expressions` e
    `gestures` restringem o que a persona aceita; vazio significa tudo o que o tipo sabe fazer."""

    id: str
    name: str
    kind: PersonaKind = "2d"
    voice: str | None = None  # id da biblioteca de vozes; sem ele, a voz automática do motor de fala
    appearance: dict[str, Any] = {}
    expressions: list[str] = []
    gestures: list[str] = []
    created: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds"))
    # preenchidos pela biblioteca ao carregar; não vão para o `persona.json`
    folder: Path | None = Field(default=None, exclude=True)
    builtin: bool = Field(default=False, exclude=True)

    def fingerprint(self) -> str:
        """Identidade do visual da persona para o cache do clipe: o tipo, a aparência e os arquivos da pasta dela
        (uma foto, um avatar). A voz e o nome não entram: não mudam um quadro sequer."""
        digest = hashlib.sha256()
        digest.update(json.dumps([self.id, self.kind, self.appearance], sort_keys=True).encode("utf-8"))
        if self.folder is not None and self.folder.is_dir():
            for path in sorted(p for p in self.folder.rglob("*") if p.is_file() and p.name != PERSONA_FILE):
                digest.update(path.relative_to(self.folder).as_posix().encode("utf-8"))
                digest.update(path.read_bytes())
        return digest.hexdigest()[:16]


class PersonaMark(PersonaModel):
    """Um momento da fala em que a persona muda de expressão ou faz um gesto (`at` em segundos desde o início
    da fala dela). A expressão vale até a próxima marca de expressão; o gesto é um movimento curto."""

    at: float = Field(ge=0)
    expression: str | None = None
    gesture: str | None = None

    @model_validator(mode="after")
    def _one_of(self) -> PersonaMark:
        if (self.expression is None) == (self.gesture is None):
            raise ValueError("a marca precisa de `expression` ou de `gesture`, um dos dois e não os dois")
        return self


class PersonaSpeech(PersonaModel):
    """O que a persona fala: um texto (sintetizado com a voz dela) ou um arquivo de áudio já gravado."""

    text: str | None = None
    audio: str | None = None
    language: str = "pt"
    speed: float = Field(1.0, ge=0.5, le=MAX_SPEECH_SPEED)
    instruct: str | None = None  # jeito de falar, como em `Narration.instruct`
    seed: int | None = None  # fixa a síntese: o mesmo texto soa igual a cada render
    volume: float = Field(1.0, ge=0, le=4)

    @model_validator(mode="after")
    def _one_source(self) -> PersonaSpeech:
        if bool(self.text and self.text.strip()) == bool(self.audio):
            raise ValueError(
                "a fala da persona precisa de `text` (o texto) ou de `audio` (um arquivo), um dos dois"
            )
        return self
