"""Triagem: escolhe o kit de ferramentas pelo pedido, sem carregar o modelo quando as palavras bastam.

Primeiro uma regra pura por palavras-chave (português com e sem acento). Só quando ela não decide entra uma
chamada curta ao modelo, com os nomes e as descrições dos kits. Um pedido que cruza kits ("corta as pausas e
legenda") cai em um só quando a receita do servidor já cobre os dois; quando as palavras empatam, o pedido
leva os dois kits (no máximo `MAX_KITS_PER_REQUEST`).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .kits import DEFAULT_KIT, KITS, MAX_KITS_PER_REQUEST, Kit
from .llm import ChatModel

TriageMethod = Literal["keywords", "previous", "model", "default"]

SHORT_KEYWORD = 3  # radicais de até 3 letras (srt, csv, cta) só casam a palavra inteira
_WORD = re.compile(r"[a-z0-9]+")

TRIAGE_SYSTEM = (
    "Você escolhe quais kits de ferramentas do DMaker servem para o pedido do usuário. "
    "Responda SOMENTE com o nome de um kit, ou de dois separados por vírgula, sem mais nenhuma palavra."
)


@dataclass(frozen=True)
class Triage:
    """O resultado: os kits escolhidos (na ordem de relevância) e como a escolha foi feita."""

    kits: tuple[str, ...]
    method: TriageMethod
    scores: tuple[tuple[str, int], ...] = ()


def normalize(text: str) -> str:
    """Minúsculas, sem acento e sem apóstrofo: 'Água', 'agua' e 'd'água' viram o mesmo texto."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return plain.replace("'", "").replace("’", "")


def _matches(keyword: str, text: str, words: Sequence[str]) -> bool:
    if " " in keyword:
        return re.search(rf"\b{re.escape(keyword)}", text) is not None
    if len(keyword) <= SHORT_KEYWORD:
        return keyword in words
    return any(word.startswith(keyword) for word in words)


def score_kit(kit: Kit, request: str) -> int:
    """Quantos pontos o pedido dá ao kit: cada palavra-chave vale 1, e uma expressão vale 1 por palavra."""
    text = normalize(request)
    words = _WORD.findall(text)
    return sum(1 + keyword.count(" ") for keyword in kit.keywords if _matches(keyword, text, words))


def score_kits(request: str, kits: Sequence[Kit] = KITS) -> list[tuple[Kit, int]]:
    """Os kits com pelo menos um ponto, do maior para o menor (empate segue a ordem dos kits)."""
    scored = [(kit, score_kit(kit, request)) for kit in kits]
    return sorted(((kit, points) for kit, points in scored if points > 0), key=lambda item: -item[1])


def triage_by_keywords(request: str, kits: Sequence[Kit] = KITS) -> Triage | None:
    """Decide só pelas palavras; `None` quando nenhuma palavra-chave aparece e a regra não tem opinião."""
    ranked = score_kits(request, kits)
    if not ranked:
        return None
    top = ranked[0][1]
    chosen = [kit.name for kit, points in ranked if points == top][:MAX_KITS_PER_REQUEST]
    return Triage(tuple(chosen), "keywords", tuple((kit.name, points) for kit, points in ranked))


def kit_menu(kits: Sequence[Kit] = KITS) -> str:
    return "\n".join(f"- {kit.name}: {kit.description}" for kit in kits)


def triage_messages(request: str, kits: Sequence[Kit] = KITS) -> list[dict]:
    """A chamada curta ao modelo: os kits com a descrição de uma linha e o pedido, nada além."""
    return [
        {"role": "system", "content": TRIAGE_SYSTEM},
        {"role": "user", "content": f"Kits:\n{kit_menu(kits)}\n\nPedido: {request}\n\nKits escolhidos:"},
    ]


def parse_kit_names(reply: str, kits: Sequence[Kit] = KITS) -> tuple[str, ...]:
    """Os nomes de kit que a resposta do modelo cita, na ordem em que aparecem e sem repetir."""
    text = normalize(reply)
    found = sorted(
        ((text.find(kit.name), kit.name) for kit in kits if kit.name in text),
        key=lambda item: item[0],
    )
    return tuple(name for _, name in found)[:MAX_KITS_PER_REQUEST]


def triage_by_model(request: str, chat: ChatModel, kits: Sequence[Kit] = KITS) -> Triage | None:
    """Pergunta ao modelo qual kit serve; `None` se a resposta não cita nenhum kit conhecido."""
    reply = chat.chat(triage_messages(request, kits), [])
    names = parse_kit_names(reply.content, kits)
    return Triage(names, "model") if names else None


def triage(
    request: str,
    chat: ChatModel | None = None,
    previous: Sequence[str] = (),
    kits: Sequence[Kit] = KITS,
) -> Triage:
    """Palavras primeiro; sem palavras, a resposta curta ("sim", "pode") continua no kit anterior; só então o
    modelo; se ele também não decide, o kit de edição, que é o caminho da maioria dos pedidos."""
    by_words = triage_by_keywords(request, kits)
    if by_words is not None:
        return by_words
    if previous:
        return Triage(tuple(previous), "previous")
    if chat is not None:
        by_model = triage_by_model(request, chat, kits)
        if by_model is not None:
            return by_model
    return Triage((DEFAULT_KIT,), "default")
