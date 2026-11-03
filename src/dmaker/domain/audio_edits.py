"""Edição de onda sobre a spec: silenciar, cortar, envelope, canais, colar, dividir, juntar, aparar, deslocar e dividir
o estéreo. Tudo puro, no molde de `domain/edits.py`: cada função devolve um Project NOVO e levanta `EditError` em
português quando o pedido não faz sentido.

Os tempos que chegam aqui já são tempos DO ITEM (segundos do sinal que entra no efeito, ver `domain.audio_targets`).
Nada é destrutivo: silenciar, cortar, envelope e canais são efeitos postos na cadeia do item (e desfazem-se tirando o
efeito); colar, dividir, juntar e aparar mexem nos campos da voz gravada (`start`, `offset`, `end`), que apontam para
o mesmo arquivo."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from .audio_effects import EffectBase, active_effects, parse_effect, rebase_effects
from .audio_effects.base import EPSILON
from .audio_effects.editing import EnvelopePoint
from .edits import EditError, _check_index, _clone
from .effect_edits import _effect_list
from .spec import MAX_AUDIO_OFFSET, Project, TrackState

# um deslocamento ou um corte de 1 ms é arredondamento da conta de tempo, não uma edição
TIME_TOLERANCE = 0.001


# ---------- a cadeia de efeitos: pedaços, emendas ----------


def keeps_file_time(effects: Sequence[EffectBase]) -> bool:
    """Se o instante do item continua sendo o instante do arquivo depois de toda a cadeia (nenhum efeito ligado troca o
    tempo de lugar). Dividir, juntar, aparar e copiar pedem isto: sem ele não há qual trecho do arquivo cortar."""
    return not any(effect.reorders_time for _, effect in active_effects(effects))


def require_file_time(effects: Sequence[EffectBase], what: str) -> None:
    for _, effect in active_effects(effects):
        if effect.reorders_time:
            raise EditError(
                f"{what}: o item tem o efeito {effect.label}, que troca o tempo do som de lugar, e já não dá para "
                "dizer qual trecho do arquivo é esse. Tire o efeito antes (audio_effect remove)"
            )


def stitch_effects(
    first: Sequence[EffectBase], second: Sequence[EffectBase], boundary: float
) -> list[EffectBase] | None:
    """As cadeias de dois pedaços seguidos (o primeiro dura `boundary`) numa só, ou None quando não dá. Um efeito que
    vale nos dois lados vira um só; o que vale só de um lado fica onde estava. É o desfazer de `rebase_effects`."""
    pending = list(second)
    merged: list[EffectBase] = []
    for effect in first:
        partner = next((candidate for candidate in pending if effect.stitched(candidate, boundary)), None)
        if partner is not None:
            pending.remove(partner)
            merged.append(effect.stitched(partner, boundary))  # type: ignore[arg-type]
        elif effect.end is not None and effect.end < boundary - EPSILON:
            merged.append(effect)
        else:
            return None
    for effect in pending:
        if effect.start is None or effect.start <= EPSILON:
            return None
        merged.append(effect.shifted(boundary))
    return merged


def _dump(effects: Sequence[EffectBase]) -> list[dict]:
    return [effect.model_dump() for effect in effects]


def _parse(effect: dict) -> dict:
    try:
        return parse_effect(effect).model_dump()
    except (ValidationError, ValueError) as exc:
        raise EditError(str(exc)) from exc


def _readable(project: Project, mutate) -> Project:
    """O projeto depois de `mutate`, com a recusa da spec dita só pela regra de negócio (sem o ruído do Pydantic)."""
    from .effect_edits import _readable as readable

    try:
        return _clone(project, mutate)
    except EditError as exc:
        raise EditError(readable(str(exc))) from exc


# ---------- efeitos postos pela edição de onda ----------


def add_effects(project: Project, target: str, effects: Sequence[dict]) -> Project:
    """Acrescenta os efeitos ao fim da cadeia do item (`target`, como em `edit_project`). Ficam no fim porque o
    intervalo que a pessoa marcou é o do que ela ouve, e o que ela ouve é a saída de toda a cadeia."""

    def mutate(data: dict) -> None:
        chain = _effect_list(data, target)
        chain.extend(_parse(effect) for effect in effects)

    return _readable(project, mutate)


def add_envelope(project: Project, target: str, points: Sequence[tuple[float, float]]) -> Project:
    """Põe os pontos `(instante do item, ganho em dB)` na curva do item: se já há um envelope na cadeia, os pontos novos
    entram nele e trocam os que estavam no mesmo trecho (como desenhar mais um pedaço da curva no Audacity); senão
    nasce um envelope no fim da cadeia."""
    new_points = sorted((EnvelopePoint(at=at, db=db) for at, db in points), key=lambda point: point.at)
    if not new_points:
        raise EditError("informe ao menos um ponto do envelope (instante e ganho em dB)")

    def mutate(data: dict) -> None:
        chain = _effect_list(data, target)
        for entry in chain:
            if entry.get("type") == "envelope":
                kept = [
                    EnvelopePoint(**point)
                    for point in entry["points"]
                    if point["at"] < new_points[0].at - EPSILON or point["at"] > new_points[-1].at + EPSILON
                ]
                merged = sorted([*kept, *new_points], key=lambda point: point.at)
                entry["points"] = [point.model_dump() for point in merged]
                entry["enabled"] = True
                return
        chain.append(_parse({"type": "envelope", "points": [point.model_dump() for point in new_points]}))

    return _readable(project, mutate)


# ---------- voz gravada: colar, dividir, juntar, aparar ----------


def append_voiceover(project: Project, clip: dict[str, Any]) -> Project:
    """Põe um item de voz gravada novo no fim da lista (os índices dos outros não mudam)."""

    def mutate(data: dict) -> None:
        data["audio"].setdefault("voiceover", []).append(clip)

    return _readable(project, mutate)


def shift_later_voiceovers(project: Project, skip: int, from_instant: float, delta: float) -> Project:
    """Anda `delta` segundos (negativo recua) as vozes gravadas que começam em `from_instant` ou depois, menos a
    `skip`: o "Delete" do Audacity, em que o que vem depois na trilha recua para fechar o buraco."""
    if abs(delta) <= EPSILON:
        return project

    def mutate(data: dict) -> None:
        for index, clip in enumerate(data["audio"].get("voiceover", [])):
            if index != skip and clip["start"] >= from_instant - TIME_TOLERANCE:
                clip["start"] = max(round(clip["start"] + delta, 6), 0.0)

    return _readable(project, mutate)


def split_voiceover(project: Project, index: int, at_item: float, length: float) -> Project:
    """Divide a voz gravada `index` no instante `at_item` do item (`length` é a duração dela): o segundo item começa
    onde o primeiro acaba, no mesmo arquivo, e a cadeia de efeitos se reparte com os intervalos no lugar certo."""
    _check_index(len(project.audio.voiceover), index, "voz gravada")
    clip = project.audio.voiceover[index]
    require_file_time(clip.effects, f"audio.voiceover.{index}")
    if not TIME_TOLERANCE < at_item < length - TIME_TOLERANCE:
        raise EditError(
            f"o ponto de divisão precisa cair dentro da voz gravada (de 0 a {length:g} s do item)"
        )

    def mutate(data: dict) -> None:
        voices = data["audio"]["voiceover"]
        original = voices[index]
        first, second = dict(original), dict(original)
        first["end"] = round(clip.offset + at_item, 6)
        first["effects"] = _dump(rebase_effects(clip.effects, 0.0, at_item))
        second["start"] = round(clip.start + at_item, 6)
        second["offset"] = round(clip.offset + at_item, 6)
        second["effects"] = _dump(rebase_effects(clip.effects, at_item, length - at_item))
        voices[index : index + 1] = [first, second]

    return _readable(project, mutate)


def join_voiceovers(project: Project, first_index: int, second_index: int) -> Project:
    """Junta duas vozes gravadas que são pedaços seguidos do mesmo arquivo (o contrário de dividir): a segunda tem que
    começar no arquivo onde a primeira termina e, na linha do tempo, onde a primeira acaba. Senão, recusa dizendo qual
    condição falhou."""
    voices = project.audio.voiceover
    _check_index(len(voices), first_index, "voz gravada")
    _check_index(len(voices), second_index, "voz gravada")
    if first_index == second_index:
        raise EditError("juntar pede duas vozes gravadas diferentes")
    first, second = voices[first_index], voices[second_index]
    where = f"audio.voiceover.{first_index} e audio.voiceover.{second_index}"
    if first.src != second.src:
        raise EditError(f"{where}: não são pedaços do mesmo arquivo ({first.src} e {second.src})")
    if first.end is None:
        raise EditError(f"{where}: a primeira vai até o fim do arquivo, não há o que juntar depois dela")
    if abs(second.offset - first.end) > TIME_TOLERANCE:
        raise EditError(
            f"{where}: os trechos do arquivo não são seguidos (a primeira acaba em {first.end:g} s e a "
            f"segunda começa em {second.offset:g} s)"
        )
    length = first.end - first.offset
    if abs(second.start - (first.start + length)) > TIME_TOLERANCE:
        raise EditError(
            f"{where}: não se encostam na linha do tempo (a primeira acaba em {first.start + length:g} s e a "
            f"segunda começa em {second.start:g} s)"
        )
    if first.volume != second.volume or first.pan != second.pan:
        raise EditError(f"{where}: têm volume ou pan diferentes; iguale os dois antes de juntar")
    require_file_time(first.effects, where)
    require_file_time(second.effects, where)
    chain = stitch_effects(first.effects, second.effects, length)
    if chain is None:
        raise EditError(
            f"{where}: os efeitos dos dois lados não combinam (cada lado precisa ter o mesmo efeito, com os "
            "mesmos parâmetros, ou um efeito que vale só dentro do próprio lado)"
        )

    def mutate(data: dict) -> None:
        items = data["audio"]["voiceover"]
        joined = dict(items[first_index])
        joined["end"] = second.end
        joined["effects"] = _dump(chain)
        items[first_index] = joined
        del items[second_index]

    return _readable(project, mutate)


def trim_voiceover(project: Project, index: int, start_at: float, end_at: float, length: float) -> Project:
    """Aparar fora da seleção na voz gravada: o trecho do arquivo encolhe para `start_at`..`end_at` (tempo do item) e
    o item continua tocando no mesmo lugar da linha do tempo, como o "Trim Audio" do Audacity."""
    _check_index(len(project.audio.voiceover), index, "voz gravada")
    clip = project.audio.voiceover[index]
    require_file_time(clip.effects, f"audio.voiceover.{index}")
    if start_at <= TIME_TOLERANCE and end_at >= length - TIME_TOLERANCE:
        return project  # a seleção é o item todo: nada a aparar

    def mutate(data: dict) -> None:
        item = data["audio"]["voiceover"][index]
        item["start"] = round(clip.start + start_at, 6)
        item["offset"] = round(clip.offset + start_at, 6)
        item["end"] = round(clip.offset + end_at, 6)
        item["effects"] = _dump(rebase_effects(clip.effects, start_at, end_at - start_at))

    return _readable(project, mutate)


# ---------- deslocar no tempo ----------


def set_audio_offset(
    project: Project, target: str, kind: str, index: int, value: float, length: float | None
) -> Project:
    """Muda o `audio_offset` do clipe, do PiP ou da faixa externa para `value`. No clipe e no PiP a cadeia de efeitos
    anda junto com o som (o tempo do item parte do começo da janela de som, que o deslocamento mexe), para um
    silêncio marcado sobre uma tosse continuar sobre a tosse."""
    if abs(value) > MAX_AUDIO_OFFSET:
        raise EditError(f"o deslocamento precisa ficar entre -{MAX_AUDIO_OFFSET:g} e {MAX_AUDIO_OFFSET:g} s")
    value = round(value, 6)

    def mutate(data: dict) -> None:
        if kind == "clip":
            item = data["timeline"][index]
        elif kind == "pip":
            item = data["overlays"][index]
        else:
            item = data["audio"]["tracks"][index]
        previous = item.get("audio_offset", 0.0)
        item["audio_offset"] = value
        if kind == "track" or length is None or not item.get("effects"):
            return
        speed = item.get("speed", 1.0) if kind == "clip" else 1.0
        moved = [parse_effect(effect) for effect in item["effects"]]
        item["effects"] = _dump(rebase_effects(moved, (previous - value) * speed, length))

    return _readable(project, mutate)


def shift_start(project: Project, kind: str, index: int, delta: float) -> Project:
    """Anda a voz gravada ou a narração `delta` segundos na linha do tempo (muda o `start`)."""
    items = project.audio.voiceover if kind == "voiceover" else project.audio.narration
    _check_index(len(items), index, "voz gravada" if kind == "voiceover" else "narração")
    new_start = round(items[index].start + delta, 6)
    if new_start < 0:
        raise EditError(f"o deslocamento levaria o item para antes do começo do vídeo ({new_start:g} s)")

    def mutate(data: dict) -> None:
        data["audio"]["voiceover" if kind == "voiceover" else "narration"][index]["start"] = new_start

    return _readable(project, mutate)


def shift_music(project: Project, delta: float) -> Project:
    """Anda a música `delta` segundos na linha do tempo: cada janela (`spans`) anda junto, e uma música sem janelas
    ganha uma que a representa. Para a frente a música começa mais tarde; para trás ela pula o começo do arquivo."""
    music = project.audio.music
    if music is None:
        raise EditError("o projeto não tem música (audio.music)")
    if any(span.from_end or span.tail for span in music.spans):
        raise EditError(
            "a música tem janelas contadas do fim (from_end) ou ancoradas no fim da faixa (tail): mude os "
            "`spans` à mão (set_field)"
        )

    def mutate(data: dict) -> None:
        item = data["audio"]["music"]
        spans = item.get("spans") or [
            {
                "start": 0.0,
                "end": None,
                "start_at": item.get("start_at", 0.0),
                "fade_in": item.get("fade_in", 1.0),
                "fade_out": item.get("fade_out", 2.0),
            }
        ]
        moved = []
        for span in spans:
            start = round(span["start"] + delta, 6)
            end = None if span.get("end") is None else round(span["end"] + delta, 6)
            start_at = span.get("start_at", 0.0)
            if (
                start < 0
            ):  # a música já devia estar tocando: pula a parte do arquivo que ficaria antes do vídeo
                start_at = round(start_at - start, 6)
                start = 0.0
            if end is not None and end <= start:
                continue  # a janela inteira saiu do vídeo
            moved.append({**span, "start": start, "end": end, "start_at": start_at})
        if not moved:
            raise EditError("o deslocamento tira todas as janelas da música do vídeo")
        item["spans"] = moved

    return _readable(project, mutate)


# ---------- dividir o estéreo em duas trilhas mono ----------


def split_stereo(project: Project, target: str, kind: str, index: int) -> Project:
    """Divide um item estéreo em dois, um com o canal esquerdo (`left`) e outro com o direito (`right`), cada um dos
    dois lados saindo nos dois canais. Numa faixa externa o par vira duas trilhas, com o pan duro em cada lado para
    soar como o original; numa voz gravada vira dois itens do mesmo trecho."""
    left = {"type": "channels", "mode": "left"}
    right = {"type": "channels", "mode": "right"}
    if kind == "voiceover":
        _check_index(len(project.audio.voiceover), index, "voz gravada")

        def mutate_voice(data: dict) -> None:
            voices = data["audio"]["voiceover"]
            twin = dict(voices[index])
            twin["effects"] = [*(twin.get("effects") or []), _parse(right)]
            voices[index]["effects"] = [*(voices[index].get("effects") or []), _parse(left)]
            voices.append(twin)

        return _readable(project, mutate_voice)
    if kind != "track":
        raise EditError(
            "dividir o estéreo vale para a voz gravada (audio.voiceover.N) e para a faixa externa (audio.tracks.N)"
        )
    _check_index(len(project.audio.tracks), index, "faixa externa")
    new_id = f"A{2 + len(project.audio.tracks)}"
    old_id = f"A{2 + index}"

    def mutate_track(data: dict) -> None:
        tracks = data["audio"]["tracks"]
        twin = dict(tracks[index])
        twin["effects"] = [*(twin.get("effects") or []), _parse(right)]
        tracks[index]["effects"] = [*(tracks[index].get("effects") or []), _parse(left)]
        tracks.append(twin)
        states = data.setdefault("tracks", {})
        for track_id, side in ((old_id, -1.0), (new_id, 1.0)):
            state = dict(states.get(track_id) or {})
            state["pan"] = side
            states[track_id] = state

    return _readable(project, mutate_track)


# ---------- estado da trilha: ganho, pan, mudo, solo ----------

TRACK_FIELDS = ("gain_db", "pan", "muted", "solo", "hidden", "locked")


def set_track_state(project: Project, track_id: str, changes: dict[str, Any], known: set[str]) -> Project:
    """Muda o estado de uma trilha (ganho, pan, mudo, solo...). Um id que a spec não conhece é erro que lista os que
    conhece; o estado que volta ao padrão sai da lista (a spec fica como se nunca tivesse sido mexida)."""
    if track_id not in known:
        raise EditError(
            f"trilha desconhecida: {track_id!r}. As trilhas deste projeto: {', '.join(sorted(known))}"
        )
    unknown = sorted(set(changes) - set(TRACK_FIELDS))
    if unknown:
        raise EditError(
            f"campo(s) de trilha desconhecido(s): {', '.join(unknown)}. Use: {', '.join(TRACK_FIELDS)}"
        )
    if not changes:
        raise EditError(f"informe o que mudar na trilha {track_id} ({', '.join(TRACK_FIELDS)})")

    def mutate(data: dict) -> None:
        states = data.setdefault("tracks", {})
        try:
            state = TrackState(**{**(states.get(track_id) or {}), **changes})
        except ValidationError as exc:
            raise EditError(str(exc)) from exc
        if state == TrackState():
            states.pop(track_id, None)
        else:
            states[track_id] = state.model_dump()

    return _readable(project, mutate)
