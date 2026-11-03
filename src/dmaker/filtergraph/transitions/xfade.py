"""Os tipos do `xfade` do FFmpeg, com curva de tempo opcional."""

from __future__ import annotations

from ...domain import curves
from ...domain.transitions import XFADE_TYPES
from ..expressions import lookup
from .registry import TransitionRequest, register
from .window import monotone


class XfadeTransition:
    """Constrói um tipo do xfade. Com curva linear gera a linha de sempre, idêntica byte a byte."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __call__(self, request: TransitionRequest) -> list[str]:
        duration, offset = request.duration, request.offset
        blend = f"xfade=transition={self.name}:duration={duration:.3f}:offset={offset:.3f}"
        if request.curve == "linear":
            return [f"{request.a}{request.b}{blend}{request.out}"]
        return self._paced(request, blend)

    def _paced(self, request: TransitionRequest, blend: str) -> list[str]:
        """Aplica a curva remapeando o tempo da janela: o `xfade` tira o progresso do timestamp do primeiro
        fluxo, então cada quadro de `a` dentro da janela ganha o timestamp `offset + duração * curva(k/N)`.
        A mola passa de 1, o que num wipe ou slide não tem sentido (a cortina não anda além da borda): o
        progresso é limitado a 1 e só cresce, e o resto da janela mostra o trecho seguinte já assentado."""
        t, fps = request.tag, f"{request.fps:g}"
        first = request.first_window_frame()
        weights = monotone(curves.samples(request.curve, request.frames))
        table = lookup(
            [round(request.offset, 3) + round(request.duration, 3) * w for w in weights], f"(N-{first})", 6
        )
        warp = f"if(lt(N,{first}),PTS,({table})/TB)"
        return [
            f"{request.a}setpts='{warp}'[{t}_paced]",
            f"[{t}_paced]{request.b}{blend}[{t}_x]",
            # o xfade devolve os quadros com o timestamp de `a` (deformado): volta ao ritmo constante
            f"[{t}_x]setpts=N/{fps}/TB{request.out}",
        ]


for _name in XFADE_TYPES:
    register(_name)(XfadeTransition(_name))
