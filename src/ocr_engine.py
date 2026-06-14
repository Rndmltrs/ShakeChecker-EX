"""Shared lazy RapidOCR engine so name and chat readers reuse one ONNX model."""

from __future__ import annotations

import numpy as np

_ocr = None


def run_ocr(image: np.ndarray) -> list[str]:
    """OCR an image, returning the detected text lines (empty if none)."""
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr = RapidOCR()
    result, _ = _ocr(image)
    return [text for _box, text, _score in result] if result else []
