"""Deslocar o som no tempo (Time Shift): onde ler a fonte quando o som anda em relação à imagem. Puro."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioWindow:
    """De onde sai o som de um trecho deslocado: `read_from` é o ponto da fonte (nunca negativo) em que a leitura
    começa e `lead` é o silêncio, em segundos de fonte, que vem antes dele quando o som pedido começa antes de o
    arquivo começar."""

    read_from: float
    lead: float


def shifted_window(in_point: float, speed: float, audio_offset: float) -> AudioWindow:
    """A janela de som de um trecho cuja imagem começa em `in_point` (segundos da fonte), com a velocidade `speed` e o
    som deslocado `audio_offset` segundos da linha do tempo (positivo atrasa o som). Atrasar o som é pegar um som mais
    antigo da fonte, e o deslocamento da linha do tempo vira `audio_offset * speed` segundos de fonte."""
    start = in_point - audio_offset * speed
    return AudioWindow(max(start, 0.0), max(-start, 0.0))
