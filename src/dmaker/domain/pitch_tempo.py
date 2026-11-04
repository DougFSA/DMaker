"""Contas puras de tempo e afinação: razões de tom, de velocidade e de andamento, e o plano do Esticar Gradualmente.

Nada aqui executa ffmpeg nem toca disco: a classe do efeito escolhe a razão pela unidade que a pessoa usou
(semitons, nota para nota, porcentagem, RPM, BPM, duração) e o construtor do filtro só aplica o número. As mesmas contas
alimentam a duração de saída, para a linha do tempo, a validação e o render concordarem.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# As doze notas da escala cromática com sustenido (a nota 0 do oitavo grau é o dó). O nome é o que o Audacity mostra.
NOTE_NAMES: tuple[str, ...] = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
# A4 = 440 Hz é a referência de afinação (a nota 69 do padrão MIDI, onde o dó central é a 60)
A4_FREQUENCY = 440.0
A4_NUMBER = 69
SEMITONES_PER_OCTAVE = 12

# Quanto o tom pode andar para cada lado, em semitons (quatro oitavas): o `rubberband` aceita razões de 0,01 a 100, mas
# além disso a voz já não é reconhecível e a conta de nota para nota passaria dos limites do filtro
MAX_PITCH_SEMITONES = 48.0

# A razão de velocidade ou de andamento fica entre estes limites: dez vezes mais lento a dez vezes mais rápido
MIN_TIME_RATIO = 0.1
MAX_TIME_RATIO = 10.0


def semitone_ratio(semitones: float) -> float:
    """A razão de frequência de `semitones` semitons (12 semitons dobram a frequência)."""
    return 2.0 ** (semitones / SEMITONES_PER_OCTAVE)


def percent_ratio(percent: float) -> float:
    """A razão de uma mudança em porcentagem: +50 vale 1,5 vez e -50 vale metade."""
    return 1.0 + percent / 100.0


def note_number(name: str, octave: int) -> int:
    """O número MIDI de uma nota (`A`, 4 -> 69). O oitavo grau começa no dó, como no Audacity."""
    return (octave + 1) * SEMITONES_PER_OCTAVE + NOTE_NAMES.index(name)


def note_frequency(name: str, octave: int) -> float:
    """A frequência de uma nota em hertz, na afinação de A4 = 440 Hz."""
    return A4_FREQUENCY * semitone_ratio(note_number(name, octave) - A4_NUMBER)


def note_to_note_semitones(from_note: str, from_octave: int, to_note: str, to_octave: int) -> float:
    """Quantos semitons há da primeira nota à segunda (negativo quando a segunda é mais grave)."""
    return float(note_number(to_note, to_octave) - note_number(from_note, from_octave))


def bpm_ratio(bpm_from: float, bpm_to: float) -> float:
    """A razão de andamento para levar uma música de `bpm_from` a `bpm_to`: de 120 a 128 BPM ela toca 128/120 vez mais
    depressa e, por isso, dura 120/128 do que durava."""
    return bpm_to / bpm_from


def length_ratio(length_from: float, length_to: float) -> float:
    """A razão de andamento para um trecho de `length_from` segundos passar a durar `length_to`."""
    return length_from / length_to


def rpm_ratio(rpm_from: float, rpm_to: float) -> float:
    """A razão de velocidade de um disco gravado a `rpm_from` rotações por minuto e tocado a `rpm_to` (de 45 a 33⅓, o disco
    gira 0,74 vez mais devagar: o tom e a velocidade baixam juntos)."""
    return rpm_to / rpm_from


def resample_rate(ratio: float, sample_rate: int) -> int:
    """A taxa que o `asetrate` recebe para tocar o som `ratio` vez mais depressa. O filtro só aceita taxa inteira, então a
    razão que vale de fato é `resample_rate / sample_rate`: a duração de saída usa essa, e não a pedida."""
    return max(1, round(sample_rate * ratio))


def effective_ratio(ratio: float, sample_rate: int) -> float:
    """A razão de velocidade que o `asetrate` entrega depois de arredondar a taxa para um inteiro."""
    return resample_rate(ratio, sample_rate) / sample_rate


# ---------- Esticar Gradualmente ----------

# Um comando de andamento e tom a cada 50 ms, no máximo 120: um trecho de minutos não pode estourar a linha de comando do
# ffmpeg, e degraus tão pequenos a cada 50 ms o `rubberband` suaviza sozinho (medido: sem estalo)
SLIDING_STEP_SECONDS = 0.05
SLIDING_MAX_STEPS = 120
SLIDING_MIN_STEPS = 8


@dataclass(frozen=True)
class SlidingStep:
    """Um degrau do Esticar Gradualmente: de `at` por `span` segundos do sinal que entra, andamento e tom constantes."""

    at: float
    span: float
    tempo: float
    pitch: float


def sliding_steps(
    length: float, tempo_start: float, tempo_end: float, pitch_start: float, pitch_end: float
) -> list[SlidingStep]:
    """O trecho de `length` segundos em degraus iguais. O andamento (razão) varia em linha reta do início ao fim, e o
    tom varia em linha reta em semitons (a audição é logarítmica em frequência, então é assim que a subida soa
    uniforme). Cada degrau vale o ponto do meio dele. As entradas são razões de andamento e semitons de tom."""
    count = max(SLIDING_MIN_STEPS, min(SLIDING_MAX_STEPS, math.ceil(length / SLIDING_STEP_SECONDS)))
    span = length / count
    steps = []
    for index in range(count):
        middle = (index + 0.5) / count
        tempo = tempo_start + (tempo_end - tempo_start) * middle
        semitones = pitch_start + (pitch_end - pitch_start) * middle
        steps.append(SlidingStep(index * span, span, tempo, semitone_ratio(semitones)))
    return steps


def sliding_duration(steps: list[SlidingStep]) -> float:
    """Quanto dura a saída: cada degrau do sinal que entra dura `span / tempo` ao sair (a integral do andamento)."""
    return sum(step.span / step.tempo for step in steps)
