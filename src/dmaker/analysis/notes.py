"""De uma frequência à nota musical mais próxima (lá 4 = 440 Hz), para o cursor do gráfico do espectro."""

from __future__ import annotations

import math
from dataclasses import dataclass

A4_HZ = 440.0
# Os nomes em português (o "si" no lugar do "B"); a interface mostra a nota como o músico brasileiro a lê.
NOTE_NAMES = ("Dó", "Dó#", "Ré", "Ré#", "Mi", "Fá", "Fá#", "Sol", "Sol#", "Lá", "Lá#", "Si")
_A4_NUMBER = 69  # o número MIDI do lá 4


@dataclass(frozen=True)
class Note:
    """A nota mais próxima de uma frequência: o nome com a oitava ("Lá4"), quanto ela dista em cents (de -50 a
    +50) e a frequência exata dela."""

    name: str
    cents: float
    frequency: float

    def label(self) -> str:
        sign = "+" if self.cents >= 0 else "-"
        return f"{self.name} {sign}{abs(self.cents):.0f} cents"


def note_for(frequency: float, a4: float = A4_HZ) -> Note | None:
    """A nota mais próxima de `frequency` Hz, ou None quando a frequência não é positiva (o DC não tem nota)."""
    if not frequency > 0 or not a4 > 0:
        return None
    exact = _A4_NUMBER + 12.0 * math.log2(frequency / a4)
    number = round(exact)
    octave, index = divmod(number, 12)
    nearest = a4 * 2.0 ** ((number - _A4_NUMBER) / 12.0)
    return Note(f"{NOTE_NAMES[index]}{octave - 1}", (exact - number) * 100.0, nearest)
