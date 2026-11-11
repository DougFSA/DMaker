"""Rotas dos plugins de efeito de terceiros (LV2 e LADSPA): a lista com os controles que cada plugin declara, a varredura e o
habilitar e desabilitar.

Adaptador fino sobre `pipeline.plugins.PluginService` (o mesmo que a ferramenta MCP `audio_plugins` e o comando `dmaker audio
plugins` usam). A interface monta o menu de plugins e os controles do efeito Plugin a partir desta lista, sem saber de plugin
nenhum: um plugin novo aparece depois de uma varredura.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..pipeline.plugins import PluginUnavailable, plugin_service


def build_audio_plugins_router() -> APIRouter:
    router = APIRouter(tags=["plugins de áudio"])

    @router.get("/api/audio-plugins")
    def list_plugins() -> dict:
        """Os plugins da última varredura (faz uma se nunca houve), as pastas varridas e o ffmpeg de cada formato."""
        return plugin_service().catalog()

    @router.post("/api/audio-plugins/scan")
    def scan_plugins() -> dict:
        """Varre as pastas de novo (depois de instalar um plugin ou o ffmpeg dos plugins)."""
        service = plugin_service()
        service.scan()
        return service.catalog()

    @router.get("/api/audio-plugins/{plugin_id}")
    def show_plugin(plugin_id: str) -> dict:
        try:
            return plugin_service().catalog(plugin_id)
        except PluginUnavailable as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/api/audio-plugins/{plugin_id}/enable")
    def enable_plugin(plugin_id: str) -> dict:
        return _set_enabled(plugin_id, True)

    @router.post("/api/audio-plugins/{plugin_id}/disable")
    def disable_plugin(plugin_id: str) -> dict:
        return _set_enabled(plugin_id, False)

    def _set_enabled(plugin_id: str, enabled: bool) -> dict:
        service = plugin_service()
        try:
            service.set_enabled(plugin_id, enabled)
            return service.catalog(plugin_id)
        except PluginUnavailable as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
