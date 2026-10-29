"""Bateria de avaliação contra o modelo local de verdade: lenta (minutos por pedido na CPU) e desligada por padrão.

Liga com `DMAKER_AGENT_EVAL=1` (o motor e o modelo vêm de `DMAKER_AGENT_ENGINE` e `DMAKER_AGENT_MODEL`), no
mesmo espírito do `DMAKER_VOICE_SMOKE`. `DMAKER_AGENT_EVAL_REAL_TOOLS=1` também executa as ferramentas pesadas
(render, Whisper, dublagem). Não deixe a variável ligada na sessão depois.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dmaker.agent import evaluation_runner as runner
from dmaker.agent.evaluation import FIRST_REPLY_LIMIT_S, PASS_THRESHOLD, load_cases, write_report
from dmaker.agent.settings import build_chat, load_settings

pytestmark = pytest.mark.skipif(
    os.environ.get("DMAKER_AGENT_EVAL") != "1",
    reason="avaliação lenta com o modelo real: ligue com DMAKER_AGENT_EVAL=1",
)

DATA = Path(__file__).parent / "data" / "agent_eval.json"


def test_the_local_model_passes_the_battery_without_an_unconfirmed_deletion(tmp_path):
    settings = load_settings()
    chat = build_chat(settings)
    assert chat.is_alive() and chat.has_model(), (
        f"o modelo {settings.model} não está disponível em {settings.url}"
    )
    real_tools = os.environ.get("DMAKER_AGENT_EVAL_REAL_TOOLS") == "1"

    report = runner.run_battery(
        load_cases(DATA), settings, real_tools=real_tools, progress=lambda line: print(line, flush=True)
    )
    markdown, _ = write_report(report, tmp_path)
    print(markdown.read_text(encoding="utf-8"))

    assert report.unsafe_cases == [], "arquivo apagado ou sobrescrito sem confirmação"
    assert report.accuracy >= PASS_THRESHOLD, f"acerto {report.accuracy:.0%}, esperado {PASS_THRESHOLD:.0%}"
    first = report.first_reply_seconds
    assert first is None or first < FIRST_REPLY_LIMIT_S, f"primeira resposta em {first:.0f} s"
