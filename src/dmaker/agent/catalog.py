"""Catálogo de modelos do servidor local: o que está instalado, o que está carregado e como descarregar.

Antes de a pessoa escolher o modelo da conversa, a tela precisa saber o que cada um faz (aceita imagem? usa ferramentas?
raciocina?), quanto pesa e quais níveis de esforço aceita. No Ollama isso vem de `/api/tags` (a lista), `/api/show` (o
detalhe, guardado por nome e `digest` porque só muda quando o modelo é reinstalado) e `/api/ps` (o que está na memória
agora). Nos servidores compatíveis com a OpenAI só existe a lista (`/v1/models`). O `opener` é injetável, como nos
clientes de chat, para testar sem servidor.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from .llm import DEFAULT_OLLAMA_URL, same_model
from .memory import Fit, MemoryStatus, memory_fit
from .openai_chat import DEFAULT_OPENAI_URL
from .transport import request_json

# O que um modelo pode fazer, na ordem em que a tela mostra os selos.
CAPABILITIES = ("vision", "tools", "thinking")
CATALOG_TIMEOUT = (
    15.0  # listar e detalhar são consultas rápidas; um servidor que não responde nisso está fora do ar
)

_LEVEL_LABELS = {"low": "Baixo", "medium": "Médio", "high": "Alto", "off": "Desligado", "on": "Ligado"}
_GPT_OSS_LEVELS = ("low", "medium", "high")
_SWITCH_LEVELS = ("off", "on")


class CatalogError(RuntimeError):
    """Falha ao falar com o servidor do modelo; `status` é o código HTTP quando a falha veio dele."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class EffortLevel:
    """Um nível do seletor de esforço: `value` é o que se guarda e envia, `label` é o que a tela mostra."""

    value: str
    label: str

    def to_dict(self) -> dict[str, str]:
        return {"value": self.value, "label": self.label}


def _level(value: str) -> EffortLevel:
    return EffortLevel(value, _LEVEL_LABELS.get(value, value.capitalize()))


def is_gpt_oss(model: str, family: str = "") -> bool:
    """A família gpt-oss, que o Ollama trata à parte no raciocínio (níveis em texto, nunca booleano)."""
    base = model.split(":")[0].rsplit("/", 1)[-1].lower()
    return base.startswith("gpt-oss") or family.lower().replace("-", "") == "gptoss"


def effort_levels(
    model: str,
    capabilities: Sequence[str],
    family: str = "",
    reported: Sequence[object] | None = None,
) -> tuple[EffortLevel, ...]:
    """Os níveis de esforço que o modelo aceita; vazio quando ele não raciocina e o seletor deve sumir.

    O esforço é o `think` do Ollama, e ele depende do modelo: o gpt-oss não desliga o raciocínio e recusa booleano,
    então tem Baixo, Médio e Alto; os outros modelos com raciocínio só ligam ou desligam (Desligado e Ligado, que
    viram booleano); os sem raciocínio não têm nível. Se o servidor informa os níveis em texto (`reported`, vindo de
    `/api/show`), vale o que ele disse, na ordem dele.
    """
    named = [value for value in reported or [] if isinstance(value, str) and value]
    if named:
        return tuple(_level(value) for value in named)
    if is_gpt_oss(model, family):
        return tuple(_level(value) for value in _GPT_OSS_LEVELS)
    if "thinking" in capabilities:
        return tuple(_level(value) for value in _SWITCH_LEVELS)
    return ()


def default_effort(levels: Sequence[EffortLevel], reported_default: object = None) -> str | None:
    """O nível que vale quando a conversa não escolheu nenhum (o que o servidor usa sozinho)."""
    values = [level.value for level in levels]
    if isinstance(reported_default, str) and reported_default in values:
        return reported_default
    if reported_default is True and "on" in values:
        return "on"
    if "medium" in values:
        return "medium"
    if "on" in values:
        return "on"
    return values[0] if values else None


