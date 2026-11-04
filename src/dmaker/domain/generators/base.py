"""Base e registro dos geradores de som: cada gerador (Tom, Chirp, Ruído, DTMF...) é uma classe Pydantic registrada aqui.

A classe diz o que a spec aceita (tipo, parâmetros, faixas) e o que o catálogo mostra (nome em português, nome no
Audacity, unidade de cada parâmetro). Quem produz as amostras é a função registrada em `filtergraph.generators` com o
mesmo `type`. Os dois registros precisam listar os mesmos tipos (há teste). O molde é o dos efeitos de áudio
(`domain.audio_effects`), e os parâmetros usam o mesmo `param()`, então o catálogo e os formulários são os mesmos.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import ClassVar, TypeVar

from pydantic import BaseModel, ConfigDict

from ..audio_effects.base import EFFECT_SAMPLE_RATE, param

__all__ = [
    "GENERATOR_CLASSES",
    "GENERATOR_SAMPLE_RATE",
    "GeneratorBase",
    "generator_type",
    "param",
    "register_generator",
]

# todo gerador registrado, pelo nome do tipo; a validação de `audio.generated[].params` sai desta tabela
GENERATOR_CLASSES: dict[str, type[GeneratorBase]] = {}

# A taxa em que o som gerado nasce: a da mixagem, para o atraso até o instante dele ser exato em amostras
GENERATOR_SAMPLE_RATE = EFFECT_SAMPLE_RATE

# Duração sugerida de um gerador que não tem uma duração natural (Tom, Ruído...): um segundo basta para ouvir
DEFAULT_DURATION = 1.0


class GeneratorBase(BaseModel):
    """O que todo gerador tem: um `type` fixo por classe e os parâmetros do som. A posição no tempo, a duração, o
    volume e os efeitos são do item da spec (`GeneratedSound`), iguais para qualquer gerador."""

    model_config = ConfigDict(extra="forbid")

    type: str

    # metadados do catálogo, fixos por classe
    label: ClassVar[str]  # nome em português
    audacity_name: ClassVar[str]  # nome do gerador no Audacity, para quem vem de lá
    summary: ClassVar[str]  # o que faz, em uma frase
    # a família agrupa os geradores no menu da interface: "tons", "ruído", "telefonia", "instrumentos", "ritmo", "dados"
    family: ClassVar[str] = "tons"
    # o gerador cuja duração é decidida pelos parâmetros (o ritmo pelas batidas, o DTMF pelos dígitos) sugere esta duração
    has_natural_duration: ClassVar[bool] = False

    def natural_duration(self, resolve: Callable[[str], Path] | None = None) -> float:
        """Quanto dura o som quando ninguém diz: a duração que os parâmetros pedem, ou `DEFAULT_DURATION`. `resolve` leva
        um caminho da spec ao arquivo (o gerador de amostras conta as linhas do texto dele)."""
        return DEFAULT_DURATION

    def describe(self) -> str:
        """O nome curto do som na linha do tempo (o gerador e o que o distingue: a frequência, os dígitos, o andamento)."""
        return self.label

    def files(self) -> list[str]:
        """Os arquivos que o gerador lê, como a spec os escreve: entram na chave de cache e na checagem de ausência."""
        return []


GeneratorClass = TypeVar("GeneratorClass", bound=type[GeneratorBase])


def register_generator(cls: GeneratorClass) -> GeneratorClass:
    """Registra a classe pelo `type` fixo dela (o valor padrão do campo `type`)."""
    name = cls.model_fields["type"].default
    if not isinstance(name, str) or not name:
        raise TypeError(f"{cls.__name__}: `type` precisa ser um Literal com valor padrão")
    if name in GENERATOR_CLASSES:
        raise ValueError(f"Gerador de som já registrado: {name}")
    GENERATOR_CLASSES[name] = cls
    return cls


def generator_type(generator: GeneratorBase | type[GeneratorBase]) -> str:
    """O nome do tipo de um gerador (instância ou classe)."""
    cls = generator if isinstance(generator, type) else type(generator)
    return cls.model_fields["type"].default
