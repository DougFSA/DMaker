"""A cadeia de efeitos de um item como linhas de grafo do ffmpeg: percorre a lista na ordem, liga a saída de cada
efeito à entrada do seguinte e cuida do intervalo (`start`/`end`) de qualquer efeito do mesmo jeito. Puro."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ...domain.audio_effects import EffectBase, active_effects
from ...domain.plugins import PluginPorts
from .measure import Measure
from .registry import SAMPLE_RATE, EffectRequest, build_effect, is_sample_effect

# Emenda entre o som seco e o processado nas bordas de um intervalo: 10 ms de transição linear. É curta o
# bastante para o efeito começar onde a pessoa marcou e longa o bastante para a onda não dar degrau (um corte
# seco de amplitude entre dois sons estala; uma rampa de 480 amostras a 48 kHz, não).
SEAM_SECONDS = 0.010


def ingress_line(input_index: int, stream: int, out: str, lead: float = 0.0) -> str:
    """A entrada de um item: a faixa de áudio `stream` do arquivo, com o tempo zerado e no formato da mixagem
    (48 kHz, estéreo, ponto flutuante). Em ponto flutuante o ganho passa de 0 dBFS sem cortar a onda, e é isso
    que deixa o Amplificar e o Normalizar medirem e corrigirem depois. `lead` é o silêncio, em segundos, antes de
    o arquivo começar (o som deslocado de um clipe cuja fonte ainda não tinha som)."""
    delay = f",adelay={round(lead * SAMPLE_RATE)}S:all=1" if lead > 0 else ""
    return (
        f"[{input_index}:a:{stream}]asetpts=PTS-STARTPTS,aresample={SAMPLE_RATE},"
        f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo{delay}{out}"
    )


def chain_lines(
    source: str,
    out: str,
    effects: Sequence[EffectBase],
    duration: float,
    measures: Mapping[int, Measure] | None = None,
    *,
    tag: str = "fx",
    ports: Mapping[int, PluginPorts] | None = None,
) -> list[str]:
    """Liga `source` a `out` passando pelos efeitos ligados de `effects`, em ordem. `duration` é a duração do
    sinal que entra e `measures` traz a medida do sinal que entra em cada efeito que precisa dela, pela posição
    do efeito na lista (`ports` faz o mesmo com as portas de áudio dos plugins). Sem nenhum efeito ligado a cadeia
    é uma passagem direta."""
    return stage_lines(source, out, active_effects(effects), duration, measures, tag=tag, ports=ports)


def stage_lines(
    source: str,
    out: str,
    active: Sequence[tuple[int, EffectBase]],
    duration: float,
    measures: Mapping[int, Measure] | None = None,
    *,
    tag: str = "fx",
    ports: Mapping[int, PluginPorts] | None = None,
) -> list[str]:
    """Como `chain_lines`, para efeitos que já vêm com a posição que têm na lista da spec (`active_effects`): é o
    que um trecho de ffmpeg de uma cadeia partida usa, e os rótulos seguem a posição de origem para não se repetirem."""
    if not active:
        return [f"{source}anull{out}"]
    lines: list[str] = []
    current = source
    for position, (index, effect) in enumerate(active):
        target = out if position == len(active) - 1 else f"[{tag}{index}]"
        request = EffectRequest(
            effect,
            current,
            target,
            f"{tag}{index}",
            duration,
            (measures or {}).get(index),
            ports=(ports or {}).get(index),
        )
        lines += apply_effect(request)
        duration = effect.output_duration(duration)
        current = target
    return lines


@dataclass(frozen=True)
class Stage:
    """Um trecho da cadeia: ou efeitos de filtro seguidos (um comando do ffmpeg), ou UM efeito de amostras (numpy), ou UM
    efeito de plugin (um comando só dele, com o ffmpeg que hospeda o formato: `host` é `lv2` ou `ladspa`). Cada efeito vem
    com a posição que tem na lista da spec."""

    effects: tuple[tuple[int, EffectBase], ...]
    samples: bool = False
    host: str | None = None


def split_stages(effects: Sequence[EffectBase]) -> list[Stage]:
    """Parte a cadeia nos trechos em que ela muda de mundo: os efeitos de filtro seguidos ficam juntos num trecho de
    ffmpeg e cada efeito de amostras, ou de plugin, é um estágio só dele. Uma cadeia sem nenhum dos dois é um trecho só (o
    comando de sempre). Só os efeitos ligados entram."""
    stages: list[Stage] = []
    run: list[tuple[int, EffectBase]] = []
    for index, effect in active_effects(effects):
        host = effect.host_format()
        if host is not None or is_sample_effect(effect):
            if run:
                stages.append(Stage(tuple(run)))
                run = []
            stages.append(Stage(((index, effect),), samples=host is None, host=host))
        else:
            run.append((index, effect))
    if run or not stages:
        stages.append(Stage(tuple(run)))
    return stages


def apply_effect(request: EffectRequest) -> list[str]:
    """O efeito no sinal todo, ou só no intervalo dele quando tem `start`/`end`, com a emenda curta nas bordas."""
    if (
        request.effect.owns_interval
    ):  # o Cortar e o Envelope leem o próprio intervalo (ver `EffectBase.owns_interval`)
        return build_effect(request)
    span = request.effect.span(request.duration)
    if span is None:
        return build_effect(request)
    rate = request.sample_rate
    total = round(request.duration * rate)
    first, last = round(span[0] * rate), round(span[1] * rate)
    if first <= 0 and last >= total:  # o intervalo cobre o sinal todo (a diferença é só arredondamento)
        return build_effect(request)
    if last - first < 2:  # nada a processar: um intervalo vazio deixa o som como está
        return request.chain("anull")
    if request.effect.alters_duration():
        return _spliced(request, first, last, total)
    return _crossfaded(request, first, last, total)


def span_samples(effect: EffectBase, duration: float) -> tuple[int, int] | None:
    """O intervalo do efeito em amostras, ou None quando ele vale no sinal todo (a análise mede só esse trecho)."""
    span = effect.span(duration)
    if span is None:
        return None
    return round(span[0] * SAMPLE_RATE), round(span[1] * SAMPLE_RATE)


def _inner(request: EffectRequest, first: int, last: int, source: str, out: str) -> list[str]:
    """O efeito aplicado ao trecho `first`..`last` já recortado e com o tempo zerado, em `source`."""
    inner = EffectRequest(
        request.effect,
        source,
        out,
        request.tag,
        (last - first) / request.sample_rate,
        request.measure,
        request.side,
        request.sample_rate,
        request.ports,
    )
    return build_effect(inner)


def _crossfaded(request: EffectRequest, first: int, last: int, total: int) -> list[str]:
    """Efeito que mantém a duração: o som seco passa fora do intervalo, o processado dentro, e nas bordas os
    dois se cruzam numa rampa linear de 10 ms (o seco sai enquanto o processado entra, somando sempre 1). Como a
    soma dos pesos é 1 e os dois sons são contínuos, a saída não tem degrau de amostra. Quando o intervalo
    começa em 0 ou termina no fim do item, aquela borda não tem vizinho e não leva rampa."""
    ramp = min(round(SEAM_SECONDS * request.sample_rate), (last - first) // 2)
    has_head, has_tail = first > 0, last < total
    names = ["w"] + (["h"] if has_head else []) + (["t"] if has_tail else [])
    lines = [f"{request.source}asplit={len(names)}" + "".join(request.label(name) for name in names)]

    lines.append(
        f"{request.label('w')}atrim=start_sample={first}:end_sample={last},asetpts=PTS-STARTPTS"
        f"{request.label('wi')}"
    )
    lines += _inner(request, first, last, request.label("wi"), request.label("wo"))
    wet_tail = []
    if has_head:
        wet_tail.append(f"afade=t=in:ss=0:ns={ramp}:curve=tri")
    if has_tail:
        wet_tail.append(f"afade=t=out:ss={last - first - ramp}:ns={ramp}:curve=tri")
    if first > 0:
        wet_tail.append(f"adelay={first}S:all=1")
    lines.append(f"{request.label('wo')}{','.join(wet_tail) or 'anull'}{request.label('wd')}")
    mixed = [request.label("wd")]

    if has_head:
        # o seco vai até o fim da rampa, saindo; depois dela o processado está sozinho
        head = [
            f"atrim=end_sample={first + ramp}",
            "asetpts=PTS-STARTPTS",
            f"afade=t=out:ss={first}:ns={ramp}:curve=tri",
        ]
        lines.append(f"{request.label('h')}{','.join(head)}{request.label('hd')}")
        mixed.append(request.label("hd"))
    if has_tail:
        # o seco volta a partir do começo da rampa final, entrando; antes dela o processado está sozinho
        tail = [
            f"atrim=start_sample={last - ramp}",
            "asetpts=PTS-STARTPTS",
            f"afade=t=in:ss=0:ns={ramp}:curve=tri",
            f"adelay={last - ramp}S:all=1",
        ]
        lines.append(f"{request.label('t')}{','.join(tail)}{request.label('td')}")
        mixed.append(request.label("td"))
    lines.append(
        "".join(mixed)
        + f"amix=inputs={len(mixed)}:duration=longest:dropout_transition=0:normalize=0{request.out}"
    )
    return lines


def _spliced(request: EffectRequest, first: int, last: int, total: int) -> list[str]:
    """Efeito que muda a duração (Repetir): o trecho processado entra no lugar do original, entre o que veio antes
    e o que vem depois. A emenda é a do próprio efeito, como no Audacity: não há rampa a fazer."""
    names = ["w"] + (["h"] if first > 0 else []) + (["t"] if last < total else [])
    lines = [f"{request.source}asplit={len(names)}" + "".join(request.label(name) for name in names)]
    parts: list[str] = []
    if first > 0:
        lines.append(
            f"{request.label('h')}atrim=end_sample={first},asetpts=PTS-STARTPTS{request.label('hd')}"
        )
        parts.append(request.label("hd"))
    lines.append(
        f"{request.label('w')}atrim=start_sample={first}:end_sample={last},asetpts=PTS-STARTPTS"
        f"{request.label('wi')}"
    )
    lines += _inner(request, first, last, request.label("wi"), request.label("wd"))
    parts.append(request.label("wd"))
    if last < total:
        lines.append(
            f"{request.label('t')}atrim=start_sample={last},asetpts=PTS-STARTPTS{request.label('td')}"
        )
        parts.append(request.label("td"))
    lines.append("".join(parts) + f"concat=n={len(parts)}:v=0:a=1{request.out}")
    return lines
