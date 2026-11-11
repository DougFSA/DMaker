"""Macros de áudio a partir de um projeto: salvar a cadeia de efeitos de um item como macro.

É a ponte entre a spec (o item e a cadeia dele) e a pasta de macros (`domain/audio_effects/user_presets`): a interface, o
MCP e a CLI chamam esta mesma função, então os três salvam a mesma lista de efeitos.
"""

from __future__ import annotations

from typing import Literal

from ..domain.audio_effects import EffectPreset, save_user_preset
from ..domain.edits import EditError
from ..domain.effect_edits import item_chain
from ..domain.spec import Project

MacroScope = Literal["global", "brand"]
SCOPES = ("global", "brand")


def macro_brand(project: Project, scope: str) -> str | None:
    """A marca em que a macro vai ficar: nenhuma no escopo global, a do projeto no escopo da marca."""
    if scope not in SCOPES:
        raise ValueError(f"escopo desconhecido: {scope!r} (use global ou brand)")
    if scope == "global":
        return None
    if not project.brand:
        raise ValueError(
            "este projeto não tem marca: salve a macro como global ou escolha uma marca para o projeto"
        )
    return project.brand


def save_chain_as_macro(
    project: Project,
    target: str,
    label: str,
    *,
    scope: str = "global",
    summary: str = "",
    output: dict | None = None,
) -> EffectPreset:
    """Salva a cadeia de efeitos do item `target` como a macro `label`. O intervalo e o bypass de cada efeito ficam de
    fora (pertencem ao item), então aplicar a macro em outro item dá a mesma lista de efeitos, ligados e sem intervalo."""
    try:
        chain = item_chain(project, target)
    except EditError as exc:
        raise ValueError(str(exc)) from exc
    if not chain:
        raise ValueError(f"o item {target} não tem efeitos para salvar como macro")
    return save_user_preset(label, chain, summary, output=output, brand=macro_brand(project, scope))
