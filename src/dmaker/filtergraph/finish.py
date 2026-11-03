"""Acabamento visual do mezanino: efeitos de câmera e de filme aplicados depois do ajuste de cor.

Cada efeito é um construtor puro, registrado por nome (o mesmo nome do campo de `ColorAdjust`): recebe o rótulo
de entrada e o de saída, a quantidade de 0 a 1 e o contexto (tamanho, fps e duração do trecho) e devolve linhas
de grafo do ffmpeg. Um efeito novo entra registrando outro construtor. A ordem do registro é a ordem no grafo:
brilho e aberração mexem na imagem, o vazamento de luz vem por cima e o grão por último, como na película.

Nada aqui executa o ffmpeg nem toca o disco, e tudo é determinístico: a mesma spec gera sempre os mesmos quadros
(o grão tem semente fixa e o vazamento é uma tabela por quadro).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from ..domain.spec import ColorAdjust
from .common import color_chain, fade_chains
from .expressions import number
from .lightleak import LeakLook, light_leak_source

# Quantas vezes o quadro é reduzido antes de borrar o brilho: um desfoque largo num quadro de 2 milhões de pixels
# custa dezenas de ms por quadro, e como a luz é difusa por natureza, a redução não aparece.
GLOW_DOWNSCALE = 4
# Raio do brilho, fração da largura: 1,5% (16 px num quadro de 1080) espalha a luz o bastante para ser um halo
# macio sem lavar os detalhes; proporcional à largura para o resultado ser o mesmo em qualquer resolução.
GLOW_RADIUS = 0.015
# O brilho nasce só das luzes: a luma abaixo de 150 não entra (cores saturadas de brilho médio, como um verde ou
# um azul vivo, não ganham halo) e 255 vira o branco cheio do halo; o ganho é 255 / (255 - 150), a rampa entre os dois.
GLOW_KNEE = 150
GLOW_GAIN = 2.43
# Opacidade do `screen` com quantidade 1: acima disso o halo some o contraste das luzes.
GLOW_MAX_OPACITY = 0.7

# Separação de vermelho e azul com quantidade 1, fração da largura: 0,5% (5 px em 1080). É o que um olho lê como
# franja de lente barata sem virar efeito de "glitch"; o deslocamento é proporcional à largura.
ABERRATION_MAX_SHIFT = 0.005

# Vazamento de luz: feixe largo e macio, rosa nas bordas, laranja no meio e quase branco no miolo, inclinado como
# uma fresta de luz na lateral da câmera. É mais largo e mais suave que o das transições, porque aqui ele passa
# por cima da imagem sem esconder nada.
LEAK_LOOK = LeakLook(
    edge=(224, 64, 120), mid=(255, 150, 50), core=(255, 232, 170), width=0.30, tilt=0.30, floor=0.0
)
LEAK_SPAN = (-0.3, 1.3)  # o centro do feixe entra fora da esquerda e sai fora da direita
LEAK_PEAK = 0.7  # opacidade máxima da luz com quantidade 1
LEAK_PERIOD = 4.0  # segundos por passagem; trecho mais curto faz uma passagem só, do tamanho dele

# Grão: uma textura de ruído gaussiano na luma, gerada UMA vez (semente fixa), em metade da resolução e ampliada, e
# deslocada alguns pixels a cada quadro. Para o olho, cada quadro tem um grão novo; para o x264, é a mesma textura em
# movimento, que ele prevê por vetor e quase não paga em quadro P. Medido a 1080x1920, CRF 18, 10 s de cena parada
# (0,1 MB sem grão), para o mesmo desvio visível de 1,4 nível: ruído novo a cada quadro 15 MB (e o x264 o aplicava em
# blocos, piscando), a textura deslocada em resolução cheia 4,9 MB, e em meia resolução 3,5 MB. O grão de 2 px também
# se lê melhor como película que o de 1 px. Só luma: grão colorido parece "digital".
GRAIN_SEED = 42
GRAIN_STEPS = (
    12  # a quantidade 1 vira força 12 do `noise` (desvio-padrão de uns 5 níveis de 255 depois da ampliação)
)
# Deslocamento máximo da textura em pixels. 7 mantém o salto entre quadros abaixo de 16 px, a busca de movimento
# padrão do x264, e a textura sobra 7 px de cada lado para o recorte.
GRAIN_SHIFT = 7


@dataclass(frozen=True)
class FinishContext:
    size: tuple[int, int]  # largura e altura do quadro
    fps: float
    duration: float

    @property
    def frames(self) -> int:
        return max(1, round(self.duration * self.fps))


EffectBuilder = Callable[[str, str, float, FinishContext], list[str]]
EFFECTS: dict[str, EffectBuilder] = {}  # nome do campo de ColorAdjust -> construtor, na ordem do grafo


def effect(name: str) -> Callable[[EffectBuilder], EffectBuilder]:
    """Registra o construtor de um efeito de acabamento."""

    def register(builder: EffectBuilder) -> EffectBuilder:
        EFFECTS[name] = builder
        return builder

    return register


def _inner(label: str) -> str:
    """Prefixo para os rótulos internos de um efeito, derivado do rótulo de saída (que é único no grafo)."""
    return label.strip("[]")


def _even(value: float) -> int:
    return max(2, int(value) // 2 * 2)


@effect("glow")
def glow(src: str, dst: str, amount: float, ctx: FinishContext) -> list[str]:
    """Brilho suave: as luzes são isoladas, borradas e somadas à imagem por `screen` (só na luma, para o halo
    não mudar a cor da cena)."""
    width, height = ctx.size
    small = f"{_even(width / GLOW_DOWNSCALE)}:{_even(height / GLOW_DOWNSCALE)}"
    sigma = GLOW_RADIUS * width / GLOW_DOWNSCALE
    t = _inner(dst)
    return [
        f"{src}split=2[{t}_base][{t}_src]",
        f"[{t}_src]lutyuv=y='clip((val-{GLOW_KNEE})*{GLOW_GAIN},0,255)',scale={small}:flags=bilinear,"
        f"gblur=sigma={sigma:.2f},scale={width}:{height}:flags=bicubic[{t}_halo]",
        f"[{t}_base][{t}_halo]blend=c0_mode=screen:c0_opacity={amount * GLOW_MAX_OPACITY:.3f}"
        f":c1_opacity=0:c2_opacity=0{dst}",
    ]


@effect("aberration")
def aberration(src: str, dst: str, amount: float, ctx: FinishContext) -> list[str]:
    """Aberração cromática: o vermelho vai para um lado e o azul para o outro, em RGB (o verde fica no lugar),
    com a borda esticada (`smear`) para não aparecer uma franja preta nem entrar a outra ponta do quadro."""
    shift = max(1, round(amount * ABERRATION_MAX_SHIFT * ctx.size[0]))
    return [f"{src}format=gbrp,rgbashift=rh=-{shift}:bh={shift}:edge=smear,format=yuv420p{dst}"]


def leak_cycle(ctx: FinishContext) -> int:
    """Quadros de uma passagem do vazamento: o trecho faz `round(duração / 4 s)` passagens (pelo menos uma), todas
    do mesmo tamanho, para a última acabar junto com o trecho."""
    passes = max(1, round(ctx.duration / LEAK_PERIOD))
    return max(2, math.ceil(ctx.frames / passes))


def leak_curves(amount: float, ctx: FinishContext) -> tuple[str, str]:
    """Expressões (do quadro `N`) da intensidade e da posição do feixe. Por fórmula, e não por tabela, porque uma
    tabela de um quadro por entrada de um trecho de 4 s estoura a linha de comando do Windows. A intensidade é um
    sino `sin^2` de inclinação zero nas pontas: a luz entra e sai sem degrau, e o corte para o próximo trecho nunca
    pega o vazamento aceso. A posição anda em linha reta, de fora da esquerda a fora da direita."""
    cycle = leak_cycle(ctx)
    progress = f"(mod(N,{cycle})/{cycle - 1})"
    start, end = LEAK_SPAN
    intensity = f"{number(amount * LEAK_PEAK)}*pow(sin(PI*{progress}),2)"
    position = f"({number(start)}+{number(end - start)}*{progress})"
    return intensity, position


@effect("light_leak")
def light_leak(src: str, dst: str, amount: float, ctx: FinishContext) -> list[str]:
    """Vazamento de luz: a luz gerada pelo DMaker (`filtergraph/lightleak.py`) sobreposta ao quadro."""
    intensity, position = leak_curves(amount, ctx)
    t = _inner(dst)
    lines = light_leak_source(f"[{t}_leak]", ctx.size, ctx.fps, LEAK_LOOK, intensity, position, ctx.frames)
    return [*lines, f"{src}[{t}_leak]overlay=format=yuv420{dst}"]


@effect("grain")
def grain(src: str, dst: str, amount: float, ctx: FinishContext) -> list[str]:
    """Granulação: a textura de ruído (luma) em torno do cinza médio, deslocada a cada quadro e somada à imagem
    por `grainmerge` (A + B - 128), que não mexe na cor."""
    width, height = ctx.size
    s = GRAIN_SHIFT
    strength = max(1, int(amount * GRAIN_STEPS + 0.5))
    full = f"{width + 2 * s}:{height + 2 * s}"  # a textura inteira, com sobra para o deslocamento
    half = f"{_even((width + 2 * s) / 2 + 1)}x{_even((height + 2 * s) / 2 + 1)}"  # onde o ruído nasce
    t = _inner(dst)
    # o cinza é fixado em 128 com `lutyuv` porque `color` converte o RGB 128 para a luma 126, e o `grainmerge`
    # clarearia ou escureceria a imagem inteira
    texture = (
        f"color=c=black:s={half}:r={ctx.fps:g}:d={2 / ctx.fps:.4f},format=yuv420p,"
        f"lutyuv=y=128:u=128:v=128,noise=c0s={strength}:allf=t:all_seed={GRAIN_SEED},"
        f"trim=end_frame=1,loop=loop=-1:size=1,scale={full}:flags=bilinear,"
        f"crop=w={width}:h={height}:x='{s}+{s}*sin(n*2.4)':y='{s}+{s}*sin(n*1.9+1)',"
        f"trim=end_frame={ctx.frames + 2},settb=AVTB,setpts=N/{ctx.fps:g}/TB[{t}_grain]"
    )
    return [texture, f"{src}[{t}_grain]blend=all_mode=grainmerge:shortest=1{dst}"]


def effect_amounts(color: ColorAdjust, look: ColorAdjust | None = None) -> dict[str, float]:
    """Quantidade de cada efeito que vale no trecho, na ordem do grafo. O valor que o trecho pediu vence o do
    look (o efeito não soma duas vezes); o que está em 0 nos dois fica de fora."""
    amounts: dict[str, float] = {}
    for name in EFFECTS:
        own = getattr(color, name)
        inherited = getattr(look, name) if look is not None else 0.0
        amount = own if own > 0 else inherited
        if amount > 0:
            amounts[name] = amount
    return amounts


def grade_chain(color: ColorAdjust, look: ColorAdjust | None = None) -> list[str]:
    """Filtros de cor: primeiro o ajuste do trecho, depois o do look. A vinheta que o trecho pediu vale no lugar
    da do look (duas vinhetas seguidas escureceriam o canto duas vezes)."""
    chain = color_chain(color)
    if look is not None:
        chain += color_chain(look.model_copy(update={"vignette": False}) if color.vignette else look)
    return chain


def post_video_lines(
    src: str,
    dst: str,
    color: ColorAdjust,
    look: ColorAdjust | None,
    fade_in: float,
    fade_out: float,
    duration: float,
    size: tuple[int, int] | None,
    fps: float,
    tag: str = "fx",
) -> list[str]:
    """Do quadro já reenquadrado até o `dst` do mezanino: cor, acabamento, fades e formato final.

    Sem look e sem efeito de acabamento é a mesma cadeia de sempre (um filtro atrás do outro), para um projeto sem
    look sair idêntico ao de antes. `tag` prefixa os rótulos internos, para dois acabamentos conviverem no grafo.
    """
    video_fades, _ = fade_chains(fade_in, fade_out, duration)
    tail = [*video_fades, "format=yuv420p", "setsar=1"]
    chain = grade_chain(color, look)
    amounts = effect_amounts(color, look)
    if not amounts:
        return [src + ",".join(chain + tail) + dst]
    if size is None:
        raise ValueError("acabamento visual precisa do tamanho do quadro")
    context = FinishContext(size, fps, duration)
    lines: list[str] = []
    current = src
    entry = [*chain, "format=yuv420p"]  # os efeitos trabalham em yuv420p (a luma e o croma separados)
    lines.append(current + ",".join(entry) + f"[{tag}_in]")
    current = f"[{tag}_in]"
    for name, amount in amounts.items():
        target = f"[{tag}_{name}]"
        lines += EFFECTS[name](current, target, amount, context)
        current = target
    lines.append(current + ",".join(tail) + dst)
    return lines
