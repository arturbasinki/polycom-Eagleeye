---
type: UseCase
title: Control a Running Instance
description: The use case of driving the running application through the UNIX socket from CLI or tray.
tags: [control, use-case]
timestamp: 2026-10-02
---

# Control a Running Instance

## Goal

Start, show, hide, configure or quit the application from outside its window — from a terminal, the
tray, or a keyboard shortcut.

## Main flow

1. The client connects to the [control socket](/contracts/control-socket.md) at
   `$XDG_RUNTIME_DIR/eagleeye.sock` and sends one JSON line `{cmd, arg}`.
2. If the socket does not answer, either start the app (bare `eagleeye`) or report "not running" and
   raise a desktop notification (a specific command).
3. The server validates the command and applies it to the [engine](/contexts/engine.md).
4. The reply is `{ok: true, state: {...}}`, or `{ok: false, error, message}` with a localized message.

## Commands

`show`, `hide`, `privacy [on|off]`, `tracking [on|off]`, `profile <talk|presentation>`,
`autozoom [on|off]`, `select X,Y|none`, `state`, `language [auto|en|pl]`, `quit`.

## Single instance

Because taking the socket is atomic, a second launch cannot start a second engine; bare `eagleeye`
instead sends `show` to the existing instance. A socket left by a crashed process (nobody answers) is
removed.

# Citations
- [eagleeye/control.py](/eagleeye/control.py)
- [eagleeye/cli.py](/eagleeye/cli.py)
- [eagleeye/engine.py](/eagleeye/engine.py)
