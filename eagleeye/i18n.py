"""Runtime translation for the UI: JSON catalogs, fallback chain, serialisable messages.

Standard library only: the tray icon runs on the system ``python3`` without the project
venv, and the installer calls ``python3 -m eagleeye.i18n`` before the venv exists.

Catalogs live in ``eagleeye/locales/<code>.json``: a flat object with dotted semantic keys
and ``{name}`` placeholders (``str.format`` syntax); ``_name`` is the language's own name.
Lookup order: selected language, then English, then the key itself.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent / "locales"
DEFAULT_LANGUAGE = "en"
AUTO = "auto"

log = logging.getLogger("eagleeye")

_catalogs: dict[str, dict[str, str]] = {}
_language = DEFAULT_LANGUAGE
_warned: set[tuple[str, str]] = set()


def reload() -> None:
    """Forget cached catalogs (after ``LOCALES_DIR`` changed or a catalog was edited)."""
    _catalogs.clear()
    _warned.clear()


def _catalog(code: str) -> dict[str, str]:
    catalog = _catalogs.get(code)
    if catalog is None:
        try:
            catalog = json.loads((LOCALES_DIR / f"{code}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            catalog = {}
        _catalogs[code] = catalog
    return catalog


def _warn_once(key: str, problem: str) -> None:
    if (key, problem) not in _warned:
        _warned.add((key, problem))
        log.warning("i18n: %s: %s", problem, key)


def available_languages() -> dict[str, str]:
    """Language code -> the language's own name, for every catalog on disk."""
    return {path.stem: _catalog(path.stem).get("_name", path.stem)
            for path in sorted(LOCALES_DIR.glob("*.json"))}


def detect_language(env: dict[str, str] | None = None) -> str:
    """Language from the environment: LC_ALL, LC_MESSAGES, LANG (first non-empty wins)."""
    env = os.environ if env is None else env
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = env.get(var, "")
        if value:
            code = value.split(".")[0].split("@")[0].split("_")[0].lower()
            return code if code in available_languages() else DEFAULT_LANGUAGE
    return DEFAULT_LANGUAGE


def set_language(code: str) -> str:
    """Select the active language (``"auto"`` = detect). Unknown codes fall back to English."""
    global _language
    if code == AUTO:
        code = detect_language()
    if code not in available_languages():
        code = DEFAULT_LANGUAGE
    _language = code
    return code


def get_language() -> str:
    return _language


def translate(language: str, key: str, **params) -> str:
    """Text for ``key`` in ``language``; never raises (bad catalog text is returned as is)."""
    text = _catalog(language).get(key)
    if text is None and language != DEFAULT_LANGUAGE:
        text = _catalog(DEFAULT_LANGUAGE).get(key)
    if text is None:
        _warn_once(key, "missing key")
        return key
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError) as exc:
        _warn_once(key, f"bad placeholders ({exc!r})")
        return text


def t(key: str, **params) -> str:
    """Text for ``key`` in the active language."""
    return translate(_language, key, **params)


@dataclass(frozen=True)
class Message:
    """A user-visible message as data: rendered by the view layer, never by core logic."""

    key: str
    params: dict = field(default_factory=dict, hash=False)

    def text(self, language: str | None = None) -> str:
        return translate(language or _language, self.key, **self.params)

    def to_dict(self) -> dict:
        return {"key": self.key, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(str(data["key"]), dict(data.get("params") or {}))


def msg(key: str, **params) -> Message:
    return Message(key, params)


class LocalizedError(Exception):
    """An error the user should see: carries a ``Message``; ``str()`` is the English text."""

    def __init__(self, key: str, **params) -> None:
        self.message = Message(key, params)
        super().__init__(self.message.text("en"))


def render(value) -> str:
    """Text for a ``Message``, a serialised message (dict) or a plain string; None -> ""."""
    if value is None:
        return ""
    if isinstance(value, Message):
        return value.text()
    if isinstance(value, dict) and "key" in value:
        return Message.from_dict(value).text()
    return str(value)


def main(argv: list[str] | None = None) -> int:
    """``python3 -m eagleeye.i18n [--lang CODE] KEY [name=value ...]``: print one translated line."""
    args = list(sys.argv[1:] if argv is None else argv)
    language = AUTO
    if args[:1] == ["--lang"] and len(args) >= 2:
        language, args = args[1], args[2:]
    if not args:
        print("usage: python3 -m eagleeye.i18n [--lang CODE] KEY [name=value ...]", file=sys.stderr)
        return 2
    set_language(language)
    params = dict(a.split("=", 1) for a in args[1:] if "=" in a)
    print(t(args[0], **params))
    return 0


if __name__ == "__main__":
    sys.exit(main())
