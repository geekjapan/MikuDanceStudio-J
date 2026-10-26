//! The `mocap` area: the MoCap menu, items 291 to 296 (`src/window/command_view_menu.cpp:1550`
//! to `:1660`), the capture session, the per-frame pump and its overlay.
//!
//! State is [`State`] in egui's memory (see [`state`]): the capture stage byte (`autoRepeat`, which
//! `WM_TIMER` 101 walks from 1 to 4 every 1500 ms, `src/window/wndproc.cpp:206`), the three
//! option bytes, whose starting values are the app's (`app_defaults.cpp:199`: mirror on, lost
//! bone off, red man on), and the frame-rate counter the smoothing window reads. The running
//! session (the [`Sensor`], the per-model [`Capture`]) sits beside it under its own id, never
//! cloned: a trace holds up to 12600 samples.
//!
//! * Menu 291 starts a session (`OpenNiInit`, `src/app/oni_kinect.cpp`) or stops it
//!   (`DisableKinect`); 296 asks for an `.oni` file and starts a session on it. Both open
//!   `Data\DxOpenNI.dll` only with the Windows `dxopenni` feature; without it, or when the DLL
//!   fails, they answer [`UNAVAILABLE`] or the loader's message. [`start_session`] takes any
//!   [`Sensor`], which is how the tests run a [`mds_kinect::Fake`].
//! * [`pass`] is `FrameDriver`'s Kinect part (`src/app/frame_driver.cpp:444` to `:517`): the
//!   tracking probe and `ManageKinectRecordGate`, the stage timer, and `PumpKinectSkeleton`
//!   (`src/app/oni_skeleton_pump.cpp:471`), whose end of a recording runs [`register_capture`].
//!   The areas pass before `Editor::pump`, so the pump runs before the playback catch-up here,
//!   after it in the C++.
//! * The overlay (`PrepareFrameTextOverlay`, `src/render/overlay_producers.cpp:162`): the
//!   countdown digit of stages 1 to 3 and the recording mark of stage 4, drawn as text where the
//!   C++ draws cells of its sprite sheet. The red man (`ComposeCallbackTexture`,
//!   `src/render/frame_scene.cpp:254`) is the DLL's depth texture in the C++, an
//!   `IDirect3DTexture9` this wgpu window cannot sample; here it is a red stick figure of the
//!   smoothed joints in the same 160 x 120 inset (`ui_viewport_refresh.cpp:144`).
//!
//! Not done here, for want of a document command: the pump computes the standard pose every frame
//! but does not put it on the model (the C++ writes `trans` and `rotQuat` of the standard bones
//! without an undo entry or the edited mark, which [`Command::DragBonePose`] sets), and
//! `DisableKinect`'s `SeekModelFrame` has nothing to undo while no pose is written. The `.oni`
//! file's 30 fps cap (`fpsLimit`) is not set: nothing in the app reads the limit.
//!
//! The device path is unverified: no Kinect, no DLL, and the window handle and Direct3D 9 device
//! `OpenNIInit` takes are null (the window has no D3D9 device; [`Ctx`] has no window handle).

use super::{help, Ctx};
use crate::actions::{Action, Mode};
use egui::{Align2, Color32, FontId, Id, LayerId, Order, Pos2, Rect, Stroke};
use mds_doc::Command;
use mds_kinect::joints::{Joints, TrackedJoint, LOST};
use mds_kinect::session::record_gate;
use mds_kinect::{Bone, Capture, IkChain, PumpInput, Sensor, Session};
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};

/// What the status line says for every function that needs a sensor.
pub const UNAVAILABLE: &str = "Kinect is not available on this system";

/// `WM_TIMER` 101's interval, `command_view_menu.cpp:1570` (`0x5DC`).
pub const STAGE_TIMER_MS: u64 = 1500;
/// The stage in which the pump records (`oni_skeleton_pump.cpp`, `autoRepeat == 4`).
pub const STAGE_RECORDING: u8 = 4;

