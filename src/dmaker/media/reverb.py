"""A resposta ao impulso do Reverb, gerada por conta própria no estilo Freeverb (domínio público).

O Freeverb é linear e invariante no tempo: oito pentes com amortecimento em paralelo, seguidos de quatro passa-tudo. Por isso
o som que ele dá a um sinal qualquer é a convolução do sinal com a resposta dele a um clique. Aqui se calcula essa resposta
uma vez por conjunto de parâmetros (no domínio da frequência, sem laço por amostra) e o `afir` do ffmpeg faz a convolução,
que é rápida. Nenhuma resposta ao impulso de terceiros entra: as afinações abaixo são as do Freeverb e o resto é conta.

Mapeamento dos parâmetros do Audacity (que não são os do Freeverb):

- Tamanho da sala e reverberância decidem o tempo de reverberação (RT60): a sala dá a base (de 0,15 s a 1,35 s) e a
  reverberância a multiplica (de 0,2x em 0% a 4,5x em 100%). Cada pente recebe a realimentação que dá aquele RT60 sozinho.
- O tamanho da sala também estica os atrasos dos pentes (de 0,3x a 1,7x), que é o "espaço" que se ouve.
- Amortecimento é o passa-baixa dentro de cada pente: os agudos morrem antes dos graves.
- Tom grave e tom agudo são prateleiras (as do EQ, `analysis.iir`) aplicadas à resposta inteira.
- Largura estéreo mistura os dois lados do reverb (0%: o mesmo reverb nos dois; 100%: lados independentes).
- O ganho molhado é medido em energia: 0 dB dá ao som molhado a mesma potência do seco para um ruído, qualquer que seja a sala.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .. import config
from ..analysis.iir import high_shelf, low_shelf, response
from ..domain.reverb import ReverbSettings
from .wavio import write_wav_float

RATE = 48000
REVERB_VERSION = "ir1"  # muda quando a receita da resposta muda (invalida o cache dela)

# As afinações do Freeverb original, em amostras a 44,1 kHz (a do lado direito leva o espalhamento a mais)
FREEVERB_RATE = 44100
COMB_TUNINGS = (1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617)
ALLPASS_TUNINGS = (556, 441, 341, 225)
STEREO_SPREAD = 23
ALLPASS_GAIN = 0.5  # a realimentação dos passa-tudo (a do Freeverb)
# O passa-baixa dentro do pente: a 100% de amortecimento o polo fica em 0,5, e o agudo no Nyquist perde mais de dois terços
# do ganho a cada volta
DAMPING_POLE = 0.5
DELAY_SCALE_MIN = 0.3
DELAY_SCALE_SPAN = 1.4
# A queda dos tons grave e agudo quando o controle vai a 0% (prateleiras em 400 Hz e 4 kHz)
TONE_CUT_DB = 24.0
TONE_LOW_HZ = 400.0
TONE_HIGH_HZ = 4000.0
# A resposta é guardada até onde ela cai 84 dB (1,4 RT60): o resto está abaixo de qualquer som audível, e o corte leva
# uma rampa para não deixar degrau
TAIL_T60S = 1.4
FADE_FRACTION = 0.1
# Para a conta no domínio da frequência não dobrar a cauda sobre o começo (aliasing no tempo), a grade tem 2,2 RT60
GRID_T60S = 2.2


def _spectrum_grid(length: int) -> tuple[int, np.ndarray]:
    size = 1 << max(int(length) - 1, 1).bit_length()
    omega = 2.0 * math.pi * np.arange(size // 2 + 1) / size
    return size, omega


def _comb_response(omega: np.ndarray, delay: int, feedback: float, pole: float) -> np.ndarray:
    """O pente com amortecimento do Freeverb: `z^-D (1 - p z^-1) / (1 - p z^-1 - fb (1 - p) z^-D)`, `p` o polo do passa-baixa."""
    u = np.exp(-1j * omega)
    u_delay = np.exp(-1j * omega * delay)
    return u_delay * (1.0 - pole * u) / (1.0 - pole * u - feedback * (1.0 - pole) * u_delay)


def _allpass_response(omega: np.ndarray, delay: int) -> np.ndarray:
    """O passa-tudo de Schroeder `(-g + z^-D) / (1 - g z^-D)`: módulo 1 em toda frequência."""
    u_delay = np.exp(-1j * omega * delay)
    return (-ALLPASS_GAIN + u_delay) / (1.0 - ALLPASS_GAIN * u_delay)


def _side_response(
    omega: np.ndarray, rate: int, scale: float, t60: float, pole: float, spread: int
) -> np.ndarray:
    """A resposta de um lado do Freeverb: os oito pentes somados, depois os quatro passa-tudo em série."""
    total = np.zeros_like(omega, dtype=np.complex128)
    for tuning in COMB_TUNINGS:
        delay = max(round((tuning + spread) * rate / FREEVERB_RATE * scale), 2)
        feedback = 10.0 ** (-3.0 * delay / (rate * t60))  # sozinho, este pente cai 60 dB em `t60` segundos
        total += _comb_response(omega, delay, feedback, pole)
    for tuning in ALLPASS_TUNINGS:
        delay = max(round((tuning + spread) * rate / FREEVERB_RATE * scale), 2)
        total *= _allpass_response(omega, delay)
    return total


def _tone_response(omega: np.ndarray, rate: int, tone_low: float, tone_high: float) -> np.ndarray:
    """A resposta das duas prateleiras de tom; 100% é plano. Em 0% a prateleira corta `TONE_CUT_DB`."""
    hz = omega * rate / (2.0 * math.pi)
    sections = []
    if tone_low < 100.0:
        sections.append(low_shelf(TONE_LOW_HZ, -TONE_CUT_DB * (1.0 - tone_low / 100.0), 1.0, rate))
    if tone_high < 100.0:
        sections.append(high_shelf(TONE_HIGH_HZ, -TONE_CUT_DB * (1.0 - tone_high / 100.0), 1.0, rate))
    return response(sections, hz, rate) if sections else np.ones_like(omega, dtype=np.complex128)


def impulse_response(settings: ReverbSettings, rate: int = RATE) -> np.ndarray:
    """A resposta do Reverb a um clique, `(amostras, 2)` em ponto flutuante de 32 bits, já com o pré-atraso, o tom, a
    largura e o ganho molhado. É só a parte molhada: o seco o `afir` não entra, quem mistura é o grafo do efeito."""
    t60 = settings.reverb_time()
    scale = DELAY_SCALE_MIN + DELAY_SCALE_SPAN * settings.room_size / 100.0
    pole = DAMPING_POLE * settings.damping / 100.0
    keep = math.ceil(TAIL_T60S * t60 * rate)
    size, omega = _spectrum_grid(math.ceil(GRID_T60S * t60 * rate) + 8192)
    left = _side_response(omega, rate, scale, t60, pole, 0)
    right = _side_response(omega, rate, scale, t60, pole, STEREO_SPREAD)
    near = (1.0 + settings.stereo_width / 100.0) / 2.0
    far = 1.0 - near
    both = np.stack([near * left + far * right, near * right + far * left], axis=1)
    # a energia é medida antes do tom: os controles de tom só tiram (um reverb escuro é mais baixo, não mais alto)
    unit = float(np.mean(np.sum(np.fft.irfft(both, n=size, axis=0) ** 2, axis=0)))
    tone = _tone_response(omega, rate, settings.tone_low, settings.tone_high)
    impulse = np.fft.irfft(both * tone[:, None], n=size, axis=0)[:keep]
    fade = max(int(keep * FADE_FRACTION), 1)
    impulse[-fade:] *= np.cos(np.linspace(0.0, math.pi / 2.0, fade))[:, None] ** 2
    impulse *= 10.0 ** (settings.wet_db / 20.0) / math.sqrt(max(unit, 1e-30))
    lead = round(settings.pre_delay_ms / 1000.0 * rate)
    if lead:
        impulse = np.vstack([np.zeros((lead, 2)), impulse])
    return impulse.astype(np.float32)


# ---------- o arquivo em cache ----------


def impulse_path(settings: ReverbSettings, rate: int = RATE) -> Path:
    """Onde mora o WAV da resposta: o nome é o hash dos parâmetros e da versão da receita, então dois efeitos iguais (e a
    prévia e o render) dividem o mesmo arquivo, e mudar a receita (`REVERB_VERSION`) o recalcula. Lê o `config` na hora."""
    payload = json.dumps([REVERB_VERSION, rate, asdict(settings)], sort_keys=True)
    return config.REVERB_IR_DIR / f"{hashlib.sha1(payload.encode()).hexdigest()[:20]}.wav"


def ensure_impulse(settings: ReverbSettings, rate: int = RATE) -> Path:
    """O WAV da resposta ao impulso, criado se ainda não está no cache (uns 0,1 s a 3,5 s de conta, uma vez só). Grava num
    arquivo temporário e renomeia, para um render ao lado nunca ler o arquivo pela metade."""
    path = impulse_path(settings, rate)
    if path.exists():
        return path
    staging = path.with_name(f"{path.stem}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}{path.suffix}")
    try:
        write_wav_float(staging, impulse_response(settings, rate), rate)
        staging.replace(path)
    finally:
        staging.unlink(missing_ok=True)
    return path
