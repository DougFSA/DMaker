"""Catálogo de modelos (instalados, carregados, descarregar), níveis de esforço e a conta de memória."""

from __future__ import annotations

import json
import sys
import urllib.error
from urllib.parse import urlparse

import pytest

from dmaker.agent.catalog import (
    CatalogError,
    EffortLevel,
    LoadedModel,
    ModelInfo,
    OllamaCatalog,
    OpenAICatalog,
    default_effort,
    effort_levels,
    is_gpt_oss,
    model_entries,
    think_value,
)
from dmaker.agent.llm import same_model
from dmaker.agent.memory import GIB, MemoryStatus, WindowsMemoryProbe, memory_fit
from dmaker.agent.settings import AgentSettings, build_catalog

from .test_agent import FakeResponse

# ---------- o servidor falso ----------


class Routes:
    """Dublê do Ollama: responde por (método, caminho) e guarda cada chamada com o corpo enviado."""

    def __init__(self, routes: dict[tuple[str, str], object]):
        self.routes = routes
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, req, timeout=None):
        method, path = req.get_method(), urlparse(req.get_full_url()).path
        self.calls.append((method, path, json.loads(req.data) if req.data else None))
        value = self.routes[(method, path)]
        if isinstance(value, Exception):
            raise value
        return FakeResponse(value)

    def paths(self, method: str | None = None) -> list[str]:
        return [path for verb, path, _ in self.calls if method in (None, verb)]


GPT_OSS_TAG = {
    "name": "gpt-oss:20b",
    "digest": "f38a",
    "size": 13_793_441_566,
    "details": {"family": "gpt-oss", "context_length": 131072},
    "capabilities": ["completion", "tools", "thinking"],
}
QWEN_TAG = {
    "name": "qwen3:30b-a3b",
    "digest": "ad81",
    "size": 18_556_699_314,
    "details": {"family": "qwen3moe"},
}
VISION_TAG = {"name": "gemma3:4b", "digest": "9a9a", "size": 3_300_000_000, "details": {"family": "gemma3"}}
EMBED_TAG = {
    "name": "nomic-embed-text",
    "digest": "0e0e",
    "size": 274_000_000,
    "details": {"family": "nomic-bert"},
}

SHOWS = {
    "gpt-oss:20b": {
        "capabilities": ["completion", "tools", "thinking"],
        "details": {"family": "gpt-oss"},
        "model_info": {"general.architecture": "gpt-oss", "gpt-oss.context_length": 131072},
        "thinking": {"values": ["low", "medium", "high"], "default": "medium"},
    },
    "qwen3:30b-a3b": {
        "capabilities": ["completion", "tools", "thinking"],
        "details": {"family": "qwen3moe"},
        "model_info": {"general.architecture": "qwen3moe", "qwen3moe.context_length": 262144},
        "thinking": {"values": [True], "default": True},
    },
    "gemma3:4b": {
        "capabilities": ["completion", "vision"],
        "details": {"family": "gemma3"},
        "model_info": {"general.architecture": "gemma3", "gemma3.context_length": 131072},
    },
    "nomic-embed-text": {"capabilities": ["embedding"], "details": {"family": "nomic-bert"}},
}


class ShowRoutes(Routes):
    """Como `Routes`, mas o `/api/show` responde pelo modelo pedido (um valor que é exceção vira falha)."""

    def __init__(self, routes: dict[tuple[str, str], object], shows: dict[str, object]):
        super().__init__(routes)
        self.shows = shows

    def __call__(self, req, timeout=None):
        if req.get_method() == "POST" and urlparse(req.get_full_url()).path == "/api/show":
            name = json.loads(req.data)["model"]
            self.calls.append(("POST", "/api/show", {"model": name}))
            value = self.shows[name]
            if isinstance(value, Exception):
                raise value
            return FakeResponse(value)
        return super().__call__(req, timeout)


def server(
    tags: list[dict], running: list[dict] | None = None, shows: dict[str, object] | None = None
) -> ShowRoutes:
    return ShowRoutes(
        {
            ("GET", "/api/tags"): {"models": tags},
            ("GET", "/api/ps"): {"models": running or []},
            ("POST", "/api/generate"): {"done": True, "done_reason": "unload"},
        },
        SHOWS if shows is None else shows,
    )


# ---------- OllamaCatalog.models ----------


