"""Efeitos sonoros na mixagem: nível em relação à voz e uma entrada atrasada ao instante exato de cada um."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from .common import LOUDNORM_TRUE_PEAK_DB, Inputs

MIX_RATE = 48_000  # a taxa da mixagem: o atraso em amostras só é exato nela
# Pico de um som da biblioteca antes de qualquer ganho (ver `sfx.synth.PEAK_DBFS`); é daqui que sai a conta do nível.
LIBRARY_PEAK_DB = -3.0
# Com `volume` 1 o pico do efeito fica 6 dB abaixo do pico da voz. Um efeito é curto (um pop dura 0,16 s) e o
# ouvido soma a energia em ~200 ms, então ele soa mais baixo que o pico indica: 6 dB deixa o pop e o clique
# audíveis sem cobrir a fala. O `volume` da spec vai até 1,5 (+3,5 dB), e aí ainda sobram 2,5 dB sob a voz.
BELOW_VOICE_DB = 6.0
# Pico da voz que se supõe quando não dá para medir (simulação, vídeo sem fala): o de uma fala bem gravada.
FALLBACK_VOICE_PEAK_DB = -6.0


class SfxInput(Protocol):
    """O que a mixagem precisa de um efeito (satisfeito por `SfxTrack`, do pipeline)."""

    path: Path
    at: float
    gain_db: float


def voice_reference_db(voice_loudness: float, voice_true_peak: float, target_lufs: float | None) -> float:
    """Pico da voz (dBFS, na escala de antes do loudnorm) a partir do qual se mede o nível dos efeitos.

    O loudnorm final soma um ganho único `target - loudness` a tudo, o que preserva a distância entre o
    efeito e a voz, MAS limita o pico em `LOUDNORM_TRUE_PEAK_DB`: voz com pico alto demais para esse ganho
    é achatada, e um efeito mais baixo passa inteiro. Então a régua é o pico que a voz terá na saída, que é
    o menor entre o pico medido e o teto menos o ganho (vale a mesma conta para a normalização rápida).
    Sem normalização (`target_lufs` None) não há ganho nem limite e vale o pico medido. A música soma um
    pouco de volume ao loudnorm real, o que deixa o ganho verdadeiro um pouco menor que o daqui: o erro
    é para o lado seguro, os efeitos saem um tanto mais baixos, nunca mais altos.
    """
    if target_lufs is None:
        return voice_true_peak
    gain = target_lufs - voice_loudness
    return min(voice_true_peak, LOUDNORM_TRUE_PEAK_DB - gain)


def sfx_gain_db(volume: float, reference_db: float) -> float:
    """Ganho (dB) que leva um som de pico `LIBRARY_PEAK_DB` a `BELOW_VOICE_DB` abaixo do pico de referência
    da voz (`voice_reference_db`), com o `volume` da spec por cima (1 = esse nível)."""
    return (reference_db - BELOW_VOICE_DB - LIBRARY_PEAK_DB) + 20.0 * math.log10(volume)


def delay_samples(at: float) -> int:
    """Instante em amostras da mixagem: o atraso em amostras dispensa a conversão de milissegundos do filtro
    e dá o instante na resolução de uma amostra (0,02 ms a 48 kHz)."""
    return int(round(at * MIX_RATE))


def sfx_streams(lines: list[str], inputs: Inputs, sfx: Sequence[SfxInput]) -> list[str]:
    """Uma entrada por efeito, em 48 kHz estéreo (como o resto da mixagem), com o ganho de nível e atrasada
    até o instante em que toca. Devolve os rótulos para somar ao barramento."""
    labels = []
    for index, item in enumerate(sfx):
        chain = [
            f"[{inputs.add(item.path)}:a]aresample={MIX_RATE}",
            "aformat=sample_fmts=fltp:channel_layouts=stereo",
            f"volume={item.gain_db:.2f}dB",
        ]
        delay = delay_samples(item.at)
        if delay > 0:
            chain.append(f"adelay={delay}S:all=1")
        label = f"[sfx{index}]"
        lines.append(",".join(chain) + label)
        labels.append(label)
    return labels
