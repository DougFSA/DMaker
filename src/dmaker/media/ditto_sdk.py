"""O pipeline do ditto em modo offline: foto e áudio viram quadros, com o warp e o decoder injetados.

É o `StreamSDK` do ditto sem o que o DMaker não usa (modo em tempo real, vídeo como fonte, escrita por imageio) e
com duas diferenças: o warp e o decoder entram prontos (o caminho rápido de `ditto_fast.py`, sem remendar o módulo
do ditto em tempo de execução) e cada quadro pronto vai para uma função, em vez de para um arquivo. Os parâmetros
que o ditto guardava num pickle (`v0.4_hubert_cfg_trt.pkl`) estão aqui como constantes e no `default_kwargs.npz`.

O trabalho corre em seis estágios encadeados por filas, cada um numa thread, como no original: movimento a partir do
áudio (difusão), costura, warp, decoder, colagem no quadro e entrega. A GPU calcula o warp e o decoder enquanto a CPU
faz o resto do quadro seguinte, e é isso que dá o tempo por quadro medido.
"""

from __future__ import annotations

import queue
import random
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..vendor.ditto.atomic_components.audio2motion import Audio2Motion
from ..vendor.ditto.atomic_components.avatar_registrar import AvatarRegistrar
from ..vendor.ditto.atomic_components.condition_handler import ConditionHandler, _mirror_index
from ..vendor.ditto.atomic_components.motion_stitch import MotionStitch
from ..vendor.ditto.atomic_components.putback import PutBack
from ..vendor.ditto.atomic_components.wav2feat import Wav2Feat
from .ditto_models import DittoPaths

DEFAULTS_FILE = Path(__file__).resolve().parent.parent / "vendor" / "ditto" / "default_kwargs.npz"

AUDIO_RATE = 16_000  # o hubert espera áudio a 16 kHz
QUEUE_SIZE = 16  # pouco: cada item de trás da fila é um quadro inteiro na memória
POLL_SECONDS = 1.0

# Os parâmetros do ditto v0.4 com hubert (valores de `default_kwargs` do pickle de origem). Só `steps` muda por pedido.
CROP_KWARGS = {"crop_scale": 2.3, "crop_vx_ratio": 0, "crop_vy_ratio": -0.125, "crop_flag_do_rot": True}
MAX_SIZE = 4096  # nunca reduz a foto: ela já vem no tamanho final do quadro
OVERLAP = 10
FIX_KP_COND = 1
FIX_KP_COND_DIM = [0, 202]
SMOOTH_DRIVING_KERNEL = 3
FADE_TYPE = "d0"
FADE_OUT_KEYS = ("exp",)
OVERALL_CTRL_INFO = {"delta_pitch": 2}  # inclina a cabeça um pouco para baixo, como o ditto faz por padrão
SEQUENCE_FRAMES = 80
MOTION_FEATURE_DIM = 265
AUDIO_FEATURE_DIM = 1103


@dataclass(frozen=True)
class DittoDefaults:
    """Os arrays do pickle de origem: emoção neutra, olhos, limites de movimento e o estado inicial da condição."""

    emotion: np.ndarray
    motion_limits: np.ndarray
    eye_blink_deltas: np.ndarray
    condition_info: dict[str, Any]

    @staticmethod
    def load(path: Path = DEFAULTS_FILE) -> DittoDefaults:
        with np.load(path, allow_pickle=False) as data:  # sem pickle: o arquivo é só arrays
            motion_keys = ("pitch", "yaw", "roll", "t", "exp", "scale", "kp")
            condition = {
                "x_s_info_lst": [{key: data[f"x_s_{key}"] for key in motion_keys}],
                "sc": data["sc"],
                "eye_open_lst": [data["eye_open"]],
                "eye_ball_lst": [data["eye_ball"]],
            }
            return DittoDefaults(
                emotion=data["emo"],
                motion_limits=data["v_min_max_for_clip"],
                eye_blink_deltas=data["delta_eye_arr"],
                condition_info=condition,
            )


def _onnx(path: Path) -> dict[str, Any]:
    return {"model_path": str(path), "device": "cpu"}


