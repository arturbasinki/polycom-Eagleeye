---
type: Contract
title: Configuration File
description: "The tolerant, atomic JSON settings-and-presets file contract, with an empty dynamics override."
tags: [contract, configuration]
timestamp: 2026-10-02
---

# Configuration File

The persisted-settings contract: a `config.json` next to the code, holding user settings and camera
presets. It is deliberately **not** in git; the app creates it on first save and runs fine without it.

## Shape

```
{
  "settings": {
    "device", "preview_width", "preview_height", "preview_fps", "overlay", "language",
    "dynamics": {},
    "tracking": {
      "profile", "overrides", "use_gpu", "invert_pan", "invert_tilt", "rate_hz",
      "home", "last_azimuth", "record", "auto_zoom", "select_hold_s"
    }
  },
  "presets": [ { "name", "pan", "tilt", "zoom", "focus", "focus_auto" } ]
}
```

## Rules

- Loading is tolerant: unknown keys are ignored, and old engine keys (PID, `settle_*`, trajectory) are
  skipped. Junk values in `dynamics` never erase the in-code calibration.
- Saving is **atomic** (write to a temp file, then rename) so the file cannot be corrupted.
- `config.example.json` documents every default; `dynamics` is an **override** of
  [the in-code calibration](/invariants/dynamics-calibration-in-code.md).

# Citations
- [eagleeye/config.py](/eagleeye/config.py)
- [config.example.json](/config.example.json)
