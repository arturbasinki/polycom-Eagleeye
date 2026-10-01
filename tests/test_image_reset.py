"""Przycisk „domyślne” w karcie Obraz: wszystkie kontrolki obrazu wracają do wartości fabrycznych.

Pułapka: zapis temperatury balansu bieli wyłącza balans auto (``AUTO_DEPENDENCIES``),
więc reset, który ustawia temperaturę, musi potem przywrócić sam tryb auto.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import CameraApp
from eagleeye.v4l2 import (CID_BACKLIGHT_COMP, CID_BRIGHTNESS, CID_GAMMA, CID_WHITE_BALANCE_AUTO,
                           CID_WHITE_BALANCE_TEMP, Control)


class FakeControls:
    """Kamera z kontrolkami obrazu; temperatura bieli jest zablokowana, gdy auto działa."""

    def __init__(self) -> None:
        self.defaults = {CID_BRIGHTNESS: 5, CID_GAMMA: 222, CID_BACKLIGHT_COMP: 1,
                         CID_WHITE_BALANCE_TEMP: 5000, CID_WHITE_BALANCE_AUTO: 1}
        self.values = {CID_BRIGHTNESS: 7, CID_GAMMA: 159, CID_BACKLIGHT_COMP: 0,
                       CID_WHITE_BALANCE_TEMP: 4000, CID_WHITE_BALANCE_AUTO: 1}

    def control(self, cid):
        if cid not in self.defaults:
            return None
        return Control(cid, hex(cid), 1, 0, 10000, 1, self.defaults[cid], 0)

    def get(self, cid):
        return self.values[cid]

    def set(self, cid, value):
        self.values[cid] = value
        return value


def make_app(controls: FakeControls) -> CameraApp:
    app = CameraApp.__new__(CameraApp)
    app.engine = SimpleNamespace(controls=controls)
    app.switch_widgets = {}
    app.control_widgets = {}
    app._notify = lambda *_a, **_k: None
    app._sync_from_device = lambda: None
    app._refresh_widgets = lambda: None
    return app


def test_reset_restores_every_image_control_including_auto_white_balance():
    controls = FakeControls()
    make_app(controls)._on_reset_image(None)
    wrong = {hex(c): (v, controls.defaults[c]) for c, v in controls.values.items()
             if v != controls.defaults[c]}
    assert not wrong, f"(jest, fabrycznie): {wrong}"


if __name__ == "__main__":
    from runner import run
    run(globals(), "Reset kontrolek obrazu")