/// This build can open `Data\DxOpenNI.dll`.
const DEVICE: bool = cfg!(all(windows, feature = "dxopenni"));

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct State {
    /// `autoRepeat`: 0 idle, 1 to 3 the countdown, 4 recording.
    pub stage: u8,
    /// When the stage timer last fired (or the stage started), in [`Ctx::now_ms`].
    pub stage_since_ms: u64,
    /// `kinectMirrorEnabled` (menu 293).
    pub mirror: bool,
    /// `kinectInitLostBone` (menu 294).
    pub lost_bone: bool,
    /// `depthTextureCompositionEnabled` (menu 295).
    pub red_man: bool,
    /// `selActive`: what `OpenNIIsTracking` answered this pass; false without a session.
    pub tracking: bool,
    /// `depthDeviceEnabled`: a session runs (menu 291 checked).
    pub kinect: bool,
    /// `framesPerSecond` (`frame_driver.cpp:370` to `:386`), the start of its one-second window
    /// and the passes counted in it.
    pub fps: i32,
    pub fps_since_ms: u64,
    pub fps_frames: u32,
}

impl Default for State {
    fn default() -> State {
        State {
            stage: 0,
            stage_since_ms: 0,
            mirror: true,
            lost_bone: false,
            red_man: true,
            tracking: false,
            kinect: false,
            fps: 0,
            fps_since_ms: 0,
            fps_frames: 0,
        }
    }
}

fn state_id() -> Id {
    Id::unique("mocap-state")
}

pub fn state(egui: &egui::Context) -> State {
    egui.data(|d| d.get_temp(state_id())).unwrap_or_default()
}

pub fn update<R>(egui: &egui::Context, f: impl FnOnce(&mut State) -> R) -> R {
    egui.data_mut(|d| f(d.get_temp_mut_or_default::<State>(state_id())))
}

/// A running session: what `OpenNiInit` leaves behind.
struct Live {
    sensor: Box<dyn Sensor>,
    session: Session,
    /// The Kinect fields of each model, by slot (`currentJoints`, `skeletonHistory`, the trace).
    captures: BTreeMap<u8, Capture>,
    /// The selected model's bones as the pump left them, with its slot.
    bones: Option<(u8, Vec<Bone>)>,
}

#[derive(Clone, Default)]
struct Device(Arc<Mutex<Option<Live>>>);

fn device(egui: &egui::Context) -> Device {
    egui.data_mut(|d| {
        d.get_temp_mut_or_default::<Device>(Id::unique("mocap-device"))
            .clone()
    })
}

impl Device {
    fn with<R>(&self, f: impl FnOnce(&mut Option<Live>) -> R) -> R {
        f(&mut self.0.lock().unwrap_or_else(|e| e.into_inner()))
    }
}

