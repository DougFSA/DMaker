"""Os parâmetros que dão forma à sala do Reverb e o tempo de reverberação que eles pedem.

São contas puras, sem arquivo nem ffmpeg: a classe do efeito (`domain/audio_effects/delay_reverb.py`) as usa para dizer quanto
dura a cauda, e a geração da resposta ao impulso (`media/reverb.py`) as usa para afinar os pentes.
"""

from __future__ import annotations

from dataclasses import dataclass

# O RT60 (queda de 60 dB) que o tamanho da sala dá, em segundos: de um banheiro (0,15 s) a uma catedral (1,35 s). A
# reverberância o multiplica por 10^((r-50)/100*1.3): de 0,2x em 0% a 4,5x em 100%
ROOM_T60_BASE = 0.15
ROOM_T60_SPAN = 1.2
REVERBERANCE_OCTAVES = 1.3
MAX_T60 = 8.0  # acima disto a resposta passaria de 11 s e não cabe com folga no cache nem no `afir`


def reverb_time(room_size: float, reverberance: float) -> float:
    """O RT60 alvo, em segundos: o tempo que o som leva para cair 60 dB."""
    base = ROOM_T60_BASE + ROOM_T60_SPAN * room_size / 100.0
    scale = 10.0 ** ((reverberance - 50.0) / 100.0 * REVERBERANCE_OCTAVES)
    return min(base * scale, MAX_T60)


@dataclass(frozen=True)
class ReverbSettings:
    """O que decide a resposta ao impulso: os parâmetros do Reverb que dão forma à sala (o seco, o "só molhado" e a
    cauda ficam de fora, porque são do grafo, não da resposta). Dois efeitos com os mesmos valores dividem o arquivo."""

    room_size: float = 75.0
    pre_delay_ms: float = 10.0
    reverberance: float = 50.0
    damping: float = 50.0
    tone_low: float = 100.0
    tone_high: float = 100.0
    wet_db: float = -1.0
    stereo_width: float = 100.0

    def reverb_time(self) -> float:
        return reverb_time(self.room_size, self.reverberance)

    def tail_seconds(self) -> float:
        """Quanto o som molhado ainda dura depois que o seco acaba: o pré-atraso mais o RT60 (60 dB de queda)."""
        return self.pre_delay_ms / 1000.0 + self.reverb_time()
