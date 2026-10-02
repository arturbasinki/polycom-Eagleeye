---
type: BusinessRule
title: UI Language Resolution
description: "How the interface language is detected, overridden, persisted and fallback-resolved."
tags: [i18n, rule, configuration]
timestamp: 2026-10-02
---

# UI Language Resolution

Business rule for choosing which language the interface shows.

## The rule

- Setting `auto` detects the language from the environment, checking `LC_ALL`, then `LC_MESSAGES`, then
  `LANG` (first non-empty wins), taking the primary subtag and mapping it to an available catalog.
- An unknown or unavailable system language falls back to **English**.
- The selection can be changed at runtime (`auto` / `en` / `pl`) and is persisted in
  [settings](/contracts/config-json.md); changing it re-renders the virtual-camera slates immediately.
- Lookup order for a key is: selected language → English → the key itself (never raising).

## Codebase counterpart

Standing project rule: code, comments, docstrings, tests, docs and commit messages are **English**;
Polish appears only in the UI catalogs and in chat. A test enforces that no Polish text leaks outside
`eagleeye/locales/pl.json` (and `README.pl.md`).

# Citations
- [eagleeye/i18n.py](/eagleeye/i18n.py)
- [docs/superpowers/specs/2026-10-01-i18n-english-codebase-design.md](/docs/superpowers/specs/2026-10-01-i18n-english-codebase-design.md)
- [tests/test_code_is_english.py](/tests/test_code_is_english.py)
