//! The MikuDanceStudio application: an editor window on an `mds-doc` document, and the headless
//! frame dump.
//!
//! * [`editor`]: the open document, and the meshes, physics world, view camera and playback
//!   cursor derived from it; one pump per window pass, as the C++ `FrameDriver` runs
//!   `PlaybackCatchup` and `PhysicsFrame`.
//! * [`file`]: reading and writing PMM files through the document, and the
//!   unsaved-changes prompts (`src/window/command_impl.cpp`, `src/window/wndproc.cpp`).
//! * [`actions`]: the action table, keyed by the ids of `tools/ui_inventory/inventory.tsv`.
//! * [`ui`]: one file per inventory area, with the contract the UI slices follow.
//! * [`viewport`]: the window's picture, drawn by `mds-render` into a texture that egui shows.
//! * [`scene`]: the meshes, accessories and picture of a document, and the frame and stage that
//!   draw it in a physics state.
//! * [`playback`]: the play, stop and loop timing of `src/app/playback_catchup.cpp`,
//!   `src/app/playback_state.cpp` and the play button (`src/window/command_frame_edit.cpp`).
//! * [`navigation`]: the camera-mode viewport input of `src/app/pump_navigation.cpp`, the
//!   wheel (`src/window/ui_scroll_mouse.cpp`) and the view buttons 402 to 407.
//! * [`dump`]: `--frame-dump`, the twin of the C++ `--mds-frame-dump`.

pub mod actions;
pub mod dump;
pub mod editor;
pub mod file;
pub mod navigation;
pub mod playback;
pub mod scene;
pub mod ui;
pub mod viewport;
