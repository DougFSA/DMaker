"""O registro dos analisadores de áudio: cada um é uma classe Pydantic registrada aqui, como os efeitos de áudio.

A classe diz o que a spec do pedido aceita (os parâmetros, com nome, unidade e faixa do Audacity) e roda a análise
(`analyze`), uma função pura sobre as amostras. O resultado é sempre um dado estruturado (`AnalysisResult`), que o
MCP devolve como JSON. Para criar um analisador novo, ponha a classe num arquivo de `analysis/analyzers/`,
decorada com `@register_analyzer`: a pasta é importada sozinha e o catálogo (MCP, CLI e interface) o mostra.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from ..domain.audio_effects.base import param
from ..domain.audio_effects.catalog import ParamInfo, param_info
from .signal import Signal

# todo analisador registrado, pelo nome do tipo
ANALYZER_CLASSES: dict[str, type[AnalyzerBase]] = {}

__all__ = [
    "ANALYZER_CLASSES",
    "AnalysisResult",
    "AnalyzerBase",
    "AnalyzerInfo",
    "MarkerProposal",
    "analyzer_catalog",
    "analyzer_class",
    "param",
    "parse_analyzer",
    "register_analyzer",
]


@dataclass(frozen=True)
class MarkerProposal:
    """Um marcador que a análise propõe, em segundos do sinal analisado: um instante (`end` vazio) ou uma região."""

    start: float
    end: float | None
    text: str


@dataclass(kw_only=True)
class AnalysisResult:
    """O que todo analisador devolve: o nome dele e uma frase para a pessoa. Cada analisador acrescenta os campos
    dele; `to_dict` os entrega como JSON (sem numpy), e `markers` diz onde a análise marcaria o áudio."""

    analyzer: str
    summary: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, detail: str = "compact", limit: int | None = None) -> dict[str, Any]:
        """O resultado como JSON puro. `detail="full"` entrega também as listas longas por inteiro (a curva do
        espectro, as amostras), que `compact` reduz a `limit` itens (cada analisador tem o seu padrão)."""
        return asdict(self)

    def markers(self) -> list[MarkerProposal]:
        """Os marcadores que esta análise propõe (vazio quando ela só mede)."""
        return []

    def table(self, separator: str = ",") -> str | None:
        """A tabela de texto (CSV com vírgula, TXT com tabulação) que a análise exporta, ou None se ela não exporta."""
        return None


class AnalyzerBase(BaseModel):
    """Os parâmetros de um analisador. O `type` é o nome na spec do pedido, fixo em cada subclasse."""

    model_config = ConfigDict(extra="forbid")

    type: str

    # metadados do catálogo, fixos por classe
    label: ClassVar[str]  # nome em português
    audacity_name: ClassVar[str]  # nome da função no Audacity, para quem vem de lá
    summary: ClassVar[str]  # o que faz, em uma frase
    # True quando a análise é feita para marcar (Marcar Sons, Achar Batidas): o padrão do pedido é gravar os marcadores
    marks_by_default: ClassVar[bool] = False
    # o grupo de marcadores onde ela escreve, quando marca; a pessoa pode trocar o nome
    marker_group: ClassVar[str] = ""
    # a cor (#RRGGBB) dos marcadores que ela escreve: o grupo se reconhece na linha do tempo
    marker_color: ClassVar[str | None] = None
    # os formatos de arquivo que o resultado exporta além do JSON ("csv", "txt", "png")
    exports: ClassVar[tuple[str, ...]] = ()

    def analyze(self, signal: Signal) -> AnalysisResult:
        raise NotImplementedError


@dataclass(frozen=True)
class AnalyzerInfo:
    """Um analisador do catálogo: o `type`, os nomes, o que faz, o que exporta e os parâmetros."""

    type: str
    label: str
    audacity_name: str
    summary: str
    marks: bool
    marks_by_default: bool
    marker_group: str
    exports: tuple[str, ...]
    parameters: tuple[ParamInfo, ...]

    def to_dict(self) -> dict[str, Any]:
        return _plain(asdict(self))


def _plain(value: Any) -> Any:
    """Os dados como o JSON os devolve (tuplas viram listas): a API entrega o mesmo que o MCP entrega."""
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


Analyzer = TypeVar("Analyzer", bound=type[AnalyzerBase])


def register_analyzer(cls: Analyzer) -> Analyzer:
    """Registra a classe pelo `type` fixo dela (o valor padrão do campo `type`)."""
    name = cls.model_fields["type"].default
    if not isinstance(name, str) or not name:
        raise TypeError(f"{cls.__name__}: `type` precisa ser um Literal com valor padrão")
    if name in ANALYZER_CLASSES:
        raise ValueError(f"Analisador já registrado: {name}")
    ANALYZER_CLASSES[name] = cls
    return cls


def analyzer_class(name: str) -> type[AnalyzerBase]:
    """A classe do analisador `name`, ou um erro em português listando os que existem."""
    try:
        return ANALYZER_CLASSES[name]
    except KeyError:
        known = ", ".join(sorted(ANALYZER_CLASSES))
        raise ValueError(f"Analisador desconhecido: {name!r}. Use um de: {known}") from None


def parse_analyzer(name: str, params: dict[str, Any] | None = None) -> AnalyzerBase:
    """O analisador `name` com os parâmetros dados, validados contra as faixas dele. Parâmetro desconhecido ou fora
    da faixa vira `ValueError` com o nome do campo, em vez da mensagem comprida do Pydantic."""
    cls = analyzer_class(name)
    try:
        return cls.model_validate({**(params or {}), "type": name})
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            where = ".".join(str(part) for part in error["loc"]) or name
            problems.append(f"{where}: {error['msg']}")
        raise ValueError(f"Parâmetros inválidos para {name}: " + "; ".join(problems)) from exc


def analyzer_info(cls: type[AnalyzerBase]) -> AnalyzerInfo:
    own = [fname for fname in cls.model_fields if fname not in AnalyzerBase.model_fields]
    return AnalyzerInfo(
        type=cls.model_fields["type"].default,
        label=cls.label,
        audacity_name=cls.audacity_name,
        summary=cls.summary,
        marks=cls.marks_by_default or bool(cls.marker_group),
        marks_by_default=cls.marks_by_default,
        marker_group=cls.marker_group,
        exports=cls.exports,
        parameters=tuple(param_info(fname, cls) for fname in own),
    )


# de onde a análise lê o som: os alvos de um item (os mesmos dos efeitos), a saída final e um arquivo solto
ANALYSIS_SOURCES: tuple[dict[str, Any], ...] = (
    {"source": "timeline.N", "label": "Som do clipe (N: posição do trecho)"},
    {"source": "overlays.N", "label": "Áudio de um PiP (N: posição da sobreposição)"},
    {"source": "audio.voiceover.N", "label": "Voz gravada"},
    {"source": "audio.narration.N", "label": "Narração sintetizada (precisa estar sintetizada)"},
    {"source": "audio.music", "label": "Música"},
    {"source": "audio.tracks.N", "label": "Faixa externa sincronizada"},
    {"source": "output", "label": "A saída final já renderizada"},
    {"source": "file", "label": "Um arquivo de áudio ou vídeo solto (informe `file`)"},
)


def analyzer_catalog(name: str | None = None) -> dict[str, Any]:
    """O catálogo como a API, o MCP e a CLI o entregam: os analisadores (todos, ou só o `name`) e de onde o som
    pode vir. Um nome que não existe é erro."""
    classes = list(ANALYZER_CLASSES.values()) if name is None else [analyzer_class(name)]
    return {
        "analyzers": [analyzer_info(cls).to_dict() for cls in classes],
        "sources": [dict(source) for source in ANALYSIS_SOURCES],
    }
