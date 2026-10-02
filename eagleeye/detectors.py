"""Person detection for auto-tracking: the RTMO-s pose model and MJPEG frame decoding.

A single model (RTMO-s, OpenMMLab, Apache-2.0) gives 17 COCO keypoints per person -
the head point is built from the nose, eyes and ears (see :mod:`eagleeye.perception`).
There used to be two models here: face (YuNet) and body (YOLOX); switching between
them moved the target by 9-13°, so they were replaced (2026-09-23).
"""

from __future__ import annotations

import ctypes
import io
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
# RTMO-s (OpenMMLab, Apache-2.0): one-stage multi-person pose, 17 COCO keypoints.
RTMO_MODEL = MODELS_DIR / "rtmo-s_body7_640.onnx"


@dataclass
class Detection:
    """A detected object in the original frame's coordinate system."""

    x: int
    y: int
    w: int
    h: int
    score: float
    label: str = ""
    # COCO pose keypoints (x, y, confidence) in the original frame's coordinates - only from PoseDetector.
    keypoints: tuple[tuple[float, float, float], ...] | None = None

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.w / 2.0, self.y + self.h / 2.0

    @property
    def area(self) -> int:
        return max(0, self.w) * max(0, self.h)

    def as_box(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h


def decode_mjpeg(jpg: bytes) -> np.ndarray | None:
    """Decodes an MJPEG frame to BGR (or ``None`` when it fails).

    We deliberately use Pillow, not ``cv2.imdecode``: the camera adds a few bytes
    of padding before the EOI marker and libjpeg in OpenCV then prints
    ``Corrupt JPEG data: N extraneous bytes`` **to stderr on every frame**,
    flooding the terminal (dozens of lines per second). Pillow reports it
    as a Python warning, which can be silenced.

    Cost: ~8 ms for 720p instead of ~5 ms - at an 8 Hz loop that is 6% of the budget,
    and the result is identical down to the byte (verified).
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with Image.open(io.BytesIO(jpg)) as image:
                rgb = np.asarray(image.convert("RGB"))
        return np.ascontiguousarray(rgb[:, :, ::-1])  # RGB -> BGR
    except Exception:
        return None


def decode_mjpeg_scaled(jpg: bytes, reduce: int = 2) -> np.ndarray | None:
    """Like :func:`decode_mjpeg`, but decodes straight at the ``1/reduce`` scale.

    Pillow's ``draft`` makes libjpeg scale in the DCT domain, so half the work
    is skipped. Measured on a 1080p frame from the camera: 3.9 ms instead of 11.5 ms,
    with no libjpeg warnings (OpenCV spews them on every frame from this camera).
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with Image.open(io.BytesIO(jpg)) as image:
                if reduce > 1:
                    image.draft("RGB", (image.width // reduce, image.height // reduce))
                rgb = np.asarray(image.convert("RGB"))
        return np.ascontiguousarray(rgb[:, :, ::-1])  # RGB -> BGR
    except Exception:
        return None


CU_CTX_SCHED_BLOCKING_SYNC = 0x04


def set_cuda_blocking_sync(load: Callable[[str], object] = ctypes.CDLL) -> bool:
    """Make the CPU sleep, not spin, while it waits for the GPU.

    CUDA's default scheduling spin-waits when a context has fewer active threads than there
    are CPU cores, so every ``session.run`` on the GPU cost as much CPU time as wall time
    (9.5 ms of 9.5 ms on the RTX 3060 Ti, measured 2026-10-02). With blocking sync: 5.3 ms
    CPU for +0.3-1 ms latency, which the 15 Hz loop does not notice.
    The driver API, not the runtime: one ``libcuda.so.1`` serves every ``libcudart`` copy,
    and the flag lives on the device's primary context, which ONNX Runtime uses. It may be
    set before or after that context exists. Best effort: False without a driver or GPU.
    """
    try:
        cuda = load("libcuda.so.1")
        dev = ctypes.c_int()
        return (cuda.cuInit(0) == 0
                and cuda.cuDeviceGet(ctypes.byref(dev), 0) == 0
                and cuda.cuDevicePrimaryCtxSetFlags_v2(dev, CU_CTX_SCHED_BLOCKING_SYNC) == 0)
    except (OSError, AttributeError):
        return False


class PoseDetector:
    """Person pose (RTMO-s) - nose, eyes, ears, shoulders... keypoints for each person.

    A single model gives the head point in every pose (front, profile, standing,
    back), without the face <-> body switching that used to make the target jump
    9-13° (spike 2026-09-23). Processing as in the model's pipeline.json:
    letterbox 640x640 to the top-left corner, padding 114, BGR, no
    normalization. NMS is already in the export, but boxes of multiple people can
    overlap - we add our own, as in rtmlib.
    """

    name = "pose"
    input_size = 640

    def __init__(self, prefer_gpu: bool = True, score_threshold: float = 0.5,
                 nms_threshold: float = 0.45) -> None:
        import onnxruntime as ort

        try:
            ort.preload_dlls()
        except Exception:
            pass
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        providers = (["CUDAExecutionProvider", "CPUExecutionProvider"] if prefer_gpu
                     else ["CPUExecutionProvider"])
        self.cuda_blocking_sync = set_cuda_blocking_sync() if prefer_gpu else False
        self._session = ort.InferenceSession(str(RTMO_MODEL), sess_options=opts, providers=providers)
        self._input = self._session.get_inputs()[0].name
        active = self._session.get_providers()
        self.backend = f"ONNX Runtime ({active[0]})"
        self.gpu_error = None if (not prefer_gpu or "CUDAExecutionProvider" in active) \
            else "CUDAExecutionProvider unavailable"
        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold
        self.last_ms = 0.0

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        h, w = frame_bgr.shape[:2]
        size = self.input_size
        ratio = min(size / h, size / w)
        rw, rh = max(1, int(w * ratio)), max(1, int(h * ratio))
        canvas = np.full((size, size, 3), 114, np.uint8)
        canvas[:rh, :rw] = cv2.resize(frame_bgr, (rw, rh), interpolation=cv2.INTER_LINEAR)
        blob = np.ascontiguousarray(canvas.transpose(2, 0, 1)[None], dtype=np.float32)

        t0 = time.perf_counter()
        dets, kpts = self._session.run(None, {self._input: blob})
        self.last_ms = (time.perf_counter() - t0) * 1000.0

        boxes = dets[0, :, :4] / ratio
        scores = dets[0, :, 4]
        points = kpts[0].copy()
        points[:, :, :2] /= ratio
        keep = np.where(scores > self.score_threshold)[0]
        if keep.size == 0:
            return []
        xywh = [[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in boxes[keep]]
        kept = np.array(cv2.dnn.NMSBoxes(xywh, scores[keep].tolist(), self.score_threshold,
                                         self.nms_threshold)).flatten()
        out = []
        for k in kept:
            i = keep[k]
            x, y, bw, bh = xywh[k]
            out.append(Detection(int(x), int(y), int(bw), int(bh), float(scores[i]), self.name,
                                 tuple((float(px), float(py), float(pc)) for px, py, pc in points[i])))
        return out


def gpu_status() -> dict:
    """GPU information to show in the interface."""
    info: dict = {"available": False, "provider": None, "device": None, "note": ""}
    try:
        import onnxruntime as ort

        if "CUDAExecutionProvider" not in ort.get_available_providers():
            info["note"] = "onnxruntime without CUDAExecutionProvider"
            return info
        import subprocess

        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            info["device"] = out.stdout.strip().splitlines()[0]
        info["available"] = True
        info["provider"] = "CUDAExecutionProvider"
    except Exception as exc:
        info["note"] = str(exc)
    return info
