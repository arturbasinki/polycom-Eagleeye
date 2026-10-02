---
type: Policy
title: Camera Busy Retries
description: "When the camera is held by another program, the engine names the holder and retries until it is free."
tags: [policy, reliability, camera]
timestamp: 2026-10-02
---

# Camera Busy Retries

Policy for the common "Device busy" condition: another program (typically a browser that selected the
physical camera) holds `/dev/video0`.

## Behaviour

- Opening the stream fails with EBUSY; the engine records which processes hold the device (from
  `/proc/*/fd`) and reports a localized message naming them.
- A background retry loop attempts to reopen the camera every few seconds while the condition stands.
- When the browser releases the device, tracking resumes **by itself** at the previous state (a
  "Resolution" change must not turn tracking off either).

## Rationale

This is a normal usage mistake, not a fault: the user should switch the conferencing app to the
`EagleEye` virtual camera. The app must recover without a restart.

# Citations
- [eagleeye/engine.py](/eagleeye/engine.py)
- [README.md](/README.md)
