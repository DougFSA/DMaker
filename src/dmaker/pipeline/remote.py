"""Ponte entre um processo qualquer (CLI, MCP) e a interface gráfica (`dmaker ui`).

Faz o render "aparecer" na interface mesmo quando disparado de fora dela: `UIClient` fala com a API
local por HTTP (stdlib, sem dependência nova); `launch_ui` sobe o servidor em segundo plano quando ele
ainda não está de pé; `RenderDispatcher` junta as duas coisas e traduz os eventos SSE do job em chamadas
de `ProgressSink` e de log, para quem chamou continuar vendo o progresso no seu próprio terminal.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import config
from ..media.ffmpeg import ProgressSink

UI_URL_ENV = "DMAKER_UI_URL"
DEFAULT_UI_URL = "http://127.0.0.1:8765"

# Maior que o intervalo de keep-alive do SSE (15s, ver ui/server.py job_events), para não estourar o
# timeout de leitura só porque o job está demorando para gerar um evento novo.
EVENTS_READ_TIMEOUT = 30.0

# Quanto esperar o processo desacoplado da interface responder antes de desistir.
LAUNCH_TIMEOUT = 15.0


def ui_url() -> str:
    """Endereço da interface: `DMAKER_UI_URL` se definida, senão o padrão local."""
    return os.environ.get(UI_URL_ENV, DEFAULT_UI_URL)


def _port_of(url: str) -> int:
    parsed = urllib.parse.urlparse(url)
    return parsed.port or 8765


class UIClient:
    """Fala com a API local da interface (`ui/server.py`) por HTTP simples."""

    def __init__(self, base_url: str | None = None, timeout: float = 2.0):
        self.base_url = (base_url or ui_url()).rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict | None = None, timeout: float | None = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout if timeout is not None else self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def is_alive(self) -> bool:
        try:
            self._request("GET", "/api/state")
            return True
        except (OSError, ValueError):
            return False

    def render(self, name: str, options: dict) -> dict:
        """POST .../render; `focus: true` garante que a interface abra o painel deste job sozinha."""
        body = {**options, "focus": True}
        return self._request("POST", f"/api/projects/{urllib.parse.quote(name)}/render", body)

    def export(self, name: str, presets: list[str]) -> dict:
        return self._request("POST", f"/api/projects/{urllib.parse.quote(name)}/export", {"presets": presets})

    def job(self, job_id: str) -> dict:
        return self._request("GET", f"/api/jobs/{job_id}")

    def jobs(self) -> list[dict]:
        return self._request("GET", "/api/jobs")

    def clients_active(self) -> bool:
        try:
            return bool(self._request("GET", "/api/clients").get("active"))
        except (OSError, ValueError):
            return False

    def events(self, job_id: str) -> Iterator[dict]:
        """Lê /api/jobs/{id}/events linha a linha (SSE) até o evento "end" (job pronto ou com erro)."""
        req = urllib.request.Request(f"{self.base_url}/api/jobs/{job_id}/events", method="GET")
        with urllib.request.urlopen(req, timeout=EVENTS_READ_TIMEOUT) as resp:
            for raw in resp:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue  # linha em branco ou ": keep-alive"
                event = json.loads(line[len("data:") :].strip())
                yield event
                if event.get("kind") == "end":
                    return


def _dmaker_executable() -> list[str]:
    """Comando para rodar o `dmaker` deste mesmo venv (não o Python global nem outro do PATH)."""
    exe_name = "dmaker.exe" if os.name == "nt" else "dmaker"
    candidate = Path(sys.executable).parent / exe_name  # Scripts/ (Windows) ou bin/ (Linux/Mac)
    if candidate.exists():
        return [str(candidate)]
    return [sys.executable, "-m", "dmaker.cli"]


def launch_ui(port: int | None = None) -> None:
    """Sobe `dmaker ui --no-browser --port <port>` desacoplado do processo atual e espera responder.

    O processo continua vivo depois que quem chamou terminar (Windows: DETACHED_PROCESS +
    CREATE_NEW_PROCESS_GROUP, para não morrer junto com o console pai; saída em cache/jobs/ui.log).
    """
    port = port or _port_of(ui_url())
    config.ensure_dirs()
    log_path = config.JOBS_DIR / "ui.log"
    cmd = [*_dmaker_executable(), "ui", "--no-browser", "--port", str(port)]
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    with open(log_path, "ab") as log_file:
        subprocess.Popen(cmd, stdout=log_file, stderr=log_file, **kwargs)

    client = UIClient(f"http://127.0.0.1:{port}")
    deadline = time.time() + LAUNCH_TIMEOUT
    while time.time() < deadline:
        if client.is_alive():
            return
        time.sleep(0.3)
    raise RuntimeError(
        f"Não consegui subir a interface DMaker em {client.base_url} (mais de {LAUNCH_TIMEOUT:.0f}s). "
        f"Veja {log_path} ou rode `dmaker ui` manualmente."
    )


@dataclass
class RenderDispatcher:
    """Garante a interface no ar, dispara um render/export nela e acompanha pelo SSE.

    `launcher` e `opener` são injetáveis para teste (dublês que não sobem processo nem abrem navegador
    de verdade); `client` também, para testar sem um servidor HTTP real.
    """

    client: UIClient
    launcher: Callable[[], None] = launch_ui
    opener: Callable[[str], None] = webbrowser.open
    log: Callable[[str], None] | None = None
    _just_launched: bool = field(default=False, init=False, repr=False)

    def _emit(self, message: str) -> None:
        if self.log:
            self.log(message)

    def ensure_ui(self) -> bool:
        """Verifica se a interface está no ar; se não estiver, sobe. Lança RuntimeError se não conseguir."""
        if self.client.is_alive():
            return True
        self._emit(f"Interface não está aberta; subindo em segundo plano ({self.client.base_url})...")
        self.launcher()
        self._just_launched = True
        if not self.client.is_alive():
            raise RuntimeError(f"Não consegui abrir a interface DMaker em {self.client.base_url}.")
        return True

    def open_browser_if_needed(self, name: str, job_id: str) -> None:
        """Abre a aba do projeto/job só se acabou de subir o servidor ou se não há ninguém olhando a
        página já aberta, para não empilhar abas a cada render."""
        should_open = self._just_launched or not self.client.clients_active()
        self._just_launched = False
        if not should_open:
            return
        url = f"{self.client.base_url}/#project={urllib.parse.quote(name)}&job={job_id}"
        self._emit(f"Abrindo a interface: {url}")
        self.opener(url)

    def follow(self, job_id: str, sink: ProgressSink, log: Callable[[str], None]) -> dict:
        """Acompanha um job já disparado na interface, traduzindo os eventos SSE para `sink` e `log`.

        Devolve o snapshot final do job (com `result`); erro do job vira RuntimeError com a mensagem.
        """
        current_label: str | None = None
        for event in self.client.events(job_id):
            kind = event.get("kind")
            if kind == "start":
                log(f"Iniciado: {event.get('description') or ''}")
            elif kind == "log":
                log(event.get("message", ""))
            elif kind == "progress":
                label = event.get("label", "")
                if label != current_label:
                    if current_label is not None:
                        sink.finish()
                    sink.start(label, event.get("total"))
                    current_label = label
                sink.update(event.get("done", 0.0))
                if event.get("percent") == 100:
                    sink.finish()
                    current_label = None
            elif kind == "end":
                if current_label is not None:
                    sink.finish()
                    current_label = None
                if event.get("status") != "done":
                    raise RuntimeError(event.get("error") or "falha desconhecida no render pela interface")
        return self.client.job(job_id)

    def render(self, name: str, options: dict, sink: ProgressSink, log: Callable[[str], None]) -> dict:
        """Dispara o render na interface (subindo-a se preciso) e acompanha até o fim."""
        self.ensure_ui()
        started = self.client.render(name, options)
        job_id = started["job_id"]
        self.open_browser_if_needed(name, job_id)
        return self.follow(job_id, sink, log)

    def export(self, name: str, presets: list[str], sink: ProgressSink, log: Callable[[str], None]) -> dict:
        """Dispara a exportação (vários presets, um job só) na interface e acompanha até o fim."""
        self.ensure_ui()
        started = self.client.export(name, presets)
        job_id = started["job_id"]
        self.open_browser_if_needed(name, job_id)
        return self.follow(job_id, sink, log)
