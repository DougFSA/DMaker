"""Registro dos tipos de saída: quem renderiza e quem confere (QA) cada tipo de preset.

O tipo da saída (`video` ou `audio`) sai do nome do preset (`domain/outputs.py`); cada tipo registra aqui o seu
renderizador e, se tem, o seu conferidor de QA. Quem precisa renderizar pede `create_renderer(...)` e nunca decide
por `if` qual pipeline usar: um tipo novo (um EPUB de áudio, uma sequência de imagens) entra registrando os dois,
sem mexer na CLI, no MCP nem na interface.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..domain.outputs import OutputKind, output_kind
from ..domain.spec import Project
from .context import RenderOptions, RenderResult


class Renderer(Protocol):
    """O que todo renderizador oferece: rodar e devolver o resultado."""

    def run(self) -> RenderResult: ...


RendererFactory = Callable[..., Renderer]
# (projeto, arquivo da saída, dependências) -> relatório de QA em texto e em dados; None = o tipo não tem QA
QAFactory = Callable[..., Any]


@dataclass(frozen=True)
class OutputKindHandlers:
    renderer: RendererFactory
    qa: QAFactory | None = None


_KINDS: dict[OutputKind, OutputKindHandlers] = {}


def register_output_kind(kind: OutputKind, renderer: RendererFactory, qa: QAFactory | None = None) -> None:
    _KINDS[kind] = OutputKindHandlers(renderer, qa)


def handlers_for(kind: OutputKind) -> OutputKindHandlers:
    try:
        return _KINDS[kind]
    except KeyError:
        known = ", ".join(sorted(_KINDS)) or "nenhum"
        raise ValueError(
            f"tipo de saída sem renderizador registrado: {kind} (registrados: {known})"
        ) from None


def effective_preset_name(project: Project, options: RenderOptions | None) -> str:
    """O preset que vale no render: o do pedido (`--preset`) ou, sem ele, o da spec."""
    return (options.preset if options else None) or project.output.preset


def create_renderer(project: Project, options: RenderOptions | None = None, **dependencies: Any) -> Renderer:
    """O renderizador do tipo da saída. As dependências (runner, prober, log...) vão para o construtor; cada tipo
    usa as que conhece e ignora as outras."""
    kind = output_kind(effective_preset_name(project, options))
    return handlers_for(kind).renderer(project, options, **dependencies)


def qa_builder(project: Project, preset_name: str | None = None) -> QAFactory | None:
    """O conferidor de QA do tipo da saída, se o tipo tem um."""
    return handlers_for(output_kind(preset_name or project.output.preset)).qa


def default_output_name(project_name: str, preset_id: str, suffix: str, extension: str) -> str:
    """O nome do arquivo de saída quando ninguém dá o caminho: `projeto__preset-id.ext`, como o vídeo sempre foi."""
    return f"{project_name}__{preset_id.replace('/', '-')}{suffix}{extension}"


def output_path_in(directory: Path, project_name: str, preset_id: str, suffix: str, extension: str) -> Path:
    return directory / default_output_name(project_name, preset_id, suffix, extension)
