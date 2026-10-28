"""A janela de transição: fatia só os quadros da troca para gastar filtro caro só neles, e os reconecta.

O `xfade` já trabalha só na janela. As transições de movimento (zoom, desfoque, deslocamento em tira) são
filtros por pixel e, aplicados ao vídeo inteiro, custariam o vídeo inteiro: aqui `a` é cortado em "antes" e
"cauda", `b` em "cabeça" e "depois", o efeito roda sobre cauda e cabeça (poucos quadros) e `concat` costura
os três pedaços de volta sem tocar nos quadros de fora.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..expressions import lookup
from .registry import TransitionRequest


@dataclass(frozen=True)
class Window:
    """Os quatro fluxos da fatia: `before` e `after` passam intactos; `tail` e `head` são a janela."""

    before: str
    tail: str
    head: str
    after: str


def open_window(request: TransitionRequest) -> tuple[list[str], Window]:
    """Corta `a` em [antes | cauda] e `b` em [cabeça | depois].

    `a` corta por tempo (a fatia começa onde o `xfade` começaria) e `b` por número de quadros: a janela tem
    `frames` quadros, o que sobra de `a` por arredondamento de tempo é descartado e, se faltar um quadro à
    cauda, o filtro que emparelha os dois fluxos repete o último. A cauda e a cabeça ganham timestamps 0, 1/fps,
    2/fps... idênticos, o que mantém os filtros de dois fluxos (xfade, overlay, hstack) emparelhando quadro com
    quadro. Os cortes de `a` e de `b` são complementares: nenhum quadro some nem se repete fora da janela.
    """
    t, fps, frames = request.tag, f"{request.fps:g}", request.frames
    lines = [
        f"{request.a}split=2[{t}_a0][{t}_a1]",
        f"[{t}_a0]trim=end={request.offset:.6f}[{t}_before]",
        f"[{t}_a1]trim=start={request.offset:.6f},setpts=N/{fps}/TB,trim=end_frame={frames}[{t}_tail]",
        f"{request.b}split=2[{t}_b0][{t}_b1]",
        f"[{t}_b0]trim=end_frame={frames},setpts=N/{fps}/TB[{t}_head]",
        f"[{t}_b1]trim=start_frame={frames},setpts=PTS-STARTPTS[{t}_after]",
    ]
    return lines, Window(f"[{t}_before]", f"[{t}_tail]", f"[{t}_head]", f"[{t}_after]")


def close_window(request: TransitionRequest, window: Window, middle: str) -> list[str]:
    """Costura antes, janela e depois. O `fps` final refaz timestamps e quadros duplicados ou faltantes que o
    `concat` possa deixar na emenda, como o resto da linha do tempo já faz depois de cada `concat`."""
    t = request.tag
    return [
        f"{window.before}{middle}{window.after}concat=n=3:v=1:a=0[{t}_joined]",
        f"[{t}_joined]fps={request.fps:g},settb=AVTB{request.out}",
    ]


def monotone(values: Sequence[float], ceiling: float = 1.0) -> list[float]:
    """Pesos que só crescem e nunca passam de `ceiling`: a mola volta atrás depois de passar do ponto, mas uma
    mistura de imagens (ou o tempo de um xfade) não pode andar para trás."""
    out: list[float] = []
    top = 0.0
    for value in values:
        top = max(top, min(value, ceiling))
        out.append(top)
    return out


def no_undershoot(progress: Sequence[float]) -> list[float]:
    """Depois de a mola chegar ao ponto final pela primeira vez, o progresso passa dele e volta, mas nunca para
    aquém: a mola física oscila dos dois lados, só que aquém do ponto a imagem de entrada voltaria a deixar ver
    um pedaço da de saída (ou a borda), e isso lê como defeito. Fica só a primeira passada, que lê como mola."""
    reached = False
    out: list[float] = []
    for value in progress:
        reached = reached or value >= 1.0
        out.append(max(value, 1.0) if reached else value)
    return out


def paced_crossfade(
    request: TransitionRequest, a: str, b: str, out: str, weights: Sequence[float], tag: str
) -> list[str]:
    """Mistura `a` e `b` (mesmo tamanho, `frames` quadros) com o peso de `b` dado quadro a quadro.

    Usa o `xfade fade` e dirige o progresso pelo timestamp de `a`: o `xfade` calcula o progresso do quadro
    como `(pts - offset) / duration` e o tira do primeiro fluxo, então reescrever o pts de `a` com
    `peso * duração` escolhe o peso de cada quadro sem filtro por pixel (rápido e sem arquivo). O `setpts`
    final devolve o ritmo constante de quadros. `weights` precisa ser não decrescente (use `monotone`).
    """
    d, fps = round(request.duration, 3), f"{request.fps:g}"
    pts_table = lookup([w * d for w in weights], "N", 6)
    return [
        f"{a}setpts='({pts_table})/TB'[{tag}_paced]",
        f"[{tag}_paced]{b}xfade=transition=fade:duration={d:.3f}:offset=0[{tag}_blend]",
        f"[{tag}_blend]setpts=N/{fps}/TB{out}",
    ]