def test_the_catalog_describes_each_installed_model():
    catalog = OllamaCatalog(opener=server([GPT_OSS_TAG, QWEN_TAG, VISION_TAG]))

    by_name = {model.name: model for model in catalog.models()}

    oss = by_name["gpt-oss:20b"]
    assert oss.size == 13_793_441_566 and oss.family == "gpt-oss" and oss.context_length == 131072
    assert oss.capabilities == ("tools", "thinking")
    assert [level.value for level in oss.effort_levels] == ["low", "medium", "high"]
    assert [level.label for level in oss.effort_levels] == ["Baixo", "Médio", "Alto"]
    assert oss.default_effort == "medium"
    qwen = by_name["qwen3:30b-a3b"]
    assert qwen.context_length == 262144 and qwen.capabilities == ("tools", "thinking")
    assert [level.value for level in qwen.effort_levels] == ["off", "on"] and qwen.default_effort == "on"
    gemma = by_name["gemma3:4b"]
    assert gemma.capabilities == ("vision",) and gemma.effort_levels == () and gemma.default_effort is None


def test_models_that_only_make_embeddings_are_not_offered_for_chat():
    catalog = OllamaCatalog(opener=server([GPT_OSS_TAG, EMBED_TAG]))

    assert [model.name for model in catalog.models()] == ["gpt-oss:20b"]


def test_the_detail_of_a_model_is_asked_once_per_name_and_digest():
    opener = server([GPT_OSS_TAG, VISION_TAG])
    catalog = OllamaCatalog(opener=opener)

    catalog.models()
    catalog.models()

    assert opener.paths("POST").count("/api/show") == 2  # um por modelo, não um por listagem
    assert opener.paths("GET").count("/api/tags") == 2  # a lista é sempre fresca: o que se instala aparece

    opener.routes[("GET", "/api/tags")] = {"models": [{**GPT_OSS_TAG, "digest": "novo"}, VISION_TAG]}
    catalog.models()

    assert opener.paths("POST").count("/api/show") == 3  # o modelo reinstalado (outro digest) é lido de novo


def test_when_the_detail_fails_the_list_still_shows_the_model_and_tries_again_next_time():
    failure = urllib.error.HTTPError("http://x/api/show", 500, "erro", {}, None)  # type: ignore[arg-type]
    opener = server([GPT_OSS_TAG], shows={"gpt-oss:20b": failure})
    catalog = OllamaCatalog(opener=opener)

    first = catalog.models()

    assert [model.name for model in first] == ["gpt-oss:20b"]
    assert (
        first[0].capabilities == ("tools", "thinking") and first[0].context_length == 131072
    )  # vindos da lista
    assert [level.value for level in first[0].effort_levels] == ["low", "medium", "high"]

    opener.shows["gpt-oss:20b"] = SHOWS["gpt-oss:20b"]
    catalog.models()
    catalog.models()
    assert opener.paths("POST").count("/api/show") == 2  # a falha não ficou guardada; o detalhe lido ficou


def test_the_context_falls_back_to_the_list_when_the_detail_has_no_model_info():
    shows = {"tmp": {"capabilities": ["completion"], "details": {}}}
    tag = {"name": "tmp", "digest": "1", "size": 1, "details": {"context_length": 4096}}

    models = OllamaCatalog(opener=server([tag], shows=shows)).models()

    assert models[0].context_length == 4096


def test_the_context_key_is_found_even_when_the_architecture_prefix_differs():
    shows = {"tmp": {"capabilities": ["completion"], "model_info": {"llama.context_length": 8192}}}

    models = OllamaCatalog(opener=server([{"name": "tmp", "digest": "1", "size": 1}], shows=shows)).models()

    assert models[0].context_length == 8192


def test_an_unreachable_server_is_a_catalog_error_without_a_status():
    catalog = OllamaCatalog(opener=Routes({("GET", "/api/tags"): OSError("conexão recusada")}))

    with pytest.raises(CatalogError) as caught:
        catalog.models()

    assert caught.value.status is None and "não respondeu" in str(caught.value)


def test_a_refusal_from_the_server_keeps_its_status():
    refusal = urllib.error.HTTPError("http://x/api/tags", 500, "erro", {}, None)  # type: ignore[arg-type]
    catalog = OllamaCatalog(opener=Routes({("GET", "/api/tags"): refusal}))

    with pytest.raises(CatalogError) as caught:
        catalog.models()

    assert caught.value.status == 500


# ---------- carregados e descarregar ----------


PS_ITEM = {
    "name": "gpt-oss:20b",
    "size": 11_000_000_000,
    "size_vram": 0,
    "context_length": 16384,
    "expires_at": "2026-10-30T18:00:00-03:00",
}


