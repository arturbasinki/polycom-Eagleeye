#!/usr/bin/env python3
"""Renders assets/screenshot-tracking.png: the tracker following a person, from the simulator.

No camera and no people are involved. The scene is a synthetic mannequin; everything else comes
from the project's own code:

* the closed-loop simulator (eagleeye/sim.py) runs the "talk" profile for a person who leans
  15 degrees to the side at 10 s and returns at 40 s - the plot shows the person's world angle and
  the camera pan exactly as the simulator and the head model computed them;
* the overlay on the preview (golden-ratio lines, aim ring, head point, detection) is drawn by
  eagleeye/overlay.py from a TrackerState, the same code the application uses.

    .venv/bin/python tools/render_sim_screenshot.py [--out assets/screenshot-tracking.png] [--at 26]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eagleeye.detectors import Detection  # noqa: E402
from eagleeye.framing import GOLDEN  # noqa: E402
from eagleeye.geometry import View, deg  # noqa: E402
from eagleeye.overlay import COLOR_AIM, COLOR_DET, COLOR_GRID, COLOR_TARGET, annotate  # noqa: E402
from eagleeye.perception import Observation  # noqa: E402
from eagleeye.profiles import TALK  # noqa: E402
from eagleeye.sim import SimScene, simulate  # noqa: E402
from eagleeye.tracker import TrackerState  # noqa: E402

FRAME = (960, 540)
SECONDS = 60.0
LEAN_FROM, LEAN_TO, LEAN_DEG = 10.0, 40.0, 15.0
ARCSEC_PER_DEG = 3600.0

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
# The application's dark palette (app.py), RGB.
BG, PANEL, BORDER = (14, 17, 22), (22, 27, 34), (42, 50, 61)
TEXT, MUTED, ACCENT, WARN = (230, 237, 243), (139, 148, 158), (47, 129, 247), (210, 153, 34)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size)


def person_path(t: float) -> tuple[float, float]:
    """World angles (arcsec) of the head: leans to the side between 10 s and 40 s."""
    pan = deg(LEAN_DEG) if LEAN_FROM <= t < LEAN_TO else 0.0
    return pan, (0.5 - GOLDEN) * View(*FRAME).vfov


class RecordingScene(SimScene):
    """SimScene that notes the camera angles and the head pixel at every step.

    ``HeadModel.angles(t)`` does not keep history (before its last command it answers with the
    previous position), so the plot must be recorded while the simulation runs, not rebuilt after.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.trace: list[tuple[float, float, float, tuple[float, float] | None]] = []

    def observe(self, t, camera, zoom):
        pan, tilt = camera.truth.angles(t)
        self.trace.append((t, pan, tilt, self.head_pixel(t, camera, zoom)))
        return super().observe(t, camera, zoom)


def draw_mannequin(size: tuple[int, int], head: tuple[float, float]) -> np.ndarray:
    """A faceless slate-grey figure on a dark gradient: obviously not a photograph."""
    w, h = size
    ramp = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
    top, bottom = np.array([46, 36, 29], np.float32), np.array([24, 18, 14], np.float32)   # BGR
    img = (top * (1.0 - ramp) + bottom * ramp) * np.ones((1, w, 1), np.float32)
    img = np.ascontiguousarray(img.astype(np.uint8))
    hx, hy = int(head[0]), int(head[1])
    body, skin = (96, 82, 72), (118, 104, 92)                                                # BGR
    cv2.line(img, (0, int(h * 0.84)), (w, int(h * 0.84)), (60, 50, 42), 3, cv2.LINE_AA)       # desk edge
    cv2.ellipse(img, (hx, hy + 150), (150, 92), 0, 180, 360, body, -1, cv2.LINE_AA)           # shoulders
    cv2.rectangle(img, (hx - 150, hy + 150), (hx + 150, h), body, -1)                         # torso
    cv2.rectangle(img, (hx - 17, hy + 20), (hx + 17, hy + 82), skin, -1)                      # neck
    cv2.ellipse(img, (hx, hy), (36, 46), 0, 0, 360, skin, -1, cv2.LINE_AA)                    # head
    return img


