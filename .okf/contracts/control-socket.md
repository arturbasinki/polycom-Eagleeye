---
type: Contract
title: Control Socket Protocol
description: The one-line JSON protocol over a UNIX socket that all clients use to read state and issue commands.
tags: [contract, api, control]
timestamp: 2026-10-02
---

# Control Socket Protocol

The interface exposed by the [engine](/contexts/engine.md) to every remote client. It is a UNIX
domain socket, one line of JSON each way, using only the standard library — so the tray icon, running on
the system `python3` without the project virtualenv, can speak it too.

## Request

```json
{"cmd": "<name>", "arg": "<optional>"}
```

## Reply

```json
{"ok": true, "state": { ... }}
{"ok": false, "error": "<Type: message>", "message": {"key": "...", "params": {}}}
```

## Commands

`show`, `hide`, `privacy`, `tracking`, `profile`, `autozoom`, `select`, `state`, `language`, `quit`.
For switches, `on`/`off` set explicitly and no argument toggles.

## State payload

`state` reports camera presence and error, tracking on/off, active profile, privacy, auto-zoom,
framing (side, shot, yaw, zoom goal), selection (state, id, remaining hold, frame size and people),
virtual-camera status, live performance (Hz, detection/loop/frame-age ms, moves, mode) and language.

## Non-functional properties

- A failing command never kills the server; the error is returned to the caller.
- The socket path is `$XDG_RUNTIME_DIR/eagleeye.sock` (fallback: the temp directory) and doubles as the
  [single-instance lock](/rules/single-instance.md).

# Citations
- [eagleeye/control.py](/eagleeye/control.py)
- [eagleeye/engine.py](/eagleeye/engine.py)
