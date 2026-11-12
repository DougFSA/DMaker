"""O ditto de verdade: uma foto e 1 s de fala viram quadros, duas vezes com a mesma semente (a diferença é medida).

Leva uns 5 minutos (preparo fixo de uns 2 minutos por clipe, duas vezes) e por isso fica FORA do pytest padrão, pelo
marcador `ditto`. Para rodar:

    set DMAKER_DITTO_MODELS=<clone>/cache/models   (a pasta com `persona-realista/`)
    set DMAKER_DITTO_PHOTO=<pasta>/foto.jpg        (uma foto de rosto, de uso livre)
    set DMAKER_DITTO_AUDIO=<pasta>/fala.wav        (qualquer fala com 1 s ou mais)
    .venv/Scripts/python -m pytest -m ditto tests/test_ditto_real.py

Sem as três variáveis, o openvino ou os modelos, o teste pula.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.ditto

SIZE = (270, 480)
DURATION = 1.0


def _env_path(name: str) -> Path:
    value = os.environ.get(name)
    if not value or not Path(value).exists():
        pytest.skip(f"defina {name} (veja o topo deste arquivo)")
    return Path(value)


def test_two_renders_with_the_same_seed_give_the_same_frames_or_nearly(tmp_path):
    pytest.importorskip("openvino")
    pytest.importorskip("cv2")
    from dmaker.media.ditto_models import paths_in
    from dmaker.media.talking_head import DittoTalkingHead, TalkingHeadRequest
    from dmaker.persona.portrait import blaze_face_finder, prepare_photo

    models = _env_path("DMAKER_DITTO_MODELS")
    if paths_in(models).missing_files():
        pytest.skip("os modelos da persona realista não estão em DMAKER_DITTO_MODELS")
    import cv2

    prepared = prepare_photo(
        _env_path("DMAKER_DITTO_PHOTO"), SIZE, "full", blaze_face_finder(paths_in(models).face_detector)
    )
    photo = tmp_path / "foto.png"
    cv2.imwrite(str(photo), cv2.cvtColor(prepared.image, cv2.COLOR_RGB2BGR))
    head = DittoTalkingHead(models_dir=models, cache_dir=tmp_path / "ovcache")
    request = TalkingHeadRequest(photo, _env_path("DMAKER_DITTO_AUDIO"), DURATION, SIZE, seed=7, steps=15)

    def draw() -> np.ndarray:
        frames = head.frames(request, print, print)
        return np.stack([np.frombuffer(f, np.uint8).reshape(SIZE[1], SIZE[0], 3) for f in frames])

    first, second = draw(), draw()
    assert first.shape == second.shape == (25, SIZE[1], SIZE[0], 3)
    difference = np.abs(first.astype(int) - second.astype(int))
    print(
        f"diferença entre os dois renders: máxima {difference.max()}, média {difference.mean():.4f} (de 255)"
    )
    assert difference.mean() < 1.0  # quase igual; a GPU em f16 pode variar nos últimos bits
    assert first.std() > 5  # e é uma imagem de verdade, não um quadro liso
