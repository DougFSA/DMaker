import numpy as np
import cv2

from ..aux_models.landmark203 import Landmark203
from ..aux_models.mediapipe_landmark478 import Landmark478
from ..models.appearance_extractor import AppearanceExtractor
from ..models.motion_extractor import MotionExtractor

from ..utils.crop import crop_image
from ..utils.eye_info import EyeAttrUtilsByMP


"""
landmark203_cfg = {
    "model_path": "",
    "device": "cuda",
    "force_ori_type": False,
}
landmark478_cfg = {
    "blaze_face_model_path": "", 
    "face_mesh_model_path": "", 
    "device": "cuda",
    "force_ori_type": False,
    "task_path": "",
}
appearance_extractor_cfg = {
    "model_path": "",
    "device": "cuda",
}
motion_extractor_cfg = {
    "model_path": "",
    "device": "cuda",
}
"""


class Source2Info:
    def __init__(
        self,
        landmark203_cfg,
        landmark478_cfg,
        appearance_extractor_cfg,
        motion_extractor_cfg,
    ):
        # DMaker: sem InsightFace (licenca nao comercial); a caixa inicial do rosto vem do blaze_face e do face_mesh
        self.landmark203 = Landmark203(**landmark203_cfg)
        self.landmark478 = Landmark478(**landmark478_cfg)

        self.appearance_extractor = AppearanceExtractor(**appearance_extractor_cfg)
        self.motion_extractor = MotionExtractor(**motion_extractor_cfg)

    def _initial_landmarks_from_mesh(self, img):
        """DMaker: monta um vetor no layout de 106 pontos a partir da malha de 478 do MediaPipe."""
        mesh = self.landmark478(img)[0]
        h, w = img.shape[:2]
        pts = mesh[:, :2] * np.array([w, h], dtype=np.float32)
        eye_a = pts[[33, 133, 159, 145]].mean(0)
        eye_b = pts[[362, 263, 386, 374]].mean(0)
        lip = pts[[13, 14]].mean(0)
        eyes_y = (eye_a[1] + eye_b[1]) / 2
        keep = pts[pts[:, 1] >= eyes_y - 0.4 * (lip[1] - eyes_y)]
        out = np.resize(keep, (106, 2)).astype(np.float32)
        out[[33, 35, 40, 39]] = eye_a
        out[[87, 89, 94, 93]] = eye_b
        out[[52, 61]] = lip
        return out

    def _crop(self, img, last_lmk=None, **kwargs):
        # img_rgb -> landmark478 -> landmark203 -> crop

        if last_lmk is None:  # DMaker: MediaPipe no lugar de InsightFace
            lmk_for_track = self._initial_landmarks_from_mesh(img)
        else:  # track for video frames
            lmk_for_track = last_lmk  # 203

        crop_dct = crop_image(
            img,
            lmk_for_track,
            dsize=self.landmark203.dsize,
            scale=1.5,
            vy_ratio=-0.1,
            pt_crop_flag=False,
        )
        lmk203 = self.landmark203(crop_dct["img_crop"], crop_dct["M_c2o"])

        ret_dct = crop_image(
            img,
            lmk203,
            dsize=512,
            scale=kwargs.get("crop_scale", 2.3),
            vx_ratio=kwargs.get("crop_vx_ratio", 0),
            vy_ratio=kwargs.get("crop_vy_ratio", -0.125),
            flag_do_rot=kwargs.get("crop_flag_do_rot", True),
            pt_crop_flag=False,
        )

        img_crop = ret_dct["img_crop"]
        M_c2o = ret_dct["M_c2o"]

        return img_crop, M_c2o, lmk203
    
    @staticmethod
    def _img_crop_to_bchw256(img_crop):
        rgb_256 = cv2.resize(img_crop, (256, 256), interpolation=cv2.INTER_AREA)
        rgb_256_bchw = (rgb_256.astype(np.float32) / 255.0)[None].transpose(0, 3, 1, 2)
        return rgb_256_bchw

    def _get_kp_info(self, img):
        # rgb_256_bchw_norm01
        kp_info = self.motion_extractor(img)
        return kp_info

    def _get_f3d(self, img):
        # rgb_256_bchw_norm01
        fs = self.appearance_extractor(img)
        return fs

    def _get_eye_info(self, img):
        # rgb uint8
        lmk478 = self.landmark478(img)  # [1, 478, 3]
        attr = EyeAttrUtilsByMP(lmk478)
        lr_open = attr.LR_open().reshape(-1, 2)   # [1, 2]
        lr_ball = attr.LR_ball_move().reshape(-1, 6)   # [1, 3, 2] -> [1, 6]
        return [lr_open, lr_ball]

    def __call__(self, img, last_lmk=None, **kwargs):
        """
        img: rgb, uint8
        last_lmk: last frame lmk203, for video tracking
        kwargs: optional crop cfg
            crop_scale: 2.3
            crop_vx_ratio: 0
            crop_vy_ratio: -0.125
            crop_flag_do_rot: True
        """
        img_crop, M_c2o, lmk203 = self._crop(img, last_lmk=last_lmk, **kwargs)

        eye_open, eye_ball = self._get_eye_info(img_crop)

        rgb_256_bchw = self._img_crop_to_bchw256(img_crop)
        kp_info = self._get_kp_info(rgb_256_bchw)
        fs = self._get_f3d(rgb_256_bchw)
        
        source_info = {
            "x_s_info": kp_info,
            "f_s": fs,
            "M_c2o": M_c2o,
            "eye_open": eye_open,   # [1, 2]
            "eye_ball": eye_ball,    # [1, 6]
            "lmk203": lmk203,  # for track
        }
        return source_info
