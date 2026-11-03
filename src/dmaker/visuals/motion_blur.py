"""Borrão de movimento por subquadros: em que instantes capturar e como juntar os subquadros num só.

O DMaker não borra a imagem depois: ele deixa a composição andar entre vários instantes dentro do tempo em que o
"obturador" de uma câmera ficaria aberto e tira a média, que é o que borra o que se move rápido e deixa nítido o que
está parado. As duas contas são puras, sem navegador nem disco.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence

import numpy as np


def blur_sample_times(
    frame_times: Sequence[float], fps: float, subframes: int, shutter: float
) -> list[float]:
    """Os instantes a capturar, `subframes` por quadro, na ordem.

    O obturador dura `shutter` do intervalo entre quadros (0,5 é o de 180 graus do cinema) e fica centrado no
    instante do quadro; cada subquadro cai no meio de uma fatia igual dele. Antes do instante 0 a composição
    ainda não existe, então os instantes que cairiam ali ficam em 0 (o primeiro quadro borra menos)."""
    window = shutter / fps
    offsets = [((index + 0.5) / subframes - 0.5) * window for index in range(subframes)]
    return [max(moment + offset, 0.0) for moment in frame_times for offset in offsets]


def blend_premultiplied(frames: Sequence[np.ndarray]) -> np.ndarray:
    """Média de quadros RGBA (alfa direto, uint8) feita em alfa pré-multiplicado.

    Tirar a média das cores diretas pintaria de escuro a borda de um objeto que atravessa um pedaço transparente
    (o transparente é preto no arquivo). A conta certa é pesar a cor de cada quadro pelo alfa dele: a cor final é
    a soma de `cor x alfa` dividida pela soma dos alfas, e o alfa final é a média dos alfas."""
    if len(frames) == 1:
        return frames[0]
    weighted = np.zeros(frames[0].shape[:2] + (3,), np.float32)
    alpha_sum = np.zeros(frames[0].shape[:2], np.float32)
    for frame in frames:
        alpha = frame[..., 3].astype(np.float32)
        weighted += frame[..., :3].astype(np.float32) * alpha[..., None]
        alpha_sum += alpha
    out = np.zeros(frames[0].shape, np.uint8)
    covered = alpha_sum > 0
    out[..., :3][covered] = np.rint(weighted[covered] / alpha_sum[covered][:, None]).astype(np.uint8)
    out[..., 3] = np.rint(alpha_sum / len(frames)).astype(np.uint8)
    return out


def blend_stream(raw_frames: Iterable[bytes], subframes: int, size: tuple[int, int]) -> Iterator[bytes]:
    """Junta os quadros crus (RGBA, `size` = largura x altura) de `subframes` em `subframes`, um por quadro final.
    Sobra de menos que `subframes` no fim (uma captura que falhou) é descartada: não há quadro inteiro nela."""
    width, height = size
    group: list[np.ndarray] = []
    for chunk in raw_frames:
        group.append(np.frombuffer(chunk, np.uint8).reshape(height, width, 4))
        if len(group) == subframes:
            yield blend_premultiplied(group).tobytes()
            group = []
