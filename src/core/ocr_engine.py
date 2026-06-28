"""Shared lazy RapidOCR engine so name and chat readers reuse one ONNX model."""

from __future__ import annotations

import csv
import threading
import time
from pathlib import Path

import numpy as np

_ocr_lock = threading.Lock()


_ocr_det = None
_ocr_no_det = None


def _engine_det():
    global _ocr_det
    if _ocr_det is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr_det = RapidOCR(
            use_angle_cls=False, print_verbose=False, intra_op_num_threads=1, inter_op_num_threads=1
        )
    return _ocr_det


def _engine_no_det():
    global _ocr_no_det
    if _ocr_no_det is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr_no_det = RapidOCR(
            use_det=False,
            use_angle_cls=False,
            print_verbose=False,
            intra_op_num_threads=1,
            inter_op_num_threads=1,
        )
    return _ocr_no_det


def preload() -> None:
    """Initialize engines immediately so ONNX C++ doesn't lock the GIL mid-game."""
    _engine_det()
    _engine_no_det()


_csv_path = Path("logs/ocr_performance.csv")


def _log_performance(task: str, duration: float, size: tuple[int, ...]):
    try:
        lines = []
        if _csv_path.exists():
            with open(_csv_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        
        # Keep header + last 99 entries
        if len(lines) >= 100:
            lines = [lines[0]] + lines[-98:]
            with open(_csv_path, "w", newline="", encoding="utf-8") as f:
                f.writelines(lines)
                
        write_header = len(lines) == 0
        _csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(_csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(["timestamp", "task", "duration_s", "width", "height"])
            h = size[0] if len(size) > 0 else 0
            w = size[1] if len(size) > 1 else 0
            writer.writerow([time.strftime("%Y-%m-%dT%H:%M:%S"), task, f"{duration:.3f}", w, h])
    except Exception:
        pass


def sorted_ocr_lines(result) -> list[str]:
    """Text lines from a RapidOCR result ordered TOP-TO-BOTTOM by box position."""
    if not result:
        return []
    return [t for _b, t, _s in sorted(result, key=lambda r: min(float(p[1]) for p in r[0]))]


def run_ocr(image: np.ndarray, task_name: str = "run_ocr") -> list[str]:
    """OCR an image, returning the detected text lines (empty if none)."""
    with _ocr_lock:
        t0 = time.time()
        result, _ = _engine_det()(image)
        inference_time = time.time() - t0
        _log_performance(task_name, inference_time, image.shape)
        return [text for _box, text, _score in result] if result else []


def run_ocr_no_det(image: np.ndarray, task_name: str = "run_ocr_no_det") -> list[str]:
    """OCR an image bypassing the text-detection network. Use only for pre-cropped single lines."""
    with _ocr_lock:
        t1 = time.time()
        result, _ = _engine_no_det()(image)
    inference_time = time.time() - t1

    # Log ONLY the inference time
    _log_performance(task_name, inference_time, image.shape)

    return [text for _box, text, _score in result] if result else []


def run_ocr_lines(image: np.ndarray, task_name: str = "run_ocr_lines") -> list[str]:
    with _ocr_lock:
        t0 = time.time()
        result, _ = _engine_det()(image)
        inference_time = time.time() - t0
        _log_performance(task_name, inference_time, image.shape)
        return sorted_ocr_lines(result)
