"""Audiograma no grafo de montagem: a onda ou as barras do áudio, desenhadas pelo próprio ffmpeg.

Cada estilo é um construtor registrado em `STYLES` (`@audiogram_style`); um estilo novo entra por ali, sem
tocar em `audiogram_graph`. O desenho nasce de uma cópia do áudio tirada da mixagem (`AudioTaps`), que nunca
volta para a saída, e sobe para o vídeo com `overlay` só entre `start` e `end`.

Duas decisões valem para todos os estilos:

- **O nível não depende da gravação.** A cópia recebe o mesmo ganho linear que o loudnorm aplica à saída
  (`normalization_gain_db`), então uma gravação baixa e uma alta enchem o desenho igual. Não há compressão
  nem `dynaudnorm`: eles levantariam o ruído das pausas, e a onda tem de ficar parada no silêncio.
- **O desenho não atrasa.** Tanto o `showwaves` quanto o `showfreqs` mostram o som alguns quadros depois de
  ele tocar (a janela de análise, o carimbo do quadro e a média no tempo). Como a renderização é offline e o
  áudio inteiro é conhecido, a cópia é adiantada desse atraso (`atrim`): o pico da fala e o pico do desenho
  caem no mesmo quadro. As constantes de atraso foram medidas com um pulso de áudio e estão presas por teste.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..domain.audiogram import BAR_COUNT, BARS_PER_HALF, RingLayout, bars_layout
from ..domain.presets import SafeZone
from ..domain.spec import AudiogramOverlay
from .audio import AudioTaps
from .common import LOUDNORM_TRUE_PEAK_DB, Inputs
from .overlays import overlay_center_position, overlay_position

# ---------- o que a animação mede ----------

# As barras olham 0 a 2 kHz: é onde a voz tem a energia (a fundamental e os dois primeiros formantes) e onde a
# música tem o grave e o corpo. Reamostrar para 4 kHz joga fora o resto antes da FFT, que fica barata.
BAND_RATE = 4000
# Janela da FFT: 64 ms (256 amostras a 4 kHz) resolve ~16 Hz por faixa, mais fino que as barras de ~83 Hz, e é
# curta o bastante para a barra acompanhar uma sílaba (~150 ms) em vez de borrá-la.
SPECTRUM_WINDOW = 256
# Sobreposição de 87,5%: uma janela nova a cada 8 ms, bem mais fina que o quadro, para o quadro pegar sempre
# a janela mais recente e o tempo do desenho não andar aos saltos do tamanho da janela.
SPECTRUM_OVERLAP = 0.875
# 128 faixas (metade da janela) e 256 linhas: a altura de cada coluna é a média de brilho dela, então 256 linhas
# dão 256 níveis de altura antes de qualquer média.
SPECTRUM_BINS = SPECTRUM_WINDOW // 2
SPECTRUM_ROWS = 256
# A altura das barras sai da raiz da amplitude (`ascale=sqrt`): a raiz comprime o grave, que domina a voz, o
# bastante para as barras agudas aparecerem, sem levantar o ruído de fundo como o dB faria.
BAR_GATE = 0.05  # abaixo disto (fração da altura) é ruído e a barra fica no repouso
BAR_BOOST = 6.0  # a fala normalizada (-14 LUFS) passa de metade da altura na maioria dos picos
# Média no tempo das alturas: 160 ms de janela triangular. Corta o tremor entre quadros (a altura de uma
# faixa oscila com a fase dos harmônicos) sem borrar sílabas; em tempo e não em quadros, para valer em
# qualquer fps.
SMOOTHING_SECONDS = 0.16
# A onda é a fundamental da voz (e o grave da música): abaixo de 500 Hz a linha fica lisa, sem a serrilha dos
# harmônicos agudos, que num quadro de 33 ms viraria um ruído de risquinhos.
WAVE_CUTOFF_HZ = 500
WAVE_LINE_RATIO = 0.03  # espessura da linha, fração da altura do desenho (no mínimo 3 px)
# o passa-baixa deixa só a fundamental da voz, uns 10 dB abaixo do pico: o ganho a leva a ocupar a altura
WAVE_BOOST_DB = 7.0

# ---------- atrasos medidos (ver `tests/test_audiogram_render.py`) ----------

# showwaves: o quadro de carimbo T mostra o som de [T - 2/fps, T - 1/fps]: meia janela mais o quadro de
# carimbo adiantado dá 1,5 quadro de atraso (medido a 24, 30 e 60 fps).
WAVE_LAG_FRAMES = 1.5
# showfreqs: um atraso fixo da janela de 64 ms (17,5 ms) mais 0,57 quadro (medidos a 24, 25, 30 e 60 fps).
SPECTRUM_LAG_SECONDS = 0.0175
SPECTRUM_LAG_FRAMES = 0.57


def smoothing_frames(fps: float) -> int:
    """Quadros da média no tempo: ímpar (a janela fica centrada) e pelo menos 3; 1 (sem média) se a janela é 0."""
    if SMOOTHING_SECONDS <= 0:
        return 1
    frames = round(SMOOTHING_SECONDS * fps)
    return max(3, frames if frames % 2 else frames + 1)


def normalization_gain_db(measured: Mapping[str, object] | None, target_lufs: float) -> float:
    """O ganho (dB) que o loudnorm linear aplica à saída: `alvo - loudness medida`, limitado para o pico
    verdadeiro não passar do teto do loudnorm. 0 sem medição (normalização desligada, simulação, silêncio)."""
    if not measured:
        return 0.0
    try:
        loudness = float(str(measured["input_i"]))
        peak = float(str(measured["input_tp"]))
    except (KeyError, TypeError, ValueError):
        return 0.0
    if (
        not (loudness == loudness and peak == peak)
        or abs(loudness) == float("inf")
        or abs(peak) == float("inf")
    ):
        return 0.0
    return min(target_lufs - loudness, LOUDNORM_TRUE_PEAK_DB - peak)


@dataclass
class ResolvedAudiogram:
    """Audiograma pronto para o grafo: caixa em px, cor, janela de tempo, áudio que segue e imagens estáticas."""

    overlay: AudiogramOverlay  # com a região já resolvida em x/y/width/height
    width: int
    height: int
    color: str  # #RRGGBB
    start: float
    end: float
    follow: str  # voice | mix, já resolvido (nunca auto)
    assets: dict[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class DrawContext:
    """O que um construtor de estilo recebe: a cópia do áudio, o ganho, o fps e o lugar das entradas."""

    lines: list[str]
    inputs: Inputs
    item: ResolvedAudiogram
    index: int  # posição do audiograma, para rótulos únicos
    source: str  # rótulo da cópia do áudio
    gain_db: float
    fps: float
    total: float

    def label(self, name: str) -> str:
        return f"[{name}{self.index}]"


StyleDrawer = Callable[[DrawContext], str]


@dataclass(frozen=True)
class AudiogramStyle:
    name: str
    lag: Callable[[float], float]  # fps -> segundos que o desenho atrasa em relação ao som
    draw: StyleDrawer  # empilha as linhas do grafo e devolve o rótulo da máscara (gray, branco = desenho)


STYLES: dict[str, AudiogramStyle] = {}


def audiogram_style(name: str, lag: Callable[[float], float]) -> Callable[[StyleDrawer], StyleDrawer]:
    """Registra o construtor de um estilo; o nome é o valor de `style` na spec."""

    def register(draw: StyleDrawer) -> StyleDrawer:
        STYLES[name] = AudiogramStyle(name, lag, draw)
        return draw

    return register


def _listening_copy(ctx: DrawContext, filters: Sequence[str], lag: float, name: str) -> str:
    """A cópia do áudio como o desenho a lê: ganho de normalização, mono, os filtros do estilo e o avanço
    que desfaz o atraso do desenho. Devolve o rótulo."""
    chain = [f"{ctx.source}volume={ctx.gain_db:.2f}dB", "pan=mono|c0=0.5*c0+0.5*c1", *filters]
    if lag > 0:
        chain += [f"atrim=start={lag:.4f}", "asetpts=PTS-STARTPTS"]
    label = ctx.label(name)
    ctx.lines.append(",".join(chain) + label)
    return label


def _spectrum_lag(fps: float) -> float:
    """Atraso do espectro: o do `showfreqs` mais o da média no tempo, que usa os quadros anteriores (uma janela
    de N quadros centrada atrasa (N - 1) / 2 deles)."""
    return SPECTRUM_LAG_SECONDS + SPECTRUM_LAG_FRAMES / fps + (smoothing_frames(fps) - 1) / 2 / fps


def _wave_lag(fps: float) -> float:
    return WAVE_LAG_FRAMES / fps


def _band_heights(ctx: DrawContext, rest_fraction: float) -> str:
    """Altura de cada uma das BARS_PER_HALF faixas de frequência, a cada quadro, como uma imagem de uma linha.

    O `showfreqs` desenha o espectro como barras cheias, e a média de brilho de cada coluna é a altura dela;
    reduzir a imagem para BARS_PER_HALF x 1 (`scale` por área) faz a média por faixa e por altura de uma vez.
    A média no tempo (`tmix`) acontece nessa imagem minúscula, então é barata e exata, sem borrar o topo
    das barras. O `lut` tira o ruído (`BAR_GATE`), dá o ganho e põe o piso de repouso."""
    frames = smoothing_frames(ctx.fps)
    listening = _listening_copy(ctx, [f"aresample={BAND_RATE}"], _spectrum_lag(ctx.fps), "vizband")
    weights = " ".join(str(min(i + 1, frames - i)) for i in range(frames))
    chain = [
        f"{listening}showfreqs=s={SPECTRUM_BINS}x{SPECTRUM_ROWS}:mode=bar:ascale=sqrt:fscale=lin"
        f":win_size={SPECTRUM_WINDOW}:win_func=hann:overlap={SPECTRUM_OVERLAP}:rate={ctx.fps:g}:colors=white",
        "format=gray",
        f"scale={BARS_PER_HALF}:1:flags=area",
        "format=gray16le",
    ]
    if frames > 1:
        chain.append(f"tmix=frames={frames}:weights='{weights}'")
    chain += [
        f"lut=y='clip((val/maxval-{BAR_GATE})*{BAR_BOOST:g},{rest_fraction:.4f},1)*maxval'",
        "format=gray",
    ]
    label = ctx.label("vizheights")
    ctx.lines.append(",".join(chain) + label)
    return label


def _mirrored_heights(ctx: DrawContext, heights: str, graves_in_middle: bool) -> str:
    """As alturas espelhadas na horizontal (BAR_COUNT colunas): graves no meio (barras) ou nas pontas, que no
    círculo se encontram no topo (círculo)."""
    plain, copy, flipped, out = (ctx.label(name) for name in ("vizhp", "vizhc", "vizhf", "vizmirror"))
    ctx.lines.append(f"{heights}split{plain}{copy}")
    ctx.lines.append(f"{copy}hflip{flipped}")
    left, right = (flipped, plain) if graves_in_middle else (plain, flipped)
    ctx.lines.append(f"{left}{right}hstack{out}")
    return out


@audiogram_style("wave", lag=_wave_lag)
def _draw_wave(ctx: DrawContext) -> str:
    """Linha de onda: o `showwaves` em modo `p2p` (uma linha ligando as amostras) sobre o grave da voz, engrossada
    por dilatação. Em silêncio a linha é reta; nada mais se mexe, e isso é a onda "parada"."""
    width, height = ctx.item.width, ctx.item.height
    line = max(3, round(height * WAVE_LINE_RATIO))
    listening = _listening_copy(
        ctx, [f"lowpass=f={WAVE_CUTOFF_HZ}", f"volume={WAVE_BOOST_DB:g}dB"], _wave_lag(ctx.fps), "vizwave"
    )
    thicken = ",".join(["dilation"] * (line // 2))
    chain = [
        f"{listening}showwaves=s={width}x{height}:mode=p2p:rate={ctx.fps:g}:scale=lin:draw=full:colors=white",
        "format=gray",
    ]
    if thicken:
        chain.append(thicken)
    chain.append("gblur=sigma=0.6:steps=1")
    out = ctx.label("vizmask")
    ctx.lines.append(",".join(chain) + out)
    return out


@audiogram_style("bars", lag=_spectrum_lag)
def _draw_bars(ctx: DrawContext) -> str:
    """Barras simétricas: as alturas das faixas espelhadas (graves no meio) comparadas, pixel a pixel, com a
    rampa estática (`visuals/audiogram.bars_ramp`), que já traz os vãos entre as barras. O `lut2` desenha o
    pixel quando a barra passa do valor da rampa e a diferença dá o antialias do topo; como a rampa cresce
    do centro para as bordas, a barra sai espelhada em cima e embaixo."""
    layout = bars_layout(ctx.item.width, ctx.item.height)
    heights = _band_heights(ctx, layout.rest_fraction)
    mirrored = _mirrored_heights(ctx, heights, graves_in_middle=True)
    expanded, ramp, out = ctx.label("vizexp"), ctx.label("vizramp"), ctx.label("vizmask")
    ctx.lines.append(f"{mirrored}scale={layout.width}:{layout.height}:flags=neighbor,format=gray{expanded}")
    ramp_input = ctx.inputs.add_looped_image(ctx.item.assets["ramp"], ctx.fps, ctx.total)
    ctx.lines.append(f"[{ramp_input}:v]format=gray{ramp}")
    ctx.lines.append(
        f"{expanded}{ramp}lut2=c0='clip((x-y)*{layout.half_height:g},0,255)':shortest=1,format=gray{out}"
    )
    return out


@audiogram_style("circle", lag=_spectrum_lag)
def _draw_circle(ctx: DrawContext) -> str:
    """Barras em volta de um círculo. O `remap` espalha a imagem de alturas (uma por barra) por um mapa polar
    (`visuals/audiogram.ring_assets`): cada pixel recebe a altura da barra que passa por ali. Aí o `lut2`
    compara essa altura com o raio (a rampa radial), como nas barras retas, e o anel (vãos e borda interna,
    com antialias) multiplica o resultado, porque o `remap` copia pixels em vez de misturá-los."""
    ring = RingLayout(ctx.item.width, ctx.item.overlay.inner_radius)
    heights = _band_heights(ctx, ring.rest_fraction)
    mirrored = _mirrored_heights(ctx, heights, graves_in_middle=False)
    field_in, xmap_a, xmap_b = ctx.label("vizfieldin"), ctx.label("vizxa"), ctx.label("vizxb")
    field_out, radial, ring_label = ctx.label("vizfield"), ctx.label("vizradial"), ctx.label("vizring")
    ring_mask, out = ctx.label("vizring0"), ctx.label("vizmask")
    # uma imagem BAR_COUNT x BAR_COUNT de linhas iguais: o mesmo mapa serve de coordenada x e y do remap
    ctx.lines.append(f"{mirrored}scale={BAR_COUNT}:{BAR_COUNT}:flags=neighbor,format=gray16le{field_in}")
    xmap = ctx.inputs.add_looped_image(ctx.item.assets["xmap"], ctx.fps, ctx.total)
    ctx.lines.append(f"[{xmap}:v]format=gray16le,split{xmap_a}{xmap_b}")
    ctx.lines.append(f"{field_in}{xmap_a}{xmap_b}remap,format=gray{field_out}")
    radial_input = ctx.inputs.add_looped_image(ctx.item.assets["radial"], ctx.fps, ctx.total)
    ctx.lines.append(f"[{radial_input}:v]format=gray{radial}")
    ctx.lines.append(f"{field_out}{radial}lut2=c0='clip((x-y)*{ring.span:g},0,255)':shortest=1{ring_mask}")
    cover_input = ctx.inputs.add_looped_image(ctx.item.assets["ring"], ctx.fps, ctx.total)
    ctx.lines.append(f"[{cover_input}:v]format=gray{ring_label}")
    ctx.lines.append(f"{ring_mask}{ring_label}blend=all_mode=multiply:shortest=1,format=gray{out}")
    return out


def _colorize(mask: str, color: str, out: str) -> str:
    """Pinta a máscara com a cor: R, G e B ficam constantes e a luminância da máscara vira o alfa. Um filtro só,
    sem fonte de cor (que seria infinita e brigaria com o fim do vídeo)."""
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return (
        f"{mask}format=rgba,colorchannelmixer=rr=0:rg=0:rb=0:ra={r:.4f}:gr=0:gg=0:gb=0:ga={g:.4f}"
        f":br=0:bg=0:bb=0:ba={b:.4f}:ar=1:ag=0:ab=0:aa=0{out}"
    )


def audiogram_graph(
    lines: list[str],
    inputs: Inputs,
    cur_v: str,
    items: Sequence[ResolvedAudiogram],
    taps: AudioTaps,
    gain_db: float,
    width: int,
    height: int,
    fps: float,
    total: float,
    scale: float,
    safe: SafeZone,
) -> str:
    """Um desenho por audiograma, sobreposto a `cur_v` entre `start` e `end`; devolve o rótulo final do vídeo.
    `taps` traz as cópias do áudio (preenchidas por `audio_graph`); vários audiogramas que seguem o mesmo
    áudio dividem a cópia com `asplit`."""
    users: dict[str, list[int]] = {}
    for index, item in enumerate(items):
        users.setdefault(item.follow, []).append(index)
    sources: dict[int, str] = {}
    for follow, indices in users.items():
        tap = taps.labels[follow]
        if len(indices) == 1:
            sources[indices[0]] = tap
            continue
        names = [f"[a_viz_{follow}{i}]" for i in indices]
        lines.append(f"{tap}asplit={len(indices)}{''.join(names)}")
        sources.update(dict(zip(indices, names, strict=True)))

    for index, item in enumerate(items):
        style = STYLES[item.overlay.style]
        ctx = DrawContext(lines, inputs, item, index, sources[index], gain_db, fps, total)
        mask = style.draw(ctx)
        layer = f"[vizlayer{index}]"
        lines.append(_colorize(mask, item.color, layer))
        ov = item.overlay
        if ov.x is not None and ov.y is not None:
            x, y = overlay_center_position(ov.x, ov.y, width, height)
        else:
            x, y = overlay_position(
                ov.position or "center",
                width,
                height,
                ov.margin * scale,
                safe if ov.safe_zone else SafeZone(),
            )
        out = f"[viza{index}]"
        lines.append(
            f"{cur_v}{layer}overlay=x={x}:y={y}:format=auto:enable='between(t,{item.start:.3f},{item.end:.3f})'{out}"
        )
        cur_v = out
    return cur_v
