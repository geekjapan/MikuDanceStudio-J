//! Viewport navigation in camera mode, on the camera the view is drawn from: the PMM camera
//! state that the C++ keeps at app+0x310 (pitch, yaw, roll), app+0x334 (position, the point
//! looked at) and app+0xA08DC (distance), which is [`Camera`]'s `rotation`, `target` and
//! `distance`.
//!
//! Ported: `ConsumeRightButtonDrag`, `ConsumeMiddleButtonPan`, `ConsumeNumpadViewPresets` and
//! the left and right arrows of `ConsumeArrowKeyNavigation` (`src/app/pump_navigation.cpp`), the
//! wheel (`HandleMouseWheel`, `src/window/ui_scroll_mouse.cpp`) and the view buttons 402 to 407
//! (`ResetViewPreset` and `ResetViewAndReloadModels`, `src/window/command_frame_edit.cpp`).
//! Only the camera-mode branches: the model-mode view offsets and the camera parented to a model
//! come with the input modes of slice `app`.

use mds_doc::CameraControls as Camera;
use mds_math::Mat4;

/// The numpad angles as the image stores them (`kNumpadHalfPi` 0x3FC90FF9, `kNumpadPi`
/// 0x40490FD8), a few ulps off the rounded constants that the view buttons use.
const NUMPAD_HALF_PI: f32 = f32::from_bits(0x3FC9_0FF9);
const NUMPAD_PI: f32 = f32::from_bits(0x4049_0FD8);
/// `kNumpadDistance` and the distance of the view buttons.
const PRESET_DISTANCE: f32 = -45.0;
/// The arrow hold threshold (x64 .rdata 0x7FF7CB552D0C).
const REPEAT_THRESHOLD: f32 = 0.4;
/// One wheel notch of `WM_MOUSEWHEEL`.
pub const WHEEL_DELTA: i16 = 120;

/// The modifier keys as the pump reads them.
#[derive(Clone, Copy, Debug, Default)]
pub struct Modifiers {
    pub shift: bool,
    pub ctrl: bool,
}

/// Right-button drag (x86 0x470BF5): Ctrl dollies, anything else orbits (in camera mode Shift
/// does not pan: that branch is model mode only). `dx`, `dy` are the cursor move of the pass in
/// pixels.
pub fn right_drag(camera: &mut Camera, dx: i32, dy: i32, m: Modifiers) {
    const PAN: f32 = 0.1;
    const ROTATE: f32 = 0.01;
    if m.ctrl {
        camera.distance -= dy as f32 * PAN;
    } else {
        camera.rotation[1] -= dx as f32 * ROTATE;
        camera.rotation[0] -= dy as f32 * ROTATE;
    }
}

/// Middle-button pan of the free camera (`PanCameraPosition`, x64 0x44DCAC): the move turned by
/// `RotZ(-roll) * RotX(pitch) * RotY(yaw)` into the camera position, with z subtracted.
pub fn middle_drag(camera: &mut Camera, dx: i32, dy: i32, m: Modifiers) {
    let scale = if m.shift {
        0.5
    } else if m.ctrl {
        0.005
    } else {
        0.05
    };
    let [pitch, yaw, roll] = camera.rotation;
    let r = Mat4::multiply(&Mat4::rotation_x(pitch), &Mat4::rotation_y(yaw));
    let r = Mat4::multiply(&Mat4::rotation_z(-roll), &r).0;
    let (rx, ry) = (-(dx as f32), dy as f32);
    let p = &mut camera.target;
    p[0] += rx * r[0] * scale + ry * r[4] * scale + r[12];
    p[1] += rx * r[1] * scale + ry * r[5] * scale + r[13];
    p[2] -= rx * r[2] * scale + ry * r[6] * scale + r[14];
}

/// The wheel over the viewport with no camera parent model (x64 0x7FF7CB45F410): the distance
/// moves by `wheel * 0.05`, `wheel` in `WM_MOUSEWHEEL` units ([`WHEEL_DELTA`] a notch).
pub fn wheel(camera: &mut Camera, wheel: i16) {
    camera.distance += f32::from(wheel) * 0.05;
}

fn preset(camera: &mut Camera, pitch: f32, yaw: f32) {
    camera.rotation = [pitch, yaw, 0.0];
    camera.distance = PRESET_DISTANCE;
}

/// A numpad view preset (`ApplyNumpadCameraPreset`). Keys 3, 7 and 9 have none (`false`).
pub fn numpad(camera: &mut Camera, digit: u8) -> bool {
    let (pitch, yaw) = match digit {
        2 => (0.0, 0.0),
        4 => (0.0, NUMPAD_HALF_PI),
        6 => (0.0, -NUMPAD_HALF_PI),
        8 => (0.0, NUMPAD_PI),
        5 => (-NUMPAD_HALF_PI, 0.0),
        0 | 1 => (NUMPAD_HALF_PI, 0.0),
        _ => return false,
    };
    preset(camera, pitch, yaw);
    true
}

