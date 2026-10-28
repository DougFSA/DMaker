"""Blocos gerados dentro do manual: o texto entre dois marcadores é do código e é reescrito por inteiro.

Os marcadores são comentários HTML, então não aparecem na leitura, no HTML nem no PDF.
"""

from __future__ import annotations

import re


class MarkerError(ValueError):
    """O manual não tem o par de marcadores que o gerador espera."""


def start_marker(name: str) -> str:
    return f"<!-- dmaker:gerado {name} -->"


def end_marker(name: str) -> str:
    return f"<!-- dmaker:fim-gerado {name} -->"


def _block_pattern(name: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?P<head>{re.escape(start_marker(name))}\n)(?P<body>.*?)(?P<tail>{re.escape(end_marker(name))})",
        re.DOTALL,
    )


def generated_names(text: str) -> list[str]:
    """Os nomes dos blocos gerados, na ordem em que aparecem no manual."""
    return re.findall(r"<!-- dmaker:gerado ([\w-]+) -->", text)


def read_generated(text: str, name: str) -> str | None:
    """O conteúdo atual de um bloco, ou `None` se o manual não o tem."""
    match = _block_pattern(name).search(text)
    return match.group("body").strip("\n") if match else None


def replace_generated(text: str, name: str, content: str) -> str:
    """Troca o conteúdo do bloco `name` por `content`; erro se o par de marcadores não existir."""
    pattern = _block_pattern(name)
    if not pattern.search(text):
        raise MarkerError(f"O manual não tem o bloco gerado '{name}' ({start_marker(name)}).")
    body = content.strip("\n")
    return pattern.sub(lambda m: f"{m.group('head')}\n{body}\n\n{m.group('tail')}", text, count=1)
