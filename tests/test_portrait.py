"""A foto da persona realista: o enquadramento (contas puras), a conferência do arquivo e a foto pronta para o ditto."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from dmaker.persona import portrait
from dmaker.persona.portrait import (
    Box,
    PhotoError,
    check_photo_file,
    crop_for_face,
    frame_photo,
    prepare_photo,
)


def test_the_full_screen_crop_puts_the_face_at_the_wanted_height_and_size():
    face = Box(1000, 800, 300, 300)
    crop = crop_for_face((3000, 4000), face, (1080, 1920), "full")
    assert crop.width / crop.height == pytest.approx(1080 / 1920)
    assert face.height / crop.height == pytest.approx(portrait.FACE_HEIGHT["full"])
    assert (face.center[1] - crop.top) / crop.height == pytest.approx(portrait.FACE_CENTER["full"])
    assert face.center[0] == pytest.approx(crop.left + crop.width / 2)


def test_the_corner_crop_is_closer_to_the_face():
    face = Box(1000, 1000, 300, 300)
    full = crop_for_face((4000, 4000), face, (720, 960), "full")
    corner = crop_for_face((4000, 4000), face, (720, 960), "corner")
    assert corner.height < full.height
    assert face.height / corner.height == pytest.approx(portrait.FACE_HEIGHT["corner"])
    assert corner.width / corner.height == pytest.approx(720 / 960)


def test_a_crop_that_does_not_fit_shrinks_and_slides_inside_the_photo():
    # rosto no canto de uma foto pequena: o recorte ideal passaria da borda
    face = Box(50, 30, 100, 100)
    crop = crop_for_face((400, 500), face, (1080, 1920), "full")
    assert crop.left >= 0 and crop.top >= 0
    assert crop.left + crop.width <= 400 + 1e-6 and crop.top + crop.height <= 500 + 1e-6
    assert crop.width / crop.height == pytest.approx(1080 / 1920)


def test_a_small_photo_gets_a_warning_and_a_big_one_does_not():
    face = Box(150, 200, 200, 200)
    small = frame_photo(
        (500, 600), face, (1080, 1920), "full"
    )  # recorte de 337x600 para um quadro de 1080x1920
    assert any("pequena" in warning for warning in small.warnings)
    big = frame_photo((3000, 4000), Box(1000, 800, 600, 600), (1080, 1920), "full")
    assert big.warnings == ()


def make_image(path: Path, size=(800, 700), fmt="JPEG") -> Path:
    Image.new("RGB", size, (120, 100, 90)).save(path, format=fmt)
    return path


def test_check_photo_file_accepts_jpg_and_png_and_returns_the_size(tmp_path):
    assert check_photo_file(make_image(tmp_path / "a.jpg")) == (800, 700)
    assert check_photo_file(make_image(tmp_path / "b.png", fmt="PNG")) == (800, 700)


@pytest.mark.parametrize(
    ("name", "fmt", "size", "message"),
    [
        ("a.gif", "GIF", (800, 800), r"\.jpg ou \.png"),
        ("a.jpg", "PNG", (800, 800), "não é um JPEG"),
        ("a.jpg", "JPEG", (400, 900), "lado menor precisa ter pelo menos 512"),
    ],
)
def test_check_photo_file_explains_what_to_fix(tmp_path, name, fmt, size, message):
    with pytest.raises(PhotoError, match=message):
        check_photo_file(make_image(tmp_path / name, size, fmt))


def test_check_photo_file_refuses_a_missing_file_and_a_text_file_with_an_image_name(tmp_path):
    with pytest.raises(PhotoError, match="não existe"):
        check_photo_file(tmp_path / "nada.jpg")
    fake = tmp_path / "texto.jpg"
    fake.write_text("não sou uma imagem")
    with pytest.raises(PhotoError, match="não é uma imagem"):
        check_photo_file(fake)


@pytest.fixture
def cv2():
    return pytest.importorskip("cv2")


def test_prepare_photo_frames_the_face_and_scales_to_the_output_size(tmp_path, cv2):
    photo = make_image(tmp_path / "foto.png", (1200, 1600), "PNG")
    seen = []

    def find_face(image: np.ndarray) -> Box:
        seen.append(image.shape)
        return Box(450, 500, 300, 300)

    prepared = prepare_photo(photo, (540, 960), "full", find_face)
    assert seen == [(1600, 1200, 3)]
    assert prepared.image.shape == (960, 540, 3) and prepared.warnings == ()
    assert tuple(prepared.image[10, 10]) == (120, 100, 90)  # RGB, não BGR


def test_prepare_photo_without_a_face_says_what_to_do(tmp_path, cv2):
    photo = make_image(tmp_path / "foto.png", (1200, 1600), "PNG")
    with pytest.raises(PhotoError, match="Não achei um rosto.*de frente"):
        prepare_photo(photo, (540, 960), "full", lambda image: None)


def test_a_photo_in_a_folder_with_accents_is_read(tmp_path, cv2):
    folder = tmp_path / "Imagens da Conceição"
    folder.mkdir()
    photo = make_image(folder / "retrato.png", (700, 800), "PNG")
    assert portrait.read_photo(photo).shape == (800, 700, 3)
