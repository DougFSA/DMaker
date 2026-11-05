"""O catálogo dos efeitos de áudio, montado a partir das classes registradas: dados puros para o MCP, a CLI
e a interface listarem os efeitos com os parâmetros, as faixas e as unidades. Efeito novo aparece aqui sozinho."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from .base import EFFECT_CLASSES, EffectBase, effect_type, is_literal

# "points" é uma lista de pontos `{at, db}` (a curva do envelope): a interface a desenha, não a escreve em um campo;
# "profile" é o nome de um perfil de ruído do projeto (`audio.noise_profiles`) ou "auto": a interface o escolhe numa lista;
# "band_gains" é a lista fixa de ganhos em dB do EQ Gráfico (um por banda, `options` traz a frequência de cada uma) e
# "freq_points" a lista de pontos `{hz, db}` do EQ por Curva: a interface os desenha como controles deslizantes e como
# um gráfico de pontos arrastáveis; "text" é um campo de texto livre (os dígitos do DTMF, o arquivo do Importar Amostras)
# um som gerado `{generator, params}` (a portadora do Vocoder): a interface o escolhe entre os geradores do catálogo de sons;
# "plugin_format" é o formato (lv2 ou ladspa), que a interface não mostra: vem do plugin escolhido; "plugin" é o nome do plugin LV2 ou LADSPA do efeito Plugin (a interface o escolhe na lista dos instalados) e "plugin_params"
# os valores dos controles dele, `{nome: número}`: a interface monta um controle por controle que o próprio plugin declara
ParamKind = Literal[
    "number",
    "integer",
    "boolean",
    "choice",
    "points",
    "profile",
    "band_gains",
    "freq_points",
    "text",
    "carrier",
    "plugin",
    "plugin_format",
    "plugin_params",
]


@dataclass(frozen=True)
class ParamInfo:
    """Um parâmetro: nome na spec, rótulo, tipo, unidade, padrão e faixa (vazios quando não há)."""

    name: str
    label: str
    kind: ParamKind
    unit: str
    default: Any
    minimum: float | None
    maximum: float | None
    hint: str
    options: tuple[str, ...] = ()
    # a condição para a interface mostrar o campo, `{"mode": "semitones"}`: só aparece com esse valor em `mode`; vazio: sempre
    shown_when: dict[str, Any] | None = None


@dataclass(frozen=True)
class ActionInfo:
    """Uma ação do efeito (`EffectAction`) como o catálogo a mostra: a interface a desenha como um botão que preenche os
    campos de `fills`; o MCP e a CLI a chamam pelo `id`."""

    id: str
    label: str
    hint: str
    fills: tuple[str, ...]
    needs_range: bool


@dataclass(frozen=True)
class EffectInfo:
    """Um efeito do catálogo: o `type` da spec, os nomes (português e Audacity), o que faz e os parâmetros."""

    type: str
    label: str
    audacity_name: str
    summary: str
    changes_duration: bool
    parameters: tuple[ParamInfo, ...]
    # só existe com uma seleção ou uma curva (Cortar, Envelope): o menu genérico da interface não o oferece
    needs_selection: bool = False
    # trabalha sobre as amostras (Redução de ruído, Reparar): não vale no áudio mestre, que roda num grafo ao vivo
    sample_stage: bool = False
    # tem resposta de frequência calculada sem o ffmpeg (os efeitos do EQ): a interface desenha o gráfico dele
    has_response: bool = False
    # o que o efeito sabe fazer além de ser aplicado (o Noise Gate sugere o limiar a partir do ruído)
    actions: tuple[ActionInfo, ...] = ()

    def to_dict(self) -> dict:
        return _plain(asdict(self))


def _plain(value: Any) -> Any:
    """Os dados como o JSON os devolve (tuplas viram listas): o que a API entrega é igual ao que o MCP entrega."""
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def _kind(annotation: Any, declared: str = "") -> ParamKind:
    if declared:
        return declared  # type: ignore[return-value]
    if get_origin(annotation) is list:
        return "points"
    if is_literal(annotation):
        return "choice"
    if annotation is bool:
        return "boolean"
    if annotation is int:
        return "integer"
    return "number"


def _bounds(metadata: list[Any]) -> tuple[float | None, float | None]:
    """Menor e maior valor aceitos, lidos das restrições do campo (`ge`/`gt` e `le`/`lt`). Cada restrição do
    Pydantic é um objeto com o atributo de mesmo nome, então não depende de importar a biblioteca delas."""
    low = high = None
    for item in metadata:
        low = getattr(item, "ge", getattr(item, "gt", low))
        high = getattr(item, "le", getattr(item, "lt", high))
    return low, high


def _options(annotation: Any, extra: dict) -> tuple[str, ...]:
    """As opções de uma escolha (os valores do `Literal`) ou, num campo de lista, os nomes que `param(options=)` deu."""
    if is_literal(annotation):
        return tuple(str(option) for option in get_args(annotation))
    return tuple(str(option) for option in extra.get("options", ()))


def param_info(name: str, cls: type[BaseModel]) -> ParamInfo:
    """Um parâmetro de qualquer modelo montado com `param()` (efeito ou analisador): o catálogo dos dois é o mesmo."""
    field = cls.model_fields[name]
    extra = field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {}
    low, high = _bounds(field.metadata)
    low, high = extra.get("minimum", low), extra.get("maximum", high)
    annotation = field.annotation
    return ParamInfo(
        name=name,
        label=str(extra.get("label", name)),
        kind=_kind(annotation, str(extra.get("kind", ""))),
        unit=str(extra.get("unit", "")),
        default=to_jsonable_python(field.get_default(call_default_factory=True)),
        minimum=low,
        maximum=high,
        hint=field.description or "",
        options=_options(annotation, extra),
        shown_when=extra.get("shown_when"),
    )


def effect_info(cls: type[EffectBase]) -> EffectInfo:
    own = [name for name in cls.model_fields if name not in EffectBase.model_fields]
    return EffectInfo(
        type=effect_type(cls),
        label=cls.label,
        audacity_name=cls.audacity_name,
        summary=cls.summary,
        changes_duration=cls.changes_duration,
        parameters=tuple(param_info(name, cls) for name in own),
        needs_selection=cls.needs_selection,
        sample_stage=cls.item_only(),
        has_response=cls.has_response,
        actions=tuple(
            ActionInfo(action.id, action.label, action.hint, action.fills, action.needs_range)
            for action in cls.actions
        ),
    )


def catalog() -> list[EffectInfo]:
    """Todos os efeitos registrados, na ordem em que foram registrados."""
    return [effect_info(cls) for cls in EFFECT_CLASSES.values()]


# onde uma cadeia de efeitos pode ficar, como o `target` das operações de edição a escreve; `may_grow` diz se
# um efeito que muda a duração (Repetir) é aceito ali
EFFECT_TARGETS: tuple[dict[str, Any], ...] = (
    {"target": "timeline.N", "label": "Som do clipe (N: posição do trecho)", "may_grow": False},
    {"target": "overlays.N", "label": "Áudio de um PiP (N: posição da sobreposição)", "may_grow": False},
    {"target": "audio.voiceover.N", "label": "Voz gravada", "may_grow": True},
    {"target": "audio.narration.N", "label": "Narração sintetizada", "may_grow": False},
    {"target": "audio.generated.N", "label": "Som gerado (Tom, Ruído, Bipe...)", "may_grow": False},
    {"target": "audio.music", "label": "Música", "may_grow": True},
    {"target": "audio.tracks.N", "label": "Faixa externa sincronizada", "may_grow": False},
    {"target": "audio.master", "label": "Mistura inteira, antes da normalização final", "may_grow": False},
)


def catalog_payload(effect_type_name: str | None = None, brand: str | None = None) -> dict[str, Any]:
    """O catálogo como a API, o MCP e a CLI o entregam: os efeitos (todos, ou só o de `effect_type_name`), os
    campos comuns a todo efeito, os lugares onde a cadeia pode ficar e as predefinições (cadeias prontas que a ação
    `preset` põe no item). Com `brand`, as macros da marca entram junto com as globais. Um nome que não existe é erro."""
    effects = catalog()
    if effect_type_name is not None:
        effects = [info for info in effects if info.type == effect_type_name]
        if not effects:
            known = ", ".join(sorted(EFFECT_CLASSES))
            raise ValueError(f"Efeito de áudio desconhecido: {effect_type_name!r}. Use um de: {known}")
    from .presets import preset_catalog

    return {
        "effects": [info.to_dict() for info in effects],
        "common": [_plain(asdict(info)) for info in common_parameters()],
        "targets": [dict(target) for target in EFFECT_TARGETS],
        "presets": preset_catalog(brand),
    }


def common_parameters() -> tuple[ParamInfo, ...]:
    """Os campos que todo efeito tem (`enabled`, `start`, `end`): a interface os mostra à parte, no cabeçalho
    do efeito e no seletor de intervalo, em vez de repetir em cada formulário."""
    return tuple(param_info(name, EffectBase) for name in ("enabled", "start", "end"))
