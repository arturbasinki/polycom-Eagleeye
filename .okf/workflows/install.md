---
type: Workflow
title: Install / Uninstall
description: The idempotent install and uninstall workflow from a clone to a desktop app.
tags: [workflow, install, product]
timestamp: 2026-10-02
---

# Install / Uninstall

The product workflow that takes a machine from a clone to a runnable desktop application, and back.

## Install steps

1. Install system packages — `v4l2loopback-dkms`, `gir1.2-ayatanaappindicator3-0.1`, `python3-venv`
   (the only `sudo` step).
2. Configure the virtual camera `EagleEye` (`/dev/video10`).
3. Create a Python virtualenv (CUDA build when an NVIDIA card is present).
4. Download the RTMO-s pose model (~36 MB).
5. Add an application-menu entry and the `eagleeye` command to `~/.local/bin`.
6. Enable the `eagleeye-placeholder` user service (keeps the virtual camera visible to Chrome).
7. Bind the Super+Shift+C shortcut to privacy mode.

## Properties

- **Idempotent**: safe to run repeatedly.
- `--dry-run` shows the steps without doing them.
- Under Secure Boot, v4l2loopback needs module signing (MOK).
- `uninstall.sh` reverses the steps; `--all` also removes the virtualenv and the kernel module.

# Citations
- [install.sh](/install.sh)
- [uninstall.sh](/uninstall.sh)
- [README.md](/README.md)
