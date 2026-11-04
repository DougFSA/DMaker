"""Contraste (Contrast): quanto a fala se destaca do fundo, em dB, com o critério de acessibilidade do Audacity.

A WCAG 1.4.7 pede que a fala fique pelo menos 20 dB acima do som de fundo, para quem ouve mal. Aqui o primeiro plano
e o fundo são dois trechos do mesmo sinal; a conferência de um vídeo inteiro (a voz contra a música) usa
`contrast_db`, a mesma conta, sobre as trilhas separadas (`pipeline/audio_checks.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

import numpy as np

from ...voice.levels import FRAME_SECONDS, active_frames, frame_rms
from ..registry import AnalysisResult, AnalyzerBase, param, register_analyzer
from ..signal import Signal, rms_db

# WCAG 1.4.7 (Low or No Background Audio): a fala pelo menos 20 dB acima do fundo
WCAG_CONTRAST_DB = 20.0


def contrast_db(foreground: np.ndarray, background: np.ndarray) -> float:
    """A diferença, em dB, entre o RMS do primeiro plano e o do fundo (todos os canais juntos)."""
    return rms_db(foreground) - rms_db(background)


# Um bloco de 1 s é a janela em que o contraste de uma fala é conferido, e só conta se tem pelo menos 0,2 s de fala.
BLOCK_SECONDS = 1.0
MIN_SPEECH_SECONDS = 0.2
# Abaixo disto o quadro é silêncio de gravação, não fala, ainda que seja o mais alto de um trecho quase mudo.
SPEECH_FLOOR_DB = -55.0
_POWER_FLOOR = 1e-14  # -140 dB: o fundo totalmente mudo não faz o contraste ir ao infinito
MAX_CONTRAST_DB = 100.0


@dataclass(frozen=True)
class SpeechContrast:
    """O contraste entre a fala e o fundo, nos trechos em que há fala: o geral, o do pior bloco de 1 s (com o instante
    em que ele começa) e quantos blocos ficaram abaixo do limite."""

    overall_db: float
    worst_db: float
    worst_at: float
    blocks: int
    blocks_below: int
    threshold_db: float

    @property
    def passes(self) -> bool:
        return self.worst_db >= self.threshold_db


def _power_db(power: float) -> float:
    return 10.0 * float(np.log10(max(power, _POWER_FLOOR)))


def speech_contrast(
    foreground: np.ndarray, background: np.ndarray, sample_rate: int, threshold_db: float = WCAG_CONTRAST_DB
) -> SpeechContrast | None:
    """A fala (`foreground`, mono) contra o fundo (`background`, mono) só nos quadros em que há fala: nas pausas a música
    sozinha não conta contra a voz. É a conta do QA do vídeo, sobre as trilhas separadas da mixagem. None quando não há
    fala (ou ela é mais curta que `MIN_SPEECH_SECONDS` em todo bloco)."""
    speech = frame_rms(foreground, sample_rate)
    levels = active_frames(speech)
    if levels is None:
        return None
    count = len(speech)
    behind = frame_rms(background[: count * int(sample_rate * FRAME_SECONDS)], sample_rate)
    if len(behind) < count:
        behind = np.pad(behind, (0, count - len(behind)))
    active = levels & (speech > 10.0 ** (SPEECH_FLOOR_DB / 20.0))
    if not active.any():
        return None
    per_block = int(round(BLOCK_SECONDS / FRAME_SECONDS))
    minimum = int(round(MIN_SPEECH_SECONDS / FRAME_SECONDS))
    contrasts: list[tuple[float, float]] = []
    for first in range(0, count, per_block):
        mask = active[first : first + per_block]
        if int(mask.sum()) < minimum:
            continue
        voice = float(np.mean(np.square(speech[first : first + per_block][mask])))
        under = float(np.mean(np.square(behind[first : first + per_block][mask])))
        contrasts.append((min(_power_db(voice) - _power_db(under), MAX_CONTRAST_DB), first * FRAME_SECONDS))
    if not contrasts:
        return None
    overall = _power_db(float(np.mean(np.square(speech[active])))) - _power_db(
        float(np.mean(np.square(behind[active])))
    )
    worst_db, worst_at = min(contrasts)
    below = sum(1 for value, _ in contrasts if value < threshold_db)
    return SpeechContrast(
        overall_db=round(min(overall, MAX_CONTRAST_DB), 3),
        worst_db=round(worst_db, 3),
        worst_at=round(worst_at, 3),
        blocks=len(contrasts),
        blocks_below=below,
        threshold_db=threshold_db,
    )


@dataclass(kw_only=True)
class ContrastResult(AnalysisResult):
    foreground_db: float
    background_db: float
    difference_db: float
    threshold_db: float
    passes: bool


@register_analyzer
class Contrast(AnalyzerBase):
    """Mede o RMS de um trecho de primeiro plano e de um de fundo e diz se a diferença chega ao limite."""

    type: Literal["contrast"] = "contrast"
    label: ClassVar[str] = "Contraste"
    audacity_name: ClassVar[str] = "Contrast"
    summary: ClassVar[str] = (
        "Mede a diferença de nível, em dB, entre a fala (primeiro plano) e o fundo, e confere o critério de "
        "20 dB de acessibilidade."
    )

    foreground_start: float | None = param(
        None, label="Início do primeiro plano", unit="s", hint="Onde a fala começa.", ge=0
    )
    foreground_end: float | None = param(
        None, label="Fim do primeiro plano", unit="s", hint="Onde a fala termina.", ge=0
    )
    background_start: float | None = param(
        None, label="Início do fundo", unit="s", hint="Onde um trecho só com o fundo começa.", ge=0
    )
    background_end: float | None = param(
        None, label="Fim do fundo", unit="s", hint="Onde o trecho só com o fundo termina.", ge=0
    )
    threshold_db: float = param(
        WCAG_CONTRAST_DB,
        label="Diferença mínima",
        unit="dB",
        hint="A fala tem que ficar pelo menos tantos dB acima do fundo (WCAG 1.4.7: 20 dB).",
        ge=0.0,
        le=120.0,
    )

    def analyze(self, signal: Signal) -> ContrastResult:
        missing = [
            name
            for name in ("foreground_start", "foreground_end", "background_start", "background_end")
            if getattr(self, name) is None
        ]
        if missing:
            raise ValueError("o contraste compara dois trechos do mesmo som: informe " + ", ".join(missing))
        assert self.foreground_start is not None and self.foreground_end is not None
        assert self.background_start is not None and self.background_end is not None
        foreground = signal.slice(self.foreground_start, self.foreground_end).samples
        background = signal.slice(self.background_start, self.background_end).samples
        if foreground.size == 0:
            raise ValueError("o trecho do primeiro plano está fora do som ou vazio")
        if background.size == 0:
            raise ValueError("o trecho do fundo está fora do som ou vazio")
        foreground_level, background_level = rms_db(foreground), rms_db(background)
        difference = foreground_level - background_level
        passes = difference >= self.threshold_db
        verdict = (
            f"passa: a fala está {difference:.1f} dB acima do fundo (mínimo {self.threshold_db:g} dB)"
            if passes
            else f"reprova: a fala está só {difference:.1f} dB acima do fundo (mínimo {self.threshold_db:g} dB)"
        )
        result = ContrastResult(
            analyzer=self.type,
            summary=f"Contraste de {difference:.1f} dB: {verdict}.",
            foreground_db=round(foreground_level, 3),
            background_db=round(background_level, 3),
            difference_db=round(difference, 3),
            threshold_db=self.threshold_db,
            passes=passes,
        )
        if not passes:
            result.warnings.append(
                f"o fundo atrapalha quem ouve mal: abaixe-o em pelo menos {self.threshold_db - difference:.1f} dB "
                "ou suba a voz."
            )
        return result
