"""Equilíbrio esquerda/direita (pan) de um item ou de um barramento de áudio: função pura, sem ffmpeg."""

from __future__ import annotations


def pan_gains(pan: float) -> tuple[float, float]:
    """O ganho (linear) de cada canal para um pan de -1 (tudo à esquerda) a 1 (tudo à direita). Como no Audacity, o
    lado para onde o som vai fica como está e o outro desce em linha reta até o silêncio no extremo: com -1 o
    canal direito zera, e com 0 os dois ficam como estavam."""
    return min(1.0, 1.0 - pan), min(1.0, 1.0 + pan)


def pan_filter(pan: float) -> str | None:
    """O filtro `pan` do ffmpeg para esse equilíbrio, ou None quando ele é neutro (não há o que filtrar). O som
    entra e sai estéreo: o filtro só atenua um canal, nunca mistura um no outro."""
    if not pan:
        return None
    left, right = pan_gains(pan)
    return f"pan=stereo|c0={left:.6f}*c0|c1={right:.6f}*c1"
