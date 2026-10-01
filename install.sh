#!/usr/bin/env bash
# EagleEye installer: virtual camera module, environment, model, menu entry, shortcut.
# Safe to re-run.   --dry-run: only print the steps, change nothing.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
msg() { PYTHONPATH="$REPO" python3 -m eagleeye.i18n "$@" 2>/dev/null || printf '%s\n' "$1"; }   # a missing python3 prints the key, never aborts
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

BIN_DIR="$HOME/.local/bin"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
LAUNCHER="$BIN_DIR/eagleeye"
DESKTOP="$APP_DIR/eagleeye.desktop"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
PLACEHOLDER_UNIT=eagleeye-placeholder.service
MODEL="$REPO/models/rtmo-s_body7_640.onnx"
MODEL_URL="https://download.openmmlab.com/mmpose/v1/projects/rtmo/onnx_sdk/rtmo-s_8xb32-600e_body7-640x640-dac2bf74_20231211.zip"
MODPROBE_CONF=/etc/modprobe.d/eagleeye.conf
MODULES_CONF=/etc/modules-load.d/eagleeye.conf
MODPROBE_LINE='options v4l2loopback devices=1 video_nr=10 card_label="EagleEye" exclusive_caps=1'
PACKAGES=(v4l2loopback-dkms gir1.2-ayatanaappindicator3-0.1 python3-venv)
SHORTCUT_BINDING='<Shift><Super>c'
SHORTCUT_PATH=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/eagleeye-privacy/
MEDIA_KEYS=org.gnome.settings-daemon.plugins.media-keys

step() { printf '\n==> %s\n' "$*"; }
run() { if (( DRY_RUN )); then printf '    [dry-run] %s\n' "$*"; else "$@"; fi; }

write_root_file() {    # file content - through sudo, only when the content changes
    if [[ -f "$1" && "$(cat "$1")" == "$2" ]]; then echo "    $(msg installer.file_unchanged "path=$1")"; return; fi
    if (( DRY_RUN )); then echo "    $(msg installer.dry_write_content "path=$1" "content=$2")"
    else printf '%s\n' "$2" | sudo tee "$1" >/dev/null; echo "    $(msg installer.file_written "path=$1")"; fi
}

write_user_file() {    # file content [mode]
    if [[ -f "$1" && "$(cat "$1")" == "$2" ]]; then echo "    $(msg installer.file_unchanged "path=$1")"; return; fi
    if (( DRY_RUN )); then echo "    $(msg installer.dry_write "path=$1")"; return; fi
    mkdir -p "$(dirname "$1")"
    printf '%s\n' "$2" > "$1"
    [[ -n "${3:-}" ]] && chmod "$3" "$1"
    echo "    $(msg installer.file_written "path=$1")"
}

