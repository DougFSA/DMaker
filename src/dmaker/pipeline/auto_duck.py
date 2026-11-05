"""O Auto Duck no pipeline: ler quando cada trilha-chave soa e planejar a curva de volume de cada trilha de fundo.

Fluxo (as funções puras estão em `domain/auto_duck.py` e `filtergraph/duck.py`; aqui só se mede e se decide):

1. **Medir a chave.** Uma passada do ffmpeg lê o nível RMS da trilha-chave em janelas de 20 ms e devolve TEXTO (uma
   linha por janela), nunca um arquivo de áudio. Três formas, conforme onde a chave soa:
   - uma faixa externa (`A2`, `A3`...) vive no arquivo dela, no tempo do arquivo. Mede-se o arquivo inteiro uma vez
     (já com os efeitos dele e o volume que ele tem na mistura) e o trecho de cada clipe vai para a linha do tempo pela
     mesma conta que o mezanino e a vista usam (`track_window`), então o que se mede é o que se ouve;
   - `A1` é o som dos PRÓPRIOS trechos: a câmera de cada clipe como o mezanino a recebe (com os efeitos do clipe e o
     isolamento), com o volume dele, sem as faixas externas e sem os PiPs. Mede-se o arquivo de cada câmera uma vez
     e o trecho de cada clipe vai para a linha do tempo pela mesma conta da faixa externa (`camera_runs`);
   - as outras trilhas (`NAR`, `VO`, `MUS`, `SFX`) são lidas da cópia que o grafo da mixagem tira de cada uma
     (`StemTaps`, a mesma do DMK-64), no tempo do projeto, antes de qualquer abaixamento. Não precisam dos mezaninos,
     então servem a uma faixa externa de fundo, que abaixa DENTRO do mezanino.
   O resultado fica em cache por hash do que entra na chave (o grafo e o arquivo de cada entrada), e não depende dos
   parâmetros da regra: mudar a quantidade, o limiar ou as rampas refaz só a conta, que é pura.
2. **Planejar a curva.** Os trechos acima do limiar, juntados pela pausa da regra, viram os pontos de ganho do fundo.
   `begin_ducks` planeja, ANTES dos mezaninos, toda regra cuja chave não precisa deles (`AutoDuck.measured_early`); o
   `finish_ducks` planeja o resto, com a mixagem pronta. As duas são chamadas pelo render, pela prévia e pelo render só
   de áudio, então a decisão é uma só.
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
from ..domain.audio_shift import shifted_window
from ..domain.auto_duck import (
    AutoDuck,
    Point,
    Region,
    camera_runs,
    clip_runs,
    duck_points,
    external_index,
    is_external,
    key_regions,
    slice_points,
    sound_runs,
)
from ..domain.spec import ClipSegment, Project
from ..domain.timeline import segment_duration
from ..filtergraph.audio import StemTaps
from ..filtergraph.duck import DuckCurve
from ..filtergraph.mezzanine import uses_camera_audio
from ..media.ffmpeg import FFmpegCommand, filter_complex_file_args
from .audio_effects import clip_camera_audio, track_audio_overrides
from .cache_key import cache_key
from .context import RenderContext
from .sfx import SfxTrack, unleveled_effects
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


@dataclass(frozen=True)
class CameraInput:
    """De onde sai o som da câmera de um clipe, como o mezanino o recebe: o arquivo (o da fonte, o isolado ou o já
    processado pelos efeitos do clipe), a faixa de áudio dele, o ponto em que o clipe começa a ouvir e o silêncio que o
    antecede."""

    path: Path
    stream: int
    volume: float
    file_in: float
    lead: float


@dataclass(frozen=True)
class DuckInputs:
    """O que o plano precisa saber ANTES dos mezaninos: onde cada clipe cai na linha do tempo e de onde vem o seu som, a
    duração estimada do projeto e o que a narração, as vozes gravadas e a música já têm pronto (nada disso depende dos
    mezaninos). É o que o render, a prévia e o render só de áudio entregam ao `begin_ducks`."""

    spans: Sequence[tuple[float, float]]
    sources: Sequence[Source]
    total: float
    track_origin: Sequence[int] | None = None
    voiceovers: Sequence = ()
    voice_files: Sequence = ()
    music_path: Path | None = None


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
    levels: dict[str, np.ndarray] = field(
        default_factory=dict
    )  # as medidas já feitas neste render, por identidade: o mesmo arquivo nunca passa duas vezes pelo ffmpeg
    cameras: dict[int, CameraInput | None] = field(
        default_factory=dict
    )  # o som da câmera de cada clipe, resolvido uma vez para todas as regras de chave A1

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
    """Roda a passada de nível e guarda o resultado em cache pela chave `identity` (o grafo e os arquivos de entrada), no
    disco e na memória do plano: dois clipes que usam o mesmo arquivo não o medem duas vezes."""
    if ctx.options.dry_run:
        return np.zeros(0, dtype=np.float32)
    key = cache_key(DUCK_VERSION, *identity)
    plan: DuckPlan | None = ctx.duck_plan
    if plan is not None and key in plan.levels:
        return plan.levels[key]
    cache = _levels_dir() / f"{key}.npy"
    if cache.exists():
        levels = np.load(cache)
    else:
        levels = parse_levels(ctx.runner.capture(args, label="nível da trilha-chave do Auto Duck"))
        if len(levels):
            staging = cache.with_suffix(".tmp.npy")
            np.save(staging, levels)
            staging.replace(cache)
    if plan is not None:
        plan.levels[key] = levels
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
    music_path: Path | None,
    total: float,
    voiceovers: Sequence,
    sfx: Sequence,
    voice_files: Sequence,
) -> np.ndarray:
    """Os níveis RMS da trilha `key` (`MUS`, `NAR`, `VO` ou `SFX`) no tempo do projeto, lidos da cópia que o grafo da
    mixagem tira dela antes de abaixar nada. O grafo leva só o que a chave pede, sobre um silêncio da duração do projeto:
    não usa os mezaninos, então vale antes deles."""
    from .assembly import audio_only_graph, graph_args

    taps = StemTaps(frozenset({key}))
    inputs, lines, aout = audio_only_graph(
        ctx,
        [],
        [],
        music_path if key == "MUS" else None,
        total,
        voiceovers if key == "NAR" else (),
        (),
        include_music=key == "MUS",
        sfx=sfx if key == "SFX" else (),
        voice_files=voice_files if key == "VO" else (),
        include_master=False,
        stems=taps,
        ducks=[],
    )
    if (
        key not in taps.labels
    ):  # a trilha existe na spec mas nada dela toca ainda (a narração da prévia ainda não foi falada)
        return np.zeros(0, dtype=np.float32)
    lines.append(f"{aout}anullsink")  # a mistura inteira não interessa: só a cópia da chave
    lines.append(level_filters(taps.labels[key], "[dk_out]"))
    args = [*graph_args(ctx, inputs, lines, "duck_detect.txt"), "-map", "[dk_out]", "-f", "null", "-"]
    return _measure(ctx, args, ["tap", key, ";".join(lines), _input_stamps(inputs.args)])


# ---------- planejar ----------


def begin_ducks(ctx: RenderContext, inputs: DuckInputs) -> None:
    """Começa o plano do Auto Duck, ANTES de os mezaninos e os pedaços da prévia existirem: toda regra cuja chave não
    precisa da mixagem pronta (`AutoDuck.measured_early`) já pode ser planejada. É o caso da chave `A1` (só a câmera, lida
    do arquivo de cada clipe), da faixa externa (lida do arquivo dela) e de `MUS`, `NAR`, `VO` e `SFX` sob uma faixa externa
    de fundo, que abaixa dentro do clipe e por isso precisa da curva antes de o mezanino existir. As demais ficam para o
    `finish_ducks`. `inputs.spans` é onde cada clipe cai na linha do tempo final e `inputs.track_origin` diz de que faixa da
    spec veio cada faixa física."""
    ctx.duck_plan = None
    rules = ctx.project.audio.ducks
    if not rules:
        return
    origin = (
        list(inputs.track_origin)
        if inputs.track_origin is not None
        else list(range(len(ctx.project.audio.tracks)))
    )
    plan = DuckPlan(
        [PlannedDuck(rule) for rule in rules],
        list(inputs.spans),
        origin,
        speeds={i: seg.speed for i, seg in enumerate(ctx.project.timeline) if isinstance(seg, ClipSegment)},
    )
    ctx.duck_plan = plan
    sfx: list[SfxTrack] | None = None
    for position, item in enumerate(plan.rules):
        rule = item.rule
        missing = _missing(ctx, plan, rule)
        if not missing and rule.key == "SFX" and rule.measured_early:
            # os efeitos só se nivelam contra a voz depois dos mezaninos (e a voz precisa deles): aqui valem com o volume da
            # spec, o nível que teriam sem voz medida
            sfx = unleveled_effects(ctx, inputs.spans) if sfx is None else sfx
            missing = _missing(ctx, plan, rule, sfx=sfx)
        if missing:
            plan.rules[position] = PlannedDuck(rule, note=missing)
            ctx.warn(missing)
        elif rule.measured_early:
            plan.rules[position] = _planned(rule, _early_runs(ctx, plan, rule, inputs, sfx or ()))


def finish_ducks(
    ctx: RenderContext,
    music_path: Path | None,
    total: float,
    voiceovers: Sequence = (),
    sfx: Sequence = (),
    voice_files: Sequence = (),
) -> None:
    """Planeja as regras que sobraram: as de chave `MUS`, `NAR`, `VO` ou `SFX` sobre um fundo que não é faixa externa. Lê a
    cópia que o grafo da mixagem tira de cada uma, com os efeitos sonoros já nivelados contra a voz. Roda depois de todo o
    resto estar pronto, junto das medidas do master."""
    plan: DuckPlan | None = ctx.duck_plan
    if plan is None:
        return
    for position, item in enumerate(plan.rules):
        rule = item.rule
        if item.note or item.points or rule.measured_early:
            continue
        missing = _missing(ctx, plan, rule, sfx=sfx)
        if missing:
            plan.rules[position] = PlannedDuck(rule, note=missing)
            ctx.warn(missing)
            continue
        levels = tap_levels(ctx, rule.key, music_path, total, voiceovers, sfx, voice_files)
        plan.rules[position] = _planned(rule, sound_runs(levels, LEVEL_WINDOW_SECONDS, rule.threshold_db))


def _planned(rule: AutoDuck, runs: Sequence[Region]) -> PlannedDuck:
    regions = key_regions(runs, rule)
    return PlannedDuck(rule, tuple(regions), tuple(duck_points(regions, rule)))


def _early_runs(
    ctx: RenderContext, plan: DuckPlan, rule: AutoDuck, inputs: DuckInputs, sfx: Sequence
) -> list[Region]:
    """Os trechos em que a chave de uma regra planejada antes dos mezaninos soa acima do limiar."""
    if is_external(rule.key):
        return _external_runs(ctx, plan, rule)
    if rule.key == "A1":
        return _camera_key_runs(ctx, plan, rule, inputs)
    levels = tap_levels(
        ctx, rule.key, inputs.music_path, inputs.total, inputs.voiceovers, sfx, inputs.voice_files
    )
    return sound_runs(levels, LEVEL_WINDOW_SECONDS, rule.threshold_db)


def _missing(ctx: RenderContext, plan: DuckPlan, rule: AutoDuck, *, sfx: Sequence | None = None) -> str:
    """Por que a regra não age, ou vazio: a trilha dela não existe neste projeto (a regra fica na spec, mas não faz nada).
    `sfx` é None enquanto os efeitos sonoros não são conhecidos (a regra então vale)."""
    for track_id in (rule.background, rule.key):
        absent = _absent(ctx, plan, track_id, sfx)
        if absent:
            return f"Auto Duck: {rule.background} sob {rule.key} não age: o projeto não tem {absent}."
    return ""


def _absent(ctx: RenderContext, plan: DuckPlan, track_id: str, sfx: Sequence | None) -> str:
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
        return "" if sfx is None or sfx else "efeito sonoro (SFX)"
    return "" if plan.physical_tracks(track_id) else f"a faixa externa {track_id}"


# ---------- a chave é a câmera dos clipes (A1) ----------


def camera_input(
    ctx: RenderContext, plan: DuckPlan, index: int, segment: ClipSegment, source: Source, span_length: float
) -> CameraInput | None:
    """De onde sai o som da câmera do clipe `index`, pela mesma receita do mezanino: o isolamento vocal e os efeitos do
    clipe (`clip_camera_audio`) valem, e o som deslocado (`audio_offset`) começa na janela dele. None quando o clipe não
    tem câmera que soe (mudo, volume zero, sem áudio, ou o A1 desligado na interface). O volume é o do clipe vezes o ganho da
    voz do projeto, que é o que sobra do A1 antes da mistura com o resto."""
    from .segments import isolate_camera_audio

    if index in plan.cameras:
        return plan.cameras[index]
    audio = ctx.project.audio
    result: CameraInput | None = None
    if (
        not audio.mute_clips
        and source.path is not None
        and source.info is not None
        and source.path.exists()
        and uses_camera_audio(segment, source.info)
    ):
        in_point = source.in_point(segment.start) if segment.source else segment.start
        isolated = isolate_camera_audio(index, segment, source, in_point, span_length, ctx)
        if isolated is not None:
            isolated.isolate()  # separa a voz (ou o fundo) se ainda não está em cache: a medida lê o arquivo isolado
        length = max(span_length * segment.speed, 0.01)
        processed = clip_camera_audio(
            ctx, segment, source, in_point, length, isolated.path if isolated else None
        )
        volume = segment.volume * audio.voice_gain
        if processed is not None:  # o silêncio inicial já vem dentro do arquivo processado
            result = CameraInput(processed, 0, volume, 0.0, 0.0)
        elif isolated is not None:
            result = CameraInput(isolated.path, 0, volume, 0.0, isolated.lead)
        elif segment.audio_offset:
            window = shifted_window(in_point, segment.speed, segment.audio_offset)
            result = CameraInput(source.path, source.audio_stream, volume, window.read_from, window.lead)
        else:
            result = CameraInput(source.path, source.audio_stream, volume, max(in_point, 0.0), 0.0)
    plan.cameras[index] = result
    return result


def _camera_key_runs(ctx: RenderContext, plan: DuckPlan, rule: AutoDuck, inputs: DuckInputs) -> list[Region]:
    """Os trechos, na linha do tempo final, em que a câmera dos clipes soa acima do limiar: só o som dos próprios trechos,
    sem as faixas externas que o mezanino soma a ele e sem os PiPs. Mede-se o arquivo de cada câmera uma vez (o mesmo
    arquivo, faixa e volume em vários clipes é uma passada só) e cada clipe recorta o que ouve."""
    if ctx.options.dry_run:
        return []
    runs: list[Region] = []
    for index, segment in enumerate(ctx.project.timeline):
        if not isinstance(segment, ClipSegment) or index >= len(plan.spans) or index >= len(inputs.sources):
            continue
        source = inputs.sources[index]
        if source.info is None:
            continue
        length = segment_duration(segment, source.info, source.offset)
        heard = camera_input(ctx, plan, index, segment, source, length)
        if heard is None:
            continue
        file_runs = sound_runs(
            file_levels(ctx, heard.path, heard.stream, heard.volume),
            LEVEL_WINDOW_SECONDS,
            rule.threshold_db,
        )
        runs += camera_runs(file_runs, plan.spans[index], segment.speed, heard.file_in, heard.lead)
    return runs


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
            runs += clip_runs(file_runs, window.start, window.end, window.file_in, segment.speed)
    return runs


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
