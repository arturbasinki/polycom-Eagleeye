---
type: Contract
title: Translation Catalog
description: "The JSON catalog format, key conventions, placeholder rules and fallback behaviour for translated text."
tags: [contract, i18n]
timestamp: 2026-10-02
---

# Translation Catalog

The contract for interface text: one JSON file per language under `eagleeye/locales/`.

## Shape

A flat JSON object of dotted semantic keys to strings, with `{name}` placeholders using `str.format`
syntax and a special `_name` key giving the language's own name.

```json
{
  "_name": "Polski",
  "tracker.on": "Śledzenie włączone",
  "light.ok": "Rozjaśniono ({before} → {after})"
}
```

## Rules

- Keys are semantic and stable; missing keys fall back to English and then to the key itself, and are
  logged once as a warning.
- Placeholders missing a supplied parameter never raise: the raw text is returned.
- Adding a language means copying `en.json`, translating values, setting `_name`, and running the
  catalog test; the app discovers the file automatically.
- A test enforces catalog conformance (same keys across languages, valid placeholders).

# Citations
- [eagleeye/locales/en.json](/eagleeye/locales/en.json)
- [eagleeye/i18n.py](/eagleeye/i18n.py)
- [tests/test_catalogs.py](/tests/test_catalogs.py)