/// The view buttons of the camera panel.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ViewButton {
    /// 402.
    Front,
    /// 403.
    Back,
    /// 404.
    Top,
    /// 405.
    Left,
    /// 406.
    Right,
    /// 407, the reset (`ResetViewAndReloadModels`).
    Bottom,
}

impl ViewButton {
    pub const ALL: [ViewButton; 6] = [
        ViewButton::Front,
        ViewButton::Back,
        ViewButton::Top,
        ViewButton::Left,
        ViewButton::Right,
        ViewButton::Bottom,
    ];

    /// The button's label in the English UI.
    pub fn label(self) -> &'static str {
        match self {
            ViewButton::Front => "front",
            ViewButton::Back => "back",
            ViewButton::Top => "top",
            ViewButton::Left => "left",
            ViewButton::Right => "right",
            ViewButton::Bottom => "bottom",
        }
    }

    /// The camera-mode branch: rotation and distance -45, with the rounded `f32` constants
    /// `3.1415927f` and `1.5707964f`.
    pub fn apply(self, camera: &mut Camera) {
        use std::f32::consts::{FRAC_PI_2, PI};
        let (pitch, yaw) = match self {
            ViewButton::Front => (0.0, 0.0),
            ViewButton::Back => (0.0, PI),
            ViewButton::Top => (-FRAC_PI_2, 0.0),
            ViewButton::Left => (0.0, FRAC_PI_2),
            ViewButton::Right => (0.0, -FRAC_PI_2),
            ViewButton::Bottom => (FRAC_PI_2, 0.0),
        };
        preset(camera, pitch, yaw);
    }
}

/// A key as `PollKeyboardStates` sees it from one pass to the next.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KeyState {
    Idle,
    Pressed,
    Released,
    Held,
}

impl KeyState {
    pub fn of(was_down: bool, down: bool) -> KeyState {
        match (was_down, down) {
            (false, false) => KeyState::Idle,
            (false, true) => KeyState::Pressed,
            (true, false) => KeyState::Released,
            (true, true) => KeyState::Held,
        }
    }
}

/// The hold timer of the arrow keys (`keyRepeatTimer`, app+0x9E650), shared by every arrow.
#[derive(Clone, Copy, Debug, Default)]
pub struct Repeat {
    timer: f32,
}

