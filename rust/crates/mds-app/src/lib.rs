//! The MikuDanceStudio application: a window that opens a PMM read-only and plays it with
//! physics and the C++ camera navigation, and the headless frame dump.
//!
//! * [`viewer`]: the scene state, a PMM and its `mds-physics` world at the current frame. The
//!   document of slice `doc` replaces it.
//! * [`playback`]: the play, stop and loop timing of `src/app/playback_catchup.cpp`,
//!   `src/app/playback_state.cpp` and the play button (`src/window/command_frame_edit.cpp`).
//! * [`navigation`]: the camera-mode viewport input of `src/app/pump_navigation.cpp`, the
//!   wheel (`src/window/ui_scroll_mouse.cpp`) and the view buttons 402 to 407.
//! * [`dump`]: `--frame-dump`, the twin of the C++ `--mds-frame-dump`.

pub mod dump;
pub mod navigation;
pub mod playback;
pub mod viewer;
