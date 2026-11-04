"""Base e registro dos efeitos de áudio: cada efeito é uma classe Pydantic registrada aqui.

A classe diz o que a spec aceita (tipo, parâmetros, faixas) e o que o catálogo mostra (nome em português, nome
no Audacity, unidade de cada parâmetro). Quem monta o grafo do ffmpeg é a função registrada em
`filtergraph.audio_effects`, com o mesmo `type`. Os dois registros precisam listar os mesmos tipos (há teste).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

# todo efeito registrado, pelo nome do tipo; `AudioEffect` (a união da spec) sai desta tabela
EFFECT_CLASSES: dict[str, type[EffectBase]] = {}

# Abaixo disto (1 microssegundo) um intervalo é arredondamento, não um trecho de som
EPSILON = 1e-6

# A taxa a que o som de um item é levado antes dos efeitos (o formato da mixagem): as contas em amostras, como o limite
# de 128 amostras do Reparar, valem nela
EFFECT_SAMPLE_RATE = 48000


def param(
    default: Any,
    *,
    label: str,
    unit: str = "",
    hint: str = "",
    kind: str = "",
    low: float | None = None,
    high: float | None = None,
    options: Sequence[str] | None = None,
    **constraints: Any,
) -> Any:
    """Campo de parâmetro de efeito: além da faixa (`ge`, `le`...), leva o rótulo em português e a unidade que o
    catálogo mostra na interface, no MCP e na CLI. O padrão é o do Audacity quando ele tem um. `kind` força o tipo que
    o catálogo anuncia quando o tipo do Python não diz tudo (`profile`: o nome de um perfil de ruído do projeto;
    `band_gains` e `freq_points`: as listas do EQ). `low` e `high` dão a faixa dos ITENS de uma lista (que `ge` e `le`
    não expressam), e `options` os nomes das posições de uma lista de tamanho fixo."""
    extra: dict[str, Any] = {"label": label, "unit": unit}
    if kind:
        extra["kind"] = kind
    if low is not None:
        extra["minimum"] = low
    if high is not None:
        extra["maximum"] = high
    if options is not None:
        extra["options"] = list(options)
    return Field(default, description=hint or label, json_schema_extra=extra, **constraints)


@dataclass(frozen=True)
class EffectAction:
    """Uma ação que o catálogo oferece ao lado dos parâmetros de um efeito: ela lê o som do item e devolve valores para
    preencher campos (o Noise Gate sugere o limiar a partir de um trecho silencioso). `fills` nomeia os campos que a
    resposta preenche, `needs_range` diz se a ação mede um trecho (`start`/`end` do item) ou o item todo. Quem a executa
    é registrado em `pipeline.effect_actions` com o mesmo par (tipo do efeito, `id`)."""

    id: str
    label: str
    hint: str
    fills: tuple[str, ...]
    needs_range: bool = True


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
    # True quando o efeito trata o próprio intervalo (Cortar, Envelope): o construtor recebe o sinal inteiro, sem
    # a emenda de 10 ms nem o recorte de `start`/`end` que `filtergraph.audio_effects.chain` faz para os outros
    owns_interval: ClassVar[bool] = False
    # True quando o efeito só existe com uma seleção ou uma curva desenhada (Cortar, Envelope): o menu genérico
    # "adicionar efeito" da interface não o oferece, e quem o cria é a edição de onda (`edit_project`, o editor de onda)
    needs_selection: ClassVar[bool] = False
    # True quando o efeito troca o tempo do som de lugar (Repetir, Reverter, Cortar): depois dele o instante do item
    # já não é o instante do arquivo, e dividir, juntar, aparar e copiar um trecho do arquivo não têm resposta certa
    reorders_time: ClassVar[bool] = False
    # True quando o efeito trabalha sobre as amostras em numpy (`register_sample_builder`), e não como filtro do ffmpeg:
    # ele precisa do sinal inteiro na memória, então não roda dentro do grafo ao vivo da mistura (o áudio mestre o recusa)
    sample_stage: ClassVar[bool] = False
    # True quando a resposta de frequência do efeito é conhecida por conta pura (`frequency_response`): a interface desenha
    # o gráfico dele sem rodar o ffmpeg. O registro das contas está em `filtergraph.audio_effects`; um teste prende os dois
    has_response: ClassVar[bool] = False
    # ações do catálogo deste efeito (ver `EffectAction`); o corpo de cada uma é registrado em `pipeline.effect_actions`
    actions: ClassVar[tuple[EffectAction, ...]] = ()

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

    def measure_kind(self) -> str:
        """O que a passada de medida lê para este efeito: `peak` (o `astats` por canal, o de sempre), `lufs` (o loudness
        integrado, pelo `ebur128`) ou `rms` (o nível RMS da mistura dos canais). Só vale quando `needs_measure()` é
        verdadeiro; os efeitos que já existiam não declaram nada e ficam com a medida de pico."""
        return "peak"

    def noise_profile(self) -> str | None:
        """A referência de perfil de ruído que o efeito pede (`auto` ou o nome de um perfil do projeto), ou None quando
        ele não usa perfil. O processador mede o espectro dela antes de aplicar o efeito."""
        return None

    def alters_duration(self) -> bool:
        """Se ESTA instância muda a duração do item. É `changes_duration` para quase todos; o Cortar decide pelo
        parâmetro (completar com silêncio mantém a duração, não completar encurta), por isso a conta é por instância."""
        return self.changes_duration

    def rebased(self, origin: float, length: float) -> EffectBase | None:
        """O mesmo efeito para um pedaço do item que começa em `origin` (segundos do item) e dura `length`: o
        intervalo anda junto com o som, e o que cai fora do pedaço some (devolve None quando nada sobra). É o que
        divide, apara e cola um trecho sem deixar um silêncio ou um corte no lugar errado."""
        if self.start is None and self.end is None:
            return self
        first = 0.0 if self.start is None else self.start - origin
        last = float("inf") if self.end is None else self.end - origin
        low, high = max(first, 0.0), min(last, length)
        if high - low <= EPSILON:
            return None
        new_start = None if low <= EPSILON else round(low, 6)
        new_end = None if self.end is None or high >= length - EPSILON else round(high, 6)
        return self.model_copy(update={"start": new_start, "end": new_end})

    def shifted(self, delta: float) -> EffectBase:
        """O mesmo efeito `delta` segundos mais tarde no item (o intervalo anda; sem intervalo fica igual)."""
        if self.start is None and self.end is None:
            return self
        start = None if self.start is None else round(self.start + delta, 6)
        end = None if self.end is None else round(self.end + delta, 6)
        return self.model_copy(update={"start": start, "end": end})

    def stitched(self, following: EffectBase, boundary: float) -> EffectBase | None:
        """Este efeito (do pedaço de antes, que dura `boundary`) juntado ao `following` (do pedaço de depois) num
        efeito só, ou None quando não são o mesmo efeito com os mesmos parâmetros e o intervalo não é contínuo na
        emenda. Desfaz o `rebased` de uma divisão (Juntar)."""
        if type(self) is not type(following) or _params(self) != _params(following):
            return None
        reaches_end = self.end is None or self.end >= boundary - EPSILON
        starts_at_zero = following.start is None or following.start <= EPSILON
        if self.start is None and self.end is None and following.start is None and following.end is None:
            return self
        if self.start is None and self.end is None or following.start is None and following.end is None:
            return None
        if not (reaches_end and starts_at_zero):
            return None
        end = None if following.end is None else round(following.end + boundary, 6)
        return self.model_copy(update={"end": end})

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


def _params(effect: EffectBase) -> dict[str, Any]:
    """Os parâmetros do efeito sem o intervalo: dois efeitos são "o mesmo" quando isto é igual."""
    return effect.model_dump(exclude={"start", "end"})


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
