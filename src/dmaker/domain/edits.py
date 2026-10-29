"""Operações de edição pontual sobre a spec: cortar, remover, mover, aparar, duplicar, inserir,
ajustar sobreposições e mudar um campo qualquer. Tudo puro: cada função devolve um Project NOVO
(a spec original nunca é alterada) e levanta `EditError` com mensagem em português quando o pedido
não faz sentido."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import ValidationError

from .spec import ClipSegment, Project, Segment

MIN_SEGMENT_DURATION = 0.1  # segundos; nenhum trecho pode ficar mais curto que isso
GAP_TOLERANCE = (
    0.002  # s; os cortes são gravados em milissegundos, então 2 ms separam "o mesmo ponto" de outro
)


class EditError(ValueError):
    """Pedido de edição inválido (índice fora do intervalo, parâmetro incoerente, spec resultante inválida)."""


def _clone(project: Project, mutate: Callable[[dict], None]) -> Project:
    """Aplica `mutate` sobre uma cópia (dict) da spec e revalida; preserva `base_dir`."""
    data = project.model_dump()
    mutate(data)
    try:
        new_project = Project.model_validate(data)
    except ValidationError as exc:
        raise EditError(str(exc)) from exc
    new_project.base_dir = project.base_dir
    return new_project


def _check_index(length: int, index: int, what: str) -> None:
    if not (0 <= index < length):
        raise EditError(f"índice de {what} fora do intervalo: {index} (0 a {length - 1})")


# ---------- trechos da linha do tempo ----------


def split_segment(project: Project, index: int, at: float, durations: list[float]) -> Project:
    """Divide o trecho `index` em dois no instante `at` (segundos desde o início do trecho, já na
    linha do tempo final). Clipe: o segundo começa em `start + at*speed`. Imagem/cartão: divide a
    `duration`. `transition`/`fade_in` ficam no primeiro; `fade_out` vai para o segundo."""
    _check_index(len(project.timeline), index, "trecho")
    if index >= len(durations):
        raise EditError("durations não cobre todos os trechos da linha do tempo")
    duration = durations[index]
    if not (0 < at < duration):
        raise EditError(f"at ({at:g}) precisa estar entre 0 e a duração do trecho ({duration:g}s)")

    def mutate(data: dict) -> None:
        timeline = data["timeline"]
        original = timeline[index]
        first = dict(original)
        second = dict(original)
        if original["type"] == "clip":
            speed = original["speed"]
            split_point = original["start"] + at * speed
            first["end"] = split_point
            second["start"] = split_point
            # second["end"] continua o mesmo do original (pode ser None: até o fim da mídia)
        else:
            first["duration"] = at
            second["duration"] = duration - at
        second["transition"] = None
        second["fade_in"] = 0.0
        first["fade_out"] = 0.0
        timeline[index : index + 1] = [first, second]

    return _clone(project, mutate)


def remove_segment(project: Project, index: int) -> Project:
    """Remove o trecho `index` (ripple: os seguintes deslizam para preencher o buraco). A linha do
    tempo nunca pode ficar vazia."""
    _check_index(len(project.timeline), index, "trecho")
    if len(project.timeline) <= 1:
        raise EditError("não é possível remover o único trecho da linha do tempo")

    def mutate(data: dict) -> None:
        del data["timeline"][index]

    return _clone(project, mutate)


def move_segment(project: Project, index: int, to: int) -> Project:
    """Move o trecho `index` para a posição `to`, deslocando os demais."""
    n = len(project.timeline)
    _check_index(n, index, "trecho")
    _check_index(n, to, "trecho")

    def mutate(data: dict) -> None:
        timeline = data["timeline"]
        item = timeline.pop(index)
        timeline.insert(to, item)

    return _clone(project, mutate)


def trim_segment(
    project: Project,
    index: int,
    side: Literal["in", "out"],
    delta: float,
    durations: list[float],
    media_duration: float | None,
) -> Project:
    """Ajusta a entrada (`side="in"`) ou a saída (`side="out"`) do trecho `index` em `delta` segundos
    (tempo final, na linha do tempo). Clipe: mexe em `start` (in) ou `end` (out), multiplicado pela
    velocidade. Imagem/cartão: só existe `duration`; "in" reduz mantendo o fim, "out" aumenta/reduz
    direto. Nunca deixa menos de 0.1s nem passa de `media_duration` (quando informado): fora dos
    limites, apara até o limite em vez de dar erro."""
    if side not in ("in", "out"):
        raise EditError(f"lado inválido: {side!r} (use 'in' ou 'out')")
    _check_index(len(project.timeline), index, "trecho")
    if index >= len(durations):
        raise EditError("durations não cobre todos os trechos da linha do tempo")
    duration = durations[index]

    def mutate(data: dict) -> None:
        seg = data["timeline"][index]
        if seg["type"] == "clip":
            speed = seg["speed"]
            start = seg["start"]
            end = seg["end"]
            if end is None:
                end = media_duration if media_duration is not None else start + duration * speed
            if side == "in":
                new_start = start + delta * speed
                new_start = min(max(new_start, 0.0), end - MIN_SEGMENT_DURATION * speed)
                seg["start"] = new_start
            else:
                new_end = end + delta * speed
                upper = media_duration if media_duration is not None else new_end
                new_end = min(max(new_end, start + MIN_SEGMENT_DURATION * speed), upper)
                seg["end"] = new_end
        else:
            current = seg["duration"]
            new_duration = current - delta if side == "in" else current + delta
            seg["duration"] = max(MIN_SEGMENT_DURATION, new_duration)

    return _clone(project, mutate)


def duplicate_segment(project: Project, index: int) -> Project:
    """Insere uma cópia do trecho `index` logo depois dele, sem transição (a cópia começa com corte seco)."""
    _check_index(len(project.timeline), index, "trecho")

    def mutate(data: dict) -> None:
        timeline = data["timeline"]
        copy = dict(timeline[index])
        copy["transition"] = None
        timeline.insert(index + 1, copy)

    return _clone(project, mutate)


def insert_segment(project: Project, index: int, segment: dict[str, Any]) -> Project:
    """Insere um trecho novo (validado pela spec) na posição `index`."""
    n = len(project.timeline)
    if not (0 <= index <= n):
        raise EditError(f"índice de trecho fora do intervalo: {index} (0 a {n})")

    def mutate(data: dict) -> None:
        data["timeline"].insert(index, dict(segment))

    return _clone(project, mutate)


def restore_gap(project: Project, start: float, end: float | None, origin: str | None = None) -> Project:
    """Devolve ao projeto o trecho `start` a `end` (tempos do arquivo; `end=None` = até o fim) que ficou de
    fora entre clipes: o clipe que acaba em `start` e o que começa em `end` viram um só. Se só um dos
    dois existe (corte no começo ou no fim da gravação), ele cresce até cobrir o trecho. `origin` restringe
    aos clipes dessa gravação (`src` ou `source`), para um projeto com várias não mexer na errada."""
    timeline = project.timeline

    def ends_at(segment: Segment) -> bool:
        return (
            isinstance(segment, ClipSegment)
            and (origin is None or segment.origin == origin)
            and segment.end is not None
            and abs(segment.end - start) <= GAP_TOLERANCE
        )

    def starts_at(segment: Segment) -> bool:
        return (
            isinstance(segment, ClipSegment)
            and (origin is None or segment.origin == origin)
            and end is not None
            and abs(segment.start - end) <= GAP_TOLERANCE
        )

    before = next((i for i, segment in enumerate(timeline) if ends_at(segment)), None)
    after = next((i for i, segment in enumerate(timeline) if starts_at(segment)), None)
    if before is None and after is None:
        raise EditError(
            "o trecho cortado não está mais ao lado de nenhum clipe (a linha do tempo foi mudada): "
            "refaça o corte ou insira o trecho à mão"
        )
    if before is not None and after is not None and not _can_join(timeline, before, after):
        raise EditError("os clipes de cada lado do corte não são mais vizinhos da mesma gravação")

    def mutate(data: dict) -> None:
        clips = data["timeline"]
        if before is not None and after is not None:
            clips[before]["end"] = clips[after]["end"]
            clips[before]["fade_out"] = clips[after].get("fade_out", 0.0)
            del clips[after]
        elif before is not None:
            clips[before]["end"] = end
        else:
            clips[after]["start"] = start

    return _clone(project, mutate)


def _can_join(timeline: list[Segment], before: int, after: int) -> bool:
    first, second = timeline[before], timeline[after]
    return (
        after == before + 1
        and isinstance(first, ClipSegment)
        and isinstance(second, ClipSegment)
        and first.origin == second.origin
        and first.speed == second.speed
        and first.audio_mode == second.audio_mode
    )


# ---------- sobreposições ----------


def set_overlay_span(project: Project, index: int, start: float, end: float | None) -> Project:
    """Muda o início/fim (`end=None` = até o fim) de uma sobreposição. Uma `progress-bar` não tem
    intervalo próprio (vale a linha inteira); tentar dar span nela levanta EditError."""
    _check_index(len(project.overlays), index, "sobreposição")

    def mutate(data: dict) -> None:
        data["overlays"][index]["start"] = start
        data["overlays"][index]["end"] = end

    return _clone(project, mutate)


def add_overlay(project: Project, overlay: dict) -> Project:
    """Acrescenta uma sobreposição (em forma de dict da spec, com `type`) ao fim da lista; a spec inteira é
    revalidada, então um campo inválido ou uma região que o projeto não declara falha aqui."""

    def mutate(data: dict) -> None:
        data["overlays"].append(overlay)

    return _clone(project, mutate)


def remove_overlay(project: Project, index: int) -> Project:
    """Remove a sobreposição `index`."""
    _check_index(len(project.overlays), index, "sobreposição")

    def mutate(data: dict) -> None:
        del data["overlays"][index]

    return _clone(project, mutate)


def duplicate_overlay(project: Project, index: int) -> Project:
    """Insere uma cópia da sobreposição `index` logo depois dela."""
    _check_index(len(project.overlays), index, "sobreposição")

    def mutate(data: dict) -> None:
        overlays = data["overlays"]
        overlays.insert(index + 1, dict(overlays[index]))

    return _clone(project, mutate)


# ---------- campo qualquer ----------


def set_field(project: Project, path: str, value: Any) -> Project:
    """Muda um campo pelo caminho (`"timeline.2.speed"`, `"overlays.0.style.size"`,
    `"audio.music.volume"`, `"sources.cam1.sync"`): pontos separam níveis, índices numéricos
    indexam listas. `value=None` remove a chave (o campo volta ao padrão da spec). Revalida a spec
    inteira; erro de validação vira EditError com a mensagem do Pydantic."""
    parts = path.split(".")
    if not path or any(not p for p in parts):
        raise EditError(f"caminho inválido: {path!r}")

    def mutate(data: dict) -> None:
        target: Any = data
        for part in parts[:-1]:
            key: Any = int(part) if isinstance(target, list) else part
            if isinstance(target, dict) and key not in target:
                target[key] = {}  # cria o dicionário no caminho (ex.: "tracks.V2" ainda não existia)
            try:
                target = target[key]
            except (KeyError, IndexError, TypeError) as exc:
                raise EditError(f"caminho inválido: {path!r} ({exc})") from exc
        last = parts[-1]
        key = int(last) if isinstance(target, list) else last
        if value is None:
            if isinstance(target, dict):
                target.pop(key, None)
            else:
                raise EditError(f"não é possível remover um item de lista com set_field: {path!r}")
        else:
            try:
                target[key] = value
            except (IndexError, TypeError) as exc:
                raise EditError(f"caminho inválido: {path!r} ({exc})") from exc

    return _clone(project, mutate)
