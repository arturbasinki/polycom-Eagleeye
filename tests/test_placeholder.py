#!/usr/bin/env python3
"""Zaślepka wirtualnej kamery: pisze planszę, gdy aplikacja nie działa, i oddaje urządzenie.

    .venv/bin/python tests/test_placeholder.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye import i18n  # noqa: E402
from eagleeye.placeholder import OFF_CARD, Placeholder  # noqa: E402
from eagleeye.v4l2 import V4L2Error  # noqa: E402
from eagleeye.vcam import card_i420, card_texts  # noqa: E402


class FakeDevice:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def close(self) -> None:
        self.closed = True


def make(app=False, factory=None, language=lambda: "en"):
    state = {"app": app, "devices": []}

    def default_factory():
        dev = FakeDevice()
        state["devices"].append(dev)
        return dev
    p = Placeholder(device_factory=factory or default_factory, app_running=lambda: state["app"],
                    size=(64, 36), language=language)
    return p, state


def test_writes_off_card_when_app_is_not_running() -> None:
    p, state = make()
    assert p.tick() == "writing"
    assert state["devices"][0].writes == [card_i420(*card_texts(OFF_CARD), size=(64, 36))]


def test_releases_device_when_app_starts_and_takes_it_back_after() -> None:
    p, state = make()
    p.tick()
    state["app"] = True
    assert p.tick() == "app"
    assert state["devices"][0].closed                  # urządzenie wolne dla aplikacji
    state["app"] = False
    assert p.tick() == "writing"
    assert len(state["devices"]) == 2 and state["devices"][1].writes


def test_does_not_open_device_while_app_runs() -> None:
    p, state = make(app=True)
    assert p.tick() == "app" and state["devices"] == []


def test_device_busy_or_missing_is_retried_without_crash() -> None:
    calls = []

    def busy():
        calls.append(1)
        raise V4L2Error("S_FMT wyjścia: Invalid argument")   # inny pisarz trzyma urządzenie
    p, _ = make(factory=busy)
    assert p.tick() == "no_device" and p.tick() == "no_device" and len(calls) == 2
    p, _ = make(factory=lambda: None)
    assert p.tick() == "no_device"


def test_write_error_releases_device() -> None:
    class Broken(FakeDevice):
        def write(self, data: bytes) -> None:
            raise OSError(5, "I/O error")
    dev = Broken()
    p, _ = make(factory=lambda: dev)
    assert p.tick() == "write_error" and dev.closed


def test_card_is_rerendered_when_the_language_changes() -> None:
    lang = ["en"]
    p, state = make(language=lambda: lang[0])
    try:
        assert p.tick() == "writing"
        lang[0] = "pl"
        assert p.tick() == "writing"
        first, second = state["devices"][0].writes
        assert first != second
    finally:
        i18n.set_language("en")


if __name__ == "__main__":
    run(globals(), "Zaślepka wirtualnej kamery")
