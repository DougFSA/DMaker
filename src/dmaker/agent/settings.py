"""Configuração do agente local: qual motor, qual modelo e onde, lida das variáveis de ambiente na hora do uso.

Segue o padrão do `config` (variável de ambiente, nada fixo no código além do padrão): `DMAKER_AGENT_ENGINE`
(`ollama` ou `openai`, este para llama.cpp server e LM Studio), `DMAKER_AGENT_MODEL`, `DMAKER_AGENT_URL`,
`DMAKER_AGENT_NUM_CTX`, `DMAKER_AGENT_TIMEOUT`, `DMAKER_AGENT_THINK` (esforço de raciocínio: `low`, `medium`, `high`, ou
`true`/`false` para os modelos que só ligam e desligam), `DMAKER_AGENT_TEMPERATURE`, `DMAKER_AGENT_SEED` e
`DMAKER_AGENT_FREE_HTML` (liga o HTML livre nas composições). As opções da CLI vencem a variável, e a variável vence o padrão.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal, cast

from .catalog import ModelCatalog, OllamaCatalog, OpenAICatalog
from .llm import DEFAULT_OLLAMA_URL, OLLAMA_URL_ENV, HealthCheckedChat, OllamaChat
from .openai_chat import DEFAULT_OPENAI_URL, OpenAICompatibleChat

Engine = Literal["ollama", "openai"]
ENGINES: tuple[Engine, ...] = ("ollama", "openai")

ENGINE_ENV = "DMAKER_AGENT_ENGINE"
MODEL_ENV = "DMAKER_AGENT_MODEL"
URL_ENV = "DMAKER_AGENT_URL"
NUM_CTX_ENV = "DMAKER_AGENT_NUM_CTX"
TIMEOUT_ENV = "DMAKER_AGENT_TIMEOUT"
FREE_HTML_ENV = "DMAKER_AGENT_FREE_HTML"
THINK_ENV = "DMAKER_AGENT_THINK"
TEMPERATURE_ENV = "DMAKER_AGENT_TEMPERATURE"
SEED_ENV = "DMAKER_AGENT_SEED"
THINK_LEVELS = ("low", "medium", "high")

# O modelo que a máquina do projeto roda; quem usa outro ajusta por DMAKER_AGENT_MODEL ou `--model`.
DEFAULT_MODEL = "gpt-oss:20b"
DEFAULT_NUM_CTX = 16384
DEFAULT_TIMEOUT = 1800.0  # um modelo de 20b em CPU leva minutos só para ler o prompt de sistema
_TRUE_WORDS = frozenset({"1", "true", "sim", "yes", "on"})
_FALSE_WORDS = frozenset({"0", "false", "nao", "não", "no", "off"})


class SettingsError(ValueError):
    """Valor de configuração que não faz sentido; a mensagem diz qual variável corrigir."""


@dataclass(frozen=True)
class AgentSettings:
    engine: Engine = "ollama"
    model: str = DEFAULT_MODEL
    url: str = DEFAULT_OLLAMA_URL
    num_ctx: int = DEFAULT_NUM_CTX
    timeout: float = DEFAULT_TIMEOUT
    free_html: bool = False  # HTML livre nas composições: só com um modelo que a avaliação mostrou dar conta
    think: str | bool | None = (
        None  # esforço de raciocínio: `low` encurta a espera na CPU (gpt-oss); booleano para quem só liga e desliga
    )
    temperature: float | None = None  # None: o padrão do modelo
    seed: int | None = None  # None: sorteada a cada resposta; um número repete a mesma resposta

    @property
    def engine_label(self) -> str:
        return "Ollama" if self.engine == "ollama" else "servidor compatível com a OpenAI"


def _number(raw: str, name: str, cast: type) -> int | float:
    try:
        return cast(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} deve ser um número, mas está '{raw}'.") from exc


def _think(raw: str | None) -> str | bool | None:
    """`low`, `medium` e `high` ficam texto; `true`/`false` (e equivalentes) viram booleano; vazio é o padrão do modelo."""
    word = (raw or "").strip().lower()
    if not word:
        return None
    if word in THINK_LEVELS:
        return word
    if word in _TRUE_WORDS:
        return True
    if word in _FALSE_WORDS:
        return False
    raise SettingsError(f"{THINK_ENV} deve ser {', '.join(THINK_LEVELS)}, true ou false, mas está '{word}'.")


def _optional_float(raw: str | None, name: str) -> float | None:
    return float(_number(raw.strip(), name, float)) if raw and raw.strip() else None


def _optional_int(raw: str | None, name: str) -> int | None:
    return int(_number(raw.strip(), name, int)) if raw and raw.strip() else None


def load_settings(env: Mapping[str, str] | None = None, **overrides: object) -> AgentSettings:
    """As configurações do ambiente, com as opções da CLI por cima (as que vierem `None` não contam)."""
    source = os.environ if env is None else env
    chosen = {name: value for name, value in overrides.items() if value is not None}
    engine = str(chosen.get("engine") or source.get(ENGINE_ENV) or "ollama").strip().lower()
    if engine not in ENGINES:
        raise SettingsError(f"O motor deve ser {' ou '.join(ENGINES)}, mas está '{engine}' ({ENGINE_ENV}).")
    # o endereço padrão acompanha o motor efetivo: trocar de motor não herda a porta do outro
    default_url = source.get(OLLAMA_URL_ENV, DEFAULT_OLLAMA_URL) if engine == "ollama" else DEFAULT_OPENAI_URL
    settings = AgentSettings(
        engine=cast(Engine, engine),
        model=source.get(MODEL_ENV) or DEFAULT_MODEL,
        url=source.get(URL_ENV) or default_url,
        num_ctx=int(_number(source.get(NUM_CTX_ENV, str(DEFAULT_NUM_CTX)), NUM_CTX_ENV, int)),
        timeout=float(_number(source.get(TIMEOUT_ENV, str(DEFAULT_TIMEOUT)), TIMEOUT_ENV, float)),
        free_html=source.get(FREE_HTML_ENV, "").strip().lower() in _TRUE_WORDS,
        think=_think(source.get(THINK_ENV)),
        temperature=_optional_float(source.get(TEMPERATURE_ENV), TEMPERATURE_ENV),
        seed=_optional_int(source.get(SEED_ENV), SEED_ENV),
    )
    chosen["engine"] = engine
    return replace(settings, **chosen)  # type: ignore[arg-type]  # as chaves são campos de AgentSettings


def build_chat(settings: AgentSettings) -> HealthCheckedChat:
    """O motor de conversa configurado: o mesmo protocolo `ChatModel`, nenhum nome de modelo fixo aqui."""
    if settings.engine == "openai":
        return OpenAICompatibleChat(
            model=settings.model,
            base_url=settings.url,
            timeout=settings.timeout,
            temperature=settings.temperature,
            seed=settings.seed,
        )
    return OllamaChat(
        model=settings.model,
        base_url=settings.url,
        num_ctx=settings.num_ctx,
        timeout=settings.timeout,
        think=settings.think,
        temperature=settings.temperature,
        seed=settings.seed,
    )


def build_catalog(settings: AgentSettings) -> ModelCatalog:
    """O catálogo de modelos do motor configurado (instalados, carregados, descarregar)."""
    if settings.engine == "openai":
        return OpenAICatalog(base_url=settings.url)
    return OllamaCatalog(base_url=settings.url)
