#!/usr/bin/env python3
"""The "Correct light" button: busy handling, outcome notice, enabled state.

    .venv/bin/python tests/test_light_button.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

import app as app_module  # noqa: E402
from app import CameraApp  # noqa: E402
from eagleeye import i18n, lightfix  # noqa: E402
from eagleeye.lightfix import LightResult, status_message  # noqa: E402


def make_app(result, privacy: bool = False, stream=object()):
    i18n.set_language("en")
    app = CameraApp.__new__(CameraApp)
    app.engine = SimpleNamespace(correct_light=lambda: result, privacy=SimpleNamespace(active=privacy),
                                 stream=stream)
    app.light_btn = SimpleNamespace(disabled=False, update=lambda: None)
    app._light_busy = False
    notes: list[tuple] = []
    app._notify = lambda text, color=None: notes.append((text, color))
    return app, notes


def test_success_is_reported_in_the_ok_colour_and_the_button_comes_back() -> None:
    result = LightResult(lightfix.OK, np.arange(256, dtype=np.uint8), 26.0, 66.0)
    app, notes = make_app(result)
    asyncio.run(app._on_correct_light(None))
    assert notes == [(status_message(result).text(), app_module.OK)]
    assert app.light_btn.disabled is False and app._light_busy is False


def test_failures_are_warnings() -> None:
    for status in (lightfix.NO_FACE, lightfix.NO_PERSON, lightfix.NO_SKIN, lightfix.NO_FRAME, lightfix.FAILED):
        app, notes = make_app(LightResult(status))
        asyncio.run(app._on_correct_light(None))
        assert notes[0][1] == app_module.WARN, status
    app, notes = make_app(LightResult(lightfix.WELL_LIT))
    asyncio.run(app._on_correct_light(None))
    assert notes[0][1] == app_module.OK


def test_a_second_click_while_busy_does_nothing() -> None:
    app, notes = make_app(LightResult(lightfix.OK))
    app.engine.correct_light = lambda: (_ for _ in ()).throw(AssertionError("must not run"))
    app._light_busy = True
    asyncio.run(app._on_correct_light(None))
    assert notes == []


def test_button_is_disabled_without_stream_during_privacy_and_while_busy() -> None:
    app, _ = make_app(LightResult(lightfix.OK))
    assert app._light_button_disabled() is False
    app._light_busy = True
    assert app._light_button_disabled() is True
    app, _ = make_app(LightResult(lightfix.OK), privacy=True)
    assert app._light_button_disabled() is True
    app, _ = make_app(LightResult(lightfix.OK), stream=None)
    assert app._light_button_disabled() is True


if __name__ == "__main__":
    run(globals(), "Light button")
