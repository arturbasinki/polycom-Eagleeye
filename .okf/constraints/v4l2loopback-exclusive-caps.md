---
type: Constraint
title: v4l2loopback exclusive_caps
description: The loopback device must be declared with exclusive_caps=1 for browsers to treat it as a camera.
tags: [constraint, virtual-camera, desktop]
timestamp: 2026-10-02
---

# v4l2loopback `exclusive_caps=1`

A configuration constraint on the external [v4l2loopback](/external/v4l2loopback.md) module: the
`EagleEye` device must be declared with `exclusive_caps=1` so Chrome/Meet recognise it as a **camera**.

## Consequences

- Do not set it to 0 — browsers then stop treating the device as a camera.
- Chrome enumerates cameras once at startup and only sees a loopback device while something is writing
  to it, which is why a [placeholder service](/domains/virtual-camera-and-privacy.md) writes a slate
  from login and the app writes continuously.
- The device must stay in the `capture` state (something writing) for receivers to keep it.

# Citations
- [install.sh](/install.sh)
- [README.md](/README.md)
