"""Avisos dos plugins que um projeto usa: o plugin que não está instalado (ou está desabilitado, ou não roda) e o controle que o
plugin não tem. São avisos, não erros: o render pula o efeito de plugin que não pode rodar e segue, então o projeto continua
válido e a pessoa fica sabendo antes de renderizar, com o nome do plugin."""

from __future__ import annotations

from typing import Any, Protocol

from ..domain.plugins import fit_params
from ..domain.spec import Project
from .plugins import PluginUnavailable, ResolvedPlugin, plugin_service


class PluginLookup(Protocol):
    def resolve(self, format_name: str, ref: str) -> ResolvedPlugin: ...


def plugin_references(project: Project) -> list[dict[str, Any]]:
    """Os efeitos de plugin do projeto (como dicionários da spec), de qualquer item e do master."""
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "plugin" and "plugin" in node:
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(project.model_dump(mode="json"))
    return found


def plugin_warnings(project: Project, lookup: PluginLookup | None = None) -> list[str]:
    """Um aviso por plugin ausente, desabilitado ou que não roda aqui, com o nome dele, e um por controle que o plugin não tem ou
    que está fora da faixa que ele declara (o render usa o limite mais próximo, ou ignora o controle). Um projeto sem efeito de plugin não consulta nada."""
    references = plugin_references(project)
    if not references:
        return []
    lookup = lookup or plugin_service()
    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()
    for node in references:
        format_name, ref = str(node.get("format", "")), str(node["plugin"])
        try:
            resolved = lookup.resolve(format_name, ref)
        except PluginUnavailable as exc:
            if (format_name, ref) not in seen:
                warnings.append(f"{exc}; o render pula esse efeito e segue sem ele.")
            seen.add((format_name, ref))
            continue
        warnings += fit_params(
            resolved.info, {str(k): float(v) for k, v in (node.get("params") or {}).items()}
        ).problems
    return warnings
