---
type: UseCase
title: Switch the UI Language
description: The use case of changing the interface language at runtime.
tags: [i18n, use-case]
timestamp: 2026-10-02
---

# Switch the UI Language

## Goal

Change the interface language at runtime without a restart.

## Main flow

1. The operator picks a language in the app (or runs `eagleeye language auto|en|pl`).
2. The engine validates the code against the available catalogs and calls `set_language`.
3. The choice is saved to [settings](/contracts/config-json.md).
4. The [virtual camera](/entities/virtual-camera.md) and the placeholder re-render their slates in the
   new language; views re-render on their next refresh.

## Alternative flows

- `auto` re-detects from the environment.
- An unknown code is rejected with an error listing the valid options.

## Note

Core logic emits localized messages as **data** (`{key, params}`) so the CLI/tray can render them in the
active language without importing the catalog.

# Citations
- [eagleeye/engine.py](/eagleeye/engine.py)
- [eagleeye/i18n.py](/eagleeye/i18n.py)
- [app.py](/app.py)
