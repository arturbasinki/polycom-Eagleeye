#!/usr/bin/env python3
"""Person identity: world paths, clothing color, target selection.

    .venv/bin/python tests/test_identity.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.detectors import Detection  # noqa: E402
from eagleeye.i18n import msg  # noqa: E402
from eagleeye.identity import (AUTO, RETAIN_S, SELECTED, SUSPENDED, PersonTracker,  # noqa: E402
                               TargetSelection, TrackInfo, track_at, track_infos)

W, H = 960, 540
RED, BLUE, GREEN = (0, 0, 255), (255, 0, 0), (0, 255, 0)
FPS = 15.0


def to_world(x: float, y: float) -> tuple[float, float]:
    """Constant scale 100 arcsec/px, tilt rises upward - like View at zoom 0 (simplified)."""
    return x * 100.0, -y * 100.0


def scene(*people):
    """Frame with colored torsos and the list of detections; person = (center x, top y, color)."""
    frame = np.full((H, W, 3), 40, np.uint8)
    dets = []
    for cx, top, color in people:
        h, w = 300, 100
        x0 = int(cx - w / 2)
        frame[int(top + 0.2 * h):int(top + 0.6 * h), x0 + 10:x0 + w - 10] = color
        kps = [(0.0, 0.0, 0.05)] * 17
        kps[0] = (cx, top + 0.05 * h, 0.9)
        kps[1] = (cx + 6, top + 0.04 * h, 0.9)
        kps[2] = (cx - 6, top + 0.04 * h, 0.9)
        kps[5] = (cx + 30, top + 0.2 * h, 0.9)
        kps[6] = (cx - 30, top + 0.2 * h, 0.9)
        kps[11] = (cx + 25, top + 0.55 * h, 0.9)
        kps[12] = (cx - 25, top + 0.55 * h, 0.9)
        dets.append(Detection(x0, int(top), w, h, 0.9, "poza", tuple(kps)))
    return frame, dets


def feed(pt: PersonTracker, t: float, *people, cam: float = 0.0, **kw):
    """``cam``: camera shift in pixels - world = pixel + cam (the camera turned)."""
    frame, dets = scene(*people)
    return pt.update(dets, frame, t, lambda x, y: to_world(x + cam, y), **kw)


def by_color(tracks, det_cx):
    return next(tr for tr in tracks if tr.det is not None and abs(tr.det.x + 50 - det_cx) < 2)


def test_ids_stay_stable_while_walking() -> None:
    pt = PersonTracker()
    first = feed(pt, 0.0, (200, 100, RED))[0].id
    for i in range(1, 40):
        tracks = feed(pt, i / FPS, (200 + 4 * i, 100, RED))
    assert [tr.id for tr in tracks] == [first]


def test_crossing_people_keep_their_ids() -> None:
    pt = PersonTracker()
    tracks = feed(pt, 0.0, (300, 100, RED), (600, 100, BLUE))
    red_id = by_color(tracks, 300).id
    blue_id = by_color(tracks, 600).id
    for i in range(1, 46):                        # they come together, pass and separate
        tracks = feed(pt, i / FPS, (300 + 10 * i, 100, RED), (600 - 10 * i, 100, BLUE))
    assert by_color(tracks, 750).id == red_id
    assert by_color(tracks, 150).id == blue_id


def test_camera_jump_keeps_the_same_person() -> None:
    """An absolute camera move shifts the person in pixels by 300 px in one frame; in the world they stand still."""
    pt = PersonTracker()
    tid = feed(pt, 0.0, (400, 100, RED))[0].id
    tracks = feed(pt, 0.07, (100, 100, RED), cam=300.0)
    assert [tr.id for tr in tracks] == [tid] and tracks[0].det is not None


def test_person_at_the_frame_edge_does_not_break() -> None:
    """The box sticks out beyond the frame, the torso almost out of the image: no exception, the path exists."""
    pt = PersonTracker()
    tid = feed(pt, 0.0, (10, 100, RED))[0].id
    tracks = feed(pt, 0.07, (12, 100, RED))
    assert [tr.id for tr in tracks] == [tid]


def test_returning_person_wins_over_a_closer_stranger() -> None:
    """Motion alone would pick a stranger (closer to the last spot); the clothing color points to the right person."""
    pt = PersonTracker()
    tid = feed(pt, 0.0, (400, 100, RED))[0].id
    feed(pt, 0.5, protect=tid, protect_s=6.0)
    tracks = feed(pt, 1.0, (405, 100, BLUE), (470, 100, RED), protect=tid, protect_s=6.0)
    back = next(tr for tr in tracks if tr.id == tid)
    assert back.det is not None and abs(back.det.x + 50 - 470) < 2


def test_same_person_is_recognised_after_short_absence() -> None:
    pt = PersonTracker()
    tid = feed(pt, 0.0, (400, 100, RED))[0].id
    for i in range(1, 30):                        # 2 s without a detection
        feed(pt, i / FPS, protect=tid, protect_s=6.0)
    tracks = feed(pt, 2.0, (420, 100, RED), protect=tid, protect_s=6.0)
    assert [tr.id for tr in tracks] == [tid] and tracks[0].det is not None


def test_stranger_in_the_same_place_is_not_adopted() -> None:
    pt = PersonTracker()
    tid = feed(pt, 0.0, (400, 100, RED))[0].id
    feed(pt, 0.5, protect=tid, protect_s=6.0)
    tracks = feed(pt, 1.0, (400, 100, GREEN), protect=tid, protect_s=6.0)
    ids = {tr.id: tr for tr in tracks}
    assert ids[tid].det is None, "a suspended path does not adopt a stranger"
    assert len(tracks) == 2


def test_ambiguous_candidates_do_not_reacquire() -> None:
    pt = PersonTracker()
    tid = feed(pt, 0.0, (400, 100, RED))[0].id
    feed(pt, 0.5, protect=tid, protect_s=6.0)
    tracks = feed(pt, 1.0, (390, 100, RED), (415, 100, RED), protect=tid, protect_s=6.0)
    assert next(tr for tr in tracks if tr.id == tid).det is None


def test_two_similar_strangers_after_a_longer_gap_are_not_adopted() -> None:
    """After 2 s, position weighs little (a gate of ~2 body heights), so two strangers in similar
    clothing must not be decided by distance: a suspended path does not guess."""
    pt = PersonTracker()
    tid = feed(pt, 0.0, (500, 100, RED))[0].id
    feed(pt, 1.0, protect=tid, protect_s=6.0)
    similar = (10, 10, 240)
    tracks = feed(pt, 2.0, (560, 100, similar), (700, 100, similar), protect=tid, protect_s=6.0)
    assert next(tr for tr in tracks if tr.id == tid).det is None


def test_protected_track_outlives_retention() -> None:
    pt = PersonTracker()
    keep = feed(pt, 0.0, (300, 100, RED), (600, 100, BLUE))
    red = by_color(keep, 300).id
    blue = by_color(keep, 600).id
    tracks = feed(pt, RETAIN_S + 1.0, protect=red, protect_s=6.0)
    assert [tr.id for tr in tracks] == [red] and blue not in pt.tracks


def test_new_person_gets_new_id() -> None:
    pt = PersonTracker()
    a = feed(pt, 0.0, (300, 100, RED))[0].id
    tracks = feed(pt, 0.1, (300, 100, RED), (700, 100, BLUE))
    assert len({tr.id for tr in tracks}) == 2 and a in {tr.id for tr in tracks}


def test_person_without_visible_torso_still_tracks() -> None:
    pt = PersonTracker()
    frame, dets = scene((400, 100, RED))
    bare = Detection(dets[0].x, dets[0].y, dets[0].w, dets[0].h, 0.9, "poza", None)
    tid = pt.update([bare], frame, 0.0, to_world)[0].id
    tracks = pt.update([bare], frame, 0.1, to_world)
    assert [tr.id for tr in tracks] == [tid]


def test_track_at_prefers_the_closer_head_and_skips_hidden() -> None:
    infos = (TrackInfo(1, (100, 100, 200, 300), (200.0, 120.0), True),
             TrackInfo(2, (150, 100, 200, 300), (250.0, 120.0), True),
             TrackInfo(3, (0, 0, 50, 50), (25.0, 10.0), False))
    assert track_at(infos, 240, 200) == 2
    assert track_at(infos, 160, 200) == 1
    assert track_at(infos, 20, 20) is None, "a suspended one is not clickable"
    assert track_at(infos, 900, 500) is None


def test_track_infos_mark_visibility() -> None:
    pt = PersonTracker()
    tid = feed(pt, 0.0, (400, 100, RED))[0].id
    seen = track_infos(feed(pt, 0.05, (400, 100, RED)))[0]
    assert seen.visible and seen.box == (350, 100, 100, 300)
    hidden = track_infos(feed(pt, 0.1, protect=tid, protect_s=6.0))
    assert hidden == (TrackInfo(tid, seen.box, seen.head, False),), "a suspended one remembers the last box"


class _T:
    def __init__(self, tid, visible):
        self.id, self.det = tid, (object() if visible else None)


def test_selection_lifecycle() -> None:
    sel = TargetSelection(hold_s=6.0)
    assert sel.state == AUTO and sel.resolve([_T(1, True)], 0.0) is None
    sel.select(1, 0.0)
    assert sel.resolve([_T(1, True)], 0.1).id == 1 and sel.state == SELECTED
    assert sel.resolve([_T(1, False)], 0.3) is None and sel.state == SELECTED, "a short gap"
    assert sel.resolve([_T(1, False)], 1.0) is None and sel.state == SUSPENDED
    assert abs(sel.remaining(1.0) - 5.1) < 1e-6
    assert sel.resolve([_T(1, True)], 3.0).id == 1 and sel.state == SELECTED, "return"


def test_selection_expires_to_auto() -> None:
    sel = TargetSelection(hold_s=6.0)
    sel.select(1, 0.0)
    sel.resolve([_T(1, False)], 3.0)
    assert sel.resolve([_T(1, False)], 6.5) is None
    assert sel.state == AUTO and sel.track_id is None and sel.event == msg("identity.selection_lost")
    sel.select(2, 7.0)
    assert sel.event is None and sel.state == SELECTED


def test_selection_clear_and_missing_track() -> None:
    sel = TargetSelection(hold_s=6.0)
    sel.select(5, 0.0)
    assert sel.resolve([], 1.0) is None and sel.state == SUSPENDED
    sel.clear()
    assert sel.state == AUTO and sel.track_id is None


def test_selection_state_values_are_english_codes() -> None:
    assert (AUTO, SELECTED, SUSPENDED) == ("auto", "selected", "suspended")


if __name__ == "__main__":
    run(globals(), "Person identity")
