"""Troca as rosas vermelhas da placa floral por rosa e azul (as brancas ficam): cada rosa vermelha
(componente conexo de pixels vermelhos) vira rosa ou azul alternadamente, mantendo luz e sombra."""

from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

D = Path(__file__).parent
PINK_HUE, PINK_SAT = 335 / 360, 0.55
BLUE_HUE, BLUE_SAT = 215 / 360, 0.60


def rgb_to_hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    d = mx - mn + 1e-9
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) / 6
    s = np.where(mx > 0, (mx - mn) / (mx + 1e-9), 0)
    return h, s, mx


def hsv_to_rgb(h, s, v):
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    table = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)]
    out = np.zeros(h.shape + (3,), dtype=np.float32)
    for k, (rr, gg, bb) in enumerate(table):
        m = i == k
        out[m] = np.stack([rr[m], gg[m], bb[m]], axis=1)
    return out


def label_components(mask):
    """Rótulos de componentes conexos (8 vizinhos) numa máscara pequena, por busca em largura."""
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    current = 0
    for y0 in range(h):
        for x0 in range(w):
            if not mask[y0, x0] or labels[y0, x0]:
                continue
            current += 1
            labels[y0, x0] = current
            queue = deque([(y0, x0)])
            while queue:
                y, x = queue.popleft()
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not labels[ny, nx]:
                            labels[ny, nx] = current
                            queue.append((ny, nx))
    return labels, current


img = np.asarray(Image.open(D / "plate.png").convert("RGB")).astype(np.float32) / 255
h, s, v = rgb_to_hsv(img)
red = ((h < 0.06) | (h > 0.92)) & (s > 0.18) & (v > 0.12)  # inclui a borda desbotada das rosas
small = red[::4, ::4]
labels_small, n = label_components(small)
labels = np.kron(labels_small, np.ones((4, 4), dtype=np.int32))[: red.shape[0], : red.shape[1]]
sizes = np.bincount(labels_small.ravel())
print("rosas vermelhas encontradas:", n)
new_h, new_s = h.copy(), s.copy()
palette = [(PINK_HUE, PINK_SAT), (BLUE_HUE, BLUE_SAT)]
for k in range(1, n + 1):
    if sizes[k] < 6:  # respingos: tratam como rosa
        hue, sat = palette[0]
    else:
        hue, sat = palette[k % 2]
    m = red & (labels == k)
    new_h[m] = hue
    new_s[m] = s[m] * sat / 0.9  # rosas do desenho são muito saturadas; suaviza
out = hsv_to_rgb(new_h, np.clip(new_s, 0, 1), v)
# rosa fica um pouco mais claro, como rosa de verdade
Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8)).save(D / "plate_rosa_azul.png")
print("ok")
