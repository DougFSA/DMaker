"""O construtor do efeito Plugin: o filtro `lv2` ou `ladspa` do ffmpeg com os controles da spec, adaptado às portas de áudio do
plugin (`filtergraph.plugins`)."""

from __future__ import annotations

from ...domain.audio_effects.plugin import Plugin
from ...domain.plugins import PluginPorts
from ..plugins import plugin_lines
from .registry import EffectRequest, register_builder

# Sem a varredura (um teste do grafo, uma simulação) não se sabe as portas: estéreo dos dois lados passa o sinal direto.
UNKNOWN_PORTS = PluginPorts(2, 2)


@register_builder("plugin")
def build_plugin(request: EffectRequest) -> list[str]:
    effect = request.effect
    assert isinstance(effect, Plugin)
    return plugin_lines(
        effect.format,
        effect.plugin,
        effect.params,
        request.ports or UNKNOWN_PORTS,
        request.source,
        request.out,
        request.tag,
    )
