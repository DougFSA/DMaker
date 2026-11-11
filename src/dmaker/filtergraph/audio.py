"""Mixagem de áudio: voz, música com ducking e normalização de loudness."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..domain.audio_effects import active_effects
from ..domain.music_tempo import SEAM_FADE_SECONDS, MusicGrid, music_grid
from ..domain.spec import AudioSettings, Music, MusicSpan
from ..voice.watermark import delay_on_detector_grid
from .audio_effects import Measure, chain_lines
from .common import AUDIO_FMT_MIX, LOUDNORM_TRUE_PEAK_DB, Inputs
from .duck import DuckCurve, curves_for, duck_chain, duck_streams
from .mix import pan_filter
from .sfx import SfxInput, sfx_streams


class NarrationInput(Protocol):
    """O que a mixagem precisa saber de uma narração já sintetizada (satisfeito por `PreparedVoiceover`)."""

    path: Path
    start: float
    volume: float


class VoiceFileInput(Protocol):
    """O que a mixagem precisa saber de um arquivo de áudio posto como voz (satisfeito por `PreparedVoiceFile`):
    onde o trecho do arquivo começa (`offset`), quanto dele toca (`duration`) e em que instante do vídeo entra."""

    path: Path
    start: float
    offset: float
    duration: float
    volume: float


@dataclass
class AudioTaps:
    """Cópias do áudio que o audiograma lê, tiradas de pontos do barramento sem mexer na saída.

    `wanted` diz de que ponto (`voice`: a voz, depois do ganho e das narrações e antes da música; `mix`: a
    mistura inteira, antes da normalização) e `labels` volta preenchido com o rótulo de cada cópia. A cópia
    nunca volta para a mixagem: o ramo que a recebe só alimenta o desenho."""

    wanted: frozenset[str]
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class StemTaps:
    """Cópias de cada barramento de som, tiradas antes da normalização, para exportar uma trilha por arquivo.

    `wanted` diz quais trilhas (`A1`: o som dos trechos, com os PiPs; `NAR`: as narrações; `VO`: as vozes gravadas;
    `MUS`: a música, já abaixada pelo ducking que sofre na mixagem; `SFX`: os efeitos sonoros) e `labels` volta
    preenchido com o rótulo de cada cópia. Cada cópia é a trilha com o ganho que ela tem na mixagem e nada mais:
    somadas, dão a mixagem inteira antes da normalização, que é o que permite a soma dos arquivos reproduzir o mix."""

    wanted: frozenset[str]
    labels: dict[str, str] = field(default_factory=dict)


STEM_TRACKS = ("A1", "NAR", "VO", "MUS", "SFX")


def silent_base(lines: list[str], inputs: Inputs, total: float) -> str:
    """O barramento de base de um projeto sem trechos de vídeo: silêncio da duração do projeto, no formato da
    mixagem. Faz o papel do áudio dos clipes, e como o `amix` da mixagem acaba com a primeira entrada
    (`duration=first`), é ele que fixa a duração do arquivo em `total`."""
    index = inputs.add_silence(total)
    lines.append(f"[{index}:a]{AUDIO_FMT_MIX}[ta_base]")
    return "[ta_base]"


def resolve_span(
    span: MusicSpan, total: float, music_duration: float | None = None
) -> tuple[float, float | None, float]:
    """Converte um `MusicSpan` para (start, end, start_at) absolutos: aplica `from_end` (contado a
    partir do fim do vídeo, usando `total`) e, quando dá para resolver, `tail` (ancora `start_at` no
    final da música, usando `music_duration`). Sem `music_duration`, um span com `tail` sai com
    `start_at` igual à folga bruta, sem ancorar (uso em contextos que só têm a linha do tempo, como a
    vista multitrilha)."""
    if span.from_end:
        start = max(total - span.start, 0.0)
        end = None if span.end is None else max(total - span.end, 0.0)
    else:
        start, end = span.start, span.end
    start_at = span.start_at
    if span.tail and music_duration is not None:
        window_end = total if end is None else end
        length = max(window_end - start, 0.0)
        start_at = max(music_duration - length - span.start_at, 0.0)
    return start, end, start_at


def audio_graph(
    lines: list[str],
    inputs: Inputs,
    cur_a: str,
    audio: AudioSettings,
    music_path: Path | None,
    total: float,
    measured: dict | None = None,
    include_music: bool = True,
    include_norm: bool = True,
    extra_voices: list[str] | None = None,
    music_duration: float | None = None,
    narrations: Sequence[NarrationInput] = (),
    sfx: Sequence[SfxInput] = (),
    voice_files: Sequence[VoiceFileInput] = (),
    taps: AudioTaps | None = None,
    master_measures: Mapping[int, Measure] | None = None,
    master_upto: int | None = None,
    include_master: bool = True,
    stems: StemTaps | None = None,
    duck_curves: Sequence[DuckCurve] = (),
) -> str:
    """Encadeia ganho de voz, música (ducking) e loudnorm sobre `cur_a`; devolve o rótulo final.
    `audio.master_effects` (a cadeia de efeitos do master) entra depois da mistura inteira e antes da
    normalização, que continua valendo por cima; `master_measures` traz a medida da mistura que cada efeito do
    master pede (pela posição dele na lista), `master_upto` corta a cadeia nos `n` primeiros efeitos (é assim que
    se mede o sinal que entra no efeito seguinte) e `include_master=False` deixa a cadeia de fora (a voz sozinha,
    para acertar os efeitos sonoros, e a transcrição).
    `extra_voices` são rótulos de áudio já alinhados à linha do tempo (PiP) somados à voz.
    `narrations` e `voice_files` (arquivos de áudio gravados) entram no barramento de voz depois do ganho e
    do mudo dos clipes (narrar sobre clipes mudos é o caso comum) e antes do ducking: a música abaixa sob
    eles e o loudnorm os conta.
    `sfx` (efeitos sonoros) somam-se por último, depois do ducking e antes do loudnorm: a música não abaixa
    por causa deles (o sidechain só enxerga a voz) e o loudnorm os conta. Sem `sfx` o grafo é o de sempre.
    `taps` pede cópias do barramento para o audiograma (ver `AudioTaps`); sem ele o grafo é o de sempre.
    `stems` pede uma cópia de cada trilha para a exportação por trilha (ver `StemTaps`); sem ele o grafo é o de
    sempre, linha por linha.
    `duck_curves` são as curvas do Auto Duck (`audio.ducks`) que abaixam cada trilha (A1, NAR, VO, MUS, SFX); a da música
    substitui o sidechain antigo, e sem curva nenhuma o grafo é o de sempre, linha por linha.
    `music_duration` é a duração da música, só necessária quando algum span usa `tail`."""
    a = cur_a
    if extra_voices:
        lines.append(
            f"{a}{''.join(extra_voices)}amix=inputs={1 + len(extra_voices)}:duration=first"
            ":dropout_transition=0:normalize=0[a_voices]"
        )
        a = "[a_voices]"
    if audio.mute_clips:
        lines.append(f"{a}volume=0[a_mute]")
        a = "[a_mute]"
    elif audio.voice_gain != 1:
        lines.append(f"{a}volume={audio.voice_gain:.3f}[a_gain]")
        a = "[a_gain]"
    a = _duck_bus(lines, a, curves_for(duck_curves, "A1"), "a_duck")
    a = _stem_tap(lines, stems, "A1", a)

    narration_labels = duck_streams(
        lines, narration_streams(lines, inputs, narrations), curves_for(duck_curves, "NAR"), "nar_duck"
    )
    narration_labels = _stem_group(lines, stems, "NAR", narration_labels)
    voice_file_labels = duck_streams(
        lines, voice_file_streams(lines, inputs, voice_files), curves_for(duck_curves, "VO"), "vf_duck"
    )
    voice_file_labels = _stem_group(lines, stems, "VO", voice_file_labels)
    spoken = narration_labels + voice_file_labels
    if spoken:
        lines.append(
            f"{a}{''.join(spoken)}amix=inputs={1 + len(spoken)}:duration=first"
            ":dropout_transition=0:normalize=0[a_narrated]"
        )
        a = "[a_narrated]"
    a = _tap(lines, taps, "voice", a)

    music: Music | None = audio.music
    if music and music_path and include_music and music.volume > 0:
        mus = music_stream(lines, inputs, music, music_path, total, music_duration, music_grid(audio))
        music_curves = curves_for(duck_curves, "MUS")
        if music_curves:
            # a regra do Auto Duck para a música substitui o sidechain antigo: os dois não rodam juntos
            mus = _stem_tap(lines, stems, "MUS", _duck_bus(lines, mus, music_curves, "mus_duck"))
            lines.append(f"{a}{mus}amix=inputs=2:duration=first:dropout_transition=0:normalize=0[amix]")
        elif music.ducking and (spoken or not audio.mute_clips):
            lines.append(f"{a}asplit=2[voice][sc]")
            sidechain_compress(lines, mus, "[sc]", music)
            ducked = _stem_tap(lines, stems, "MUS", "[musd]")
            lines.append(
                f"[voice]{ducked}amix=inputs=2:duration=first:dropout_transition=0:normalize=0[amix]"
            )
        else:
            mus = _stem_tap(lines, stems, "MUS", mus)
            lines.append(f"{a}{mus}amix=inputs=2:duration=first:dropout_transition=0:normalize=0[amix]")
        a = "[amix]"

    effects = duck_streams(lines, sfx_streams(lines, inputs, sfx), curves_for(duck_curves, "SFX"), "sfx_duck")
    effects = _stem_group(lines, stems, "SFX", effects)
    if effects:
        # sem normalizar (`normalize=0`): o nível de cada efeito já foi acertado contra a voz, e dividir por
        # N entradas o rebaixaria; `duration=first` corta o que passa do fim do vídeo
        lines.append(
            f"{a}{''.join(effects)}amix=inputs={1 + len(effects)}:duration=first"
            ":dropout_transition=0:normalize=0[a_fx]"
        )
        a = "[a_fx]"
    master = audio.master_effects if master_upto is None else audio.master_effects[:master_upto]
    if include_master and active_effects(master):
        # a cadeia espera o formato da mixagem (48 kHz, estéreo, ponto flutuante), o mesmo dos itens
        lines.append(f"{a}aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a_master_in]")
        lines += chain_lines("[a_master_in]", "[a_master]", master, total, master_measures, tag="mfx")
        a = "[a_master]"
    a = _tap(lines, taps, "mix", a)

    if audio.normalize != "off" and include_norm:
        # o loudnorm entrega 192 kHz; volta para 48 kHz
        lines.append(f"{a}{loudnorm_filter(audio.target_lufs, measured)},aresample=48000[a_norm]")
        a = "[a_norm]"
    lines.append(f"{a}aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[aout]")
    return "[aout]"


def sidechain_compress(lines: list[str], music_bus: str, sidechain: str, music: Music) -> None:
    """Abaixa `music_bus` sob `sidechain` (a voz) e deixa a música abaixada em `[musd]`.

    O `sidechaincompress` do ffmpeg guarda cada entrada numa fila própria e, quando uma delas acaba, encerra
    a saída na hora e descarta o que ainda esperava na outra fila. Quanto sobra lá depende de qual das duas
    entradas entregou o último quadro primeiro (uma corrida entre as threads), então o fim da mistura saía
    diferente a cada render do mesmo projeto: medido, o PCM variava em até 7 quadros de 1024 amostras (0,15 s)
    e 52 níveis de 16 bits nos últimos 0,15 s, em 8 s de teste. Igualar as durações não resolve (o fim das
    duas continua simultâneo). O que resolve é o compressor nunca ver o fim: o `apad` sem argumento enche
    as duas entradas com silêncio sem fim, e quem encerra a mistura é a voz, no `amix` (`duration=first`),
    como sempre foi. O silêncio vem depois do programa, então o que se ouve não muda."""
    lines.append(f"{sidechain}apad[scp]")
    lines.append(f"{music_bus}apad[musp]")
    lines.append(
        f"[musp][scp]sidechaincompress=threshold={music.duck_threshold:.4f}:ratio={music.duck_ratio:g}"
        f":attack=20:release={music.duck_release:g}:makeup=1:level_sc=1[musd]"
    )


def _duck_bus(lines: list[str], label: str, curves: Sequence[DuckCurve], name: str) -> str:
    """Abaixa um barramento inteiro (o som dos clipes, a música) pelas curvas do Auto Duck; sem curva devolve o rótulo."""
    chain = duck_chain(curves)
    if not chain:
        return label
    lines.append(f"{label}{','.join(chain)}[{name}]")
    return f"[{name}]"


def _stem_tap(lines: list[str], stems: StemTaps | None, name: str, a: str) -> str:
    """Se a trilha `name` foi pedida, divide `a` em duas: a cópia fica em `stems.labels[name]` e o resto segue."""
    if stems is None or name not in stems.wanted:
        return a
    lines.append(f"{a}asplit=2[stem_{name}_main][stem_{name}_tap]")
    stems.labels[name] = f"[stem_{name}_tap]"
    return f"[stem_{name}_main]"


def _stem_group(lines: list[str], stems: StemTaps | None, name: str, labels: list[str]) -> list[str]:
    """Como `_stem_tap`, para uma trilha que vem em vários fluxos (cada narração, cada voz gravada, cada efeito):
    cada fluxo é dividido em dois, e as cópias se somam na trilha. Sem a trilha pedida devolve os fluxos como vieram."""
    if stems is None or name not in stems.wanted or not labels:
        return labels
    mains, copies = [], []
    for position, label in enumerate(labels):
        main, copy = f"[stem_{name}{position}_main]", f"[stem_{name}{position}_tap]"
        lines.append(f"{label}asplit=2{main}{copy}")
        mains.append(main)
        copies.append(copy)
    if len(copies) == 1:
        stems.labels[name] = copies[0]
    else:
        lines.append(
            "".join(copies)
            + f"amix=inputs={len(copies)}:duration=longest:dropout_transition=0:normalize=0[stem_{name}]"
        )
        stems.labels[name] = f"[stem_{name}]"
    return mains


def _tap(lines: list[str], taps: AudioTaps | None, name: str, a: str) -> str:
    """Se o audiograma pediu `name`, divide `a` em duas: a cópia fica em `taps.labels[name]` e o resto segue."""
    if taps is None or name not in taps.wanted:
        return a
    lines.append(f"{a}asplit=2[a_{name}_main][a_{name}_tap]")
    taps.labels[name] = f"[a_{name}_tap]"
    return f"[a_{name}_main]"


def loudnorm_filter(target_lufs: float, measured: dict | None = None) -> str:
    """O `loudnorm` da normalização final. Com a medição da primeira passada (`measured`) ele aplica um ganho linear
    único (modo de duas passadas); sem ela, trabalha de forma dinâmica numa passada só."""
    ln = f"loudnorm=I={target_lufs:g}:TP={LOUDNORM_TRUE_PEAK_DB:g}:LRA=11"
    if measured:
        ln += (
            f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
            f":offset={measured['target_offset']}:linear=true"
        )
    return ln


def loudnorm_measure_graph(cur_a: str, target_lufs: float, out: str = "[ameas]") -> str:
    return f"{cur_a}loudnorm=I={target_lufs:g}:TP={LOUDNORM_TRUE_PEAK_DB:g}:LRA=11:print_format=json{out}"


def _balance(item: object) -> list[str]:
    """O filtro de equilíbrio esquerda/direita de uma narração ou voz gravada (nenhum, quando o pan é neutro). Lê
    `pan` com `getattr` porque quem satisfaz os protocolos de entrada pode não ter o campo."""
    balance = pan_filter(getattr(item, "pan", 0.0))
    return [balance] if balance else []


def narration_streams(lines: list[str], inputs: Inputs, narrations: Sequence[NarrationInput]) -> list[str]:
    """Uma entrada por narração, em 48 kHz estéreo (como o resto da mixagem), com ganho e atrasada até o
    instante em que começa. Narração sem volume não gera entrada."""
    labels = []
    for index, narration in enumerate(narrations):
        if narration.volume <= 0:
            continue
        chain = [
            f"[{inputs.add(narration.path)}:a]aresample=48000",
            "aformat=sample_fmts=fltp:channel_layouts=stereo",
            f"volume={narration.volume:.3f}",
        ]
        chain += _balance(narration)
        if narration.start > 0:
            # na grade de 20 ms do detector da marca d'água da voz (ver `voice/watermark.py`)
            chain.append(f"adelay={delay_on_detector_grid(narration.start)}:all=1")
        label = f"[nar{index}]"
        lines.append(",".join(chain) + label)
        labels.append(label)
    return labels


def voice_file_streams(lines: list[str], inputs: Inputs, files: Sequence[VoiceFileInput]) -> list[str]:
    """Uma entrada por arquivo de áudio de voz: só o trecho `offset` + `duration` do arquivo, em 48 kHz estéreo
    (como o resto da mixagem), com ganho e atrasado até o instante em que entra. O `asetpts` zera o tempo
    do trecho aparado antes do atraso, senão o `adelay` somaria o `offset` ao instante de entrada."""
    labels = []
    for index, voice in enumerate(files):
        if voice.volume <= 0 or voice.duration <= 0:
            continue
        chain = [
            f"[{inputs.add(voice.path)}:a]atrim=start={voice.offset:.3f}:duration={voice.duration:.3f}",
            "asetpts=PTS-STARTPTS",
            "aresample=48000",
            "aformat=sample_fmts=fltp:channel_layouts=stereo",
            f"volume={voice.volume:.3f}",
        ]
        chain += _balance(voice)
        if voice.start > 0:
            chain.append(f"adelay={int(round(voice.start * 1000))}:all=1")
        label = f"[vf{index}]"
        lines.append(",".join(chain) + label)
        labels.append(label)
    return labels


def music_stream(
    lines: list[str],
    inputs: Inputs,
    music: Music,
    music_path: Path,
    total: float,
    music_duration: float | None = None,
    grid: MusicGrid | None = None,
) -> str:
    """Música alinhada à linha do tempo: uma entrada por janela (`spans`), cada uma aparada, com
    ganho e fades, atrasada até o instante em que entra; sem janelas, uma só cobrindo o vídeo
    inteiro. Devolve o rótulo da mistura das janelas. `music_duration` é obrigatória quando algum
    span usa `tail` (só assim dá para ancorar `start_at` no final da faixa).

    `grid` existe quando a música é esticada para o andamento do projeto (ver `domain.music_tempo`): a entrada ganha o atraso
    que põe o primeiro tempo dela num tempo da grade e, com `loop`, o arquivo esticado repete em tempos inteiros (o
    `aloop` do filtro no lugar do `-stream_loop` da entrada, que repetiria o arquivo no tamanho que ele tem). Sem `grid` o
    grafo é o de sempre, linha por linha."""
    spans = music.spans or [
        MusicSpan(
            start=0.0, end=None, start_at=music.start_at, fade_in=music.fade_in, fade_out=music.fade_out
        )
    ]
    if any(span.tail for span in spans) and music_duration is None:
        raise ValueError("música: span com tail=true precisa da duração da música (music_duration)")
    labels = []
    for k, span in enumerate(spans):
        start, span_end, start_at = resolve_span(span, total, music_duration)
        end = total if span_end is None else min(span_end, total)
        # a entrada atrasada até a batida da grade: a janela ganha o atraso e perde o mesmo tanto no fim
        entry = grid.entry_delay(start, start_at) if grid else 0.0
        length = max(end - start - entry, 0.0)
        in_grid_loop = grid is not None and music.loop and music_duration is not None
        pre = ["-stream_loop", "-1"] if music.loop and not in_grid_loop else []
        idx = inputs.add(music_path, *pre)
        if in_grid_loop:
            assert grid is not None and music_duration is not None
            head = [
                f"[{idx}:a]aresample=48000",
                "aformat=sample_fmts=fltp:channel_layouts=stereo",
                *_whole_beat_loop(grid, music_duration),
                f"atrim=start={start_at:.3f}:duration={length:.3f}",
                "asetpts=PTS-STARTPTS",
            ]
        else:
            head = [
                f"[{idx}:a]atrim=start={start_at:.3f}:duration={length:.3f}",
                "asetpts=PTS-STARTPTS",
                "aresample=48000",
                "aformat=sample_fmts=fltp:channel_layouts=stereo",
            ]
        chain = [
            *head,
            f"volume={music.volume:.3f}",
            *([balance] if (balance := pan_filter(music.pan)) else []),
        ]
        if span.fade_in:
            chain.append(f"afade=t=in:st=0:d={span.fade_in:.3f}")
        if span.fade_out:
            chain.append(f"afade=t=out:st={max(length - span.fade_out, 0):.3f}:d={span.fade_out:.3f}")
        if start + entry > 0:
            chain.append(f"adelay={int(round((start + entry) * 1000))}:all=1")
        label = f"[mus{k}]"
        lines.append(",".join(chain) + label)
        labels.append(label)
    if len(labels) == 1:
        return labels[0]
    lines.append(
        "".join(labels) + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0[mus]"
    )
    return "[mus]"


def _whole_beat_loop(grid: MusicGrid, stretched_duration: float) -> list[str]:
    """Os filtros que repetem a música esticada em tempos inteiros: o arquivo é aparado (ou completado com silêncio) até o
    número inteiro de tempos mais perto e repetido sem fim pelo `aloop`, que guarda um loop inteiro na memória (uns
    poucos segundos de áudio). Quando foi preciso aparar ou completar, a emenda leva um fade curto nas duas pontas."""
    length = grid.loop_length(stretched_duration)
    samples = int(round(length * 48000))
    filters = [f"atrim=duration={length:.6f}", f"apad=whole_dur={length:.6f}"]
    if grid.needs_seam_fade(stretched_duration):
        filters += [
            f"afade=t=in:d={SEAM_FADE_SECONDS:g}",
            f"afade=t=out:st={max(length - SEAM_FADE_SECONDS, 0):.6f}:d={SEAM_FADE_SECONDS:g}",
        ]
    filters.append(f"aloop=loop=-1:size={samples}:start=0")
    return filters
