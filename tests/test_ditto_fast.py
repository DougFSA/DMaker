"""O caminho rápido do ditto: a escolha do dispositivo, as opções do OpenVINO, os parâmetros guardados em código e a
semente (sem rodar modelo nenhum)."""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest

from dmaker.media.ditto_fast import Accelerator, choose_accelerator, compile_options

pytest.importorskip("cv2")  # o ditto_sdk importa o código vendorizado, que usa OpenCV e onnxruntime
sdk = pytest.importorskip("dmaker.media.ditto_sdk")


def test_a_gpu_runs_in_f16_and_without_one_the_cpu_runs_in_f32():
    assert choose_accelerator(["CPU", "GPU"]) == Accelerator("GPU", "f16")
    assert choose_accelerator(["CPU"]) == Accelerator("CPU", "f32")
    assert "GPU integrada (f16)" == choose_accelerator(["GPU"]).describe
    assert choose_accelerator([]).describe == "CPU (f32)"


def test_the_openvino_options_pin_latency_the_cache_folder_and_the_precision(tmp_path):
    options = compile_options(Accelerator("GPU", "f16"), tmp_path / "ovcache")
    assert options == {
        "PERFORMANCE_HINT": "LATENCY",
        "CACHE_DIR": str(tmp_path / "ovcache"),
        "INFERENCE_PRECISION_HINT": "f16",
    }
    assert compile_options(Accelerator("CPU", "f32"), tmp_path)["INFERENCE_PRECISION_HINT"] == "f32"


def test_the_defaults_come_from_the_npz_without_pickle_and_have_the_shapes_the_model_expects():
    defaults = sdk.DittoDefaults.load()
    assert defaults.emotion.shape == (600, 8)
    assert defaults.motion_limits.shape == (4, 265)
    assert defaults.eye_blink_deltas.shape == (15, 63)
    condition = defaults.condition_info
    assert condition["sc"].shape == (63,)
    assert condition["eye_open_lst"][0].shape == (1, 2) and condition["eye_ball_lst"][0].shape == (1, 6)
    motion = condition["x_s_info_lst"][0]
    assert set(motion) == {"pitch", "yaw", "roll", "t", "exp", "scale", "kp"}
    assert motion["kp"].shape == (1, 63) and motion["pitch"].shape == (1, 66)


def test_the_npz_records_the_sha256_of_the_pickle_it_came_from():
    with np.load(sdk.DEFAULTS_FILE, allow_pickle=False) as data:
        assert (
            str(data["origem_sha256"]) == "be6729ca19e25269c4447d8ff4062e18de053b0f6dd38fdb6ef8166de6e8f3e3"
        )
    notice = (Path(sdk.DEFAULTS_FILE).parent / "NOTICE").read_text(encoding="utf-8")
    assert "be6729ca19e25269c4447d8ff4062e18de053b0f6dd38fdb6ef8166de6e8f3e3" in notice
    assert "c3e47ee" in notice and (Path(sdk.DEFAULTS_FILE).parent / "LICENSE").is_file()


def test_the_seed_fixes_the_diffusion_noise_and_the_blink_timing():
    sdk.seed_everything(7)
    first = (np.random.randn(3), random.randint(0, 10_000))
    sdk.seed_everything(7)
    again = (np.random.randn(3), random.randint(0, 10_000))
    sdk.seed_everything(8)
    other = np.random.randn(3)
    assert np.array_equal(first[0], again[0]) and first[1] == again[1]
    assert not np.array_equal(first[0], other)


def test_the_vendored_code_does_not_load_a_pickle_or_name_removed_dependencies():
    root = Path(sdk.DEFAULTS_FILE).parent
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "pickle" not in text, path
        assert "import insightface" not in text and "from core." not in text, path
