---
type: Domain
title: Internationalization
description: "The subdomain of runtime translation catalogs, language detection and localized messages."
tags: [domain, supporting, i18n]
timestamp: 2026-10-02
---

# Internationalization

The supporting subdomain of presenting the interface in the user's language while keeping the codebase
English. At launch: English and Polish.

## Model

- Flat JSON **catalogs** per language (`eagleeye/locales/<code>.json`) with dotted semantic keys and
  `{name}` placeholders; `_name` is the language's own name.
- A runtime translation function with a fallback chain: selected language → English → the key itself.
- **Detection** from the environment (`LC_ALL`, `LC_MESSAGES`, `LANG`), overridable in the app
  (`auto` / `en` / `pl`) and persisted in settings.
- Messages are **data** (`{key, params}`) produced by core logic and rendered by views; the CLI/tray
  can carry them over the socket without importing the catalog.

## Where text appears

Widgets, the virtual-camera slates, the placeholder slate, the tray menu and installer output. Adding a
language is copying a catalog, translating values, setting `_name` and running the catalog test.

# Citations
- [eagleeye/i18n.py](/eagleeye/i18n.py)
- [docs/superpowers/specs/2026-10-01-i18n-english-codebase-design.md](/docs/superpowers/specs/2026-10-01-i18n-english-codebase-design.md)
