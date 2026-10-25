//! "New scene" (menu 0xCD): `ResetAppState` (`src/app/reset_app_state.cpp`,
//! VA 0x0044E540) over the defaults of `MMDApp::InitDefaults`
//! (`src/app/app_defaults.cpp`).
//!
//! `ResetAppState` writes only some of the fields a save reads; the rest
//! (render size, panel width, the selected slots, the media paths, the
//! follow-camera and floor flags, the self-shadow enabled byte) keep their
//! value from before, so they are taken from the current scene. The
//! `BM_CLICK`s it sends run their handlers, which toggle the value the reset
//! just wrote ([`reset`] lists them). The head self-shadow key mode assumes
//! a device with post-processing. The refresh tail (`ReloadModels`,
//! `RefreshLightPanel`, ...) runs in `Document::apply`.

use crate::global::DEFAULT_CAMERA_CURVE;
use mds_formats::key_pool::{KeyPool, GLOBAL_KEY_CAPACITY};
use mds_formats::pmm::{
    Appearance, Background, CameraKey, GravityKey, LightKey, Physics, Pmm, SceneSettings,
    SelfShadowKey, Tail, Timeline, View, Wave,
};
use mds_formats::text::FixedSjis;

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
    // `EditMode = None`, then the clicks on the bone select, box select,
    // move and rotate radios (`command_panel_toggles.cpp`): the last one
    // leaves `ViewportEditMode::Rotate`.
    t.edit_mode = 3;
    // The model-reference click checks its box (mode 1, the bone box
    // unchecked); the bone-reference click then checks the bone box
    // (`CameraAttachmentReference::SelectedBone`), whatever the boxes were.
    t.camera_reference_mode = 2;
    // Set to 0, then toggled by the loop and return checkbox clicks
    // (`command_frame_edit.cpp`).
    t.playback_loop = 1;
    t.return_to_start = 1;
    // The play range edits are set to "%", which atol reads as 0.
    t.play_start_frame = 0;
    t.play_stop_frame = 0;
    p.wave.enabled = 0;
    p.avi.enabled = 0;
    p.avi.path.raw = [0; 256];
    p.avi.path.text.clear();
    p.picture.enabled = 0;
    // Set to 0 and 1, then toggled by the info and coordinate-axis checkbox
    // clicks (`command_frame_register.cpp`).
    p.view.fps_overlay = 1;
    p.view.ground_grid = 0;
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

fn no_path() -> FixedSjis<256> {
    FixedSjis {
        raw: [0; 256],
        text: String::new(),
    }
}

/// The scene a save right after start-up writes: `MMDApp::InitDefaults`
/// (`src/app/app_defaults.cpp`, VA 0x0040A730) over the zeroed object,
/// the global tracks that start-up creates with the heads [`reset`] also
/// builds, and the window layout of a start with no `Data\mmconfig.ini`
/// (a 640 x 360 render area, a 250-pixel panel).
pub fn startup() -> Pmm {
    let background = Background {
        offset: [0; 2],
        scale: 0.0,
        path: no_path(),
        enabled: 0,
    };
    let zero = Pmm {
        header: [0; 30],
        settings: SceneSettings {
            render_width: 640,
            render_height: 360,
            panel_width: 250,
            ..SceneSettings::default()
        },
        selected_model_slot: 0,
        models: Vec::new(),
        camera: pool(CameraKey::default()),
        camera_state: [0.0; 9],
        camera_perspective: 0,
        light: pool(LightKey::default()),
        light_state: [0.0; 6],
        selected_accessory_slot: 0,
        display_list_scroll: 0,
        accessories: Vec::new(),
        timeline: Timeline::default(),
        wave: Wave {
            enabled: 0,
            path: no_path(),
        },
        avi: background.clone(),
        picture: background,
        view: View::default(),
        physics: Physics {
            // `projectedShadowAmbient`, set by the window setup.
            projected_shadow_ambient: 1.0,
            ..Physics::default()
        },
        gravity: pool(GravityKey::default()),
        // `selfShadowEnabled`.
        self_shadow_mode: 1,
        physics_interval: 0.0,
        self_shadow: pool(SelfShadowKey::default()),
        appearance: Appearance {
            floor_visible: 1,
            ..Appearance::default()
        },
        tail: Tail::Registrations(Vec::new()),
    };
    let mut p = reset(&zero);
    // InitDefaults sets no light color and leaves `CameraFov` at the 30 of
    // the track heads, and no checkbox is clicked: `EditMode` is
    // `ViewportEditMode::None`, the loop, return, info and reference flags
    // are 0, the grid is on.
    p.light_state[..3].fill(0.0);
    p.settings.camera_fov = 30.0;
    let t = &mut p.timeline;
    t.edit_mode = 2;
    t.camera_reference_mode = 0;
    t.playback_loop = 0;
    t.return_to_start = 0;
    p.view.fps_overlay = 0;
    p.view.ground_grid = 1;
    p
}
