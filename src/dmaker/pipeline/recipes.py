"""Receitas: operações compostas que fazem em uma chamada o que a ferramenta simples faz em várias.

Valem para qualquer IA que use o servidor MCP, mas pesam mais no agente local: cada volta ao modelo custa
minutos na CPU, então "narrar este roteiro e pôr no projeto" ou "montar o explicativo destes assuntos" têm de
ser um passo só. Nada aqui executa por conta própria: as receitas chamam os mesmos serviços das ferramentas
simples (`set_field`, `project_from_template`, o corte automático) e o disco entra por injeção.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import config
from ..domain.edits import set_field
from ..domain.spec import Project
from ..media.probe import probe
from .context import Prober
from .projects import load_project, project_from_template, project_path
from .projects import save_project as save_project_file


class RecipeError(ValueError):
    """O pedido da receita não fecha; a mensagem diz o que corrigir, em português."""


@dataclass(frozen=True)
class NarrationRequest:
    text: str
    voice: str | None = None
    start: float = 0.0
    language: str = "pt"
    speed: float = 1.0
    seed: int | None = None
    captions: bool = True  # usa o texto falado como legenda (sem transcrever de novo)


def add_narration(project: Project, request: NarrationRequest) -> Project:
    """O projeto com a narração somada às que ele já tinha e, se pedido, o texto falado como legenda."""
    if not request.text.strip():
        raise RecipeError("O texto da narração está vazio.")
    item: dict[str, Any] = {
        "text": request.text.strip(),
        "start": request.start,
        "language": request.language,
        "speed": request.speed,
    }
    if request.voice:
        item["voice"] = request.voice
    if request.seed is not None:
        item["seed"] = request.seed
    existing = [narration.model_dump(exclude_none=True) for narration in project.audio.narration]
    updated = set_field(project, "audio.narration", [*existing, item])
    if not request.captions:
        return updated
    # sem bloco de legendas ainda, cria um; com ele, só troca a fonte e mantém o estilo que o projeto já tinha
    if updated.captions is None:
        return set_field(updated, "captions", {"source": "narration"})
    return set_field(updated, "captions.source", "narration")


def narrate_into_project(
    name_or_path: str,
    request: NarrationRequest,
    check_voice: Callable[[str], object] = lambda voice_id: None,
    load: Callable[[str], Project] = load_project,
    save: Callable[[Project], Path] = save_project_file,
) -> tuple[Project, Path]:
    """Põe a narração no projeto salvo. `check_voice` falha na hora se a voz não existe (e não só no render)."""
    if request.voice:
        check_voice(request.voice)
    project = add_narration(load(name_or_path), request)
    return project, save(project)


MIXED_ENDS = "Informe o 'fim' de todos os assuntos ou de nenhum (aí divido a gravação em partes iguais)."


def check_subject_ends(subjects: Sequence[dict[str, Any]]) -> bool:
    """`True` se todos os assuntos trazem `fim`, `False` se nenhum traz; recusa lista vazia e mistura dos dois.

    Misturar obrigaria a adivinhar onde o assunto sem `fim` termina, e a receita prefere perguntar.
    """
    if not subjects:
        raise RecipeError("Informe pelo menos um assunto.")
    given = ["fim" in subject for subject in subjects]
    if any(given) and not all(given):
        raise RecipeError(MIXED_ENDS)
    return all(given)


def distribute_subject_ends(subjects: Sequence[dict[str, Any]], total: float | None) -> list[dict[str, Any]]:
    """Dá o `fim` de cada assunto: os que o usuário informou, ou uma divisão igual da gravação se nenhum informou."""
    if check_subject_ends(subjects):
        return [dict(subject) for subject in subjects]
    if not total:
        raise RecipeError(
            "Não sei a duração da gravação para dividir entre os assuntos; informe o 'fim' de cada um."
        )
    count = len(subjects)
    return [
        {**subject, "fim": round(total, 2) if index == count - 1 else round(total * (index + 1) / count, 2)}
        for index, subject in enumerate(subjects)
    ]


def build_explainer(
    name: str,
    recording: str,
    subjects: Sequence[dict[str, Any]],
    options: dict[str, Any] | None = None,
    prober: Prober = probe,
    create: Callable[[str, str, dict], Project] = project_from_template,
) -> Project:
    """Cria o projeto do template `explicativo` já com os `fim` dos assuntos completos (medindo a gravação)."""
    needs_total = not check_subject_ends(subjects)  # recusa antes de medir a gravação
    total = prober(Path(recording)).duration if needs_total else None
    params: dict[str, Any] = {
        "gravacao": recording,
        "assuntos": distribute_subject_ends(subjects, total),
        **(options or {}),
    }
    return create("explicativo", name, params)


def cut_summary(result: dict[str, Any]) -> dict[str, Any]:
    """O resultado compacto do corte automático para o modelo: o essencial, sem a lista inteira de cortes."""
    report = result["report"]
    return {
        "project": result["project"],
        "spec_path": result["spec_path"],
        "duration_before_s": report["duration_before_s"],
        "duration_after_s": report["duration_after_s"],
        "removed_s": report["removed_s"],
        "removed_percent": report["removed_percent"],
        "cuts_by_reason": report["counts"],
        "captions": True,
        "warnings": result.get("warnings", []),
        "next": "Confira com list_cuts e gere a prévia com render_project (preview=true).",
    }


def project_exists(name: str) -> bool:
    return project_path(name).exists()


def project_names() -> list[str]:
    """Os nomes dos projetos que existem em `projects/`, lidos na hora (a pasta pode ser trocada)."""
    return sorted(spec.parent.name for spec in config.PROJECTS_DIR.glob("*/spec.json"))


PREVIEW_NEXT = "Isto é só a prévia em baixa resolução, não o vídeo final. Para entregar o vídeo final, chame de novo sem preview."


def preview_notice(payload: dict[str, Any], preview: bool) -> dict[str, Any]:
    """Marca a prévia como prévia: quem lê o resultado (uma IA pequena, principalmente) não a entrega como final."""
    if preview:
        payload["preview"] = True
        payload["next"] = PREVIEW_NEXT
    return payload
