"""Template-image asset store (PNG files under ``assets/templates/``)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .paths import TEMPLATES_DIR, ensure_dirs

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\- ]+$")


def normalize_name(name: str) -> str:
    """Validate a template name and ensure it ends with ``.png``."""
    name = name.strip()
    if not name or not _SAFE_NAME.match(name) or ".." in name:
        raise ValueError(f"invalid template name: {name!r}")
    if not name.lower().endswith(".png"):
        name += ".png"
    return name


def template_path(name: str) -> Path:
    return TEMPLATES_DIR / normalize_name(name)


def list_templates() -> list[dict]:
    ensure_dirs()
    out = []
    for path in sorted(TEMPLATES_DIR.glob("*.png")):
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            continue
        h, w = img.shape[:2]
        out.append({"name": path.name, "width": w, "height": h, "size_bytes": path.stat().st_size})
    return out


def load_template(name: str) -> np.ndarray:
    path = template_path(name)
    if not path.exists():
        raise FileNotFoundError(f"template not found: {name}")
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"template is not a readable image: {name}")
    return img


def save_template(name: str, png_bytes: bytes) -> dict:
    ensure_dirs()
    path = template_path(name)
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("uploaded file is not a readable PNG image")
    path.write_bytes(png_bytes)
    h, w = img.shape[:2]
    return {"name": path.name, "width": w, "height": h}


def read_template_bytes(name: str) -> bytes:
    path = template_path(name)
    if not path.exists():
        raise FileNotFoundError(f"template not found: {name}")
    return path.read_bytes()


def delete_template(name: str) -> bool:
    path = template_path(name)
    if not path.exists():
        raise FileNotFoundError(f"template not found: {name}")
    path.unlink()
    return True
