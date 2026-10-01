#!/usr/bin/env bash
# Instalator EagleEye: moduł wirtualnej kamery, środowisko, model, wpis w menu, skrót.
# Bezpieczny do ponownego uruchomienia.   --dry-run: tylko wypisz kroki, nic nie zmieniaj.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

BIN_DIR="$HOME/.local/bin"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
LAUNCHER="$BIN_DIR/eagleeye"
DESKTOP="$APP_DIR/eagleeye.desktop"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
PLACEHOLDER_UNIT=eagleeye-zaslepka.service
MODEL="$REPO/models/rtmo-s_body7_640.onnx"
MODEL_URL="https://download.openmmlab.com/mmpose/v1/projects/rtmo/onnx_sdk/rtmo-s_8xb32-600e_body7-640x640-dac2bf74_20231211.zip"
MODPROBE_CONF=/etc/modprobe.d/eagleeye.conf
MODULES_CONF=/etc/modules-load.d/eagleeye.conf
MODPROBE_LINE='options v4l2loopback devices=1 video_nr=10 card_label="EagleEye" exclusive_caps=1'
PACKAGES=(v4l2loopback-dkms gir1.2-ayatanaappindicator3-0.1 python3-venv)
SHORTCUT_BINDING='<Shift><Super>c'
SHORTCUT_PATH=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/eagleeye-prywatnosc/
MEDIA_KEYS=org.gnome.settings-daemon.plugins.media-keys

step() { printf '\n==> %s\n' "$*"; }
run() { if (( DRY_RUN )); then printf '    [dry-run] %s\n' "$*"; else "$@"; fi; }

write_root_file() {    # plik treść - przez sudo, tylko gdy treść się zmienia
    if [[ -f "$1" && "$(cat "$1")" == "$2" ]]; then echo "    $1: bez zmian"; return; fi
    if (( DRY_RUN )); then printf '    [dry-run] zapis %s: %s\n' "$1" "$2"
    else printf '%s\n' "$2" | sudo tee "$1" >/dev/null; echo "    zapisano $1"; fi
}

write_user_file() {    # plik treść [tryb]
    if [[ -f "$1" && "$(cat "$1")" == "$2" ]]; then echo "    $1: bez zmian"; return; fi
    if (( DRY_RUN )); then printf '    [dry-run] zapis %s\n' "$1"; return; fi
    mkdir -p "$(dirname "$1")"
    printf '%s\n' "$2" > "$1"
    [[ -n "${3:-}" ]] && chmod "$3" "$1"
    echo "    zapisano $1"
}

