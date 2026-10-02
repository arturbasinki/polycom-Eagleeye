---
type: Contract
title: eagleeye CLI
description: The command-line surface for starting the app and sending commands to a running engine.
tags: [contract, cli, control]
timestamp: 2026-10-02
---

# `eagleeye` CLI

The command-line contract for starting the app and controlling a running instance.

## Usage

```
eagleeye                         start (or show the window of a running instance)
eagleeye privacy [on|off]        privacy (no argument: toggle)
eagleeye tracking [on|off]       auto-tracking
eagleeye profile talk            tracking profile
eagleeye autozoom [on|off]       automatic zoom (no argument: toggle)
eagleeye select X,Y | none       follow the person at a frame point, or back to automatic
eagleeye state                   state as JSON
eagleeye show | hide | quit
eagleeye language [auto|en|pl]   UI language
```

## Behaviour

- With a command, the CLI sends it over the [control socket](/contracts/control-socket.md) and prints
  the JSON reply; a failed command also raises a desktop notification.
- With no command, if an instance is running it sends `show`; otherwise it starts the application
  (loading Flet and the models only on a real start).
- Without installation it runs as `.venv/bin/python -m eagleeye.cli`.

# Citations
- [eagleeye/cli.py](/eagleeye/cli.py)
- [install.sh](/install.sh)
