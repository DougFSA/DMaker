"""Concatenação dos mezaninos com cortes secos (concat) ou transições (xfade/acrossfade)."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.spec import Transition
from ..domain.timeline import effective_transition
from .common import AUDIO_FMT_MIX
from .transitions import TransitionRequest, build_transition


@dataclass
class TimelineGraph:
    lines: list[str]
    video: str | None  # rótulo do vídeo final (None quando só áudio)
    audio: str
    total: float


def timeline_graph(
    n: int,
    durations: list[float],
    transitions: list[Transition | None],
    fps: float,
    want_video: bool = True,
    size: tuple[int, int] | None = None,
    lead_in: float = 0.0,
    want_audio: bool = True,
) -> TimelineGraph:
    """Junta n mezaninos (entradas 0..n-1). Trechos separados por corte viram um `concat`; entre blocos há a
    transição de vídeo (registrada em `transitions`: xfade ou de movimento) e `acrossfade` (áudio) com o mesmo
    deslocamento. `size` (largura, altura do quadro) só é exigido pelas transições de movimento.

    `lead_in` e `want_audio=False` servem para montar só um pedaço da linha do tempo (a janela da camada da
    pessoa): `lead_in` é o tempo da linha do tempo final que vem antes do primeiro trecho, para o teto de cada
    transição (metade do que já existe) sair igual ao do render completo; sem áudio, o grafo não deixa saída
    solta, que o ffmpeg recusa."""
    assert n == len(durations) == len(transitions)
    lines: list[str] = []
    for i in range(n):
        if want_video:
            # mesmo fps, timebase e formato em todas as entradas: exigência do xfade
            lines.append(f"[{i}:v]fps={fps:g},settb=AVTB,format=yuv420p,setsar=1[tv{i}]")
        if want_audio:
            lines.append(f"[{i}:a]{AUDIO_FMT_MIX}[ta{i}]")

    runs: list[list[int]] = [[0]]
    for i in range(1, n):
        tr = transitions[i]
        if tr is None or tr.type == "cut":
            runs[-1].append(i)
        else:
            runs.append([i])

    labels: list[tuple[str | None, str, float]] = []
    for r, run in enumerate(runs):
        dur = sum(durations[i] for i in run)
        if len(run) == 1:
            i = run[0]
            labels.append((f"[tv{i}]" if want_video else None, f"[ta{i}]", dur))
            continue
        if want_video and not want_audio:
            lines.append("".join(f"[tv{i}]" for i in run) + f"concat=n={len(run)}:v=1:a=0[rv{r}_]")
            lines.append(f"[rv{r}_]fps={fps:g},settb=AVTB[rv{r}]")
            labels.append((f"[rv{r}]", f"[ra{r}]", dur))
        elif want_video:
            ins = "".join(f"[tv{i}][ta{i}]" for i in run)
            lines.append(f"{ins}concat=n={len(run)}:v=1:a=1[rv{r}_][ra{r}]")
            lines.append(f"[rv{r}_]fps={fps:g},settb=AVTB[rv{r}]")
            labels.append((f"[rv{r}]", f"[ra{r}]", dur))
        else:
            ins = "".join(f"[ta{i}]" for i in run)
            lines.append(f"{ins}concat=n={len(run)}:v=0:a=1[ra{r}]")
            labels.append((None, f"[ra{r}]", dur))

    cur_v, cur_a, cur_len = labels[0]
    for k in range(1, len(runs)):
        vl, al, dlen = labels[k]
        tr = transitions[runs[k][0]]
        d = effective_transition(tr, lead_in + cur_len, dlen)
        offset = cur_len - d
        if want_video:
            assert tr is not None
            request = TransitionRequest(
                a=cur_v,
                b=vl,
                out=f"[xv{k}]",
                tag=f"tx{k}",
                duration=d,
                offset=offset,
                fps=fps,
                curve=tr.curve,
                size=size,
            )
            lines.extend(build_transition(tr.type, request))
            cur_v = f"[xv{k}]"
        if want_audio:
            lines.append(f"{cur_a}{al}acrossfade=d={d:.3f}:c1=tri:c2=tri[xa{k}]")
            cur_a = f"[xa{k}]"
        cur_len = cur_len + dlen - d
    return TimelineGraph(lines, cur_v, cur_a, cur_len)
