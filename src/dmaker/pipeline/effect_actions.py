"""Ações de efeito: o que um efeito sabe fazer além de ser aplicado, servido igual na interface, no MCP e na CLI.

O Noise Gate, por exemplo, sabe "Analisar ruído": lê um trecho em que ninguém fala e devolve o limiar que serve. A
ação é DECLARADA na classe do efeito (`EffectBase.actions`, que o catálogo entrega, com os campos que ela preenche) e
EXECUTADA aqui, registrada por `@register_effect_action("<tipo>", "<ação>")`. A interface, a rota e o MCP não têm `if` por
tipo de efeito: eles leem o catálogo, mostram um botão por ação e chamam `run_effect_action`. Um teste prende que toda
ação declarada tem corpo e que todo corpo tem a ação declarada.

Uma ação só LÊ: ela nunca grava a spec. Quem decide gravar o valor que ela sugere é a pessoa (o botão preenche o campo, e
o `Salvar` do editor, ou o `edit_project`, grava).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..domain.audio_effects import EFFECT_CLASSES
from ..domain.audio_effects.restoration import AUTO_PROFILE
from ..domain.edits import EditError
from ..domain.spec import Project
from ..filtergraph.audio_effects.registry import SAMPLE_RATE
from ..media.ffmpeg import SubprocessRunner
from ..media.gate import NOISE_PERCENTILE, SUGGESTED_MARGIN_DB, noise_level_db, suggested_threshold_db
from ..media.probe import probe
from .context import Prober
from .layout import OriginAggregate, aggregate_by_origin, project_layout
from .missing import MissingMedia
from .noise_profiles import ProfileLocator
from .restoration_ops import noise_window
from .sample_reader import AudioSlice, FFmpegSampleReader, SampleReader

ActionRunner = Callable[[Project, dict, OriginAggregate], dict[str, Any]]

_RUNNERS: dict[tuple[str, str], ActionRunner] = {}

# O trecho é lido como o item chega aos efeitos: estéreo, na taxa da mistura
READ_CHANNELS = 2


def register_effect_action(effect_type: str, action_id: str) -> Callable[[ActionRunner], ActionRunner]:
    """Registra o corpo da ação `action_id` do efeito `effect_type`. A ação precisa estar declarada na classe do efeito,
    senão o catálogo não a mostraria: o erro aparece na hora de importar, e não numa tela sem botão."""

    def decorator(runner: ActionRunner) -> ActionRunner:
        cls = EFFECT_CLASSES.get(effect_type)
        if cls is None or action_id not in {action.id for action in cls.actions}:
            raise ValueError(f"a ação {action_id!r} não está declarada no efeito {effect_type!r}")
        if (effect_type, action_id) in _RUNNERS:
            raise ValueError(f"ação de efeito já registrada: {effect_type}.{action_id}")
        _RUNNERS[(effect_type, action_id)] = runner
        return runner

    return decorator


def registered_actions() -> set[tuple[str, str]]:
    return set(_RUNNERS)


def run_effect_action(
    project: Project,
    effect_type: str,
    action_id: str,
    params: dict,
    *,
    prober: Prober = probe,
    reader: SampleReader | None = None,
) -> dict[str, Any]:
    """Executa a ação sobre o projeto (a spec da tela, gravada ou não) e devolve o que ela mediu e os valores que sugere
    para os campos (`fills`, com o nome do campo na spec). `params` traz o que a ação pede (`target`, `profile`, `start`,
    `end`). Pedido que não faz sentido é `EditError` com o motivo."""
    runner = _RUNNERS.get((effect_type, action_id))
    if runner is None:
        known = ", ".join(f"{kind}.{name}" for kind, name in sorted(_RUNNERS)) or "nenhuma"
        raise EditError(f"ação de efeito desconhecida: {effect_type}.{action_id}. Use uma de: {known}")
    layout = aggregate_by_origin(project, project_layout(project, prober, None, MissingMedia.scan(project)))
    layout.reader = reader or FFmpegSampleReader(SubprocessRunner(quiet=True))
    result = runner(project, params, layout)
    return {"effect": effect_type, "action": action_id, **result}


# ---------- Noise Gate: analisar ruído ----------


@register_effect_action("noise_gate", "analyze_noise")
def analyze_noise(project: Project, params: dict, layout: OriginAggregate) -> dict[str, Any]:
    """Mede o ruído de um trecho em que ninguém fala e sugere o limiar do gate: o nível do ruído mais 6 dB.

    O trecho é, nesta ordem: o `start`/`end` (ou `region`) pedido; o perfil de ruído do projeto nomeado em `profile`
    (`audio.noise_profiles`, do DMK-55); ou, sem nenhum dos dois (ou com `profile: "auto"`), o trecho mais quieto do
    item `target`, uma janela de 0,5 s. O nível é o percentil 95 dos picos de 1 ms (a régua do detector do gate), então
    um estalo solto no trecho não leva o limiar para cima; a margem de 6 dB deixa o chiado, cujo pico oscila uns 3 dB,
    sempre abaixo do limiar."""
    reader = layout.reader
    assert reader is not None
    profile = params.get("profile") or AUTO_PROFILE
    explicit = any(params.get(key) is not None for key in ("start", "end", "region"))
    if profile != AUTO_PROFILE and not explicit:
        session = layout.physical.session if layout.physical else {}
        try:
            audio = ProfileLocator(project, session).slice(profile)
        except ValueError as exc:
            raise EditError(str(exc)) from exc
        stored = project.audio.noise_profiles[profile]
        where = {"target": stored.target, "start": stored.start, "end": stored.end}
        source = f"perfil {profile}"
    else:
        target, found, first, last = noise_window(project, {"type": "audio_effect", **params}, layout)
        audio = found.slice(first, last)
        where = {"target": target.path, "start": round(first, 6), "end": round(last, 6)}
        source = "trecho marcado" if explicit else "trecho mais quieto do item"
    samples = reader.read(audio, rate=SAMPLE_RATE, channels=READ_CHANNELS)
    if len(samples) == 0:
        raise EditError(f"não consegui ler o trecho de ruído de {_name(audio)}")
    noise = noise_level_db(samples, SAMPLE_RATE)
    threshold = round(suggested_threshold_db(noise), 1)
    return {
        "fills": {"threshold_db": threshold},
        "noise_db": round(noise, 1),
        "margin_db": SUGGESTED_MARGIN_DB,
        "percentile": NOISE_PERCENTILE,
        "window": where,
        "source": source,
        "message": f"Ruído de {noise:.1f} dB ({source}); limiar sugerido: {threshold:.1f} dB.",
    }


def _name(audio: AudioSlice) -> str:
    return audio.path.name
