"""Encadeamento das partes de uma fonte (arquivos em sequência da mesma câmera ou gravador) no
relógio da sessão: função pura, sem tocar ffmpeg nem disco.

Duas rodadas de link por áudio: uma cega (arquivo inteiro contra arquivo inteiro, como sempre foi),
que só tenta pares que possam ter sobreposição pelo relógio de gravação; e uma guiada, que usa a
posição já encontrada de uma parte e o relógio de gravação das duas fontes para prever onde a outra
parte deveria estar e correlacionar só essa vizinhança (`media/audiosync.estimate_offset_near`) —
essencial quando dois arquivos longos têm pouco trecho em comum, caso em que a correlação cega dilui
demais o sinal. Sem link nenhum, a parte cai para o relógio de gravação do próprio arquivo
(`creation_time` do ffprobe), com aviso; sem link e sem relógio, encostada no fim da parte anterior.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..media.audiosync import MIN_GUIDED_OVERLAP_S, SyncResult

PartOffsets = dict[str, list[float]]
LinkFinder = Callable[[Path, Path, float | None], SyncResult]

# câmeras diferentes podem ter o relógio interno dessincronizado por dezenas de segundos; um link de
# áudio "confiável" que discorde disso além dessa margem provavelmente casou o trecho errado, e é
# também o raio de busca da correlação guiada ao redor do deslocamento esperado
CLOCK_TOLERANCE_S = 90.0

ClockHypothesis = str  # "start" (creation_time é o início da gravação) ou "end" (é o fim)


@dataclass(frozen=True)
class PartInfo:
    path: Path
    duration: float
    clock: float | None = None  # creation_time (epoch, segundos) do arquivo, se o ffprobe informar


@dataclass(frozen=True)
class _Placed:
    source: str
    part: int


def chain_parts(
    parts: dict[str, list[PartInfo]],
    links: LinkFinder,
    master: str,
    seed: dict[str, float] | None = None,
) -> tuple[PartOffsets, list[str]]:
    """Posição (relógio da sessão) de cada parte de cada fonte em `parts`. A parte 0 do `master`
    começa em 0 (ou no valor de `seed[master]`, se houver); as demais fontes com posição conhecida
    de antemão (arquivo único, ou `sync` numérico) entram em `seed` do mesmo jeito. Toda posição
    ainda desconhecida é ligada por áudio, primeiro numa rodada cega e depois numa guiada pelo
    relógio de gravação, a uma parte já posicionada de outra fonte; na falta de um link, cai para o
    relógio de gravação do arquivo."""
    seed = seed or {}
    positions: dict[str, list[float | None]] = {name: [None] * len(infos) for name, infos in parts.items()}
    positions[master][0] = seed.get(master, 0.0)
    for name, start in seed.items():
        if name in positions:
            positions[name][0] = start

    placed = [
        _Placed(name, k) for name, values in positions.items() for k, v in enumerate(values) if v is not None
    ]
    pending = {(name, k) for name, values in positions.items() for k, v in enumerate(values) if v is None}
    warnings: list[str] = []

    _run_pass(
        positions, pending, placed, lambda name, k: _best_blind_link(parts, positions, placed, name, k, links)
    )

    hypotheses = clock_hypotheses(parts, positions)
    _run_pass(
        positions,
        pending,
        placed,
        lambda name, k: _best_guided_link(parts, positions, placed, name, k, links, hypotheses),
    )

    for name in sorted({source for source, _ in pending}):
        fallen = sorted(k for source, k in pending if source == name)
        _position_by_clock(name, parts[name], positions[name], hypotheses.get(name, "start"), warnings)
        pending -= {(name, k) for k in fallen}
        warnings.append(
            f"{name}: {len(fallen)} de {len(parts[name])} parte(s) sem link de áudio confiável, "
            "confira o posicionamento"
        )

    resolved = {name: [v if v is not None else 0.0 for v in values] for name, values in positions.items()}
    return resolved, warnings


def _run_pass(
    positions: dict[str, list[float | None]],
    pending: set[tuple[str, int]],
    placed: list[_Placed],
    best_link: Callable[[str, int], float | None],
) -> None:
    """Tenta posicionar cada parte pendente repetidamente até uma rodada inteira não progredir; uma
    parte recém-posicionada vira referência para as próximas tentativas na mesma rodada."""
    progressed = True
    while pending and progressed:
        progressed = False
        for name, k in sorted(pending):
            start = best_link(name, k)
            if start is None:
                continue
            positions[name][k] = start
            placed.append(_Placed(name, k))
            pending.discard((name, k))
            progressed = True


def _best_blind_link(
    parts: dict[str, list[PartInfo]],
    positions: dict[str, list[float | None]],
    placed: list[_Placed],
    name: str,
    k: int,
    links: LinkFinder,
) -> float | None:
    """Melhor posição para `parts[name][k]` ligando por áudio, arquivo inteiro contra arquivo
    inteiro, a cada parte já posicionada de outra fonte; só tenta pares que, por alguma leitura do
    relógio de gravação, podem ter sobreposição (ou tenta todos, sem relógio para descartar), e
    descarta o que discordar demais dos relógios."""
    info_pending = parts[name][k]
    best_confidence = -1.0
    best_start: float | None = None
    for ref in placed:
        if ref.source == name:
            continue
        info_ref = parts[ref.source][ref.part]
        overlap = _max_clock_overlap(info_ref, info_pending)
        if overlap is not None and overlap < MIN_GUIDED_OVERLAP_S:
            continue
        result = links(info_ref.path, info_pending.path, None)
        if not result.reliable or result.confidence <= best_confidence:
            continue
        if not _agrees_with_clocks(result.offset, info_ref, info_pending):
            continue
        best_confidence, best_start = result.confidence, positions[ref.source][ref.part] + result.offset
    return best_start


def _best_guided_link(
    parts: dict[str, list[PartInfo]],
    positions: dict[str, list[float | None]],
    placed: list[_Placed],
    name: str,
    k: int,
    links: LinkFinder,
    hypotheses: dict[str, ClockHypothesis],
) -> float | None:
    """Melhor posição ligando por áudio, guiado pelo deslocamento que o relógio de gravação das
    duas fontes prevê (hipóteses já decididas); só tenta pares cuja sobreposição prevista basta
    para correlacionar, e descarta links fora da margem do relógio mesmo que "confiáveis"."""
    info_pending = parts[name][k]
    best_confidence = -1.0
    best_start: float | None = None
    for ref in placed:
        if ref.source == name:
            continue
        info_ref = parts[ref.source][ref.part]
        expected = _expected_offset(hypotheses, ref.source, info_ref, name, info_pending)
        if expected is None:
            continue
        if _predicted_overlap(info_ref.duration, expected, info_pending.duration) < MIN_GUIDED_OVERLAP_S:
            continue
        result = links(info_ref.path, info_pending.path, expected)
        if not result.reliable or abs(result.offset - expected) > CLOCK_TOLERANCE_S:
            continue
        if result.confidence <= best_confidence:
            continue
        best_confidence, best_start = result.confidence, positions[ref.source][ref.part] + result.offset
    return best_start


def _clock_start(info: PartInfo, hypothesis: ClockHypothesis) -> float:
    """Início da gravação no relógio de bordo do arquivo, segundo a hipótese: `creation_time` já é
    o início, ou marca o fim e é preciso descontar a duração."""
    return info.clock if hypothesis == "start" else info.clock - info.duration  # type: ignore[operator]


def _expected_offset(
    hypotheses: dict[str, ClockHypothesis], name_a: str, a: PartInfo, name_b: str, b: PartInfo
) -> float | None:
    """Deslocamento (início de `b` menos início de `a`) que os relógios de gravação preveem, dadas
    as hipóteses já decididas para cada fonte; `None` se algum dos dois não informa relógio."""
    if a.clock is None or b.clock is None:
        return None
    return _clock_start(b, hypotheses.get(name_b, "start")) - _clock_start(a, hypotheses.get(name_a, "start"))


def _predicted_overlap(duration_a: float, offset: float, duration_b: float) -> float:
    """Segundos em comum entre um arquivo de `duration_a` e outro de `duration_b` que começa
    `offset` segundos depois (ou antes, se negativo)."""
    return min(duration_a, offset + duration_b) - max(0.0, offset)


def _max_clock_overlap(a: PartInfo, b: PartInfo) -> float | None:
    """Maior sobreposição prevista entre `a` e `b`, testando as 4 combinações possíveis de hipótese
    de relógio (início ou fim) para cada um; `None` se algum dos dois não informa relógio, caso em
    que não há como descartar o par por sobreposição."""
    if a.clock is None or b.clock is None:
        return None
    return max(
        _predicted_overlap(a.duration, _clock_start(b, hyp_b) - _clock_start(a, hyp_a), b.duration)
        for hyp_a in ("start", "end")
        for hyp_b in ("start", "end")
    )


def _agrees_with_clocks(offset: float, a: PartInfo, b: PartInfo) -> bool:
    """Um `offset` (início de `b` menos início de `a`) é compatível com os relógios de gravação se
    bate, dentro da margem, com alguma leitura deles: cada câmera pode gravar em `creation_time` o
    início OU o fim da gravação, então as duas hipóteses valem para cada lado. Sem relógio num dos
    dois, não há como discordar."""
    if a.clock is None or b.clock is None:
        return True
    return any(
        abs(offset - (_clock_start(b, hyp_b) - _clock_start(a, hyp_a))) <= CLOCK_TOLERANCE_S
        for hyp_a in ("start", "end")
        for hyp_b in ("start", "end")
    )


def clock_hypotheses(
    parts: dict[str, list[PartInfo]], positions: dict[str, list[float | None]]
) -> dict[str, ClockHypothesis]:
    """Hipótese de cada fonte sobre o que `creation_time` marca (início ou fim da gravação). Um par
    já posicionado por áudio de fontes DIFERENTES vota, para cada uma, em toda combinação de
    hipótese compatível com a posição observada (as duas fontes podem ter hipóteses diferentes). Na
    falta disso, um par consecutivo já posicionado da MESMA fonte vota na hipótese cujo palpite de
    intervalo entre as gravações fica mais perto do observado (as duas partes de uma fonte têm a
    mesma hipótese, então aqui não há combinação a testar). Sem evidência nenhuma, o palpite padrão
    é "início"."""
    votes = {name: {"start": 0, "end": 0} for name in parts}

    placed = [(name, k) for name, values in positions.items() for k, v in enumerate(values) if v is not None]
    for i, (name_a, k_a) in enumerate(placed):
        for name_b, k_b in placed[i + 1 :]:
            if name_a != name_b:
                _vote_cross_source(votes, parts, positions, name_a, k_a, name_b, k_b)

    for name, infos in parts.items():
        for k in range(1, len(infos)):
            _vote_same_source(votes, parts[name], positions[name], name, k)

    return {name: ("end" if tally["end"] > tally["start"] else "start") for name, tally in votes.items()}


def _vote_cross_source(
    votes: dict[str, dict[str, int]],
    parts: dict[str, list[PartInfo]],
    positions: dict[str, list[float | None]],
    name_a: str,
    k_a: int,
    name_b: str,
    k_b: int,
) -> None:
    """Soma um voto de hipótese para `name_a` e para `name_b`, cada um podendo ter a sua, a cada
    combinação (início/fim) compatível com o deslocamento observado entre as duas partes."""
    pos_a, pos_b = positions[name_a][k_a], positions[name_b][k_b]
    info_a, info_b = parts[name_a][k_a], parts[name_b][k_b]
    if pos_a is None or pos_b is None or info_a.clock is None or info_b.clock is None:
        return
    observed = pos_b - pos_a
    for hyp_a in ("start", "end"):
        for hyp_b in ("start", "end"):
            predicted = _clock_start(info_b, hyp_b) - _clock_start(info_a, hyp_a)
            if abs(predicted - observed) <= CLOCK_TOLERANCE_S:
                votes[name_a][hyp_a] += 1
                votes[name_b][hyp_b] += 1


def _vote_same_source(
    votes: dict[str, dict[str, int]], infos: list[PartInfo], positions: list[float | None], name: str, k: int
) -> None:
    """Soma um voto para a hipótese (a mesma para as duas partes, por serem da mesma fonte) cujo
    intervalo previsto entre o fim de `k - 1` e o início de `k` fica mais perto do observado."""
    pos_prev, pos_cur = positions[k - 1], positions[k]
    info_prev, info_cur = infos[k - 1], infos[k]
    if pos_prev is None or pos_cur is None or info_prev.clock is None or info_cur.clock is None:
        return
    observed = pos_cur - pos_prev
    start_guess = _clock_start(info_cur, "start") - _clock_start(info_prev, "start")
    end_guess = _clock_start(info_cur, "end") - _clock_start(info_prev, "end")
    hypothesis = "end" if abs(end_guess - observed) < abs(start_guess - observed) else "start"
    votes[name][hypothesis] += 1


def _position_by_clock(
    name: str,
    infos: list[PartInfo],
    positions: list[float | None],
    hypothesis: ClockHypothesis,
    warnings: list[str],
) -> None:
    """Preenche as posições ainda vazias de `name` a partir da parte anterior e do `creation_time`,
    já com a hipótese de relógio (início ou fim da gravação) decidida em `clock_hypotheses`."""
    total = len(infos)
    for k in range(total):
        if positions[k] is not None:
            continue
        if positions[k - 1] is None:
            positions[k] = 0.0  # segurança: a parte 0 de toda fonte em `parts` já vem semeada
            warnings.append(
                f"{name}: parte {k + 1} de {total} sem posição anterior; encostada em 0s, confira"
            )
            continue
        prev_end = positions[k - 1] + infos[k - 1].duration
        if infos[k].clock is not None and infos[k - 1].clock is not None:
            gap = (_clock_start(infos[k], hypothesis) - _clock_start(infos[k - 1], hypothesis)) - infos[
                k - 1
            ].duration
            positions[k] = prev_end + max(gap, 0.0)
            warnings.append(f"{name}: parte {k + 1} de {total} posicionada pelo relógio, confira")
        else:
            positions[k] = prev_end
            warnings.append(
                f"{name}: parte {k + 1} de {total} sem link de áudio nem relógio de gravação; "
                "encostada no fim da parte anterior, confira"
            )
