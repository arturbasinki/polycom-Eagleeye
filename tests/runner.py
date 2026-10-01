"""Shared, minimal test runner (the project does not use pytest).

Every test file ends with::

    if __name__ == "__main__":
        run(globals(), "Nazwa zestawu")

The ``tests`` directory is on ``sys.path`` because Python adds the directory of the
script being run - that is why ``from runner import run`` works without installation.
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
            print(f"    FAILED: {exc}")
        except Exception:
            failures += 1
            print("    ERROR:")
            traceback.print_exc()
    print()
    if failures:
        print(f"RESULT: {failures} of {len(tests)} tests failed")
        sys.exit(1)
    print(f"RESULT: all {len(tests)} tests passed")
