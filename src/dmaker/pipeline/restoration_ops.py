"""As operações de limpeza e reparo do `edit_project`: o perfil de ruído e o Truncar Silêncio.

São três operações, e nenhuma é um efeito da cadeia (`domain/audio_effects/restoration.py` tem os quatro efeitos):

- `noise_profile_set` e `noise_profile_remove` guardam e apagam um trecho de ruído com nome em `audio.noise_profiles`,
  pelo `edit_project`, para entrarem no histórico (desfazer e refazer);
- `audio_truncate_silence` encurta as pausas de um item. Não é um efeito porque muda a duração do que toca e, no clipe,
  tem que mexer na imagem junto (um efeito só enxerga o som). Por isso fica ao lado do Cortar: no clipe corta imagem e som
  pelo mesmo plano do corte automático e devolve o mapa de tempo dos marcadores; na voz gravada é um `cut` por silêncio.

Cada operação lê o pedido, acha o item (`audio_targets`), traduz o tempo da linha do tempo (que aceita `marker:<texto>`) e
chama a função pura. O som é lido pelo `SampleReader` que a edição recebe (o ffmpeg, ou amostras de teste). Entram em
`EDIT_OPERATIONS` por `RESTORATION_OPERATIONS`, sem tocar o despacho de `pipeline.edits`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..domain.audio_edits import add_effects, shift_later_voiceovers
from ..domain.audio_targets import AudioTarget, parse_target
from ..domain.edits import EditError, cut_clip_ranges
from ..domain.noise_profile_edits import check_profile_name, remove_noise_profile, set_noise_profile
from ..domain.spec import Project
from ..domain.time_map import TimeMap
from ..media.spectral import MIN_PROFILE_SECONDS
from ..voice.cut_plan import DEFAULT_FRAME_GRID
from ..voice.silence import MODES, find_silences, plan_truncation, removed_seconds
from .audio_edit_ops import _interval, _required, _target
from .edit_outcome import EditOutcome
from .layout import OriginAggregate
from .noise_profiles import TargetAudio, locate_target_audio, quietest_item_window
from .sample_reader import SampleReader

# O som é lido em mono a 16 kHz para achar silêncio: a energia de um quadro de 10 ms não pede mais, e a decodificação de
# uma hora de gravação fica em 230 MB
DETECTION_RATE = 16000
# Os padrões e as faixas do Audacity (Truncate Silence): limiar -20 dB (de -80 a -20), duração mínima e "truncar para"
# 0,5 s, e a compressão em porcentagem do que passa da duração mínima
DEFAULT_THRESHOLD_DB = -20.0
DEFAULT_MIN_DURATION = 0.5
DEFAULT_TRUNCATE_TO = 0.5
DEFAULT_COMPRESS_PERCENT = 50.0
# O fade de áudio de cada pedaço do clipe cortado: o mesmo do corte automático (10 ms), que zera o som na emenda
CUT_FADE_SECONDS = 0.01


def _reader(layout: OriginAggregate) -> SampleReader:
    if layout.reader is None:
        raise EditError("esta operação precisa ler o áudio do projeto e não há leitor de amostras na edição")
    return layout.reader


# ---------- perfil de ruído ----------


def noise_window(
    project: Project, op: dict, layout: OriginAggregate
) -> tuple[AudioTarget, TargetAudio, float, float]:
    """O trecho só de ruído que `op` pede, em tempo do item: o item (`target`), o arquivo dele e o início e o fim. Com
    `start`/`end` (ou `region`) é o que foi marcado; sem eles, o trecho mais quieto do item. É o que o perfil de ruído e o
    Analisar ruído do Noise Gate têm em comum."""
    target = _target(project, op, layout)
    session = layout.physical.session if layout.physical else {}
    source = locate_target_audio(project, session, target.path)
    if any(op.get(key) is not None for key in ("start", "end", "region")):
        start, end = _interval(project, op)
        first, last = target.single_interval(start, end)
    else:
        first, last = quietest_item_window(_reader(layout), source, target.length)
    if last - first < MIN_PROFILE_SECONDS - 1e-9:
        raise EditError(
            f"o trecho de ruído tem {last - first:.3f} s; use pelo menos {MIN_PROFILE_SECONDS:.1f} s só de ruído "
            "(sem fala) para o perfil ter o que medir"
        )
    return target, source, first, last


def _op_noise_profile_set(project: Project, op: dict, layout: OriginAggregate) -> Project:
    name = check_profile_name(op.get("name"))
    target, _, first, last = noise_window(project, op, layout)
    return set_noise_profile(project, name, target.path, first, last)


def _op_noise_profile_remove(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return remove_noise_profile(project, str(_required(op, "name")))


# ---------- Truncar Silêncio ----------


@dataclass(frozen=True)
class TruncateOptions:
    threshold_db: float
    min_duration: float
    mode: str
    truncate_to: float
    percent: float


def _options(op: dict) -> TruncateOptions:
    """Os parâmetros do Audacity, com os padrões e as faixas dele; fora da faixa é erro que diz a faixa."""

    def number(name: str, default: float, low: float, high: float, unit: str) -> float:
        value = op.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
            raise EditError(f"`{name}` precisa ser um número de {low:g} a {high:g}{unit} (recebi {value!r})")
        return float(value)

    mode = op.get("mode", "truncate")
    if mode not in MODES:
        raise EditError(f"`mode` desconhecido: {mode!r}. Use um de: {', '.join(MODES)}")
    return TruncateOptions(
        number("threshold_db", DEFAULT_THRESHOLD_DB, -80.0, -20.0, " dB"),
        number("min_duration", DEFAULT_MIN_DURATION, 0.001, 10000.0, " s"),
        mode,
        number("truncate_to", DEFAULT_TRUNCATE_TO, 0.0, 10000.0, " s"),
        number("compress_percent", DEFAULT_COMPRESS_PERCENT, 0.0, 100.0, " %"),
    )


def _truncatable(path: str) -> None:
    """Recusa, com o motivo, o item que não encolhe. Olha só o caminho (`timeline.N`...), antes de achar o item, porque a
    faixa externa que nenhum clipe usa nem chega a ter janelas."""
    kind, _ = parse_target(path)
    refusals = {
        "pip": "o PiP tem a duração presa à imagem: trunque o silêncio do clipe de origem",
        "narration": "a narração é sintetizada com as pausas que o texto pede: ajuste o texto ou o ritmo dela",
        "track": "a faixa externa segue a sessão e o que toca é a soma dos itens: trunque o clipe",
        "master": "a mistura inteira não se encurta por aqui: trunque o clipe ou a voz gravada",
        "music": "a música não tem pausas de fala para truncar",
    }
    if kind in refusals:
        raise EditError(f"{path}: não dá para truncar silêncio, {refusals[kind]}")


def _op_truncate_silence(project: Project, op: dict, layout: OriginAggregate) -> EditOutcome:
    _truncatable(str(_required(op, "target")))
    target = _target(project, op, layout)
    target.require_intervals()
    options = _options(op)
    session = layout.physical.session if layout.physical else {}
    source = locate_target_audio(project, session, target.path)
    if target.length is None:
        raise EditError(f"{target.path}: o arquivo de áudio não foi encontrado, não dá para medir o silêncio")
    if any(op.get(key) is not None for key in ("start", "end", "region")):
        first, last = target.single_interval(*_interval(project, op))
    else:
        first, last = 0.0, target.length
    samples = _reader(layout).read(source.slice(first, last), rate=DETECTION_RATE, channels=1)
    if len(samples) == 0:
        raise EditError(f"{target.path}: não consegui ler o áudio para medir o silêncio")
    mono = samples[:, 0]
    silences = find_silences(mono, DETECTION_RATE, options.threshold_db, options.min_duration)
    grid = DEFAULT_FRAME_GRID if target.kind == "clip" else None
    removed = plan_truncation(
        mono,
        DETECTION_RATE,
        silences,
        options.mode,  # type: ignore[arg-type]
        options.min_duration,
        options.truncate_to,
        options.percent,
        # a grade de quadros vale em segundos de linha do tempo; no clipe acelerado o corte é em segundos do item. O que
        # fica antes do primeiro corte começa no começo do clipe, `first` segundos antes do trecho que se mediu
        frame_grid=None if grid is None else grid * _clip_speed(project, target),
        grid_origin=first,
    )
    if not removed:
        raise EditError(
            f"{target.path}: nenhum silêncio de pelo menos {options.min_duration:g} s abaixo de "
            f"{options.threshold_db:g} dB para truncar. Suba o limiar ou baixe a duração mínima"
        )
    item_cuts = [(round(first + a, 6), round(first + b, 6)) for a, b in removed]
    note = (
        f"{len(item_cuts)} silêncio(s) truncado(s) em {target.path}, "
        f"{removed_seconds(item_cuts):.2f} s a menos de {target.length:.2f} s"
    )
    if target.kind == "clip":
        return _truncate_clip(project, layout, target, item_cuts, note)
    return _truncate_voiceover(project, target, item_cuts, note)


def _clip_speed(project: Project, target: AudioTarget) -> float:
    return float(project.timeline[target.index].speed)  # type: ignore[index, union-attr]


def _truncate_clip(
    project: Project,
    layout: OriginAggregate,
    target: AudioTarget,
    item_cuts: list[tuple[float, float]],
    note: str,
) -> EditOutcome:
    """No clipe: cada silêncio sai da imagem e do som juntos, e o mapa de tempo avisa os marcadores. Os cortes estão em
    segundos do item (da fonte); a linha do tempo anda `1 / velocidade` por segundo de item."""
    speed = _clip_speed(project, target)
    start_of_clip = layout.spans[target.index][0]  # type: ignore[index]
    relative = [(a / speed, b / speed) for a, b in item_cuts]
    edited = cut_clip_ranges(project, target.index, relative, layout.durations, CUT_FADE_SECONDS)  # type: ignore[arg-type]
    time_map = TimeMap.from_changes(removed=[(start_of_clip + a, start_of_clip + b) for a, b in relative])
    return EditOutcome(edited, time_map, [note])


def _truncate_voiceover(
    project: Project, target: AudioTarget, item_cuts: list[tuple[float, float]], note: str
) -> EditOutcome:
    """Na voz gravada: um `cut` (o item encolhe) por silêncio, do último para o primeiro, e a voz que vem depois na
    trilha recua o que saiu. Como nada disso mexe na imagem, os marcadores ficam onde estão."""
    cuts = [
        {"type": "cut", "start": a, "end": b, "keep_length": False}
        for a, b in reversed(item_cuts)  # do fim para o começo: o tempo dos que faltam não muda
    ]
    edited = add_effects(project, target.path, cuts)
    clip = project.audio.voiceover[target.index]  # type: ignore[index]
    for a, b in reversed(item_cuts):
        edited = shift_later_voiceovers(edited, target.index, clip.start + b, -(b - a))  # type: ignore[arg-type]
    return EditOutcome(edited, None, [note])


RestorationOperation = Callable[[Project, dict, OriginAggregate], object]

RESTORATION_OPERATIONS: dict[str, RestorationOperation] = {
    "noise_profile_set": _op_noise_profile_set,
    "noise_profile_remove": _op_noise_profile_remove,
    "audio_truncate_silence": _op_truncate_silence,
}
