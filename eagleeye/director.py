"""Reżyser: kiedy i jak ruszyć kamerą - jak spokojny operator.

Wejście: estymata celu w kątach świata, model głowicy, pole widzenia.
Wyjście: lista rozkazów (:class:`Command`) dla wykonawcy. Moduł nie dotyka
sprzętu, więc całe zachowanie da się sprawdzić testami.

Zasady (spec, sekcja "Reżyser"):

* histereza - kamera rusza, gdy głowa wyjdzie poza szeroką strefę wyzwalania,
  i dojeżdża dokładnie do punktu kadrowania,
* zwłoka - głowa musi być poza strefą nieprzerwanie,
* jeden rozkaz na ruch; korekta w locie tylko przy dużym rozjeździe i po 60% ruchu
  (restart krzywej S w połowie byłby najgorszym szarpnięciem),
* podążanie prędkościowe tylko dla pan i tylko w profilu, który je włącza; stop
  z wyprzedzeniem na wybieg, a po wyhamowaniu zawsze dojazd absolutny, który
  przy okazji ponownie zakotwicza prawdziwą pozycję głowicy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .framing import CENTER, GOLDEN, SIDE_X, SideSelector, aim, shot_for, zoom_goal
from .geometry import View, deg, zoom_factor
from .head_model import Dynamics, HeadModel
from .profiles import Profile
from .search import local_plan, startup_plan
from .target_filter import TargetEstimate


@dataclass(frozen=True)
class Command:
    kind: str       # "abs" | "vel" | "zoom"
    axis: str       # "pan" | "tilt" | "zoom"
    value: float    # abs: kąt [arcsec]; vel: kierunek -1/0/+1; zoom: wartość kontrolki


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


# stany osi
SPOKOJ, CZUJNY, RUCH, PODAZANIE, HAMOWANIE = "spokój", "czujny", "ruch", "podążanie", "hamowanie"
# tryby reżysera
SLEDZENIE, SZUKANIE, UTRATA, CZEKANIE = "śledzenie", "szukanie", "utrata", "czekanie"

FAST_FOR = 0.06             # s szybkiego ruchu celu, zanim włączymy podążanie
RETARGET_PROGRESS = 0.6     # korekta w locie dopiero po tej części ruchu
MIN_MOVE = deg(0.5)         # ruchy krótsze niż to pomijamy (np. cel za granicą zakresu)
# Kompozycja (odbiór 2026-09-25): punkt głowy w spoczynku ma być w paśmie 5% wokół
# punktu złotego podziału (kryterium odbioru), a strefa wyzwalania (do 15-26%) jest
# za szeroka, by to gwarantować: po przemieszczeniu osoba potrafi "osiąść" 10% od
# punktu i strefa nigdy by nie skorygowała. Pasmo wewnętrzne + cichy re-fit.
COMPOSITION_BAND = 0.05     # ułamek szerokości (pan) / wysokości (tilt) kadru
REFIT_DWELL = 3.0           # s w strefie środkowej (pasmo..strefa), zanim re-fit
FOLLOW_MARGIN_S = 0.1       # zapas przy granicy: droga ~1 taktu pętli (15 Hz) przy pełnej prędkości
SEARCH_DWELL = 0.6          # s postoju w punkcie skanu (detekcja tylko w bezruchu)
RESCAN_AFTER = 60.0         # s do ponownego skanu, gdy nikogo nie znaleziono
WORK_TILT_DEFAULT = -deg(5) # wysokość robocza skanu bez presetu "dom"
CATCHUP_HORIZON = 1.0       # s - na ile w przód przewidujemy uciekający cel
CATCHUP_MAX = 0.75          # doganianie najdalej o tyle pól widzenia
CATCHUP_MIN_SPEED = deg(2)  # wolniejszy cel nie "uciekł" - nie doganiamy
EDGE_MARGIN = 0.12          # cel "przy krawędzi": bliżej niż 12% szerokości od brzegu
# Ruch dopiero na osiadły cel (przegląd 2026-09-26): ruch absolutny trafia jednym rozkazem
# tylko w cel, który stoi. Rozkaz wydany w trakcie wstawania/kroku celuje w pozycję
# chwilową, osoba idzie dalej i trzeba dojeżdżać drugi, trzeci raz (schody). Czekamy, aż
# prędkość celu spadnie, chyba że przewidywana pozycja w chwili dojazdu opuszcza kadr.
SETTLE_SPEED = deg(2.0)     # cel wolniejszy niż to "stoi" (szum prędkości filtra w spoczynku < 1,5°/s)
SETTLE_MAX_WAIT = 2.0       # s - najdłuższe czekanie na osiadnięcie
# Wyprzedzenie (prezentacja) jest dla idącej osoby: chód to ~20°/s. Z bliska (podjazd
# fotelem) prędkość kątowa z filtra sięgała 60°/s i wyprzedzenie v × ~0,5 s dawało rozkazy
# pan +110° / -110° (sesja 20260926-150210). Ograniczamy prędkość i samo przesunięcie.
LEAD_MAX_SPEED = deg(25.0)
LEAD_MAX_FOV = 0.25         # wyprzedzenie najwyżej o 1/4 szerokości kadru
ESCAPE_HORIZON = 0.3        # s - na tyle naprzód sprawdzamy, czy cel wyjdzie z kadru
GO, WAIT, ESCAPE = "go", "wait", "escape"
ZOOM_BAND = 1.2             # zoom rusza, gdy potrzebna krotność różni się o ponad 20% (w logarytmie)
ZOOM_BAND_RESET = 1.15      # zwłoka resetuje się dopiero poniżej tego stosunku (histereza)
ZOOM_DWELL = 2.0            # s poza pasmem - dłużej niż pan/tilt: pochylenie się do ekranu nie przybliża
ZOOM_TARGET_STABILITY = 1.12  # cel może się zmieniać o ≤12% w oknie zwłoki, inaczej nie startuje ruch
# Wynik tools/measure_zoom.py (plan etapu C, Task 2): czy zoom może jechać razem z pan/tilt.
ZOOM_WITH_PAN_TILT = True


@dataclass
class _Axis:
    state: str = SPOKOJ
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
    note: str
    ladder: int


class Director:
    def __init__(self, profile: Profile, limits: Limits, dynamics: Dynamics) -> None:
        self.profile = profile
        self.limits = limits
        self.dyn = dynamics
        self.home: tuple[float, float] | None = None
        self.last_azimuth: tuple[float, float] | None = None
        self._axes = {"pan": _Axis(), "tilt": _Axis()}
        self._mode = SLEDZENIE
        self._note = ""
        self._pending: list[Command] = []
        self._last_est: TargetEstimate | None = None
        self._ladder = 0
        self._plan: list[tuple[float, float]] = []
        self._plan_kind = ""                 # "start" | "lokalne"
        self._arrived_at: float | None = None
        self._await_motion = False           # rozkaz punktu wysłany, głowica jeszcze nie ruszyła
        self._step_deadline: float | None = None
        self._rescan_at: float | None = None
        self._zoom_before: float | None = None
        self._return_point: tuple[float, float] | None = None
        self._cam_at_last_seen: float = 0.0
        self.side = SideSelector()
        self._pan_side = CENTER             # strona, dla której wysłano ostatni ruch pan
        self.auto_zoom = False
        self.last_zoom_goal: float | None = None  # ostatni wyliczony zoom docelowy (podgląd, "stan")
        self._zoom_axis = _Axis()
        self._zoom_moving = False
        self._lead_hfov = 0.0               # pole widzenia z ostatniego taktu (limit wyprzedzenia)

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

    # --- tryby -----------------------------------------------------------

    def _tick_mode(self, t: float, est: TargetEstimate | None, head: HeadModel, view: View) -> list[Command]:
        if self._mode == SZUKANIE:
            return self._tick_search(t, est, head)
        if self._mode in (UTRATA, CZEKANIE):
            still = not head.moving("pan", t) and not head.moving("tilt", t)
            if est is not None and still:
                return self._reacquire()
            if self._mode == UTRATA:
                return self._tick_lost(t, head, view)
            if self._rescan_at is not None and t >= self._rescan_at:
                self.start_search(t, view.zoom_value)
                cmds, self._pending = self._pending, []
                return cmds
            return []
        if est is None:
            # Własny dojazd absolutny może chwilowo zgubić detekcję (kamera się rusza).
            # Dokańczamy zaplanowany ruch, zanim ogłosimy utratę celu - inaczej reżyser
            # przerywałby własny przejazd i wpadał w drabinę utraty bez powodu.
            if any(ax.state == RUCH and head.moving(axis, t) for axis, ax in self._axes.items()):
                return []
            return self._begin_lost(t, view)
        zoom = self._track_zoom(t, est, head, view)
        if zoom:
            return zoom
        return self._track_axis("pan", t, est, head, view) + self._track_axis("tilt", t, est, head, view)

    # --- szukanie ----------------------------------------------------------

    def start_search(self, t: float, zoom_value: float = 0.0) -> None:
        """Kalibracja startowa / przycisk "szukaj osoby". Rozkazy wyjdą w najbliższym tick()."""
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
        """Śledzenie wyłączone: zapomnij plany i czekaj."""
        self._axes = {"pan": _Axis(), "tilt": _Axis()}
        self._mode, self._ladder, self._note = CZEKANIE, 0, ""
        self._plan, self._pending = [], []
        self._rescan_at = self._step_deadline = self._arrived_at = None
        self._await_motion = False
        self.side.reset()
        self._pan_side = CENTER
        self._zoom_axis = _Axis()

    def _enter_search(self, zoom_value: float, cmds: list[Command]) -> list[Command]:
        self._mode = SZUKANIE
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
        self._note = f"szukam osoby (zostało punktów: {len(self._plan)})"
        return [Command("abs", "pan", pan), Command("abs", "tilt", tilt)]

    def _tick_search(self, t: float, est: TargetEstimate | None, head: HeadModel) -> list[Command]:
        if self._await_motion:
            # Rozkaz punktu wychodzi w tym samym takcie co ta decyzja, a wykonawca stosuje
            # go dopiero po tick(). Bez tej flagi postój liczyłby się od chwili przed ruszeniem.
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
        # Bez presetu "dom" po szukaniu lokalnym wracamy tam, gdzie cel zniknął. Zostanie
        # w ostatnim punkcie skanu (-1 pole widzenia) odwracało kamerę od pokoju na stałe
        # (sesja 20260923-004030).
        back = self.home or (self._return_point if self._plan_kind == "lokalne" else None)
        if back:
            cmds += [Command("abs", "pan", back[0]), Command("abs", "tilt", back[1])]
        cmds += self._restore_zoom()
        # Czekanie zawsze kończy się ponownym pełnym skanem - inaczej kamera odwrócona
        # od osoby nie miałaby jak jej znowu zobaczyć.
        self._rescan_at = t + RESCAN_AFTER
        if self._plan_kind == "lokalne":
            self._ladder = 4
        self._mode = CZEKANIE
        self._note = "nikogo nie znalazłem - czekam"
        if self._rescan_at is not None:
            self._note += f", ponowny skan za {RESCAN_AFTER:.0f} s"
        return cmds

    def _restore_zoom(self) -> list[Command]:
        if self._zoom_before is None:
            return []
        zoom, self._zoom_before = self._zoom_before, None
        return [Command("zoom", "zoom", zoom)]

    def _reacquire(self) -> list[Command]:
        self._mode, self._ladder = SLEDZENIE, 0
        self._plan, self._rescan_at, self._step_deadline = [], None, None
        self._await_motion = False
        self._axes = {"pan": _Axis(), "tilt": _Axis()}
        self._zoom_axis = _Axis()
        self._note = "cel odnaleziony"
        if self.auto_zoom:
            self._zoom_before = None        # zoom wyliczy kompozycja z planu
            return []
        return self._restore_zoom()

    # --- drabina utraty celu ------------------------------------------------

    def _begin_lost(self, t: float, view: View) -> list[Command]:
        cmds = self._stop_following()
        self._mode, self._step_deadline = UTRATA, None
        last = self._last_est
        if last is None:
            self._mode, self._note = CZEKANIE, "brak celu"
            return cmds
        offset = last.pan - self._cam_at_last_seen
        near_edge = abs(offset) > (0.5 - EDGE_MARGIN) * view.hfov
        toward = 1 if offset > 0 else -1
        if self.profile.catch_up and near_edge and last.v_pan * toward > CATCHUP_MIN_SPEED:
            reach = max(-CATCHUP_MAX * view.hfov, min(CATCHUP_MAX * view.hfov, last.v_pan * CATCHUP_HORIZON))
            self._ladder, self._note = 1, "doganiam cel"
            return cmds + [Command("abs", "pan", self.limits.clamp("pan", last.pan + reach))]
        return cmds + self._ladder_last_azimuth(view)

    def _ladder_last_azimuth(self, view: View) -> list[Command]:
        last = self._last_est
        self._ladder, self._step_deadline = 2, None
        self._note = "czekam tam, gdzie cel zniknął"
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
            # Oddalamy dopiero po czasie kroku bez celu: krótka utrata (mrugnięcie detekcji,
            # odwrócenie się) nie może skakać obrazem 2400 -> 0 -> 2400.
            self._zoom_before = view.zoom_value
            self._step_deadline = None
            self._note = "oddalam, żeby zobaczyć więcej"
            return [Command("zoom", "zoom", 0.0)]
        if self._ladder == 2 and self.profile.ladder_max >= 3:
            last = self._last_est
            self._ladder = 3
            tilt = self.limits.clamp("tilt", self._aim("tilt", last, view))
            self._plan = local_plan(last.pan, tilt, view.hfov, self.limits.bounds("pan"))
            self._return_point = self._plan[0]      # miejsce utraty celu - tam wracamy bez "domu"
            self._plan_kind = "lokalne"
            return self._enter_search(view.zoom_value, [])
        self._step_deadline = math.inf      # rozmowa: zostajemy na kroku 2
        return []

    def _stop_following(self) -> list[Command]:
        cmds = []
        for axis, ax in self._axes.items():
            if ax.state == PODAZANIE:
                cmds.append(Command("vel", axis, 0))
            self._axes[axis] = _Axis()
        return cmds

    # --- śledzenie jednej osi ---------------------------------------------

    def _aim(self, axis: str, est: TargetEstimate, view: View) -> float:
        """Gdzie ma patrzeć kamera: głowa w punkcie złotego podziału po bieżącej stronie."""
        pan, tilt = aim(est, self.side.side, self._aim_view(view))
        return pan if axis == "pan" else tilt

    def _aim_view(self, view: View) -> View:
        """W trakcie jazdy zoomu celujemy już przy docelowym polu widzenia - po dojeździe
        obu osi twarz jest dokładnie w punkcie."""
        z = self._zoom_axis
        if z.state == RUCH and z.move_target is not None:
            return replace(view, zoom_value=z.move_target)
        return view

    def _threshold(self, axis: str, view: View) -> float:
        if axis == "pan":
            return self.profile.trigger_pan * view.hfov
        return self.profile.trigger_tilt * view.vfov

    def _band(self, axis: str, view: View) -> float:
        """Pasmo kompozycji: spoczynek głowy w paśmie wokół punktu - bez ruchu."""
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

        if ax.state == RUCH:
            if not head.moving(axis, t):
                ax.state = SPOKOJ
            elif (ax.move_target is not None and abs(aim - ax.move_target) > thr
                  and head.progress(axis, t) >= RETARGET_PROGRESS
                  and (axis == "pan" or abs(v) < SETTLE_SPEED)):
                # Tilt koryguje w locie tylko osiadły cel: w pionie nikt nie "idzie", a w jeździe
                # kamery estymata jedzie na przewidywaniu (pomiary z ruchu mało ważą) i
                # przestrzeliwała zatrzymane wstawanie - korekta, a po niej jeszcze powrót.
                return self._move(axis, aim, v, current)
            return []
        if ax.state == PODAZANIE:
            return self._follow(axis, t, est, head, aim, v)
        if ax.state == HAMOWANIE:
            if head.moving(axis, t):
                return []
            return self._move(axis, aim, 0.0, current, force=True)

        if axis == "pan" and self.side.side != self._pan_side:
            # Zmiana strony przesuwa cel o ~12% szerokości - mniej niż strefa rozmowy (15%),
            # więc bez tego kamera by nie ruszyła. Strona ma już własną zwłokę (side_dwell).
            return self._move(axis, aim, v, current)
        if abs(error) <= self._band(axis, view):
            ax.state, ax.fast_since = SPOKOJ, None
            return []
        if (axis == "pan" and self.side.pending is not None
                and abs(error) <= (0.5 - EDGE_MARGIN) * view.hfov):
            # Strona kadru właśnie się rozstrzyga (twarz odwrócona, trwa side_dwell). Ruch
            # teraz celowałby w punkt, który za chwilę się zmieni - a zmiana strony wymusi
            # drugi ruch. Czekamy (najdłużej side_dwell) i jedziemy raz, do właściwego punktu.
            # Cel przy krawędzi kadru (idzie) nie czeka - utrata byłaby gorsza niż dwa ruchy.
            if ax.state == SPOKOJ:
                ax.state, ax.since = CZUJNY, t
            return []
        if abs(error) <= thr:
            # Strefa środkowa: głowa osiadła poza pasmem kompozycji, ale w strefie
            # wyzwalania (np. po przemieszczeniu fotela) - strefa sama tego nie
            # skorygowałaby; cichy re-fit po REFIT_DWELL (krótsze wycieczki - gesty -
            # nie startują).
            if ax.state == SPOKOJ:
                ax.state, ax.since = CZUJNY, t
            if t - ax.since >= REFIT_DWELL:
                wait = self._settling(axis, t, error, v, view)
                if wait != WAIT:
                    return self._move(axis, aim, v, current)
            return []
        if ax.state == SPOKOJ:
            ax.state, ax.since = CZUJNY, t
        if axis == "pan" and self.profile.follow:
            direction = 1 if error > 0 else -1
            lo, hi = self.limits.bounds(axis)
            room = (hi - current) if direction > 0 else (current - lo)
            fast = (abs(v) > self.profile.follow_speed and v * error > 0
                    and room > self.dyn.coast_distance() + self._follow_margin())
            if fast:
                ax.fast_since = t if ax.fast_since is None else ax.fast_since
                if t - ax.fast_since < FAST_FOR:
                    # Decyzja o podążaniu jeszcze zapada. Bez tego krótsza zwłoka
                    # (0,2 s w prezentacji) zawsze wygrywałaby ruchem absolutnym.
                    return []
                ax.state, ax.direction = PODAZANIE, direction
                self._note = "podążam za celem"
                return [Command("vel", axis, direction)]
            ax.fast_since = None
        if t - ax.since >= self.profile.dwell:
            wait = self._settling(axis, t, error, v, view)
            if wait != WAIT:
                return self._move(axis, aim, v, current)
        return []

    def _settling(self, axis: str, t: float, error: float, v: float, view: View) -> str:
        """GO - ruch teraz; WAIT - cel jeszcze jedzie, czekamy, aż stanie; ESCAPE - cel jedzie
        i w chwili dojazdu byłby już przy krawędzi: ruch teraz. (Celowanie w punkt przechwycenia
        v × czas dojazdu sprawdzone w symulacji i odrzucone: osoba, która wstaje albo robi
        krok, zwalnia pod koniec, a v w chwili decyzji jest największa - przestrzelenie i powrót.)"""
        ax = self._axes[axis]
        if abs(v) < SETTLE_SPEED or (self.profile.lead and axis == "pan"):
            # Idący cel w prezentacji: wyprzedzenie i podążanie liczą się z jego prędkością.
            ax.settle_since = None
            return GO
        if axis == "pan":
            fov, edge = view.hfov, min(SIDE_X[self.side.side], 1.0 - SIDE_X[self.side.side])
        else:
            fov, edge = view.vfov, GOLDEN
        if axis == "tilt" and error * (-1.0 if view.invert_tilt else 1.0) < 0:
            edge = 1.0 - GOLDEN            # w dół do dolnej krawędzi jest dalej
        # Horyzont krótki: ruchy człowieka (wstawanie, krok) trwają ułamki sekundy, więc
        # prędkość chwilowa przedłużona na cały czas dojazdu (~1 s) przepowiadała ucieczkę,
        # której nie było, i kamera ruszała w połowie ruchu - drugi ruch domykał (schody).
        if abs(error + v * ESCAPE_HORIZON) > (edge - EDGE_MARGIN) * fov:
            ax.settle_since = None
            return ESCAPE
        if ax.settle_since is None:
            ax.settle_since = t
        if t - ax.settle_since >= SETTLE_MAX_WAIT:
            ax.settle_since = None
            return GO
        self._note = f"czekam, aż cel stanie ({axis})"
        return WAIT

    def _move(self, axis: str, aim: float, v: float, current: float, force: bool = False) -> list[Command]:
        ax = self._axes[axis]
        lead = 0.0
        # Wyprzedzenie tylko w poziomie: idąca osoba przesuwa się w pan. Pionowa "prędkość"
        # to kiwanie i pochylenia - wyprzedzenie jej wystrzeliwało tilt ponad cel i drugi
        # ruch wracał (sesja 20260926-011024, t=191,9 s i 239,5 s).
        if self.profile.lead and axis == "pan":
            speed = max(-LEAD_MAX_SPEED, min(LEAD_MAX_SPEED, v))
            lead = speed * (self.dyn.abs_latency + self.dyn.abs_duration(aim - current) / 2.0)
            reach = LEAD_MAX_FOV * self._lead_hfov
            lead = max(-reach, min(reach, lead))
        target = self.limits.clamp(axis, aim + lead)
        if not force and abs(target - current) < MIN_MOVE:
            ax.state, ax.fast_since = SPOKOJ, None
            if axis == "pan":
                self._pan_side = self.side.side
            return []
        ax.state, ax.move_target, ax.fast_since, ax.settle_since = RUCH, target, None, None
        if axis == "pan":
            self._pan_side = self.side.side
        self._note = f"ruch {axis}"
        return [Command("abs", axis, target)]

    def _track_zoom(self, t: float, est: TargetEstimate, head: HeadModel, view: View) -> list[Command]:
        """Trzecia oś: zoom do planu. Pasmo w logarytmie krotności (jednakowo czułe przy 1x
        i 5x), zwłoka dłuższa niż pan/tilt, dojazd dokładnie do celu.

        Histereza (kalibracja 2026-09-25): ruch startuje, gdy stosunek cel/bieżący przekroczy
        ZOOM_BAND, ale licznik zwłoki resetuje się dopiero, gdy spadnie pod ZOOM_BAND_RESET -
        wariacje celu w szczelinie 1,15-1,2 nie zatrzymywałyby przygotowanego ruchu.

        Bramka stabilności celu (odstępstwo 5, odbiór 2026-09-25): ruch startuje tylko, gdy
        cel nie "pila" w oknie zwłoki (max/min krotności <= ZOOM_TARGET_STABILITY) - przy
        stałej odległości rozmowy wahania skali (gesty, obrót głowy) niosły stosunek przez
        próg 1,2 i bez bramki zoom pompował (13 ruchów w 2 min)."""
        ax = self._zoom_axis
        if ax.state == RUCH:
            if self._zoom_moving:
                return []
            ax.state, ax.fwin = SPOKOJ, None
        shot = shot_for(self.profile, est)
        goal = zoom_goal(est, shot, view) if self.auto_zoom else None
        self.last_zoom_goal = goal
        if goal is None:
            ax.state, ax.fwin = SPOKOJ, None
            return []
        r = abs(math.log(zoom_factor(goal) / zoom_factor(view.zoom_value)))
        if r <= math.log(ZOOM_BAND_RESET):
            ax.state, ax.fwin = SPOKOJ, None
            return []
        if r > math.log(ZOOM_BAND) and ax.state == SPOKOJ:
            ax.state, ax.since, ax.fwin = CZUJNY, t, None
        # Stosunek w szczelinie (ZOOM_BAND_RESET, ZOOM_BAND]: ani resetu, ani startu licznika.
        if ax.state == CZUJNY:
            win = ax.fwin if ax.fwin is not None else []
            while win and t - win[0][0] > ZOOM_DWELL:
                win.pop(0)
            win.append((t, zoom_factor(goal)))
            ax.fwin = win
            stable = max(f for _, f in win) / min(f for _, f in win) <= ZOOM_TARGET_STABILITY
            if (t - ax.since >= ZOOM_DWELL and stable and self.side.pending is None
                    and not (head.moving("pan", t) or head.moving("tilt", t))):
                ax.state, ax.move_target, ax.fwin = RUCH, goal, None
                self._note = f"zoom: plan {shot.name}"
                cmds = [Command("zoom", "zoom", goal)]
                if ZOOM_WITH_PAN_TILT:
                    for axis in ("pan", "tilt"):
                        cmds += self._move(axis, self._aim(axis, est, view), 0.0, head.angle(axis, t))
                return cmds
        return []

    def _follow(self, axis: str, t: float, est: TargetEstimate, head: HeadModel,
                aim: float, v: float) -> list[Command]:
        """Jazda ze stałą prędkością; stop, gdy głowica po wybiegu dogoni przyszłą pozycję celu."""
        ax = self._axes[axis]
        d = ax.direction
        rest = head.rest_angle(axis, t)
        target_future = aim + v * self.dyn.coast_time()
        lo, hi = self.limits.bounds(axis)
        margin = self._follow_margin()      # decyzja zapada raz na takt - zapas na jeden takt jazdy
        at_limit = (d > 0 and rest + margin >= hi) or (d < 0 and rest - margin <= lo)
        if d * (rest - target_future) >= 0 or at_limit or v * d <= 0:
            ax.state = HAMOWANIE
            self._note = "hamuję"
            return [Command("vel", axis, 0)]
        return [Command("vel", axis, d)]

    def _follow_margin(self) -> float:
        return self.dyn.vel_speed * FOLLOW_MARGIN_S
