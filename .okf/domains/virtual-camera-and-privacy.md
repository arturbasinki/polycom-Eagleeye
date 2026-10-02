---
type: Domain
title: Virtual Camera and Privacy
description: The subdomain that publishes the framed image on a virtual camera and provides privacy mode and the placeholder slate.
tags: [domain, supporting, virtual-camera, privacy]
timestamp: 2026-10-02
---

# Virtual Camera and Privacy

The subdomain that publishes the application's image as a camera and hides the room on demand. It is a
supporting domain, but it is what makes EagleEye usable by conferencing apps at all.

## Virtual camera

The app writes the framed image to the [v4l2loopback](/external/v4l2loopback.md) device named
`EagleEye` in a fixed format. It never re-encodes to JPEG for the output, subsamples colour only at the
end, and repeats the last frame at a steady rate so receivers see an even stream regardless of camera
pauses. When there is no image it writes a **slate**.

## Privacy

Privacy mode is a coordinated change across the system: the output switches to a privacy slate
**immediately**, tracking is turned off, and the head is tilted down. Disabling restores the previous
pose and then the live image — the order matters. See
[the privacy use case](/use-cases/enable-privacy.md) and [invariant](/invariants/tracking-off-in-privacy.md).

## Placeholder

Because Chrome only recognises a loopback camera while something writes to it, a small `--user` service
(the *placeholder*) writes a "not running" slate from login and yields the device to the app. This
keeps `EagleEye` in the camera list of a browser that started before the app.

# Citations
- [eagleeye/vcam.py](/eagleeye/vcam.py)
- [eagleeye/privacy.py](/eagleeye/privacy.py)
- [eagleeye/placeholder.py](/eagleeye/placeholder.py)
