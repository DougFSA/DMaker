"""Executa a bateria de avaliação: cada pedido numa pasta de dados temporária, com mídia sintética.

É a parte com efeito colateral da avaliação (`evaluation.py` só tem dados e contas). Os dados reais de quem usa
o editor nunca são tocados: os caminhos do `config` apontam para uma pasta temporária durante o pedido, e as
ferramentas pesadas (render, Whisper, dublagem) são simuladas a menos que `real_tools` as liberte. O modelo
entra por `ChatModel`: o falso segue o roteiro do pedido (`oracle`), o real é o configurado.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from .. import config
from .evaluation import (
    HEAVY_TOOLS,
    BatteryReport,
    CaseResult,
    Check,
    EvalCase,
    Observation,
    evaluate_case,
)
from .kits import DEFAULT_KIT
from .llm import ChatModel, Reply, ToolCall
from .safety import ConfirmationRequest
from .session import AgentSession, server_tool_names
from .settings import AgentSettings, build_chat
from .tools import DEFAULT_WAIT_SECONDS, McpToolHost, ToolHost, ToolSpec

STUB_RESULT = json.dumps(
    {"status": "done", "simulado": True, "aviso": "ferramenta pesada simulada na avaliação"},
    ensure_ascii=False,
)
MODEL_PROCESS_NAMES = ("ollama", "llama-server", "llama_server", "llama.cpp", "lm studio", "lm-studio")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


# ---------- pasta de dados isolada ----------


# O que mora no repositório (código, modelos baixados, ferramentas, assets e modelos de projeto): nunca vai para a
# pasta temporária, nem quando `DATA_DIR` é a própria raiz (o padrão de quem usa o editor).
CODE_PATHS = frozenset(
    {
        "ROOT",
        "PACKAGE_DIR",
        "BIN_DIR",
        "FFMPEG_DIR",
        "PLAYWRIGHT_DIR",
        "ASSETS_DIR",
        "FONTS_DIR",
        "HTML_ASSETS_DIR",
        "BRANDS_DIR",
        "SFX_DIR",
        "TEMPLATES_DIR",
        "INFOGRAPHICS_DIR",
        "MODELS_DIR",
        "WINDOWS_FONTS_DIR",
    }
)


@contextmanager
def isolated_workspace(root: Path) -> Iterator[Path]:
    """Aponta os caminhos de dados do `config` (cache, saída, projetos, vozes, léxico, layouts) para `root` e
    devolve tudo ao fim. Os modelos baixados e tudo que é do repositório ficam onde estão."""
    old_data = config.DATA_DIR
    moved = {
        name: value
        for name, value in vars(config).items()
        if name.isupper()
        and isinstance(value, Path)
        and name not in CODE_PATHS
        and value != old_data
        and value.is_relative_to(old_data)
    }
    originals = {name: getattr(config, name) for name in (*moved, "DATA_DIR")}
    for name, value in moved.items():
        setattr(config, name, root / value.relative_to(old_data))
    config.DATA_DIR = root
    try:
        yield root
    finally:
        for name, value in originals.items():
            setattr(config, name, value)


# ---------- mídia sintética ----------


def _make_video(path: Path, seconds: float = 4.0) -> None:
    from ..media import ffmpeg

    args = ["-f", "lavfi", "-i", "testsrc2=size=320x568:rate=30", "-f", "lavfi", "-i", "sine=frequency=440"]
    args += [
        "-t",
        str(seconds),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
    ]
    ffmpeg.run([*args, str(path)], quiet=True)


def _make_audio(path: Path, seconds: float = 4.0) -> None:
    from ..media import ffmpeg

    ffmpeg.run(
        ["-f", "lavfi", "-i", "sine=frequency=330", "-t", str(seconds), "-c:a", "pcm_s16le", str(path)],
        quiet=True,
    )


def _make_image(path: Path, seconds: float = 0.0) -> None:
    from PIL import Image

    Image.new("RGB", (600, 400), (30, 110, 160)).save(path)


def substitute(value: Any, names: Mapping[str, str]) -> Any:
    """Troca `{video}`, `{image}`... pelo caminho do arquivo sintético, em qualquer nível; o resto fica como está."""
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda found: names.get(found.group(1), found.group(0)), value)
    if isinstance(value, Mapping):
        return {key: substitute(item, names) for key, item in value.items()}
    if isinstance(value, list):
        return [substitute(item, names) for item in value]
    return value


def build_media(fixtures: Mapping[str, Any], folder: Path) -> dict[str, str]:
    """Gera a mídia dos fixtures (`video`, `audio`, `image`, `folder`, `sheet`) e devolve nome -> caminho."""
    folder.mkdir(parents=True, exist_ok=True)
    names: dict[str, str] = {}
    makers: dict[str, Callable[[Path], None]] = {
        "video": _make_video,
        "audio": _make_audio,
        "image": _make_image,
    }
    suffixes = {"video": ".mp4", "audio": ".wav", "image": ".png"}
    for name, spec in fixtures.items():
        if name == "projects":
            continue
        kind = spec.get("kind")
        if kind in makers:
            target = folder / f"{name}{suffixes[kind]}"
            makers[kind](target, float(spec.get("seconds", 4.0)))  # a foto ignora a duração
            names[name] = target.as_posix()
        elif kind == "folder":
            target = folder / name
            target.mkdir(parents=True, exist_ok=True)
            _make_video(target / "0001.mp4")
            names[name] = target.as_posix()
    for name, spec in fixtures.items():
        if name != "projects" and spec.get("kind") == "sheet":
            rows = substitute(spec["rows"], names)
            lines = [",".join(spec["columns"]), *(",".join(str(cell) for cell in row) for row in rows)]
            target = folder / f"{name}.csv"
            target.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
            names[name] = target.as_posix()
    return names


def create_projects(fixtures: Mapping[str, Any], names: Mapping[str, str]) -> None:
    """Cria os projetos do fixture pelo mesmo caminho do agente (`project_from_template`)."""
    from ..pipeline.projects import project_from_template

    for item in fixtures.get("projects", []):
        project_from_template(item["template"], item["name"], substitute(item.get("params", {}), names))


# ---------- dublês do pedido ----------


class OracleChat:
    """O modelo falso: segue o roteiro de passos do pedido (`call` com argumentos, ou `answer` com a resposta)."""

    def __init__(self, steps: Sequence[Mapping[str, Any]], kits: Sequence[str] = ()) -> None:
        self._steps = list(steps)
        self._kits = ", ".join(kits) or DEFAULT_KIT

    def chat(self, messages: list[dict], tools: list[dict]) -> Reply:
        if not tools:  # a triagem, quando as palavras não decidem, pergunta o kit sem passar ferramentas
            return Reply(content=self._kits)
        if not self._steps:
            return Reply(content="Não há mais passos no roteiro deste pedido.")
        step = self._steps.pop(0)
        if "call" in step:
            return Reply(content="", tool_calls=[ToolCall(step["call"], dict(step.get("arguments", {})))])
        return Reply(content=str(step.get("answer", "")))


class ScriptedPolicy:
    """A pessoa do pedido: responde sempre o mesmo à confirmação de ação e à autorização do dono da voz."""

    def __init__(self, approve: bool, consent: bool) -> None:
        self._approve = approve
        self._consent = consent
        self.asked: list[str] = []

    def confirm(self, request: ConfirmationRequest) -> bool:
        self.asked.append(request.tool)
        return self._consent if request.kind == "voice_consent" else self._approve


@dataclass
class RecordingHost:
    """Passa as chamadas ao host de verdade, anota as que chegaram a executar e simula as pesadas se for o caso."""

    inner: ToolHost
    executed: list[tuple[str, dict]]
    stub_heavy: bool = True

    def specs(self) -> list[ToolSpec]:
        return self.inner.specs()

    def call(self, name: str, arguments: dict) -> str:
        self.executed.append((name, dict(arguments)))
        if self.stub_heavy and name in HEAVY_TOOLS:
            return STUB_RESULT
        return self.inner.call(name, arguments)


class MemoryProbe(Protocol):
    def measure(self) -> int | None: ...


class PsutilMemoryProbe:
    """Soma a memória (RSS) dos processos do servidor do modelo; `None` se nenhum aparece ou o psutil falta."""

    def __init__(self, names: Sequence[str] = MODEL_PROCESS_NAMES) -> None:
        self._names = tuple(name.lower() for name in names)

    def measure(self) -> int | None:
        try:
            import psutil
        except ImportError:
            return None
        total = 0
        for process in psutil.process_iter(["name", "memory_info"]):
            name = (process.info.get("name") or "").lower()
            info = process.info.get("memory_info")
            if info is not None and any(part in name for part in self._names):
                total += info.rss
        return total or None


# ---------- um pedido ----------


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _observe(case: EvalCase, root: Path, before: Mapping[str, str | None]) -> dict[str, Any]:
    """O estado em disco que as verificações do pedido leem: specs dos projetos, arquivos iguais e gerados."""
    projects: dict[str, Any] = {}
    unchanged: dict[str, bool] = {}
    files: dict[str, bool] = {}
    for check in case.checks:
        if check.kind == "project_field":
            spec = root / "projects" / check.params["project"] / "spec.json"
            projects[check.params["project"]] = (
                json.loads(spec.read_text(encoding="utf-8")) if spec.exists() else None
            )
        elif check.kind == "file_unchanged":
            unchanged[check.params["path"]] = _sha(root / check.params["path"]) == before.get(
                check.params["path"]
            )
        elif check.kind == "file_exists":
            files[check.params["glob"]] = any(root.glob(check.params["glob"]))
    return {"projects": projects, "unchanged": unchanged, "files": files}


def run_case(
    case: EvalCase,
    chat_factory: Callable[[EvalCase, Mapping[str, str]], ChatModel],
    available: set[str],
    root: Path,
    real_tools: bool = False,
    memory: MemoryProbe | None = None,
) -> tuple[CaseResult, int | None]:
    """Roda um pedido na pasta `root` e devolve o resultado e a memória medida do modelo logo depois."""
    from ..pipeline.recipes import project_exists

    with isolated_workspace(root):
        names = build_media(case.fixtures, root / "midia")
        create_projects(case.fixtures, names)
        request = substitute(case.request, names)
        case = replace(
            case, checks=tuple(Check(c.kind, substitute(c.params, names), c.real_only) for c in case.checks)
        )
        watched = [c.params["path"] for c in case.checks if c.kind == "file_unchanged"]
        before = {path: _sha(root / path) for path in watched}

        executed: list[tuple[str, dict]] = []
        attempted: list[str] = []
        kits: list[str] = []
        replies: list[float] = []
        policy = ScriptedPolicy(case.confirm, case.consent)

        def listen(kind: str, data: dict[str, Any]) -> None:
            if kind == "tool_call":
                attempted.append(data["name"])
            elif kind == "triage":
                kits.extend(data["kits"])
            elif kind == "model_reply":
                replies.append(data["seconds"])

        defaults = {"wait_seconds": DEFAULT_WAIT_SECONDS, "show_ui": False}

        def make_host(tool_names: list[str]) -> ToolHost:
            return RecordingHost(
                McpToolHost(allowed=tool_names, argument_defaults=defaults), executed, not real_tools
            )

        session = AgentSession(
            chat=chat_factory(case, names),
            host_factory=make_host,
            available=available,
            policy=policy,
            on_event=listen,
            project_exists=project_exists,
        )
        started = time.monotonic()
        error = ""
        answer = ""
        try:
            answer = session.ask(request)
        except Exception as exc:  # noqa: BLE001 - um pedido que quebra conta como falha, não derruba a bateria
            error = f"{type(exc).__name__}: {exc}"
        seconds = time.monotonic() - started
        seen = Observation(
            executed=executed,
            attempted=attempted,
            asked=policy.asked,
            kits=tuple(dict.fromkeys(kits)),
            answer=answer,
            **_observe(case, root, before),
        )
        failed, unsafe = evaluate_case(case, seen, real_tools)
        if error:
            failed.append(error)
        result = CaseResult(
            case_id=case.id,
            passed=not failed,
            failed=failed,
            unsafe=unsafe,
            steps=session.steps_taken,
            seconds=seconds,
            first_reply_seconds=replies[0] if replies and case.simple else None,
            tools=[name for name, _ in executed],
            answer=answer,
            error=error,
        )
    return result, memory.measure() if memory else None


def oracle_factory(case: EvalCase, names: Mapping[str, str]) -> ChatModel:
    """O modelo falso do pedido: os passos do roteiro com os caminhos sintéticos no lugar dos marcadores."""
    hinted = [kit for check in case.checks if check.kind == "kit" for kit in check.params["kits"]]
    return OracleChat(substitute(list(case.oracle), names), hinted)


def same_chat(chat: ChatModel) -> Callable[[EvalCase, Mapping[str, str]], ChatModel]:
    """O mesmo modelo real para todos os pedidos (cada pedido começa uma conversa nova, mas o motor é um só)."""
    return lambda case, names: chat


def run_battery(
    cases: Sequence[EvalCase],
    settings: AgentSettings,
    fake: bool = False,
    real_tools: bool = False,
    progress: Callable[[str], None] = lambda line: None,
    memory: MemoryProbe | None = None,
    available: set[str] | None = None,
    chat_factory: Callable[[EvalCase, Mapping[str, str]], ChatModel] | None = None,
) -> BatteryReport:
    """Roda a bateria inteira e devolve o relatório. Sem `chat_factory`, usa o modelo falso (`fake`) ou o configurado."""
    present = server_tool_names() if available is None else available
    if chat_factory is None:
        chat_factory = oracle_factory if fake else same_chat(build_chat(settings))
    probe = memory if memory is not None else (None if fake else PsutilMemoryProbe())
    results: list[CaseResult] = []
    peak: int | None = None
    for case in cases:
        missing = [tool for tool in case.requires_tools if tool not in present]
        if missing:
            progress(f"{case.id}: pendente (falta {', '.join(missing)})")
            results.append(CaseResult(case.id, False, skipped=f"falta a ferramenta {', '.join(missing)}"))
            continue
        with tempfile.TemporaryDirectory(prefix="dmaker-avaliacao-", ignore_cleanup_errors=True) as folder:
            result, used = run_case(case, chat_factory, present, Path(folder), real_tools, probe)
        if used is not None:
            peak = max(peak or 0, used)
        progress(
            f"{case.id}: {'ok' if result.passed else 'FALHOU'} ({result.steps} passos, {result.seconds:.1f} s)"
        )
        results.append(result)
    return BatteryReport(
        model="modelo falso" if fake else settings.model,
        engine=settings.engine_label,
        results=results,
        memory_bytes=peak,
        fake=fake,
        real_tools=real_tools,
    )
