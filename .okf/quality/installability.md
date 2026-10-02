---
type: QualityAttribute
title: Installability
description: The non-functional requirement that installation and launch feel like a normal desktop application.
tags: [quality, install, nfr]
timestamp: 2026-10-02
---

# Installability

The quality attribute that the application must install and start like an ordinary desktop app, not via
CLI magic.

## How it is met

- A single idempotent `./install.sh` performs all setup, with one `sudo` step for system packages.
- Afterwards the app starts from the GNOME menu with an icon, and `eagleeye` is on `PATH`.
- `--dry-run` makes the installer inspectable; results are shellcheck- and test-covered.
- A placeholder user service means the virtual camera is present in the browser's camera list even
  before the app starts, so no post-install ritual is needed.
- `uninstall.sh` reverses everything (`--all` removes the venv and the kernel module).

## Why

The product is for the owner first, then anyone who clones the repo. Moving to wider distribution later
should not require re-architecting the deployment; a one-time install then a normal desktop app is the
target.

# Citations
- [install.sh](/install.sh)
- [tests/test_install.py](/tests/test_install.py)
- [docs/superpowers/specs/2026-09-23-productization-design.md](/docs/superpowers/specs/2026-09-23-productization-design.md)
