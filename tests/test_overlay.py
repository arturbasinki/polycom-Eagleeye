#!/usr/bin/env python3
"""Rysowanie wykryć i strefy na podglądzie.

    .venv/bin/python tests/test_overlay.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye import i18n  # noqa: E402
from eagleeye.detectors import Detection  # noqa: E402
from eagleeye.framing import GOLDEN  # noqa: E402
from eagleeye.i18n import msg  # noqa: E402
from eagleeye.identity import TrackInfo  # noqa: E402
from eagleeye.overlay import Shape, annotate, frame_point, overlay_shapes, selection_text  # noqa: E402
from eagleeye.perception import Observation  # noqa: E402
from eagleeye.tracker import TrackerState  # noqa: E402


def test_detections_are_scaled_to_preview_size() -> None:
    state = TrackerState(enabled=True, detections=(Detection(100, 50, 40, 40, 0.9, "twarz"),),
                         target=Observation(120.0, 70.0, 0.0, 0.9, "twarz", (100, 50, 40, 40)),
                         frame_size=(960, 540), zones=(0.15, 0.12))
    out = annotate(np.zeros((1080, 1920, 3), np.uint8), state)
    assert out[100:180, 200:280].any(), "ramka wykrycia w skali 2x"
    assert out[140, 240].any(), "punkt głowy celu"


def test_head_keypoints_are_drawn() -> None:
    kps = [(0.0, 0.0, 0.0)] * 17
    kps[0] = (500.0, 300.0, 0.9)          # nos, w skali 2x -> (1000, 600)
    kps[5] = (520.0, 400.0, 0.9)          # bark - nie rysujemy
    state = TrackerState(enabled=True, frame_size=(960, 540), zones=(0.0, 0.0),
                         detections=(Detection(400, 250, 200, 280, 0.9, "poza", tuple(kps)),))
    out = annotate(np.zeros((1080, 1920, 3), np.uint8), state)
    assert out[600, 1000].any(), "punkt nosa"
    assert not out[800, 1040].any(), "barki nie są punktami głowy"


def test_disabled_state_draws_nothing() -> None:
    frame = np.zeros((540, 960, 3), np.uint8)
    assert not annotate(frame, TrackerState()).any()


def _state() -> TrackerState:
    kps = [(0.0, 0.0, 0.0)] * 17
    kps[0] = (500.0, 300.0, 0.9)          # nos
    kps[5] = (520.0, 400.0, 0.9)          # bark - nie rysujemy
    return TrackerState(enabled=True, frame_size=(960, 540), zones=(0.15, 0.12),
                        detections=(Detection(400, 250, 200, 280, 0.9, "poza", tuple(kps)),),
                        target=Observation(500.0, 300.0, 0.0, 0.9, "poza", (400, 250, 200, 280)))


def test_shapes_map_to_top_aligned_image() -> None:
    # okno 1000x1000, obraz 16:9 wyrównany do górnej krawędzi: wysokość 562.5, pas tylko na dole
    shapes = overlay_shapes(_state(), 1000, 1000)
    det = next(s for s in shapes if s.kind == "rect" and s.label)
    k = 1000 / 960
    assert abs(det.x - 400 * k) < 0.01 and abs(det.y - 250 * k) < 0.01
    assert abs(det.w - 200 * k) < 0.01 and abs(det.h - 280 * k) < 0.01
    assert det.label == "poza 0.90"


def test_shapes_pillarbox_golden_grid_and_aim() -> None:
    # okno szersze niż 16:9: pasy po bokach; linie i punkty złotego podziału w obrazie
    shapes = overlay_shapes(_state(), 2000, 900)
    k = 900 / 540
    ox = (2000 - 960 * k) / 2
    iw, ih = 960 * k, 540 * k
    lines = [s for s in shapes if s.kind == "line"]
    assert len(lines) == 4
    xs = sorted(s.x for s in lines if s.x == s.x2)
    assert [round(x, 2) for x in xs] == [round(ox + GOLDEN * iw, 2), round(ox + (1 - GOLDEN) * iw, 2)]
    rings = [(round(s.x, 2), round(s.y, 2)) for s in shapes if s.kind == "ring" and s.r == 5]
    assert sorted(rings) == sorted((round(ox + gx * iw, 2), round(gy * ih, 2))
                                   for gx in (GOLDEN, 1 - GOLDEN) for gy in (GOLDEN, 1 - GOLDEN))
    aim = [s for s in shapes if s.kind == "ring" and s.r == 14]
    assert len(aim) == 1 and abs(aim[0].x - (ox + 0.5 * iw)) < 0.01 and abs(aim[0].y - GOLDEN * ih) < 0.01


def test_no_trigger_zone_box() -> None:
    # Prostokąt strefy wyzwalania usunięty: kadr ocenia się po punkcie złotego podziału.
    shapes = overlay_shapes(_state(), 960, 540)
    assert [s for s in shapes if s.kind == "rect" and not s.label] == []


def test_aim_point_follows_side() -> None:
    state = TrackerState(enabled=True, frame_size=(960, 540), zones=(0.15, 0.12), aim=(GOLDEN, GOLDEN))
    aim = [s for s in overlay_shapes(state, 960, 540) if s.kind == "ring" and s.r == 14]
    assert abs(aim[0].x - GOLDEN * 960) < 0.01 and abs(aim[0].y - GOLDEN * 540) < 0.01


def test_shapes_head_points_and_target() -> None:
    shapes = overlay_shapes(_state(), 960, 540)
    heads = [s for s in shapes if s.kind == "dot" and s.r == 4]
    assert [(s.x, s.y) for s in heads] == [(500.0, 300.0)], "tylko punkty głowy, bez barku"
    target = [s for s in shapes if s.kind == "dot" and s.r == 8]
    assert [(s.x, s.y) for s in target] == [(500.0, 300.0)]


def test_no_shapes_when_disabled_or_unsized() -> None:
    assert overlay_shapes(TrackerState(enabled=False, frame_size=(960, 540)), 800, 450) == []
    assert overlay_shapes(_state(), 0, 0) == []
    assert all(isinstance(s, Shape) for s in overlay_shapes(_state(), 800, 450))


def test_golden_grid_and_aim_point_are_drawn() -> None:
    state = TrackerState(enabled=True, frame_size=(960, 540), zones=(0.15, 0.12), aim=(0.382, 0.382))
    out = annotate(np.zeros((1080, 1920, 3), np.uint8), state)
    assert out[100, int(0.618 * 1920)].any(), "pionowa linia złotego podziału"
    assert out[int(0.382 * 1080), int(0.382 * 1920)].any(), "punkt docelowy"
    assert out[int(0.618 * 1080), int(0.618 * 1920) + 5].any(), "punkt przecięcia (dolny prawy)"



def _tracked(selection: str, left: float = 0.0) -> TrackerState:
    info = TrackInfo(1, (400, 250, 200, 280), (500.0, 300.0), selection == "selected")
    return replace(_state(), tracks=(info,), selection=selection, selected_id=1, selection_left=left)


def test_frame_point_inverts_the_overlay_geometry() -> None:
    # Kliknięcie w lewy górny róg ramki na nakładce musi wrócić jako róg ramki w klatce -
    # dla okna kwadratowego (pas na dole) i szerokiego (pasy po bokach).
    for box_w, box_h in ((1000, 1000), (2000, 900), (500, 900)):
        det = next(s for s in overlay_shapes(_state(), box_w, box_h) if s.kind == "rect" and s.label)
        fx, fy = frame_point(box_w, box_h, (960, 540), det.x, det.y)
        assert abs(fx - 400) < 1e-6 and abs(fy - 250) < 1e-6, (box_w, box_h)


def test_frame_point_outside_the_image_is_none() -> None:
    assert frame_point(2000, 900, (960, 540), 100, 400) is None, "pas po lewej"
    assert frame_point(1000, 1000, (960, 540), 500, 800) is None, "pas pod obrazem"
    assert frame_point(1000, 1000, (960, 540), -1, 10) is None
    assert frame_point(0, 0, (960, 540), 10, 10) is None
    assert frame_point(1000, 1000, (0, 0), 10, 10) is None, "brak klatki"


def test_selection_labels_follow_the_language() -> None:
    try:
        i18n.set_language("en")
        labels = [s.label for s in overlay_shapes(_tracked("selected"), 960, 540) if s.kind == "rect"]
        assert "following #1" in labels
        labels = [s.label for s in overlay_shapes(_tracked("suspended", 4.2), 960, 540) if s.kind == "rect"]
        assert "searching… 4 s" in labels and not any(l.startswith("following") for l in labels)
        i18n.set_language("pl")
        labels = [s.label for s in overlay_shapes(_tracked("selected"), 960, 540) if s.kind == "rect"]
        assert "śledzę #1" in labels
    finally:
        i18n.set_language("en")


def test_selection_text_returns_messages() -> None:
    assert selection_text(_tracked("selected")) == msg("selection.selected", id=1)
    assert selection_text(_tracked("suspended", 4.2)) == msg("selection.suspended", seconds="4")
    note = msg("identity.selection_lost")
    assert selection_text(replace(_state(), selection_note=note)) == note
    assert selection_text(_state()) is None

if __name__ == "__main__":
    run(globals(), "Rysowanie wykryć")
