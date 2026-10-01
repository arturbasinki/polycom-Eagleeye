"""Detekcja osób dla auto-trackingu: model pozy RTMO-s i dekodowanie klatek MJPEG.

Jeden model (RTMO-s, OpenMMLab, Apache-2.0) daje dla każdej osoby 17 punktów
COCO - z nosa, oczu i uszu powstaje punkt głowy (patrz :mod:`eagleeye.perception`).
Wcześniej były tu dwa modele: twarz (YuNet) i sylwetka (YOLOX); przełączanie
między nimi przesuwało cel o 9-13°, więc zostały zastąpione (2026-09-23).
"""

from __future__ import annotations

import io
import time
import warnings
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
# RTMO-s (OpenMMLab, Apache-2.0): jednoetapowa poza wielu osób, 17 punktów COCO.
RTMO_MODEL = MODELS_DIR / "rtmo-s_body7_640.onnx"


@dataclass
class Detection:
    """Wykryty obiekt w układzie oryginalnej klatki."""

    x: int
    y: int
    w: int
    h: int
    score: float
    label: str = ""
    # Punkty pozy COCO (x, y, pewność) w układzie oryginalnej klatki - tylko z PoseDetector.
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
    """Dekoduje ramkę MJPEG do BGR (albo ``None``, gdy się nie uda).

    Celowo używamy Pillow, a nie ``cv2.imdecode``: kamera dokłada kilka bajtów
    dopełnienia przed znacznikiem EOI i libjpeg w OpenCV wypisuje wtedy
    ``Corrupt JPEG data: N extraneous bytes`` **na stderr przy każdej klatce**,
    zaśmiecając terminal (kilkadziesiąt linii na sekundę). Pillow zgłasza to
    jako ostrzeżenie Pythona, które da się wyciszyć.

    Koszt: ~8 ms dla 720p zamiast ~5 ms - przy pętli 8 Hz to 6% budżetu,
    a wynik jest identyczny co do bajtu (sprawdzone).
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
    """Jak :func:`decode_mjpeg`, ale dekoduje od razu w skali ``1/reduce``.

    Pillow ``draft`` każe libjpeg skalować w dziedzinie DCT, więc połowa pracy
    odpada. Zmierzone na klatce 1080p z kamery: 3,9 ms zamiast 11,5 ms, bez
    ostrzeżeń libjpeg (OpenCV sypie nimi przy każdej klatce z tej kamery).
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


class PoseDetector:
    """Poza osób (RTMO-s) - punkty nosa, oczu, uszu, barków... dla każdej osoby.

    Jeden model daje punkt głowy w każdej pozycji (przodem, profil, stojąc,
    tyłem), bez przełączania twarz <-> sylwetka, które dawało skoki celu
    9-13° (spike 2026-09-23). Przetwarzanie jak w pipeline.json modelu:
    letterbox 640x640 do lewego górnego rogu, wypełnienie 114, BGR, bez
    normalizacji. NMS jest już w eksporcie, ale ramki wielu osób mogą się
    nakładać - dokładamy własny, jak w rtmlib.
    """

    name = "poza"
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
        self._session = ort.InferenceSession(str(RTMO_MODEL), sess_options=opts, providers=providers)
        self._input = self._session.get_inputs()[0].name
        active = self._session.get_providers()
        self.backend = f"ONNX Runtime ({active[0]})"
        self.gpu_error = None if (not prefer_gpu or "CUDAExecutionProvider" in active) \
            else "CUDAExecutionProvider niedostępny"
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
    """Informacje o GPU do pokazania w interfejsie."""
    info: dict = {"available": False, "provider": None, "device": None, "note": ""}
    try:
        import onnxruntime as ort

        if "CUDAExecutionProvider" not in ort.get_available_providers():
            info["note"] = "onnxruntime bez CUDAExecutionProvider"
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
