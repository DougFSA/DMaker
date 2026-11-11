"""O Phaser e o Wahwah: a resposta do filtro em cada instante, para o filtro quadro a quadro de `media/stft_filter.py`.

Os dois são filtros cuja frequência de corte anda com um LFO lento (até 4 Hz). Em cada instante o filtro é fixo, e a resposta
dele sai de uma fórmula fechada, sem simular amostra por amostra:

- **Phaser:** uma cadeia de `estágios` passa-tudo de primeira ordem, cuja frequência de quebra o LFO varre em escala log. Misturada
  ao som original, cada par de estágios cava um entalhe que passeia pelo espectro. A realimentação (atraso de uma amostra) é a
  fórmula `A / (1 - f A z^-1)`.
- **Wahwah:** um passa-banda ressonante (RBJ, ganho de pico 0 dB) cujo centro o LFO varre em escala log entre `WAH_LOW_HZ` e
  `WAH_HIGH_HZ`; a ressonância é o Q.

O mapeamento dos controles do Audacity para estas fórmulas é nosso (o Audacity não o publica em valores): a faixa de cada
controle é a dele, e a conta está nas constantes abaixo.
"""

from __future__ import annotations

import numpy as np

from .stft_filter import bin_omega

# Phaser: o centro da varredura e a largura dela em oitavas quando a profundidade está no máximo (255). A 100 (o padrão) são
# 2,35 oitavas, de uns 300 Hz a 1,6 kHz: a região onde uma voz tem mais corpo
PHASER_CENTER_HZ = 700.0
PHASER_SWEEP_OCTAVES = 6.0
PHASER_DEPTH_MAX = 255.0
# A realimentação passa de -100% a 100% no Audacity; a fórmula só é estável abaixo de 1, e perto dele ressoa sem fim
MAX_FEEDBACK = 0.98
# Wahwah: o centro varre de 300 Hz a 2,5 kHz (a faixa de um pedal), em escala log
WAH_LOW_HZ = 300.0
WAH_HIGH_HZ = 2500.0


def lfo(times: np.ndarray, frequency_hz: float, phase_degrees: float) -> np.ndarray:
    """O LFO senoidal entre 0 e 1 nos instantes dados (0,5 em fase 0)."""
    return 0.5 * (1.0 + np.sin(2.0 * np.pi * frequency_hz * times + np.radians(phase_degrees)))


def phaser_response(
    times: np.ndarray,
    rate: int,
    stages: int,
    dry_wet: float,
    lfo_hz: float,
    phase_degrees: float,
    depth: float,
    feedback_percent: float,
) -> np.ndarray:
    """A resposta complexa do Phaser em cada quadro e em cada bin: `(1 - m) + m A^n / (1 - f A^n z^-1)`, com `m` a parte
    molhada, `n` os estágios, `f` a realimentação e `A` o passa-tudo `(a + z^-1) / (1 + a z^-1)` cuja frequência de quebra o LFO
    varre."""
    sweep = lfo(times, lfo_hz, phase_degrees)
    width = PHASER_SWEEP_OCTAVES * depth / PHASER_DEPTH_MAX
    break_hz = PHASER_CENTER_HZ * 2.0 ** ((sweep - 0.5) * width)
    k = np.tan(np.pi * np.minimum(break_hz, rate * 0.45) / rate)
    coefficient = ((k - 1.0) / (k + 1.0))[:, None]
    z = np.exp(-1j * bin_omega())[None, :]
    allpass = (coefficient + z) / (1.0 + coefficient * z)
    chain = allpass**stages
    feedback = float(np.clip(feedback_percent / 100.0, -MAX_FEEDBACK, MAX_FEEDBACK))
    wet = chain / (1.0 - feedback * chain * z)
    mix = dry_wet / 255.0
    return (1.0 - mix) + mix * wet


def wah_centers(
    times: np.ndarray, lfo_hz: float, phase_degrees: float, depth: float, offset: float
) -> np.ndarray:
    """O centro do filtro em Hz em cada instante. A posição na varredura é `offset + depth (1 - offset) lfo` (de 0 a 1), com
    `depth` e `offset` em fração: a profundidade só anda o que o deslocamento deixa."""
    position = offset + depth * (1.0 - offset) * lfo(times, lfo_hz, phase_degrees)
    return WAH_LOW_HZ * (WAH_HIGH_HZ / WAH_LOW_HZ) ** np.clip(position, 0.0, 1.0)


def wah_response(
    times: np.ndarray,
    rate: int,
    lfo_hz: float,
    phase_degrees: float,
    depth: float,
    resonance: float,
    offset: float,
) -> np.ndarray:
    """A resposta complexa do passa-banda ressonante em cada quadro e em cada bin: o RBJ de ganho de pico 0 dB,
    `α (1 - z^-2) / ((1 + α) - 2 cos(w0) z^-1 + (1 - α) z^-2)`, com `α = sin(w0) / 2Q` e `Q` a ressonância."""
    centers = wah_centers(times, lfo_hz, phase_degrees, depth, offset)
    w0 = 2.0 * np.pi * np.minimum(centers, rate * 0.45) / rate
    alpha = (np.sin(w0) / (2.0 * resonance))[:, None]
    cosine = np.cos(w0)[:, None]
    z = np.exp(-1j * bin_omega())[None, :]
    z2 = z * z
    return alpha * (1.0 - z2) / ((1.0 + alpha) - 2.0 * cosine * z + (1.0 - alpha) * z2)