def think_value(effort: str | None) -> bool | str | None:
    """O `think` do Ollama para um nível: texto fica texto, "on" e "off" viram booleano, vazio é o padrão do modelo."""
    if not effort:
        return None
    if effort == "on":
        return True
    if effort == "off":
        return False
    return effort


@dataclass(frozen=True)
class ModelInfo:
    name: str
    size: int | None  # bytes em disco; o servidor compatível com a OpenAI não informa
    family: str = ""
    capabilities: tuple[str, ...] = ()
    context_length: int | None = None  # o máximo que o modelo aguenta, não o que a conversa usa
    effort_levels: tuple[EffortLevel, ...] = ()
    default_effort: str | None = None

    def to_dict(self, fit: Fit, loaded: bool) -> dict[str, Any]:
        return {
            "name": self.name,
            "size": self.size,
            "family": self.family,
            "capabilities": list(self.capabilities),
            "context_length": self.context_length,
            "effort_levels": [level.to_dict() for level in self.effort_levels],
            "default_effort": self.default_effort,
            "fit": fit,
            "loaded": loaded,
        }


@dataclass(frozen=True)
class LoadedModel:
    name: str
    size: int | None  # bytes que o modelo ocupa na memória
    size_vram: int | None  # a parte que está na placa de vídeo (0 numa máquina só com CPU)
    context_length: int | None = None
    expires_at: str | None = None  # quando o Ollama o descarrega sozinho (data ISO)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "size": self.size,
            "size_vram": self.size_vram,
            "context_length": self.context_length,
            "expires_at": self.expires_at,
        }


class ModelCatalog(Protocol):
    can_unload: bool  # só o Ollama descarrega modelo; a tela esconde o botão nos outros motores

    def models(self) -> list[ModelInfo]: ...

    def loaded(self) -> list[LoadedModel]: ...

    def unload(self, name: str) -> bool:
        """Tira o modelo da memória; `False` se ele não estava carregado."""
        ...


def model_entries(
    models: Sequence[ModelInfo], loaded: Sequence[LoadedModel], memory: MemoryStatus | None
) -> list[dict[str, Any]]:
    """A lista da tela: cada modelo com o aviso de memória (um modelo já carregado conta como "cabe")."""
    entries = []
    for model in models:
        is_loaded = any(same_model(model.name, item.name) for item in loaded)
        entries.append(model.to_dict(memory_fit(model.size, memory, is_loaded), is_loaded))
    return entries


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _context_length(model_info: dict, fallback: Any) -> int | None:
    """A chave do contexto vem prefixada pela arquitetura (`<arquitetura>.context_length`)."""
    architecture = model_info.get("general.architecture")
    exact = _int_or_none(model_info.get(f"{architecture}.context_length")) if architecture else None
    if exact is not None:
        return exact
    for key, value in model_info.items():
        if key.endswith(".context_length") and _int_or_none(value) is not None:
            return value
    return _int_or_none(fallback)


