"""O arquivo de marcadores (`.txt`) do Audacity: ler e escrever, sem tocar disco.

O formato é o que o Audacity exporta de uma trilha de rótulos (label track): uma linha por rótulo, com início, fim e
texto separados por tabulação, os tempos em segundos com ponto decimal e seis casas. O rótulo pontual repete o
instante nas duas colunas. Um rótulo espectral ganha, além da linha dele, uma linha que começa com `\\` e traz as
frequências de baixo e de cima (`-1` quando não há). Ler e escrever com as mesmas regras faz o arquivo voltar
idêntico, byte a byte."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .spec import Marker

TIME_DECIMALS = 6  # as casas que o Audacity grava: 12.345678
NO_FREQUENCY = -1.0  # o que o Audacity escreve onde o rótulo não tem faixa de frequência
SPECTRAL_MARK = "\\"
_LINE_BREAK = re.compile(r"\r\n|\r|\n")


@dataclass(frozen=True)
class ParsedLabels:
    markers: list[Marker]
    warnings: list[str]


def _number(raw: str) -> float | None:
    """O número de uma coluna; a vírgula decimal de um Audacity em outro idioma também vale."""
    try:
        return float(raw.strip().replace(",", "."))
    except ValueError:
        return None


def _split_lines(text: str) -> list[str]:
    lines = _LINE_BREAK.split(text.lstrip("﻿"))
    if lines and lines[-1] == "":
        lines.pop()  # o arquivo termina com quebra de linha
    return lines


def _parse_label(line: str, group: str) -> Marker | str:
    """O rótulo de uma linha, ou o motivo de ela não valer."""
    columns = line.split("\t", 2)
    start = _number(columns[0])
    if start is None:
        return "o início não é um número"
    end = _number(columns[1]) if len(columns) > 1 else None
    if end is None:
        # sem coluna de fim, a segunda coluna é o texto de um rótulo pontual
        text = "\t".join(columns[1:])
        end = start
    else:
        text = columns[2] if len(columns) > 2 else ""
    if start < 0 or end < 0:
        return "o tempo é negativo"
    if end < start:
        return "o fim vem antes do início"
    if end == start:
        return Marker(at=start, text=text, group=group)
    return Marker(start=start, end=end, text=text, group=group)


def _frequencies(line: str) -> tuple[float, float] | None:
    """As duas frequências de uma linha `\\`, ou nulo se não houver faixa (`-1`) ou a linha estiver quebrada."""
    columns = line.split("\t")
    if len(columns) < 3:
        return None
    low, high = _number(columns[1]), _number(columns[2])
    if low is None or high is None or low <= 0 or high <= 0:
        return None
    return low, high


def parse_labels(text: str, group: str = "") -> ParsedLabels:
    """Os marcadores do texto do Audacity, todos no `group` dado. Linha que não dá para ler é pulada com um aviso
    que cita o número dela; a faixa de frequência de um rótulo espectral vai para `low_hz` e `high_hz`.

    As linhas `\\` podem vir logo depois do rótulo a que pertencem ou todas juntas no fim do arquivo (um par para cada
    rótulo, na ordem); as duas formas são lidas."""
    lines = _split_lines(text)
    last_label_line = max(
        (number for number, line in enumerate(lines) if line.strip() and not line.startswith(SPECTRAL_MARK)),
        default=-1,
    )
    markers: list[Marker] = []
    warnings: list[str] = []
    trailing_pairs = 0
    for number, line in enumerate(lines):
        if not line.strip():
            continue
        if line.startswith(SPECTRAL_MARK):
            frequencies = _frequencies(line)
            if number > last_label_line:  # bloco de frequências no fim: a n-ésima linha é do n-ésimo rótulo
                target = trailing_pairs
                trailing_pairs += 1
            else:  # logo depois do rótulo: é do último lido
                target = len(markers) - 1
            if frequencies is not None and 0 <= target < len(markers):
                markers[target] = markers[target].model_copy(
                    update={"low_hz": frequencies[0], "high_hz": frequencies[1]}
                )
            continue
        label = _parse_label(line, group)
        if isinstance(label, str):
            warnings.append(f"Linha {number + 1} ignorada: {label}.")
            continue
        markers.append(label)
    return ParsedLabels(markers, warnings)


def _time(value: float) -> str:
    return f"{value:.{TIME_DECIMALS}f}"


def _clean_text(text: str) -> str:
    """Tabulação e quebra de linha no texto quebrariam as colunas do arquivo."""
    return _LINE_BREAK.sub(" ", text).replace("\t", " ")


def format_labels(markers: Sequence[Marker], newline: str = "\n") -> str:
    """O arquivo do Audacity com estes marcadores, em ordem de início (a ordem em que ele guarda os rótulos).
    Se algum marcador tem faixa de frequência, as linhas `\\` vêm depois de todos os rótulos, uma por rótulo."""
    ordered = sorted(markers, key=lambda marker: marker.begin)  # estável: empates ficam como estavam
    lines = [
        f"{_time(marker.begin)}\t{_time(marker.finish)}\t{_clean_text(marker.text)}" for marker in ordered
    ]
    if any(marker.low_hz is not None and marker.high_hz is not None for marker in ordered):
        for marker in ordered:
            low = marker.low_hz if marker.low_hz is not None and marker.high_hz is not None else NO_FREQUENCY
            high = (
                marker.high_hz if marker.low_hz is not None and marker.high_hz is not None else NO_FREQUENCY
            )
            lines.append(f"{SPECTRAL_MARK}\t{_time(low)}\t{_time(high)}")
    return "".join(f"{line}{newline}" for line in lines)
