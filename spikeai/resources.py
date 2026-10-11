from __future__ import annotations

import hashlib
import os
import sys

import cv2
import numpy as np

from .logsys import log


def base_dir() -> str:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts: str) -> str:
    return os.path.join(base_dir(), *parts)


def images_dir() -> str:
    return resource_path("assets", "templates")


def derived_dir() -> str:
    return resource_path("assets", "derived")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_png_unchanged(path: str) -> np.ndarray | None:
    try:
        data = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    except Exception as e:
        log.error("No se pudo leer %s: %s", path, e)
        return None
    if img is None or img.size == 0:
        log.error("Imagen dañada o no válida: %s", path)
        return None
    if img.dtype != np.uint8:
        img = cv2.convertScaleAbs(img, alpha=255.0 / max(1, int(np.iinfo(img.dtype).max)))
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    return img


def list_reference_pngs(folder: str | None = None) -> list[str]:
    folder = folder or images_dir()
    if not os.path.isdir(folder):
        log.error("No existe la carpeta de plantillas: %s", folder)
        return []
    return sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".png"))