def test_the_loaded_models_come_from_ps():
    catalog = OllamaCatalog(opener=server([GPT_OSS_TAG], running=[PS_ITEM]))

    assert catalog.loaded() == [
        LoadedModel("gpt-oss:20b", 11_000_000_000, 0, 16384, "2026-10-30T18:00:00-03:00")
    ]
    assert catalog.loaded()[0].to_dict() == {
        "name": "gpt-oss:20b",
        "size": 11_000_000_000,
        "size_vram": 0,
        "context_length": 16384,
        "expires_at": "2026-10-30T18:00:00-03:00",
    }


def test_nothing_loaded_is_an_empty_list():
    assert OllamaCatalog(opener=server([GPT_OSS_TAG])).loaded() == []


def test_unloading_sends_keep_alive_zero_for_a_loaded_model():
    opener = server([GPT_OSS_TAG], running=[PS_ITEM])
    catalog = OllamaCatalog(opener=opener)

    assert catalog.unload("gpt-oss:20b") is True

    assert opener.calls[-1] == ("POST", "/api/generate", {"model": "gpt-oss:20b", "keep_alive": 0})


def test_unloading_a_model_that_is_not_loaded_never_calls_generate():
    """Pedir `keep_alive: 0` a um modelo descarregado poderia carregá-lo só para descarregar: nem tenta."""
    opener = server([GPT_OSS_TAG, QWEN_TAG], running=[PS_ITEM])
    catalog = OllamaCatalog(opener=opener)

    assert catalog.unload("qwen3:30b-a3b") is False

    assert "/api/generate" not in opener.paths()


def test_unloading_accepts_the_name_without_the_latest_tag():
    opener = server([], running=[{**PS_ITEM, "name": "llama3:latest"}])

    assert OllamaCatalog(opener=opener).unload("llama3") is True
    assert opener.calls[-1][2] == {"model": "llama3:latest", "keep_alive": 0}


# ---------- motor compatível com a OpenAI ----------


def test_the_openai_catalog_lists_what_the_server_serves_and_nothing_else():
    opener = Routes({("GET", "/v1/models"): {"data": [{"id": "modelo-a"}, {"id": "modelo-b"}]}})
    catalog = OpenAICatalog(opener=opener)

    models = catalog.models()

    assert [model.name for model in models] == ["modelo-a", "modelo-b"]
    assert models[0].size is None and models[0].capabilities == () and models[0].effort_levels == ()
    assert catalog.loaded() == [] and catalog.can_unload is False
    with pytest.raises(CatalogError) as caught:
        catalog.unload("modelo-a")
    assert caught.value.status == 400


def test_the_catalog_follows_the_configured_engine():
    assert isinstance(build_catalog(AgentSettings(engine="ollama")), OllamaCatalog)
    assert isinstance(
        build_catalog(AgentSettings(engine="openai", url="http://127.0.0.1:8080")), OpenAICatalog
    )


# ---------- níveis de esforço ----------


@pytest.mark.parametrize(
    ("model", "capabilities", "family", "expected"),
    [
        ("gpt-oss:20b", ["tools", "thinking"], "gpt-oss", ["low", "medium", "high"]),
        (
            "gpt-oss:120b",
            [],
            "",
            ["low", "medium", "high"],
        ),  # a família basta, mesmo sem capacidades conhecidas
        ("registry.local/gpt-oss:20b-q4", ["thinking"], "", ["low", "medium", "high"]),
        ("qwen3:30b-a3b", ["tools", "thinking"], "qwen3moe", ["off", "on"]),
        ("deepseek-r1:8b", ["thinking"], "qwen2", ["off", "on"]),
        ("gemma3:4b", ["vision"], "gemma3", []),
        ("llama3.2:3b", ["tools"], "llama", []),
    ],
)
def test_effort_levels_depend_on_the_model_family_and_its_reasoning(model, capabilities, family, expected):
    assert [level.value for level in effort_levels(model, capabilities, family)] == expected


def test_effort_labels_are_in_portuguese_without_dashes():
    labels = {
        level.value: level.label
        for level in (*effort_levels("gpt-oss:20b", []), *effort_levels("x", ["thinking"]))
    }

    assert labels == {
        "low": "Baixo",
        "medium": "Médio",
        "high": "Alto",
        "off": "Desligado",
        "on": "Ligado",
    }
    assert all("—" not in label and "–" not in label for label in labels.values())


