"""A foto da persona realista: conferir o arquivo, achar o rosto e enquadrar no formato do vídeo.

O ditto anima a imagem que recebe no tamanho em que ela vem, e o decoder dele trabalha a 512 pixels no rosto e cola
de volta: então o custo de desenhar não muda com a resolução, mas a foto precisa chegar já recortada no
enquadramento do vídeo (rosto na altura e no tamanho certos) e no tamanho final. As contas do enquadramento são
puras; ler a foto e achar o rosto (blaze_face, o detector do MediaPipe, em ONNX) ficam nas funções do fim.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MIN_PHOTO_SIDE = 512  # abaixo disso a foto não tem detalhe para um rosto em tela cheia
PHOTO_EXTENSIONS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG"}
# Quanto da altura do quadro o rosto ocupa e onde fica o centro dele (do topo), por enquadramento. Na tela cheia
# (9:16) o rosto é de meio corpo, numa faixa alta do quadro, deixando espaço para a legenda embaixo; na
# sobreposição do canto (3:4 ou 1:1) é cabeça e ombros, com o rosto grande.
FACE_HEIGHT = {"full": 0.28, "corner": 0.45}
FACE_CENTER = {"full": 0.35, "corner": 0.45}
# Abaixo desta fração do lado menor da saída, a foto recortada precisa ser ampliada mais de duas vezes e o rosto
# sai borrado: o render avisa.
MIN_CROP_RATIO = 0.5
DEFAULT_FRAMING = "full"


@dataclass(frozen=True)
class Box:
    """Um retângulo em pixels da foto original."""

    left: float
    top: float
    width: float
    height: float

    @property
    def center(self) -> tuple[float, float]:
        return self.left + self.width / 2, self.top + self.height / 2


@dataclass(frozen=True)
class FramedPhoto:
    """O resultado do enquadramento: o recorte na foto original e o que o usuário deve saber sobre ele."""

    crop: Box
    warnings: tuple[str, ...]


class PhotoError(ValueError):
    """A foto não serve (a mensagem diz o que corrigir)."""


FaceFinder = Callable[[np.ndarray], Box | None]


def crop_for_face(image_size: tuple[int, int], face: Box, out_size: tuple[int, int], framing: str) -> Box:
    """O recorte da foto na proporção da saída com o rosto na altura e no tamanho do enquadramento. Se a foto não
    comporta o recorte inteiro, ele encolhe até caber (o rosto fica um pouco maior) e é empurrado para dentro."""
    image_width, image_height = image_size
    face_fraction = FACE_HEIGHT.get(framing, FACE_HEIGHT[DEFAULT_FRAMING])
    center_fraction = FACE_CENTER.get(framing, FACE_CENTER[DEFAULT_FRAMING])
    aspect = out_size[0] / out_size[1]
    height = face.height / face_fraction
    width = height * aspect
    fit = min(image_width / width, image_height / height, 1.0)
    width, height = width * fit, height * fit
    center_x, center_y = face.center
    left = min(max(center_x - width / 2, 0.0), image_width - width)
    top = min(max(center_y - center_fraction * height, 0.0), image_height - height)
    return Box(left, top, width, height)


def frame_photo(
    image_size: tuple[int, int], face: Box, out_size: tuple[int, int], framing: str
) -> FramedPhoto:
    crop = crop_for_face(image_size, face, out_size, framing)
    warnings: list[str] = []
    wanted = MIN_CROP_RATIO * min(out_size)
    if min(crop.width, crop.height) < wanted:
        warnings.append(
            f"A foto da persona é pequena para este enquadramento: o recorte do rosto tem {crop.width:.0f}x"
            f"{crop.height:.0f} pixels e o vídeo é {out_size[0]}x{out_size[1]}, então o rosto sai borrado. "
            "Use uma foto maior."
        )
    return FramedPhoto(crop, tuple(warnings))


# ---------- arquivo da foto ----------


def check_photo_file(path: Path) -> tuple[int, int]:
    """Confere que `path` é um jpg ou png de verdade, com o lado menor de pelo menos `MIN_PHOTO_SIDE`; devolve
    (largura, altura)."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if not path.is_file():
        raise PhotoError(f"A foto {str(path)!r} não existe.")
    expected = PHOTO_EXTENSIONS.get(path.suffix.lower())
    if expected is None:
        raise PhotoError("A foto da persona precisa ser um arquivo .jpg ou .png.")
    try:
        with Image.open(path) as image:
            if image.format != expected:
                raise PhotoError(
                    f"O arquivo {path.name!r} tem extensão {path.suffix.lower()} mas não é um {expected}; "
                    "use um .jpg ou .png de verdade."
                )
            width, height = ImageOps.exif_transpose(image).size
    except UnidentifiedImageError as exc:
        raise PhotoError(f"Não consegui abrir a foto {path.name!r}: o arquivo não é uma imagem.") from exc
    if min(width, height) < MIN_PHOTO_SIDE:
        raise PhotoError(
            f"A foto tem {width}x{height} pixels; o lado menor precisa ter pelo menos {MIN_PHOTO_SIDE}. "
            "Use uma foto maior."
        )
    return width, height


