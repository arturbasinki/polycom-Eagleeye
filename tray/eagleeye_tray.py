#!/usr/bin/python3
"""Ikona EagleEye w zasobniku GNOME.

Działa na SYSTEMOWYM python3 (ma gi/GTK i AyatanaAppIndicator3), nie w projektowym
venv. Z aplikacją rozmawia przez gniazdo sterujące (eagleeye.control - tylko
biblioteka standardowa). Uruchamia i zamyka ją silnik aplikacji; gdy aplikacji
nie ma (gniazdo nie odpowiada), ikona sama się zamyka.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eagleeye.control import send  # noqa: E402

ASSETS = ROOT / "assets"
ICON = ASSETS / "eagleeye-tray.svg"
ICON_PRIVACY = ASSETS / "eagleeye-tray-prywatnosc.svg"
PROFILE_LABELS = {"talk": "rozmowa", "presentation": "prezentacja (eksperymentalna)"}
POLL_S = 1


def icon_for(state: dict) -> Path:
    return ICON_PRIVACY if state.get("privacy") else ICON


def tooltip(state: dict) -> str:
    if state.get("privacy"):
        return "EagleEye: prywatność włączona"
    if not state.get("camera"):
        return "EagleEye: kamera niepodłączona"
    tracking = "śledzenie włączone" if state.get("tracking") else "śledzenie wyłączone"
    return f"EagleEye: {tracking}, profil {state.get('profile', '?')}"


def main() -> int:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
    from gi.repository import GLib, Gtk

    indicator = AppIndicator.Indicator.new("eagleeye", str(ICON),
                                           AppIndicator.IndicatorCategory.HARDWARE)
    indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
    indicator.set_title("EagleEye")
    updating = [False]     # zmiany z odpytywania stanu nie mogą wysyłać poleceń

    def command(cmd: str, arg: str | None = None) -> None:
        if updating[0]:
            return
        try:
            send(cmd, arg)
        except OSError:
            Gtk.main_quit()

    menu = Gtk.Menu()
    show = Gtk.MenuItem(label="Pokaż okno")
    show.connect("activate", lambda _w: command("show"))
    tracking = Gtk.CheckMenuItem(label="Śledzenie")
    tracking.connect("toggled", lambda w: command("tracking", "on" if w.get_active() else "off"))
    profile_item = Gtk.MenuItem(label="Profil")
    profile_menu = Gtk.Menu()
    radios, group = {}, None
    for name, label in PROFILE_LABELS.items():
        radio = Gtk.RadioMenuItem.new_with_label_from_widget(group, label)
        group = radio
        radio.connect("toggled", lambda w, n=name: w.get_active() and command("profile", n))
        radios[name] = radio
        profile_menu.append(radio)
    profile_item.set_submenu(profile_menu)
    privacy = Gtk.CheckMenuItem(label="Prywatność   Super+Shift+C")
    privacy.connect("toggled", lambda w: command("privacy", "on" if w.get_active() else "off"))
    quit_item = Gtk.MenuItem(label="Zakończ")
    quit_item.connect("activate", lambda _w: command("quit"))
    for item in (show, Gtk.SeparatorMenuItem(), tracking, profile_item, privacy,
                 Gtk.SeparatorMenuItem(), quit_item):
        menu.append(item)
    menu.show_all()
    indicator.set_menu(menu)

    def poll() -> bool:
        try:
            reply = send("state")
        except (OSError, ValueError):
            Gtk.main_quit()
            return False
        state = reply.get("state") or {}
        updating[0] = True
        try:
            tracking.set_active(bool(state.get("tracking")))
            tracking.set_sensitive(bool(state.get("camera")) and not state.get("privacy"))
            privacy.set_active(bool(state.get("privacy")))
            radio = radios.get(state.get("profile"))
            if radio is not None:
                radio.set_active(True)
            indicator.set_icon_full(str(icon_for(state)), tooltip(state))
        finally:
            updating[0] = False
        return True

    poll()
    GLib.timeout_add_seconds(POLL_S, poll)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
