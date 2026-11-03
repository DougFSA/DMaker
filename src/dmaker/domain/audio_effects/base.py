"""Base e registro dos efeitos de áudio: cada efeito é uma classe Pydantic registrada aqui.

A classe diz o que a spec aceita (tipo, parâmetros, faixas) e o que o catálogo mostra (nome em português, nome
no Audacity, unidade de cada parâmetro). Quem monta o grafo do ffmpeg é a função registrada em
`filtergraph.audio_effects`, com o mesmo `type`. Os dois registros precisam listar os mesmos tipos (há teste).
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

# todo efeito registrado, pelo nome do tipo; `AudioEffect` (a união da spec) sai desta tabela
EFFECT_CLASSES: dict[str, type[EffectBase]] = {}


def param(default: Any, *, label: str, unit: str = "", hint: str = "", **constraints: Any) -> Any:
    """Campo de parâmetro de efeito: além da faixa (`ge`, `le`...), leva o rótulo em português e a unidade que o
    catálogo mostra na interface, no MCP e na CLI. O padrão é o do Audacity quando ele tem um."""
    return Field(
        default,
        description=hint or label,
        json_schema_extra={"label": label, "unit": unit},
        **constraints,
    )


class EffectBase(BaseModel):
    """O que todo efeito de áudio tem: ligar e desligar sem apagar (`enabled`, o botão de bypass) e um
    intervalo opcional (`start`/`end`, em segundos do sinal que entra no efeito), que é o equivalente a
    selecionar um trecho no Audacity. Fora do intervalo o som passa intacto."""

    model_config = ConfigDict(extra="forbid")

    # nome do efeito na spec; cada subclasse o fixa com um `Literal` (é o discriminador da união)
    type: str
    enabled: bool = param(True, label="Ligado", hint="Desliga o efeito sem apagá-lo (bypass).")
    start: float | None = param(
        None, label="Início do intervalo", unit="s", hint="Vazio: do começo do item.", ge=0
    )
    end: float | None = param(
        None, label="Fim do intervalo", unit="s", hint="Vazio: até o fim do item.", ge=0
    )

    # metadados do catálogo, fixos por classe
    label: ClassVar[str]  # nome em português
    audacity_name: ClassVar[str]  # nome do efeito no Audacity, para quem vem de lá
    summary: ClassVar[str]  # o que faz, em uma frase
    # True quando a saída dura diferente da entrada (Repetir): só vale onde o item pode crescer
    changes_duration: ClassVar[bool] = False

    @model_validator(mode="after")
    def _interval(self) -> EffectBase:
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError(
                f"efeito {self.type}: end ({self.end:g}) precisa ser maior que start ({self.start:g})"
            )
        return self

    def needs_measure(self) -> bool:
        """Se o efeito precisa do pico (e do nível médio) do sinal que entra nele antes de montar o filtro."""
        return False

    def span(self, duration: float) -> tuple[float, float] | None:
        """O intervalo em segundos dentro de um sinal de `duration`, ou None quando o efeito vale no sinal todo
        (sem `start`/`end`, ou cobrindo do começo ao fim)."""
        start = 0.0 if self.start is None else min(self.start, duration)
        end = duration if self.end is None else min(self.end, duration)
        if start <= 0 and end >= duration:
            return None
        return start, max(end, start)

    def output_duration(self, duration: float) -> float:
        """Quanto dura o sinal depois do efeito. Só os efeitos que declaram `changes_duration` mudam isto."""
        return duration


EffectClass = TypeVar("EffectClass", bound=type[EffectBase])


def register_effect(cls: EffectClass) -> EffectClass:
    """Registra a classe pelo `type` fixo dela (o valor padrão do campo `type`)."""
    name = cls.model_fields["type"].default
    if not isinstance(name, str) or not name:
        raise TypeError(f"{cls.__name__}: `type` precisa ser um Literal com valor padrão")
    if name in EFFECT_CLASSES:
        raise ValueError(f"Efeito de áudio já registrado: {name}")
    EFFECT_CLASSES[name] = cls
    return cls


def effect_type(effect: EffectBase | type[EffectBase]) -> str:
    """O nome do tipo de um efeito (instância ou classe)."""
    cls = effect if isinstance(effect, type) else type(effect)
    return cls.model_fields["type"].default


def is_literal(annotation: Any) -> bool:
    """Se a anotação é um `Literal[...]` (o catálogo mostra os valores possíveis como uma escolha)."""
    return getattr(annotation, "__origin__", None) is Literal
