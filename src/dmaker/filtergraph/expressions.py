"""Peças de expressão do FFmpeg compartilhadas pelas transições e pelo vazamento de luz."""

from __future__ import annotations

from collections.abc import Sequence


def number(value: float, digits: int = 4) -> str:
    """Número curto e estável para dentro de uma expressão (sem notação científica nem zeros sobrando)."""
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def lookup(values: Sequence[float], index: str, digits: int = 4) -> str:
    """Tabela por quadro como expressão: o filtro avalia a cada quadro e não tem vetor, então a tabela vira
    uma árvore de `if` com busca binária (profundidade log2 N). O último valor vale para índices além da tabela
    e o primeiro para os negativos; `index` é a variável de quadro do filtro (`n`, `in`, `N`)."""
    if not values:
        raise ValueError("tabela vazia")

    def branch(low: int, high: int) -> str:
        if low == high:
            return number(values[low], digits)
        middle = (low + high) // 2
        return f"if(lt({index},{middle + 0.5:g}),{branch(low, middle)},{branch(middle + 1, high)})"

    return branch(0, len(values) - 1)


def sendcmd_table(target: str, option: str, values: Sequence[float], fps: float, digits: int = 3) -> str:
    """Comandos do `sendcmd` que dão ao filtro `target` o valor de `option` de cada quadro, para as opções
    que o FFmpeg aceita mudar em tempo de execução mas que não são expressão (o sigma do `gblur`, por
    exemplo). Cada comando vale a partir de meio quadro antes do quadro k: o timestamp do quadro k é k/fps
    arredondado ao microssegundo, e comparar em cima dele poderia atrasar o comando em um quadro. Deve ficar
    logo antes do filtro `target`, na mesma cadeia, para o quadro passar pelos dois sem fila no meio."""
    commands = [
        f"{number(max(0.0, (k - 0.5) / fps), 6)} {target} {option} {number(value, digits)}"
        for k, value in enumerate(values)
    ]
    return ";".join(commands)
