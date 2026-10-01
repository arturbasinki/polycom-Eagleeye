#!/usr/bin/env python3
"""Sterowanie kamerą Polycom EagleEye IV USB.

Aplikacja desktopowa (Flet/Flutter) do kamery udostępnianej przez V4L2.
Uruchamianie::

    .venv/bin/flet run app.py          # okno natywne
    .venv/bin/flet run --web app.py    # w przeglądarce

Warstwy: ``eagleeye.v4l2`` (sprzęt), ``eagleeye.detectors`` (detekcja),
``eagleeye.tracker`` (śledzenie), ``eagleeye.config`` (ustawienia).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import flet as ft
import flet.canvas as cv

from eagleeye.config import RESOLUTIONS, Preset, Store, snapshots_dir
from eagleeye.control import ControlServer, InstanceRunning, send
from eagleeye.detectors import gpu_status
from eagleeye.engine import Engine, UiHooks
from eagleeye.framing import SHOTS
from eagleeye.overlay import Shape, frame_point, overlay_shapes, selection_text
from eagleeye.profiles import PROFILES, TUNABLE, resolve
from eagleeye.trayproc import TrayProcess
from eagleeye.v4l2 import (CID_BACKLIGHT_COMP, CID_BRIGHTNESS, CID_CONTRAST,
                           CID_FOCUS_ABSOLUTE, CID_FOCUS_AUTO, CID_GAMMA, CID_HUE,
                           CID_PAN_ABSOLUTE, CID_SATURATION,
                           CID_SHARPNESS, CID_TILT_ABSOLUTE,
                           CID_WHITE_BALANCE_AUTO, CID_WHITE_BALANCE_TEMP,
                           CID_ZOOM_ABSOLUTE, ControlDevice,
                           V4L2Error, list_input_devices)
from eagleeye.vcam import CARD_LABEL, PRIVACY_TEXT, render_card

# Paleta - ciemny motyw dobrany pod długą pracę przed kamerą.
BG = "#0e1116"
PANEL = "#161b22"
PANEL_SOFT = "#1c232c"
BORDER = "#2a323d"
TEXT = "#e6edf3"
MUTED = "#8b949e"
ACCENT = "#2f81f7"
OK = "#3fb950"
WARN = "#d29922"
ERROR = "#f85149"

SLIDER_WIDTH = 220
PROFILE_LABELS = {"rozmowa": "rozmowa", "prezentacja": "prezentacja (eksperymentalna)"}
SHOT_LABELS = {"CU": "zbliżenie (CU)", "MCU": "bliski (MCU)", "MS": "średni (MS)"}
OPTICS_STEP_ZOOM = 600      # krok zoomu przyciskami (~1.3x)
OPTICS_STEP_FOCUS = 150
PREVIEW_BADGE_PERIOD = 1.0  # s - napis z fps co klatkę to drugi komunikat do Fleta na klatkę

log = logging.getLogger("eagleeye")

# Kontrolki, które są nieaktywne, gdy działa tryb automatyczny: ``uvcvideo``
# zwraca wtedy EPERM ("Permission denied") przy każdej próbie zapisu. Bez tej
# obsługi suwak ostrości wygląda na działający, a nic nie robi.
AUTO_DEPENDENCIES = {
    CID_FOCUS_ABSOLUTE: CID_FOCUS_AUTO,
    CID_WHITE_BALANCE_TEMP: CID_WHITE_BALANCE_AUTO,
}


def ensure_manual_mode(controls: ControlDevice, ctrl_id: int) -> bool:
    """Wyłącza tryb automatyczny, jeśli kontrolka jest od niego zależna.

    ``uvcvideo`` zwraca EPERM przy zapisie kontrolki nieaktywnej, więc żeby
    ustawić ręczną ostrość trzeba najpierw wyłączyć autofocus. Zwraca ``True``,
    gdy tryb automatyczny faktycznie został wyłączony.
    """
    auto = AUTO_DEPENDENCIES.get(ctrl_id)
    if auto is None:
        return False
    try:
        if controls.get(auto):
            controls.set(auto, 0)
            return True
    except V4L2Error:
        pass  # brak kontrolki auto - próbujemy zapisać i tak
    return False


class CameraApp:
    """Cały stan aplikacji w jednym miejscu - interfejs i sprzęt."""

    def __init__(self, page: ft.Page, engine: Engine, tray: TrayProcess) -> None:
        self.page = page
        self.engine = engine
        self.tray = tray
        self.store = engine.store
        self.settings = engine.settings

        self.control_widgets: dict[int, ft.Slider] = {}
        self.switch_widgets: dict[int, ft.Switch] = {}
        self.overlay = True
        self.closing = False
        self.hidden = False
        self._last_frame_id = 0
        self._last_preview = 0.0
        self._last_badge = 0.0
        self._dragging: set[int] = set()
        self._fps_ema = 0.0
        self._preview_fps_ema = 0.0
        self._last_jpg: bytes | None = None

        self._build_widgets()
        self._build_layout()

    @property
    def stream(self):
        return self.engine.stream

    @property
    def controls(self):
        return self.engine.controls

    @property
    def tracker(self):
        return self.engine.tracker

    # ------------------------------------------------------------------
    # Budowa interfejsu
    # ------------------------------------------------------------------

    def _build_widgets(self) -> None:
        s = self.settings
        tr = s["tracking"]

        # Flet 1.0 wymaga niepustego `src` - startujemy z przezroczystym pikselem
        # 1x1, który pierwsza klatka z kamery zaraz zastąpi.
        transparent_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/wIAAgMBAp0YVwAAAABJRU5ErkJggg=="
        )
        self.preview = ft.Image(
            src=transparent_png, fit=ft.BoxFit.CONTAIN, gapless_playback=True,
            border_radius=10,
            # Obraz przy górnej krawędzi, w poziomie na środku - tak samo liczy
            # położenie nakładka (overlay_shapes), inaczej punkty się rozjeżdżają.
            align=ft.Alignment.TOP_CENTER,
        )
        self.preview_placeholder = ft.Container(
            expand=True, bgcolor="#0b0e13", border_radius=10,
            content=ft.Column(
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.VIDEOCAM_OFF, size=48, color=MUTED),
                    ft.Text("kamera niepodłączona", color=MUTED, size=14),
                ],
            ),
        )
        # Wykrycia rysuje Flutter nad obrazem - klatka z kamery idzie do okna bez zmian.
        self.overlay_canvas = cv.Canvas(left=0, top=0, right=0, bottom=0,
                                        resize_interval=100, on_resize=self._on_overlay_resize)
        self._overlay_size = (0.0, 0.0)
        self._overlay_drawn: tuple | None = None     # (stan trackera, rozmiar) ostatnio narysowane
        self.preview_stack = ft.Stack(
            expand=True,
            controls=[
                self.preview_placeholder,
                self.preview,
                self.overlay_canvas,
                ft.Container(
                    right=14, top=12,
                    padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                    bgcolor="#000000aa", border_radius=8,
                    content=ft.Text("", color=TEXT, size=12, font_family="monospace"),
                ),
            ],
        )
        self.preview_badge = self.preview_stack.controls[2].content
        # Ta sama plansza, którą widzą uczestnicy - obiektyw i tak patrzy wtedy w podłogę.
        self._privacy_card = cv2.imencode(".jpg", render_card(*PRIVACY_TEXT))[1].tobytes()
        self._privacy_shown = False
        self._shown = (None, None)          # (tracker, błąd) ostatnio pokazane w oknie

        # --- połączenie ---
        self.device_dd = ft.Dropdown(
            label="urządzenie", value=s["device"], width=200, dense=True,
            options=[ft.DropdownOption(key=d, text=d) for d in (list_input_devices(CARD_LABEL) or [s["device"]])],
            on_select=self._on_device_change,
        )
        self.res_dd = ft.Dropdown(
            label="rozdzielczość", width=170, dense=True,
            value=f"{s['preview_width']}x{s['preview_height']}",
            options=[ft.DropdownOption(key=f"{w}x{h}", text=f"{w} × {h}") for w, h in RESOLUTIONS],
            on_select=self._on_resolution_change,
        )
        self.fps_dd = ft.Dropdown(
            label="podgląd (fps)", width=130, dense=True, value=str(s["preview_fps"]),
            options=[ft.DropdownOption(key=str(f), text=str(f)) for f in (5, 10, 15, 20, 30)],
            on_select=self._on_fps_change,
        )
        self.overlay_sw = ft.Switch(
            label="rysuj wykrycia", value=bool(s["overlay"]),
            on_change=lambda e: self._set_overlay(e.control.value),
        )
        self.connect_btn = ft.FilledButton("Połącz", icon=ft.Icons.CABLE, on_click=self._on_connect)
        self.connection_status = ft.Text("", size=12, color=MUTED)

        # --- wirtualna kamera ---
        self.vcam_status = ft.Text("", size=12, color=MUTED)
        self.privacy_sw = ft.Switch(label="prywatność (Super+Shift+C)", value=False,
                                    on_change=self._on_privacy_change)

        # --- PTZ ---
        self.pan_slider = self._axis_slider("pan", CID_PAN_ABSOLUTE)
        self.tilt_slider = self._axis_slider("tilt", CID_TILT_ABSOLUTE)
        self.step_dd = ft.Dropdown(
            label="krok przycisku", width=170, dense=True, value="5",
            options=[ft.DropdownOption(key=k, text=v) for k, v in
                     (("1", "1° (precyzyjnie)"), ("5", "5°"), ("15", "15°"), ("40", "40° (szybko)"))],
        )
        self.pad = ft.Column(
            spacing=6,
            controls=[
                ft.Row([self._ptz_button(ft.Icons.NORTH_WEST, -1, -1),
                        self._ptz_button(ft.Icons.NORTH, 0, -1),
                        self._ptz_button(ft.Icons.NORTH_EAST, 1, -1)],
                       alignment=ft.MainAxisAlignment.CENTER, spacing=6),
                ft.Row([self._ptz_button(ft.Icons.WEST, -1, 0),
                        ft.IconButton(ft.Icons.CENTER_FOCUS_STRONG, tooltip="wyśrodkuj (pan i tilt = 0)",
                                      icon_color=ACCENT, icon_size=26, on_click=self._on_center),
                        self._ptz_button(ft.Icons.EAST, 1, 0)],
                       alignment=ft.MainAxisAlignment.CENTER, spacing=6),
                ft.Row([self._ptz_button(ft.Icons.SOUTH_WEST, -1, 1),
                        self._ptz_button(ft.Icons.SOUTH, 0, 1),
                        self._ptz_button(ft.Icons.SOUTH_EAST, 1, 1)],
                       alignment=ft.MainAxisAlignment.CENTER, spacing=6),
            ],
        )

        # --- optyka ---
        self.zoom_slider = self._axis_slider("zoom", CID_ZOOM_ABSOLUTE, fmt=lambda v: f"{v}")
        self.zoom_in_btn = ft.FilledTonalButton("+ zoom", icon=ft.Icons.ZOOM_IN,
                                                on_click=lambda e: self._nudge(CID_ZOOM_ABSOLUTE, OPTICS_STEP_ZOOM))
        self.zoom_out_btn = ft.FilledTonalButton("− zoom", icon=ft.Icons.ZOOM_OUT,
                                                 on_click=lambda e: self._nudge(CID_ZOOM_ABSOLUTE, -OPTICS_STEP_ZOOM))
        self.focus_auto_sw = ft.Switch(label="autofocus", on_change=self._on_focus_auto)
        self.focus_slider = self._axis_slider("ostrość", CID_FOCUS_ABSOLUTE)
        self.focus_in_btn = ft.FilledTonalButton("ostrzej", icon=ft.Icons.ADD,
                                                 on_click=lambda e: self._nudge(CID_FOCUS_ABSOLUTE, OPTICS_STEP_FOCUS))
        self.focus_out_btn = ft.FilledTonalButton("miękcej", icon=ft.Icons.REMOVE,
                                                  on_click=lambda e: self._nudge(CID_FOCUS_ABSOLUTE, -OPTICS_STEP_FOCUS))
        self.gpu_text = ft.Text("", size=11, color=MUTED)

        # --- obraz ---
        # Zawartość tej karty powstaje dopiero po połączeniu z kamerą, bo
        # dopiero wtedy znamy listę kontrolek i ich zakresy.
        self.image_body = ft.Column(spacing=9, controls=[])
        self.image_switches: list[ft.Control] = []

        # --- tracking ---
        self.track_sw = ft.Switch(label="auto-tracking", value=False, on_change=self._on_tracking_toggle)
        self.profile_dd = ft.Dropdown(
            label="profil", width=170, dense=True, value=tr["profile"],
            # "prezentacja" z samą mechaniką nie jedzie płynnie za idącą osobą (odbiór
            # 2026-09-23) - czeka na cyfrowy kadr, więc jest oznaczona w interfejsie.
            options=[ft.DropdownOption(key=name, text=PROFILE_LABELS.get(name, name)) for name in PROFILES],
            on_select=self._on_profile_change,
        )
        self.auto_zoom_sw = ft.Switch(label="zoom automatyczny", value=bool(tr["auto_zoom"]),
                                      on_change=self._on_auto_zoom_change)
        self.gpu_sw = ft.Switch(label="użyj GPU (CUDA)", value=bool(tr["use_gpu"]), on_change=self._on_gpu_change)
        self.search_btn = ft.FilledTonalButton("szukaj osoby", icon=ft.Icons.TRAVEL_EXPLORE,
                                               on_click=self._on_search)
        self.home_btn = ft.OutlinedButton("ustaw dom", icon=ft.Icons.HOME, on_click=self._on_set_home)
        # Osoba do śledzenia: kliknięcie w podgląd (_on_preview_tap); przycisk wraca do trybu automatycznego.
        self.auto_pick_btn = ft.OutlinedButton("śledź automatycznie", icon=ft.Icons.PERSON_SEARCH,
                                               disabled=True, on_click=self._on_auto_pick)
        self.select_status = ft.Text("kliknij osobę w podglądzie, żeby śledzić tylko ją", size=12, color=MUTED)
        hold = float(tr["select_hold_s"])
        self.hold_text = ft.Text(f"{hold:.0f} s", size=11, color=MUTED, width=56)
        self.hold_slider = ft.Slider(min=2, max=20, value=hold, divisions=18, width=SLIDER_WIDTH,
                                     on_change_end=self._on_hold_change)
        self.invert_pan_sw = ft.Switch(label="odwróć pan", value=bool(tr["invert_pan"]),
                                       on_change=lambda e: self._set_tracking_flag("invert_pan", e.control.value))
        self.invert_tilt_sw = ft.Switch(label="odwróć tilt", value=bool(tr["invert_tilt"]),
                                        on_change=lambda e: self._set_tracking_flag("invert_tilt", e.control.value))
        self.record_sw = ft.Switch(label="zapisuj sesję", value=bool(tr["record"]),
                                   on_change=self._on_record_change)
        base = resolve(tr["profile"], tr["overrides"])
        self.advanced_sliders = [
            self._override_slider("strefa pan", "trigger_pan", base.trigger_pan, 0.05, 0.35, 0.01, "{:.2f}"),
            self._override_slider("strefa tilt", "trigger_tilt", base.trigger_tilt, 0.05, 0.35, 0.01, "{:.2f}"),
            self._override_slider("zwłoka", "dwell", base.dwell, 0.0, 3.0, 0.1, "{:.1f} s"),
            self._override_slider("czas kroku utraty", "ladder_step_time", base.ladder_step_time, 0.5, 10.0, 0.5, "{:.1f} s"),
            self._override_slider("próg odwrócenia twarzy", "side_enter", base.side_enter, 0.1, 0.9, 0.05, "{:.2f}"),
            self._override_slider("próg powrotu na wprost", "side_exit", base.side_exit, 0.05, 0.6, 0.05, "{:.2f}"),
            self._override_slider("zwłoka zmiany strony", "side_dwell", base.side_dwell, 0.0, 5.0, 0.1, "{:.1f} s"),
        ]
        self.shot_dd = ft.Dropdown(
            label="plan", width=170, dense=True, value=base.shot,
            options=[ft.DropdownOption(key=k, text=SHOT_LABELS[k]) for k in SHOTS],
            on_select=lambda e: self._set_override("shot", e.control.value),
        )
        self.advanced = ft.ExpansionTile(
            title=ft.Text("zaawansowane", size=12, color=MUTED),
            controls=[self.shot_dd, *self.advanced_sliders,
                      ft.Row([self.invert_pan_sw, self.invert_tilt_sw, self.record_sw],
                             spacing=6, wrap=True)],
        )
        self.track_status = ft.Text("", size=12, color=MUTED, selectable=True)
        self.track_detail = ft.Text("", size=11, color=MUTED, font_family="monospace", selectable=True)

        # --- presety ---
        self.preset_dd = ft.Dropdown(label="preset", width=190, dense=True, options=[],
                                     on_select=lambda e: None)
        self.preset_name = ft.TextField(label="nazwa nowego presetu", width=190, dense=True)
        self._refresh_preset_options()

        # --- stopka ---
        self.footer = ft.Text("", size=11, color=MUTED, font_family="monospace", selectable=True)
        self.notice = ft.Text("", size=12, color=WARN, selectable=True)

    def _axis_slider(self, label: str, ctrl_id: int, fmt=None) -> ft.Slider:
        ctrl = self.controls.control(ctrl_id) if self.controls else None
        lo = ctrl.minimum if ctrl else 0
        hi = ctrl.maximum if ctrl else 100
        step = ctrl.step if ctrl and ctrl.step else 1
        value = ctrl.default if ctrl else lo
        divisions = max(1, int((hi - lo) // step))
        slider = ft.Slider(
            min=lo, max=hi, value=value, divisions=min(divisions, 1000),
            label=f"{label}: {{value}}", width=SLIDER_WIDTH, round=0,
            on_change=lambda e: self._on_slider_change(ctrl_id, e.control.value),
            on_change_start=lambda e: self._dragging.add(ctrl_id),
            on_change_end=lambda e: self._dragging.discard(ctrl_id),
        )
        self.control_widgets[ctrl_id] = slider
        return slider

    def _override_slider(self, label: str, key: str, value: float, lo: float, hi: float,
                         step: float, fmt: str) -> ft.Control:
        text = ft.Text(fmt.format(value), size=11, color=MUTED, width=56)

        def changed(e) -> None:
            text.value = fmt.format(e.control.value)
            text.update()
            self._set_override(key, float(e.control.value))

        slider = ft.Slider(min=lo, max=hi, value=value, divisions=max(1, int(round((hi - lo) / step))),
                           width=SLIDER_WIDTH, on_change_end=changed)
        return ft.Row([ft.Text(label, size=12, color=MUTED, width=118), slider, text], spacing=6)

    def _bool_switch(self, label: str, handler) -> ft.Switch:
        return ft.Switch(label=label, value=False, on_change=handler)

    def _ptz_button(self, icon, dx: int, dy: int) -> ft.IconButton:
        return ft.IconButton(
            icon=icon, icon_size=26, icon_color=TEXT,
            bgcolor=PANEL_SOFT, tooltip="przesuń kamerę",
            on_click=lambda e: self._ptz_step(dx, dy),
        )

    def _card(self, title: str, icon, children: list[ft.Control], subtitle: str | None = None) -> ft.Container:
        header = [
            ft.Row([ft.Icon(icon, size=17, color=ACCENT),
                    ft.Text(title, size=14, weight=ft.FontWeight.W_600, color=TEXT)],
                   spacing=8),
        ]
        if subtitle:
            header.append(ft.Text(subtitle, size=11, color=MUTED))
        return ft.Container(
            bgcolor=PANEL, border=ft.Border.all(1, BORDER), border_radius=12,
            padding=ft.Padding.symmetric(horizontal=14, vertical=12),
            content=ft.Column(spacing=9, controls=header + children),
        )

    def _labeled(self, label: str, control: ft.Control) -> ft.Row:
        return ft.Row(
            [ft.Text(label, size=12, color=MUTED, width=118), control],
            spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _build_layout(self) -> None:
        left = ft.Column(
            expand=True, spacing=10,
            controls=[
                ft.GestureDetector(expand=True, mouse_cursor=ft.MouseCursor.CLICK,
                                   on_tap_down=self._on_preview_tap, content=self.preview_stack),
                self.footer,
                self.notice,
            ],
        )
        right = ft.Container(
            width=440,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO, expand=True, spacing=10,
                controls=[
                    self._card("Połączenie", ft.Icons.CABLE, [
                        ft.Row([self.device_dd, self.res_dd], spacing=8, wrap=True),
                        ft.Row([self.fps_dd, self.overlay_sw, self.connect_btn], spacing=10, wrap=True),
                        self.connection_status,
                        self.gpu_text,
                    ]),
                    self._card("Wirtualna kamera", ft.Icons.VIDEOCAM, [
                        self.privacy_sw, self.vcam_status,
                    ], subtitle="w Meet / Teams / OBS wybierz kamerę „EagleEye”"),
                    self._card("Ruch głowicy (PTZ)", ft.Icons.CONTROL_CAMERA, [
                        ft.Row([ft.Column([self._labeled("pan", self.pan_slider),
                                           self._labeled("tilt", self.tilt_slider)], spacing=4),
                                self.pad], spacing=10,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
                        self.step_dd,
                    ]),
                    self._card("Optyka", ft.Icons.CAMERA_OUTDOOR, [
                        self._labeled("zoom", self.zoom_slider),
                        ft.Row([self.zoom_out_btn, self.zoom_in_btn], spacing=8),
                        self.focus_auto_sw,
                        self._labeled("ostrość", self.focus_slider),
                        ft.Row([self.focus_out_btn, self.focus_in_btn], spacing=8),
                    ]),
                    self._card("Obraz", ft.Icons.TUNE, [
                        self.image_body,
                        ft.OutlinedButton("przywróć domyślne", icon=ft.Icons.RESTART_ALT,
                                          on_click=self._on_reset_image),
                    ]),
                    self._card("Auto-tracking", ft.Icons.PSYCHOLOGY, [
                        ft.Row([self.track_sw, self.profile_dd, self.auto_zoom_sw], spacing=10, wrap=True),
                        ft.Row([self.search_btn, self.home_btn, self.gpu_sw], spacing=8, wrap=True),
                        ft.Row([self.auto_pick_btn, self.select_status], spacing=10, wrap=True),
                        ft.Row([ft.Text("czekanie na wybraną", size=12, color=MUTED, width=118),
                                self.hold_slider, self.hold_text], spacing=6),
                        self.advanced,
                        ft.Divider(height=1, color=BORDER),
                        self.track_status, self.track_detail,
                    ]),
                    self._card("Presety", ft.Icons.BOOKMARK_ADDED, [
                        ft.Row([self.preset_dd,
                                ft.IconButton(ft.Icons.PLAY_ARROW, tooltip="wczytaj preset",
                                              icon_color=OK, on_click=self._on_preset_load),
                                ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="usuń preset",
                                              icon_color=ERROR, on_click=self._on_preset_delete)],
                               spacing=6),
                        ft.Row([self.preset_name, ft.FilledTonalButton("zapisz", icon=ft.Icons.SAVE,
                                                                       on_click=self._on_preset_save)], spacing=8),
                    ]),
                    self._card("Akcje", ft.Icons.BOLT, [
                        ft.Row([
                            ft.FilledTonalButton("zrzut klatki", icon=ft.Icons.PHOTO_CAMERA,
                                                 on_click=self._on_snapshot),
                            ft.FilledTonalButton("zapisz ustawienia", icon=ft.Icons.SAVE_AS,
                                                 on_click=lambda e: self._save_settings()),
                        ], spacing=8, wrap=True),
                    ]),
                ],
            ),
        )

        self.page.add(ft.Container(
            expand=True, bgcolor=BG, padding=16,
            content=ft.Row([left, right], spacing=14, expand=True,
                           vertical_alignment=ft.CrossAxisAlignment.STRETCH),
        ))

    def _image_controls(self) -> list[ft.Control]:
        """Suwaki i przełączniki obrazu budowane z kontrolek zgłoszonych przez kamerę."""
        order = [
            (CID_BRIGHTNESS, "jasność"), (CID_CONTRAST, "kontrast"),
            (CID_SATURATION, "nasycenie"), (CID_HUE, "odcień"),
            (CID_GAMMA, "gamma"), (CID_SHARPNESS, "ostrość obrazu"),
            (CID_WHITE_BALANCE_TEMP, "balans bieli (K)"),
        ]
        out: list[ft.Control] = []
        if not self.controls:
            return [ft.Text("brak połączenia - nie znam kontrolek kamery", size=12, color=MUTED)]
        for cid, label in order:
            if self.controls.control(cid) is None:
                continue
            out.append(self._labeled(label, self._axis_slider(label, cid)))
        for cid, label in ((CID_WHITE_BALANCE_AUTO, "balans bieli auto"),
                           (CID_BACKLIGHT_COMP, "kompensacja podświetlenia")):
            ctrl = self.controls.control(cid)
            if ctrl is None:
                continue
            try:
                value = bool(self.controls.get(cid))
            except V4L2Error:
                value = bool(ctrl.default)
            sw = ft.Switch(label=label, value=value,
                           on_change=lambda e, c=cid: self._write(c, 1 if e.control.value else 0))
            self.switch_widgets[cid] = sw
            out.append(sw)
        return out

    # ------------------------------------------------------------------
    # Obsługa sprzętu
    # ------------------------------------------------------------------

    def _show_connected(self) -> None:
        caps = self.engine.caps
        self.preview_placeholder.visible = False
        self.connection_status.value = (f"{caps['card']} • {caps['bus_info']} • "
                                        f"{self.stream.actual_width}×{self.stream.actual_height}")
        self.connection_status.color = OK
        gpu = gpu_status()
        self.gpu_text.value = (f"GPU: {gpu['device']} ({gpu['provider']})" if gpu["available"]
                               else f"GPU: niedostępne — {gpu.get('note') or 'brak CUDA'}")
        self._rebuild_image_controls()
        self._apply_control_ranges()
        self._sync_from_device()

    def _close_stream(self) -> None:
        self.engine.close_camera()

    def _apply_control_ranges(self) -> None:
        """Ustawia suwakom prawdziwe zakresy z kontrolek kamery.

        Interfejs powstaje przed połączeniem, więc suwaki startują z zakresami
        zastępczymi - tutaj dostają właściwe (np. pan to ±612000, nie 0..100).
        """
        if not self.controls:
            return
        for cid, widget in self.control_widgets.items():
            ctrl = self.controls.control(cid)
            if ctrl is None:
                continue
            widget.min = ctrl.minimum
            widget.max = ctrl.maximum
            step = ctrl.step or 1
            widget.divisions = max(1, min(1000, int((ctrl.maximum - ctrl.minimum) // step)))
            try:
                widget.value = max(ctrl.minimum, min(ctrl.maximum, self.controls.get(cid)))
            except V4L2Error:
                widget.value = ctrl.default
            log.info("kontrolka 0x%08x %-22s zakres %d..%d (krok %d), wartość %s",
                     cid, ctrl.name, ctrl.minimum, ctrl.maximum, step, widget.value)

    def _rebuild_image_controls(self) -> None:
        """Buduje sekcję obrazu z kontrolek faktycznie zgłoszonych przez kamerę."""
        self.control_widgets = {cid: w for cid, w in self.control_widgets.items()
                                if cid not in self._image_control_ids()}
        self.image_body.controls = self._image_controls()

    def _image_control_ids(self) -> set[int]:
        return {CID_BRIGHTNESS, CID_CONTRAST, CID_SATURATION, CID_HUE, CID_GAMMA,
                CID_SHARPNESS, CID_WHITE_BALANCE_TEMP, CID_WHITE_BALANCE_AUTO,
                CID_BACKLIGHT_COMP}

    def _sync_from_device(self) -> None:
        """Wczytuje bieżące wartości kontrolek i ustawia suwaki."""
        if not self.controls:
            return
        for cid, widget in self.control_widgets.items():
            if cid in self._dragging:
                continue
            try:
                value = self.controls.get(cid)
            except V4L2Error:
                continue
            # Ograniczamy do zakresu suwaka: Flet odrzuca wartość spoza
            # min/max, a suwak mógł jeszcze nie dostać prawdziwego zakresu.
            widget.value = max(widget.min, min(widget.max, value))
        for cid, widget in self.switch_widgets.items():
            try:
                widget.value = bool(self.controls.get(cid))
            except V4L2Error:
                continue
        try:
            self.focus_auto_sw.value = bool(self.controls.get(CID_FOCUS_AUTO))
        except V4L2Error:
            pass

    # ------------------------------------------------------------------
    # Zdarzenia interfejsu
    # ------------------------------------------------------------------

    def _control_label(self, ctrl_id: int) -> str:
        ctrl = self.controls.control(ctrl_id) if self.controls else None
        return ctrl.name if ctrl else f"0x{ctrl_id:08x}"

    def _friendly_error(self, exc: Exception) -> str:
        text = str(exc)
        if "Permission denied" in text:
            return f"{text} — kontrolka nieaktywna (tryb automatyczny lub tylko do odczytu)"
        return text

    def _auto_switch_widget(self, ctrl_id: int) -> ft.Switch | None:
        if ctrl_id == CID_FOCUS_AUTO:
            return self.focus_auto_sw
        return self.switch_widgets.get(ctrl_id)

    def _write(self, ctrl_id: int, value: int) -> None:
        if not self.controls:
            return
        # Kontrolki zależne od trybu automatycznego: zapis kończy się EPERM, gdy
        # auto jest włączone. Zamiast pokazywać błąd, wyłączamy automatyzm -
        # tak samo zachowuje się aparat, gdy przekręcisz pierścień ostrości.
        auto = AUTO_DEPENDENCIES.get(ctrl_id)
        if auto is not None:
            try:
                if self.controls.get(auto):
                    self.controls.set(auto, 0)
                    widget = self._auto_switch_widget(auto)
                    if widget is not None:
                        widget.value = False
                        try:
                            widget.update()
                        except Exception:
                            pass
                    self._notify(f"wyłączono tryb automatyczny, "
                                 f"żeby ustawić „{self._control_label(ctrl_id)}”", MUTED)
            except V4L2Error:
                pass  # brak kontrolki auto - i tak próbujemy zapisać
        try:
            self.controls.set(ctrl_id, int(value))
        except V4L2Error as exc:
            self._notify(self._friendly_error(exc), ERROR)

    def _on_slider_change(self, ctrl_id: int, value: float) -> None:
        # Pan/tilt idą przez tracker (wykonawcę), żeby model głowicy znał każdy ruch.
        if ctrl_id in (CID_PAN_ABSOLUTE, CID_TILT_ABSOLUTE) and self.tracker is not None:
            target = int(round(value))
            moved = self.tracker.move_to(pan=target if ctrl_id == CID_PAN_ABSOLUTE else None,
                                         tilt=target if ctrl_id == CID_TILT_ABSOLUTE else None)
            if not moved:
                self._notify("najpierw wyłącz auto-tracking, żeby sterować ręcznie", WARN)
            return
        self._write(ctrl_id, int(round(value)))

    def _nudge(self, ctrl_id: int, delta: int) -> None:
        if not self.controls:
            return
        try:
            current = self.controls.get(ctrl_id)
        except V4L2Error:
            return
        ctrl = self.controls.control(ctrl_id)
        target = int(current + delta)
        if ctrl is not None:
            target = max(ctrl.minimum, min(ctrl.maximum, target))
        self._write(ctrl_id, target)
        widget = self.control_widgets.get(ctrl_id)
        if widget is not None:
            widget.value = target
            widget.update()

    def _ptz_step(self, dx: int, dy: int) -> None:
        if self.tracker is None:
            return
        delta = float(self.step_dd.value or 5) * 3600
        # dy=+1 oznacza "w dół", a tilt dodatni patrzy w górę.
        if not self.tracker.nudge(dx * delta, -dy * delta):
            self._notify("najpierw wyłącz auto-tracking, żeby sterować ręcznie", WARN)

    def _on_center(self, _e=None) -> None:
        if self.tracker is not None and not self.tracker.move_to(pan=0, tilt=0):
            self._notify("wyłącz auto-tracking, żeby wyśrodkować ręcznie", WARN)

    def _on_focus_auto(self, e) -> None:
        self._write(CID_FOCUS_AUTO, 1 if e.control.value else 0)

    def _on_gpu_change(self, e) -> None:
        self.settings["tracking"]["use_gpu"] = bool(e.control.value)
        if self.tracker:
            self.tracker.set_use_gpu(bool(e.control.value))
        self._notify("detekcja: " + ("GPU (CUDA)" if e.control.value else "CPU"), OK)

    def _set_overlay(self, value: bool) -> None:
        self.overlay = bool(value)
        self.settings["overlay"] = self.overlay

    def _set_tracking_flag(self, key: str, value) -> None:
        self.settings["tracking"][key] = bool(value)
        self._notify("zmiana zadziała po ponownym połączeniu z kamerą", MUTED)

    def _on_record_change(self, e) -> None:
        on = bool(e.control.value)
        self.settings["tracking"]["record"] = on
        self._save_settings(silent=True)
        if self.tracker:
            self.tracker.set_record(on)
        self._notify("zapis sesji włączony (captures/sessions/)" if on else "zapis sesji wyłączony",
                     OK if on else MUTED)

    def _on_auto_zoom_change(self, e) -> None:
        on = bool(e.control.value)
        self.settings["tracking"]["auto_zoom"] = on
        self._save_settings(silent=True)
        if self.tracker:
            self.tracker.set_auto_zoom(on)
        self._notify("zoom automatyczny włączony" if on else "zoom automatyczny wyłączony",
                     OK if on else MUTED)

    def _set_override(self, key: str, value: float) -> None:
        if key not in TUNABLE:
            return
        tr = self.settings["tracking"]
        tr["overrides"][key] = value
        if self.tracker:
            self.tracker.set_profile(tr["profile"], tr["overrides"])

    def _on_profile_change(self, e) -> None:
        tr = self.settings["tracking"]
        tr["profile"] = e.control.value or "rozmowa"
        tr["overrides"] = {}
        self.shot_dd.value = resolve(tr["profile"], {}).shot    # nowy profil = jego plan
        if self.tracker:
            self.tracker.set_profile(tr["profile"], {})
        self._notify(f"profil: {tr['profile']} (nadpisania wyczyszczone)", OK)

    def _on_tracking_toggle(self, e) -> None:
        enabled = bool(e.control.value)
        try:
            self.engine.set_tracking(enabled)
        except RuntimeError as exc:
            self._notify(str(exc), WARN)
            e.control.value = False
            e.control.update()
            return
        # Pole pod podglądem to jednorazowy komunikat o zdarzeniu - bieżący stan
        # (szukanie/śledzenie) pokazuje na żywo prawy panel.
        self._notify("auto-tracking włączony" if enabled else "auto-tracking wyłączony",
                     OK if enabled else MUTED)

    def _on_search(self, _e) -> None:
        if self.tracker is None or not self.tracker.enabled:
            self._notify("włącz auto-tracking, żeby szukać osoby", WARN)
            return
        self.tracker.search_now()
        self._notify("szukanie osoby uruchomione", OK)

    def _on_preview_tap(self, e) -> None:
        """Kliknięcie w podgląd wybiera osobę pod kursorem (tracker liczy trafienie w swojej klatce)."""
        tracker = self.tracker
        if tracker is None or not tracker.enabled or e.local_position is None:
            return
        point = frame_point(*self._overlay_size, tracker.state.frame_size,
                            e.local_position.x, e.local_position.y)
        if point is not None and tracker.select_at(*point):
            self._notify("śledzę wskazaną osobę", OK)

    def _on_auto_pick(self, _e) -> None:
        if self.tracker is not None:
            self.tracker.clear_selection()
            self._notify("śledzę automatycznie (największa osoba)", MUTED)

    def _on_hold_change(self, e) -> None:
        value = float(e.control.value)
        self.hold_text.value = f"{value:.0f} s"
        self.hold_text.update()
        self.settings["tracking"]["select_hold_s"] = value
        self._save_settings(silent=True)
        if self.tracker:
            self.tracker.set_select_hold(value)

    def _on_set_home(self, _e) -> None:
        if self.tracker is None:
            return
        pan, tilt = self.tracker.set_home()
        self.settings["tracking"]["home"] = [pan, tilt]
        self._save_settings(silent=True)
        self._notify(f"dom: pan {pan / 3600:+.1f}°, tilt {tilt / 3600:+.1f}°", OK)

    def _on_device_change(self, e) -> None:
        self.settings["device"] = e.control.value or "/dev/video0"
        self._save_settings(silent=True)

    def _on_resolution_change(self, e) -> None:
        value = e.control.value or "1280x720"
        w, h = (int(x) for x in value.split("x"))
        self.settings["preview_width"], self.settings["preview_height"] = w, h
        self._save_settings(silent=True)
        if self.stream is not None:
            self._on_connect(None)

    def _on_fps_change(self, e) -> None:
        self.settings["preview_fps"] = int(e.control.value or 15)
        self._save_settings(silent=True)

    def _on_connect(self, _e) -> None:
        if self.engine.open_camera() is None:
            self._notify("kamera podłączona", OK)
        self._sync_connection()
        self._save_settings(silent=True)

    def _on_privacy_change(self, e) -> None:
        on = bool(e.control.value)
        self.engine.set_privacy(on)
        self._notify("prywatność włączona - uczestnicy widzą planszę" if on else "prywatność wyłączona",
                     WARN if on else OK)

    # --- presety ---

    def _refresh_preset_options(self) -> None:
        self.preset_dd.options = [ft.DropdownOption(key=p.name, text=p.name)
                                  for p in self.store.presets]

    def _on_preset_save(self, _e) -> None:
        name = (self.preset_name.value or "").strip()
        if not name:
            self._notify("podaj nazwę presetu", WARN)
            return
        if not self.controls:
            self._notify("brak połączenia z kamerą", ERROR)
            return
        preset = Preset(
            name=name,
            pan=self.controls.get(CID_PAN_ABSOLUTE), tilt=self.controls.get(CID_TILT_ABSOLUTE),
            zoom=self.controls.get(CID_ZOOM_ABSOLUTE), focus=self.controls.get(CID_FOCUS_ABSOLUTE),
            focus_auto=self.controls.get(CID_FOCUS_AUTO),
        )
        self.store.upsert_preset(preset)
        self._refresh_preset_options()
        self.preset_dd.value = name
        self.preset_name.value = ""
        self._notify(f"zapisano preset {name!r}", OK)
        self._refresh_widgets()

    def _on_preset_load(self, _e) -> None:
        name = self.preset_dd.value
        preset = self.store.preset(name) if name else None
        if preset is None:
            self._notify("wybierz preset do wczytania", WARN)
            return
        if self.tracker and self.tracker.enabled:
            self._notify("wyłącz auto-tracking przed wczytaniem presetu", WARN)
            return
        for cid, value in ((CID_ZOOM_ABSOLUTE, preset.zoom), (CID_FOCUS_ABSOLUTE, preset.focus),
                           (CID_FOCUS_AUTO, preset.focus_auto)):
            if self.controls and self.controls.control(cid):
                self._write(cid, value)
        if self.tracker:
            self.tracker.move_to(pan=preset.pan, tilt=preset.tilt)   # przez wykonawcę - model głowicy wie o ruchu
        self._sync_from_device()
        self._refresh_widgets()
        self._notify(f"wczytano preset {name!r}", OK)

    def _on_preset_delete(self, _e) -> None:
        name = self.preset_dd.value
        if not name:
            self._notify("wybierz preset do usunięcia", WARN)
            return
        if self.store.delete_preset(name):
            self._refresh_preset_options()
            self.preset_dd.value = None
            self._notify(f"usunięto preset {name!r}", OK)
            self._refresh_widgets()

    # --- akcje ---

    def _on_snapshot(self, _e) -> None:
        if self._last_jpg is None:
            self._notify("brak klatki do zapisania", WARN)
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            path = snapshots_dir() / f"zrzut-{stamp}.jpg"
            path.write_bytes(self._last_jpg)
        except OSError as exc:
            self._notify(f"nie udało się zapisać: {exc}", ERROR)
            return
        self._notify(f"zapisano {path}", OK)

    def _on_reset_image(self, _e) -> None:
        if not self.controls:
            return
        # Balans auto na końcu: zapis temperatury bieli wyłącza auto (AUTO_DEPENDENCIES).
        for cid in (CID_BRIGHTNESS, CID_CONTRAST, CID_SATURATION, CID_HUE, CID_GAMMA,
                    CID_SHARPNESS, CID_WHITE_BALANCE_TEMP, CID_BACKLIGHT_COMP,
                    CID_WHITE_BALANCE_AUTO):
            ctrl = self.controls.control(cid)
            if ctrl is not None:
                self._write(cid, ctrl.default)
        self._sync_from_device()
        self._refresh_widgets()
        self._notify("kontrolki obrazu wrócą do wartości domyślnych", OK)

    def _save_settings(self, silent: bool = False) -> None:
        try:
            self.store.save()
        except OSError as exc:
            self._notify(f"nie zapisano konfiguracji: {exc}", ERROR)
            return
        if not silent:
            self._notify("ustawienia zapisane w config.json", OK)

    def _notify(self, message: str, color: str = MUTED) -> None:
        self.notice.value = message
        self.notice.color = color
        if color == ERROR:
            log.error("%s", message)
        elif color == WARN:
            log.warning("%s", message)
        else:
            log.debug("%s", message)
        try:
            self.notice.update()
        except Exception:
            pass

    def _refresh_widgets(self) -> None:
        try:
            self.page.update()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Pętle: podgląd i status
    # ------------------------------------------------------------------

    def _sync_connection(self) -> None:
        """Pokazuje stan połączenia z silnika - także gdy silnik połączył się sam
        (kamera zwolniona przez inny program) albo zmienił komunikat błędu."""
        self._shown = (self.engine.tracker, self.engine.error)
        if self.engine.error or self.engine.tracker is None:
            self.connection_status.value = self.engine.error or "kamera niepodłączona"
            self.connection_status.color = ERROR
            self.preview_placeholder.visible = True
        else:
            self._show_connected()
        self._refresh_widgets()

    async def run(self) -> None:
        self._sync_connection()
        self.page.run_task(self._preview_loop)
        self.page.run_task(self._status_loop)

    # --- okno: pokaż / schowaj / zamknij (komendy z zewnątrz) -----------------

    def show_window(self) -> None:
        self.page.run_task(self._show)

    async def _show(self) -> None:
        self.hidden = False
        self.page.window.visible = True
        self.page.update()
        try:
            await self.page.window.to_front()
        except Exception:
            pass          # Wayland może odmówić wyciągnięcia okna na wierzch

    def hide_window(self) -> None:
        self.page.run_task(self._hide)

    async def _hide(self) -> None:
        self.hidden = True
        self.page.window.visible = False
        self.page.update()

    def quit_app(self) -> None:
        self.page.run_task(self._quit)

    async def _quit(self) -> None:
        self.closing = True
        await self.page.window.destroy()

    def on_window_event(self, e) -> None:
        if e.type == ft.WindowEventType.CLOSE:
            if self.tray.alive:
                self.hide_window()
                self._notify("EagleEye działa dalej w zasobniku", MUTED)
            else:
                self.quit_app()

    def _show_privacy_card(self) -> None:
        self._privacy_shown = True
        self.preview.src = self._privacy_card
        self.overlay_canvas.shapes = []
        self._overlay_drawn = None
        self.preview.visible = True
        self.preview_placeholder.visible = False
        self.preview_badge.value = "PRYWATNOŚĆ — uczestnicy widzą tę planszę"
        try:
            self.preview_stack.update()
        except Exception:
            pass

    async def _preview_loop(self) -> None:
        """Przekazuje klatki do kontrolki Image, z opcjonalnym rysowaniem wykryć."""
        while not self.closing:
            if self.hidden:                            # schowane okno: nie wysyłamy klatek do Fleta
                await asyncio.sleep(0.2)
                continue
            if self.engine.privacy.active:
                if not self._privacy_shown:
                    self._show_privacy_card()
                await asyncio.sleep(0.1)
                continue
            if self._privacy_shown:                    # koniec prywatności: plansza znika
                self._privacy_shown = False
                self.preview.visible = self.stream is not None
                self.preview_placeholder.visible = self.stream is None
                self.preview_badge.value = ""
                try:
                    self.preview_stack.update()
                except Exception:
                    pass
            if self.stream is None:
                await asyncio.sleep(0.2)
                continue
            target_fps = max(1, int(self.settings["preview_fps"]))
            interval = 1.0 / target_fps
            started = time.perf_counter()

            frame_id, jpg = await asyncio.to_thread(self.stream.frame, self._last_frame_id, 0.5)
            if jpg is None:
                await asyncio.sleep(0.1)
                continue
            if frame_id == self._last_frame_id:
                await asyncio.sleep(0.004)
                continue
            self._last_frame_id = frame_id
            self._last_jpg = jpg

            self.preview.src = jpg
            self.preview.visible = True
            self.preview_placeholder.visible = False

            now = time.perf_counter()
            dt = now - self._last_preview
            self._last_preview = now
            if dt > 0:
                inst = 1.0 / dt
                self._preview_fps_ema = inst if not self._preview_fps_ema else \
                    0.85 * self._preview_fps_ema + 0.15 * inst
            try:
                if self._sync_overlay():
                    self.preview_stack.update()         # obraz i nakładka w jednym komunikacie
                else:
                    self.preview.update()
                if now - self._last_badge >= PREVIEW_BADGE_PERIOD:
                    self._last_badge = now
                    self.preview_badge.value = (f"{self.stream.actual_width}×{self.stream.actual_height}"
                                                f"  {self._preview_fps_ema:4.1f} fps")
                    self.preview_badge.update()
            except Exception:
                pass

            rest = interval - (time.perf_counter() - started)
            if rest > 0:
                await asyncio.sleep(rest)

    def _on_overlay_resize(self, e) -> None:
        self._overlay_size = (e.width, e.height)

    def _sync_overlay(self) -> bool:
        """Ustawia kształty nakładki; ``True``, gdy się zmieniły i trzeba je wysłać."""
        state = self.tracker.state if self.tracker else None
        if not self.overlay or state is None or not state.enabled:
            state = None
        key = (state, self._overlay_size)
        if key == self._overlay_drawn or (state is None and not self.overlay_canvas.shapes):
            self._overlay_drawn = key
            return False
        self._overlay_drawn = key
        shapes = overlay_shapes(state, *self._overlay_size) if state is not None else []
        self.overlay_canvas.shapes = [c for s in shapes for c in self._canvas_shapes(s)]
        return True

    @staticmethod
    def _canvas_shapes(s: Shape) -> list:
        if s.kind == "dot":
            return [cv.Circle(s.x, s.y, s.r, paint=ft.Paint(color=s.color, style=ft.PaintingStyle.FILL))]
        if s.kind == "ring":
            return [cv.Circle(s.x, s.y, s.r, paint=ft.Paint(color=s.color, stroke_width=s.stroke,
                                                             style=ft.PaintingStyle.STROKE))]
        if s.kind == "line":
            return [cv.Line(s.x, s.y, s.x2, s.y2, paint=ft.Paint(color=s.color, stroke_width=s.stroke))]
        out = [cv.Rect(s.x, s.y, s.w, s.h, paint=ft.Paint(color=s.color, stroke_width=s.stroke,
                                                           style=ft.PaintingStyle.STROKE))]
        if s.label:
            out.append(cv.Text(s.x, max(0.0, s.y - 18), s.label,
                               style=ft.TextStyle(size=12, color=s.color)))
        return out

    async def _status_loop(self) -> None:
        """Odświeża odczyty z kamery i statystyki trackera kilka razy na sekundę."""
        while not self.closing:
            await asyncio.sleep(0.25)
            try:
                # Stan wirtualnej kamery i prywatność aktualizujemy też bez kamery -
                # plansza i przełącznik muszą działać, gdy urządzenia nie ma.
                self.vcam_status.value = f"stan: {self.engine.vcam.status}"
                self.privacy_sw.value = self.engine.privacy.active
                if (self.engine.tracker, self.engine.error) != self._shown:
                    self._sync_connection()
                    if self.engine.tracker is not None:
                        self._notify("kamera podłączona", OK)
                if self.controls is None:
                    self.page.update()
                    continue
                self._sync_from_device()
                state = self.tracker.state if self.tracker else None
                parts = [f"kontrolki: {len(self.controls.list_controls())}"]
                if self.stream:
                    parts.append(f"klatek: {self.stream.dropped} odrzuconych")
                self.footer.value = "  •  ".join(parts)
                if state is not None:
                    target = (f"{state.target.source} {state.target.score:.2f} "
                              f"@ {int(state.target.x)},{int(state.target.y)}" if state.target else "brak")
                    self.track_detail.value = (
                        f"tryb     : {state.mode}   pan: {state.pan_state}   tilt: {state.tilt_state}\n"
                        f"cel      : {target}\n"
                        f"kadr     : {state.side or '-'}  plan {state.shot or '-'}  "
                        f"yaw {'-' if state.yaw is None else f'{state.yaw:+.2f}'}  "
                        f"zoom→ {'-' if state.zoom_goal is None else int(state.zoom_goal)}  "
                        f"({'auto' if state.auto_zoom else 'ręczny'})\n"
                        f"głowica  : pan {state.pan / 3600:+6.1f}°  tilt {state.tilt / 3600:+6.1f}°\n"
                        f"detekcja : {state.detection_ms:5.1f} ms   pętla: {state.loop_ms:5.1f} ms\n"
                        f"tempo    : {state.fps:4.1f} Hz   ruchów: {state.moves}\n"
                        f"detektor : {state.detector}"
                    )
                    self.track_status.value = state.message
                    self.select_status.value = (selection_text(state)
                                                or "kliknij osobę w podglądzie, żeby śledzić tylko ją")
                    self.auto_pick_btn.disabled = state.selection == "auto"
                    if self.track_sw.value != state.enabled:
                        self.track_sw.value = state.enabled      # tracker mógł się sam wyłączyć (błąd, odłączenie)
                    if state.enabled and self.auto_zoom_sw.value and not state.auto_zoom:
                        # Tracker wyłączył automat, bo zoom zmieniono ręcznie - utrwalamy i mówimy.
                        self.auto_zoom_sw.value = False
                        self.settings["tracking"]["auto_zoom"] = False
                        self._save_settings(silent=True)
                        self._notify("zoom zmieniony ręcznie - zoom automatyczny wyłączony", WARN)
                    azimuth = self.tracker.last_azimuth
                    stored = self.settings["tracking"]["last_azimuth"]
                    if azimuth and (not stored or abs(azimuth[0] - stored[0]) > 3600):
                        self.settings["tracking"]["last_azimuth"] = [azimuth[0], azimuth[1]]
                        self._save_settings(silent=True)
                self.page.update()
            except Exception as exc:
                self._notify(f"błąd pętli statusu: {exc}", ERROR)


def main(page: ft.Page, engine: Engine, tray: TrayProcess) -> None:
    page.title = "EagleEye — sterowanie kamerą"
    page.theme_mode = ft.ThemeMode.DARK
    try:
        page.window.width = 1420
        page.window.height = 900
        page.window.min_width = 1100
        page.window.min_height = 700
    except Exception:
        pass  # w trybie webowym okno nie istnieje
    app = CameraApp(page, engine, tray)
    engine.ui = UiHooks(show=app.show_window, hide=app.hide_window, quit=app.quit_app)
    try:
        page.window.prevent_close = True
        page.window.on_event = app.on_window_event
    except Exception:
        pass  # w trybie webowym okno nie istnieje
    page.run_task(app.run)


def _parse_args(argv: list[str]):
    import argparse

    parser = argparse.ArgumentParser(
        description="Sterowanie kamerą Polycom EagleEye IV USB",
        epilog="Domyślnie otwiera okno natywne. Uruchamiane też przez 'flet run app.py'.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--web", action="store_true",
                      help="serwuj jako aplikację webową pod podanym adresem (bez otwierania okna)")
    mode.add_argument("--browser", action="store_true",
                      help="uruchom jako aplikację webową i otwórz przeglądarkę")
    mode.add_argument("--hidden", action="store_true", help="okno natywne, ale ukryte")
    parser.add_argument("--host", default="127.0.0.1", help="adres nasłuchu w trybie webowym")
    parser.add_argument("--port", type=int, default=8550, help="port w trybie webowym")
    return parser.parse_known_args(argv)[0]


def run_app(argv: list[str] | None = None) -> None:
    """Uruchamia aplikację: silnik, gniazdo sterujące, ikonę w zasobniku, okno."""
    logging.basicConfig(
        level=logging.INFO, stream=sys.stdout,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # OpenCV 5 nie ma już cv2.setLogLevel - jest cv2.utils.logging.
    # Uwaga: komunikatów libjpeg ("Corrupt JPEG data: N extraneous bytes
    # before marker 0xd9") nie da się tym wyciszyć, bo libjpeg pisze wprost
    # na stderr. Kamera dokłada kilka bajtów dopełnienia przed znacznikiem EOI,
    # obraz dekoduje się poprawnie - to wyłącznie szum w terminalu.
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except AttributeError:
        pass
    # Pula OpenCV ma domyślnie wątek na rdzeń; przy operacjach na jednej klatce
    # wątki głównie czekają aktywnie. Zmierzone na konwersji 1080p dla vcam:
    # 12 wątków 67 ms CPU/klatkę, 2 wątki 26 ms - przy prawie tym samym czasie.
    cv2.setNumThreads(2)
    args = _parse_args(list(argv if argv is not None else sys.argv[1:]))
    engine = Engine(Store())
    server = ControlServer(engine.command)
    tray = TrayProcess()
    try:
        server.start()      # najpierw gniazdo: drugie uruchomienie w trakcie startu tylko pokaże okno
    except InstanceRunning:
        send("pokaz", None, server.path)
        return
    engine.start()
    tray.start()
    signal.signal(signal.SIGTERM, lambda *_: engine.ui.quit())
    if args.web:
        view, host, port = ft.AppView.FLET_APP_WEB, args.host, args.port
    elif args.browser:
        view, host, port = ft.AppView.WEB_BROWSER, args.host, args.port
    elif args.hidden:
        view, host, port = ft.AppView.FLET_APP_HIDDEN, None, 0
    else:
        view, host, port = ft.AppView.FLET_APP, None, 0
    try:
        ft.run(lambda page: main(page, engine, tray), view=view, host=host, port=port)
    except KeyboardInterrupt:
        pass
    finally:
        tray.stop()
        server.stop()
        engine.shutdown()


if __name__ == "__main__":
    sys.exit(__import__("eagleeye.cli").cli.main())
