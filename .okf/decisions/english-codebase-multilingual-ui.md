---
type: Decision
title: "English Codebase, Multilingual UI"
description: The decision to make the codebase English and move all user-visible text into runtime catalogs.
tags: [decision, i18n, process]
timestamp: 2026-10-02
---

# English Codebase, Multilingual UI

Decision: before public release, make the repository, README and code **English**, and make the user
interface **multilingual** (English and Polish at launch) with runtime switching.

## Context

The project was written in Polish: docstrings, identifiers, profiles and error messages. The user's
native language is Polish, but the project was going public. Polish text appeared in five roles:
user-visible text, core logic messages, identifiers/comments, docs and commit messages.

## Decision

- Code, comments, docstrings, tests, docs and commit messages are **English** — a standing project rule.
- User-visible text moves into **runtime JSON catalogs** with a fallback chain, detected from `$LANG`
  and switchable in the app.
- Core logic emits **messages as data** (`{key, params}`) that views render, so the CLI/tray can localize
  without importing catalogs.
- A test enforces "no Polish text outside `eagleeye/locales/pl.json` and `README.pl.md`".

## Consequences

- Behaviour is unchanged: the full existing test suite must pass after every stage.
- Adding a language is a data-only change (copy a catalog, translate, set `_name`, run the test).
- `README.md` (English) and `README.pl.md` are both maintained.

# Citations
- [docs/superpowers/specs/2026-10-01-i18n-english-codebase-design.md](/docs/superpowers/specs/2026-10-01-i18n-english-codebase-design.md)
- [eagleeye/i18n.py](/eagleeye/i18n.py)
- [tests/test_code_is_english.py](/tests/test_code_is_english.py)
