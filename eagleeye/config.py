"""Persistent application settings and camera position presets."""

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
    # Measured head dynamics (fields of eagleeye.head_model.Dynamics).
    # An empty dict = values from the spike; filled in by tools/measure_dynamics.py --save.
    "dynamics": {},
    "tracking": {
        "profile": "talk",             # "talk" or "presentation"
        "overrides": {},               # overrides of profiles.TUNABLE fields from the "advanced" section
        "use_gpu": True,
        "invert_pan": False,
        "invert_tilt": False,
        "rate_hz": 15.0,
        "home": None,                  # [pan, tilt] of the "home" preset, or None
        "last_azimuth": None,          # [pan, tilt] of the person's last position - scan start
        "record": False,               # session recording to captures/sessions/*.jsonl
        "auto_zoom": True,             # zoom matched to the shot; a manual zoom disables it permanently
        "select_hold_s": 6.0,          # s of waiting for the selected person after they vanish
    },
}

RESOLUTIONS: list[tuple[int, int]] = [
    (640, 360), (960, 540), (1280, 720), (1920, 1080),
]


@dataclass
class Preset:
    """Saved camera position."""

    name: str
    pan: int = 0
    tilt: int = 0
    zoom: int = 0
    focus: int = 0
    focus_auto: int = 1


class Store:
    """Reads and writes ``config.json`` (atomic write, so the file is not corrupted)."""

    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path
        self.settings: dict = json.loads(json.dumps(DEFAULTS))  # deep copy
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
                # Old engine keys (PID, settle_*, trajectory) are skipped.
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

    # --- presets ---

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


def language_setting(path: Path = CONFIG_PATH) -> str:
    """The saved ``settings.language`` (``"auto"`` when missing); standard library only,
    so the placeholder service can read it without building a ``Store``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str((data.get("settings") or {}).get("language", "auto"))
    except (OSError, ValueError, AttributeError):
        return "auto"


def captures_dir() -> Path:
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    return CAPTURES_DIR


def pictures_dir() -> Path:
    """The user's pictures directory per XDG (localized, e.g. ~/Pictures)."""
    try:
        out = subprocess.run(["xdg-user-dir", "PICTURES"], capture_output=True,
                             text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    # xdg-user-dir returns $HOME when the pictures directory is not set
    if out and Path(out) != Path.home():
        return Path(out)
    return Path.home() / "Pictures"


def snapshots_dir() -> Path:
    """Directory for frame snapshots from the UI button."""
    path = pictures_dir() / "EagleEye"
    path.mkdir(parents=True, exist_ok=True)
    return path
