//! The `edit` area: the Edit menu and the frame-line keys I, K, U and J.
//!
//! Done: the select-all menus (217, 218, 220, 237 to 241; `SelectFrameGroup`,
//! `src/window/frame_line_edit.cpp:540`, and `src/window/command_file_menu.cpp:1964` to `:2029`),
//! the frame-line menus and keys (255 to 258; `command_view_menu.cpp:861`,
//! `src/app/key_ladder.cpp:127` to `:141`) and the rotation reset (302, `command_view_menu.cpp:1864`).
//!
//! Missing, because `mds-doc` has no [`Command`] for them yet (the menu items are drawn greyed
//! out): delete unused frames (222), the multiply menus (242, 251, 252, key R), the center
//! position bias (219, key D), paste at a different frame (250, key F) and the numeric input
//! dialog (300). The report of the slice names the Command each one needs.
//!
//! The menus are gated by mode as the C++ grays them (`RestorePlaybackMenus`,
//! `src/app/playback_state.cpp:83`; `src/app/reset_app_state.cpp:489`): the model-mode ones in
//! camera mode, the camera-mode ones in model mode. During playback they are all grayed
//! (`DisablePlaybackMenus`, `playback_state.cpp:67`), which `needs_document` covers.

use super::{button, Ctx};
use crate::actions::Action;
use mds_doc::{Command, SelectAll};

