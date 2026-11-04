"""O Auto Duck no pipeline: ler quando cada trilha-chave soa e planejar a curva de volume de cada trilha de fundo.

Fluxo (as funções puras estão em `domain/auto_duck.py` e `filtergraph/duck.py`; aqui só se mede e se decide):

1. **Medir a chave.** Uma passada do ffmpeg lê o nível RMS da trilha-chave em janelas de 20 ms e devolve TEXTO (uma
   linha por janela), nunca um arquivo de áudio. Duas formas, conforme onde a chave soa:
   - uma faixa externa (`A2`, `A3`...) vive no arquivo dela, no tempo do arquivo. Mede-se o arquivo inteiro uma vez
     (já com os efeitos dele e o volume que ele tem na mistura) e o trecho de cada clipe vai para a linha do tempo pela
     mesma conta que o mezanino e a vista usam (`track_window`), então o que se mede é o que se ouve;
   - as outras trilhas (`A1`, `NAR`, `VO`, `MUS`, `SFX`) são lidas da cópia que o grafo da mixagem tira de cada uma
     (`StemTaps`, a mesma do DMK-64), no tempo do projeto, antes de qualquer abaixamento. Só `A1` precisa dos mezaninos.
   O resultado fica em cache por hash do que entra na chave (o grafo e o arquivo de cada entrada), e não depende dos
   parâmetros da regra: mudar a quantidade, o limiar ou as rampas refaz só a conta, que é pura.
2. **Planejar a curva.** Os trechos acima do limiar, juntados pela pausa da regra, viram os pontos de ganho do fundo.
3. **Aplicar.** `filtergraph/audio.py` abaixa a música, a narração, a voz gravada, os efeitos sonoros e o `A1` na
   mixagem, e `filtergraph/mezzanine.py` abaixa a faixa externa dentro do clipe, só com o pedaço da curva que cai nele.

Uma regra para a música substitui o `music.ducking` antigo, que continua igual enquanto não há regra.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from .. import config
from ..domain.auto_duck import (
    AutoDuck,
    Point,
    Region,
    duck_points,
    external_index,
    is_external,
    key_regions,
    slice_points,
    sound_runs,
)
from ..domain.spec import ClipSegment, Project
from ..filtergraph.audio import StemTaps
from ..filtergraph.duck import DuckCurve
from ..media.ffmpeg import FFmpegCommand, filter_complex_file_args
from .audio_effects import track_audio_overrides
from .cache_key import cache_key
from .context import RenderContext
from .sources import Source, physical_source_names
from .track_slices import track_slice, track_window

DUCK_VERSION = "dk1"  # muda quando a medida da chave muda (invalida os níveis em cache)
# A janela do nível RMS: 20 ms, a 48 kHz. Curta o bastante para a descida começar a tempo da primeira palavra (a janela que
# a contém já conta como som) e longa o bastante para uma hora de fala dar uns 180 mil números, que cabem em texto.
LEVEL_SAMPLES = 960
LEVEL_RATE = 48000
LEVEL_WINDOW_SECONDS = LEVEL_SAMPLES / LEVEL_RATE
SILENT_DB = -120.0  # o nível que o astats imprime como `-inf`

_LEVEL_LINE = re.compile(
    r"lavfi\.astats\.Overall\.RMS_level=(-?inf|nan|-?[0-9.]+(?:e[-+]?\d+)?)", re.IGNORECASE
)


def level_filters(source: str, out: str) -> str:
    """Uma linha de grafo que lê o nível RMS de `source` em janelas de `LEVEL_SAMPLES` amostras e o imprime no log: o
    `astats` com `reset=1` mede cada quadro sozinho, e o `ametadata` escreve o número dele."""
    return (
        f"{source}asetnsamples=n={LEVEL_SAMPLES}:p=0,"
        # só o RMS do conjunto dos canais: o `astats` completo (entropia, cruzamentos por zero...) custa 20x mais
        "astats=metadata=1:reset=1:measure_perchannel=none:measure_overall=RMS_level,"
        f"ametadata=mode=print:key=lavfi.astats.Overall.RMS_level{out}"
    )


def parse_levels(report: str) -> np.ndarray:
    """Os níveis RMS (dBFS), um por janela, na ordem do arquivo. `-inf` (janela muda) vira `SILENT_DB`."""
    values = []
    for found in _LEVEL_LINE.finditer(report):
        number = float(found.group(1)) if found.group(1).lower() not in ("-inf", "nan") else SILENT_DB
        values.append(max(number, SILENT_DB))
    return np.asarray(values, dtype=np.float32)


@dataclass(frozen=True)
class PlannedDuck:
    """Uma regra planejada: onde a chave soa (segundos do projeto), a curva de ganho que ela impõe ao fundo e, quando ela
    não age, o motivo (a trilha não existe no projeto, a chave não soa nada...)."""

    rule: AutoDuck
    regions: tuple[Region, ...] = ()
    points: tuple[Point, ...] = ()
    note: str = ""


@dataclass
class DuckPlan:
    """As regras de `audio.ducks` já planejadas, na ordem da spec. Mora no contexto do render (`ctx.duck_plan`)."""

    rules: list[PlannedDuck] = field(default_factory=list)
    spans: list[tuple[float, float]] = field(
        default_factory=list
    )  # onde cada clipe cai na linha do tempo final
    track_origin: list[int] = field(
        default_factory=list
    )  # de que faixa externa da spec veio cada faixa física

    def curves(self) -> list[DuckCurve]:
        """As curvas das trilhas que a mixagem abaixa (`filtergraph/audio.py`): todas menos as faixas externas, que são
        abaixadas dentro do clipe."""
        return [
            DuckCurve(item.rule.background, item.points)
            for item in self.rules
            if item.points and not is_external(item.rule.background)
        ]

    def replaces_music_ducking(self) -> bool:
        """Se há regra para a música (mesmo sem trecho): o `sidechaincompress` antigo não roda junto com ela."""
        return any(item.rule.is_music_rule for item in self.rules)

    def physical_tracks(self, track_id: str) -> list[int]:
        """As posições, em `audio.tracks` do projeto físico, da faixa externa `track_id` (uma fonte com `parts` vira várias)."""
        original = external_index(track_id)
        return [j for j, origin in enumerate(self.track_origin) if origin == original]

    def track_curves(self, clip_index: int, track_index: int) -> tuple[tuple[Point, ...], ...]:
        """As curvas que abaixam a faixa externa física `track_index` dentro do clipe `clip_index`, já no tempo do clipe
        (segundos de fonte, antes da velocidade) e só com o pedaço que cai nele. Vazio quando nenhuma regra mexe nela ali:
        o clipe então não leva filtro nenhum e o hash dele é o de sempre."""
        if not self.rules or not 0 <= clip_index < len(self.spans):
            return ()
        original = self.track_origin[track_index] if track_index < len(self.track_origin) else track_index
        first, last = self.spans[clip_index]
        scale = self.speeds.get(clip_index, 1.0)
        curves = []
        for item in self.rules:
            if external_index(item.rule.background) == original and item.points:
                sliced = slice_points(item.points, first, last, scale)
                if sliced:
                    curves.append(tuple(sliced))
        return tuple(curves)

    speeds: dict[int, float] = field(
        default_factory=dict
    )  # a velocidade de cada clipe (segundos de fonte por segundo)


def spill_long_graph(command: FFmpegCommand, directory: Path, name: str) -> FFmpegCommand:
    """O mesmo comando com o grafo lido de um arquivo quando passa do limite da linha de comando do Windows. A curva do Auto
    Duck de um clipe longo pode ter centenas de pontos (uns 50 caracteres cada), e o mezanino e o pedaço da prévia levam o
    grafo na linha de comando. Um grafo curto, ou um comando sem grafo, volta como estava."""
    from .assembly import INLINE_GRAPH_LIMIT

    args = list(command.args)
    if "-filter_complex" not in args:
        return command
    position = args.index("-filter_complex")
    graph = args[position + 1]
    if len(graph) < INLINE_GRAPH_LIMIT:
        return command
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / name
    script.write_text(graph, encoding="utf-8")
    args[position : position + 2] = filter_complex_file_args(str(script))
    return replace(command, args=args)


def duck_key_part(curves: Sequence[Sequence[Point]]) -> list:
    """A parte da chave de cache de um pedaço (mezanino, pedaço da prévia) que muda quando a curva dele muda. Vazia sem
    curva: a chave de um projeto sem Auto Duck é a de sempre."""
    return [[list(point) for point in curve] for curve in curves]


# ---------- medir a chave ----------


def _levels_dir() -> Path:
    path = config.AUDIO_FX_DIR / "levels"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _stamp(path: Path) -> list | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return [str(path), stat.st_mtime_ns, stat.st_size]


def _input_stamps(args: Sequence[str]) -> list:
    """Data e tamanho de cada arquivo de entrada de um comando: trocar o conteúdo de um deles muda a chave."""
    return [
        _stamp(Path(args[i + 1]))
        for i, arg in enumerate(args[:-1])
        if arg == "-i" and Path(args[i + 1]).exists()
    ]


def _measure(ctx: RenderContext, args: list[str], identity: Sequence[object]) -> np.ndarray:
    """Roda a passada de nível e guarda o resultado em cache pela chave `identity` (o grafo e os arquivos de entrada)."""
    if ctx.options.dry_run:
        return np.zeros(0, dtype=np.float32)
    cache = _levels_dir() / f"{cache_key(DUCK_VERSION, *identity)}.npy"
    if cache.exists():
        return np.load(cache)
    levels = parse_levels(ctx.runner.capture(args, label="nível da trilha-chave do Auto Duck"))
    if len(levels):
        staging = cache.with_suffix(".tmp.npy")
        np.save(staging, levels)
        staging.replace(cache)
    return levels


def file_levels(ctx: RenderContext, path: Path, stream: int, volume: float) -> np.ndarray:
    """Os níveis RMS de um arquivo de uma faixa externa como ela soa na mistura (com o `volume` dela), no tempo do arquivo."""
    graph = ";".join(
        [
            f"[0:a:{stream}]aresample={LEVEL_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={volume:.6f},asetpts=PTS-STARTPTS[dk_in]",
            level_filters("[dk_in]", "[dk_out]"),
        ]
    )
    args = ["-i", str(path), "-filter_complex", graph, "-map", "[dk_out]", "-f", "null", "-"]
    return _measure(ctx, args, ["file", graph, _stamp(path)])


def tap_levels(
    ctx: RenderContext,
    key: str,
    prepared: list,
    transitions: list,
    music_path: Path | None,
    total: float,
    voiceovers: Sequence,
    pips: Sequence,
    sfx: Sequence,
    voice_files: Sequence,
) -> np.ndarray:
    """Os níveis RMS da trilha `key` no tempo do projeto, lidos da cópia que o grafo da mixagem tira dela antes de abaixar
    nada. O grafo leva só o que a chave pede: a música, a narração, as vozes ou os efeitos de cada vez, sobre um silêncio
    da duração do projeto; só `A1` precisa dos mezaninos."""
    from .assembly import audio_only_graph, graph_args

    taps = StemTaps(frozenset({key}))
    inputs, lines, aout = audio_only_graph(
        ctx,
        prepared if key == "A1" else [],
        transitions if key == "A1" else [],
        music_path if key == "MUS" else None,
        total,
        voiceovers if key == "NAR" else (),
        pips if key == "A1" else (),
        include_music=key == "MUS",
        sfx=sfx if key == "SFX" else (),
        voice_files=voice_files if key == "VO" else (),
        include_master=False,
        stems=taps,
        ducks=[],
    )
    lines.append(f"{aout}anullsink")  # a mistura inteira não interessa: só a cópia da chave
    lines.append(level_filters(taps.labels[key], "[dk_out]"))
    args = [*graph_args(ctx, inputs, lines, "duck_detect.txt"), "-map", "[dk_out]", "-f", "null", "-"]
    return _measure(ctx, args, ["tap", key, ";".join(lines), _input_stamps(inputs.args)])


# ---------- planejar ----------


def begin_ducks(
    ctx: RenderContext, spans: Sequence[tuple[float, float]], track_origin: Sequence[int] | None = None
) -> None:
    """Começa o plano do Auto Duck, ANTES de os mezaninos e os pedaços da prévia existirem: as regras cuja chave é uma faixa
    externa já podem ser planejadas (a chave se mede no arquivo dela), e são elas que a faixa externa de fundo precisa, porque
    é dentro do clipe que ela abaixa. As regras de chave de outro tipo ficam para `finish_ducks`, que precisa da mixagem.
    `spans` é onde cada clipe cai na linha do tempo final e `track_origin` diz de que faixa da spec veio cada faixa física."""
    ctx.duck_plan = None
    rules = ctx.project.audio.ducks
    if not rules:
        return
    origin = list(track_origin) if track_origin is not None else list(range(len(ctx.project.audio.tracks)))
    plan = DuckPlan(
        [PlannedDuck(rule) for rule in rules],
        list(spans),
        origin,
        {i: seg.speed for i, seg in enumerate(ctx.project.timeline) if isinstance(seg, ClipSegment)},
    )
    ctx.duck_plan = plan
    for position, item in enumerate(plan.rules):
        rule = item.rule
        missing = _missing(ctx, plan, rule, early=True)
        if missing:
            plan.rules[position] = PlannedDuck(rule, note=missing)
            ctx.warn(missing)
        elif is_external(rule.key):
            runs = _external_runs(ctx, plan, rule)
            plan.rules[position] = _planned(rule, runs)


def finish_ducks(
    ctx: RenderContext,
    prepared: list,
    transitions: list,
    music_path: Path | None,
    total: float,
    voiceovers: Sequence = (),
    pips: Sequence = (),
    sfx: Sequence = (),
    voice_files: Sequence = (),
) -> None:
    """Planeja as regras cuja chave é a música, a narração, a voz gravada, os efeitos ou o som dos clipes: lê a cópia que o
    grafo da mixagem tira de cada uma. Roda depois de todo o resto estar pronto, junto das medidas do master."""
    plan: DuckPlan | None = ctx.duck_plan
    if plan is None:
        return
    for position, item in enumerate(plan.rules):
        rule = item.rule
        if item.note or item.points or is_external(rule.key):
            continue
        missing = _missing(ctx, plan, rule, early=False, sfx=sfx)
        if missing:
            plan.rules[position] = PlannedDuck(rule, note=missing)
            ctx.warn(missing)
            continue
        levels = tap_levels(
            ctx, rule.key, prepared, transitions, music_path, total, voiceovers, pips, sfx, voice_files
        )
        plan.rules[position] = _planned(rule, sound_runs(levels, LEVEL_WINDOW_SECONDS, rule.threshold_db))


def _planned(rule: AutoDuck, runs: Sequence[Region]) -> PlannedDuck:
    regions = key_regions(runs, rule)
    return PlannedDuck(rule, tuple(regions), tuple(duck_points(regions, rule)))


def _missing(ctx: RenderContext, plan: DuckPlan, rule: AutoDuck, *, early: bool, sfx: Sequence = ()) -> str:
    """Por que a regra não age, ou vazio: a trilha dela não existe neste projeto (a regra fica na spec, mas não faz nada)."""
    for track_id in (rule.background, rule.key):
        absent = _absent(ctx, plan, track_id, early, sfx)
        if absent:
            return f"Auto Duck: {rule.background} sob {rule.key} não age: o projeto não tem {absent}."
    return ""


def _absent(ctx: RenderContext, plan: DuckPlan, track_id: str, early: bool, sfx: Sequence) -> str:
    audio = ctx.project.audio
    if track_id == "A1":
        return (
            ""
            if any(isinstance(seg, ClipSegment) for seg in ctx.project.timeline)
            else "trechos de vídeo (A1)"
        )
    if track_id == "MUS":
        return "" if audio.music is not None and audio.music.volume > 0 else "música (MUS)"
    if track_id == "NAR":
        return "" if audio.narration else "narração (NAR)"
    if track_id == "VO":
        return "" if audio.voiceover else "voz gravada (VO)"
    if track_id == "SFX":
        # os efeitos sonoros só se conhecem depois de nivelados; antes disso a regra vale
        return "" if early or sfx else "efeito sonoro (SFX)"
    return "" if plan.physical_tracks(track_id) else f"a faixa externa {track_id}"


# ---------- a chave é uma faixa externa ----------


def _external_runs(ctx: RenderContext, plan: DuckPlan, rule: AutoDuck) -> list[Region]:
    """Os trechos, na linha do tempo final, em que a faixa externa `rule.key` soa acima do limiar. Mede-se o arquivo de cada
    faixa física uma vez, no tempo dele, e cada clipe que o usa recorta o que ouve (com a velocidade e o atraso da faixa)."""
    overrides = track_audio_overrides(ctx)
    runs: list[Region] = []
    for track_index in plan.physical_tracks(rule.key):
        track = ctx.project.audio.tracks[track_index]
        source: Source | None = ctx.session.get(track.source)
        if source is None or source.path is None or source.info is None:
            continue
        override = overrides[track_index] if track_index < len(overrides) else None
        path, stream = (override, 0) if override is not None else (source.path, source.audio_stream)
        file_runs = sound_runs(
            file_levels(ctx, path, stream, track.volume), LEVEL_WINDOW_SECONDS, rule.threshold_db
        )
        if not file_runs:
            continue
        for index, segment in enumerate(ctx.project.timeline):
            if not isinstance(segment, ClipSegment) or not segment.source or index >= len(plan.spans):
                continue
            piece = track_slice(track, ctx.session[track.source], segment, override)
            window = (
                track_window(piece, source.info.duration, segment.speed, plan.spans[index]) if piece else None
            )
            if window is None:
                continue
            runs += _clip_runs(file_runs, window.start, window.end, window.file_in, segment.speed)
    return runs


def _clip_runs(
    file_runs: Sequence[Region], start: float, end: float, file_in: float, speed: float
) -> list[Region]:
    """Os trechos do arquivo que um clipe toca (de `file_in`, durante `end - start` segundos da linha do tempo, na
    velocidade `speed`), no tempo da linha do tempo final."""
    heard_until = file_in + (end - start) * speed
    mapped = []
    for first, last in file_runs:
        low, high = max(first, file_in), min(last, heard_until)
        if high > low:
            mapped.append((start + (low - file_in) / speed, start + (high - file_in) / speed))
    return mapped


# ---------- o que o mezanino e a mixagem pedem ----------


def track_duck_lookup(
    ctx: RenderContext, clip_index: int
) -> Callable[[int], tuple[tuple[Point, ...], ...]] | None:
    """Para `track_slices`: dada a posição da faixa externa, as curvas que a abaixam dentro do clipe `clip_index`. None sem
    Auto Duck no projeto (o caminho de sempre)."""
    plan: DuckPlan | None = ctx.duck_plan
    if plan is None or not any(is_external(item.rule.background) and item.points for item in plan.rules):
        return None
    return lambda track_index: plan.track_curves(clip_index, track_index)


def bus_curves(ctx: RenderContext) -> list[DuckCurve]:
    """As curvas que `filtergraph.audio.audio_graph` aplica às trilhas da mixagem (vazio sem Auto Duck)."""
    plan: DuckPlan | None = ctx.duck_plan
    return plan.curves() if plan else []


def plan_summary(plan: DuckPlan | None) -> list[dict]:
    """Um resumo de cada regra para a vista, o MCP e a CLI: a trilha de fundo, a chave, quantas regiões a chave tem e quantos
    segundos ela soa, ou o motivo de a regra não agir."""
    if plan is None:
        return []
    summary = []
    for item in plan.rules:
        summary.append(
            {
                **item.rule.model_dump(),
                "regions": len(item.regions),
                "key_seconds": round(sum(last - first for first, last in item.regions), 3),
                "note": item.note,
            }
        )
    return summary


def project_track_origin(project: Project) -> list[int]:
    """De que faixa externa da spec vem cada faixa do projeto físico (`expand_parts`): as de uma fonte com `parts` viram uma
    por arquivo, e as regras citam a faixa da spec."""
    origin: list[int] = []
    for index, track in enumerate(project.audio.tracks):
        origin += [index] * len(physical_source_names(project, track.source))
    return origin