const ACTIONS: &[Action] = &[
    Action::run("menu:291", kinect, false),
    Action::run("menu:292", record, false),
    Action::run("menu:293", |c| toggle(c, |s| &mut s.mirror), false),
    Action::run("menu:294", |c| toggle(c, |s| &mut s.lost_bone), false),
    Action::run("menu:295", |c| toggle(c, |s| &mut s.red_man), false),
    Action::run("menu:296", load_oni, false),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

/// Menu 291 (`:1550`): `DisableKinect` while a session runs, else `OpenNiInit` on the sensor.
fn kinect(ctx: &mut Ctx) -> Result<(), String> {
    let egui = ctx.egui.clone().ok_or(UNAVAILABLE)?;
    if state(&egui).kinect {
        stop_session(ctx);
        return Ok(());
    }
    let sensor = open(ctx, None)?;
    start_session(ctx, sensor, false)
}

/// `OpenNiInit` with the DLL: the loader's failures as the C++ words them.
#[cfg(all(windows, feature = "dxopenni"))]
fn open(ctx: &Ctx, oni: Option<&std::ffi::CStr>) -> Result<Box<dyn Sensor>, String> {
    let english = ctx.egui.as_ref().is_some_and(help::english);
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let dir = exe.parent().ok_or(UNAVAILABLE)?;
    // SAFETY: null window and device (see the module doc); the DLL keeps neither past `stop`.
    let opened = unsafe {
        mds_kinect::dll::OpenNi::start(
            dir,
            std::ptr::null_mut(),
            english,
            std::ptr::null_mut(),
            oni,
        )
    };
    match opened {
        Ok(sensor) => Ok(Box::new(sensor)),
        Err(e) => Err(match e.message() {
            Some(m) => [m.jp, m.en][usize::from(english)].to_string(),
            None => e.to_string(),
        }),
    }
}

#[cfg(not(all(windows, feature = "dxopenni")))]
fn open(_: &Ctx, _: Option<&std::ffi::CStr>) -> Result<Box<dyn Sensor>, String> {
    Err(UNAVAILABLE.into())
}

/// The rest of `OpenNiInit` (`oni_kinect.cpp`) once `OpenNIInit` succeeded on `sensor`:
/// menu 291 checked, the selected model's Kinect history reset in model mode
/// (`ModelInitMorphSlots`), the stage cleared. `from_file` is a `.oni` file
/// (`kinectCaptureActive`).
pub fn start_session(
    ctx: &mut Ctx,
    sensor: Box<dyn Sensor>,
    from_file: bool,
) -> Result<(), String> {
    let egui = ctx.egui.clone().ok_or(UNAVAILABLE)?;
    let selected = (Mode::of(ctx) == Mode::Model)
        .then(|| ctx.editor.doc.selected_model().map(|m| m.slot))
        .flatten();
    let (session, _fps_limit) = Session::start(sensor.version(), from_file, 0.0);
    let mut live = Live {
        sensor,
        session,
        captures: BTreeMap::new(),
        bones: None,
    };
    if let Some(slot) = selected {
        live.captures
            .insert(slot, Capture::new(session.version.code()));
    }
    let old = device(&egui).with(|d| d.replace(live));
    if let Some(old) = old {
        old.sensor.stop();
    }
    update(&egui, |s| (s.kinect, s.stage) = (true, 0));
    Ok(())
}

/// `DisableKinect` (`oni_kinect.cpp`): `OpenNIClean`, menus 291 and 292 unchecked, the stage
/// cleared, a physics settle.
fn stop_session(ctx: &mut Ctx) {
    let Some(egui) = ctx.egui.clone() else {
        return;
    };
    if let Some(live) = device(&egui).with(Option::take) {
        live.sensor.stop();
    }
    update(&egui, |s| {
        (s.kinect, s.stage, s.tracking) = (false, 0, false)
    });
    ctx.editor.reset_physics();
}

/// Menu 292 (`:1565`): stage 0 starts the countdown and gives every model the session's DxOpenNI
/// version, any other stage stops it. Both ways ask for a physics settle
/// (`PhysicsResetPending`); stopping also marks the scene modified. The C++ greys the item unless
/// a sensor tracks in model mode (`ManageKinectRecordGate`).
fn record(ctx: &mut Ctx) -> Result<(), String> {
    let egui = ctx.egui.clone().ok_or("no window")?;
    let now = ctx.now_ms;
    let st = state(&egui);
    if !st.tracking || Mode::of(ctx) != Mode::Model {
        return Err(UNAVAILABLE.into());
    }
    if st.stage == 0 {
        update(&egui, |s| (s.stage, s.stage_since_ms) = (1, now));
        device(&egui).with(|d| {
            if let Some(live) = d {
                let v = live.session.version.code();
                live.captures.values_mut().for_each(|c| c.version = v);
            }
        });
    } else {
        update(&egui, |s| s.stage = 0);
        ctx.editor.modified = true;
    }
    ctx.editor.reset_physics();
    Ok(())
}

/// The end of a recording (`PumpKinectSkeleton`, `oni_skeleton_pump.cpp:510` to `:524`):
/// `DisableKinect` ends the session, then `Command::RegisterKinectCapture` writes the keys of the
/// `samples` frames of the trace from `frame` on ([`mds_kinect::register`] makes them), seeks the
/// model, raises the last registered frame and asks for a settle.
pub fn register_capture(
    ctx: &mut Ctx,
    frame: u32,
    samples: u32,
    keys: Vec<mds_kinect::KeyRegistration>,
) -> Result<(), String> {
    stop_session(ctx);
    ctx.editor.apply(Command::RegisterKinectCapture {
        frame,
        samples,
        keys,
    })
}

fn toggle(ctx: &mut Ctx, flag: fn(&mut State) -> &mut bool) -> Result<(), String> {
    let egui = ctx.egui.clone().ok_or("no window")?;
    update(&egui, |s| {
        let f = flag(s);
        *f = !*f;
    });
    Ok(())
}

/// Menu 296 (`:1638`): in camera mode the C++ shows a message box instead of the file dialog;
/// otherwise the `.oni` file dialog, `DisableKinect` of a running session, and `OpenNiInit` on
/// the file.
fn load_oni(ctx: &mut Ctx) -> Result<(), String> {
    if Mode::of(ctx) == Mode::Camera {
        let en = ctx.egui.as_ref().is_some_and(help::english);
        return Err(match en {
            true => "Please select model!",
            false => "カメラ・照明モードではoniデータは読めません",
        }
        .into());
    }
    if !DEVICE {
        return Err(UNAVAILABLE.into());
    }
    let Some(path) = rfd::FileDialog::new()
        .set_title("open file data")
        .add_filter("oni files(*.oni)", &["oni"])
        .pick_file()
    else {
        return Ok(());
    };
    // The DLL takes the path in the system code page (`WideToSjis`, `0x407910`).
    let sjis = encoding_rs::SHIFT_JIS
        .encode(&path.to_string_lossy())
        .0
        .into_owned();
    let path = std::ffi::CString::new(sjis).map_err(|e| e.to_string())?;
    if ctx.egui.as_ref().is_some_and(|e| state(e).kinect) {
        stop_session(ctx);
    }
    let sensor = open(ctx, Some(&path))?;
    start_session(ctx, sensor, true)
}

/// Item id, `label_ja` and `label_en` of the inventory, mnemonics dropped.
pub const LABELS: &[(&str, &str, &str)] = &[
    ("menu:291", "Kinect", "Kinect"),
    ("menu:292", "ｷｬﾌﾟﾁｬ", "capture"),
    ("menu:293", "左右反転", "L-R reversing"),
    ("menu:294", "ﾛｽﾄﾎﾞｰﾝ初期化", "initialize lost bone"),
    ("menu:295", "赤人表示", "display red man"),
    ("menu:296", "oniﾌｧｲﾙ読込", "load oni-file"),
];

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let st = state(ui.ctx());
    let record_gate = st.tracking && Mode::of(ctx) == Mode::Model;
    for &(id, ja, en) in LABELS {
        let (checked, runs) = match id {
            "menu:291" => (st.kinect, DEVICE || st.kinect),
            "menu:292" => (st.stage != 0, record_gate),
            "menu:293" => (st.mirror, true),
            "menu:294" => (st.lost_bone, true),
            "menu:295" => (st.red_man, true),
            _ => (false, DEVICE),
        };
        let item = egui::Button::new(help::pick(ui.ctx(), ja, en)).selected(checked);
        if ui.add_enabled(runs && ctx.enabled(id), item).clicked() {
            ctx.run(id);
        }
        if id == "menu:291" || id == "menu:292" {
            ui.separator();
        }
    }
}

