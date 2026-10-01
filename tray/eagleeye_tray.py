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

from eagleeye.config import language_setting  # noqa: E402
from eagleeye.control import send  # noqa: E402
from eagleeye.i18n import set_language, t  # noqa: E402

ASSETS = ROOT / "assets"
ICON = ASSETS / "eagleeye-tray.svg"
ICON_PRIVACY = ASSETS / "eagleeye-tray-privacy.svg"
PROFILE_NAMES = ("talk", "presentation")
POLL_S = 1


def icon_for(state: dict) -> Path:
    return ICON_PRIVACY if state.get("privacy") else ICON


def labels() -> dict[str, str]:
    """Menu labels in the active language."""
    return {"show": t("tray.show"), "tracking": t("tray.tracking"), "profile": t("tray.profile"),
            "privacy": t("tray.privacy"), "quit": t("tray.quit")}


def profile_label(name: str) -> str:
    return t(f"profile.{name}") if name in PROFILE_NAMES else str(name)


def tooltip(state: dict) -> str:
    if state.get("privacy"):
        return t("tray.tip.privacy")
    if not state.get("camera"):
        return t("tray.tip.no_camera")
    tracking = t("tracker.on") if state.get("tracking") else t("tracker.off")
    return t("tray.tip.status", tracking=tracking, profile=profile_label(state.get("profile", "?")))


def main() -> int:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
    from gi.repository import GLib, Gtk

    set_language(language_setting())
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

    text = labels()
    menu = Gtk.Menu()
    show = Gtk.MenuItem(label=text["show"])
    show.connect("activate", lambda _w: command("show"))
    tracking = Gtk.CheckMenuItem(label=text["tracking"])
    tracking.connect("toggled", lambda w: command("tracking", "on" if w.get_active() else "off"))
    profile_item = Gtk.MenuItem(label=text["profile"])
    profile_menu = Gtk.Menu()
    radios, group = {}, None
    for name in PROFILE_NAMES:
        radio = Gtk.RadioMenuItem.new_with_label_from_widget(group, profile_label(name))
        group = radio
        radio.connect("toggled", lambda w, n=name: w.get_active() and command("profile", n))
        radios[name] = radio
        profile_menu.append(radio)
    profile_item.set_submenu(profile_menu)
    privacy = Gtk.CheckMenuItem(label=text["privacy"])
    privacy.connect("toggled", lambda w: command("privacy", "on" if w.get_active() else "off"))
    quit_item = Gtk.MenuItem(label=text["quit"])
    quit_item.connect("activate", lambda _w: command("quit"))
    for item in (show, Gtk.SeparatorMenuItem(), tracking, profile_item, privacy,
                 Gtk.SeparatorMenuItem(), quit_item):
        menu.append(item)
    menu.show_all()
    indicator.set_menu(menu)

    current_language = [None]

    def apply_labels() -> None:
        text = labels()
        show.set_label(text["show"])
        tracking.set_label(text["tracking"])
        profile_item.set_label(text["profile"])
        privacy.set_label(text["privacy"])
        quit_item.set_label(text["quit"])
        for name, radio in radios.items():
            radio.set_label(profile_label(name))

    def poll() -> bool:
        try:
            reply = send("state")
        except (OSError, ValueError):
            Gtk.main_quit()
            return False
        state = reply.get("state") or {}
        language = state.get("language")
        if language and language != current_language[0]:
            set_language(language)
            current_language[0] = language
            apply_labels()
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
