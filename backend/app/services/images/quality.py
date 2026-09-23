from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from app.models import ImageQualityIssue


def inspect_quality(image: Image.Image) -> list[ImageQualityIssue]:
    rgb = np.asarray(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape
    issues: list[ImageQualityIssue] = []

    shortest = min(width, height)
    if shortest < 400:
        issues.append(ImageQualityIssue(code="very_low_resolution", message="The image resolution is too low to read reliably. Retake the photo more closely.", severity="blocking"))
    elif shortest < 800:
        issues.append(ImageQualityIssue(code="low_resolution", message="The notice may be too small in the image. A closer photo may improve accuracy."))

    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if blur_score < 25:
        issues.append(ImageQualityIssue(code="severe_blur", message="The notice appears extremely blurry. Text may not be readable.", severity="blocking"))
    elif blur_score < 65:
        issues.append(ImageQualityIssue(code="blur", message="The notice appears slightly blurry. Please retake it steadily if possible."))

    brightness = float(gray.mean())
    if brightness < 40:
        issues.append(ImageQualityIssue(code="too_dark", message="The image is too dark to interpret reliably.", severity="blocking"))
    elif brightness < 68:
        issues.append(ImageQualityIssue(code="dark", message="The image is dark. Some text may require review."))

    glare_ratio = float(np.count_nonzero(gray > 248) / gray.size)
    if 0.06 < glare_ratio < 0.30:
        issues.append(ImageQualityIssue(code="glare", message="Large bright areas may hide text. Avoid glare when retaking the photo."))

    edges = cv2.Canny(gray, 60, 180)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        largest = max(contours, key=cv2.contourArea)
        coverage = cv2.contourArea(largest) / float(width * height)
        if 0.01 < coverage < 0.12:
            issues.append(ImageQualityIssue(code="notice_too_small", message="The notice appears to occupy only a small part of the photo."))
        if coverage > 0.2:
            x, y, box_width, box_height = cv2.boundingRect(largest)
            margin = max(4, int(shortest * 0.01))
            if x <= margin or y <= margin or x + box_width >= width - margin or y + box_height >= height - margin:
                issues.append(ImageQualityIssue(code="possible_cutoff", message="Part of the notice may touch the image edge. Check that no text is cut off."))

    return issues