/// The selected model's bones and IK chains as `ModelStandardPoseSetup` reads them: the PMM
/// names (Shift-JIS, which PMX bones also get on load), the bind height of the live model, the
/// saved pose.
fn standard_bones(ctx: &Ctx) -> Option<(u8, Vec<Bone>, Vec<IkChain>)> {
    let m = ctx.editor.doc.selected_model()?;
    let live = ctx
        .editor
        .physics
        .scene
        .models
        .iter()
        .find(|p| p.slot == m.slot)?;
    let bones = m
        .bone_names
        .iter()
        .zip(&m.bone_pose)
        .zip(&live.bones)
        .map(|((name, pose), bone)| {
            let mut field = [0u8; 20];
            let n = name.raw.len().min(19);
            field[..n].copy_from_slice(&name.raw[..n]);
            Bone {
                name: field,
                bind_y: bone.position[1],
                translation: pose.translation,
                rotation: pose.rotation,
            }
        })
        .collect();
    let ik = live
        .iks
        .iter()
        .filter_map(|c| {
            Some(IkChain {
                bone: usize::try_from(c.bone_index).ok()?,
                enabled: c.enabled != 0,
            })
        })
        .collect();
    Some((m.slot, bones, ik))
}

/// One window pass of the Kinect: the frame-rate counter, `WM_TIMER` 101, the tracking probe
/// with `ManageKinectRecordGate`, `PumpKinectSkeleton`, and the overlay.
pub fn pass(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let egui = ui.ctx().clone();
    let now = ctx.now_ms;
    let model = Mode::of(ctx) == Mode::Model;
    // `frameStepPlayback`: the app steps frames only while recording a video.
    let frame_step = ctx.editor.recording.is_some();
    update(&egui, |s| {
        if now.saturating_sub(s.fps_since_ms) > 1000 {
            s.fps = s.fps_frames as i32 - 1;
            (s.fps_since_ms, s.fps_frames) = (now, 0);
        }
        s.fps_frames += 1;
        s.fps = match s.fps {
            29 => 30,
            59 => 60,
            f => f,
        };
        if (1..STAGE_RECORDING).contains(&s.stage)
            && now.saturating_sub(s.stage_since_ms) >= STAGE_TIMER_MS
        {
            s.stage += 1;
            s.stage_since_ms = now;
        }
    });

    let dev = device(&egui);
    let st = state(&egui);
    let bones = standard_bones(ctx);
    let frame = ctx.editor.current_frame();
    let (finished, joints) = dev.with(|d| {
        let Some(live) = d else {
            update(&egui, |s| s.tracking = false);
            return (None, None);
        };
        let mut st = st;
        st.tracking = false;
        if !frame_step {
            st.tracking = live.sensor.is_tracking();
            let gate = record_gate(&live.session, st.stage, st.tracking, model);
            live.sensor.draw_depth_map(gate.draw_depth_map);
            if !gate.record_menu_enabled {
                st.stage = 0;
            }
        }
        let mut finished = None;
        if let Some((slot, fresh, ik)) = bones {
            let carried = live
                .bones
                .take()
                .filter(|(s, b)| *s == slot && b.len() == fresh.len());
            let mut bones = carried.map_or(fresh, |(_, b)| b);
            let version = live.session.version.code();
            let capture = live
                .captures
                .entry(slot)
                .or_insert_with(|| Capture::new(version));
            let samples = capture.trace().len() as u32;
            let sensor = &mut live.sensor;
            let pump = capture.pump(
                PumpInput {
                    tracking: st.tracking,
                    model_mode: model,
                    frame_step_playback: frame_step,
                    fps: st.fps,
                    stage: st.stage,
                    frame,
                    mirror: st.mirror,
                    lost_bone: st.lost_bone,
                },
                |id, slot| sensor.joint(id, slot),
                &mut bones,
                &ik,
            );
            st.stage = pump.stage;
            finished = pump.finished.map(|keys| (samples, keys));
            live.bones = Some((slot, bones));
        }
        let joints = st.red_man.then(|| {
            let slot = live.bones.as_ref().map(|b| b.0)?;
            live.captures.get(&slot).map(|c| c.joints.clone())
        });
        update(&egui, |s| (s.tracking, s.stage) = (st.tracking, st.stage));
        (finished, joints.flatten())
    });
    if let Some((samples, keys)) = finished {
        if let Err(e) = register_capture(ctx, frame, samples, keys) {
            *ctx.status = e;
        }
    }

    let st = state(&egui);
    let Some(v) = ctx.editor.doc.edit.viewport else {
        return;
    };
    // `media_viewport` keeps the client rect in pixels under these names.
    let view = [v.hide_right, v.hide_top, v.hide_left, v.hide_bottom].map(|p| p as f32);
    let painter = egui.layer_painter(LayerId::new(Order::Foreground, Id::unique("mocap-overlay")));
    let ppp = egui.pixels_per_point();
    let to_points = |r: Rect| {
        Rect::from_min_max(
            (r.min.to_vec2() / ppp).to_pos2(),
            (r.max.to_vec2() / ppp).to_pos2(),
        )
    };
    if let Some((rect, text, color)) = countdown(view, st.stage) {
        let rect = to_points(rect);
        let font = FontId::proportional(rect.height() * 0.8);
        let shadow = Color32::from_black_alpha(color.a());
        painter.text(
            rect.center() + egui::vec2(1.0, 1.0),
            Align2::CENTER_CENTER,
            text,
            font.clone(),
            shadow,
        );
        painter.text(rect.center(), Align2::CENTER_CENTER, text, font, color);
    }
    if st.kinect && st.red_man && !frame_step {
        if let Some(j) = joints {
            for [a, b] in red_man(view, &j) {
                painter.line_segment(
                    [a, b].map(|p| (p.to_vec2() / ppp).to_pos2()),
                    Stroke::new(2.0, Color32::RED),
                );
            }
        }
    }
}

