"""Aparo do histórico: tira os turnos mais antigos da conversa para o pedido caber no contexto do modelo.

Uma conversa salva cresce sem limite, mas o modelo só lê `num_ctx` tokens: passou disso, o servidor corta o começo
por conta própria (e leva junto o prompt de sistema). Aparar aqui, por turno inteiro, mantém o que o modelo vê
coerente. Tudo é função pura sobre as mensagens: o laço do agente decide quando chamar e avisa a pessoa do que saiu.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# PT-BR e JSON de ferramenta rendem uns 3 a 4 caracteres por token; 3 erra para o lado seguro (aparar antes da hora
# custa um pouco de memória, aparar tarde demais custa o prompt de sistema).
DEFAULT_CHARS_PER_TOKEN = 3.0
MIN_CHARS_PER_TOKEN = 1.5
# Parte do contexto que fica livre para a resposta (o raciocínio do gpt-oss também sai desse espaço).
REPLY_RESERVE_RATIO = 0.25
MIN_REPLY_RESERVE_TOKENS = 1024
# Cada mensagem custa alguns tokens de moldura (papel, separadores) além do texto.
MESSAGE_FRAME_TOKENS = 4
# Uma imagem custa tokens, não caracteres: o base64 dela não pode inflar a conta. O valor é uma média grosseira.
IMAGE_TOKENS = 1024


@dataclass(frozen=True)
class TrimResult:
    """O histórico já aparado e quantos turnos saíram (0 quando tudo coube)."""

    messages: list[dict[str, Any]]
    removed_turns: int
    estimated_tokens: int  # do pedido que vai ao modelo, depois do aparo
    budget_tokens: int


def message_chars(message: dict[str, Any]) -> int:
    """Os caracteres de texto de uma mensagem: conteúdo, chamadas de ferramenta e nome (imagens contam à parte)."""
    total = len(str(message.get("content") or "")) + len(str(message.get("tool_name") or ""))
    if calls := message.get("tool_calls"):
        total += len(json.dumps(calls, ensure_ascii=False))
    return total


def image_count(messages: Sequence[dict[str, Any]]) -> int:
    return sum(len(message.get("images") or []) for message in messages)


def request_chars(messages: Sequence[dict[str, Any]], overhead_chars: int = 0) -> int:
    """O tamanho em caracteres do que vai ao modelo; `overhead_chars` são as definições de ferramenta, fora das mensagens."""
    return overhead_chars + sum(message_chars(message) for message in messages)


def estimate_tokens(
    messages: Sequence[dict[str, Any]],
    overhead_chars: int = 0,
    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
) -> int:
    """Estimativa de tokens do pedido, por caracteres. Com `chars_per_token` medido, fica mais fiel ao modelo real."""
    text_tokens = request_chars(messages, overhead_chars) / max(chars_per_token, MIN_CHARS_PER_TOKEN)
    return round(text_tokens + MESSAGE_FRAME_TOKENS * len(messages) + IMAGE_TOKENS * image_count(messages))


def calibrated_chars_per_token(sent_chars: int, prompt_tokens: int | None, images: int = 0) -> float:
    """Caracteres por token medidos na última resposta; nunca acima do padrão, só para o lado conservador.

    O Ollama pode contar em `prompt_eval_count` só os tokens novos quando reaproveita o começo do pedido do cache, o
    que faria cada token parecer render muitos caracteres e a conta subestimar o pedido. Por isso a medição só
    vale quando indica tokens MAIS caros que o padrão (texto mais denso, como código ou JSON).
    """
    if not prompt_tokens or prompt_tokens <= 0 or sent_chars <= 0:
        return DEFAULT_CHARS_PER_TOKEN
    text_tokens = prompt_tokens - images * IMAGE_TOKENS
    if text_tokens <= 0:
        return DEFAULT_CHARS_PER_TOKEN
    return min(DEFAULT_CHARS_PER_TOKEN, max(MIN_CHARS_PER_TOKEN, sent_chars / text_tokens))


def prompt_budget(num_ctx: int) -> int:
    """Quantos tokens o pedido pode ter: o contexto menos o espaço reservado para a resposta."""
    reserve = max(MIN_REPLY_RESERVE_TOKENS, round(num_ctx * REPLY_RESERVE_RATIO))
    return max(num_ctx - reserve, 0)


def turn_starts(messages: Sequence[dict[str, Any]]) -> list[int]:
    """Onde cada turno começa: um turno é a mensagem do usuário e tudo que veio depois dela até a próxima."""
    return [index for index, message in enumerate(messages) if message.get("role") == "user"]


def trim_history(
    messages: Sequence[dict[str, Any]],
    num_ctx: int,
    overhead_chars: int = 0,
    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN,
) -> TrimResult:
    """Corta os turnos mais antigos até o pedido caber em `num_ctx` (menos o espaço da resposta).

    `messages[0]` é o prompt de sistema e fica sempre. Corta-se por turno inteiro, o que mantém cada chamada de
    ferramenta junto do seu resultado. O último turno (o pedido de agora) nunca sai, mesmo que sozinho passe do
    limite: aí não há mais o que cortar sem perder a pergunta.
    """
    budget = prompt_budget(num_ctx)
    kept = list(messages)
    removed = 0
    while True:
        starts = turn_starts(kept)
        if len(starts) <= 1 or estimate_tokens(kept, overhead_chars, chars_per_token) <= budget:
            break
        # tira o turno mais antigo: da primeira mensagem de usuário até a seguinte
        head = kept[: starts[0]]
        kept = head + kept[starts[1] :]
        removed += 1
    return TrimResult(kept, removed, estimate_tokens(kept, overhead_chars, chars_per_token), budget)


INTERRUPTED_TOOL_RESULT = "Esta ferramenta não terminou porque o DMaker foi fechado."


def repair_history(messages: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dá resultado a toda chamada de ferramenta que ficou sem ele (o DMaker fechou no meio de um turno).

    Uma chamada sem resposta deixaria o histórico torto para o modelo; o par é completado com um resultado que diz o
    que houve, sem inventar que a ferramenta rodou.
    """
    pending = list(messages)
    repaired: list[dict[str, Any]] = []
    index = 0
    while index < len(pending):
        message = pending[index]
        repaired.append(message)
        index += 1
        calls = message.get("tool_calls") if message.get("role") == "assistant" else None
        if not calls:
            continue
        answered = 0
        while answered < len(calls) and index < len(pending) and pending[index].get("role") == "tool":
            repaired.append(pending[index])
            index += 1
            answered += 1
        for call in calls[answered:]:
            name = (call.get("function") or {}).get("name", "")
            repaired.append({"role": "tool", "tool_name": name, "content": INTERRUPTED_TOOL_RESULT})
    return repaired
