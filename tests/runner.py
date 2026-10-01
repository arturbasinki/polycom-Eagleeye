"""Wspólny, minimalny runner testów (projekt nie używa pytest).

Każdy plik testów kończy się::

    if __name__ == "__main__":
        run(globals(), "Nazwa zestawu")

Katalog ``tests`` jest na ``sys.path``, bo Python dodaje katalog uruchamianego
skryptu - dlatego ``from runner import run`` działa bez instalacji.
"""

from __future__ import annotations

import sys
import traceback


def run(namespace: dict, title: str) -> None:
    tests = [v for k, v in sorted(namespace.items()) if k.startswith("test_") and callable(v)]
    print(f"{title} ({len(tests)}):\n")
    failures = 0
    for test in tests:
        print(f"- {test.__name__}")
        try:
            test()
        except AssertionError as exc:
            failures += 1
            print(f"    NIEUDANY: {exc}")
        except Exception:
            failures += 1
            print("    BŁĄD:")
            traceback.print_exc()
    print()
    if failures:
        print(f"WYNIK: {failures} z {len(tests)} testów nie przeszło")
        sys.exit(1)
    print(f"WYNIK: wszystkie {len(tests)} testy przeszły")
