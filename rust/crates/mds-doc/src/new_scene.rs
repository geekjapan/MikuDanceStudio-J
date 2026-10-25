//! "New scene" (menu 0xCD): `ResetAppState` (`src/app/reset_app_state.cpp`,
//! VA 0x0044E540) over the defaults of `MMDApp::InitDefaults`
//! (`src/app/app_defaults.cpp`).
//!
//! `ResetAppState` writes only some of the fields a save reads; the rest
//! (render size, panel width, the selected slots, the media paths, the
//! follow-camera and floor flags, the self-shadow enabled byte) keep their
//! value from before, so they are taken from the current scene. The
//! `BM_CLICK`s it sends to checkboxes run their handlers in the C++; their
//! effects are not ported. The head self-shadow key mode assumes a device
//! with post-processing.

use crate::global::DEFAULT_CAMERA_CURVE;
use mds_formats::key_pool::{KeyPool, GLOBAL_KEY_CAPACITY};
use mds_formats::pmm::{CameraKey, GravityKey, LightKey, Pmm, SelfShadowKey, Tail};

fn pool<K: mds_formats::key_pool::Key>(head: K) -> KeyPool<K> {
    KeyPool::new(GLOBAL_KEY_CAPACITY, vec![head]).expect("one head fits")
}

/// The scene a save right after "new scene" writes, from the scene before.
pub fn reset(old: &Pmm) -> Pmm {
    let mut p = old.clone();
    p.header = [0; 30];
    p.header[..24].copy_from_slice(b"Polygon Movie maker 0002");
    // CameraMode = 1, then the six panels expanded; CameraFov 30, then 45.
    p.settings.options = [1; 7];
    p.settings.camera_fov = 45.0;
    p.models.clear();
    p.accessories.clear();
    p.camera = pool(CameraKey {
        distance: -45.0,
        eye: [0.0, 10.0, 0.0],
        parent_model: -1,
        interpolation: DEFAULT_CAMERA_CURVE,
        fov: 30,
        ..CameraKey::default()
    });
    // position, view offset, distance, pitch, yaw, roll
    p.camera_state = [0.0, 10.0, 0.0, 0.0, 0.0, -45.0, 0.0, 0.0, 0.0];
    p.camera_perspective = 0;
    p.light = pool(LightKey {
        color: [0.602; 3],
        direction: [-0.5, -1.0, 0.5],
        ..LightKey::default()
    });
    p.light_state = [0.602, 0.602, 0.602, -0.5, -1.0, 0.5];
    let t = &mut p.timeline;
    t.current_frame = 0;
    t.start_frame = 0;
    t.last_registered_frame = 0;
    t.edit_mode = 0;
    t.camera_reference_mode = 0;
    t.playback_loop = 0;
    t.return_to_start = 0;
    // The play range edits are set to "%", which atol reads as 0.
    t.play_start_frame = 0;
    t.play_stop_frame = 0;
    p.wave.enabled = 0;
    p.avi.enabled = 0;
    p.avi.path.raw = [0; 256];
    p.avi.path.text.clear();
    p.picture.enabled = 0;
    p.view.fps_overlay = 0;
    p.view.ground_grid = 1;
    p.view.ground_shadow = 1;
    p.view.fps_limit = 60.0;
    p.view.capture_mode = 0;
    let ph = &mut p.physics;
    ph.accessory_render_order = 1;
    ph.projected_shadow_blend = 1;
    ph.playback_mode = 2;
    ph.gravity_magnitude = 9.8;
    ph.gravity_noise = 10;
    ph.gravity_direction = [0.0, -1.0, 0.0];
    ph.gravity_noise_enabled = 0;
    p.gravity = pool(GravityKey {
        noise: 10,
        acceleration: 9.8,
        direction: [0.0, -1.0, 0.0],
        ..GravityKey::default()
    });
    // ShadowDistance; RefreshSelfShadowPanel then reads the same value back
    // from the head key.
    p.physics_interval = 0.01125;
    p.self_shadow = pool(SelfShadowKey {
        mode: crate::POST_PROCESS_SHADOW_MODE,
        distance: 0.01125,
        ..SelfShadowKey::default()
    });
    let a = &mut p.appearance;
    a.outline_color = [0; 3];
    a.camera_parent_model = -1;
    a.camera_parent_bone = 0;
    a.camera_attachment_basis = [0.0; 16];
    for i in [0, 5, 10, 15] {
        a.camera_attachment_basis[i] = 1.0;
    }
    // The goto-frame edit is set to "0".
    a.max_frame = 0;
    p.tail = Tail::Registrations(Vec::new());
    p
}
