"""`dmaker doctor --offline`: confere se tudo que as funções usam já está baixado e o que falha sem rede.

Cada item diz onde o DMaker procurou, se achou, o que deixa de funcionar quando falta e o comando para baixar
enquanto ainda há conexão. O relatório é montado por funções puras; o disco, o servidor do modelo e os módulos
Python entram atrás do protocolo `OfflineProbe`, e é o que o teste troca por um falso.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from .. import config
from .settings import AgentSettings

ItemStatus = Literal["ok", "missing"]

# Modelos do registro (`domain/models.py`) que as funções usam e que precisam estar em disco para funcionar sem
# rede: (id, o que deixa de funcionar sem ele). Os tamanhos extras do Whisper só baixam sob pedido.
REQUIRED_MODELS: tuple[tuple[str, str], ...] = (
    ("whisper-small", "legendas automáticas, transcrição, corte de pausas, correção de fala e dublagem"),
    ("omnivoice", "narração com voz clonada ou projetada, correção de fala e dublagem"),
    ("kokoro-fp32", "narração com as vozes prontas (dora, alex, santa)"),
    ("demucs-htdemucs", "isolamento da voz e dublagem que mantém o fundo"),
    ("rvm-resnet50", "fundo trocado e texto atrás da pessoa (recorte de pessoa)"),
    ("audioseal", "marca d'água e verificação de voz gerada por IA"),
    ("diarization-sherpa", "dublagem com uma voz por pessoa"),
    ("openvoice-v2", "troca de voz de uma gravação"),
)
# Módulos Python opcionais que cada função precisa além do modelo: (módulo, extra do pip, o que usa).
REQUIRED_MODULES: tuple[tuple[str, str, str], ...] = (
    ("faster_whisper", "captions", "legendas e transcrição"),
    ("kokoro_onnx", "voice", "vozes prontas"),
    ("playwright", "html", "exportar o manual em PDF e as composições em HTML"),
    ("pypdf", "agente", "anexar arquivos PDF na conversa com o agente"),
)
SFX_SAMPLE = "whoosh.wav"
FONT_SAMPLE = "Poppins-Regular.ttf"
CHROMIUM_PREFIX = "chromium"  # as pastas `chromium-<rev>` e `chromium_headless_shell-<rev>` do Playwright
PLAYWRIGHT_INSTALL = "dmaker setup --html"


@dataclass(frozen=True)
class OfflineItem:
    """Uma coisa de que o DMaker depende em disco: onde procurei, se achei, o que falha sem ela e como baixar."""

    name: str
    status: ItemStatus
    where: str
    needed_by: str
    download: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class OfflineReport:
    items: tuple[OfflineItem, ...]

    @property
    def missing(self) -> tuple[OfflineItem, ...]:
        return tuple(item for item in self.items if not item.ok)

    @property
    def ready(self) -> bool:
        return not self.missing


class OfflineProbe(Protocol):
    """O que o relatório precisa saber do mundo; a implementação real toca disco e servidor, o teste usa um falso."""

    def model_state(self, model_id: str) -> str: ...

    def module_available(self, name: str) -> bool: ...

    def path_exists(self, path: Path) -> bool: ...

    def list_dir(self, path: Path) -> list[str]: ...

    def tool_path(self, name: str) -> Path | None: ...

    def language_model_state(
        self, settings: AgentSettings
    ) -> Literal["ready", "model_missing", "server_down"]: ...


def _model_item(model_id: str, needed_by: str, probe: OfflineProbe) -> OfflineItem:
    state = probe.model_state(model_id)
    where = f"{config.MODELS_DIR} (modelo {model_id})"
    status: ItemStatus = "ok" if state == "installed" else "missing"
    suffix = " (download pela metade)" if state == "partial" else ""
    return OfflineItem(
        f"Modelo {model_id}{suffix}", status, where, needed_by, f"dmaker models download {model_id}"
    )


def _module_item(module: str, extra: str, needed_by: str, probe: OfflineProbe) -> OfflineItem:
    found = probe.module_available(module)
    return OfflineItem(
        f"Pacote Python {module}",
        "ok" if found else "missing",
        "o ambiente Python do DMaker (.venv)",
        needed_by,
        f'pip install -e ".[{extra}]"',
    )


def _chromium_item(probe: OfflineProbe) -> OfflineItem:
    """O Chromium só vale na pasta do DMaker (`bin/playwright`): é lá que o render o abre, com o ambiente do
    Playwright apontado para ela, então o do padrão do sistema não conta."""
    folder = config.PLAYWRIGHT_DIR
    found = any(name.startswith(CHROMIUM_PREFIX) for name in probe.list_dir(folder))
    needed = "exportar o manual em PDF, tirar capturas e as composições em HTML"
    return OfflineItem(
        "Chromium do Playwright", "ok" if found else "missing", str(folder), needed, PLAYWRIGHT_INSTALL
    )


def _language_model_item(settings: AgentSettings, probe: OfflineProbe) -> OfflineItem:
    state = probe.language_model_state(settings)
    where = f"{settings.engine_label} em {settings.url}"
    name = f"Modelo de linguagem {settings.model}"
    needed = "o agente local e a tradução da dublagem"
    if state == "ready":
        return OfflineItem(name, "ok", where, needed)
    if state == "server_down":
        start = (
            "ollama serve"
            if settings.engine == "ollama"
            else "inicie o servidor do modelo (llama.cpp ou LM Studio)"
        )
        return OfflineItem(f"{name} (servidor parado)", "missing", where, needed, start)
    pull = (
        f"ollama pull {settings.model}" if settings.engine == "ollama" else "baixe o modelo no seu servidor"
    )
    return OfflineItem(name, "missing", where, needed, pull)


def _file_items(probe: OfflineProbe) -> list[OfflineItem]:
    ffmpeg = probe.tool_path("ffmpeg")
    ffprobe = probe.tool_path("ffprobe")
    return [
        OfflineItem(
            "FFmpeg e ffprobe",
            "ok" if ffmpeg and ffprobe else "missing",
            f"{config.FFMPEG_DIR} e o PATH",
            "todo render, corte e leitura de mídia",
            "dmaker setup",
        ),
        OfflineItem(
            "Fonte Poppins",
            "ok" if probe.path_exists(config.FONTS_DIR / FONT_SAMPLE) else "missing",
            str(config.FONTS_DIR),
            "texto e legendas na tela",
            "dmaker setup",
        ),
        OfflineItem(
            "Efeitos sonoros",
            "ok" if probe.path_exists(config.SFX_DIR / SFX_SAMPLE) else "missing",
            str(config.SFX_DIR),
            "efeitos sonoros e transições com som (vêm no repositório)",
            "git restore assets/sfx",
        ),
    ]


def build_report(settings: AgentSettings, probe: OfflineProbe) -> OfflineReport:
    """Todos os itens, na ordem em que a pessoa deve resolver: ferramentas, modelo de linguagem, modelos, pacotes."""
    items = [
        *_file_items(probe),
        _language_model_item(settings, probe),
        *(_model_item(model_id, needed, probe) for model_id, needed in REQUIRED_MODELS),
        *(_module_item(module, extra, needed, probe) for module, extra, needed in REQUIRED_MODULES),
        _chromium_item(probe),
    ]
    return OfflineReport(tuple(items))


def render_report(report: OfflineReport) -> list[str]:
    """As linhas do relatório em texto puro: uma por item e, nos que faltam, o que falha e o comando de download."""
    lines = []
    for item in report.items:
        lines.append(f"[{'ok' if item.ok else 'FALTA'}] {item.name}")
        lines.append(f"    procurei em: {item.where}")
        if not item.ok:
            lines.append(f"    sem isso falha: {item.needed_by}")
            if item.download:
                lines.append(f"    para baixar agora, com internet: {item.download}")
    lines.append("")
    if report.ready:
        lines.append("Tudo pronto: o DMaker funciona sem internet.")
    else:
        lines.append(
            f"{len(report.missing)} item(ns) vão falhar sem rede. Rode os comandos acima enquanto há conexão."
        )
    return lines


class DiskOfflineProbe:
    """A sonda de verdade: disco local, módulos importáveis e o servidor do modelo (que também é local)."""

    def model_state(self, model_id: str) -> str:
        from ..pipeline.models_service import shared_service

        return shared_service().status(model_id).state

    def module_available(self, name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            return False

    def path_exists(self, path: Path) -> bool:
        return path.exists()

    def list_dir(self, path: Path) -> list[str]:
        try:
            return [entry.name for entry in path.iterdir()]
        except OSError:
            return []

    def tool_path(self, name: str) -> Path | None:
        return config.find_tool(name)

    def language_model_state(
        self, settings: AgentSettings
    ) -> Literal["ready", "model_missing", "server_down"]:
        from .settings import build_chat

        chat = build_chat(settings)
        if not chat.is_alive():
            return "server_down"
        return "ready" if chat.has_model() else "model_missing"  # type: ignore[attr-defined]
