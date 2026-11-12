"""Cadastro de personas: as prontas (versionadas no repositório, somente leitura) e as do usuário (dado da máquina).

Cada persona é uma pasta `<raiz>/<id>/` com `persona.json` e, nos tipos que usam arquivos (uma foto, um avatar), os
arquivos dela. As prontas ficam em `assets/personas/` e as criadas pelo usuário em `config.PERSONAS_DIR`, fora do
git, como as vozes. As duas raízes são lidas na hora do uso, para os testes poderem apontá-las para pastas temporárias.
"""

from __future__ import annotations

import re
import shutil
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .. import config
from ..domain.persona import PERSONA_FILE, Persona
from .engine import PersonaEngineError, engine_for


class PersonaNotFoundError(ValueError):
    """Persona inexistente no cadastro (a mensagem lista as que existem)."""


def slugify(name: str) -> str:
    """Nome livre vira id de pasta: sem acento, minúsculas, hifens."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    if not slug:
        raise ValueError(f"O nome {name!r} não gera um id válido; use letras ou números.")
    return slug


class PersonaLibrary:
    def __init__(self, root: Path | None = None, presets_root: Path | None = None) -> None:
        self._root = root
        self._presets_root = presets_root

    @property
    def root(self) -> Path:
        return self._root or config.PERSONAS_DIR

    @property
    def presets_root(self) -> Path:
        return self._presets_root or config.PERSONA_PRESETS_DIR

    @staticmethod
    def _load(folder: Path, builtin: bool) -> Persona:
        persona = Persona.model_validate_json((folder / PERSONA_FILE).read_text(encoding="utf-8"))
        return persona.model_copy(update={"folder": folder, "builtin": builtin})

    def _scan(self, root: Path, builtin: bool) -> list[Persona]:
        if not root.exists():
            return []
        return [self._load(p.parent, builtin) for p in sorted(root.glob(f"*/{PERSONA_FILE}"))]

    def list(self) -> list[Persona]:
        """Todas as personas, as prontas primeiro."""
        return [*self._scan(self.presets_root, True), *self._scan(self.root, False)]

    def get(self, persona_id: str) -> Persona:
        for persona in self.list():
            if persona.id == persona_id:
                return persona
        known = ", ".join(p.id for p in self.list()) or "nenhuma persona cadastrada"
        raise PersonaNotFoundError(f"Persona {persona_id!r} não encontrada. Personas disponíveis: {known}.")

    def _check(self, persona: Persona) -> Persona:
        """Confere o tipo e a aparência no motor do tipo e preenche os padrões da aparência."""
        engine = engine_for(persona.kind)
        checked = persona.model_copy(update={"appearance": engine.normalize_appearance(persona.appearance)})
        for field, wanted, allowed in (
            ("expressions", checked.expressions, engine.expressions),
            ("gestures", checked.gestures, engine.gestures),
        ):
            unknown = [name for name in wanted if name not in allowed]
            if unknown:
                raise PersonaEngineError(
                    f"{field}: {', '.join(unknown)} não existe no tipo {checked.kind}; use: {', '.join(allowed)}."
                )
        return checked

    def create(
        self,
        name: str,
        kind: str = "2d",
        voice: str | None = None,
        appearance: Mapping[str, Any] | None = None,
        expressions: list[str] | None = None,
        gestures: list[str] | None = None,
    ) -> Persona:
        persona_id = slugify(name)
        if any(p.id == persona_id for p in self.list()):
            raise ValueError(f"Já existe a persona {persona_id!r}. Apague-a antes ou escolha outro nome.")
        persona = self._check(
            Persona(
                id=persona_id,
                name=name.strip(),
                kind=kind,  # type: ignore[arg-type] - a validação do Pydantic recusa o tipo que não existe
                voice=voice,
                appearance=dict(appearance or {}),
                expressions=expressions or [],
                gestures=gestures or [],
            )
        )
        return self._write(persona)

    def update(self, persona_id: str, changes: Mapping[str, Any]) -> Persona:
        """Edita campos de uma persona do usuário: `name`, `voice`, `appearance` (mescla com a atual), `expressions`
        e `gestures`. O tipo e o id não mudam (outro tipo é outra persona)."""
        current = self._editable(persona_id)
        allowed = {"name", "voice", "appearance", "expressions", "gestures"}
        unknown = sorted(set(changes) - allowed)
        if unknown:
            raise ValueError(f"Campo(s) que a persona não aceita editar: {', '.join(unknown)}.")
        data = current.model_dump()
        for key, value in changes.items():
            if key == "appearance":
                data["appearance"] = {**current.appearance, **dict(value)}
            elif key == "name":
                data["name"] = str(value).strip()
            else:
                data[key] = value
        updated = self._check(Persona.model_validate(data).model_copy(update={"folder": current.folder}))
        return self._write(updated)

    def remove(self, persona_id: str) -> None:
        persona = self._editable(persona_id)
        assert persona.folder is not None
        shutil.rmtree(persona.folder)

    def _editable(self, persona_id: str) -> Persona:
        persona = self.get(persona_id)
        if persona.builtin:
            raise ValueError(
                f"{persona_id!r} é uma persona pronta e não pode ser alterada nem apagada; "
                "crie outra com `dmaker persona create`."
            )
        return persona

    def _write(self, persona: Persona) -> Persona:
        folder = self.root / persona.id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / PERSONA_FILE).write_text(persona.model_dump_json(indent=1), encoding="utf-8")
        return persona.model_copy(update={"folder": folder, "builtin": False})