step "$(msg installer.step.packages)"
missing=()
for p in "${PACKAGES[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p"); done
if (( ${#missing[@]} )); then
    echo "    $(msg installer.packages_installing "packages=${missing[*]}")"
    run sudo apt-get install -y "${missing[@]}"
else
    echo "    $(msg installer.packages_ok)"
fi

step "$(msg installer.step.module)"
write_root_file "$MODPROBE_CONF" "$MODPROBE_LINE"
write_root_file "$MODULES_CONF" "v4l2loopback"
if grep -qlx EagleEye /sys/class/video4linux/*/name 2>/dev/null; then
    echo "    $(msg installer.device_ok)"
elif lsmod | grep -q '^v4l2loopback'; then
    echo "    $(msg installer.module_other_options)"
    echo "    $(msg installer.module_restart)"
else
    run sudo modprobe v4l2loopback
fi

step "$(msg installer.step.python)"
if [[ ! -x "$REPO/.venv/bin/python" ]]; then run python3 -m venv "$REPO/.venv"; fi
req="$REPO/requirements.txt"
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "    $(msg installer.no_nvidia)"
    req_cpu="$(mktemp)"
    grep -vE 'onnxruntime-gpu|nvidia-cudnn' "$REPO/requirements.txt" > "$req_cpu"
    echo "onnxruntime>=1.20" >> "$req_cpu"
    req="$req_cpu"
fi
run "$REPO/.venv/bin/pip" install -q -r "$req"

step "$(msg installer.step.model)"
if [[ -f "$MODEL" ]]; then
    echo "    $(msg installer.model_present "path=$MODEL")"
else
    tmp_zip="$(mktemp --suffix=.zip)"
    run mkdir -p "$REPO/models"
    run curl -fL -o "$tmp_zip" "$MODEL_URL"
    run sh -c "unzip -p '$tmp_zip' end2end.onnx > '$MODEL'"
fi

step "$(msg installer.step.launcher)"
write_user_file "$LAUNCHER" "#!/bin/sh
cd \"$REPO\" && exec \"$REPO/.venv/bin/python\" -m eagleeye.cli \"\$@\"" 755
# The window is drawn by the Flet client, which on Linux always presents itself as com.appveyor.flet:
# StartupWMClass links that window to the EagleEye icon in the dock. StartupNotify=false, because the window
# comes from a different process than the launcher (and a second start only shows the window) -
# GNOME would wait for it until the "busy" cursor times out.
write_user_file "$DESKTOP" "[Desktop Entry]
Type=Application
Name=EagleEye
Comment=Control for the Polycom EagleEye IV camera with auto-tracking
Comment[pl]=Sterowanie kamerą Polycom EagleEye IV z auto-trackingiem
Exec=$LAUNCHER
Icon=$REPO/assets/eagleeye.svg
Terminal=false
Categories=AudioVideo;Video;
StartupNotify=false
StartupWMClass=com.appveyor.flet"
if command -v update-desktop-database >/dev/null 2>&1; then run update-desktop-database -q "$APP_DIR" || true; fi

step "$(msg installer.step.placeholder)"
# Chrome sees the v4l2loopback device only while someone writes to it, and it builds its camera list
# at startup. The placeholder writes the slate from login and releases the device to the app.
write_user_file "$UNIT_DIR/$PLACEHOLDER_UNIT" "[Unit]
Description=EagleEye: slate shown in the virtual camera when the app is not running

[Service]
WorkingDirectory=$REPO
ExecStart=$REPO/.venv/bin/python -m eagleeye.placeholder
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target"
if command -v systemctl >/dev/null 2>&1; then
    run systemctl --user daemon-reload
    run systemctl --user enable --now "$PLACEHOLDER_UNIT"
    run systemctl --user restart "$PLACEHOLDER_UNIT"
else
    echo "    $(msg installer.no_systemctl "command=$REPO/.venv/bin/python -m eagleeye.placeholder")"
fi

step "$(msg installer.step.shortcut)"
if ! command -v gsettings >/dev/null 2>&1; then
    echo "    $(msg installer.no_gsettings "command=$LAUNCHER privacy")"
else
    current="$(gsettings get "$MEDIA_KEYS" custom-keybindings)"
    taken="$(gsettings list-recursively 2>/dev/null | grep -iE "<(Shift><Super|Super><Shift)>c'" | grep -v eagleeye || true)"
    if [[ -n "$taken" && "$current" != *"eagleeye-privacy"* ]]; then
        echo "    $(msg installer.shortcut_taken)"
        echo "    $taken"
    else
        new_list="$(python3 -c "import ast,sys; l=ast.literal_eval(sys.argv[1].replace('@as ', '')); p=sys.argv[2]; print(l if p in l else l+[p])" "$current" "$SHORTCUT_PATH")"
        schema="$MEDIA_KEYS.custom-keybinding:$SHORTCUT_PATH"
        run gsettings set "$MEDIA_KEYS" custom-keybindings "$new_list"
        run gsettings set "$schema" name "$(msg installer.shortcut_name)"
        run gsettings set "$schema" command "$LAUNCHER privacy"
        run gsettings set "$schema" binding "$SHORTCUT_BINDING"
    fi
fi

step "$(msg installer.step.done)"
echo "    $(msg installer.done_launch)"
echo "    $(msg installer.done_commands "dir=$BIN_DIR")"
(( DRY_RUN )) && echo "    $(msg installer.dry_run_note)"
exit 0
