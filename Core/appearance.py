"""UI appearance helpers, including wallpaper-based Monet color extraction."""

from __future__ import annotations

import colorsys
from pathlib import Path
from typing import Final

import cv2
import numpy as np


DEFAULT_ACCENT: Final = "#4DA3FF"


def _hex(rgb: np.ndarray | tuple[int, int, int]) -> str:
    red, green, blue = (int(round(float(channel))) for channel in rgb)
    return f"#{red:02X}{green:02X}{blue:02X}"


def _mix(rgb: np.ndarray, target: tuple[int, int, int], amount: float) -> np.ndarray:
    return np.clip(rgb * (1.0 - amount) + np.asarray(target) * amount, 0, 255)


def extract_monet_palette(image_path: str | Path) -> dict[str, str]:
    """Extract a compact dark-theme palette from a wallpaper.

    OpenCV's k-means keeps this deterministic and avoids another UI-only
    dependency.  The primary color favors populous, saturated bright clusters,
    which gives a useful Material/Monet-like accent instead of a muddy average.
    """

    path = Path(image_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"壁纸不存在：{path}")

    encoded = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取图片：{path}")

    height, width = image.shape[:2]
    scale = min(1.0, 120.0 / max(height, width))
    if scale < 1.0:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    pixels = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).reshape(-1, 3).astype(np.float32)
    if len(pixels) > 4096:
        indexes = np.linspace(0, len(pixels) - 1, 4096, dtype=np.int32)
        pixels = pixels[indexes]

    cluster_count = min(8, max(1, len(pixels)))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.6)
    cv2.setRNGSeed(42)
    _, labels, centers = cv2.kmeans(
        pixels,
        cluster_count,
        None,
        criteria,
        3,
        cv2.KMEANS_PP_CENTERS,
    )
    counts = np.bincount(labels.ravel(), minlength=cluster_count).astype(np.float32)

    scores: list[float] = []
    for center, count in zip(centers, counts):
        red, green, blue = center / 255.0
        _, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
        population = count / counts.sum()
        scores.append(population * 0.35 + saturation * 0.45 + value * 0.20)
    primary_rgb = centers[int(np.argmax(scores))]

    red, green, blue = primary_rgb / 255.0
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    if saturation < 0.28:
        saturation = 0.45
    if value < 0.55:
        value = 0.72
    primary_rgb = np.asarray(colorsys.hsv_to_rgb(hue, saturation, value)) * 255.0
    secondary_rgb = np.asarray(
        colorsys.hsv_to_rgb((hue + 0.10) % 1.0, saturation * 0.72, min(1.0, value + 0.08))
    ) * 255.0

    return {
        "primary": _hex(primary_rgb),
        "secondary": _hex(secondary_rgb),
        "surface": _hex(_mix(primary_rgb, (8, 13, 23), 0.88)),
        "surface_variant": _hex(_mix(primary_rgb, (18, 26, 40), 0.78)),
        "outline": _hex(_mix(primary_rgb, (80, 92, 112), 0.62)),
    }
