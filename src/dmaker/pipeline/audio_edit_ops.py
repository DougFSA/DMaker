"""As operações de edição de onda do `edit_project`: silenciar, cortar, envelope, canais, copiar e colar, duplicar,
dividir, juntar, aparar fora da seleção, deslocar no tempo, dividir o estéreo e o estado da trilha.

Cada operação lê o pedido, acha o item (`audio_targets`), traduz o tempo da linha do tempo (que aceita
`marker:<texto>`) para o tempo do item e chama a função pura de `domain.audio_edits`. Nenhuma toca a imagem nem a
duração do vídeo, então os marcadores não se mexem. Uma operação nova entra aqui por uma entrada em
`AUDIO_OPERATIONS`, sem tocar o despacho de `pipeline.edits`."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..domain.audio_edits import (
    TIME_TOLERANCE,
    add_effects,
    add_envelope,
    append_voiceover,
    join_voiceovers,
    rebase_effects,
    require_file_time,
    set_audio_offset,
    set_edge_fade,
    set_track_state,
    shift_later_voiceovers,
    shift_music,
    shift_start,
    split_stereo,
    split_voiceover,
    trim_voiceover,
)
from ..domain.audio_targets import AudioTarget
from ..domain.crossfade_edits import check_crossfade_kind, crossfade_pair, set_clip_crossfade
from ..domain.edits import EditError
from ..domain.markers import MarkerError, find_marker, is_marker_ref, resolve_instant
from ..domain.spec import ClipSegment, Project, VideoOverlay
from ..domain.tracks import known_track_ids
from .audio_targets import resolve_audio_target
from .layout import OriginAggregate

AudioOperation = Callable[[Project, dict, OriginAggregate], Project]

CHANNEL_MODES = ("mono", "swap", "left", "right")


# ---------- ler o pedido ----------


def _required(op: Mapping, name: str) -> Any:
    if op.get(name) is None:
        raise EditError(f"a operação {op.get('type')!r} precisa do campo `{name}`")
    return op[name]


def _instant(project: Project, value: Any, name: str) -> float:
    try:
        return resolve_instant(value, project.markers, name)
    except MarkerError as exc:
        raise EditError(str(exc)) from exc


def _interval(project: Project, op: Mapping) -> tuple[float, float]:
    """O intervalo pedido, em segundos da linha do tempo: `start` e `end` (números ou `marker:<texto>`), ou `region`,
    o nome de uma região de marcador (`marker:Refrão`), que dá o começo e o fim dela."""
    if op.get("region") is not None:
        reference = op["region"]
        if not is_marker_ref(reference):
            raise EditError(f"`region` é uma referência de marcador (marker:<texto>), não {reference!r}")
        try:
            marker = project.markers[find_marker(project.markers, reference)]
        except MarkerError as exc:
            raise EditError(str(exc)) from exc
        if not marker.is_region:
            raise EditError(f"{reference} é um instante, não uma região: use `start` e `end`")
        return marker.begin, marker.finish
    start = _instant(project, _required(op, "start"), "start")
    end = _instant(project, _required(op, "end"), "end")
    if end <= start:
        raise EditError(f"`end` ({end:g}) precisa ser maior que `start` ({start:g})")
    return start, end


def _target(project: Project, op: Mapping, layout: OriginAggregate) -> AudioTarget:
    return resolve_audio_target(project, layout, _required(op, "target"))


def _whole_item(target: AudioTarget, a: float, b: float) -> bool:
    return a <= TIME_TOLERANCE and target.length is not None and b >= target.length - TIME_TOLERANCE


# ---------- efeitos postos pela edição ----------


def _op_silence(project: Project, op: dict, layout: OriginAggregate) -> Project:
    target = _target(project, op, layout)
    start, end = _interval(project, op)
    pieces = target.item_intervals(start, end)
    effects = [{"type": "silence", "start": round(a, 6), "end": round(b, 6)} for a, b in pieces]
    return add_effects(project, target.path, effects)


def _op_cut(project: Project, op: dict, layout: OriginAggregate) -> Project:
    target = _target(project, op, layout)
    if target.kind in ("track", "master"):
        raise EditError(
            f"{target.path}: {target.name} não aceita cortar (ela segue a sessão e o que toca é a soma dos "
            "itens). Silencie o intervalo, ou corte o item que a alimenta"
        )
    start, end = _interval(project, op)
    a, b = target.single_interval(start, end)
    if _whole_item(target, a, b):
        raise EditError(
            f"o corte leva {target.name} {target.path} inteiro: silencie-o (audio_silence) ou remova o item"
        )
    keep_length = target.pinned  # item preso à imagem: a duração não muda, o fim completa com silêncio
    cut = {"type": "cut", "start": round(a, 6), "end": round(b, 6), "keep_length": keep_length}
    edited = add_effects(project, target.path, [cut])
    if target.kind == "voiceover":  # o que vem depois na trilha recua para fechar o buraco
        clip = project.audio.voiceover[target.index]  # type: ignore[index]
        edited = shift_later_voiceovers(edited, target.index, clip.start + b, -(b - a))  # type: ignore[arg-type]
    return edited


def _op_envelope(project: Project, op: dict, layout: OriginAggregate) -> Project:
    target = _target(project, op, layout)
    raw = _required(op, "points")
    if not isinstance(raw, list) or not raw:
        raise EditError(
            '`points` é uma lista de pontos, por exemplo [{"at": 10, "db": 0}, {"at": 12, "db": -12}]'
        )
    points = []
    for position, point in enumerate(raw):
        if not isinstance(point, Mapping) or "at" not in point or "db" not in point:
            raise EditError(f"o ponto {position} do envelope precisa de `at` (instante) e `db` (ganho)")
        instant = target.item_time(_instant(project, point["at"], f"points[{position}].at"))
        points.append((round(instant, 6), float(point["db"])))
    return add_envelope(project, target.path, points)


def _op_fade(project: Project, op: dict, layout: OriginAggregate) -> Project:
    """O Fade In (`side: in`) ou o Fade Out (`side: out`) preso à borda do item, com `duration` e `curve`: o que a alça do
    fade da linha do tempo grava. Duração zero tira o fade."""
    target = _target(project, op, layout)
    if target.kind == "master":
        raise EditError(
            "o fade da borda vale num item; para o fim da mistura use o efeito studio_fade_out ou fade_out"
        )
    duration = _required(op, "duration")
    if not isinstance(duration, int | float) or isinstance(duration, bool) or duration < 0:
        raise EditError("`duration` é a duração do fade em segundos (0 tira o fade)")
    params = {"curve": op["curve"]} if op.get("curve") is not None else {}
    return set_edge_fade(project, target.path, str(_required(op, "side")), float(duration), params)


def _op_crossfade_tracks(project: Project, op: dict, layout: OriginAggregate) -> Project:
    """O Crossfade Tracks do Audacity: um Fade Ajustável de saída em `out_target` e um de entrada em `in_target`, no
    mesmo intervalo da linha do tempo, com as curvas casadas. É uma edição só (um passo do desfazer) e não muda a mixagem."""
    out_target = resolve_audio_target(project, layout, _required(op, "out_target"))
    in_target = resolve_audio_target(project, layout, _required(op, "in_target"))
    if out_target.path == in_target.path:
        raise EditError("o crossfade pede dois itens diferentes: um que sai e um que entra")
    kind, shape, mid = check_crossfade_kind(
        op.get("kind", "constant_power_1"), op.get("curve"), op.get("mid_adjust")
    )
    start, end = _interval(project, op)
    spans = []
    for target in (out_target, in_target):
        if target.kind == "master":
            raise EditError(
                "a mistura inteira não faz crossfade: use dois itens (clipes, faixas, voz ou música)"
            )
        first, last = target.windows[0], target.windows[-1]
        if start < first.start - TIME_TOLERANCE or end > last.end + TIME_TOLERANCE:
            raise EditError(
                f"{target.path}: {target.name} soa {target.where()} e o crossfade vai de {start:g} a {end:g} s; os "
                "dois itens precisam cobrir o intervalo inteiro"
            )
        spans.append(target.single_interval(start, end))
    leaving, entering = crossfade_pair(kind, shape, mid, spans[0], spans[1])
    edited = add_effects(project, out_target.path, [leaving])
    return add_effects(edited, in_target.path, [entering])


def _op_crossfade_clips(project: Project, op: dict, layout: OriginAggregate) -> Project:
    """O crossfade de som no corte entre dois clipes vizinhos (J-cut e L-cut): `index` é o clipe que entra, `duration` o
    tempo do cruzamento (0 tira) e `curve` o tipo. A imagem continua trocando no quadro exato do corte."""
    index = _required(op, "index")
    if not isinstance(index, int) or isinstance(index, bool):
        raise EditError("`index` é a posição do clipe que entra no corte (1 é o segundo trecho)")
    duration = op.get("duration", 0.5)
    if not isinstance(duration, int | float) or isinstance(duration, bool) or not 0 <= duration <= 5:
        raise EditError("`duration` é o tempo do crossfade em segundos, de 0 (tira) a 5")
    return set_clip_crossfade(project, index, float(duration), op.get("curve"))


def _op_channels(project: Project, op: dict, layout: OriginAggregate) -> Project:
    target = _target(project, op, layout)
    mode = _required(op, "mode")
    if mode not in CHANNEL_MODES:
        raise EditError(f"modo de canais desconhecido: {mode!r}. Use um de: {', '.join(CHANNEL_MODES)}")
    if op.get("start") is None and op.get("end") is None and op.get("region") is None:
        return add_effects(project, target.path, [{"type": "channels", "mode": mode}])
    start, end = _interval(project, op)
    effects = [
        {"type": "channels", "mode": mode, "start": round(a, 6), "end": round(b, 6)}
        for a, b in target.item_intervals(start, end)
    ]
    return add_effects(project, target.path, effects)


def _op_trim(project: Project, op: dict, layout: OriginAggregate) -> Project:
    """Aparar fora da seleção: na voz gravada o trecho do arquivo encolhe; nos outros itens, o que está fora da
    seleção é silenciado (a imagem e a duração não podem mudar)."""
    target = _target(project, op, layout)
    start, end = _interval(project, op)
    a, b = target.single_interval(start, end) if target.kind != "track" else _hull(target, start, end)
    if target.kind == "voiceover":
        if target.length is None:
            raise EditError(f"{target.path}: o arquivo de áudio não foi encontrado, não dá para medir a voz")
        return trim_voiceover(project, target.index, a, min(b, target.length), target.length)  # type: ignore[arg-type]
    outside = []
    if a > TIME_TOLERANCE:
        outside.append({"type": "silence", "start": 0.0, "end": round(a, 6)})
    if target.length is None or b < target.length - TIME_TOLERANCE:
        outside.append({"type": "silence", "start": round(b, 6)})
    return add_effects(project, target.path, outside) if outside else project


def _hull(target: AudioTarget, start: float, end: float) -> tuple[float, float]:
    """O primeiro e o último ponto do arquivo da faixa que a seleção toca, para aparar uma faixa externa em volta
    (a faixa é o arquivo inteiro, e a seleção pode pegar mais de um clipe)."""
    pieces = target.item_intervals(start, end)
    return pieces[0][0], pieces[-1][1]


# ---------- copiar, colar, duplicar ----------


def _copy(
    project: Project, layout: OriginAggregate, target: AudioTarget, a: float, b: float
) -> tuple[dict, float]:
    """O item de voz gravada que reproduz o trecho `a`..`b` (tempo do item) de `target`: o mesmo arquivo, o ponto de
    entrada e de saída nele, o volume e a cadeia de efeitos com os intervalos recortados para o trecho. Devolve também
    o atraso, em segundos, com que ele deve entrar (o som pedido que ainda não existia no começo do arquivo)."""
    kind = target.kind
    if kind in ("narration", "track", "master"):
        reasons = {
            "narration": "a narração é sintetizada do texto e não tem um arquivo para copiar",
            "track": "as faixas externas seguem a sessão e não aceitam copiar e colar",
            "master": "a mistura não é um arquivo; exporte-a e use o arquivo",
        }
        raise EditError(f"{target.path}: {reasons[kind]}")
    if kind == "voiceover":
        clip = project.audio.voiceover[target.index]  # type: ignore[index]
        require_file_time(clip.effects, target.path)
        data = {"src": clip.src, "offset": clip.offset + a, "end": clip.offset + b, "volume": clip.volume}
        return _finished(data, rebase_effects(clip.effects, a, b - a), clip.pan), 0.0
    if kind == "music":
        music = project.audio.music
        assert music is not None
        require_file_time(music.effects, target.path)
        data = {"src": music.src, "offset": a, "end": b, "volume": music.volume}
        return _finished(data, rebase_effects(music.effects, a, b - a), music.pan), 0.0
    if kind == "clip":
        segment = project.timeline[target.index]  # type: ignore[index]
        assert isinstance(segment, ClipSegment)
        if segment.speed != 1:
            raise EditError(
                f"{target.path}: o clipe toca a {segment.speed:g}x e o item novo tocaria na velocidade normal; "
                "ponha a velocidade em 1 antes de copiar o som"
            )
        if segment.audio_mode != "original":
            raise EditError(
                f"{target.path}: o clipe usa o áudio isolado ({segment.audio_mode}), que não é um arquivo"
            )
        if segment.mute or segment.volume <= 0:
            raise EditError(f"{target.path}: o clipe está mudo, não há som para copiar")
        if segment.src:
            path, in_point = segment.src, segment.start
        else:
            reference = project.sources[segment.source or ""]
            if reference.audio_stream != 0:
                raise EditError(
                    f"{target.path}: a fonte usa a faixa de áudio {reference.audio_stream}, que não dá para copiar"
                )
            path, in_point = reference.src or "", layout.sources[target.index].in_point(segment.start)  # type: ignore[index]
        return _from_file(
            path, in_point - segment.audio_offset, a, b, segment.volume, segment.pan, segment.effects
        )
    assert kind == "pip"
    overlay = project.overlays[target.index]  # type: ignore[index]
    assert isinstance(overlay, VideoOverlay)
    if overlay.source:
        reference = project.sources[overlay.source]
        session = layout.physical.session[overlay.source] if layout.physical else None
        if reference.audio_stream != 0 or session is None or reference.src is None:
            raise EditError(f"{target.path}: a fonte do PiP não é um arquivo simples de áudio na faixa 0")
        path, in_point = reference.src, session.in_point(overlay.offset)
    else:
        path, in_point = overlay.src or "", overlay.offset
    return _from_file(path, in_point - overlay.audio_offset, a, b, overlay.volume, 0.0, overlay.effects)


def _from_file(
    path: str, window_start: float, a: float, b: float, volume: float, pan: float, effects
) -> tuple[dict, float]:
    """A voz gravada do trecho `a`..`b` de um som que começa em `window_start` no arquivo `path`. Se o trecho começa
    antes do arquivo, a entrada espera o que falta."""
    require_file_time(effects, "o item")
    lead = max(-(window_start + a), 0.0)  # silêncio antes de o arquivo começar
    first = a + lead
    if first >= b - TIME_TOLERANCE:
        raise EditError("o trecho pedido cai antes do começo do arquivo: não há som para copiar")
    data = {"src": path, "offset": window_start + first, "end": window_start + b, "volume": volume}
    return _finished(data, rebase_effects(effects, first, b - first), pan), lead


def _finished(data: dict, effects, pan: float) -> dict:
    clip = {key: round(value, 6) if isinstance(value, float) else value for key, value in data.items()}
    if effects:
        clip["effects"] = [effect.model_dump() for effect in effects]
    if pan:
        clip["pan"] = pan
    return clip


def _paste(project: Project, op: dict, layout: OriginAggregate, default_at: bool) -> Project:
    target = _target(project, op, layout)
    if op.get("start") is None and op.get("end") is None and op.get("region") is None:
        if target.length is None:
            raise EditError(f"informe `start` e `end`: não dá para saber onde {target.path} acaba")
        start, end = target.windows[0].start, target.windows[-1].end
        a, b = 0.0, target.length
    else:
        start, end = _interval(project, op)
        a, b = target.single_interval(start, end)
    if default_at:  # duplicar: logo depois do original
        at = end
    else:
        at = _instant(project, _required(op, "at"), "at")
    clip, lead = _copy(project, layout, target, a, b)
    clip["start"] = round(at + lead, 6)
    if clip["start"] < 0:
        raise EditError("o instante de colar não pode ser negativo")
    return append_voiceover(project, clip)


def _op_paste(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return _paste(project, op, layout, default_at=False)


def _op_duplicate(project: Project, op: dict, layout: OriginAggregate) -> Project:
    return _paste(project, op, layout, default_at=True)


# ---------- dividir e juntar ----------


def _voice_target(project: Project, op: dict, layout: OriginAggregate, what: str) -> AudioTarget:
    target = _target(project, op, layout)
    if target.kind != "voiceover":
        raise EditError(
            f"{target.path}: {what} só vale para a voz gravada (audio.voiceover.N). {target.name.capitalize()} "
            "é um item preso a outra coisa: para o clipe use `split` (que corta imagem e som juntos)"
        )
    return target


def _op_split(project: Project, op: dict, layout: OriginAggregate) -> Project:
    target = _voice_target(project, op, layout, "dividir")
    if target.length is None:
        raise EditError(f"{target.path}: o arquivo de áudio não foi encontrado, não dá para medir a voz")
    at = target.item_time(_instant(project, _required(op, "at"), "at"))
    return split_voiceover(project, target.index, at, target.length)  # type: ignore[arg-type]


def _op_join(project: Project, op: dict, layout: OriginAggregate) -> Project:
    target = _voice_target(project, op, layout, "juntar")
    other = op.get("with")
    if other is None:
        second = target.index + 1  # type: ignore[operator]
    elif isinstance(other, int) and not isinstance(other, bool):
        second = other
    else:
        second_target = resolve_audio_target(project, layout, other)
        if second_target.kind != "voiceover":
            raise EditError(f"`with` precisa apontar para outra voz gravada, não {other!r}")
        second = second_target.index
    return join_voiceovers(project, target.index, second)  # type: ignore[arg-type]


# ---------- deslocar, dividir o estéreo, estado da trilha ----------


def _op_shift(project: Project, op: dict, layout: OriginAggregate) -> Project:
    target = _target(project, op, layout)
    if (op.get("delta") is None) == (op.get("to") is None):
        raise EditError("informe `delta` (quanto mexer, em segundos) ou `to` (o valor final), um dos dois")
    kind = target.kind
    if kind == "master":
        raise EditError("a mistura inteira não se desloca: desloque os itens que a formam")
    if kind in ("clip", "pip", "track"):
        if kind == "clip":
            current = project.timeline[target.index].audio_offset  # type: ignore[index, union-attr]
        elif kind == "pip":
            current = project.overlays[target.index].audio_offset  # type: ignore[index, union-attr]
        else:
            current = project.audio.tracks[target.index].audio_offset  # type: ignore[index]
        value = float(op["to"]) if op.get("to") is not None else current + float(op["delta"])
        if kind != "track":
            target.require_intervals()
        return set_audio_offset(project, target.path, kind, target.index, value, target.length)  # type: ignore[arg-type]
    if kind in ("voiceover", "narration"):
        items = project.audio.voiceover if kind == "voiceover" else project.audio.narration
        delta = (
            float(op["delta"]) if op.get("delta") is not None else float(op["to"]) - items[target.index].start
        )  # type: ignore[index]
        return shift_start(project, kind, target.index, delta)  # type: ignore[arg-type]
    if op.get("delta") is None:
        raise EditError("a música se desloca por `delta` (quanto andar, em segundos)")
    return shift_music(project, float(op["delta"]))


def _op_split_stereo(project: Project, op: dict, layout: OriginAggregate) -> Project:
    target = _target(project, op, layout)
    return split_stereo(project, target.path, target.kind, target.index)  # type: ignore[arg-type]


def _op_track_set(project: Project, op: dict, layout: OriginAggregate) -> Project:
    track = _required(op, "track")
    changes = {name: value for name, value in op.items() if name not in ("type", "track")}
    return set_track_state(project, str(track), changes, known_track_ids(project))


AUDIO_OPERATIONS: dict[str, AudioOperation] = {
    "audio_silence": _op_silence,
    "audio_cut": _op_cut,
    "audio_envelope": _op_envelope,
    "audio_channels": _op_channels,
    "audio_fade": _op_fade,
    "audio_crossfade_tracks": _op_crossfade_tracks,
    "audio_crossfade_clips": _op_crossfade_clips,
    "audio_trim": _op_trim,
    "audio_paste": _op_paste,
    "audio_duplicate": _op_duplicate,
    "audio_split": _op_split,
    "audio_join": _op_join,
    "audio_shift": _op_shift,
    "audio_split_stereo": _op_split_stereo,
    "track_set": _op_track_set,
}
