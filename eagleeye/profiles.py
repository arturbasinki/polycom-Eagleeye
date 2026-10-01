"""Profile śledzenia: "rozmowa" (spokój) i "prezentacja" (nadążanie).

Wartości startowe ze specyfikacji; w interfejsie da się nadpisać tylko pola
z ``TUNABLE`` (sekcja "zaawansowane").
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from .framing import SHOTS
from .geometry import deg


@dataclass(frozen=True)
class Profile:
    name: str
    trigger_pan: float       # strefa wyzwalania: ułamek szerokości kadru od punktu kadrowania
    trigger_tilt: float      # ... i wysokości kadru
    dwell: float             # s nieprzerwanie poza strefą, zanim kamera ruszy
    lead: bool               # wyprzedzenie ruchu o prędkość celu
    follow: bool             # podążanie prędkościowe (tylko pan)
    follow_speed: float      # próg prędkości celu do podążania [arcsec/s]
    ladder_max: int          # ostatni krok drabiny utraty celu
    ladder_step_time: float  # s między krokami drabiny
    # Pomiary z klatek zrobionych w trakcie ruchu absolutnego kamery są przesunięte
    # o 3-4° w kierunku jazdy. Gdy cel po ruchu stoi (rozmowa), lepiej je pominąć
    # i trzymać ostatnią pewną pozycję; gdy cel idzie (prezentacja), pominięcie
    # oślepia tracker akurat wtedy, gdy cel się przesuwa.
    hold_during_moves: bool = False
    # Doganianie celu, który zniknął przy krawędzi w ruchu (krok 1 drabiny). W chwili
    # utraty prędkość filtra bywa bezwartościowa (luki w detekcji) - w rozmowie strzelało
    # 54-61° za daleko, a ostatni azymut trafiał w osobę (sesja 20260923-020939).
    catch_up: bool = True
    # Kompozycja (framing.py): plan i strona kadru. Pion wyznacza linia złotego podziału
    # (framing.GOLDEN) - wspólna dla profili, dawne head_height (0,375 / 0,30) usunięte.
    shot: str = "MCU"        # plan: framing.SHOTS
    side_enter: float = 0.35 # |yaw| powyżej - twarz odwrócona, kadr na punkt boczny
    side_exit: float = 0.20  # |yaw| poniżej - twarz na wprost, powrót na środek
    side_dwell: float = 1.5  # s trwałego odwrócenia (albo powrotu), zanim zmieni się strona


# trigger_tilt = 0,12 (przegląd 2026-09-26): strefa wyzwalania to próg reakcji na *duży*
# rozjazd, a dokładność kompozycji zapewnia pasmo 5% z cichym re-fitem (director.
# COMPOSITION_BAND/REFIT_DWELL). Kalibracyjne 0,05 (≈2°) było równe pasmu, więc re-fit
# w pionie nie istniał, a każde kiwnięcie głową (±2°) po zwłoce 0,2 s w prezentacji
# ruszało tilt - wprost na szczyt kiwnięcia, a drugi ruch wracał (sesja 20260926-011024).
ROZMOWA = Profile("rozmowa", 0.15, 0.12, 0.8, False, False, deg(8), 2, 4.0,
                  hold_during_moves=True, catch_up=False, shot="MCU")
PREZENTACJA = Profile("prezentacja", 0.26, 0.12, 0.2, True, True, deg(8), 4, 1.5, shot="MS")
PROFILES = {p.name: p for p in (ROZMOWA, PREZENTACJA)}
TUNABLE = ("trigger_pan", "trigger_tilt", "dwell", "ladder_step_time",
           "shot", "side_enter", "side_exit", "side_dwell")


def resolve(name: str, overrides: dict | None = None) -> Profile:
    base = PROFILES.get(name, ROZMOWA)
    changes: dict = {}
    for key, value in (overrides or {}).items():
        if key == "shot":
            if value in SHOTS:
                changes[key] = value
        elif key in TUNABLE:
            changes[key] = float(value)
    return dataclasses.replace(base, **changes)
