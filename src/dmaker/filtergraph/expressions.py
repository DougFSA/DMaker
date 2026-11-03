"""Peças de expressão do FFmpeg compartilhadas pelas transições e pelo vazamento de luz."""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable, Mapping, Sequence

_BINARY: dict[type, Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY: dict[type, Callable[[float], float]] = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def evaluate(expression: str, variables: Mapping[str, float]) -> float:
    """Valor de uma expressão aritmética do FFmpeg (`W-w-60`, `(W-w)/2`, `540.00-w/2`) com as variáveis dadas.

    Quem precisa saber ONDE o `overlay` pôs uma camada (a caixa de uma sobreposição na interface, a zona segura
    no QA) avalia a mesma expressão que o grafo usa, em vez de repetir a tabela de posições em outra conta.
    Só aceita números, as variáveis, `+ - * /` e parênteses: o resto levanta ValueError.
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"expressão inválida: {expression!r}") from exc
    return _evaluate_node(tree.body, variables, expression)


def _evaluate_node(node: ast.expr, variables: Mapping[str, float], source: str) -> float:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int | float)
        and not isinstance(node.value, bool)
    ):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in variables:
        return float(variables[node.id])
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_evaluate_node(node.operand, variables, source))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left = _evaluate_node(node.left, variables, source)
        right = _evaluate_node(node.right, variables, source)
        return _BINARY[type(node.op)](left, right)
    raise ValueError(f"expressão fora do que sei avaliar: {source!r}")


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
