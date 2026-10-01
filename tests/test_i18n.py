#!/usr/bin/env python3
"""i18n module: catalogs, fallback chain, language detection, serialisable messages.

    .venv/bin/python tests/test_i18n.py
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye import i18n  # noqa: E402
from eagleeye.i18n import LocalizedError, Message, msg, render, t, translate  # noqa: E402


@contextlib.contextmanager
def catalogs(**by_language: dict):
    """Temporary catalog directory; restores the real one and the language afterwards."""
    old_dir, old_lang = i18n.LOCALES_DIR, i18n.get_language()
    tmp = Path(tempfile.mkdtemp())
    for code, data in by_language.items():
        (tmp / f"{code}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    i18n.LOCALES_DIR = tmp
    i18n.reload()
    try:
        i18n.set_language("en")
        yield
    finally:
        i18n.LOCALES_DIR = old_dir
        i18n.reload()
        i18n.set_language(old_lang)


EN = {"_name": "English", "hello": "hello {name}", "only_en": "only english", "plain": "plain"}
PL = {"_name": "Polski", "hello": "cześć {name}", "plain": "zwykły"}


def test_translates_in_the_selected_language() -> None:
    with catalogs(en=EN, pl=PL):
        assert t("hello", name="Ala") == "hello Ala"
        i18n.set_language("pl")
        assert t("hello", name="Ala") == "cześć Ala"
        assert translate("en", "plain") == "plain"


def test_missing_key_falls_back_to_english() -> None:
    with catalogs(en=EN, pl=PL):
        i18n.set_language("pl")
        assert t("only_en") == "only english"


def test_unknown_key_returns_the_key_and_warns_once() -> None:
    records: list[str] = []

    class Grab(logging.Handler):
        def emit(self, record) -> None:
            records.append(record.getMessage())

    handler = Grab()
    logging.getLogger("eagleeye").addHandler(handler)
    try:
        with catalogs(en=EN):
            assert t("no.such.key") == "no.such.key"
            assert t("no.such.key") == "no.such.key"
    finally:
        logging.getLogger("eagleeye").removeHandler(handler)
    assert len([r for r in records if "no.such.key" in r]) == 1


def test_broken_catalog_text_never_raises() -> None:
    bad = {"_name": "English", "stray": "oops { here", "missing": "needs {value}", "index": "{0}"}
    with catalogs(en=bad):
        assert t("stray") == "oops { here"
        assert t("missing") == "needs {value}"
        assert t("index") == "{0}"
        assert t("missing", value=3) == "needs 3"


def test_params_may_contain_braces_and_unicode() -> None:
    with catalogs(en={"_name": "English", "err": "error: {error}"}):
        assert t("err", error="{x} zażółć gęślą") == "error: {x} zażółć gęślą"


def test_detect_language_from_environment_forms() -> None:
    with catalogs(en=EN, pl=PL):
        cases = [
            ({"LANG": "pl_PL.UTF-8"}, "pl"),
            ({"LANG": "pl"}, "pl"),
            ({"LANG": "pl_PL@euro"}, "pl"),
            ({"LC_ALL": "pl_PL.UTF-8", "LANG": "en_US.UTF-8"}, "pl"),
            ({"LC_ALL": "C", "LANG": "pl_PL.UTF-8"}, "en"),
            ({"LC_MESSAGES": "pl_PL.UTF-8", "LANG": "en_US.UTF-8"}, "pl"),
            ({"LANG": "C.UTF-8"}, "en"),
            ({"LANG": "POSIX"}, "en"),
            ({"LANG": "de_DE.UTF-8"}, "en"),
            ({"LANG": ""}, "en"),
            ({}, "en"),
        ]
        for env, expected in cases:
            assert i18n.detect_language(env) == expected, (env, expected)


def test_set_language_handles_auto_and_unknown_codes() -> None:
    with catalogs(en=EN, pl=PL):
        assert i18n.set_language("pl") == "pl" and i18n.get_language() == "pl"
        assert i18n.set_language("klingon") == "en" and i18n.get_language() == "en"
        assert i18n.set_language("auto") in ("en", "pl")


def test_available_languages_reads_native_names() -> None:
    with catalogs(en=EN, pl=PL):
        assert i18n.available_languages() == {"en": "English", "pl": "Polski"}


def test_message_round_trips_through_json() -> None:
    m = msg("hello", name="{ł} 'x'")
    wire = json.dumps(m.to_dict(), ensure_ascii=False)
    back = Message.from_dict(json.loads(wire))
    assert back == m and back.params == {"name": "{ł} 'x'"}


def test_message_text_uses_active_or_explicit_language() -> None:
    with catalogs(en=EN, pl=PL):
        m = msg("hello", name="Ala")
        i18n.set_language("pl")
        assert m.text() == "cześć Ala"
        assert m.text("en") == "hello Ala"


def test_message_is_hashable_with_params() -> None:
    assert len({msg("a", x=1), msg("a", x=1), msg("b")}) >= 1      # hash ignores params; must not raise


def test_render_accepts_message_dict_string_and_none() -> None:
    with catalogs(en=EN):
        assert render(msg("plain")) == "plain"
        assert render({"key": "plain", "params": {}}) == "plain"
        assert render("already text") == "already text"
        assert render(None) == ""


def test_localized_error_is_english_and_carries_the_message() -> None:
    with catalogs(en=EN, pl=PL):
        i18n.set_language("pl")
        err = LocalizedError("hello", name="Ala")
        assert str(err) == "hello Ala"
        assert err.message == msg("hello", name="Ala")


def test_cli_prints_one_translated_line() -> None:
    with catalogs(en=EN, pl=PL):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert i18n.main(["--lang", "pl", "hello", "name=Jan"]) == 0
        assert out.getvalue() == "cześć Jan\n"


def test_real_catalogs_exist_and_name_themselves() -> None:
    assert (i18n.LOCALES_DIR / "en.json").exists()
    langs = i18n.available_languages()
    assert langs.get("en") == "English" and langs.get("pl") == "Polski"


if __name__ == "__main__":
    run(globals(), "i18n")