const ACTIONS: &[Action] = &[
    Action::run("menu:217", select_bone, true),
    Action::run("menu:218", select_display, true),
    Action::run("menu:220", select_morph, true),
    Action::run("menu:237", select_camera, true),
    Action::run("menu:238", select_light, true),
    Action::run("menu:239", select_self_shadow, true),
    Action::run("menu:240", select_gravity, true),
    Action::run("menu:241", select_accessory, true),
    Action::run("menu:255", insert_bone_camera, true),
    Action::run("menu:256", delete_bone_camera, true),
    Action::run("menu:257", insert_morph_light, true),
    Action::run("menu:258", delete_morph_light, true),
    Action::run("key:I", insert_bone_camera, true),
    Action::run("key:K", delete_bone_camera, true),
    Action::run("key:U", insert_morph_light, true),
    Action::run("key:J", delete_morph_light, true),
    Action::run("menu:302", reset_rotation, true),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

fn camera_mode(ctx: &Ctx) -> bool {
    ctx.editor.doc.pmm.settings.options[0] != 0
}

/// Which edit mode a menu item is enabled in.
#[derive(Clone, Copy, PartialEq)]
enum Mode {
    Any,
    Model,
    Camera,
}

impl Mode {
    fn allows(self, camera: bool) -> bool {
        match self {
            Mode::Any => true,
            Mode::Model => !camera,
            Mode::Camera => camera,
        }
    }
}

fn gated(ctx: &Ctx, mode: Mode, id: &str) -> Result<(), String> {
    match mode.allows(camera_mode(ctx)) {
        true => Ok(()),
        false => Err(format!("{id}: not in this mode")),
    }
}

fn select(ctx: &mut Ctx, id: &str, what: SelectAll) -> Result<(), String> {
    let mode = match what {
        SelectAll::Bone | SelectAll::Display | SelectAll::Morph => Mode::Model,
        _ => Mode::Camera,
    };
    gated(ctx, mode, id)?;
    ctx.editor.apply(Command::SelectAll(what))
}

fn select_bone(ctx: &mut Ctx) -> Result<(), String> {
    select(ctx, "menu:217", SelectAll::Bone)
}

fn select_display(ctx: &mut Ctx) -> Result<(), String> {
    select(ctx, "menu:218", SelectAll::Display)
}

fn select_morph(ctx: &mut Ctx) -> Result<(), String> {
    select(ctx, "menu:220", SelectAll::Morph)
}

fn select_camera(ctx: &mut Ctx) -> Result<(), String> {
    select(ctx, "menu:237", SelectAll::Camera)
}

fn select_light(ctx: &mut Ctx) -> Result<(), String> {
    select(ctx, "menu:238", SelectAll::Light)
}

fn select_self_shadow(ctx: &mut Ctx) -> Result<(), String> {
    select(ctx, "menu:239", SelectAll::SelfShadow)
}

fn select_gravity(ctx: &mut Ctx) -> Result<(), String> {
    select(ctx, "menu:240", SelectAll::Gravity)
}

fn select_accessory(ctx: &mut Ctx) -> Result<(), String> {
    select(ctx, "menu:241", SelectAll::Accessory)
}

fn frame_line(ctx: &mut Ctx, morph: bool, insert: bool) -> Result<(), String> {
    ctx.editor.apply(Command::FrameLine { morph, insert })
}

fn insert_bone_camera(ctx: &mut Ctx) -> Result<(), String> {
    frame_line(ctx, false, true)
}

fn delete_bone_camera(ctx: &mut Ctx) -> Result<(), String> {
    frame_line(ctx, false, false)
}

fn insert_morph_light(ctx: &mut Ctx) -> Result<(), String> {
    frame_line(ctx, true, true)
}

fn delete_morph_light(ctx: &mut Ctx) -> Result<(), String> {
    frame_line(ctx, true, false)
}

/// Menu 302: the camera's pitch, yaw and roll to 0, or the selected bone's rotation to identity
/// (a bone-edit undo entry first; nothing when no bone is selected).
fn reset_rotation(ctx: &mut Ctx) -> Result<(), String> {
    let pmm = &ctx.editor.doc.pmm;
    if camera_mode(ctx) {
        let s = pmm.camera_state;
        return ctx.editor.apply(Command::SetCamera {
            position: [s[0], s[1], s[2]],
            rotation: [0.0; 3],
            distance: s[5],
            fov: pmm.settings.camera_fov,
            perspective: pmm.camera_perspective != 0,
        });
    }
    let model = pmm
        .models
        .iter()
        .find(|m| m.slot == pmm.selected_model_slot)
        .ok_or("no model")?;
    let Ok(bone) = u32::try_from(model.selection.selected_bone) else {
        return Ok(());
    };
    let translation = model
        .bone_pose
        .get(bone as usize)
        .ok_or("no such bone")?
        .translation;
    ctx.editor.apply(Command::SetBonePose {
        bone,
        translation,
        rotation: [0.0, 0.0, 0.0, 1.0],
    })
}

/// The Edit menu in the order of `res/templates/menu/menus.rc`; an empty id is a separator.
const MENU: &[(&str, &str, Mode)] = &[
    ("menu:300", "bone camera numeric input", Mode::Any),
    ("menu:302", "bone camera angle initialize", Mode::Any),
    ("", "", Mode::Any),
    ("menu:222", "delete unused frame", Mode::Model),
    ("", "", Mode::Any),
    ("menu:237", "select all camera frame", Mode::Camera),
    ("menu:238", "select all light frame", Mode::Camera),
    ("menu:239", "select all self shadow frame", Mode::Camera),
    ("menu:240", "select all gravity frame", Mode::Camera),
    ("menu:241", "select all accessory frame", Mode::Camera),
    ("", "", Mode::Any),
    (
        "menu:242",
        "multiply of camera frame position-angle",
        Mode::Camera,
    ),
    ("", "", Mode::Any),
    ("menu:217", "select all bone frame", Mode::Model),
    ("menu:220", "select all facial frame", Mode::Model),
    ("menu:218", "select all disp/IK/OP frame", Mode::Model),
    ("", "", Mode::Any),
    ("menu:250", "paste to different frame (F)", Mode::Any),
    ("", "", Mode::Any),
    (
        "menu:255",
        "insert frame line (bone or camera) (I)",
        Mode::Any,
    ),
    (
        "menu:256",
        "delete frame line (bone or camera) (K)",
        Mode::Any,
    ),
    (
        "menu:257",
        "insert frame line (facial or light) (U)",
        Mode::Any,
    ),
    (
        "menu:258",
        "delete frame line (facial or light) (J)",
        Mode::Any,
    ),
    ("", "", Mode::Any),
    (
        "menu:251",
        "multiply of bone frame position-angle (R)",
        Mode::Model,
    ),
    ("menu:252", "multiply of facial expression", Mode::Model),
    ("", "", Mode::Any),
    ("menu:219", "apply center position bias", Mode::Model),
];

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let camera = camera_mode(ctx);
    for &(id, label, mode) in MENU {
        match id {
            "" => {
                ui.separator();
            }
            _ => {
                ui.add_enabled_ui(mode.allows(camera), |ui| button(ui, ctx, id, label));
            }
        }
    }
}

pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}
