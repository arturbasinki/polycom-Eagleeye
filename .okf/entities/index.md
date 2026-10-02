# entities

* [Director](/entities/director.md) - The decision entity that turns a filtered target estimate into camera movement commands.
* [Head Dynamics Model](/entities/head-dynamics-model.md) - The model of the real head angle over time, reconstructed from commands and measured firmware dynamics.
* [Privacy Mode](/entities/privacy-mode.md) - The entity that remembers the pre-privacy pose and tracking state and coordinates the ordered switch.
* [Tracked Person (Track)](/entities/tracked-person.md) - A person tracked across frames: stable id, world-angle position, appearance feature and lifecycle.
* [Tracker](/entities/tracker.md) - The engine entity owning the tracking thread, safety, recording and the state snapshot for views.
* [Virtual Camera](/entities/virtual-camera.md) - The entity that owns the loopback output device, the frame writer thread and the slates.