step "Pakiety systemowe"
missing=()
for p in "${PACKAGES[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p"); done
if (( ${#missing[@]} )); then
    echo "    doinstaluję (wymaga sudo): ${missing[*]}"
    run sudo apt-get install -y "${missing[@]}"
else
    echo "    wszystkie są zainstalowane"
fi

step "Moduł wirtualnej kamery (v4l2loopback)"
write_root_file "$MODPROBE_CONF" "$MODPROBE_LINE"
write_root_file "$MODULES_CONF" "v4l2loopback"
if grep -qlx EagleEye /sys/class/video4linux/*/name 2>/dev/null; then
    echo "    urządzenie EagleEye działa"
elif lsmod | grep -q '^v4l2loopback'; then
    echo "    UWAGA: v4l2loopback jest załadowany z innymi opcjami (inny program?)."
    echo "    Nie wyładowuję go na siłę - uruchom komputer ponownie, żeby pojawiła się kamera EagleEye."
else
    run sudo modprobe v4l2loopback
fi

step "Środowisko Pythona"
if [[ ! -x "$REPO/.venv/bin/python" ]]; then run python3 -m venv "$REPO/.venv"; fi
req="$REPO/requirements.txt"
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "    brak karty NVIDIA - instaluję ONNX Runtime na CPU"
    req_cpu="$(mktemp)"
    grep -vE 'onnxruntime-gpu|nvidia-cudnn' "$REPO/requirements.txt" > "$req_cpu"
    echo "onnxruntime>=1.20" >> "$req_cpu"
    req="$req_cpu"
fi
run "$REPO/.venv/bin/pip" install -q -r "$req"

step "Model pozy RTMO-s"
if [[ -f "$MODEL" ]]; then
    echo "    $MODEL: jest"
else
    tmp_zip="$(mktemp --suffix=.zip)"
    run mkdir -p "$REPO/models"
    run curl -fL -o "$tmp_zip" "$MODEL_URL"
    run sh -c "unzip -p '$tmp_zip' end2end.onnx > '$MODEL'"
fi

step "Wpis w menu i polecenie eagleeye"
write_user_file "$LAUNCHER" "#!/bin/sh
cd \"$REPO\" && exec \"$REPO/.venv/bin/python\" -m eagleeye.cli \"\$@\"" 755
# Okno rysuje klient Flet, który na Linuksie przedstawia się zawsze jako com.appveyor.flet:
# StartupWMClass łączy to okno z ikoną EagleEye w docku. StartupNotify=false, bo okno
# pochodzi z innego procesu niż uruchomiony (a drugie uruchomienie tylko pokazuje okno) -
# GNOME czekałby na nie do upływu czasu z kursorem „zajęty”.
write_user_file "$DESKTOP" "[Desktop Entry]
Type=Application
Name=EagleEye
Comment=Sterowanie kamerą Polycom EagleEye IV z auto-trackingiem
Exec=$LAUNCHER
Icon=$REPO/assets/eagleeye.svg
Terminal=false
Categories=AudioVideo;Video;
StartupNotify=false
StartupWMClass=com.appveyor.flet"
if command -v update-desktop-database >/dev/null 2>&1; then run update-desktop-database -q "$APP_DIR" || true; fi

step "Zaślepka wirtualnej kamery (EagleEye zawsze widoczna w Chrome)"
# Chrome widzi urządzenie v4l2loopback tylko wtedy, gdy ktoś do niego pisze, a listę kamer
# buduje przy starcie. Zaślepka pisze planszę od zalogowania i oddaje urządzenie aplikacji.
write_user_file "$UNIT_DIR/$PLACEHOLDER_UNIT" "[Unit]
Description=EagleEye: plansza w wirtualnej kamerze, gdy aplikacja nie działa

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
    echo "    brak systemctl - zaślepka nie wystartuje sama (uruchom: $REPO/.venv/bin/python -m eagleeye.placeholder)"
fi

step "Skrót klawiszowy prywatności (Super+Shift+C)"
if ! command -v gsettings >/dev/null 2>&1; then
    echo "    brak gsettings - pomijam (przypisz skrót ręcznie: $LAUNCHER prywatnosc)"
else
    current="$(gsettings get "$MEDIA_KEYS" custom-keybindings)"
    taken="$(gsettings list-recursively 2>/dev/null | grep -iE "<(Shift><Super|Super><Shift)>c'" | grep -v eagleeye || true)"
    if [[ -n "$taken" && "$current" != *"eagleeye-prywatnosc"* ]]; then
        echo "    UWAGA: Super+Shift+C jest zajęty - nie przejmuję go:"
        echo "    $taken"
    else
        new_list="$(python3 -c "import ast,sys; l=ast.literal_eval(sys.argv[1].replace('@as ', '')); p=sys.argv[2]; print(l if p in l else l+[p])" "$current" "$SHORTCUT_PATH")"
        schema="$MEDIA_KEYS.custom-keybinding:$SHORTCUT_PATH"
        run gsettings set "$MEDIA_KEYS" custom-keybindings "$new_list"
        run gsettings set "$schema" name "EagleEye: prywatność"
        run gsettings set "$schema" command "$LAUNCHER prywatnosc"
        run gsettings set "$schema" binding "$SHORTCUT_BINDING"
    fi
fi

step "Gotowe"
echo "    Uruchom z menu: EagleEye. W Meet / Teams / OBS wybierz kamerę „EagleEye”."
echo "    Polecenia: eagleeye --help   (katalog $BIN_DIR musi być w PATH)"
(( DRY_RUN )) && echo "    (tryb --dry-run: nic nie zostało zmienione)"
exit 0
