"""Trwałe ustawienia aplikacji i presety pozycji kamery."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
CAPTURES_DIR = ROOT / "captures"

DEFAULTS: dict = {
    "device": "/dev/video0",
    "preview_width": 1280,
    "preview_height": 720,
    "preview_fps": 15,
    "overlay": True,
    "language": "auto",            # "auto" (from $LANG), or a catalog code: "en", "pl"
    # Zmierzona dynamika głowicy (pola eagleeye.head_model.Dynamics).
    # Pusty słownik = wartości ze spike'u; wypełnia tools/measure_dynamics.py --save.
    "dynamics": {},
    "tracking": {
        "profile": "talk",             # "talk" or "presentation"
        "overrides": {},               # nadpisania pól profiles.TUNABLE z sekcji "zaawansowane"
        "use_gpu": True,
        "invert_pan": False,
        "invert_tilt": False,
        "rate_hz": 15.0,
        "home": None,                  # [pan, tilt] presetu "dom" albo None
        "last_azimuth": None,          # [pan, tilt] ostatniej pozycji osoby - start skanu
        "record": False,               # zapis sesji do captures/sessions/*.jsonl
        "auto_zoom": True,             # zoom dobierany do planu; ręczny zoom trwale wyłącza
        "select_hold_s": 6.0,          # s czekania na wybraną osobę po jej zniknięciu
    },
}

RESOLUTIONS: list[tuple[int, int]] = [
    (640, 360), (960, 540), (1280, 720), (1920, 1080),
]


@dataclass
class Preset:
    """Zapisana pozycja kamery."""

    name: str
    pan: int = 0
    tilt: int = 0
    zoom: int = 0
    focus: int = 0
    focus_auto: int = 1


class Store:
    """Wczytuje i zapisuje ``config.json`` (zapis atomowy, żeby nie uszkodzić pliku)."""

    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path
        self.settings: dict = json.loads(json.dumps(DEFAULTS))  # głęboka kopia
        self.presets: list[Preset] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for key, value in (data.get("settings") or {}).items():
            if key == "tracking" and isinstance(value, dict):
                # Klucze starego silnika (PID, settle_*, trajektoria) są pomijane.
                for k, v in value.items():
                    if k in self.settings["tracking"]:
                        self.settings["tracking"][k] = v
            elif key in self.settings:
                self.settings[key] = value
        for item in data.get("presets") or []:
            try:
                self.presets.append(Preset(**item))
            except TypeError:
                continue

    def save(self) -> None:
        payload = {
            "settings": self.settings,
            "presets": [asdict(p) for p in self.presets],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".config-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # --- presety ---

    def upsert_preset(self, preset: Preset) -> None:
        for i, existing in enumerate(self.presets):
            if existing.name == preset.name:
                self.presets[i] = preset
                break
        else:
            self.presets.append(preset)
        self.save()

    def delete_preset(self, name: str) -> bool:
        before = len(self.presets)
        self.presets = [p for p in self.presets if p.name != name]
        if len(self.presets) != before:
            self.save()
            return True
        return False

    def preset(self, name: str) -> Preset | None:
        return next((p for p in self.presets if p.name == name), None)


def captures_dir() -> Path:
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    return CAPTURES_DIR


def pictures_dir() -> Path:
    """Katalog obrazów użytkownika wg XDG (~/Pictures, ~/Obrazy - zależnie od języka)."""
    try:
        out = subprocess.run(["xdg-user-dir", "PICTURES"], capture_output=True,
                             text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    # xdg-user-dir zwraca $HOME, gdy katalog obrazów nie jest ustawiony
    if out and Path(out) != Path.home():
        return Path(out)
    return Path.home() / "Pictures"


def snapshots_dir() -> Path:
    """Katalog na zrzuty klatek z przycisku w UI."""
    path = pictures_dir() / "EagleEye"
    path.mkdir(parents=True, exist_ok=True)
    return path
