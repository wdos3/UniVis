from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from app.models import BoundingBox, QRCode


def _box(points: np.ndarray, width: int, height: int) -> BoundingBox:
    flattened = points.reshape(-1, 2)
    x_min, y_min = flattened.min(axis=0)
    x_max, y_max = flattened.max(axis=0)
    return BoundingBox(
        x=max(0, float(x_min) / width),
        y=max(0, float(y_min) / height),
        width=min(1, max(0.001, float(x_max - x_min) / width)),
        height=min(1, max(0.001, float(y_max - y_min) / height)),
    )


def detect_qr_codes(image: Image.Image, page_number: int) -> list[QRCode]:
    rgb = np.asarray(image.convert("RGB"))
    detector = cv2.QRCodeDetector()
    height, width = rgb.shape[:2]
    found: list[QRCode] = []
    try:
        success, values, points, _ = detector.detectAndDecodeMulti(rgb)
        if success and points is not None:
            for value, region in zip(values, points, strict=False):
                if value:
                    found.append(QRCode(url=value, source_page=page_number, bounding_box=_box(region, width, height)))
            return found
    except cv2.error:
        pass

    value, points, _ = detector.detectAndDecode(rgb)
    if value:
        found.append(QRCode(url=value, source_page=page_number, bounding_box=_box(points, width, height) if points is not None else None))
    return found