class DittoSdk:
    """Uma foto e a fala dela viram quadros RGB, entregues um a um a `on_frame(índice, quadro)`."""

    def __init__(
        self,
        paths: DittoPaths,
        warp: Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray],
        decoder: Callable[[np.ndarray], np.ndarray],
        defaults: DittoDefaults | None = None,
    ) -> None:
        self.defaults = defaults or DittoDefaults.load()
        self.avatar_registrar = AvatarRegistrar(
            landmark203_cfg=_onnx(paths.onnx("landmark203.onnx")),
            landmark478_cfg={
                "blaze_face_model_path": str(paths.onnx("blaze_face.onnx")),
                "face_mesh_model_path": str(paths.onnx("face_mesh.onnx")),
                "device": "cpu",
            },
            appearance_extractor_cfg=_onnx(paths.onnx("appearance_extractor.onnx")),
            motion_extractor_cfg=_onnx(paths.onnx("motion_extractor.onnx")),
        )
        self.condition_handler = ConditionHandler(
            use_emo=True, use_sc=True, use_eye_open=True, use_eye_ball=True, seq_frames=SEQUENCE_FRAMES
        )
        self.audio2motion = Audio2Motion(
            {
                **_onnx(paths.onnx("lmdm_v0.4_hubert.onnx")),
                "motion_feat_dim": MOTION_FEATURE_DIM,
                "audio_feat_dim": AUDIO_FEATURE_DIM,
                "seq_frames": SEQUENCE_FRAMES,
            }
        )
        self.motion_stitch = MotionStitch(_onnx(paths.onnx("stitch_network.onnx")))
        self.putback = PutBack()
        self.wav2feat = Wav2Feat(w2f_cfg=_onnx(paths.onnx("hubert.onnx")), w2f_type="hubert")
        self._warp = warp
        self._decoder = decoder
        self._error: Exception | None = None
        self._stop = threading.Event()
        self._source_info: dict[str, Any] = {}

    # ---------- preparo ----------

    def register_photo(self, photo: Path, steps: int) -> None:
        """Acha o rosto da foto e prepara tudo o que depende só dela. Chamar `np.random.seed` ANTES: o ruído da
        difusão é sorteado aqui e fica guardado, então uma semente tardia não faria efeito."""
        defaults = self.defaults
        source_info = self.avatar_registrar(str(photo), max_dim=MAX_SIZE, n_frames=-1, **CROP_KWARGS)
        self._source_info = source_info
        self.condition_handler.setup(
            source_info, defaults.emotion, eye_f0_mode=False, ch_info=defaults.condition_info
        )
        self.audio2motion.setup(
            self.condition_handler.x_s_info_0,
            overlap_v2=OVERLAP,
            fix_kp_cond=FIX_KP_COND,
            fix_kp_cond_dim=FIX_KP_COND_DIM,
            sampling_timesteps=steps,
            online_mode=False,
            v_min_max_for_clip=defaults.motion_limits,
            smo_k_d=SMOOTH_DRIVING_KERNEL,
        )
        self.motion_stitch.setup(
            N_d=-1,
            use_d_keys=None,
            relative_d=True,
            drive_eye=None,
            delta_eye_arr=defaults.eye_blink_deltas,
            delta_eye_open_n=0,
            fade_out_keys=FADE_OUT_KEYS,
            fade_type=FADE_TYPE,
            flag_stitching=True,
            is_image_flag=source_info["is_image_flag"],
            x_s_info=source_info["x_s_info_lst"][0],
            d0=None,
            ch_info=defaults.condition_info,
            overall_ctrl_info=OVERALL_CTRL_INFO,
        )

    def audio_features(self, audio_16k: np.ndarray) -> np.ndarray:
        return self.wav2feat.wav2feat(audio_16k)

    # ---------- geração ----------

    def generate(self, features: np.ndarray, on_frame: Callable[[int, np.ndarray], None]) -> None:
        """Roda os estágios até todos os quadros (`len(features)`) saírem por `on_frame`, em ordem."""
        frame_count = len(features)
        self.motion_stitch.set_Nd(frame_count)
        self._error = None
        self._stop.clear()
        to_stitch, to_warp, to_decode, to_putback, to_write = (
            queue.Queue(maxsize=QUEUE_SIZE) for _ in range(5)
        )
        written = 0

        def stitch(item: Any) -> Any:
            frame_index, motion, control = item
            source_motion = self._source_info["x_s_info_lst"][frame_index]
            source_keypoints, driving_keypoints = self.motion_stitch(source_motion, motion, **control)
            return [frame_index, source_keypoints, driving_keypoints]

        def warp(item: Any) -> Any:
            frame_index, source_keypoints, driving_keypoints = item
            features_3d = self._source_info["f_s_lst"][frame_index]
            return [frame_index, self._warp(features_3d, source_keypoints, driving_keypoints)]

        def decode(item: Any) -> Any:
            frame_index, warped = item
            prediction = self._decoder(warped)
            return [frame_index, np.transpose(prediction[0], [1, 2, 0]).clip(0, 1) * 255]

        def paste_back(item: Any) -> Any:
            frame_index, image = item
            photo = self._source_info["img_rgb_lst"][frame_index]
            return self.putback(photo, image, self._source_info["M_c2o_lst"][frame_index])

        def deliver(frame: Any) -> None:
            nonlocal written
            on_frame(written, frame)
            written += 1

        stages = [
            ("costura", to_stitch, to_warp, stitch),
            ("warp", to_warp, to_decode, warp),
            ("decoder", to_decode, to_putback, decode),
            ("colagem", to_putback, to_write, paste_back),
        ]
        threads = [
            threading.Thread(target=self._guarded, args=(self._motion, features, to_stitch), name="movimento")
        ]
        threads += [
            threading.Thread(target=self._guarded, args=(self._stage, inbox, outbox, work), name=name)
            for name, inbox, outbox, work in stages
        ]
        threads.append(
            threading.Thread(
                target=self._guarded, args=(self._stage, to_write, None, deliver), name="entrega"
            )
        )
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        if self._error is not None:
            raise self._error
        if written != frame_count:
            raise RuntimeError(f"O ditto entregou {written} quadros de {frame_count}.")

    def _guarded(self, target: Callable[..., None], *args: Any) -> None:
        """Um erro em qualquer estágio para todos eles e é levantado por `generate`, no thread que o chamou."""
        try:
            target(*args)
        except Exception as exc:  # noqa: BLE001 - guardado e reerguido por `generate`
            self._error = self._error or exc
            self._stop.set()

    def _put(self, outbox: queue.Queue, item: Any) -> bool:
        """Põe na fila sem travar para sempre se um estágio adiante já parou (falso: a geração foi interrompida)."""
        while not self._stop.is_set():
            try:
                outbox.put(item, timeout=POLL_SECONDS)
                return True
            except queue.Full:
                continue
        return False

    def _stage(self, inbox: queue.Queue, outbox: queue.Queue | None, work: Callable[[Any], Any]) -> None:
        """Um estágio: tira da entrada, trabalha e põe na saída; `None` encerra e passa o aviso adiante."""
        while not self._stop.is_set():
            try:
                item = inbox.get(timeout=POLL_SECONDS)
            except queue.Empty:
                continue
            if item is None:
                if outbox is not None:
                    self._put(outbox, None)
                return
            result = work(item)
            if outbox is not None and not self._put(outbox, result):
                return

    def _motion(self, features: np.ndarray, outbox: queue.Queue) -> None:
        """A difusão: do áudio ao movimento da cabeça, em janelas de 80 quadros que se sobrepõem. O movimento de
        cada quadro segue para a costura; a foto é a mesma em todos (índice espelhado, como no original)."""
        condition = self.condition_handler(features, 0)
        sequence_frames = self.audio2motion.seq_frames
        valid_length = self.audio2motion.valid_clip_len
        total = len(condition)
        keypoints = None
        start = 0
        while start < total:
            window = condition[start : start + sequence_frames][None]
            if window.shape[1] < sequence_frames:
                padding = np.stack([window[:, -1]] * (sequence_frames - window.shape[1]), 1)
                window = np.concatenate([window, padding], 1)
            keypoints = self.audio2motion(window, keypoints)
            start += valid_length
        keypoints = keypoints[:, :total]
        keypoints = self.audio2motion._smo(keypoints, 0, keypoints.shape[1])
        source_frames = len(self._source_info["x_s_info_lst"])
        for generated, motion in enumerate(self.audio2motion.cvt_fmt(keypoints)):
            if not self._put(outbox, [_mirror_index(generated, source_frames), motion, {}]):
                return
        self._put(outbox, None)


def seed_everything(seed: int) -> None:
    """Fixa os sorteios do ditto: o ruído da difusão (numpy) e o tempo das piscadas (random). Deve vir antes do
    `register_photo`."""
    np.random.seed(seed)
    random.seed(seed)
