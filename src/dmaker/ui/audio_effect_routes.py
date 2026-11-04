"""Rotas dos efeitos de áudio da interface: o catálogo, a resposta de frequência, as predefinições salvas, as ações de um
efeito e o nível de um item.

Adaptador fino sobre `domain.audio_effects.catalog_payload` (o mesmo que a ferramenta MCP `audio_effects` e o comando
`dmaker audio effects` entregam), `pipeline.effect_actions` (o que a ferramenta `audio_effect_action` e `dmaker audio
effect action` fazem) e `pipeline.item_level`. A interface monta o painel "Efeitos" (adicionar do catálogo, as
predefinições, o formulário de parâmetros e o botão de cada ação) a partir do catálogo, então um efeito novo aparece
lá sem tocar no front. As rotas de ação e de nível recebem a spec da tela (ainda não salva): o efeito que a pessoa acabou
de pôr já conta.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from .. import config
from ..domain.audio_effects import (
    catalog_payload,
    list_user_presets,
    remove_user_preset,
    save_user_preset,
)
from ..domain.edits import EditError
from ..domain.spec import Project
from ..media.ffmpeg import FFmpegError


class EffectActionBody(BaseModel):
    """Uma ação de efeito sobre a spec da tela: o efeito, a ação e o que ela pede (o item, o perfil, o trecho)."""

    spec: dict
    effect: str
    action: str
    target: str | None = None
    profile: str | None = None
    start: float | str | None = None
    end: float | str | None = None


class EffectResponseBody(BaseModel):
    """Um efeito de equalização (como a spec o escreve) e quantos pontos o gráfico tem."""

    effect: dict
    points: int = 256


class PresetBody(BaseModel):
    """Uma macro a salvar: o nome, os efeitos da cadeia e, se quiser, uma frase do que faz e a saída (formato do arquivo,
    que só vale ao aplicar a arquivos). `brand` a guarda na pasta dessa marca; sem ele, é global."""

    label: str
    effects: list[dict]
    summary: str = ""
    output: dict | None = None
    brand: str | None = None


class ChainMacroBody(BaseModel):
    """Salvar a cadeia de efeitos de um item da spec da tela como macro: o item, o nome e o escopo (`global` ou `brand`,
    a marca do projeto)."""

    spec: dict
    target: str
    label: str
    scope: str = "global"
    summary: str = ""
    output: dict | None = None


class ItemLevelBody(BaseModel):
    spec: dict
    target: str
    start: float | str | None = None
    end: float | str | None = None


def _project(name: str, spec: dict) -> Project:
    try:
        project = Project.model_validate({**spec, "name": name})
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    project.base_dir = (config.PROJECTS_DIR / name).resolve()
    return project


def build_audio_effects_router() -> APIRouter:
    router = APIRouter(tags=["efeitos de áudio"])

    @router.get("/api/audio-effects")
    def list_audio_effects(type: str | None = None, brand: str | None = None) -> dict:
        try:
            return catalog_payload(type, brand)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/api/audio-effects/response")
    def effect_response(body: EffectResponseBody) -> dict[str, list[float]]:
        """O gráfico de resposta de frequência de um efeito de equalização: conta pura, sem ffmpeg."""
        from ..pipeline.effect_response import effect_frequency_response

        try:
            return effect_frequency_response(body.effect, body.points)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/api/audio-effects/presets")
    def saved_presets(brand: str | None = None) -> dict[str, list[dict]]:
        """As macros que a pessoa salvou, as globais e, com `brand`, as da marca (as embutidas vêm no catálogo)."""
        try:
            return {"presets": [preset.to_dict() for preset in list_user_presets(brand)]}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/api/audio-effects/presets")
    def save_preset(body: PresetBody) -> dict:
        try:
            return save_user_preset(
                body.label, body.effects, body.summary, output=body.output, brand=body.brand
            ).to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/api/projects/{name}/audio-macros")
    def save_chain(name: str, body: ChainMacroBody) -> dict:
        """ "Salvar a cadeia como macro": a cadeia de efeitos do item (da spec da tela, ainda não salva) vira uma macro."""
        from ..pipeline.macros import save_chain_as_macro

        try:
            return save_chain_as_macro(
                _project(name, body.spec),
                body.target,
                body.label,
                scope=body.scope,
                summary=body.summary,
                output=body.output,
            ).to_dict()
        except (EditError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.delete("/api/audio-effects/presets/{preset_id}")
    def delete_preset(preset_id: str, brand: str | None = None) -> dict:
        try:
            return remove_user_preset(preset_id, brand).to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/api/projects/{name}/audio-effect-action")
    def run_action(name: str, body: EffectActionBody) -> dict[str, Any]:
        from ..pipeline.effect_actions import run_effect_action

        params = {"target": body.target, "profile": body.profile, "start": body.start, "end": body.end}
        try:
            return run_effect_action(
                _project(name, body.spec),
                body.effect,
                body.action,
                {key: value for key, value in params.items() if value is not None},
            )
        except (EditError, ValueError, FileNotFoundError, FFmpegError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/api/projects/{name}/audio-level")
    def item_level(name: str, body: ItemLevelBody) -> dict[str, Any]:
        from ..pipeline.item_level import measure_item_level

        try:
            return measure_item_level(_project(name, body.spec), body.target, body.start, body.end)
        except (EditError, ValueError, FileNotFoundError, FFmpegError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router
