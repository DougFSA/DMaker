import cv2
import numpy as np


def check_resize(h, w, max_dim=1920, division=2):
    rsz_flag = False
    # ajust the size of the image according to the maximum dimension
    if max_dim > 0 and max(h, w) > max_dim:
        rsz_flag = True
        if h > w:
            new_h = max_dim
            new_w = int(round(w * max_dim / h))
        else:
            new_w = max_dim
            new_h = int(round(h * max_dim / w))
    else:
        new_h = h
        new_w = w

    # ensure that the image dimensions are multiples of n
    if new_h % division != 0:
        new_h = new_h - (new_h % division)
        rsz_flag = True
    if new_w % division != 0:
        new_w = new_w - (new_w % division)
        rsz_flag = True

    return new_h, new_w, rsz_flag


def load_image(image_path, max_dim=-1):
    # DMaker: le pelos bytes, porque cv2.imread nao abre caminho com acento no Windows
    img = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = img.shape[:2]
    new_h, new_w, rsz_flag = check_resize(h, w, max_dim)
    if rsz_flag:
        img = cv2.resize(img, (new_w, new_h))
    return img


def load_source_frames(source_path, max_dim=-1, n_frames=-1):
    # DMaker: so imagem (a foto da persona); o caminho de video do ditto, com filetype e imageio, nao e usado
    return [load_image(source_path, max_dim)], True
