#!/usr/bin/env python3
"""Reżyser: histereza, zwłoka, kadrowanie, wyprzedzenie, podążanie.

Zamiast sprzętu: prawdziwy HeadModel, do którego od razu stosujemy rozkazy.

    .venv/bin/python tests/test_director.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.director import Director, Limits, REFIT_DWELL, ZOOM_DWELL, ZOOM_WITH_PAN_TILT  # noqa: E402
from eagleeye.framing import GOLDEN, SHOTS, Shot, zoom_goal  # noqa: E402
from eagleeye.geometry import View, deg  # noqa: E402
from eagleeye.head_model import Dynamics, HeadModel  # noqa: E402
from eagleeye.profiles import PREZENTACJA, ROZMOWA  # noqa: E402
from eagleeye.target_filter import TargetEstimate  # noqa: E402

DYN = Dynamics()
LIM = Limits(-deg(170), deg(170), -deg(30), deg(90))
VIEW = View(1280, 720)
DT = 1 / 15


def framed_tilt(_profile=None, cam_tilt: float = 0.0) -> float:
    """Kąt świata głowy, która przy danym tilcie kamery jest dokładnie na linii złotego podziału
    (wspólnej dla profili - parametr profilu zostaje dla zgodności wywołań)."""
    return cam_tilt + (0.5 - GOLDEN) * VIEW.vfov


def est(pan: float, tilt: float, t: float, v_pan: float = 0.0, v_tilt: float = 0.0,
        yaw=None, scale=None) -> TargetEstimate:
    return TargetEstimate(pan, tilt, v_pan, v_tilt, t, t, yaw=yaw, head_scale=scale)


def apply(head: HeadModel, cmds, t: float) -> None:
    for c in cmds:
        if c.kind == "abs":
            head.command_absolute(c.axis, c.value, t)
        elif c.kind == "vel":
            head.command_velocity(c.axis, int(c.value), t)


def simulate(director: Director, head: HeadModel, seconds: float, est_fn, t0: float = 0.0):
    """Pętla reżysera; ``est_fn(t, head)`` zwraca estymatę albo None. Zwraca [(t, Command)]."""
    log = []
    n = int(seconds / DT)
    for i in range(n):
        t = t0 + i * DT
        cmds = director.tick(t, est_fn(t, head), head, VIEW)
        apply(head, cmds, t)
        log += [(t, c) for c in cmds]
    return log


def test_brief_excursion_shorter_than_dwell_is_ignored() -> None:
    d, h = Director(ROZMOWA, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 5.0, lambda t, _: est(0.3 * VIEW.hfov if 1.0 <= t < 1.5 else 0.0,
                                               framed_tilt(ROZMOWA), t))
    assert log == []


def test_sustained_offset_moves_once_exactly_to_aim() -> None:
    d, h = Director(ROZMOWA, LIM, DYN), HeadModel(DYN)
    aim = 0.3 * VIEW.hfov
    log = simulate(d, h, 6.0, lambda t, _: est(aim, framed_tilt(ROZMOWA), t))
    pans = [c for _, c in log if c.axis == "pan"]
    assert len(pans) == 1 and pans[0].kind == "abs" and abs(pans[0].value - aim) < 1e-6
    assert abs(log[0][0] - ROZMOWA.dwell) < 2 * DT


def test_tilt_frames_head_on_golden_line() -> None:
    # Głowa startuje poza strefą wyzwalania (odchylenie 0,182 vfov > 0,12 vfov) - test
    # sprawdza dokładność dojazdu na linię złotego podziału jednym ruchem.
    d, h = Director(ROZMOWA, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 3.0, lambda t, _: est(0.0, 0.3 * VIEW.vfov, t))
    tilts = [c for _, c in log if c.axis == "tilt"]
    assert len(tilts) == 1
    assert abs(tilts[0].value - (0.3 * VIEW.vfov - (0.5 - GOLDEN) * VIEW.vfov)) < 1e-6


def test_tilt_frames_head_from_within_old_zone() -> None:
    # Kalibracja (2026-09-25): głowa 3° poniżej linii złotego podziału leżała w strefie
    # 0,12 vfov (≈4,9°), więc kamera nigdy nie ustawiała jej na linii (pierwszy rozkaz
    # tiltu w całej sesji po 92 s). Dziś naprawia to pasmo kompozycji (5%) i cichy re-fit -
    # jednym ruchem, dokładnie na linię (a nie strefa zmniejszona do 2°, która goniła kiwnięcia).
    d, h = Director(ROZMOWA, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 6.0, lambda t, _: est(0.0, framed_tilt(ROZMOWA) - deg(3), t))
    tilts = [c for _, c in log if c.axis == "tilt"]
    assert len(tilts) == 1, [c.value for _, c in log]
    assert abs(tilts[0].value + deg(3)) < 1e-6


def test_rest_off_point_reframes_after_refit_dwell() -> None:
    # Odbiór 2026-09-25: użytkownik przeniósł fotel - głowa osiadła 10% szerokości od
    # punktu złotego podziału (w strefie wyzwalania 15%); sama strefa zostawiałaby kadr
    # w tym stanie na stałe (kryterium 1: błąd ≤ 5%). Cichy re-fit po REFIT_DWELL.
    d, h = Director(ROZMOWA, LIM, DYN), HeadModel(DYN)
    offset = 0.10 * VIEW.hfov
    log = simulate(d, h, 6.0, lambda t, _: est(offset, framed_tilt(ROZMOWA), t))
    pans = [c for _, c in log if c.axis == "pan"]
    assert len(pans) == 1, [(t, c.value) for t, c in log]
    assert abs(pans[0].value - offset) < 1e-6
    assert abs(log[0][0] - REFIT_DWELL) < 2 * DT


def test_rest_inside_composition_band_never_moves() -> None:
    d, h = Director(ROZMOWA, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 8.0, lambda t, _: est(0.04 * VIEW.hfov, framed_tilt(ROZMOWA), t))
    assert log == []


def test_brief_mid_band_excursion_does_not_refit() -> None:
    # Wycieczka 10% szerokości trwająca 2 s (gest) - za krótka, by liczyć się za nową
    # pozycję spoczynkową.
    d, h = Director(ROZMOWA, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 8.0, lambda t, _: est(0.10 * VIEW.hfov if 2.0 <= t < 4.0 else 0.0,
                                               framed_tilt(ROZMOWA), t))
    assert log == []


def test_turning_head_moves_face_to_opposite_golden_point() -> None:
    d, h = Director(ROZMOWA, LIM, DYN), HeadModel(DYN)
    tilt = framed_tilt()
    log = simulate(d, h, 6.0, lambda t, _: est(0.0, tilt, t, yaw=0.6 if t >= 1.0 else 0.0))
    pans = [(t, c.value) for t, c in log if c.axis == "pan"]
    assert len(pans) == 1, pans
    t_move, value = pans[0]
    assert abs(t_move - (1.0 + ROZMOWA.side_dwell)) < 2 * DT
    x, _ = VIEW.world_to_pixel(0.0, tilt, value, 0.0)
    assert abs(x - GOLDEN * VIEW.frame_w) < 1.0


def test_turning_head_to_other_side_is_one_pan_move() -> None:
    # Zgłoszone 2026-09-26: nos w lewo -> nos w prawo przechodziło przez punkt środkowy
    # (dwa ruchy). Ma być jeden ruch, wprost na przeciwny punkt złotego podziału.
    d, h = Director(ROZMOWA, LIM, DYN), HeadModel(DYN)
    tilt = framed_tilt()
    yaw = lambda t: 0.6 if t < 6.0 else -0.6
    log = simulate(d, h, 12.0, lambda t, _: est(0.0, tilt, t, yaw=yaw(t)))
    pans = [(t, c.value) for t, c in log if c.axis == "pan" and t >= 6.0]
    assert len(pans) == 1, pans
    x, _ = VIEW.world_to_pixel(0.0, tilt, pans[0][1], 0.0)
    assert abs(x - (1 - GOLDEN) * VIEW.frame_w) < 1.0


def test_frontal_face_stays_centered() -> None:
    d, h = Director(ROZMOWA, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 6.0, lambda t, _: est(0.0, framed_tilt(), t, yaw=0.1))
    assert log == []


def test_no_retarget_before_60_percent_of_move() -> None:
    d, h = Director(ROZMOWA, LIM, DYN), HeadModel(DYN)
    first = 0.3 * VIEW.hfov
    moved_at: list[float] = []

    def target(t, head):
        if head.target("pan") is not None and not moved_at:
            moved_at.append(t)
        pan = first if not moved_at else 0.9 * VIEW.hfov
        return est(pan, framed_tilt(ROZMOWA), t)

    log = simulate(d, h, 6.0, target)
    pans = [(t, c) for t, c in log if c.axis == "pan"]
    assert len(pans) == 2
    t_second = pans[1][0]
    h2 = HeadModel(DYN)
    h2.command_absolute("pan", first, pans[0][0])
    assert h2.progress("pan", t_second) >= 0.6


def test_lead_in_presentation_moves_past_aim() -> None:
    d, h = Director(PREZENTACJA, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 1.0, lambda t, _: est(0.3 * VIEW.hfov, framed_tilt(PREZENTACJA), t, v_pan=deg(4)))
    pans = [c for _, c in log if c.axis == "pan" and c.kind == "abs"]
    assert pans and pans[0].value > 0.3 * VIEW.hfov


def test_presentation_lead_is_bounded() -> None:
    # Sesja 20260926-150210: szybki podjazd fotelem blisko kamery - głowa przy krawędzi,
    # prędkość kątowa z filtra ~60°/s, a wyprzedzenie v × ~0,5 s dawało rozkazy pan
    # +110° i -110°. Wyprzedzenie jest dla idącej osoby: prędkość do 25°/s, najwyżej 1/4 kadru.
    from eagleeye.director import LEAD_MAX_FOV
    d, h = Director(PREZENTACJA, LIM, DYN), HeadModel(DYN)
    aim = 0.3 * VIEW.hfov
    # Prędkość w stronę środka kadru - bez podążania, ruch absolutny z wyprzedzeniem.
    log = simulate(d, h, 1.0, lambda t, _: est(aim, framed_tilt(), t, v_pan=-deg(60)))
    pans = [c for _, c in log if c.axis == "pan" and c.kind == "abs"]
    assert pans, log
    assert aim - LEAD_MAX_FOV * VIEW.hfov - 1e-6 <= pans[0].value < aim, [c.value for c in pans]


def test_presentation_lead_is_pan_only() -> None:
    # Pionowa "prędkość" to kiwanie głową, nie chód: wyprzedzenie wystrzeliwało tilt ponad
    # cel, a drugi ruch wracał (sesja 20260926-011024, t=191,9 s).
    d, h = Director(PREZENTACJA, LIM, DYN), HeadModel(DYN)
    tilt = framed_tilt() + 0.3 * VIEW.vfov
    log = simulate(d, h, 1.0, lambda t, _: est(0.0, tilt, t, v_tilt=deg(6)))
    tilts = [c for _, c in log if c.axis == "tilt"]
    assert len(tilts) == 1 and abs(tilts[0].value - 0.3 * VIEW.vfov) < 1e-6, [c.value for c in tilts]


def test_nod_inside_tilt_zone_does_not_move() -> None:
    # Kiwnięcie ±2,5° (pionowe gesty w rozmowie) mieści się w strefie tiltu i wraca do pasma
    # kompozycji, zanim upłynie REFIT_DWELL - kamera stoi.
    import math
    for profile in (ROZMOWA, PREZENTACJA):
        d, h = Director(profile, LIM, DYN), HeadModel(DYN)
        log = simulate(d, h, 10.0, lambda t, _: est(0.0, framed_tilt() + deg(2.5) * math.sin(t * 4.0), t))
        assert log == [], (profile.name, [(t, c.axis, c.value) for t, c in log])


def test_pan_waits_for_side_decision_then_moves_once() -> None:
    # Krok w bok z odwróceniem twarzy: ruch pozycji ruszał przed rozstrzygnięciem strony,
    # a zmiana strony 1-1,5 s później wymuszała drugi ruch (sesja 20260926-011024, np.
    # t=1248-1250 s). Pan czeka na decyzję strony i jedzie raz, do punktu nowej strony.
    d, h = Director(ROZMOWA, LIM, DYN), HeadModel(DYN)
    tilt = framed_tilt()
    offset = 0.25 * VIEW.hfov
    log = simulate(d, h, 6.0, lambda t, _: est(offset if t >= 1.0 else 0.0, tilt, t,
                                               yaw=0.6 if t >= 1.0 else 0.0))
    pans = [(t, c.value) for t, c in log if c.axis == "pan"]
    assert len(pans) == 1, pans
    t_move, value = pans[0]
    assert t_move >= 1.0 + ROZMOWA.side_dwell - 2 * DT
    x, _ = VIEW.world_to_pixel(offset, tilt, value, 0.0)
    assert abs(x - GOLDEN * VIEW.frame_w) < 1.0


def test_target_near_edge_does_not_wait_for_side() -> None:
    # Cel przy krawędzi (idzie) nie czeka na stronę - utrata byłaby gorsza niż dwa ruchy.
    d, h = Director(ROZMOWA, LIM, DYN), HeadModel(DYN)
    offset = 0.42 * VIEW.hfov
    log = simulate(d, h, 2.0, lambda t, _: est(offset, framed_tilt(), t, yaw=0.6))
    pans = [t for t, c in log if c.axis == "pan"]
    assert pans and pans[0] < ROZMOWA.side_dwell


def test_target_beyond_limit_does_not_spam_moves() -> None:
    d = Director(ROZMOWA, LIM, DYN)
    h = HeadModel(DYN, pan=LIM.pan_max)
    log = simulate(d, h, 10.0, lambda t, _: est(LIM.pan_max + 0.4 * VIEW.hfov, framed_tilt(ROZMOWA), t))
    assert [c for _, c in log if c.axis == "pan"] == []


def test_fast_walker_triggers_follow_then_brake_then_absolute() -> None:
    d, h = Director(PREZENTACJA, LIM, DYN), HeadModel(DYN)
    v = deg(20)
    log = simulate(d, h, 4.0, lambda t, _: est(0.12 * VIEW.hfov + v * t, framed_tilt(PREZENTACJA), t, v_pan=v))
    pan = [(c.kind, c.value) for _, c in log if c.axis == "pan"]
    assert ("vel", 1) in pan
    start = pan.index(("vel", 1))
    stop = pan.index(("vel", 0), start)
    assert pan[start:stop].count(("vel", 1)) > 1, "podążanie musi odświeżać rozkaz dla strażnika"
    assert any(k == "abs" for k, _ in pan[stop:]), "po hamowaniu dojazd absolutny"


def test_rozmowa_never_uses_velocity() -> None:
    d, h = Director(ROZMOWA, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 4.0, lambda t, _: est(0.2 * VIEW.hfov + deg(20) * t, framed_tilt(ROZMOWA), t,
                                               v_pan=deg(20)))
    assert all(c.kind != "vel" for _, c in log)


def test_tilt_never_uses_velocity() -> None:
    d, h = Director(PREZENTACJA, LIM, DYN), HeadModel(DYN)
    log = simulate(d, h, 3.0, lambda t, _: est(0.0, framed_tilt(PREZENTACJA) + deg(20) * t, t,
                                               v_tilt=deg(20)))
    assert all(not (c.axis == "tilt" and c.kind == "vel") for _, c in log)


def test_follow_stops_before_pan_limit() -> None:
    d = Director(PREZENTACJA, LIM, DYN)
    h = HeadModel(DYN, pan=deg(150))
    v = deg(25)
    simulate(d, h, 4.0, lambda t, _: est(deg(150) + 0.12 * VIEW.hfov + v * t, framed_tilt(PREZENTACJA), t, v_pan=v))
    assert max(h.angle("pan", i * 0.05) for i in range(120)) <= LIM.pan_max + deg(0.5)


ZOOM_MOVE = 1.0     # s jazdy optyki w teście


def run_zoom(d, h, seconds: float, est_fn, zoom: float = 0.0, t0: float = 0.0):
    """Jak simulate(), ale widok ma bieżący zoom, a rozkaz zoomu jedzie ZOOM_MOVE s."""
    log, zoom_now, until = [], zoom, -1.0
    for i in range(int(seconds / DT)):
        t = t0 + i * DT
        cmds = d.tick(t, est_fn(t, h), h, View(1280, 720, zoom_now), zoom_moving=t < until)
        apply(h, cmds, t)
        for c in cmds:
            if c.kind == "zoom":
                zoom_now, until = c.value, t + ZOOM_MOVE
        log += [(t, c) for c in cmds]
    return log, zoom_now


def auto_director(profile=ROZMOWA):
    d = Director(profile, LIM, DYN)
    d.auto_zoom = True
    return d, HeadModel(DYN)


def test_auto_zoom_moves_once_to_shot_after_dwell() -> None:
    d, h = auto_director()
    scale = deg(4)
    log, zoom = run_zoom(d, h, 8.0, lambda t, _: est(0.0, framed_tilt(), t, yaw=0.0, scale=scale))
    zooms = [(t, c.value) for t, c in log if c.kind == "zoom"]
    assert len(zooms) == 1, zooms
    assert abs(zooms[0][0] - ZOOM_DWELL) < 2 * DT
    assert abs(scale / View(1280, 720, zoom).vfov - SHOTS["MCU"]) < 0.01


def test_zoom_ignores_small_changes_and_short_lean() -> None:
    d, h = auto_director()
    z0 = zoom_goal(est(0.0, 0.0, 0.0, scale=deg(4)), Shot("MCU", SHOTS["MCU"]), View(1280, 720))

    def fn(t, _):
        s = deg(4) * (1.1 if int(t) % 2 else 1.0)          # ±10% - w paśmie 20%
        if 5.0 <= t < 6.5:
            s = deg(6)                                      # pochylenie 1,5 s < ZOOM_DWELL
        return est(0.0, framed_tilt(), t, yaw=0.0, scale=s)
    log, _ = run_zoom(d, h, 12.0, fn, zoom=z0)
    assert [c for _, c in log if c.kind == "zoom"] == []


def test_zoom_gap_jitter_does_not_reset_dwell() -> None:
    # Kalibracja (2026-09-25): krok w tył dawał cel 1,15-1,25x w stosunku do bieżącego
    # zoomu; każde zanurkowanie pod 1,2 zerowało zwłokę i żaden ruch nie wystartował
    # (~11 s wariacji, zero rozkazów). Zwłoka resetuje się dopiero pod ZOOM_BAND_RESET.
    d, h = auto_director()
    base = deg(4)
    z0 = zoom_goal(est(0.0, 0.0, 0.0, scale=base), Shot("MCU", SHOTS["MCU"]), View(1280, 720))

    def fn(t, _):
        m = 1.25 if int(t / 1.5) % 2 == 0 else 1.18
        return est(0.0, framed_tilt(), t, yaw=0.0, scale=base / m)
    log, _ = run_zoom(d, h, 12.0, fn, zoom=z0)
    zooms = [c for _, c in log if c.kind == "zoom"]
    assert len(zooms) == 1, [(t, c.value) for t, c in log if c.kind == "zoom"]


def test_zoom_target_jitter_around_band_does_not_move() -> None:
    # Odbiór 2026-09-25 (sesja 20260925-235118): w odległości rozmowy cel MCU leżał
    # przy ~1,1-1,4x, a wahania skali (gesty, obrót głowy) niosły stosunek przez próg
    # 1,2x - zoom "piła" (13 ruchów w 2 min przy stałej odległości; cel oscylował
    # 1,16-1,38x, nigdy nie spadając pod reset 1,15x). Ruch startuje tylko, gdy cel
    # jest stabilny w oknie zwłoki (zmiana < ZOOM_TARGET_STABILITY).
    d, h = auto_director()
    base = deg(4)
    z0 = zoom_goal(est(0.0, 0.0, 0.0, scale=base), Shot("MCU", SHOTS["MCU"]), View(1280, 720))

    def fn(t, _):
        m = 1.38 if int(t / 1.5) % 2 == 0 else 1.18
        return est(0.0, framed_tilt(), t, yaw=0.0, scale=base / m)
    log, _ = run_zoom(d, h, 12.0, fn, zoom=z0)
    assert [c for _, c in log if c.kind == "zoom"] == []


def test_zoom_stable_target_still_moves_once() -> None:
    # To samo co wyżej, ale cel skacze na 1,4x i tam zostaje (np. krok w tył):
    # bramka stabilności nie może zablokować prawdziwej zmiany planu.
    d, h = auto_director()
    base = deg(4)
    z0 = zoom_goal(est(0.0, 0.0, 0.0, scale=base), Shot("MCU", SHOTS["MCU"]), View(1280, 720))

    def fn(t, _):
        m = 1.4 if t >= 1.0 else 1.0
        return est(0.0, framed_tilt(), t, yaw=0.0, scale=base / m)
    log, _ = run_zoom(d, h, 8.0, fn, zoom=z0)
    zooms = [(t, c) for t, c in log if c.kind == "zoom"]
    assert len(zooms) == 1, zooms
    assert abs(zooms[0][0] - (1.0 + ZOOM_DWELL)) < 2 * DT


def test_auto_zoom_off_sends_no_zoom() -> None:
    d, h = Director(ROZMOWA, LIM, DYN), HeadModel(DYN)
    log, _ = run_zoom(d, h, 8.0, lambda t, _: est(0.0, framed_tilt(), t, scale=deg(4)))
    assert [c for _, c in log if c.kind == "zoom"] == []


def test_pan_tilt_aim_at_goal_zoom_when_zooming() -> None:
    d, h = auto_director()
    log, zoom = run_zoom(d, h, 8.0, lambda t, _: est(deg(3), framed_tilt(), t, yaw=0.0, scale=deg(4)))
    t_zoom = next(t for t, c in log if c.kind == "zoom")
    same_tick = [c for t, c in log if t == t_zoom and c.kind == "abs"]
    if not ZOOM_WITH_PAN_TILT:
        assert same_tick == [], "zoom kolejno: pan/tilt dopiero po jeździe optyki"
        return
    assert {c.axis for c in same_tick} == {"pan", "tilt"}
    pan = next(c.value for c in same_tick if c.axis == "pan")
    tilt = next(c.value for c in same_tick if c.axis == "tilt")
    x, y = View(1280, 720, zoom).world_to_pixel(deg(3), framed_tilt(), pan, tilt)
    assert abs(x - 640) < 1.0 and abs(y - GOLDEN * 720) < 1.0


if __name__ == "__main__":
    run(globals(), "Reżyser: śledzenie")
