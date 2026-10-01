#!/usr/bin/env bash
# Odinstalowanie EagleEye. Domyślnie zostawia pakiety systemowe i venv.
#   --all  usuwa też venv i pakiet v4l2loopback-dkms
#   --dry-run   tylko wypisz kroki
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
msg() { PYTHONPATH="$REPO" python3 -m eagleeye.i18n "$@" 2>/dev/null || printf '%s\n' "$1"; }   # a missing python3 prints the key, never aborts
DRY_RUN=0; ALL=0
for a in "$@"; do
    case "$a" in --dry-run) DRY_RUN=1 ;; --all) ALL=1 ;; esac
done
MEDIA_KEYS=org.gnome.settings-daemon.plugins.media-keys
SHORTCUT_PATH=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/eagleeye-privacy/

step() { printf '\n==> %s\n' "$*"; }
run() { if (( DRY_RUN )); then printf '    [dry-run] %s\n' "$*"; else "$@"; fi; }

step "$(msg installer.step.uninstall_close)"
if [[ -x "$HOME/.local/bin/eagleeye" ]]; then run "$HOME/.local/bin/eagleeye" quit || true; fi

step "$(msg installer.step.uninstall_placeholder)"
PLACEHOLDER="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/eagleeye-placeholder.service"
if [[ -e "$PLACEHOLDER" ]]; then
    run systemctl --user disable --now eagleeye-placeholder.service || true
    run rm -f "$PLACEHOLDER"
    run systemctl --user daemon-reload
fi

step "$(msg installer.step.uninstall_menu)"
for f in "$HOME/.local/bin/eagleeye" "${XDG_DATA_HOME:-$HOME/.local/share}/applications/eagleeye.desktop"; do
    if [[ -e "$f" ]]; then run rm -f "$f"; fi
done

step "$(msg installer.step.uninstall_shortcut)"
if command -v gsettings >/dev/null 2>&1; then
    current="$(gsettings get "$MEDIA_KEYS" custom-keybindings)"
    if [[ "$current" == *"eagleeye-privacy"* ]]; then
        new_list="$(python3 -c "import ast,sys; l=ast.literal_eval(sys.argv[1].replace('@as ', '')); print([x for x in l if x != sys.argv[2]])" "$current" "$SHORTCUT_PATH")"
        run gsettings set "$MEDIA_KEYS" custom-keybindings "$new_list"
        run gsettings reset-recursively "$MEDIA_KEYS.custom-keybinding:$SHORTCUT_PATH"
    fi
fi

step "$(msg installer.step.uninstall_module)"
for f in /etc/modprobe.d/eagleeye.conf /etc/modules-load.d/eagleeye.conf; do
    if [[ -e "$f" ]]; then run sudo rm -f "$f"; fi
done

if (( ALL )); then
    step "$(msg installer.step.uninstall_env)"
    run rm -rf "$REPO/.venv"
    run sudo apt-get remove -y v4l2loopback-dkms
fi

step "$(msg installer.step.done)"
(( DRY_RUN )) && echo "    $(msg installer.dry_run_note)"
exit 0
