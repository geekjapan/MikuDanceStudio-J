//! The `mocap` area: the MoCap menu, items 291 to 296 (`src/window/command_view_menu.cpp:1550`
//! to `:1660`).
//!
//! State is [`State`] in egui's memory (see [`state`]): the capture stage byte (`autoRepeat`, which
//! `WM_TIMER` 101 walks from 1 to 4 every 1500 ms, `src/window/wndproc.cpp:206`) and the three
//! option bytes. Their starting values are the app's (`app_defaults.cpp:199`): mirror on, lost
//! bone off, red man on.
//!
//! The device side is not wired: `mds-app` does not depend on `mds-kinect` yet, so no session can
//! start. Menu 291 and 296 (and 292, whose gate `ManageKinectRecordGate` needs a tracking sensor,
//! [`State::tracking`]) answer [`UNAVAILABLE`] on the status line, and `show` greys them. The
//! options 293 to 295 are plain toggles, as in the C++, and stay enabled.
//!
//! Not here, for the same reason: the per-frame pump (`PumpKinectSkeleton`), registering a
//! finished recording, and drawing the red man over the viewport.

use super::{help, Ctx};
use crate::actions::{Action, Mode};
use egui::Id;

/// What the status line says for every function that needs a sensor.
pub const UNAVAILABLE: &str = "Kinect is not available on this system";

/// `WM_TIMER` 101's interval, `command_view_menu.cpp:1570` (`0x5DC`).
pub const STAGE_TIMER_MS: u64 = 1500;
/// The stage in which the pump records (`oni_skeleton_pump.cpp`, `autoRepeat == 4`).
pub const STAGE_RECORDING: u8 = 4;

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
    /// `OpenNIIsTracking`, which the pump sets each frame.
    pub tracking: bool,
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

/// Menu 291: `OpenNiInit` or `DisableKinect` (`:1550`). No session can run yet.
fn kinect(_: &mut Ctx) -> Result<(), String> {
    Err(UNAVAILABLE.into())
}

/// Menu 292 (`:1565`): stage 0 starts the countdown, any other stage stops it. Both ways ask for
/// a physics settle (`PhysicsResetPending`); stopping also marks the scene modified. The C++
/// greys the item unless a sensor tracks in model mode (`ManageKinectRecordGate`).
fn record(ctx: &mut Ctx) -> Result<(), String> {
    let egui = ctx.egui.clone().ok_or("no window")?;
    let now = ctx.now_ms;
    let st = state(&egui);
    if !st.tracking || Mode::of(ctx) != Mode::Model {
        return Err(UNAVAILABLE.into());
    }
    if st.stage == 0 {
        update(&egui, |s| (s.stage, s.stage_since_ms) = (1, now));
    } else {
        update(&egui, |s| s.stage = 0);
        ctx.editor.modified = true;
    }
    ctx.editor.reset_physics();
    Ok(())
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
/// otherwise it would open the `.oni` file in a session.
fn load_oni(ctx: &mut Ctx) -> Result<(), String> {
    if Mode::of(ctx) == Mode::Camera {
        let en = ctx.egui.as_ref().is_some_and(help::english);
        return Err(match en {
            true => "Please select model!",
            false => "カメラ・照明モードではoniデータは読めません",
        }
        .into());
    }
    Err(UNAVAILABLE.into())
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
            "menu:292" => (st.stage != 0, record_gate),
            "menu:293" => (st.mirror, true),
            "menu:294" => (st.lost_bone, true),
            "menu:295" => (st.red_man, true),
            _ => (false, false),
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

/// `WM_TIMER` 101 and the record gate, once per pass. The timer steps the stage every
/// [`STAGE_TIMER_MS`] and stops at 4 (`wndproc.cpp:206`). Without a tracking sensor in model mode
/// the gate drops the stage to 0 (`ManageKinectRecordGate`, `oni_skeleton_pump.cpp`).
pub fn pass(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let (now, model) = (ctx.now_ms, Mode::of(ctx) == Mode::Model);
    update(ui.ctx(), |s| {
        if s.stage != 0 && !(s.tracking && model) {
            s.stage = 0;
        } else if (1..STAGE_RECORDING).contains(&s.stage)
            && now.saturating_sub(s.stage_since_ms) >= STAGE_TIMER_MS
        {
            s.stage += 1;
            s.stage_since_ms = now;
        }
    });
}