def test_levels_reported_by_the_server_win_when_they_are_text():
    levels = effort_levels("modelo-novo", ["thinking"], "", ["minimal", "high"])

    assert levels == (EffortLevel("minimal", "Minimal"), EffortLevel("high", "Alto"))


def test_reported_booleans_are_not_levels():
    assert [level.value for level in effort_levels("m", ["thinking"], "", [True])] == ["off", "on"]


def test_the_default_effort_is_the_servers_when_it_matches_else_medium_else_on():
    levels = effort_levels("gpt-oss:20b", [])
    assert default_effort(levels, "high") == "high"
    assert default_effort(levels) == "medium"
    switch = effort_levels("x", ["thinking"])
    assert default_effort(switch, True) == "on" and default_effort(switch) == "on"
    assert default_effort(()) is None


@pytest.mark.parametrize(
    ("effort", "think"),
    [
        (None, None),
        ("", None),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("on", True),
        ("off", False),
    ],
)
def test_the_chosen_effort_becomes_the_think_the_server_understands(effort, think):
    assert think_value(effort) == think
    assert type(think_value(effort)) is type(think)  # True não pode virar o texto "on", nem 1


def test_gpt_oss_is_recognised_by_name_or_family():
    assert is_gpt_oss("gpt-oss:20b") and is_gpt_oss("lib/gpt-oss") and is_gpt_oss("x", "gptoss")
    assert not is_gpt_oss("qwen3:30b") and not is_gpt_oss("my-gpt:1")


def test_the_latest_tag_is_optional_when_comparing_models():
    assert same_model("llama3", "llama3:latest") and not same_model("llama3:8b", "llama3:70b")


# ---------- memória ----------


def memory(total_gib: float, available_gib: float) -> MemoryStatus:
    return MemoryStatus(total=int(total_gib * GIB), available=int(available_gib * GIB))


@pytest.mark.parametrize(
    ("size_gib", "available_gib", "loaded", "expected"),
    [
        (4.0, 12.0, False, "fits"),  # sobra bastante
        (4.0, 5.4, False, "tight"),  # sobram 1,4 GiB: menos que a folga de 1,5
        (4.0, 5.5, False, "fits"),  # exatamente 1,5 GiB de folga já é folga
        (12.8, 1.5, False, "tight"),  # falta memória livre agora, mas a máquina tem RAM para ele
        (17.3, 14.0, False, "too_big"),  # maior que a RAM inteira (16 GiB): nenhuma folga resolve
        (17.3, 1.0, True, "fits"),  # já carregado conta como cabe, mesmo com pouca memória livre
    ],
)
def test_memory_fit_says_fits_tight_or_too_big(size_gib, available_gib, loaded, expected):
    assert memory_fit(int(size_gib * GIB), memory(16, available_gib), loaded) == expected


def test_memory_fit_is_unknown_without_the_size_or_the_memory_reading():
    assert memory_fit(None, memory(16, 8)) == "unknown"
    assert memory_fit(4 * GIB, None) == "unknown"
    assert memory_fit(4 * GIB, None, loaded=True) == "fits"  # carregado cabe, sem precisar saber a memória


def test_the_model_list_for_the_screen_carries_the_fit_and_the_loaded_flag():
    models = [
        ModelInfo("gpt-oss:20b", int(12.8 * GIB), capabilities=("tools", "thinking")),
        ModelInfo("qwen3:30b-a3b", int(17.3 * GIB)),
        ModelInfo("remoto", None),
    ]
    running = [LoadedModel("gpt-oss:20b", int(11 * GIB), 0)]

    entries = model_entries(models, running, memory(15.7, 1.5))

    assert [(e["name"], e["fit"], e["loaded"]) for e in entries] == [
        ("gpt-oss:20b", "fits", True),
        ("qwen3:30b-a3b", "too_big", False),
        ("remoto", "unknown", False),
    ]
    assert set(entries[0]) == {
        "name",
        "size",
        "family",
        "capabilities",
        "context_length",
        "effort_levels",
        "default_effort",
        "fit",
        "loaded",
    }


def test_the_windows_reading_is_plausible_or_absent_elsewhere(monkeypatch):
    reading = WindowsMemoryProbe().read()

    if sys.platform == "win32":
        assert reading is not None and 0 < reading.available <= reading.total
        assert reading.total > GIB
    else:
        assert reading is None
    monkeypatch.setattr(sys, "platform", "linux")
    assert WindowsMemoryProbe().read() is None  # em outro sistema não sabe e diz que não sabe