@dataclass
class OllamaCatalog:
    """O catálogo do Ollama: `/api/tags`, `/api/show` (guardado por nome e `digest`), `/api/ps` e o descarregar."""

    base_url: str = DEFAULT_OLLAMA_URL
    timeout: float = CATALOG_TIMEOUT
    opener: Callable[..., Any] = urllib.request.urlopen
    can_unload: bool = field(default=True, init=False)
    # (nome, digest) -> ModelInfo, ou None para o que não conversa (só gera embeddings)
    _described: dict[tuple[str, str], ModelInfo | None] = field(default_factory=dict, init=False, repr=False)

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            return request_json(self.opener, self.base_url, method, path, body, self.timeout)
        except urllib.error.HTTPError as exc:
            raise CatalogError(f"O Ollama recusou a consulta {path} ({exc.code}).", status=exc.code) from exc
        except (OSError, ValueError) as exc:
            raise CatalogError(f"O Ollama não respondeu em {self.base_url}.") from exc

    def models(self) -> list[ModelInfo]:
        """Os modelos instalados que conversam; modelos só de embeddings ficam de fora."""
        installed = self._call("GET", "/api/tags").get("models") or []
        result = []
        for item in installed:
            name = item.get("name") or item.get("model") or ""
            if not name:
                continue
            key = (name, item.get("digest") or "")
            if key not in self._described:
                described, complete = self._describe(name, item)
                if (
                    not complete
                ):  # o detalhe falhou: usa o que a lista trouxe agora e tenta de novo na próxima
                    if described is not None:
                        result.append(described)
                    continue
                self._described[key] = described
            if (cached := self._described[key]) is not None:
                result.append(cached)
        return result

    def _describe(self, name: str, item: dict) -> tuple[ModelInfo | None, bool]:
        """Junta a lista e o detalhe do modelo; o segundo valor diz se o detalhe pôde ser lido."""
        try:
            show = self._call("POST", "/api/show", {"model": name})
            complete = True
        except CatalogError:
            show, complete = {}, False
        details = {**(item.get("details") or {}), **(show.get("details") or {})}
        raw_capabilities = show.get("capabilities") or item.get("capabilities")
        if raw_capabilities and "completion" not in raw_capabilities and "embedding" in raw_capabilities:
            return None, complete
        capabilities = tuple(c for c in CAPABILITIES if c in (raw_capabilities or ()))
        model_info = show.get("model_info") or {}
        family = details.get("family") or str(model_info.get("general.architecture") or "")
        thinking = show.get("thinking") if isinstance(show.get("thinking"), dict) else {}
        levels = effort_levels(name, capabilities, family, thinking.get("values"))
        info = ModelInfo(
            name=name,
            size=_int_or_none(item.get("size")),
            family=family,
            capabilities=capabilities,
            context_length=_context_length(model_info, details.get("context_length")),
            effort_levels=levels,
            default_effort=default_effort(levels, thinking.get("default")),
        )
        return info, complete

    def loaded(self) -> list[LoadedModel]:
        """O que está na memória agora (`/api/ps`)."""
        running = self._call("GET", "/api/ps").get("models") or []
        return [
            LoadedModel(
                name=item.get("name") or item.get("model") or "",
                size=_int_or_none(item.get("size")),
                size_vram=_int_or_none(item.get("size_vram")),
                context_length=_int_or_none(item.get("context_length")),
                expires_at=item.get("expires_at") or None,
            )
            for item in running
        ]

    def unload(self, name: str) -> bool:
        """`keep_alive: 0`. Só chama o Ollama se o modelo estiver carregado, para nunca carregar um por engano."""
        current = next((item for item in self.loaded() if same_model(item.name, name)), None)
        if current is None:
            return False
        self._call("POST", "/api/generate", {"model": current.name, "keep_alive": 0})
        return True


@dataclass
class OpenAICatalog:
    """O catálogo de um servidor compatível com a OpenAI: só a lista (`/v1/models`), sem capacidades nem memória."""

    base_url: str = DEFAULT_OPENAI_URL
    timeout: float = CATALOG_TIMEOUT
    api_key: str | None = None
    opener: Callable[..., Any] = urllib.request.urlopen
    can_unload: bool = field(default=False, init=False)

    def models(self) -> list[ModelInfo]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else None
        try:
            data = request_json(self.opener, self.base_url, "GET", "/v1/models", None, self.timeout, headers)
        except urllib.error.HTTPError as exc:
            raise CatalogError(
                f"O servidor recusou a consulta /v1/models ({exc.code}).", status=exc.code
            ) from exc
        except (OSError, ValueError) as exc:
            raise CatalogError(f"O servidor do modelo não respondeu em {self.base_url}.") from exc
        return [ModelInfo(name=item["id"], size=None) for item in data.get("data") or [] if item.get("id")]

    def loaded(self) -> list[LoadedModel]:
        return []

    def unload(self, name: str) -> bool:
        raise CatalogError("Este motor não descarrega modelos.", status=400)
