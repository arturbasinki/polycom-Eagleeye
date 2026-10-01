"""Filtr celu: pozycja i prędkość głowy w kątach świata.

Dwa niezależne filtry Kalmana (pan, tilt) z modelem stałej prędkości.
Kąt świata nie zmienia się, gdy kamera się obraca, więc pomiary z trakcie
ruchu głowicy są tak samo dobre jak w bezruchu - pod warunkiem, że pozycja
głowicy w chwili klatki pochodzi z modelu głowicy.

Bramkowanie zastępuje dawny ``max_target_jump_px``: pomiar dalej niż
``gate_sigmas`` odchyleń od przewidywania jest odrzucany (detektor raz
obejmuje całą sylwetkę, raz jej część). Kilka takich pomiarów z rzędu
znaczy, że cel naprawdę jest gdzie indziej - wtedy filtr startuje od nowa.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import deg


@dataclass(frozen=True)
class FilterSettings:
    # Szum pomiaru i model ruchu człowieka: estymacja największej wiarygodności z innowacji
    # filtra na 158 tys. pomiarów z 9 sesji (odcinki bez ruchu kamery, 2026-09-26). Dawne
    # 0,22° / 1°/s² robiły z filtra ~15× za bezwładny: spóźniał się na starcie ruchu
    # i przestrzeliwał po zatrzymaniu (estymata 2-5° za stojącą osobą) - reżyser dojeżdżał
    # schodami i wracał. Filtr ma mówić prawdę o celu; o tym, czy kamera ma reagować,
    # decyduje reżyser (strefa, zwłoka, pasmo kompozycji, osiadanie celu).
    meas_sigma: float = 300.0          # szum punktu głowy: 2× MLE (0,04°) - zapas na gorsze światło i detekcję
    accel_sigma: float = deg(12.0)     # jak gwałtownie człowiek zmienia prędkość w poziomie [arcsec/s²]
    accel_sigma_tilt: float = deg(6.0) # ... i w pionie
    gate_sigmas: float = 12.0
    reset_after_rejects: int = 5
    # ... albo gdy od ostatniego przyjętego pomiaru minęło tyle, a pomiary nadal przychodzą
    # (odrzucane). Musi być krótsze niż lost_after - inaczej przy wolniejszej detekcji
    # (5 klatek przy 10 Hz = 0,5 s) cel "ginął", choć był widoczny, i reżyser zaczynał
    # drabinę utraty zamiast przejść do nowej pozycji.
    reset_after_s: float = 0.25
    lost_after: float = 0.4            # s bez przyjętego pomiaru = cel utracony
    # Przewidywanie ponad ostatni pomiar najwyżej o tyle. Dłuższa ekstrapolacja starej
    # prędkości przez luki w detekcji (rozmycie w trakcie jazdy kamery) wypychała
    # estymatę 5-7° za zatrzymaną osobę i kamera dojeżdżała drugim ruchem.
    max_extrapolation: float = 0.1
    # Gdy pomiary są celowo wstrzymane (ruch absolutny kamery), estymata trzyma się
    # ostatniej pozycji najwyżej tyle sekund, zamiast uznawać cel za utracony.
    max_hold: float = 3.0
    attr_alpha: float = 0.3            # wygładzanie yaw i skali głowy (średnia wykładnicza)
    # Pomiar z klatki zrobionej w trakcie ruchu kamery: kąt świata = kąt głowicy z modelu
    # w chwili klatki + przesunięcie w pikselach. Niepewność chwili naświetlenia (USB, MJPEG,
    # rolling shutter) i błąd modelu trajektorii dają błąd ~ prędkość kamery × timing_sigma
    # + motion_model_sigma. Zamiast ufać takim klatkom jak statycznym (dodatnie sprzężenie:
    # pomiar ucieka w kierunku jazdy, reżyser dokłada ruch - oscylacja w sesji 20260926-011024)
    # albo je wyrzucać, filtr dostaje ich prawdziwą wariancję (R zależne od ruchu).
    timing_sigma: float = 0.02         # s - z nagrań: rozrzut pomiaru w ruchu vs prędkość kamery
    motion_model_sigma: float = deg(0.3)  # błąd RMS modelu trajektorii (tools/measure_trajectory.py)


class Kalman1D:
    """Model stałej prędkości: stan (x, v), pomiar x."""

    def __init__(self, meas_sigma: float, accel_sigma: float) -> None:
        self.r = meas_sigma ** 2
        self.q = accel_sigma ** 2
        self.x = 0.0
        self.v = 0.0
        self.p = [[0.0, 0.0], [0.0, 0.0]]
        self.t = 0.0

    def reset(self, z: float, t: float) -> None:
        self.x, self.v, self.t = float(z), 0.0, t
        self.p = [[self.r, 0.0], [0.0, deg(30.0) ** 2]]

    def _predicted(self, t: float) -> tuple[float, list[list[float]]]:
        dt = max(0.0, t - self.t)
        (p00, p01), (p10, p11) = self.p
        q = self.q
        n00 = p00 + dt * (p10 + p01) + dt * dt * p11 + q * dt ** 4 / 4.0
        n01 = p01 + dt * p11 + q * dt ** 3 / 2.0
        n10 = p10 + dt * p11 + q * dt ** 3 / 2.0
        n11 = p11 + q * dt * dt
        return self.x + self.v * dt, [[n00, n01], [n10, n11]]

    def innovation(self, z: float, t: float, r_extra: float = 0.0) -> tuple[float, float]:
        """(reszta, wariancja reszty) pomiaru ``z`` w chwili ``t``."""
        x, p = self._predicted(t)
        return z - x, p[0][0] + self.r + r_extra

    def update(self, z: float, t: float, r_extra: float = 0.0) -> None:
        """``r_extra`` - dodatkowa wariancja tego pomiaru (np. klatka z ruchu kamery)."""
        x, p = self._predicted(t)
        s = p[0][0] + self.r + r_extra
        k0, k1 = p[0][0] / s, p[1][0] / s
        y = z - x
        self.x = x + k0 * y
        self.v = self.v + k1 * y
        self.p = [[(1 - k0) * p[0][0], (1 - k0) * p[0][1]],
                  [p[1][0] - k1 * p[0][0], p[1][1] - k1 * p[0][1]]]
        self.t = max(self.t, t)

    def position_at(self, t: float) -> float:
        return self.x + self.v * max(0.0, t - self.t)


@dataclass(frozen=True)
class TargetEstimate:
    pan: float
    tilt: float
    v_pan: float
    v_tilt: float
    t: float            # chwila, na którą przewidziano
    last_seen: float    # chwila ostatniego przyjętego pomiaru
    yaw: float | None = None          # kierunek twarzy, wygładzony (framing.SideSelector)
    head_scale: float | None = None   # odcinek oczy→barki w arcsec kąta świata, wygładzony

    @property
    def age(self) -> float:
        return self.t - self.last_seen


def _smooth(old: float | None, new: float | None, alpha: float) -> float | None:
    if new is None:
        return old
    if old is None:
        return float(new)
    return old + alpha * (float(new) - old)


class TargetFilter:
    def __init__(self, settings: FilterSettings = FilterSettings()) -> None:
        self.settings = settings
        self._pan = Kalman1D(settings.meas_sigma, settings.accel_sigma)
        self._tilt = Kalman1D(settings.meas_sigma, settings.accel_sigma_tilt)
        self._last_seen: float | None = None
        self._rejects = 0
        self._yaw: float | None = None
        self._scale: float | None = None

    def reset(self) -> None:
        self._last_seen = None
        self._rejects = 0
        self._yaw = None
        self._scale = None

    def _restart(self, t: float, pan: float, tilt: float) -> None:
        self._pan.reset(pan, t)
        self._tilt.reset(tilt, t)
        self._last_seen = t
        self._rejects = 0

    def motion_variance(self, cam_speed: float) -> float:
        """Dodatkowa wariancja pomiaru z klatki, gdy oś kamery jechała z ``cam_speed`` [arcsec/s]."""
        if cam_speed <= 0.0:
            return 0.0
        s = self.settings
        return (cam_speed * s.timing_sigma) ** 2 + s.motion_model_sigma ** 2

    def update(self, t: float, pan: float, tilt: float,
               yaw: float | None = None, head_scale: float | None = None,
               cam_speed: tuple[float, float] = (0.0, 0.0)) -> bool:
        """Dodaje pomiar kąta świata głowy (i opcjonalnie yaw, skalę). Zwraca, czy został przyjęty.

        ``cam_speed`` - prędkość osi (pan, tilt) kamery w chwili klatki; w ruchu pomiar jest
        mniej pewny (:meth:`motion_variance`) i słabiej przesuwa estymatę.
        """
        r_pan, r_tilt = (self.motion_variance(abs(v)) for v in cam_speed)
        if self._last_seen is None:
            self._restart(t, pan, tilt)
            self._yaw, self._scale = yaw, head_scale
            return True
        rp, sp = self._pan.innovation(pan, t, r_pan)
        rt, st = self._tilt.innovation(tilt, t, r_tilt)
        if rp * rp / sp + rt * rt / st > self.settings.gate_sigmas ** 2:
            self._rejects += 1
            if (self._rejects < self.settings.reset_after_rejects
                    and t - self._last_seen < self.settings.reset_after_s):
                return False
            self._restart(t, pan, tilt)
            self._yaw, self._scale = yaw, head_scale
            return True
        self._rejects = 0
        self._pan.update(pan, t, r_pan)
        self._tilt.update(tilt, t, r_tilt)
        self._last_seen = max(self._last_seen, t)
        a = self.settings.attr_alpha
        self._yaw = _smooth(self._yaw, yaw, a)
        self._scale = _smooth(self._scale, head_scale, a)
        return True

    def estimate(self, t: float, hold: bool = False, capped: bool = True) -> TargetEstimate | None:
        """Estymata na chwilę ``t``.

        ``hold=True`` - pomiary są wstrzymane z powodu ruchu kamery, więc brak nowych
        pomiarów nie oznacza utraty celu (do ``max_hold`` s).
        ``capped=False`` - przewidywanie bez limitu ``max_extrapolation`` (idący cel:
        podążanie i doganianie potrzebują przewidywania przez luki w detekcji).
        """
        if self._last_seen is None:
            return None
        age = t - self._last_seen
        limit = self.settings.max_hold if hold else self.settings.lost_after
        if age > limit:
            return None
        te = min(t, self._last_seen + self.settings.max_extrapolation) if capped else t
        return TargetEstimate(self._pan.position_at(te), self._tilt.position_at(te),
                              self._pan.v, self._tilt.v, t, self._last_seen,
                              yaw=self._yaw, head_scale=self._scale)