/// The stage overlay of `PrepareFrameTextOverlay` (`overlay_producers.cpp:162` to `:172`) in the
/// client rect `view` (`[left, top, right, bottom]`, pixels): stages 1 to 3 a 40 x 60 cell 160
/// pixels from the right with the seconds left, alpha 0xBB; stage 4 the opaque 120 x 20 recording
/// cell 200 pixels from the right.
pub fn countdown(view: [f32; 4], stage: u8) -> Option<(Rect, &'static str, Color32)> {
    let [_, top, right, _] = view;
    let at = |x: f32, y: f32, w: f32, h: f32| {
        Rect::from_min_size(Pos2::new(right - x, top + y), egui::vec2(w, h))
    };
    match stage {
        1..=3 => Some((
            at(160.0, 30.0, 40.0, 60.0),
            ["3", "2", "1"][usize::from(stage - 1)],
            Color32::from_white_alpha(0xBB),
        )),
        4 => Some((at(200.0, 120.0, 120.0, 20.0), "● REC", Color32::RED)),
        _ => None,
    }
}

/// The red man's inset (`RightViewportVertices`, `ui_viewport_refresh.cpp:144`): 160 x 120 pixels
/// from 220 to 60 pixels left of the right edge, at the top.
pub fn red_man_rect([_, top, right, _]: [f32; 4]) -> Rect {
    Rect::from_min_max(
        Pos2::new(right - 220.0, top),
        Pos2::new(right - 60.0, top + 120.0),
    )
}

