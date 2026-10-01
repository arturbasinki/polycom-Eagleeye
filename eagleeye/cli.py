"""Polecenie ``eagleeye``: uruchamia aplikację albo steruje działającą.

    eagleeye                         uruchom (albo pokaż okno działającej)
    eagleeye prywatnosc [wl|wyl]     prywatność (bez argumentu: przełącz)
    eagleeye sledzenie [wl|wyl]      auto-tracking
    eagleeye profil rozmowa          profil śledzenia
    eagleeye autozoom [wl|wyl]       zoom automatyczny (bez argumentu: przełącz)
    eagleeye wybierz X,Y | brak      śledź osobę w punkcie klatki (rozmiar: stan -> wybor.klatka)
    eagleeye stan                    stan w JSON
    eagleeye pokaz | schowaj | zakoncz
"""

from __future__ import annotations

import json
import subprocess
import sys

from .control import instance_running, send, socket_path

COMMANDS = {"pokaz", "schowaj", "prywatnosc", "sledzenie", "profil", "autozoom", "wybierz", "stan", "zakoncz"}


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
    if args and args[0] in ("-h", "--help", "pomoc"):
        print(__doc__)
        return 0
    if args and args[0] in COMMANDS:
        try:
            reply = send(args[0], args[1] if len(args) > 1 else None, path)
        except OSError:
            print("EagleEye nie działa", file=sys.stderr)
            notify("EagleEye nie działa - uruchom aplikację z menu")
            return 1
        print(json.dumps(reply, ensure_ascii=False))
        if not reply.get("ok"):
            notify(str(reply.get("blad", "błąd polecenia")))
            return 1
        return 0
    if instance_running(path):
        send("pokaz", None, path)
        return 0
    from app import run_app        # Flet i modele ładujemy tylko przy prawdziwym starcie
    run_app(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
