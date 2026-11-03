"""Bateria fixa de 10 perguntas ao manual, com o modelo local de verdade e a rede bloqueada.

Lenta (o modelo roda na CPU, minutos por pergunta), então fica desligada: `DMAKER_MANUAL_EVAL=1` liga, como o
`DMAKER_VOICE_SMOKE` faz com os modelos de voz. Precisa do Ollama no ar com o modelo (`gpt-oss:20b` por padrão;
`DMAKER_MANUAL_EVAL_MODEL` troca). Meta do chamado: 9 de 10. Para ver o relatório na tela, rode com `-s`; para
guardá-lo, aponte `DMAKER_MANUAL_EVAL_REPORT` para um arquivo `.json`.
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.request
from pathlib import Path

import pytest

from dmaker import config
from dmaker.agent.llm import OllamaChat, ollama_url
from dmaker.manual import files, live
from dmaker.manual.ask import answer_question, thinking_level
from dmaker.manual.evaluation import grade, load_battery
from dmaker.manual.examples import command_problem
from dmaker.manual.search import ManualIndex

from .netguard import NetworkBlocked, is_local, only_localhost

BATTERY_PATH = Path(config.ROOT) / "tests" / "data" / "manual_perguntas.json"
TARGET = 9


def test_the_network_guard_lets_localhost_through_and_blocks_everything_else():
    assert is_local("127.0.0.1") and is_local("localhost") and is_local("::1") and is_local("[::1]")
    assert not is_local("8.8.8.8") and not is_local("example.com") and not is_local("192.168.0.10")
    with only_localhost() as blocked:
        with pytest.raises(NetworkBlocked):
            socket.create_connection(("example.com", 80), timeout=1)
        with pytest.raises(NetworkBlocked):
            socket.socket().connect(("93.184.216.34", 80))
        assert blocked == ["example.com", "93.184.216.34"]
    # fora do bloqueio a resolução volta ao normal
    assert socket.getaddrinfo("localhost", 80)


def _model_memory(base_url: str) -> dict:
    """O que o Ollama diz ocupar o modelo carregado (`/api/ps`): tamanho total e o que está na GPU, em GB."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/ps", timeout=5) as response:
            running = json.loads(response.read().decode("utf-8")).get("models") or []
    except OSError:
        return {}
    return {
        item["name"]: {
            "size_gb": round(item.get("size", 0) / 1e9, 1),
            "vram_gb": round(item.get("size_vram", 0) / 1e9, 1),
        }
        for item in running
    }


@pytest.mark.skipif(
    os.environ.get("DMAKER_MANUAL_EVAL") != "1", reason="lenta, com modelo real: defina DMAKER_MANUAL_EVAL=1"
)
def test_dmaker_ajuda_answers_the_fixed_battery_with_the_local_model_offline():
    model = os.environ.get("DMAKER_MANUAL_EVAL_MODEL", "gpt-oss:20b")
    base_url = ollama_url()
    chat = OllamaChat(
        model=model, base_url=base_url, num_ctx=16384, timeout=3600.0, think=thinking_level(model)
    )
    if not chat.is_alive() or not chat.has_model():
        pytest.skip(f"Ollama não está no ar em {base_url} com o modelo {model}")
    index = ManualIndex.from_text(files.read_manual())
    battery = load_battery(BATTERY_PATH.read_text(encoding="utf-8"))
    assert len(battery) == 10

    cli_root = live.cli_root()
    rows = []
    with only_localhost() as blocked:
        for question in battery:
            started = time.perf_counter()
            answer = answer_question(question.text, index, chat, ia_doc=files.read_ia_doc)
            seconds = time.perf_counter() - started
            result = grade(
                answer, question, lambda line: command_problem(line, cli_root, require_arguments=False)
            )
            rows.append(
                {
                    "id": question.id,
                    "pergunta": question.text,
                    "ok": result.ok,
                    "secao_consultada": result.section_ok,
                    "secao_citada_no_texto": result.section_in_text,
                    "termos_faltando": list(result.missing_terms),
                    "comandos_inventados": list(result.invalid_commands),
                    "segundos": round(seconds, 1),
                    "resposta": answer.text,
                    "fontes": [source.section for source in answer.sources],
                }
            )
            print(
                f"{'ok ' if result.ok else 'ERRO'} {seconds:6.1f}s  {question.text}  {list(result.invalid_commands) or ''}",
                flush=True,
            )
    report = {
        "modelo": model,
        "acertos": sum(row["ok"] for row in rows),
        "total": len(rows),
        "comandos_inventados": sum(len(row["comandos_inventados"]) for row in rows),
        "segundos_medios": round(sum(row["segundos"] for row in rows) / len(rows), 1),
        "tentativas_de_rede_bloqueadas": blocked,
        "memoria_do_modelo": _model_memory(base_url),
        "perguntas": rows,
    }
    target = os.environ.get("DMAKER_MANUAL_EVAL_REPORT")
    if target:
        Path(target).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "perguntas"}, ensure_ascii=False))
    for row in rows:
        print(
            f"{'ok ' if row['ok'] else 'ERRO'} {row['segundos']:6.1f}s  {row['pergunta']}  {row['termos_faltando'] or ''}"
        )

    assert blocked == [], f"o teste tentou falar com a internet: {blocked}"
    assert report["acertos"] >= TARGET, f"{report['acertos']} de {report['total']} (meta {TARGET})"
