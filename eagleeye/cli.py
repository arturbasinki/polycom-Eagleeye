"""The ``eagleeye`` command: starts the app or controls a running instance.

    eagleeye                         start (or show the window of a running instance)
    eagleeye privacy [on|off]        privacy (no argument: toggle)
    eagleeye tracking [on|off]       auto-tracking
    eagleeye profile talk            tracking profile
    eagleeye autozoom [on|off]       automatic zoom (no argument: toggle)
    eagleeye select X,Y | none       track the person at a frame point (size: state -> selection.frame)
    eagleeye state                   state as JSON
    eagleeye show | hide | quit
    eagleeye language [auto|en|pl]   UI language
"""

from __future__ import annotations

import json
import subprocess
import sys

from .config import language_setting
from .control import instance_running, send, socket_path
from .i18n import render, set_language, t

COMMANDS = {"show", "hide", "privacy", "tracking", "profile", "autozoom", "select", "state", "quit", "language"}


def notify(text: str) -> None:
    """Powiadomienie pulpitu - skrót klawiszowy nie ma terminala, w którym widać błąd."""
    try:
        subprocess.Popen(["notify-send", "-a", "EagleEye", "EagleEye", text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    path = socket_path()
    if args and args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if args and args[0] in COMMANDS:
        try:
            reply = send(args[0], args[1] if len(args) > 1 else None, path)
        except OSError:
            set_language(language_setting())
            print(t("cli.not_running"), file=sys.stderr)
            notify(t("cli.not_running_notify"))
            return 1
        print(json.dumps(reply, ensure_ascii=False))
        if not reply.get("ok"):
            set_language(language_setting())
            notify(render(reply.get("message")) if reply.get("message")
                   else str(reply.get("error", t("cli.command_failed"))))
            return 1
        return 0
    if instance_running(path):
        send("show", None, path)
        return 0
    from app import run_app        # Flet i modele ładujemy tylko przy prawdziwym starcie
    run_app(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