impl Repeat {
    /// Whether a left or right arrow in `state` steps a frame this pass; `dt` is the frame delta
    /// (`deltaTime`). A press steps and re-arms the timer; a hold adds `dt` and, past 0.4 s,
    /// steps every pass without re-arming. With Ctrl the press jumps to a keyframe instead
    /// (not ported) and the hold does nothing.
    pub fn step(&mut self, state: KeyState, ctrl: bool, dt: f32) -> bool {
        match state {
            KeyState::Pressed if !ctrl => {
                self.timer = 0.0;
                true
            }
            KeyState::Held if !ctrl => {
                self.timer += dt;
                self.timer > REPEAT_THRESHOLD
            }
            _ => false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn camera() -> Camera {
        Camera {
            target: [1.0, 10.0, -2.0],
            rotation: [0.1, 0.2, 0.0],
            distance: -45.0,
            fov_deg: 30.0,
            orthographic: false,
        }
    }

    const PLAIN: Modifiers = Modifiers {
        shift: false,
        ctrl: false,
    };

    #[test]
    fn right_drag_orbits_and_ctrl_dollies() {
        let mut c = camera();
        right_drag(&mut c, 30, -20, PLAIN);
        assert_eq!(c.rotation, [0.1 - -20.0 * 0.01, 0.2 - 30.0 * 0.01, 0.0]);
        assert_eq!(c.distance, -45.0);
        // Shift orbits too in camera mode.
        let mut s = camera();
        right_drag(
            &mut s,
            30,
            -20,
            Modifiers {
                shift: true,
                ctrl: false,
            },
        );
        assert_eq!(s.rotation, c.rotation);
        let mut c = camera();
        right_drag(
            &mut c,
            30,
            -20,
            Modifiers {
                shift: false,
                ctrl: true,
            },
        );
        assert_eq!(
            (c.rotation, c.distance),
            (camera().rotation, -45.0 - -20.0 * 0.1)
        );
    }

    #[test]
    fn middle_drag_pans_along_the_view_with_z_flipped() {
        // Unrotated: x moves against the drag, y with it, z not at all.
        let mut c = Camera {
            rotation: [0.0; 3],
            ..camera()
        };
        middle_drag(&mut c, 10, 4, PLAIN);
        assert_eq!(c.target, [1.0 - 10.0 * 0.05, 10.0 + 4.0 * 0.05, -2.0]);
        // Yaw a quarter turn: row 0 of RotY is (0, 0, -1), and the z term is subtracted.
        let mut c = Camera {
            rotation: [0.0, std::f32::consts::FRAC_PI_2, 0.0],
            ..camera()
        };
        middle_drag(
            &mut c,
            10,
            0,
            Modifiers {
                shift: true,
                ctrl: false,
            },
        );
        assert!((c.target[0] - 1.0).abs() < 1e-5);
        assert!(
            (c.target[2] - (-2.0 - 10.0 * 0.5)).abs() < 1e-5,
            "{:?}",
            c.target
        );
        let mut c = Camera {
            rotation: [0.0; 3],
            ..camera()
        };
        middle_drag(
            &mut c,
            10,
            0,
            Modifiers {
                shift: false,
                ctrl: true,
            },
        );
        assert_eq!(c.target[0], 1.0 - 10.0 * 0.005);
    }

    #[test]
    fn a_wheel_notch_moves_the_distance_by_six() {
        let mut c = camera();
        wheel(&mut c, WHEEL_DELTA);
        assert_eq!(c.distance, -39.0);
        wheel(&mut c, -2 * WHEEL_DELTA);
        assert_eq!(c.distance, -51.0);
    }

    #[test]
    fn numpad_presets_use_the_stored_angles() {
        let mut c = camera();
        assert!(numpad(&mut c, 8));
        assert_eq!(c.rotation[1].to_bits(), 0x4049_0FD8);
        assert_eq!(
            (c.rotation[0], c.rotation[2], c.distance),
            (0.0, 0.0, -45.0)
        );
        let mut b = camera();
        ViewButton::Back.apply(&mut b);
        assert_eq!(b.rotation[1].to_bits(), 0x4049_0FDB);
        assert_ne!(b.rotation, c.rotation);
        for (digit, rotation) in [
            (2, [0.0, 0.0]),
            (4, [0.0, f32::from_bits(0x3FC9_0FF9)]),
            (6, [0.0, -f32::from_bits(0x3FC9_0FF9)]),
            (5, [-f32::from_bits(0x3FC9_0FF9), 0.0]),
            (0, [f32::from_bits(0x3FC9_0FF9), 0.0]),
            (1, [f32::from_bits(0x3FC9_0FF9), 0.0]),
        ] {
            let mut c = camera();
            assert!(numpad(&mut c, digit));
            assert_eq!(
                c.rotation,
                [rotation[0], rotation[1], 0.0],
                "numpad {digit}"
            );
        }
        for digit in [3, 7, 9] {
            let mut c = camera();
            assert!(!numpad(&mut c, digit));
            assert_eq!(c.rotation, camera().rotation);
        }
    }

    #[test]
    fn view_buttons_use_the_rounded_angles() {
        for (button, pitch, yaw) in [
            (ViewButton::Front, 0, 0),
            (ViewButton::Top, 0xBFC9_0FDB, 0),
            (ViewButton::Left, 0, 0x3FC9_0FDB),
            (ViewButton::Right, 0, 0xBFC9_0FDB),
            (ViewButton::Bottom, 0x3FC9_0FDB, 0),
        ] {
            let mut c = camera();
            button.apply(&mut c);
            assert_eq!(
                (c.rotation.map(f32::to_bits), c.distance),
                ([pitch, yaw, 0], -45.0),
                "{button:?}"
            );
        }
    }

    #[test]
    fn arrows_repeat_every_pass_after_four_tenths() {
        let mut r = Repeat::default();
        assert!(r.step(KeyState::Pressed, false, 0.1));
        // 0.2 + 0.2 is 0.4 exactly, which is not past the threshold.
        let held: Vec<bool> = (0..4).map(|_| r.step(KeyState::Held, false, 0.2)).collect();
        assert_eq!(held, [false, false, true, true]);
        // A press re-arms; a release does not step.
        assert!(r.step(KeyState::Pressed, false, 0.1));
        assert!(!r.step(KeyState::Held, false, 0.1));
        assert!(!r.step(KeyState::Released, false, 0.1));
        // Ctrl: no step and no repeat.
        assert!(!r.step(KeyState::Pressed, true, 0.1));
        assert!(!r.step(KeyState::Held, true, 1.0));
    }

    #[test]
    fn key_states_follow_the_poll() {
        assert_eq!(KeyState::of(false, true), KeyState::Pressed);
        assert_eq!(KeyState::of(true, true), KeyState::Held);
        assert_eq!(KeyState::of(true, false), KeyState::Released);
        assert_eq!(KeyState::of(false, false), KeyState::Idle);
    }
}