def tracker_state(head: tuple[float, float], t: float) -> TrackerState:
    hx, hy = head
    keypoints = tuple([(hx, hy + 6, 0.9), (hx - 13, hy - 7, 0.9), (hx + 13, hy - 7, 0.9),
                       (hx - 31, hy, 0.9), (hx + 31, hy, 0.9)] + [(0.0, 0.0, 0.0)] * 12)
    top = max(0.0, hy - 58)
    box = (hx - 100, top, 200.0, min(FRAME[1] - top - 2, 430.0))
    detection = Detection(int(box[0]), int(box[1]), int(box[2]), int(box[3]), 0.93, "pose", keypoints)
    target = Observation(hx, hy - 1, t, 0.93, "pose", (int(hx) - 20, int(hy) - 20, 40, 40),
                         yaw=0.0, head_scale_px=60.0)
    return TrackerState(enabled=True, frame_size=FRAME, detections=(detection,), target=target,
                        aim=(0.5, GOLDEN))


def rounded(draw: ImageDraw.ImageDraw, box, radius: int, fill=None, outline=None) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=1)


def render(at: float, out: Path) -> dict:
    scene = RecordingScene(person_path, frame=FRAME, seed=1)
    result = simulate(TALK, scene, SECONDS)
    zoom = result.core.actuator.zoom_value                            # type: ignore[attr-defined]

    ts = np.array([row[0] for row in scene.trace])
    person = np.array([person_path(t)[0] for t in ts]) / ARCSEC_PER_DEG
    camera = np.array([row[1] for row in scene.trace]) / ARCSEC_PER_DEG
    zone = TALK.trigger_pan * View(*FRAME, zoom).hfov / ARCSEC_PER_DEG
    start = camera[np.searchsorted(ts, LEAN_FROM)]
    moved = next((t for t, c in zip(ts, camera) if t > LEAN_FROM and abs(c - start) > 0.3), None)
    reaction = None if moved is None else float(moved - LEAN_FROM)

    nearest = int(np.argmin(np.abs(ts - at)))
    head = scene.trace[nearest][3]
    if head is None:
        raise SystemExit(f"the head is outside the frame at t={at}s: pick another --at")
    state = tracker_state(head, at)
    frame = annotate(draw_mannequin(FRAME, head), state)
    preview = Image.fromarray(frame[:, :, ::-1])

    width, height = 1840, 700
    canvas = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.text((30, 22), "EagleEye Control", font=font(26, True), fill=TEXT)
    draw.text((30 + draw.textlength("EagleEye Control", font=font(26, True)) + 16, 31),
              "tracking, simulated", font=font(16), fill=MUTED)

    # --- left: the preview with the overlay
    canvas.paste(preview, (30, 90))
    ImageDraw.Draw(canvas).rounded_rectangle((29, 89, 30 + FRAME[0], 90 + FRAME[1]), radius=6,
                                             outline=BORDER, width=1)
    draw.text((46, 90 + FRAME[1] - 28), "simulated scene", font=font(13), fill=(139, 148, 158, 255))
    chips = [("golden-ratio lines", COLOR_GRID[::-1]), ("aim point", COLOR_AIM[::-1]),
             ("head point", COLOR_TARGET[::-1]), ("detection", COLOR_DET[::-1])]
    x = 30
    for label, rgb in chips:
        draw.ellipse((x, 650, x + 12, 662), fill=rgb + (255,))
        draw.text((x + 20, 646), label, font=font(14), fill=MUTED)
        x += 40 + int(draw.textlength(label, font=font(14)))

    # --- right: person vs camera pan
    px0, py0, px1, py1 = 1030, 90, 1810, 630
    rounded(draw, (px0, py0, px1, py1), 8, fill=PANEL + (255,), outline=BORDER + (255,))
    draw.text((px0 + 24, py0 + 16), "Person vs camera pan", font=font(20, True), fill=TEXT)
    draw.text((px0 + 24, py0 + 46), f"talk profile: the person leans {LEAN_DEG:.0f}° at {LEAN_FROM:.0f} s "
              f"and returns at {LEAN_TO:.0f} s", font=font(13), fill=MUTED)

    ax0, ax1, ay0, ay1 = px0 + 70, px1 - 30, py0 + 110, py1 - 56
    lo, hi = -6.0, 22.0

    def sx(t: float) -> float:
        return ax0 + (t / SECONDS) * (ax1 - ax0)

    def sy(angle: float) -> float:
        return ay1 - ((angle - lo) / (hi - lo)) * (ay1 - ay0)

    for angle in range(0, 21, 5):
        draw.line((ax0, sy(angle), ax1, sy(angle)), fill=BORDER + (255,), width=1)
        draw.text((ax0 - 12, sy(angle)), f"{angle}°", font=font(12), fill=MUTED, anchor="rm")
    for t in range(0, 61, 10):
        draw.line((sx(t), ay0, sx(t), ay1), fill=BORDER + (120,), width=1)
        draw.text((sx(t), ay1 + 10), f"{t} s", font=font(12), fill=MUTED, anchor="mt")

    def clip(y: float) -> float:
        return min(max(y, ay0), ay1)

    upper = [(sx(t), clip(sy(c + zone))) for t, c in zip(ts, camera)]
    lower = [(sx(t), clip(sy(c - zone))) for t, c in zip(ts, camera)]
    draw.polygon(upper + lower[::-1], fill=WARN + (46,))
    draw.line([(sx(t), sy(p)) for t, p in zip(ts, person)], fill=ACCENT + (255,), width=3, joint="curve")
    draw.line([(sx(t), sy(c)) for t, c in zip(ts, camera)], fill=WARN + (255,), width=3, joint="curve")

    mark = sx(at)
    for y in range(int(ay0), int(ay1), 10):
        draw.line((mark, y, mark, y + 5), fill=MUTED + (255,), width=1)
    draw.text((mark + 6, ay0 + 4), "preview frame", font=font(12), fill=MUTED)
    if reaction is not None:
        note = f"the camera answers once, after {reaction:.1f} s"
        nx, ny = sx(LEAN_FROM) + 14, sy(LEAN_DEG) - 34
        w = draw.textlength(note, font=font(13))
        rounded(draw, (nx - 6, ny - 4, nx + w + 6, ny + 20), 4, fill=PANEL + (255,))
        draw.text((nx, ny), note, font=font(13), fill=TEXT)

    lx, ly = ax0 + 10, py1 - 28
    for label, rgb, kind in (("person (world angle)", ACCENT, "line"), ("camera pan", WARN, "line"),
                             ("trigger zone", WARN, "band")):
        if kind == "line":
            draw.line((lx, ly + 8, lx + 26, ly + 8), fill=rgb + (255,), width=3)
        else:
            draw.rectangle((lx, ly, lx + 26, ly + 16), fill=rgb + (70,))
        draw.text((lx + 36, ly), label, font=font(13), fill=MUTED)
        lx += 60 + int(draw.textlength(label, font=font(13)))

    draw.text((30, height - 30),
              "Simulated: a synthetic person in the closed-loop simulator (eagleeye/sim.py); the overlay is "
              "drawn by eagleeye/overlay.py. Not a camera recording.", font=font(13), fill=MUTED)

    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, optimize=True)
    return {"head_px": head, "reaction_s": reaction, "zone_deg": zone, "camera_end_deg": float(camera[-1])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "assets" / "screenshot-tracking.png")
    parser.add_argument("--at", type=float, default=26.0, help="second of the simulation shown as the preview")
    args = parser.parse_args()
    info = render(args.at, args.out)
    print(f"wrote {args.out}  {info}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
