#!/usr/bin/env python3
"""Control the Polycom EagleEye IV USB camera.

Desktop application (Flet/Flutter) for the camera exposed through V4L2.
Running::

    .venv/bin/flet run app.py          # native window
    .venv/bin/flet run --web app.py    # in the browser

Layers: ``eagleeye.v4l2`` (hardware), ``eagleeye.detectors`` (detection),
``eagleeye.tracker`` (tracking), ``eagleeye.config`` (settings).
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
from eagleeye.i18n import available_languages, msg, render, t
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
from eagleeye.vcam import CARD_LABEL, PRIVACY_CARD, card_texts, render_card

# Palette - a dark theme chosen for long work in front of the camera.
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
OPTICS_STEP_ZOOM = 600      # zoom step of the buttons (~1.3x)
OPTICS_STEP_FOCUS = 150
PREVIEW_BADGE_PERIOD = 1.0  # s - an fps caption every frame is a second Flet message per frame

log = logging.getLogger("eagleeye")

# Controls that are inactive while automatic mode is on: ``uvcvideo``
# then returns EPERM ("Permission denied") on every write attempt. Without this
# handling the focus slider looks like it works while doing nothing.
AUTO_DEPENDENCIES = {
    CID_FOCUS_ABSOLUTE: CID_FOCUS_AUTO,
    CID_WHITE_BALANCE_TEMP: CID_WHITE_BALANCE_AUTO,
}


def ensure_manual_mode(controls: ControlDevice, ctrl_id: int) -> bool:
    """Turns automatic mode off if the control depends on it.

    ``uvcvideo`` returns EPERM when writing an inactive control, so to set
    manual focus one must first turn autofocus off. Returns ``True``
    when automatic mode was actually turned off.
    """
    auto = AUTO_DEPENDENCIES.get(ctrl_id)
    if auto is None:
        return False
    try:
        if controls.get(auto):
            controls.set(auto, 0)
            return True
    except V4L2Error:
        pass  # no auto control - we try to write anyway
    return False


def _diag_text(state) -> str:
    """The monospace diagnostics block of the tracking card, in the active language."""
    def code(prefix: str, value: str) -> str:
        return t(f"{prefix}.{value}") if value else "-"
    target = (f"{state.target.source} {state.target.score:.2f} @ {int(state.target.x)},{int(state.target.y)}"
              if state.target else t("app.target_none"))
    return t("app.diag",
             mode=code("director.mode", state.mode),
             pan_state=code("director.axis", state.pan_state),
             tilt_state=code("director.axis", state.tilt_state),
             target=target,
             side=code("framing.side", state.side),
             shot=state.shot or "-",
             yaw="-" if state.yaw is None else f"{state.yaw:+.2f}",
             zoom_goal="-" if state.zoom_goal is None else int(state.zoom_goal),
             zoom_mode=t("app.zoom_auto") if state.auto_zoom else t("app.zoom_manual"),
             pan=state.pan / 3600, tilt=state.tilt / 3600,
             detection_ms=state.detection_ms, loop_ms=state.loop_ms, fps=state.fps,
             moves=state.moves, detector=state.detector)


class CameraApp:
    """The whole application state in one place - interface and hardware."""

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

        # Flet 1.0 requires a non-empty `src` - we start with a transparent 1x1
        # pixel, which the first camera frame will replace shortly.
        transparent_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/wIAAgMBAp0YVwAAAABJRU5ErkJggg=="
        )
        self.preview = ft.Image(
            src=transparent_png, fit=ft.BoxFit.CONTAIN, gapless_playback=True,
            border_radius=10,
            # The image sits at the top edge, horizontally centered - the overlay
            # (overlay_shapes) computes the position the same way, otherwise the points drift apart.
            align=ft.Alignment.TOP_CENTER,
        )
        self.preview_placeholder = ft.Container(
            expand=True, bgcolor="#0b0e13", border_radius=10,
            content=ft.Column(
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.VIDEOCAM_OFF, size=48, color=MUTED),
                    ft.Text(t("app.camera_disconnected"), color=MUTED, size=14),
                ],
            ),
        )
        # Flutter draws the detections over the image - the camera frame reaches the window unchanged.
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
        # The same slate the participants see - the lens is pointing at the floor then anyway.
        self._privacy_card = cv2.imencode(".jpg", render_card(*card_texts(PRIVACY_CARD)))[1].tobytes()
        self._privacy_shown = False
        self._shown = (None, None)          # (tracker, error) last shown in the window

        # --- connection ---
        self.device_dd = ft.Dropdown(
            label=t("app.device"), value=s["device"], width=200, dense=True,
            options=[ft.DropdownOption(key=d, text=d) for d in (list_input_devices(CARD_LABEL) or [s["device"]])],
            on_select=self._on_device_change,
        )
        self.res_dd = ft.Dropdown(
            label=t("app.resolution"), width=170, dense=True,
            value=f"{s['preview_width']}x{s['preview_height']}",
            options=[ft.DropdownOption(key=f"{w}x{h}", text=f"{w} × {h}") for w, h in RESOLUTIONS],
            on_select=self._on_resolution_change,
        )
        # The selector sits next to the device choice; rebuilding the window never touches
        # the engine, so tracking and the virtual camera keep running.
        self.language_dd = ft.Dropdown(
            label=t("app.language"), width=170, dense=True, value=self.settings["language"],
            options=[ft.DropdownOption(key="auto", text=t("app.language_auto"))]
                    + [ft.DropdownOption(key=code, text=name)
                       for code, name in available_languages().items()],
            on_select=self._on_language_change,
        )
        self.fps_dd = ft.Dropdown(
            label=t("app.preview_fps"), width=130, dense=True, value=str(s["preview_fps"]),
            options=[ft.DropdownOption(key=str(f), text=str(f)) for f in (5, 10, 15, 20, 30)],
            on_select=self._on_fps_change,
        )
        self.overlay_sw = ft.Switch(
            label=t("app.draw_detections"), value=bool(s["overlay"]),
            on_change=lambda e: self._set_overlay(e.control.value),
        )
        self.connect_btn = ft.FilledButton(t("app.connect"), icon=ft.Icons.CABLE, on_click=self._on_connect)
        self.connection_status = ft.Text("", size=12, color=MUTED)

        # --- virtual camera ---
        self.vcam_status = ft.Text("", size=12, color=MUTED)
        self.privacy_sw = ft.Switch(label=t("app.privacy_switch"), value=False,
                                    on_change=self._on_privacy_change)

        # --- PTZ ---
        self.pan_slider = self._axis_slider(t("app.pan"), CID_PAN_ABSOLUTE)
        self.tilt_slider = self._axis_slider(t("app.tilt"), CID_TILT_ABSOLUTE)
        self.step_dd = ft.Dropdown(
            label=t("app.step_label"), width=170, dense=True, value="5",
            options=[ft.DropdownOption(key=k, text=v) for k, v in
                     (("1", t("app.step_fine")), ("5", "5°"), ("15", "15°"), ("40", t("app.step_fast")))],
        )
        self.pad = ft.Column(
            spacing=6,
            controls=[
                ft.Row([self._ptz_button(ft.Icons.NORTH_WEST, -1, -1),
                        self._ptz_button(ft.Icons.NORTH, 0, -1),
                        self._ptz_button(ft.Icons.NORTH_EAST, 1, -1)],
                       alignment=ft.MainAxisAlignment.CENTER, spacing=6),
                ft.Row([self._ptz_button(ft.Icons.WEST, -1, 0),
                        ft.IconButton(ft.Icons.CENTER_FOCUS_STRONG, tooltip=t("app.center_tooltip"),
                                      icon_color=ACCENT, icon_size=26, on_click=self._on_center),
                        self._ptz_button(ft.Icons.EAST, 1, 0)],
                       alignment=ft.MainAxisAlignment.CENTER, spacing=6),
                ft.Row([self._ptz_button(ft.Icons.SOUTH_WEST, -1, 1),
                        self._ptz_button(ft.Icons.SOUTH, 0, 1),
                        self._ptz_button(ft.Icons.SOUTH_EAST, 1, 1)],
                       alignment=ft.MainAxisAlignment.CENTER, spacing=6),
            ],
        )

        # --- optics ---
        self.zoom_slider = self._axis_slider(t("app.zoom"), CID_ZOOM_ABSOLUTE, fmt=lambda v: f"{v}")
        self.zoom_in_btn = ft.FilledTonalButton(t("app.zoom_plus"), icon=ft.Icons.ZOOM_IN,
                                                on_click=lambda e: self._nudge(CID_ZOOM_ABSOLUTE, OPTICS_STEP_ZOOM))
        self.zoom_out_btn = ft.FilledTonalButton(t("app.zoom_minus"), icon=ft.Icons.ZOOM_OUT,
                                                 on_click=lambda e: self._nudge(CID_ZOOM_ABSOLUTE, -OPTICS_STEP_ZOOM))
        self.focus_auto_sw = ft.Switch(label=t("app.autofocus"), on_change=self._on_focus_auto)
        self.focus_slider = self._axis_slider(t("app.focus"), CID_FOCUS_ABSOLUTE)
        self.focus_in_btn = ft.FilledTonalButton(t("app.focus_sharper"), icon=ft.Icons.ADD,
                                                 on_click=lambda e: self._nudge(CID_FOCUS_ABSOLUTE, OPTICS_STEP_FOCUS))
        self.focus_out_btn = ft.FilledTonalButton(t("app.focus_softer"), icon=ft.Icons.REMOVE,
                                                  on_click=lambda e: self._nudge(CID_FOCUS_ABSOLUTE, -OPTICS_STEP_FOCUS))
        self.gpu_text = ft.Text("", size=11, color=MUTED)

        # --- image ---
        # The content of this card is built only after connecting to the camera, because
        # only then do we know the list of controls and their ranges.
        self.image_body = ft.Column(spacing=9, controls=[])
        self.image_switches: list[ft.Control] = []

        # --- tracking ---
        self.track_sw = ft.Switch(label=t("app.tracking_switch"), value=False, on_change=self._on_tracking_toggle)
        self.profile_dd = ft.Dropdown(
            label=t("app.profile"), width=170, dense=True, value=tr["profile"],
            # "presentation" with pure mechanics does not follow a walking person smoothly (acceptance
            # 2026-09-23) - it waits for a digital frame, so it is marked in the interface.
            options=[ft.DropdownOption(key=name, text=t(f"profile.{name}")) for name in PROFILES],
            on_select=self._on_profile_change,
        )
        self.auto_zoom_sw = ft.Switch(label=t("app.auto_zoom"), value=bool(tr["auto_zoom"]),
                                      on_change=self._on_auto_zoom_change)
        self.gpu_sw = ft.Switch(label=t("app.use_gpu"), value=bool(tr["use_gpu"]), on_change=self._on_gpu_change)
        self.search_btn = ft.FilledTonalButton(t("app.search_person"), icon=ft.Icons.TRAVEL_EXPLORE,
                                               on_click=self._on_search)
        self.home_btn = ft.OutlinedButton(t("app.set_home"), icon=ft.Icons.HOME, on_click=self._on_set_home)
        # Person to track: a click on the preview (_on_preview_tap); the button returns to automatic mode.
        self.auto_pick_btn = ft.OutlinedButton(t("app.track_auto"), icon=ft.Icons.PERSON_SEARCH,
                                               disabled=True, on_click=self._on_auto_pick)
        self.select_status = ft.Text(t("app.select_hint"), size=12, color=MUTED)
        hold = float(tr["select_hold_s"])
        self.hold_text = ft.Text(f"{hold:.0f} s", size=11, color=MUTED, width=56)
        self.hold_slider = ft.Slider(min=2, max=20, value=hold, divisions=18, width=SLIDER_WIDTH,
                                     on_change_end=self._on_hold_change)
        self.invert_pan_sw = ft.Switch(label=t("app.invert_pan"), value=bool(tr["invert_pan"]),
                                       on_change=lambda e: self._set_tracking_flag("invert_pan", e.control.value))
        self.invert_tilt_sw = ft.Switch(label=t("app.invert_tilt"), value=bool(tr["invert_tilt"]),
                                        on_change=lambda e: self._set_tracking_flag("invert_tilt", e.control.value))
        self.record_sw = ft.Switch(label=t("app.record_session"), value=bool(tr["record"]),
                                   on_change=self._on_record_change)
        base = resolve(tr["profile"], tr["overrides"])
        self.advanced_sliders = [
            self._override_slider(t("app.zone_pan"), "trigger_pan", base.trigger_pan, 0.05, 0.35, 0.01, "{:.2f}"),
            self._override_slider(t("app.zone_tilt"), "trigger_tilt", base.trigger_tilt, 0.05, 0.35, 0.01, "{:.2f}"),
            self._override_slider(t("app.dwell"), "dwell", base.dwell, 0.0, 3.0, 0.1, "{:.1f} s"),
            self._override_slider(t("app.ladder_step"), "ladder_step_time", base.ladder_step_time, 0.5, 10.0, 0.5, "{:.1f} s"),
            self._override_slider(t("app.turn_threshold"), "side_enter", base.side_enter, 0.1, 0.9, 0.05, "{:.2f}"),
            self._override_slider(t("app.return_threshold"), "side_exit", base.side_exit, 0.05, 0.6, 0.05, "{:.2f}"),
            self._override_slider(t("app.side_dwell"), "side_dwell", base.side_dwell, 0.0, 5.0, 0.1, "{:.1f} s"),
        ]
        self.shot_dd = ft.Dropdown(
            label=t("app.shot"), width=170, dense=True, value=base.shot,
            options=[ft.DropdownOption(key=k, text=t(f"shot.{k}")) for k in SHOTS],
            on_select=lambda e: self._set_override("shot", e.control.value),
        )
        self.advanced = ft.ExpansionTile(
            title=ft.Text(t("app.advanced"), size=12, color=MUTED),
            controls=[self.shot_dd, *self.advanced_sliders,
                      ft.Row([self.invert_pan_sw, self.invert_tilt_sw, self.record_sw],
                             spacing=6, wrap=True)],
        )
        self.track_status = ft.Text("", size=12, color=MUTED, selectable=True)
        self.track_detail = ft.Text("", size=11, color=MUTED, font_family="monospace", selectable=True)

        # --- presets ---
        self.preset_dd = ft.Dropdown(label=t("app.preset"), width=190, dense=True, options=[],
                                     on_select=lambda e: None)
        self.preset_name = ft.TextField(label=t("app.preset_name"), width=190, dense=True)
        self._refresh_preset_options()

        # --- footer ---
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
            bgcolor=PANEL_SOFT, tooltip=t("app.move_camera"),
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
                    self._card(t("app.card_connection"), ft.Icons.CABLE, [
                        ft.Row([self.device_dd, self.res_dd, self.language_dd], spacing=8, wrap=True),
                        ft.Row([self.fps_dd, self.overlay_sw, self.connect_btn], spacing=10, wrap=True),
                        self.connection_status,
                        self.gpu_text,
                    ]),
                    self._card(t("app.card_virtual_camera"), ft.Icons.VIDEOCAM, [
                        self.privacy_sw, self.vcam_status,
                    ], subtitle=t("app.virtual_camera_hint")),
                    self._card(t("app.card_ptz"), ft.Icons.CONTROL_CAMERA, [
                        ft.Row([ft.Column([self._labeled(t("app.pan"), self.pan_slider),
                                           self._labeled(t("app.tilt"), self.tilt_slider)], spacing=4),
                                self.pad], spacing=10,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
                        self.step_dd,
                    ]),
                    self._card(t("app.card_optics"), ft.Icons.CAMERA_OUTDOOR, [
                        self._labeled(t("app.zoom"), self.zoom_slider),
                        ft.Row([self.zoom_out_btn, self.zoom_in_btn], spacing=8),
                        self.focus_auto_sw,
                        self._labeled(t("app.focus"), self.focus_slider),
                        ft.Row([self.focus_out_btn, self.focus_in_btn], spacing=8),
                    ]),
                    self._card(t("app.card_image"), ft.Icons.TUNE, [
                        self.image_body,
                        ft.OutlinedButton(t("app.image_reset"), icon=ft.Icons.RESTART_ALT,
                                          on_click=self._on_reset_image),
                    ]),
                    self._card(t("app.card_tracking"), ft.Icons.PSYCHOLOGY, [
                        ft.Row([self.track_sw, self.profile_dd, self.auto_zoom_sw], spacing=10, wrap=True),
                        ft.Row([self.search_btn, self.home_btn, self.gpu_sw], spacing=8, wrap=True),
                        ft.Row([self.auto_pick_btn, self.select_status], spacing=10, wrap=True),
                        ft.Row([ft.Text(t("app.select_hold"), size=12, color=MUTED, width=118),
                                self.hold_slider, self.hold_text], spacing=6),
                        self.advanced,
                        ft.Divider(height=1, color=BORDER),
                        self.track_status, self.track_detail,
                    ]),
                    self._card(t("app.card_presets"), ft.Icons.BOOKMARK_ADDED, [
                        ft.Row([self.preset_dd,
                                ft.IconButton(ft.Icons.PLAY_ARROW, tooltip=t("app.preset_load"),
                                              icon_color=OK, on_click=self._on_preset_load),
                                ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip=t("app.preset_delete"),
                                              icon_color=ERROR, on_click=self._on_preset_delete)],
                               spacing=6),
                        ft.Row([self.preset_name, ft.FilledTonalButton(t("app.preset_save"), icon=ft.Icons.SAVE,
                                                                       on_click=self._on_preset_save)], spacing=8),
                    ]),
                    self._card(t("app.card_actions"), ft.Icons.BOLT, [
                        ft.Row([
                            ft.FilledTonalButton(t("app.snapshot"), icon=ft.Icons.PHOTO_CAMERA,
                                                 on_click=self._on_snapshot),
                            ft.FilledTonalButton(t("app.save_settings"), icon=ft.Icons.SAVE_AS,
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
        """Image sliders and switches built from the controls reported by the camera."""
        order = [
            (CID_BRIGHTNESS, t("app.image_brightness")), (CID_CONTRAST, t("app.image_contrast")),
            (CID_SATURATION, t("app.image_saturation")), (CID_HUE, t("app.image_hue")),
            (CID_GAMMA, t("app.image_gamma")), (CID_SHARPNESS, t("app.image_sharpness")),
            (CID_WHITE_BALANCE_TEMP, t("app.image_white_balance")),
        ]
        out: list[ft.Control] = []
        if not self.controls:
            return [ft.Text(t("app.no_controls"), size=12, color=MUTED)]
        for cid, label in order:
            if self.controls.control(cid) is None:
                continue
            out.append(self._labeled(label, self._axis_slider(label, cid)))
        for cid, label in ((CID_WHITE_BALANCE_AUTO, t("app.wb_auto")),
                           (CID_BACKLIGHT_COMP, t("app.backlight"))):
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
    # Hardware handling
    # ------------------------------------------------------------------

    def _show_connected(self) -> None:
        caps = self.engine.caps
        self.preview_placeholder.visible = False
        self.connection_status.value = (f"{caps['card']} • {caps['bus_info']} • "
                                        f"{self.stream.actual_width}×{self.stream.actual_height}")
        self.connection_status.color = OK
        gpu = gpu_status()
        self.gpu_text.value = (t("app.gpu_available", device=gpu["device"], provider=gpu["provider"])
                               if gpu["available"]
                               else t("app.gpu_unavailable", note=gpu.get("note") or t("app.gpu_no_cuda")))
        self._rebuild_image_controls()
        self._apply_control_ranges()
        self._sync_from_device()

    def _close_stream(self) -> None:
        self.engine.close_camera()

    def _apply_control_ranges(self) -> None:
        """Gives the sliders their real ranges from the camera controls.

        The interface is built before connecting, so the sliders start with placeholder
        ranges - here they get the proper ones (e.g. pan is ±612000, not 0..100).
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
            log.info("control 0x%08x %-22s range %d..%d (step %d), value %s",
                     cid, ctrl.name, ctrl.minimum, ctrl.maximum, step, widget.value)

    def _rebuild_image_controls(self) -> None:
        """Builds the image section from the controls actually reported by the camera."""
        self.control_widgets = {cid: w for cid, w in self.control_widgets.items()
                                if cid not in self._image_control_ids()}
        self.image_body.controls = self._image_controls()

    def _image_control_ids(self) -> set[int]:
        return {CID_BRIGHTNESS, CID_CONTRAST, CID_SATURATION, CID_HUE, CID_GAMMA,
                CID_SHARPNESS, CID_WHITE_BALANCE_TEMP, CID_WHITE_BALANCE_AUTO,
                CID_BACKLIGHT_COMP}

    def _sync_from_device(self) -> None:
        """Reads the current control values and sets the sliders."""
        if not self.controls:
            return
        for cid, widget in self.control_widgets.items():
            if cid in self._dragging:
                continue
            try:
                value = self.controls.get(cid)
            except V4L2Error:
                continue
            # Limit to the slider's range: Flet rejects a value outside
            # min/max, and the slider may not have received its real range yet.
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
    # Interface events
    # ------------------------------------------------------------------

    def _control_label(self, ctrl_id: int) -> str:
        ctrl = self.controls.control(ctrl_id) if self.controls else None
        return ctrl.name if ctrl else f"0x{ctrl_id:08x}"

    def _friendly_error(self, exc: Exception) -> str:
        text = str(exc)
        if "Permission denied" in text:
            return t("app.error_control_inactive", error=text)
        return text

    def _auto_switch_widget(self, ctrl_id: int) -> ft.Switch | None:
        if ctrl_id == CID_FOCUS_AUTO:
            return self.focus_auto_sw
        return self.switch_widgets.get(ctrl_id)

    def _write(self, ctrl_id: int, value: int) -> None:
        if not self.controls:
            return
        # Controls that depend on automatic mode: writing ends in EPERM when
        # auto is on. Instead of showing an error, we turn the automation off -
        # exactly as a camera behaves when you turn the focus ring.
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
                    self._notify(t("app.notice_auto_mode_off",
                                   control=self._control_label(ctrl_id)), MUTED)
            except V4L2Error:
                pass  # no auto control - we try to write anyway
        try:
            self.controls.set(ctrl_id, int(value))
        except V4L2Error as exc:
            self._notify(self._friendly_error(exc), ERROR)

    def _on_slider_change(self, ctrl_id: int, value: float) -> None:
        # Pan/tilt go through the tracker (the actuator), so the head model knows about every move.
        if ctrl_id in (CID_PAN_ABSOLUTE, CID_TILT_ABSOLUTE) and self.tracker is not None:
            target = int(round(value))
            moved = self.tracker.move_to(pan=target if ctrl_id == CID_PAN_ABSOLUTE else None,
                                         tilt=target if ctrl_id == CID_TILT_ABSOLUTE else None)
            if not moved:
                self._notify(t("app.hint_manual_control"), WARN)
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
        # dy=+1 means "down", and a positive tilt looks up.
        if not self.tracker.nudge(dx * delta, -dy * delta):
            self._notify(t("app.hint_manual_control"), WARN)

    def _on_center(self, _e=None) -> None:
        if self.tracker is not None and not self.tracker.move_to(pan=0, tilt=0):
            self._notify(t("app.hint_manual_center"), WARN)

    def _on_focus_auto(self, e) -> None:
        self._write(CID_FOCUS_AUTO, 1 if e.control.value else 0)

    def _on_gpu_change(self, e) -> None:
        self.settings["tracking"]["use_gpu"] = bool(e.control.value)
        if self.tracker:
            self.tracker.set_use_gpu(bool(e.control.value))
        self._notify(t("app.notice_detection", where="GPU (CUDA)" if e.control.value else "CPU"), OK)

    def _set_overlay(self, value: bool) -> None:
        self.overlay = bool(value)
        self.settings["overlay"] = self.overlay

    def _set_tracking_flag(self, key: str, value) -> None:
        self.settings["tracking"][key] = bool(value)
        self._notify(t("app.notice_reconnect"), MUTED)

    def _on_record_change(self, e) -> None:
        on = bool(e.control.value)
        self.settings["tracking"]["record"] = on
        self._save_settings(silent=True)
        if self.tracker:
            self.tracker.set_record(on)
        self._notify(t("app.notice_record_on") if on else t("app.notice_record_off"),
                     OK if on else MUTED)

    def _on_auto_zoom_change(self, e) -> None:
        on = bool(e.control.value)
        self.settings["tracking"]["auto_zoom"] = on
        self._save_settings(silent=True)
        if self.tracker:
            self.tracker.set_auto_zoom(on)
        self._notify(t("app.notice_auto_zoom_on") if on else t("app.notice_auto_zoom_off"),
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
        tr["profile"] = e.control.value or "talk"
        tr["overrides"] = {}
        self.shot_dd.value = resolve(tr["profile"], {}).shot    # a new profile = its shot
        if self.tracker:
            self.tracker.set_profile(tr["profile"], {})
        self._notify(t("app.notice_profile_default", profile=tr["profile"]), OK)

    def _on_tracking_toggle(self, e) -> None:
        enabled = bool(e.control.value)
        try:
            self.engine.set_tracking(enabled)
        except RuntimeError as exc:
            self._notify(str(exc), WARN)
            e.control.value = False
            e.control.update()
            return
        # The field under the preview is a one-off event message - the current state
        # (searching/tracking) is shown live in the right panel.
        self._notify(t("app.notice_tracking_on") if enabled else t("app.notice_tracking_off"),
                     OK if enabled else MUTED)

    def _on_search(self, _e) -> None:
        if self.tracker is None or not self.tracker.enabled:
            self._notify(t("app.notice_enable_tracking_to_search"), WARN)
            return
        self.tracker.search_now()
        self._notify(t("app.notice_search_started"), OK)

    def _on_preview_tap(self, e) -> None:
        """A click on the preview selects the person under the cursor (the tracker computes the hit in its own frame)."""
        tracker = self.tracker
        if tracker is None or not tracker.enabled or e.local_position is None:
            return
        point = frame_point(*self._overlay_size, tracker.state.frame_size,
                            e.local_position.x, e.local_position.y)
        if point is not None and tracker.select_at(*point):
            self._notify(t("app.notice_tracking_selected"), OK)

    def _on_auto_pick(self, _e) -> None:
        if self.tracker is not None:
            self.tracker.clear_selection()
            self._notify(t("app.notice_tracking_auto"), MUTED)

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
        self._notify(t("app.notice_home_set", pan=pan / 3600, tilt=tilt / 3600), OK)

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

    def _on_language_change(self, e) -> None:
        self.engine.set_language(e.control.value or "auto")
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        """Rebuild every widget in the active language. The engine and its state are untouched,
        so tracking, the virtual camera and the camera connection keep running."""
        self.page.controls.clear()
        self.control_widgets.clear()
        self.switch_widgets.clear()
        self._build_widgets()
        self._build_layout()
        self.page.title = t("app.title")
        self._privacy_shown = False          # the privacy card is re-rendered in the new language
        self._shown = None                   # force _sync_connection to repaint the connection card
        self._overlay_drawn = None           # force the overlay to be redrawn after the rebuild
        self._last_jpg = None                # no stale frame belongs to the rebuilt preview
        self._sync_connection()
        self._refresh_widgets()

    def _on_connect(self, _e) -> None:
        if self.engine.open_camera() is None:
            self._notify(t("app.notice_camera_connected"), OK)
        self._sync_connection()
        self._save_settings(silent=True)

    def _on_privacy_change(self, e) -> None:
        on = bool(e.control.value)
        self.engine.set_privacy(on)
        self._notify(t("app.notice_privacy_on") if on else t("app.notice_privacy_off"),
                     WARN if on else OK)

    # --- presets ---

    def _refresh_preset_options(self) -> None:
        self.preset_dd.options = [ft.DropdownOption(key=p.name, text=p.name)
                                  for p in self.store.presets]

    def _on_preset_save(self, _e) -> None:
        name = (self.preset_name.value or "").strip()
        if not name:
            self._notify(t("app.notice_preset_name_needed"), WARN)
            return
        if not self.controls:
            self._notify(t("app.notice_no_camera"), ERROR)
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
        self._notify(t("app.notice_preset_saved", name=name), OK)
        self._refresh_widgets()

    def _on_preset_load(self, _e) -> None:
        name = self.preset_dd.value
        preset = self.store.preset(name) if name else None
        if preset is None:
            self._notify(t("app.notice_preset_pick_load"), WARN)
            return
        if self.tracker and self.tracker.enabled:
            self._notify(t("app.notice_preset_tracking_off"), WARN)
            return
        for cid, value in ((CID_ZOOM_ABSOLUTE, preset.zoom), (CID_FOCUS_ABSOLUTE, preset.focus),
                           (CID_FOCUS_AUTO, preset.focus_auto)):
            if self.controls and self.controls.control(cid):
                self._write(cid, value)
        if self.tracker:
            self.tracker.move_to(pan=preset.pan, tilt=preset.tilt)   # through the actuator - the head model knows about the move
        self._sync_from_device()
        self._refresh_widgets()
        self._notify(t("app.notice_preset_loaded", name=name), OK)

    def _on_preset_delete(self, _e) -> None:
        name = self.preset_dd.value
        if not name:
            self._notify(t("app.notice_preset_pick_delete"), WARN)
            return
        if self.store.delete_preset(name):
            self._refresh_preset_options()
            self.preset_dd.value = None
            self._notify(t("app.notice_preset_deleted", name=name), OK)
            self._refresh_widgets()

    # --- actions ---

    def _on_snapshot(self, _e) -> None:
        if self._last_jpg is None:
            self._notify(t("app.notice_no_frame"), WARN)
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            path = snapshots_dir() / f"zrzut-{stamp}.jpg"
            path.write_bytes(self._last_jpg)
        except OSError as exc:
            self._notify(t("app.notice_snapshot_failed", error=exc), ERROR)
            return
        self._notify(t("app.notice_snapshot_saved", path=path), OK)

    def _on_reset_image(self, _e) -> None:
        if not self.controls:
            return
        # Auto balance last: writing the white balance turns auto off (AUTO_DEPENDENCIES).
        for cid in (CID_BRIGHTNESS, CID_CONTRAST, CID_SATURATION, CID_HUE, CID_GAMMA,
                    CID_SHARPNESS, CID_WHITE_BALANCE_TEMP, CID_BACKLIGHT_COMP,
                    CID_WHITE_BALANCE_AUTO):
            ctrl = self.controls.control(cid)
            if ctrl is not None:
                self._write(cid, ctrl.default)
        self._sync_from_device()
        self._refresh_widgets()
        self._notify(t("app.notice_image_reset"), OK)

    def _save_settings(self, silent: bool = False) -> None:
        try:
            self.store.save()
        except OSError as exc:
            self._notify(t("app.notice_settings_save_failed", error=exc), ERROR)
            return
        if not silent:
            self._notify(t("app.notice_settings_saved"), OK)

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
    # Loops: preview and status
    # ------------------------------------------------------------------

    def _sync_connection(self) -> None:
        """Shows the connection state from the engine - also when the engine connected by itself
        (camera released by another program) or changed the error message."""
        self._shown = (self.engine.tracker, self.engine.error)
        if self.engine.error or self.engine.tracker is None:
            self.connection_status.value = render(self.engine.error) or t("app.camera_disconnected")
            self.connection_status.color = ERROR
            self.preview_placeholder.visible = True
        else:
            self._show_connected()
        self._refresh_widgets()

    async def run(self) -> None:
        self._sync_connection()
        self.page.run_task(self._preview_loop)
        self.page.run_task(self._status_loop)

    # --- window: show / hide / close (external commands) ---

    def show_window(self) -> None:
        self.page.run_task(self._show)

    async def _show(self) -> None:
        self.hidden = False
        self.page.window.visible = True
        self.page.update()
        try:
            await self.page.window.to_front()
        except Exception:
            pass          # Wayland may refuse to raise the window

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
                self._notify(t("app.notice_tray_running"), MUTED)
            else:
                self.quit_app()

    def _show_privacy_card(self) -> None:
        self._privacy_shown = True
        self.preview.src = self._privacy_card
        self.overlay_canvas.shapes = []
        self._overlay_drawn = None
        self.preview.visible = True
        self.preview_placeholder.visible = False
        self.preview_badge.value = t("app.privacy_preview")
        try:
            self.preview_stack.update()
        except Exception:
            pass

    async def _preview_loop(self) -> None:
        """Passes frames to the Image control, with optional detection drawing."""
        while not self.closing:
            if self.hidden:                            # hidden window: we do not send frames to Flet
                await asyncio.sleep(0.2)
                continue
            if self.engine.privacy.active:
                if not self._privacy_shown:
                    self._show_privacy_card()
                await asyncio.sleep(0.1)
                continue
            if self._privacy_shown:                    # end of privacy: the slate disappears
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
                    self.preview_stack.update()         # image and overlay in one message
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
        """Sets the overlay shapes; ``True`` when they changed and need to be sent."""
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
        """Refreshes the camera readings and tracker statistics a few times per second."""
        while not self.closing:
            await asyncio.sleep(0.25)
            try:
                # Virtual camera state and privacy are updated even without a camera -
                # the slate and the switch must work when there is no device.
                self.vcam_status.value = t("app.vcam_state", state=render(self.engine.vcam.status))
                self.privacy_sw.value = self.engine.privacy.active
                if (self.engine.tracker, self.engine.error) != self._shown:
                    self._sync_connection()
                    if self.engine.tracker is not None:
                        self._notify(t("app.notice_camera_connected"), OK)
                if self.controls is None:
                    self.page.update()
                    continue
                self._sync_from_device()
                state = self.tracker.state if self.tracker else None
                parts = [t("app.footer_controls", count=len(self.controls.list_controls()))]
                if self.stream:
                    parts.append(t("app.footer_dropped", count=self.stream.dropped))
                self.footer.value = "  •  ".join(parts)
                if state is not None:
                    self.track_detail.value = _diag_text(state)
                    self.track_status.value = render(state.message)
                    self.select_status.value = render(selection_text(state) or msg("app.select_hint"))
                    self.auto_pick_btn.disabled = state.selection == "auto"
                    if self.track_sw.value != state.enabled:
                        self.track_sw.value = state.enabled      # the tracker may have turned itself off (error, disconnect)
                    if state.enabled and self.auto_zoom_sw.value and not state.auto_zoom:
                        # The tracker turned automation off because the zoom was changed manually -
                        # we persist it and say so.
                        self.auto_zoom_sw.value = False
                        self.settings["tracking"]["auto_zoom"] = False
                        self._save_settings(silent=True)
                        self._notify(t("app.notice_zoom_manual_off"), WARN)
                    azimuth = self.tracker.last_azimuth
                    stored = self.settings["tracking"]["last_azimuth"]
                    if azimuth and (not stored or abs(azimuth[0] - stored[0]) > 3600):
                        self.settings["tracking"]["last_azimuth"] = [azimuth[0], azimuth[1]]
                        self._save_settings(silent=True)
                self.page.update()
            except Exception as exc:
                self._notify(t("app.notice_status_loop_error", error=exc), ERROR)


def main(page: ft.Page, engine: Engine, tray: TrayProcess) -> None:
    page.title = t("app.title")
    page.theme_mode = ft.ThemeMode.DARK
    try:
        page.window.width = 1420
        page.window.height = 900
        page.window.min_width = 1100
        page.window.min_height = 700
    except Exception:
        pass  # in web mode there is no window
    app = CameraApp(page, engine, tray)
    engine.ui = UiHooks(show=app.show_window, hide=app.hide_window, quit=app.quit_app)
    try:
        page.window.prevent_close = True
        page.window.on_event = app.on_window_event
    except Exception:
        pass  # in web mode there is no window
    page.run_task(app.run)


def _parse_args(argv: list[str]):
    import argparse

    parser = argparse.ArgumentParser(
        description="Control the Polycom EagleEye IV USB camera",
        epilog="By default opens the native window. Also run through 'flet run app.py'.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--web", action="store_true",
                      help="serve as a web application at the given address (without opening a window)")
    mode.add_argument("--browser", action="store_true",
                      help="run as a web application and open the browser")
    mode.add_argument("--hidden", action="store_true", help="native window, but hidden")
    parser.add_argument("--host", default="127.0.0.1", help="listen address in web mode")
    parser.add_argument("--port", type=int, default=8550, help="port in web mode")
    return parser.parse_known_args(argv)[0]


def run_app(argv: list[str] | None = None) -> None:
    """Starts the application: engine, control socket, tray icon, window."""
    logging.basicConfig(
        level=logging.INFO, stream=sys.stdout,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # OpenCV 5 no longer has cv2.setLogLevel - it is cv2.utils.logging.
    # Note: libjpeg messages ("Corrupt JPEG data: N extraneous bytes
    # before marker 0xd9") cannot be silenced this way, because libjpeg writes directly
    # to stderr. The camera adds a few bytes of padding before the EOI marker,
    # the image decodes correctly - it is only terminal noise.
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except AttributeError:
        pass
    # The OpenCV pool has one thread per core by default; on single-frame operations
    # the threads mostly spin. Measured on 1080p conversion for vcam:
    # 12 threads 67 ms CPU/frame, 2 threads 26 ms - at almost the same wall time.
    cv2.setNumThreads(2)
    args = _parse_args(list(argv if argv is not None else sys.argv[1:]))
    engine = Engine(Store())
    server = ControlServer(engine.command)
    tray = TrayProcess()
    try:
        server.start()      # socket first: a second start during startup will only show the window
    except InstanceRunning:
        send("show", None, server.path)
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