/// The stick figure of the joints not lost, fitted into [`red_man_rect`] with y up, in pixels.
pub fn red_man(view: [f32; 4], joints: &Joints) -> Vec<[Pos2; 2]> {
    use TrackedJoint::*;
    const LIMBS: [(TrackedJoint, TrackedJoint); 19] = [
        (Head, Neck),
        (Neck, Torso),
        (Torso, Center),
        (Neck, LeftShoulder),
        (LeftShoulder, LeftElbow),
        (LeftElbow, LeftWrist),
        (LeftWrist, LeftHand),
        (Neck, RightShoulder),
        (RightShoulder, RightElbow),
        (RightElbow, RightWrist),
        (RightWrist, RightHand),
        (Center, LeftHip),
        (LeftHip, LeftKnee),
        (LeftKnee, LeftAnkle),
        (LeftAnkle, LeftFoot),
        (Center, RightHip),
        (RightHip, RightKnee),
        (RightKnee, RightAnkle),
        (RightAnkle, RightFoot),
    ];
    let seen = |j: TrackedJoint| Some(joints[j]).filter(|p| p[1] != LOST);
    let points: Vec<[f32; 3]> = joints.0.iter().copied().filter(|p| p[1] != LOST).collect();
    let (Some(min), Some(max)) = (
        points
            .iter()
            .copied()
            .reduce(|a, b| [a[0].min(b[0]), a[1].min(b[1]), 0.0]),
        points
            .iter()
            .copied()
            .reduce(|a, b| [a[0].max(b[0]), a[1].max(b[1]), 0.0]),
    ) else {
        return Vec::new();
    };
    let rect = red_man_rect(view).shrink(8.0);
    let scale =
        (rect.width() / (max[0] - min[0]).max(1.0)).min(rect.height() / (max[1] - min[1]).max(1.0));
    let mid = [(min[0] + max[0]) / 2.0, (min[1] + max[1]) / 2.0];
    let at =
        |p: [f32; 3]| rect.center() + egui::vec2((p[0] - mid[0]) * scale, (mid[1] - p[1]) * scale);
    LIMBS
        .iter()
        .filter_map(|&(a, b)| Some([at(seen(a)?), at(seen(b)?)]))
        .collect()
}
