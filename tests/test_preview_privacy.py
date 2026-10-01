#!/usr/bin/env python3
"""Preview in the window while privacy is switched on and off: the slate appears, goes away,
and an error in the preview loop never freezes the picture. No real window: a mock Flet page.

    .venv/bin/python tests/test_preview_privacy.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import flet as ft  # noqa: E402
from runner import run  # noqa: E402
from test_engine import make_engine  # noqa: E402

from app import CameraApp  # noqa: E402
from eagleeye import i18n  # noqa: E402


def _app():
    engine, _ = make_engine()
    engine.start()
    engine.command("language", "en")
    return engine, CameraApp(MagicMock(), engine, MagicMock())


async def _watch(ui, steps) -> asyncio.Task:
    """Runs the preview loop and calls each ``(seconds, action)`` of ``steps`` in turn."""
    task = asyncio.create_task(ui._preview_loop())
    for seconds, action in steps:
        action()
        await asyncio.sleep(seconds)
    return task


async def _stop(ui, task) -> None:
    ui.closing = True
    await asyncio.wait_for(task, timeout=3)


def test_preview_badge_is_the_text_in_the_corner() -> None:
    engine, ui = _app()
    try:
        assert isinstance(ui.preview_badge, ft.Text), type(ui.preview_badge).__name__
        corner = ui.preview_stack.controls[-1]
        assert corner.content is ui.preview_badge
    finally:
        engine.shutdown()
        i18n.set_language("en")


def test_slate_appears_and_goes_away_with_privacy() -> None:
    engine, ui = _app()

    async def scenario():
        task = await _watch(ui, [(0.4, lambda: engine.command("privacy", "on"))])
        assert not task.done(), f"the preview loop died: {task.exception() if task.done() else ''}"
        assert ui._privacy_shown and ui.preview_badge.value == i18n.t("app.privacy_preview")
        engine.command("privacy", "off")
        await asyncio.sleep(0.4)
        assert not task.done(), "the preview loop must survive the end of privacy"
        assert not ui._privacy_shown, "the slate must go away when privacy ends"
        assert ui.preview_badge.value != i18n.t("app.privacy_preview")
        await _stop(ui, task)

    try:
        asyncio.run(scenario())
    finally:
        engine.shutdown()
        i18n.set_language("en")


def test_an_error_in_one_iteration_does_not_freeze_the_preview() -> None:
    engine, ui = _app()
    calls = []

    def boom() -> None:
        calls.append(1)
        raise RuntimeError("simulated failure while drawing the slate")

    ui._show_privacy_card = boom

    async def scenario():
        task = await _watch(ui, [(0.8, lambda: engine.command("privacy", "on"))])
        assert calls, "the failing code path was not exercised"
        assert not task.done(), "one failed iteration must not end the loop"
        await _stop(ui, task)

    try:
        asyncio.run(scenario())
    finally:
        engine.shutdown()
        i18n.set_language("en")


if __name__ == "__main__":
    run(globals(), "Preview and privacy")