def read_photo(path: Path) -> np.ndarray:
    """A foto como RGB (altura, largura, 3). Lê pelos bytes: o OpenCV não abre caminho com acento no Windows. A
    orientação do EXIF é respeitada, como o celular grava."""
    import cv2

    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise PhotoError(f"Não consegui abrir a foto {path.name!r}.")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def blaze_face_finder(model_path: Path) -> FaceFinder:
    """O detector de rosto do MediaPipe (o mesmo que o ditto usa) como uma função: acha o rosto maior e devolve a
    caixa em pixels, ou None."""
    from ..vendor.ditto.aux_models.blaze_face import BlazeFace

    detector = BlazeFace(str(model_path), device="cpu")

    def find(image: np.ndarray) -> Box | None:
        height, width = image.shape[:2]
        detections = detector(image)
        if len(detections) == 0:
            return None
        top, left, bottom, right = detections[0][
            :4
        ]  # y e x mínimos e máximos, em unidades da imagem de 128 px
        scale_x, scale_y = width / 128.0, height / 128.0
        return Box(left * scale_x, top * scale_y, (right - left) * scale_x, (bottom - top) * scale_y)

    return find


def frame_image(image: np.ndarray, crop: Box, out_size: tuple[int, int]) -> np.ndarray:
    """Recorta `crop` e leva ao tamanho da saída: encolher usa a média da área (nítido, sem serrilhado) e ampliar
    usa o cúbico."""
    import cv2

    left, top = round(crop.left), round(crop.top)
    right = min(round(crop.left + crop.width), image.shape[1])
    bottom = min(round(crop.top + crop.height), image.shape[0])
    piece = image[top:bottom, left:right]
    shrinking = piece.shape[1] >= out_size[0]
    method = cv2.INTER_AREA if shrinking else cv2.INTER_CUBIC
    return cv2.resize(piece, out_size, interpolation=method)


@dataclass(frozen=True)
class PreparedPhoto:
    image: np.ndarray  # RGB, no tamanho da saída
    warnings: tuple[str, ...]


def prepare_photo(
    photo: Path, out_size: tuple[int, int], framing: str, find_face: FaceFinder
) -> PreparedPhoto:
    """A foto enquadrada no tamanho do vídeo, pronta para o ditto. Levanta `PhotoError` se não há rosto."""
    image = read_photo(photo)
    face = find_face(image)
    if face is None:
        raise PhotoError(
            f"Não achei um rosto na foto {photo.name!r}. Use uma foto de frente, com o rosto inteiro visível "
            "e bem iluminado."
        )
    height, width = image.shape[:2]
    framed = frame_photo((width, height), face, out_size, framing)
    return PreparedPhoto(frame_image(image, framed.crop, out_size), framed.warnings)
