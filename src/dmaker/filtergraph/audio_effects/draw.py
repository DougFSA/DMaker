"""O construtor do efeito Desenhar (a classe está em `domain/audio_effects/draw.py`): função pura sobre as amostras.

Põe os valores desenhados nas amostras a partir do `start` do efeito, no canal pedido, e deixa o resto do sinal como veio.
Sem emenda: a Draw Tool do Audacity também substitui as amostras exatamente, e o que se quer ver no render é o que se
desenhou. Um som mono (uma coluna só) recebe o desenho na coluna única, qualquer que seja o canal pedido.
"""

from __future__ import annotations

import numpy as np

from ...domain.audio_effects.draw import Draw
from .registry import SampleRequest, register_sample_builder


@register_sample_builder("draw")
def build_draw(request: SampleRequest) -> np.ndarray:
    effect = request.effect
    assert isinstance(effect, Draw) and effect.start is not None
    first = round(effect.start * request.sample_rate)
    values = np.asarray(effect.values, dtype=np.float32)
    # o sinal que entra pode ser um arquivo mapeado só para leitura: o resultado é uma cópia, nunca o mesmo array
    result = np.array(request.samples, dtype=np.float32, copy=True)
    low, high = max(first, 0), min(first + len(values), len(result))
    if high <= low:
        return result
    channels = result.shape[1]
    columns = {"both": list(range(channels)), "left": [0], "right": [min(1, channels - 1)]}[effect.channel]
    result[low:high, columns] = values[low - first : high - first, None]
    return result
