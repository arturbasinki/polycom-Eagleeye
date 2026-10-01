"""Director: when and how to move the camera - like a calm operator.

Input: target estimate in world angles, head model, field of view.
Output: a list of commands (:class:`Command`) for the actuator. The module does not touch
hardware, so the whole behaviour can be checked with tests.

Rules (spec, "Director" section):

* hysteresis - the camera moves when the head leaves the wide trigger zone,
  and arrives exactly at the framing point,
* dwell - the head must be outside the zone continuously,
* one command per move; in-flight correction only on a large deviation and after 60% of the move
  (restarting the S-curve halfway would be the worst jerk),
* velocity following only for pan and only in a profile that enables it; stop
  with a lead for the coast, and after braking always an absolute arrival that
  also re-anchors the true head position.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .framing import CENTER, GOLDEN, SIDE_X, SideSelector, aim, shot_for, zoom_goal
from .geometry import View, deg, zoom_factor
from .head_model import Dynamics, HeadModel
from .i18n import Message, msg
from .profiles import Profile
from .search import local_plan, startup_plan
from .target_filter import TargetEstimate


@dataclass(frozen=True)
class Command:
    kind: str       # "abs" | "vel" | "zoom"
    axis: str       # "pan" | "tilt" | "zoom"
    value: float    # abs: angle [arcsec]; vel: direction -1/0/+1; zoom: control value


@dataclass(frozen=True)
class Limits:
    pan_min: float
    pan_max: float
    tilt_min: float
    tilt_max: float

    def bounds(self, axis: str) -> tuple[float, float]:
        return (self.pan_min, self.pan_max) if axis == "pan" else (self.tilt_min, self.tilt_max)

    def clamp(self, axis: str, value: float) -> float:
        lo, hi = self.bounds(axis)
        return min(max(value, lo), hi)


# axis states
IDLE, ALERT, MOVING, FOLLOWING, BRAKING = "idle", "alert", "moving", "following", "braking"
# director modes
TRACKING, SEARCHING, LOST, WAITING = "tracking", "searching", "lost", "waiting"

FAST_FOR = 0.06             # s of fast target motion before we enable following
RETARGET_PROGRESS = 0.6     # in-flight correction only after this part of the move
MIN_MOVE = deg(0.5)         # moves shorter than this we skip (e.g. target beyond the range)
# Composition (acceptance 2026-09-25): a head point at rest must be within the 5% band around
# the golden-ratio point (the acceptance criterion), while the trigger zone (up to 15-26%) is
# too wide to guarantee it: after a displacement a person can "settle" 10% from the
# point and the zone would never correct it. An inner band + a quiet re-fit.
COMPOSITION_BAND = 0.05     # fraction of frame width (pan) / height (tilt)
REFIT_DWELL = 3.0           # s in the middle zone (band..zone) before the re-fit
FOLLOW_MARGIN_S = 0.1       # margin at the limit: distance ~1 loop tick (15 Hz) at full speed
SEARCH_DWELL = 0.6          # s of rest at a scan point (detection only while still)
RESCAN_AFTER = 60.0         # s until a full rescan when nobody was found
WORK_TILT_DEFAULT = -deg(5) # working height for the scan without a "home" preset
CATCHUP_HORIZON = 1.0       # s - how far ahead we predict a fleeing target
CATCHUP_MAX = 0.75          # catch-up at most this many fields of view
CATCHUP_MIN_SPEED = deg(2)  # a slower target did not "escape" - we do not catch up
EDGE_MARGIN = 0.12          # target "at the edge": less than 12% of the width from the border
# Move only onto a settled target (review 2026-09-26): an absolute move hits with a single
# command only a target that is standing still. A command issued while a person is standing up
# or taking a step aims at an instantaneous position, the person walks on and the camera has to
# arrive a second, third time (in steps). We wait until the target speed drops, unless the
# predicted position at arrival time leaves the frame.
SETTLE_SPEED = deg(2.0)     # a target slower than this "stands still" (filter speed noise at rest < 1.5°/s)
SETTLE_MAX_WAIT = 2.0       # s - the longest wait for settling
# Lead (presentation) is for a walking person: walking is ~20°/s. From close up (rolling the
# chair) the angular speed from the filter reached 60°/s and the lead v x ~0.5 s gave pan
# commands of +110° / -110° (session 20260926-150210). We limit the speed and the offset itself.
LEAD_MAX_SPEED = deg(25.0)
LEAD_MAX_FOV = 0.25         # lead at most 1/4 of the frame width
ESCAPE_HORIZON = 0.3        # s - how far ahead we check whether the target will leave the frame
GO, WAIT, ESCAPE = "go", "wait", "escape"
ZOOM_BAND = 1.2             # zoom moves when the required factor differs by more than 20% (in logarithm)
ZOOM_BAND_RESET = 1.15      # the dwell resets only below this ratio (hysteresis)
ZOOM_DWELL = 2.0            # s outside the band - longer than pan/tilt: leaning in does not zoom
ZOOM_TARGET_STABILITY = 1.12  # the target may change by ≤12% in the dwell window, or no move
# Result of tools/measure_zoom.py (stage C plan, Task 2): whether zoom may travel together with pan/tilt.
ZOOM_WITH_PAN_TILT = True


@dataclass
class _Axis:
    state: str = IDLE
    since: float = 0.0
    fast_since: float | None = None
    move_target: float | None = None
    direction: int = 0
    fwin: list | None = None
    settle_since: float | None = None


@dataclass(frozen=True)
class DirectorStatus:
    mode: str
    pan: str
    tilt: str
    note: Message | None
    ladder: int


class Director:
    def __init__(self, profile: Profile, limits: Limits, dynamics: Dynamics) -> None:
        self.profile = profile
        self.limits = limits
        self.dyn = dynamics
        self.home: tuple[float, float] | None = None
        self.last_azimuth: tuple[float, float] | None = None
        self._axes = {"pan": _Axis(), "tilt": _Axis()}
        self._mode = TRACKING
        self._note = None
        self._pending: list[Command] = []
        self._last_est: TargetEstimate | None = None
        self._ladder = 0
        self._plan: list[tuple[float, float]] = []
        self._plan_kind = ""                 # "start" | "local"
        self._arrived_at: float | None = None
        self._await_motion = False           # point command sent, the head has not moved yet
        self._step_deadline: float | None = None
        self._rescan_at: float | None = None
        self._zoom_before: float | None = None
        self._return_point: tuple[float, float] | None = None
        self._cam_at_last_seen: float = 0.0
        self.side = SideSelector()
        self._pan_side = CENTER             # the side for which the last pan move was sent
        self.auto_zoom = False
        self.last_zoom_goal: float | None = None  # last computed target zoom (preview, "state")
        self._zoom_axis = _Axis()
        self._zoom_moving = False
        self._lead_hfov = 0.0               # field of view from the last tick (lead limit)

    def set_profile(self, profile: Profile) -> None:
        self.profile = profile

    @property
    def status(self) -> DirectorStatus:
        return DirectorStatus(self._mode, self._axes["pan"].state, self._axes["tilt"].state,
                              self._note, self._ladder)

    def tick(self, t: float, est: TargetEstimate | None, head: HeadModel, view: View,
             zoom_moving: bool = False) -> list[Command]:
        cmds, self._pending = self._pending, []
        self._lead_hfov = view.hfov
        self._zoom_moving = zoom_moving
        if est is not None:
            self._last_est = est
            self.last_azimuth = (est.pan, est.tilt)
            self._cam_at_last_seen = head.angle("pan", est.last_seen)
            p = self.profile
            self.side.update(t, est.yaw, p.side_enter, p.side_exit, p.side_dwell)
        return cmds + self._tick_mode(t, est, head, view)

    # --- modes -----------------------------------------------------------

    def _tick_mode(self, t: float, est: TargetEstimate | None, head: HeadModel, view: View) -> list[Command]:
        if self._mode == SEARCHING:
            return self._tick_search(t, est, head)
        if self._mode in (LOST, WAITING):
            still = not head.moving("pan", t) and not head.moving("tilt", t)
            if est is not None and still:
                return self._reacquire()
            if self._mode == LOST:
                return self._tick_lost(t, head, view)
            if self._rescan_at is not None and t >= self._rescan_at:
                self.start_search(t, view.zoom_value)
                cmds, self._pending = self._pending, []
                return cmds
            return []
        if est is None:
            # Our own absolute arrival can briefly lose the detection (the camera is moving).
            # We finish the planned move before announcing the target loss - otherwise the director
            # would interrupt its own travel and fall into the loss ladder for no reason.
            if any(ax.state == MOVING and head.moving(axis, t) for axis, ax in self._axes.items()):
                return []
            return self._begin_lost(t, view)
        zoom = self._track_zoom(t, est, head, view)
        if zoom:
            return zoom
        return self._track_axis("pan", t, est, head, view) + self._track_axis("tilt", t, est, head, view)

    # --- searching ----------------------------------------------------------

    def start_search(self, t: float, zoom_value: float = 0.0) -> None:
        """Startup calibration / "search for a person" button. Commands will go out in the next tick()."""
        cmds = self._stop_following()
        work_tilt = self.home[1] if self.home else WORK_TILT_DEFAULT
        if self.last_azimuth:
            start_pan = self.last_azimuth[0]
        else:
            start_pan = self.home[0] if self.home else 0.0
        self._plan = startup_plan(start_pan, work_tilt, self.limits.bounds("pan"), self.limits.bounds("tilt"))
        self._plan_kind = "start"
        self._ladder = 0
        self._pending += self._enter_search(zoom_value, cmds)

    def reset(self) -> None:
        """Tracking disabled: forget the plans and wait."""
        self._axes = {"pan": _Axis(), "tilt": _Axis()}
        self._mode, self._ladder, self._note = WAITING, 0, None
        self._plan, self._pending = [], []
        self._rescan_at = self._step_deadline = self._arrived_at = None
        self._await_motion = False
        self.side.reset()
        self._pan_side = CENTER
        self._zoom_axis = _Axis()

    def _enter_search(self, zoom_value: float, cmds: list[Command]) -> list[Command]:
        self._mode = SEARCHING
        self._rescan_at = None
        if zoom_value > 0:
            if self._zoom_before is None:
                self._zoom_before = zoom_value
            cmds.append(Command("zoom", "zoom", 0.0))
        return cmds + self._next_point()

    def _next_point(self) -> list[Command]:
        pan, tilt = self._plan.pop(0)
        self._arrived_at = None
        self._await_motion = True
        self._note = msg("director.note.searching", points=len(self._plan))
        return [Command("abs", "pan", pan), Command("abs", "tilt", tilt)]

    def _tick_search(self, t: float, est: TargetEstimate | None, head: HeadModel) -> list[Command]:
        if self._await_motion:
            # The point command goes out in the same tick as this decision, and the actuator applies
            # it only after tick(). Without this flag the rest would count from before the movement.
            if head.moving("pan", t) or head.moving("tilt", t):
                self._await_motion = False
            return []
        if head.moving("pan", t) or head.moving("tilt", t):
            return []
        if self._arrived_at is None:
            self._arrived_at = t
            return []
        if est is not None and est.last_seen >= self._arrived_at:
            return self._reacquire()
        if t - self._arrived_at < SEARCH_DWELL:
            return []
        if self._plan:
            return self._next_point()
        return self._search_exhausted(t)

    def _search_exhausted(self, t: float) -> list[Command]:
        cmds: list[Command] = []
        # Without a "home" preset, after a local search we return to where the target vanished. Staying
        # at the last scan point (-1 field of view) turned the camera away from the room permanently
        # (session 20260923-004030).
        back = self.home or (self._return_point if self._plan_kind == "local" else None)
        if back:
            cmds += [Command("abs", "pan", back[0]), Command("abs", "tilt", back[1])]
        cmds += self._restore_zoom()
        # Waiting always ends with another full scan - otherwise a camera turned away
        # from the person would have no way to see them again.
        self._rescan_at = t + RESCAN_AFTER
        if self._plan_kind == "local":
            self._ladder = 4
        self._mode = WAITING
        self._note = (msg("director.note.nobody_rescan", seconds=f"{RESCAN_AFTER:.0f}")
                      if self._rescan_at is not None else msg("director.note.nobody"))
        return cmds

    def _restore_zoom(self) -> list[Command]:
        if self._zoom_before is None:
            return []
        zoom, self._zoom_before = self._zoom_before, None
        return [Command("zoom", "zoom", zoom)]

    def _reacquire(self) -> list[Command]:
        self._mode, self._ladder = TRACKING, 0
        self._plan, self._rescan_at, self._step_deadline = [], None, None
        self._await_motion = False
        self._axes = {"pan": _Axis(), "tilt": _Axis()}
        self._zoom_axis = _Axis()
        self._note = msg("director.note.found")
        if self.auto_zoom:
            self._zoom_before = None        # zoom will be computed by the composition from the shot
            return []
        return self._restore_zoom()

    # --- target loss ladder ------------------------------------------------

    def _begin_lost(self, t: float, view: View) -> list[Command]:
        cmds = self._stop_following()
        self._mode, self._step_deadline = LOST, None
        last = self._last_est
        if last is None:
            self._mode, self._note = WAITING, msg("director.note.no_target")
            return cmds
        offset = last.pan - self._cam_at_last_seen
        near_edge = abs(offset) > (0.5 - EDGE_MARGIN) * view.hfov
        toward = 1 if offset > 0 else -1
        if self.profile.catch_up and near_edge and last.v_pan * toward > CATCHUP_MIN_SPEED:
            reach = max(-CATCHUP_MAX * view.hfov, min(CATCHUP_MAX * view.hfov, last.v_pan * CATCHUP_HORIZON))
            self._ladder, self._note = 1, msg("director.note.catching_up")
            return cmds + [Command("abs", "pan", self.limits.clamp("pan", last.pan + reach))]
        return cmds + self._ladder_last_azimuth(view)

    def _ladder_last_azimuth(self, view: View) -> list[Command]:
        last = self._last_est
        self._ladder, self._step_deadline = 2, None
        self._note = msg("director.note.waiting_last_seen")
        cmds = [Command("abs", "pan", self.limits.clamp("pan", last.pan)),
                Command("abs", "tilt", self.limits.clamp("tilt", self._aim("tilt", last, view)))]
        return cmds

    def _tick_lost(self, t: float, head: HeadModel, view: View) -> list[Command]:
        if head.moving("pan", t) or head.moving("tilt", t):
            return []
        if self._step_deadline is None:
            wait = SEARCH_DWELL if self._ladder == 1 else self.profile.ladder_step_time
            self._step_deadline = t + wait
            return []
        if t < self._step_deadline:
            return []
        if self._ladder == 1:
            return self._ladder_last_azimuth(view)
        if self._ladder == 2 and view.zoom_value > 0 and self._zoom_before is None:
            # We zoom out only after a step time without a target: a short loss (detection blink,
            # a turn away) must not jump the image 2400 -> 0 -> 2400.
            self._zoom_before = view.zoom_value
            self._step_deadline = None
            self._note = msg("director.note.zooming_out")
            return [Command("zoom", "zoom", 0.0)]
        if self._ladder == 2 and self.profile.ladder_max >= 3:
            last = self._last_est
            self._ladder = 3
            tilt = self.limits.clamp("tilt", self._aim("tilt", last, view))
            self._plan = local_plan(last.pan, tilt, view.hfov, self.limits.bounds("pan"))
            self._return_point = self._plan[0]      # the loss place - we return there without a "home"
            self._plan_kind = "local"
            return self._enter_search(view.zoom_value, [])
        self._step_deadline = math.inf      # talk: we stay at step 2
        return []

    def _stop_following(self) -> list[Command]:
        cmds = []
        for axis, ax in self._axes.items():
            if ax.state == FOLLOWING:
                cmds.append(Command("vel", axis, 0))
            self._axes[axis] = _Axis()
        return cmds

    # --- tracking a single axis ---------------------------------------------

    def _aim(self, axis: str, est: TargetEstimate, view: View) -> float:
        """Where the camera should look: head at the golden-ratio point on the current side."""
        pan, tilt = aim(est, self.side.side, self._aim_view(view))
        return pan if axis == "pan" else tilt

    def _aim_view(self, view: View) -> View:
        """While the zoom is moving we already aim with the target field of view - on arrival of
        both axes the face is exactly at the point."""
        z = self._zoom_axis
        if z.state == MOVING and z.move_target is not None:
            return replace(view, zoom_value=z.move_target)
        return view

    def _threshold(self, axis: str, view: View) -> float:
        if axis == "pan":
            return self.profile.trigger_pan * view.hfov
        return self.profile.trigger_tilt * view.vfov

    def _band(self, axis: str, view: View) -> float:
        """Composition band: the head at rest within the band around the point - no movement."""
        if axis == "pan":
            return COMPOSITION_BAND * view.hfov
        return COMPOSITION_BAND * view.vfov

    def _track_axis(self, axis: str, t: float, est: TargetEstimate, head: HeadModel, view: View) -> list[Command]:
        ax = self._axes[axis]
        aim = self._aim(axis, est, view)
        v = est.v_pan if axis == "pan" else est.v_tilt
        current = head.angle(axis, t)
        error = aim - current
        thr = self._threshold(axis, view)

        if ax.state == MOVING:
            if not head.moving(axis, t):
                ax.state = IDLE
            elif (ax.move_target is not None and abs(aim - ax.move_target) > thr
                  and head.progress(axis, t) >= RETARGET_PROGRESS
                  and (axis == "pan" or abs(v) < SETTLE_SPEED)):
                # Tilt corrects in flight only a settled target: vertically nobody "walks", and while the camera
                # moves the estimate runs on prediction (measurements in motion weigh little) and
                # overshot a stationary standing-up - a correction, and after it yet another return.
                return self._move(axis, aim, v, current)
            return []
        if ax.state == FOLLOWING:
            return self._follow(axis, t, est, head, aim, v)
        if ax.state == BRAKING:
            if head.moving(axis, t):
                return []
            return self._move(axis, aim, 0.0, current, force=True)

        if axis == "pan" and self.side.side != self._pan_side:
            # A side change shifts the target by ~12% of the width - less than the talk zone (15%),
            # so without this the camera would not move. The side already has its own dwell (side_dwell).
            return self._move(axis, aim, v, current)
        if abs(error) <= self._band(axis, view):
            ax.state, ax.fast_since = IDLE, None
            return []
        if (axis == "pan" and self.side.pending is not None
                and abs(error) <= (0.5 - EDGE_MARGIN) * view.hfov):
            # The frame side is just being decided (face turned away, side_dwell running). A move
            # now would aim at a point that will change shortly - and the side change would force
            # a second move. We wait (at most side_dwell) and go once, to the right point.
            # A target at the frame edge (walking) does not wait - a loss would be worse than two moves.
            if ax.state == IDLE:
                ax.state, ax.since = ALERT, t
            return []
        if abs(error) <= thr:
            # Middle zone: the head settled outside the composition band but inside the trigger
            # zone (e.g. after moving the chair) - the zone alone would not
            # correct it; a quiet re-fit after REFIT_DWELL (shorter excursions - gestures -
            # do not start).
            if ax.state == IDLE:
                ax.state, ax.since = ALERT, t
            if t - ax.since >= REFIT_DWELL:
                wait = self._settling(axis, t, error, v, view)
                if wait != WAIT:
                    return self._move(axis, aim, v, current)
            return []
        if ax.state == IDLE:
            ax.state, ax.since = ALERT, t
        if axis == "pan" and self.profile.follow:
            direction = 1 if error > 0 else -1
            lo, hi = self.limits.bounds(axis)
            room = (hi - current) if direction > 0 else (current - lo)
            fast = (abs(v) > self.profile.follow_speed and v * error > 0
                    and room > self.dyn.coast_distance() + self._follow_margin())
            if fast:
                ax.fast_since = t if ax.fast_since is None else ax.fast_since
                if t - ax.fast_since < FAST_FOR:
                    # The decision to follow is still pending. Without this the shorter dwell
                    # (0.2 s in presentation) would always win with an absolute move.
                    return []
                ax.state, ax.direction = FOLLOWING, direction
                self._note = msg("director.note.following")
                return [Command("vel", axis, direction)]
            ax.fast_since = None
        if t - ax.since >= self.profile.dwell:
            wait = self._settling(axis, t, error, v, view)
            if wait != WAIT:
                return self._move(axis, aim, v, current)
        return []

    def _settling(self, axis: str, t: float, error: float, v: float, view: View) -> str:
        """GO - move now; WAIT - the target is still moving, we wait for it to stop; ESCAPE - the target moves
        and at arrival time would already be at the edge: move now. (Aiming at the intercept point
        v x time-to-arrival was checked in simulation and rejected: a person who stands up or takes
        a step slows down at the end, while v at decision time is the largest - overshoot and return.)"""
        ax = self._axes[axis]
        if abs(v) < SETTLE_SPEED or (self.profile.lead and axis == "pan"):
            # A walking target in presentation: lead and following count on its speed.
            ax.settle_since = None
            return GO
        if axis == "pan":
            fov, edge = view.hfov, min(SIDE_X[self.side.side], 1.0 - SIDE_X[self.side.side])
        else:
            fov, edge = view.vfov, GOLDEN
        if axis == "tilt" and error * (-1.0 if view.invert_tilt else 1.0) < 0:
            edge = 1.0 - GOLDEN            # downwards to the bottom edge is farther
        # A short horizon: human movements (standing up, a step) last fractions of a second, so
        # the instantaneous speed extended over the whole arrival time (~1 s) predicted an escape
        # that did not happen, and the camera moved halfway through the move - a second move closed it (in steps).
        if abs(error + v * ESCAPE_HORIZON) > (edge - EDGE_MARGIN) * fov:
            ax.settle_since = None
            return ESCAPE
        if ax.settle_since is None:
            ax.settle_since = t
        if t - ax.settle_since >= SETTLE_MAX_WAIT:
            ax.settle_since = None
            return GO
        self._note = msg("director.note.waiting_settle", axis=axis)
        return WAIT

    def _move(self, axis: str, aim: float, v: float, current: float, force: bool = False) -> list[Command]:
        ax = self._axes[axis]
        lead = 0.0
        # Lead only horizontally: a walking person moves in pan. Vertical "velocity"
        # is nodding and leaning - leading it fired the tilt past the target and a second
        # move brought it back (session 20260926-011024, t=191.9 s and 239.5 s).
        if self.profile.lead and axis == "pan":
            speed = max(-LEAD_MAX_SPEED, min(LEAD_MAX_SPEED, v))
            lead = speed * (self.dyn.abs_latency + self.dyn.abs_duration(aim - current) / 2.0)
            reach = LEAD_MAX_FOV * self._lead_hfov
            lead = max(-reach, min(reach, lead))
        target = self.limits.clamp(axis, aim + lead)
        if not force and abs(target - current) < MIN_MOVE:
            ax.state, ax.fast_since = IDLE, None
            if axis == "pan":
                self._pan_side = self.side.side
            return []
        ax.state, ax.move_target, ax.fast_since, ax.settle_since = MOVING, target, None, None
        if axis == "pan":
            self._pan_side = self.side.side
        self._note = msg("director.note.moving", axis=axis)
        return [Command("abs", axis, target)]

    def _track_zoom(self, t: float, est: TargetEstimate, head: HeadModel, view: View) -> list[Command]:
        """Third axis: zoom to the shot. Band in the logarithm of the factor (equally sensitive at 1x
        and 5x), a dwell longer than pan/tilt, arrival exactly at the target.

        Hysteresis (calibration 2026-09-25): the move starts when the target/current ratio crosses
        ZOOM_BAND, but the dwell counter resets only when it drops below ZOOM_BAND_RESET -
        target variations in the 1.15-1.2 gap would otherwise stop a prepared move.

        Target stability gate (deviation 5, acceptance 2026-09-25): the move starts only when the
        target does not "saw" within the dwell window (max/min factor <= ZOOM_TARGET_STABILITY) - at a
        constant talk distance, scale fluctuations (gestures, head turn) carried the ratio across
        the 1.2 threshold and without the gate the zoom pumped (13 moves in 2 min)."""
        ax = self._zoom_axis
        if ax.state == MOVING:
            if self._zoom_moving:
                return []
            ax.state, ax.fwin = IDLE, None
        shot = shot_for(self.profile, est)
        goal = zoom_goal(est, shot, view) if self.auto_zoom else None
        self.last_zoom_goal = goal
        if goal is None:
            ax.state, ax.fwin = IDLE, None
            return []
        r = abs(math.log(zoom_factor(goal) / zoom_factor(view.zoom_value)))
        if r <= math.log(ZOOM_BAND_RESET):
            ax.state, ax.fwin = IDLE, None
            return []
        if r > math.log(ZOOM_BAND) and ax.state == IDLE:
            ax.state, ax.since, ax.fwin = ALERT, t, None
        # The ratio in the gap (ZOOM_BAND_RESET, ZOOM_BAND]: neither a reset nor a start of the counter.
        if ax.state == ALERT:
            win = ax.fwin if ax.fwin is not None else []
            while win and t - win[0][0] > ZOOM_DWELL:
                win.pop(0)
            win.append((t, zoom_factor(goal)))
            ax.fwin = win
            stable = max(f for _, f in win) / min(f for _, f in win) <= ZOOM_TARGET_STABILITY
            if (t - ax.since >= ZOOM_DWELL and stable and self.side.pending is None
                    and not (head.moving("pan", t) or head.moving("tilt", t))):
                ax.state, ax.move_target, ax.fwin = MOVING, goal, None
                self._note = msg("director.note.zoom_shot", shot=shot.name)
                cmds = [Command("zoom", "zoom", goal)]
                if ZOOM_WITH_PAN_TILT:
                    for axis in ("pan", "tilt"):
                        cmds += self._move(axis, self._aim(axis, est, view), 0.0, head.angle(axis, t))
                return cmds
        return []

    def _follow(self, axis: str, t: float, est: TargetEstimate, head: HeadModel,
                aim: float, v: float) -> list[Command]:
        """Travel at constant speed; stop when the head, after coasting, catches up with the
        target's future position."""
        ax = self._axes[axis]
        d = ax.direction
        rest = head.rest_angle(axis, t)
        target_future = aim + v * self.dyn.coast_time()
        lo, hi = self.limits.bounds(axis)
        margin = self._follow_margin()      # the decision is made once per tick - margin for one driving tick
        at_limit = (d > 0 and rest + margin >= hi) or (d < 0 and rest - margin <= lo)
        if d * (rest - target_future) >= 0 or at_limit or v * d <= 0:
            ax.state = BRAKING
            self._note = msg("director.note.braking")
            return [Command("vel", axis, 0)]
        return [Command("vel", axis, d)]

    def _follow_margin(self) -> float:
        return self.dyn.vel_speed * FOLLOW_MARGIN_S
