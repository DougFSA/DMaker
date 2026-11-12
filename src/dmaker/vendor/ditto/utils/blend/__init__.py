import numpy as np


def blend_images_cy(mask_warped, frame_warped, frame_rgb, result):
    """DMaker: equivalente em numpy do blend em Cython do ditto, sem compilador C."""
    m = mask_warped[:, :, None]
    out = m * frame_warped + (1.0 - m) * frame_rgb
    result[:] = np.clip(out, 0, 255).astype(np.uint8)
