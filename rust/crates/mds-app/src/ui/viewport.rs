//! The `viewport` area: the picture ([`crate::viewport`]), the camera navigation of
//! [`crate::navigation`] with the model-mode branches of `ConsumeRightButtonDrag` and
//! `ConsumeMiddleButtonPan` (`src/app/pump_navigation.cpp:316`, `:367`), the view buttons 402 to
//! 407, and the left-button tools of `MouseInteractionBegin` (`src/app/frame_modes.cpp:460`):
//! bone picking and box selection, the rotate and move gizmos, the corner tool rows, the view
//! tools, the coordinate-system tool and key L, and the right double click
//! (`HandleMouseActivate`, `src/window/ui_mouse_misc.cpp:284`).
//!
//! The overlay the C++ draws in `PrepareFrameSpriteOverlay` (`src/render/sprite_overlay.cpp`)
//! is drawn with egui's painter over the picture, at the C++ hit sizes. Positions are egui points
//! measured from the picture's top-left, standing in for the C++ client pixels at a `viewScale`
//! of one. The two view tools that the C++ puts in the strip above the viewport sit in its top
//! 25 points instead.
//!
//! The drag math is in pure functions on a [`Rig`], a copy of the selected model's posed bones
//! (`mds-pose` matrices of the live model) and its saved pose and selection (the document).
//! A bone drag is one undo entry: the press on a gizmo or a model tool row pushes it
//! ([`Command::BeginBoneEdit`], `PushBoneEditUndo`, `frame_modes.cpp:351`) and each move sets the
//! poses ([`Command::DragBonePose`]); the box and the pick go through [`Command::SelectBones`].
//! Camera tools edit raw document controls before deriving the view; accessory targets go through
//! [`Command::AccessoryEdit`]. The model-mode pans (the pan tool, the middle button and Shift with
//! the right button) write the view offsets ([`Command::SetViewOffset`], `camera_state[3..5]`)
//! and the derived view includes these offsets once.
//! The model-mode orbit and Ctrl distance of the right button write the camera state they move
//! (`camera_state[5..8]`, [`Command::SetCamera`]), which the PMM saves too.
//!
//! While the physics model dialog is open (`physics_scratch` of the document), the rotate and
//! move rows of the model tools drag the selected rigid body or joint of that dialog instead of
//! the bones (`BoneEditModes`, `frame_modes_bone.cpp:373`): [`Command::EditPhysicsRecord`] on the
//! [`RecordTarget`] the dialog area keeps with [`set_record_target`].

use super::{button, Ctx};
use crate::actions::Action;
use crate::editor::Editor;
use crate::navigation::{self, KeyState, Modifiers, ViewButton, WHEEL_DELTA};
use egui::{Color32, Event, MouseWheelUnit, PointerButton, Rect, Sense, Stroke, Vec2};
use mds_doc::CameraControls as Camera;
use mds_doc::{Command, ModelFile, PhysicsField};
use mds_math::{Mat4, Quat, Vec3};
use mds_render::View;

const ACTIONS: &[Action] = &[
    Action::run("ctl:402", |c| view(c, ViewButton::Front), false),
    Action::run("ctl:403", |c| view(c, ViewButton::Back), false),
    Action::run("ctl:404", |c| view(c, ViewButton::Top), false),
    Action::run("ctl:405", |c| view(c, ViewButton::Left), false),
    Action::run("ctl:406", |c| view(c, ViewButton::Right), false),
    Action::run("ctl:407", |c| view(c, ViewButton::Bottom), false),
    Action::run("key:L", cycle_coordinate, false),
    Action::run("key:Numpad0", |c| numpad(c, 0), false),
    Action::run("key:Numpad1", |c| numpad(c, 1), false),
    Action::run("key:Numpad2", |c| numpad(c, 2), false),
    Action::run("key:Numpad4", |c| numpad(c, 4), false),
    Action::run("key:Numpad5", |c| numpad(c, 5), false),
    Action::run("key:Numpad6", |c| numpad(c, 6), false),
    Action::run("key:Numpad8", |c| numpad(c, 8), false),
    Action::inline("mouse:bone-pick"),
    Action::inline("mouse:bone-box-select"),
    Action::inline("mouse:bone-drag"),
    Action::inline("mouse:record-drag"),
    Action::inline("mouse:rmb-drag"),
    Action::inline("mouse:shift-rmb-drag"),
    Action::inline("mouse:ctrl-rmb-drag"),
    Action::inline("mouse:mmb-drag"),
    Action::inline("mouse:wheel"),
    Action::inline("mouse:rmb-dblclick"),
    Action::inline("mouse:tool-view-dolly"),
    Action::inline("mouse:tool-view-pan"),
    Action::inline("mouse:tool-rotate-gizmo-x"),
    Action::inline("mouse:tool-rotate-gizmo-y"),
    Action::inline("mouse:tool-rotate-gizmo-ring"),
    Action::inline("mouse:tool-move-gizmo-horizontal"),
    Action::inline("mouse:tool-move-gizmo-vertical"),
    Action::inline("mouse:tool-move-gizmo-plane"),
    Action::inline("mouse:tool-model-local-rotate-x"),
    Action::inline("mouse:tool-model-local-rotate-y"),
    Action::inline("mouse:tool-model-local-rotate-z"),
    Action::inline("mouse:tool-model-local-translate-x"),
    Action::inline("mouse:tool-model-local-translate-y"),
    Action::inline("mouse:tool-model-local-translate-z"),
    Action::inline("mouse:tool-camera-move-x"),
    Action::inline("mouse:tool-camera-move-y"),
    Action::inline("mouse:tool-camera-move-z"),
    Action::inline("mouse:tool-camera-rotate-x"),
    Action::inline("mouse:tool-camera-rotate-y"),
    Action::inline("mouse:tool-camera-rotate-z"),
    Action::inline("mouse:tool-coordinate-cycle"),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

fn view(ctx: &mut Ctx, b: ViewButton) -> Result<(), String> {
    ctx.editor.edit_camera_controls(|camera| b.apply(camera))
}

/// `ConsumeNumpadViewPresets` runs in the stopped branch of the pump only.
fn numpad(ctx: &mut Ctx, digit: u8) -> Result<(), String> {
    if !ctx.editor.playing() {
        ctx.editor.edit_camera_controls(|camera| {
            navigation::numpad(camera, digit);
        })?;
    }
    Ok(())
}

fn camera_mode(editor: &Editor) -> bool {
    editor.doc.pmm.settings.options[0] != 0
}

/// Key L (`key_ladder.cpp:183`) and the coordinate tool (`frame_modes.cpp:363`):
/// `coordinateSystem` steps through 0 local, 1 global and, in camera mode, 2 accessory.
fn cycle_coordinate(ctx: &mut Ctx) -> Result<(), String> {
    let mut s = state(ctx);
    s.coordinate = next_coordinate(s.coordinate, camera_mode(ctx.editor));
    put(ctx, s);
    Ok(())
}

pub fn next_coordinate(c: u8, camera_mode: bool) -> u8 {
    let limit = if camera_mode { 3 } else { 2 };
    if c + 1 >= limit {
        0
    } else {
        c + 1
    }
}

/// The viewport input state the C++ keeps in the app record between passes.
#[derive(Clone, Copy, Debug, Default)]
pub struct State {
    /// `coordinateSystem` (0x9ED9C).
    pub coordinate: u8,
    /// `ViewToolDragOperation`: 1 dolly, 2 pan, or the corner tool being dragged.
    pub view_tool: u8,
    /// `InteractionDragMode` (`kDragMode` of `frame_modes.cpp:338`).
    pub drag: u8,
    /// `ViewportToolDragOrigin`: the gizmo centre when the ring drag began.
    pub origin: [i32; 2],
    /// `BoneBoxStart` while a box selection runs.
    pub box_start: Option<[i32; 2]>,
    /// `PreviousMouse`.
    pub prev: [i32; 2],
    /// `ViewportToolOperation`, for the highlight.
    pub hovered: u8,
}

fn state_id() -> egui::Id {
    egui::Id::unique("viewport-input")
}

/// The area's [`State`]; the default without an egui context.
pub fn state(ctx: &Ctx) -> State {
    ctx.egui
        .as_ref()
        .and_then(|e| e.data(|d| d.get_temp(state_id())))
        .unwrap_or_default()
}

fn put(ctx: &Ctx, s: State) {
    if let Some(e) = &ctx.egui {
        e.data_mut(|d| d.insert_temp(state_id(), s));
    }
}

/// The record the physics model dialog has selected (`selectedRigidIndex`, `selectedJointIndex`
/// and the page `physicsEditorJointPage`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RecordTarget {
    pub joint: bool,
    pub index: u32,
}

fn target_id() -> egui::Id {
    egui::Id::unique("viewport-record-target")
}

/// Sets, or with `None` clears, the record the model tool rows drag while the dialog is open.
pub fn set_record_target(egui: &egui::Context, target: Option<RecordTarget>) {
    egui.data_mut(|d| d.insert_temp(target_id(), target));
}

fn record_target(ctx: &Ctx) -> Option<RecordTarget> {
    let egui = ctx.egui.as_ref()?;
    egui.data(|d| d.get_temp::<Option<RecordTarget>>(target_id()))
        .flatten()
}

/// Applies a command; an error goes to the status line and is `false`.
fn apply_or_report(ctx: &mut Ctx, cmd: Command) -> bool {
    ctx.editor.apply(cmd).map_err(|e| *ctx.status = e).is_ok()
}

fn edit_camera(ctx: &mut Ctx, edit: impl FnOnce(&mut Camera)) {
    if let Err(e) = ctx.editor.edit_camera_controls(edit) {
        *ctx.status = e;
    }
}

/// The model-mode view offset moved by `(dx, dy)` (`ViewOffsetX` and `ViewOffsetY`, the pans of
/// `pump_navigation.cpp:330`, `:376` and `frame_modes.cpp:530`).
fn pan(ctx: &mut Ctx, dx: f32, dy: f32) {
    let s = &ctx.editor.doc.pmm.camera_state;
    apply_or_report(ctx, Command::SetViewOffset([s[3] + dx, s[4] + dy]));
}

/// The model-mode right drag without Shift (`pump_navigation.cpp:335` to `:342`): Ctrl moves
/// `CameraDistance`, else the drag turns `CameraYaw` and `CameraPitch`. The view camera turns
/// with the state and keeps its target.
fn orbit(ctx: &mut Ctx, dx: i32, dy: i32, m: Modifiers) {
    edit_camera(ctx, |camera| navigation::right_drag(camera, dx, dy, m));
}

// ---- the selected model ----------------------------------------------------------------------

/// `BoneType` values (`mds_pose::model::kind`).
mod kind {
    pub const MOVE: u8 = 1;
    pub const IK: u8 = 2;
    pub const UNDER_IK: u8 = 4;
    pub const EFFECTOR: u8 = 6;
    pub const INERT_TIP: u8 = 7;
    pub const FIXED_AXIS: u8 = 8;
}

/// `kBoneFlag*` (`mds_pose::model::flag`).
mod flag {
    pub const VISIBLE: u16 = 0x0008;
    pub const FIXED_AXIS: u16 = 0x0400;
}

/// One bone as picking and the drags read it: the live `BoneRecord` fields and the document's
/// saved pose and selection mark.
#[derive(Clone, Debug, Default)]
pub struct BoneState {
    pub parent: i32,
    pub kind: u8,
    pub flags: u16,
    pub rigid: bool,
    pub physics_disabled: bool,
    /// The rest position.
    pub position: [f32; 3],
    pub tail_bone: i32,
    /// The fixed axis (PMX).
    pub axis: [f32; 3],
    /// The PMX local X and Z axes, zero without them.
    pub local_axes: [f32; 6],
    /// The SJIS name.
    pub name: Vec<u8>,
    pub mat_init: [f32; 16],
    pub mat_world: [f32; 16],
    pub selected: bool,
    pub translation: [f32; 3],
    pub rotation: [f32; 4],
}

/// The selected model in model mode.
#[derive(Clone, Debug, Default)]
pub struct Rig {
    /// `physicsMode == 2`: a PMX model.
    pub pmx: bool,
    /// `PlaybackPhysicsMode`.
    pub physics_mode: u8,
    pub selected_bone: i32,
    pub bones: Vec<BoneState>,
}

/// The [`Rig`] of the editor's selected model, `None` in camera mode or when the live model does
/// not match the document.
pub fn rig(editor: &Editor) -> Option<Rig> {
    let doc = &editor.doc;
    let m = doc.selected_model()?;
    let i = doc.pmm.models.iter().position(|x| x.slot == m.slot)?;
    let live = editor
        .physics
        .scene
        .models
        .iter()
        .find(|x| x.slot == m.slot)?;
    if live.bones.len() != m.bone_pose.len() || m.bone_names.len() != m.bone_pose.len() {
        return None;
    }
    let pmx_bones = match doc.models.get(i) {
        Some(ModelFile::Pmx(p)) => Some(&p.bones),
        _ => None,
    };
    let bones = live
        .bones
        .iter()
        .zip(&m.bone_pose)
        .enumerate()
        .map(|(k, (b, p))| BoneState {
            parent: b.parent,
            kind: b.kind,
            flags: b.flags,
            rigid: b.has_rigid_body != 0,
            physics_disabled: b.physics_disabled != 0,
            position: b.position,
            tail_bone: b.tail_bone,
            axis: b.axis,
            local_axes: pmx_bones.and_then(|a| a.get(k)).map_or([0.0; 6], |x| {
                let [a, z] = x.local_axes;
                [a[0], a[1], a[2], z[0], z[1], z[2]]
            }),
            name: m.bone_names[k].raw.clone(),
            mat_init: b.mat_init.0,
            mat_world: b.mat_world.0,
            selected: p.flags[2] != 0,
            translation: p.translation,
            rotation: p.rotation,
        })
        .collect();
    Some(Rig {
        pmx: live.pmx,
        physics_mode: doc.pmm.physics.playback_mode,
        selected_bone: m.selection.selected_bone,
        bones,
    })
}

impl Rig {
    fn selected(&self) -> Option<&BoneState> {
        usize::try_from(self.selected_bone)
            .ok()
            .and_then(|i| self.bones.get(i))
    }

    /// The physics filter of the markers and the pick (`frame_modes.cpp:424`).
    fn simulated(&self, b: &BoneState) -> bool {
        b.rigid && (self.physics_mode == 1 || (self.physics_mode == 2 && !b.physics_disabled))
    }

    /// `IsSelectedRoot` (`frame_modes_bone.cpp:102`).
    fn selected_root(&self, i: usize, exclude_selected: bool) -> bool {
        let b = &self.bones[i];
        if !b.selected || (exclude_selected && i as i32 == self.selected_bone) {
            return false;
        }
        if b.kind != kind::MOVE && b.kind != kind::IK {
            return false;
        }
        usize::try_from(b.parent).map_or(true, |p| !self.bones.get(p).is_some_and(|p| p.selected))
    }
}

/// `BoneWorldPoint` (`frame_modes_bone.cpp:124`): the rest position through `matInit`.
pub fn world_point(b: &BoneState) -> [f32; 3] {
    let m = &b.mat_init;
    let p = b.position;
    std::array::from_fn(|j| m[j] * p[0] + m[4 + j] * p[1] + m[8 + j] * p[2] + m[12 + j])
}

/// `TransformBoneVector` (`frame_modes_bone.cpp:117`): `v` times the upper 3x3 of `m`.
fn transform(m: &[f32; 16], v: [f32; 3]) -> [f32; 3] {
    std::array::from_fn(|j| m[j] * v[0] + m[4 + j] * v[1] + m[8 + j] * v[2])
}

/// `ProjectBonePoint` (`src/render/sprite_overlay.cpp:87`) with the viewport at the origin and
/// `size` wide and high: the screen point and the clip w, `None` behind the eye (393939).
pub fn project(view: &View, size: [i32; 2], p: [f32; 3]) -> Option<([i32; 2], f32)> {
    let [x, y, _, w] = view.clip(p);
    if w <= 0.0 {
        return None;
    }
    let sx = f64::from(x / w) * f64::from(size[0]) * 0.5 + f64::from(size[0] / 2);
    let sy = f64::from(size[1] / 2) - f64::from(y / w) * f64::from(size[1]) * 0.5;
    Some(([sx as i32, sy as i32], w))
}

/// Each bone's screen point.
pub fn screen(rig: &Rig, view: &View, size: [i32; 2]) -> Vec<Option<([i32; 2], f32)>> {
    rig.bones
        .iter()
        .map(|b| project(view, size, world_point(b)))
        .collect()
}

/// A selection as [`Command::SelectBones`] takes it: `first` leads when it is marked.
pub fn selection_list(marks: &[bool], first: i32) -> Vec<u32> {
    let mut v: Vec<u32> = (0..marks.len())
        .filter(|&i| marks[i])
        .map(|i| i as u32)
        .collect();
    if let Some(k) = v.iter().position(|&b| b as i32 == first) {
        v[..=k].rotate_right(1);
    }
    v
}

/// `PickBoneAtPoint` (`frame_modes.cpp:411`): the marks and selected bone after a click at
/// `(x, y)`, `None` when nothing changes. A plain click selects the first marker within 8 pixels
/// after the selected bone (so repeated clicks cycle), Shift toggles every marker in reach.
pub fn pick(
    rig: &Rig,
    screen: &[Option<([i32; 2], f32)>],
    x: i32,
    y: i32,
    additive: bool,
) -> Option<(Vec<bool>, i32)> {
    let mut marks: Vec<bool> = rig.bones.iter().map(|b| b.selected).collect();
    let mut selected = rig.selected_bone;
    let (mut first, mut candidate, mut changed) = (None, None, false);
    for (i, b) in rig.bones.iter().enumerate() {
        if b.flags & flag::VISIBLE == 0 || !(b.kind < kind::INERT_TIP || b.kind == kind::FIXED_AXIS)
        {
            continue;
        }
        if rig.simulated(b) {
            continue;
        }
        let Some(([sx, sy], _)) = screen[i] else {
            continue;
        };
        let (dx, dy) = (sx - x, sy - y);
        if dx * dx + dy * dy >= 64 {
            continue;
        }
        if additive {
            marks[i] = !marks[i];
            if marks[i] {
                selected = i as i32;
            } else if selected == i as i32 {
                selected = -1;
            }
            changed = true;
        } else {
            first.get_or_insert(i);
            if i as i32 > selected {
                candidate = Some(i);
                break;
            }
        }
    }
    if !additive {
        if let Some(c) = candidate.or(first) {
            marks.iter_mut().for_each(|m| *m = false);
            marks[c] = true;
            selected = c as i32;
            changed = true;
        }
    }
    changed.then_some((marks, selected))
}

/// `UpdateBoneBoxSelection` (`frame_modes.cpp:298`): the marks after a box from `a` to `b`, `None`
/// when they do not change. Shift keeps the marks outside the box.
pub fn box_select(
    rig: &Rig,
    screen: &[Option<([i32; 2], f32)>],
    a: [i32; 2],
    b: [i32; 2],
    additive: bool,
) -> Option<Vec<bool>> {
    let (left, right) = (a[0].min(b[0]), a[0].max(b[0]));
    let (top, bottom) = (a[1].min(b[1]), a[1].max(b[1]));
    let marks: Vec<bool> = rig
        .bones
        .iter()
        .zip(screen)
        .map(|(bone, s)| {
            let eligible = bone.kind <= kind::EFFECTOR || bone.kind == kind::FIXED_AXIS;
            let inside = eligible
                && s.is_some_and(|([x, y], _)| x > left && x < right && y > top && y < bottom);
            inside || (additive && bone.selected)
        })
        .collect();
    let changed = marks.iter().zip(&rig.bones).any(|(m, b)| *m != b.selected);
    changed.then_some(marks)
}

// ---- the tools ---------------------------------------------------------------------------------

/// What [`tool_at`] needs of the pass.
#[derive(Clone, Copy, Debug)]
pub struct Hit {
    pub size: [i32; 2],
    pub camera_mode: bool,
    pub playing: bool,
    /// `timeline.edit_mode`: 3 rotate and 4 move show the gizmo.
    pub edit_mode: i32,
    /// The selected bone on screen, the gizmo centre.
    pub center: Option<[i32; 2]>,
    /// `InteractionDragMode != None`.
    pub dragging: bool,
}

/// `ViewportToolAtPoint` (`frame_modes.cpp:115`): the `ViewportToolAction` under `(x, y)`, 0 for
/// none. 1 and 2 are the view tools, 3..5 the rotate gizmo, 6..8 the move gizmo, 9..14 the model
/// tool rows, 15..20 the camera tool rows, 21 the coordinate tool.
pub fn tool_at(h: &Hit, x: i32, y: i32) -> u8 {
    let [w, ht] = h.size;
    // The C++ strip is `view.top - 25 .. view.top`; here it is the top of the picture.
    let mut op = 0;
    if y > 0 && y < 25 {
        if x > w - 60 && x < w - 36 {
            op = 1;
        } else if x > w - 30 && x < w - 6 {
            op = 2;
        }
    }
    if op != 0 || h.playing {
        return op;
    }
    let (fx, fy) = (x as f32, y as f32);
    let (wf, hf) = (w as f32, ht as f32);
    let column = if fx > wf - 127.0 && fx < wf - 92.0 {
        Some(0)
    } else if fx > wf - 86.0 && fx < wf - 51.0 {
        Some(1)
    } else if fx > wf - 48.0 && fx < wf - 13.0 {
        Some(2)
    } else {
        None
    };
    if let Some(c) = column {
        // `v32c` (the model rows shown) is 0 in every path of the C++: both rows.
        if fy > hf - 80.0 && fy < hf - 50.0 {
            op = if h.camera_mode { 18 + c } else { 9 + c };
        } else if fy > hf - 40.0 && fy < hf - 10.0 {
            op = if h.camera_mode { 15 + c } else { 12 + c };
        }
    }
    if let (0, Some([cx, cy])) = (op, h.center) {
        let (px, py) = (x - cx, y - cy);
        if h.edit_mode == 3 {
            let horizontal = ((px > 7 && px < 35) || (px > -35 && px < -7)) && py > -7 && py < 7;
            let vertical = ((py > 7 && py < 35) || (py > -35 && py < -7)) && px > -7 && px < 7;
            let r2 = px * px + py * py;
            op = if horizontal {
                3
            } else if vertical {
                4
            } else if r2 > 1225 && r2 < 2025 {
                5
            } else {
                0
            };
        } else if h.edit_mode == 4 {
            op = if px > 41 && px < 61 && py > -8 && py < 8 {
                6
            } else if px > -13 && px < 8 && py > -61 && py < -42 {
                7
            } else if px > -13 && px < 11 && py > -16 && py < 8 {
                8
            } else {
                0
            };
        }
    }
    if op == 0 && !h.dragging {
        let (left, top) = (wf - 120.0, hf - 105.0);
        if fx > left && fx < left + 25.0 && fy > top && fy < top + 25.0 {
            op = 21;
        }
    }
    op
}

/// `kDragMode` (`frame_modes.cpp:338`): the drag mode a press on tool `op` starts.
pub fn drag_mode(op: u8) -> u8 {
    const MODES: [u8; 21] = [
        0, 0, 0, 1, 2, 3, 7, 8, 9, 4, 5, 6, 10, 11, 12, 13, 14, 15, 16, 17, 18,
    ];
    MODES.get(usize::from(op)).copied().unwrap_or(0)
}

/// The pointer of one drag pass, in C++ pixels.
#[derive(Clone, Copy, Debug, Default)]
pub struct Pointer {
    pub prev: [i32; 2],
    pub cur: [i32; 2],
    /// The gizmo centre when the drag began (mode 3).
    pub origin: [i32; 2],
    pub shift: bool,
    pub ctrl: bool,
}

/// A bone's new saved pose.
pub type Pose = (u32, [f32; 3], [f32; 4]);

const ANGLE_BASE: f64 = 0.004999999888241291;
const COARSE: f64 = 5.0;
const FINE: f64 = 0.10000000149011612;
/// The image stores 6.28 (dbl 0x52E8E8), not 2 pi.
#[allow(clippy::approx_constant)]
const WRAP: f64 = 6.28;

/// `BoneLocalAxes` (`frame_modes_bone.cpp:318`): the local-axis basis of the selected bone, rows
/// X, Y, Z. Identity, unless the bone has PMX local axes, or is an arm, elbow, wrist or finger
/// bone, whose X follows the bone towards its tail in the XY plane.
pub fn local_axes(rig: &Rig) -> [f32; 16] {
    let mut out = Mat4::IDENTITY.0;
    let Some(b) = rig.selected() else {
        return out;
    };
    let la = b.local_axes;
    if !(la[0] == 0.0 && la[1] == 0.0 && la[2] == 0.0) && rig.pmx {
        let a = Vec3([la[0], la[1], la[2]]).normalize().0;
        let bz = Vec3([la[3], la[4], la[5]]).normalize().0;
        let c = Vec3([
            bz[1] * a[2] - bz[2] * a[1],
            bz[2] * a[0] - bz[0] * a[2],
            bz[0] * a[1] - bz[1] * a[0],
        ])
        .normalize()
        .0
        .map(|v| -v);
        let e = Vec3([
            c[2] * a[1] - c[1] * a[2],
            a[2] * c[0] - c[2] * a[0],
            a[0] * c[1] - c[0] * a[1],
        ])
        .normalize()
        .0;
        out[..3].copy_from_slice(&a);
        out[4..7].copy_from_slice(&c);
        out[8..11].copy_from_slice(&e);
    } else if arm_name(&b.name) {
        let Some(p) = usize::try_from(b.tail_bone)
            .ok()
            .and_then(|t| rig.bones.get(t))
        else {
            return out;
        };
        let dx = p.position[0] - b.position[0];
        let dy = p.position[1] - b.position[1];
        let len = (dx * dx + dy * dy).sqrt();
        out[0] = dx / len;
        out[1] = dy / len;
        out[4] = -out[1];
        out[5] = out[0];
    }
    out
}

/// The SJIS names `BoneLocalAxes` compares with (`.rdata 0x52B7F0..0x52B81C`): 右手首, 右ひじ,
/// 右腕 and the left ones whole, or 指 anywhere.
fn arm_name(name: &[u8]) -> bool {
    const NAMES: [&[u8]; 6] = [
        b"\x89\x45\x8E\xE8\x8E\xF1",
        b"\x89\x45\x82\xD0\x82\xB6",
        b"\x89\x45\x98\x72",
        b"\x8D\xB6\x8E\xE8\x8E\xF1",
        b"\x8D\xB6\x82\xD0\x82\xB6",
        b"\x8D\xB6\x98\x72",
    ];
    NAMES.contains(&name) || name.windows(2).any(|w| w == b"\x8E\x77")
}

/// Modes 1..6 of `BoneEditModes` (`frame_modes_bone.cpp:401..549`): the selected bone turned by
/// the drag, and every other selected root bone turned about its world point. Modes 1 and 2 turn
/// about the camera X and Y axes, 3 in the view plane (the angle swept about the gizmo centre),
/// 4..6 about the bone's local X, Y, Z. `rotation` is the camera's pitch, yaw, roll.
pub fn rotate(rig: &Rig, mode: u8, p: &Pointer, rotation: [f32; 3]) -> Vec<Pose> {
    let Some(b) = rig.selected() else {
        return Vec::new();
    };
    let sel = rig.selected_bone as usize;
    let scale = |base: f32| -> f32 {
        if p.shift {
            (COARSE * f64::from(base)) as f32
        } else if p.ctrl {
            (FINE * f64::from(base)) as f32
        } else {
            base
        }
    };
    let (w, i) = (&b.mat_world, &b.mat_init);
    let a_x = -f64::from(rotation[0]);
    let a_y = -f64::from(rotation[1]);
    let view_axis = |ax: f32, ay: f32, az: f32| {
        [
            w[1] * ax + w[0] * ay + w[2] * az,
            w[6] * az + w[4] * ay + w[5] * ax,
            w[10] * az + w[9] * ax + w[8] * ay,
        ]
    };
    let (ang, mut axis) = match mode {
        1 => {
            let base = (f64::from(p.prev[0] - p.cur[0]) * ANGLE_BASE) as f32;
            let axis = view_axis(
                a_x.cos() as f32,
                (a_y.sin() * a_x.sin()) as f32,
                (a_y.cos() * a_x.sin()) as f32,
            );
            (scale(base), axis)
        }
        2 => {
            let base = (f64::from(p.prev[1] - p.cur[1]) * ANGLE_BASE) as f32;
            let (ax, az) = (a_x.cos() as f32, a_y.sin() as f32);
            let axis = [
                w[0] * ax + w[2] * az,
                w[4] * ax + w[6] * az,
                w[8] * ax + w[10] * az,
            ];
            (scale(base), axis)
        }
        3 => {
            let angle = |q: [i32; 2]| {
                let a = f64::from(q[0] - p.origin[0]).atan2(f64::from(q[1] - p.origin[1]));
                (a * 0.5) as f32
            };
            let (mut ang1, mut ang2) = (angle(p.cur), angle(p.prev));
            if WRAP < f64::from(ang1) - f64::from(ang2) {
                ang2 = (f64::from(ang2) + WRAP) as f32;
            }
            if f64::from(ang1) - f64::from(ang2) < -WRAP {
                ang1 = (f64::from(ang1) + WRAP) as f32;
            }
            let axis = view_axis(
                -(a_x.sin() as f32),
                (a_y.sin() * a_x.cos()) as f32,
                (a_y.cos() * a_x.cos()) as f32,
            );
            (scale(ang1 - ang2), axis)
        }
        4..=6 => {
            let base = (f64::from(p.prev[1] - p.cur[1]) * ANGLE_BASE) as f32;
            let basis = local_axes(rig);
            let r = usize::from(mode - 4) * 4;
            let (mx, my, mz) = (basis[r], basis[r + 1], basis[r + 2]);
            let mid0 = i[8] * mz + i[0] * mx + i[4] * my;
            let mid1 = i[9] * mz + i[1] * mx + i[5] * my;
            let mid2 = i[10] * mz + i[6] * my + i[2] * mx;
            let axis = Vec3([
                w[1] * mid1 + w[0] * mid0 + w[2] * mid2,
                w[6] * mid2 + w[4] * mid0 + w[5] * mid1,
                mid2 * w[10] + w[9] * mid1 + w[8] * mid0,
            ])
            .normalize()
            .0;
            (scale(base), axis)
        }
        _ => return Vec::new(),
    };
    if b.flags & flag::FIXED_AXIS == flag::FIXED_AXIS
        && (b.kind == kind::UNDER_IK || b.kind == kind::FIXED_AXIS)
    {
        if rig.pmx {
            axis = b.axis;
        } else if let Some(t) = usize::try_from(b.tail_bone)
            .ok()
            .and_then(|t| rig.bones.get(t))
        {
            axis = Vec3(std::array::from_fn(|k| t.position[k] - b.position[k]))
                .normalize()
                .0;
        }
    }
    // The full drag angle: the instruction stream has no half-angle multiply (0x476D6D).
    let (s, c) = (ang.sin(), ang.cos());
    let dq = Quat([s * axis[0], s * axis[1], s * axis[2], c]);
    let mut out = vec![(
        sel as u32,
        b.translation,
        Quat::multiply(Quat(b.rotation), dq).0,
    )];
    let pivot = world_point(b);
    let inv = Quat([-dq.0[0], -dq.0[1], -dq.0[2], dq.0[3]]);
    for (k, ch) in rig.bones.iter().enumerate() {
        if !rig.selected_root(k, true) {
            continue;
        }
        let point = world_point(ch);
        let off = [
            point[0] - pivot[0],
            point[1] - pivot[1],
            point[2] - pivot[2],
            0.0,
        ];
        let r2 = Quat::multiply(Quat::multiply(inv, Quat(off)), dq).0;
        let t = std::array::from_fn(|j| ch.translation[j] + (r2[j] - off[j]));
        out.push((k as u32, t, Quat::multiply(Quat(ch.rotation), dq).0));
    }
    out
}

/// `ApplySelectedRootTranslation` (`frame_modes_bone.cpp:132`): `delta` through each selected
/// root bone's `matWorld` onto its translation, as poses from `base` (the poses so far).
fn move_roots(rig: &Rig, base: &mut [[f32; 3]], delta: [f32; 3]) {
    for (i, b) in rig.bones.iter().enumerate() {
        if rig.selected_root(i, false) {
            let local = transform(&b.mat_world, delta);
            base[i] = std::array::from_fn(|j| base[i][j] + local[j]);
        }
    }
}

fn moved(rig: &Rig, translations: &[[f32; 3]]) -> Vec<Pose> {
    rig.bones
        .iter()
        .zip(translations)
        .enumerate()
        .filter(|(_, (b, t))| b.translation != **t)
        .map(|(i, (b, t))| (i as u32, *t, b.rotation))
        .collect()
}

/// The camera a screen-plane move reads.
#[derive(Clone, Copy, Debug)]
pub struct Lens {
    pub rotation: [f32; 3],
    pub distance: f32,
    pub orthographic: bool,
    /// The viewport (and output) size in pixels.
    pub size: [i32; 2],
    /// The selected bone's clip w (`selectedClipW`).
    pub clip_w: f32,
}

/// Modes 7..9, `ApplyScreenPlaneBoneMove` (`frame_modes_bone.cpp:234`): the selected root bones
/// moved horizontally (7), vertically (8) or both (9) by the pointer, scaled to the depth of the
/// selected bone. The C++ "perspective" flag is set for the orthographic view.
pub fn move_screen(rig: &Rig, mode: u8, p: &Pointer, lens: &Lens) -> Vec<Pose> {
    if rig.selected().is_none() || lens.size[0] == 0 || lens.size[1] == 0 {
        return Vec::new();
    }
    let precision = if p.shift {
        10.0
    } else if p.ctrl {
        0.1
    } else {
        1.0
    };
    let clip_w = f64::from(lens.clip_w);
    let [vw, vh] = lens.size.map(f64::from);
    let mut t: Vec<[f32; 3]> = rig.bones.iter().map(|b| b.translation).collect();
    if mode == 7 || mode == 9 {
        let mut amount = f64::from(p.cur[0] - p.prev[0]);
        amount *= clip_w / vw;
        amount *= vw / vh;
        if lens.orthographic {
            amount *= -f64::from(lens.distance) * 0.9;
        }
        amount *= precision;
        let yaw = f64::from(lens.rotation[1]);
        let delta = [
            (yaw.cos() * amount) as f32,
            0.0,
            (yaw.sin() * amount) as f32,
        ];
        move_roots(rig, &mut t, delta);
    }
    if mode == 8 || mode == 9 {
        let mut amount = f64::from(p.prev[1] - p.cur[1]);
        amount *= clip_w / vh;
        if lens.orthographic {
            amount *= -f64::from(lens.distance) * 0.95;
        } else {
            amount *= 1.05;
        }
        amount *= precision;
        let pitch = -f64::from(lens.rotation[0]);
        let yaw = -f64::from(lens.rotation[1]);
        let delta = [
            (yaw.sin() * pitch.sin() * amount) as f32,
            (pitch.cos() * amount) as f32,
            (yaw.cos() * pitch.sin() * amount) as f32,
        ];
        move_roots(rig, &mut t, delta);
    }
    moved(rig, &t)
}

/// Modes 10..12, `ApplyLocalAxisBoneMove` (`frame_modes_bone.cpp:280`): the selected root bones
/// moved along X, Y or Z, the selected bone's local axis unless `coordinate` is 1 (global).
pub fn move_local(rig: &Rig, mode: u8, p: &Pointer, coordinate: u8) -> Vec<Pose> {
    let Some(b) = rig.selected() else {
        return Vec::new();
    };
    if !(10..=12).contains(&mode) {
        return Vec::new();
    }
    let step = if p.shift {
        0.5
    } else if p.ctrl {
        0.004999999888241291
    } else {
        0.05000000074505806
    };
    let d = if mode == 12 {
        p.cur[1] - p.prev[1]
    } else {
        p.prev[1] - p.cur[1]
    };
    let axis = usize::from(mode - 10);
    let mut delta = [0.0; 3];
    delta[axis] = (f64::from(d) * step) as f32;
    if coordinate != 1 {
        let basis = local_axes(rig);
        let local = std::array::from_fn(|j| basis[axis * 4 + j] * delta[axis]);
        delta = transform(&b.mat_init, local);
    }
    let mut t: Vec<[f32; 3]> = rig.bones.iter().map(|b| b.translation).collect();
    move_roots(rig, &mut t, delta);
    moved(rig, &t)
}

/// Shift, Ctrl and plain scales of the camera tool rows (`frame_modes.cpp:574`).
fn tool_scale(p: &Pointer, scales: [f32; 3]) -> f32 {
    if p.shift {
        scales[0]
    } else if p.ctrl {
        scales[1]
    } else {
        scales[2]
    }
}

/// Modes 13..15 on the camera, `ModeCameraAdjust` (`frame_modes.cpp:601`): the target moved
/// along a world axis (`global`, or with a camera parent) or along the camera's own axis.
pub fn camera_move(camera: &mut Camera, axis: usize, p: &Pointer, global: bool) {
    let step = (p.cur[1] - p.prev[1]) as f32 * tool_scale(p, [0.5, 0.005, 0.05]);
    if global {
        camera.target[axis] += step;
        return;
    }
    let [pitch, yaw, roll] = camera.rotation;
    let r = Mat4::multiply(&Mat4::rotation_z(-roll), &Mat4::rotation_x(-pitch));
    let r = Mat4::multiply(&r, &Mat4::rotation_y(-yaw)).0;
    let mut local = [0.0; 3];
    local[axis] = step;
    for j in 0..3 {
        camera.target[j] += local[0] * r[j] + local[1] * r[4 + j] + local[2] * r[8 + j] + r[12 + j];
    }
}

/// Modes 16..18 on the camera, `ModeAngleAdjust` (`frame_modes.cpp:651`): pitch, yaw or roll.
pub fn camera_turn(camera: &mut Camera, axis: usize, p: &Pointer) {
    camera.rotation[axis] += (p.cur[1] - p.prev[1]) as f32 * tool_scale(p, [0.2, 0.002, 0.02]);
}

/// `DragScale` (`frame_modes.cpp:87`).
fn drag_scale(m: Modifiers) -> f32 {
    if m.shift {
        0.5
    } else if m.ctrl {
        0.005
    } else {
        0.05
    }
}

/// `BoneEditPathActive` (`pump_navigation.cpp:110`): the camera follows the selected model, so a
/// model-mode right or middle drag only refreshes the readouts.
fn bone_edit_path(editor: &Editor) -> bool {
    let a = &editor.doc.pmm.appearance;
    a.camera_parent_model >= 0
        && a.camera_parent_model == i32::from(editor.doc.pmm.selected_model_slot)
        && a.follow_camera != 0
        && !editor.playing()
}

// ---- one pass ------------------------------------------------------------------------------------

/// The mouse of one pass over the viewport; the buttons as `PollKey` reads them.
#[derive(Clone, Copy, Debug)]
pub struct Input {
    /// The pointer in points from the picture's top-left; `None` off the window.
    pub pos: Option<[f32; 2]>,
    /// The picture's size in points.
    pub size: [f32; 2],
    pub left: KeyState,
    pub right: KeyState,
    pub middle: KeyState,
    pub right_double_click: bool,
    /// The pointer move in physical pixels, for the right and middle drags.
    pub pixels: [i32; 2],
    /// Wheel units of `WM_MOUSEWHEEL`, over the picture.
    pub wheel: f32,
    pub shift: bool,
    pub ctrl: bool,
}

/// What the overlay and the tools read of the pass: the selected model and its bones on screen.
struct Overlay {
    rig: Option<Rig>,
    screen: Vec<Option<([i32; 2], f32)>>,
    center: Option<([i32; 2], f32)>,
}

fn overlay(editor: &Editor, size: [i32; 2]) -> Overlay {
    let rig = rig(editor).filter(|_| size[0] > 0 && size[1] > 0);
    let screen = rig.as_ref().map_or_else(Vec::new, |r| {
        let view = editor.camera_view(size.map(|v| v as u32));
        screen(r, &view, size)
    });
    let center = rig
        .as_ref()
        .and_then(|r| usize::try_from(r.selected_bone).ok())
        .and_then(|i| screen.get(i).copied().flatten());
    Overlay {
        rig,
        screen,
        center,
    }
}

fn select(ctx: &mut Ctx, marks: &[bool], first: i32) {
    if let Err(e) = ctx
        .editor
        .apply(Command::SelectBones(selection_list(marks, first)))
    {
        *ctx.status = e;
    }
}

fn set_poses(ctx: &mut Ctx, poses: Vec<Pose>) {
    for (bone, translation, rotation) in poses {
        let moved = apply_or_report(
            ctx,
            Command::DragBonePose {
                bone,
                translation,
                rotation,
            },
        );
        if !moved {
            return;
        }
    }
}

/// The selected accessory's field `field` of `AccessoryEdit` moved by `delta` (radians for the
/// rotations, which the command takes in degrees).
fn accessory_step(ctx: &mut Ctx, field: u8, delta: f32) {
    let pmm = &ctx.editor.doc.pmm;
    let slot = pmm.selected_accessory_slot;
    let Some(a) = pmm.accessories.iter().find(|a| a.slot == slot) else {
        return;
    };
    let f = usize::from(field);
    let value = match f {
        0..=2 => f64::from(a.state.position[f] + delta),
        _ => f64::from(a.state.rotation[f - 3] + delta) / std::f64::consts::PI * 180.0,
    };
    if let Err(e) = ctx.editor.apply(Command::AccessoryEdit { field, value }) {
        *ctx.status = e;
    }
}

/// One pass of the viewport mouse, in the order of `MouseInteractionBegin` and `FrameDriver`
/// (`frame_driver.cpp:390..432`): the tool under the pointer, the left press and release, the box
/// and the view tools, the right and middle drags and the wheel, then the drag mode.
pub fn input(ctx: &mut Ctx, i: &Input) {
    let mut s = state(ctx);
    let size = [i.size[0] as i32, i.size[1] as i32];
    let cur = i
        .pos
        .map_or(s.prev, |[x, y]| [x.floor() as i32, y.floor() as i32]);
    let camera_mode = camera_mode(ctx.editor);
    let playing = ctx.editor.playing();
    let o = overlay(ctx.editor, size);
    let hit = Hit {
        size,
        camera_mode,
        playing,
        edit_mode: ctx.editor.doc.pmm.timeline.edit_mode,
        center: o.center.map(|c| c.0),
        dragging: s.drag != 0,
    };
    let inside = cur[0] > 0 && cur[0] < size[0] && cur[1] > 0 && cur[1] < size[1];
    let op = if i.pos.is_some() {
        tool_at(&hit, cur[0], cur[1])
    } else {
        0
    };
    s.hovered = op;
    let m = Modifiers {
        shift: i.shift,
        ctrl: i.ctrl,
    };

    // BeginOrEndViewportToolDrag (frame_modes.cpp:331).
    match i.left {
        KeyState::Pressed if i.pos.is_some() => match op {
            1 | 2 => s.view_tool = op,
            3..=20 => {
                s.drag = drag_mode(op);
                if op >= 9 {
                    s.view_tool = op;
                }
                if op == 5 {
                    s.origin = hit.center.unwrap_or(cur);
                }
                if op <= 14 && o.rig.is_some() {
                    apply_or_report(ctx, Command::BeginBoneEdit);
                }
            }
            21 => s.coordinate = next_coordinate(s.coordinate, camera_mode),
            _ if !playing && inside => match (hit.edit_mode, &o.rig) {
                (0, Some(rig)) => {
                    if let Some((marks, first)) = pick(rig, &o.screen, cur[0], cur[1], i.shift) {
                        select(ctx, &marks, first);
                    }
                }
                (1, Some(_)) => s.box_start = Some(cur),
                _ => {}
            },
            _ => {}
        },
        KeyState::Released => {
            s.view_tool = 0;
            s.drag = 0;
            s.box_start = None;
        }
        _ => {}
    }

    let held = i.left == KeyState::Held;
    let (dx, dy) = (cur[0] - s.prev[0], cur[1] - s.prev[1]);
    if held {
        if let (Some(start), Some(rig)) = (s.box_start, &o.rig) {
            if let Some(marks) = box_select(rig, &o.screen, start, cur, i.shift) {
                select(ctx, &marks, rig.selected_bone);
            }
        }
        match s.view_tool {
            1 => edit_camera(ctx, |camera| camera.distance -= dy as f32 * 0.1),
            2 if camera_mode => {
                edit_camera(ctx, |camera| navigation::middle_drag(camera, dx, dy, m))
            }
            2 => pan(ctx, -(dx as f32) * drag_scale(m), dy as f32 * drag_scale(m)),
            _ => {}
        }
    }

    // ConsumeRightButtonDrag, ConsumeMiddleButtonPan and the wheel.
    let [px, py] = i.pixels;
    let model_path = !camera_mode && bone_edit_path(ctx.editor);
    if i.right == KeyState::Held && !model_path {
        if camera_mode {
            edit_camera(ctx, |camera| navigation::right_drag(camera, px, py, m));
        } else if i.shift {
            pan(ctx, -(px as f32) * 0.1, py as f32 * 0.1);
        } else {
            orbit(ctx, px, py, m);
        }
    }
    if i.middle == KeyState::Held {
        if camera_mode {
            edit_camera(ctx, |camera| navigation::middle_drag(camera, px, py, m));
        } else {
            let k = drag_scale(m);
            pan(ctx, -(px as f32) * k, py as f32 * k);
        }
    }
    if i.wheel != 0.0 {
        if camera_mode && ctx.editor.doc.pmm.appearance.camera_parent_model >= 0 {
            edit_camera(ctx, |camera| {
                camera.target[2] += f32::from(i.wheel.round() as i16) * 0.05
            });
        } else if !model_path {
            edit_camera(ctx, |camera| {
                navigation::wheel(camera, i.wheel.round() as i16)
            });
        }
    }

    if held && s.drag != 0 {
        let p = Pointer {
            prev: s.prev,
            cur,
            origin: s.origin,
            shift: i.shift,
            ctrl: i.ctrl,
        };
        drag(ctx, &o, s, &p, size);
    }

    if i.right_double_click && !playing {
        double_click(ctx);
    }
    s.prev = cur;
    put(ctx, s);
}

/// The drag-mode dispatch of `FrameDriver` (`frame_driver.cpp:398`).
fn drag(ctx: &mut Ctx, o: &Overlay, s: State, p: &Pointer, size: [i32; 2]) {
    let mode = s.drag;
    if mode >= 13 {
        let axis = usize::from((mode - 13) % 3);
        let accessory = s.coordinate == 2 && camera_mode(ctx.editor);
        let dy = (p.cur[1] - p.prev[1]) as f32;
        if mode <= 15 {
            if accessory {
                accessory_step(ctx, axis as u8, -dy * tool_scale(p, [0.5, 0.005, 0.05]));
            } else {
                let global =
                    ctx.editor.doc.pmm.appearance.camera_parent_model >= 0 || s.coordinate == 1;
                edit_camera(ctx, |camera| camera_move(camera, axis, p, global));
            }
        } else if s.coordinate == 2 {
            accessory_step(ctx, 3 + axis as u8, dy * tool_scale(p, [0.2, 0.002, 0.02]));
        } else {
            edit_camera(ctx, |camera| camera_turn(camera, axis, p));
        }
        return;
    }
    if (mode <= 6 || mode >= 10) && ctx.editor.doc.edit.physics_scratch.is_some() {
        record_drag(ctx, mode, p);
        return;
    }
    let Some(rig) = &o.rig else {
        return;
    };
    let c = crate::scene::state_camera(&ctx.editor.doc);
    let poses = match mode {
        1..=6 => rotate(rig, mode, p, c.rotation),
        7..=9 => {
            let lens = Lens {
                rotation: c.rotation,
                distance: c.distance,
                orthographic: c.orthographic,
                size,
                clip_w: o.center.map_or(1.0, |c| c.1),
            };
            move_screen(rig, mode, p, &lens)
        }
        _ => move_local(rig, mode, p, s.coordinate),
    };
    set_poses(ctx, poses);
}

/// `EditModeRecord` (`frame_modes_bone.cpp:158`): modes 4 to 6 turn the selected record about
/// X, Y or Z and modes 10 to 12 move it, or with Shift resize a rigid body (a joint has no size).
/// Modes 1 to 3 do nothing while the dialog is open, and nothing is edited without a selected
/// record. The pointer row delta is `dy`.
fn record_drag(ctx: &mut Ctx, mode: u8, p: &Pointer) {
    let (field, axis) = match mode {
        4..=6 => (PhysicsField::Rotation, mode - 4),
        10..=12 => (PhysicsField::Position, mode - 10),
        _ => return,
    };
    let Some(RecordTarget { joint, index }) = record_target(ctx) else {
        return;
    };
    let field = match field {
        PhysicsField::Position if p.shift && !joint => PhysicsField::Size,
        f => f,
    };
    apply_or_report(
        ctx,
        Command::EditPhysicsRecord {
            joint,
            index,
            field,
            axis,
            dy: p.cur[1] - p.prev[1],
        },
    );
}

/// The right double click over the viewport (`HandleMouseActivate`, `ui_mouse_misc.cpp:284`):
/// camera mode goes to the model of the model combo; model mode switches the edit mode to bone
/// select, or from bone select to none. The cursor warps of the C++ are left out.
fn double_click(ctx: &mut Ctx) {
    let pmm = &ctx.editor.doc.pmm;
    let cmd = if camera_mode(ctx.editor) {
        let slot = pmm.selected_model_slot;
        if !pmm.models.iter().any(|m| m.slot == slot) {
            return;
        }
        Command::SelectModel(slot)
    } else if pmm.timeline.edit_mode != 0 {
        Command::SetEditMode(0)
    } else {
        Command::SetEditMode(2)
    };
    if let Err(e) = ctx.editor.apply(cmd) {
        *ctx.status = e;
    }
}

// ---- the window ------------------------------------------------------------------------------------

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    ui.horizontal(|ui| {
        for (b, a) in ViewButton::ALL.into_iter().zip(ACTIONS) {
            button(ui, ctx, a.id, b.label());
        }
    });
    let (rect, response) = ui.allocate_exact_size(ui.available_size(), Sense::click_and_drag());
    let ppp = ui.ctx().pixels_per_point();
    let (pressed, released, down) = ui.input(|i| {
        let p = &i.pointer;
        (p.primary_pressed(), p.primary_released(), p.primary_down())
    });
    let left = if pressed && response.hovered() {
        KeyState::Pressed
    } else if released {
        KeyState::Released
    } else if down && response.is_pointer_button_down_on() {
        KeyState::Held
    } else {
        KeyState::Idle
    };
    let (pos, wheel, shift, ctrl, delta) = ui.input(|i| {
        let wheel: f32 = i
            .events
            .iter()
            .filter_map(|e| match e {
                Event::MouseWheel {
                    unit: MouseWheelUnit::Line,
                    delta,
                    ..
                } => Some(delta.y * f32::from(WHEEL_DELTA)),
                // ponytail: a trackpad point counts as one WM_MOUSEWHEEL unit; tune if the
                // zoom feels wrong.
                Event::MouseWheel { delta, .. } => Some(delta.y),
                _ => None,
            })
            .sum();
        (
            i.pointer.latest_pos().map(|p| p - rect.min),
            wheel,
            i.modifiers.shift,
            i.modifiers.ctrl || i.modifiers.mac_cmd,
            i.pointer.delta(),
        )
    });
    let pixels = |v: f32| (v * ppp).round() as i32;
    let drag_of = |b| match response.dragged_by(b) {
        true => KeyState::Held,
        false => KeyState::Idle,
    };
    let i = Input {
        pos: pos.map(|p| [p.x, p.y]),
        size: [rect.width(), rect.height()],
        left,
        right: drag_of(PointerButton::Secondary),
        middle: drag_of(PointerButton::Middle),
        right_double_click: response.double_clicked_by(PointerButton::Secondary),
        pixels: [pixels(delta.x), pixels(delta.y)],
        wheel: if response.hovered() { wheel } else { 0.0 },
        shift,
        ctrl,
    };
    input(ctx, &i);

    let size = [(rect.width() * ppp) as u32, (rect.height() * ppp) as u32];
    if let Some(viewport) = ctx
        .viewport
        .as_deref_mut()
        .filter(|_| size[0] > 0 && size[1] > 0)
    {
        match viewport.show(ctx.editor, size) {
            Ok(texture) => {
                let uv = Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0));
                ui.painter().image(texture, rect, uv, Color32::WHITE);
            }
            Err(e) => *ctx.status = e,
        }
    }
    draw(ui.painter_at(rect), rect, ctx);
}

const SELECTED: Color32 = Color32::from_rgb(255, 0, 0);
const MARKED: Color32 = Color32::from_rgb(200, 0, 0);
const UNMARKED: Color32 = Color32::from_rgb(100, 100, 230);
const TOOL: Color32 = Color32::from_rgba_premultiplied(40, 40, 40, 160);
const HOT: Color32 = Color32::from_rgb(255, 160, 0);

/// The overlay of `PrepareFrameSpriteOverlay` (`sprite_overlay.cpp:233..620`): bone lines and
/// markers by edit mode, the gizmo, the box, the coordinate tool and the tool rows.
fn draw(painter: egui::Painter, rect: Rect, ctx: &Ctx) {
    let editor = &*ctx.editor;
    if editor.playing() {
        return;
    }
    let s = state(ctx);
    let size = [rect.width() as i32, rect.height() as i32];
    let o = overlay(editor, size);
    let at = |p: [i32; 2]| rect.min + Vec2::new(p[0] as f32, p[1] as f32);
    let hot =
        |op: u8| s.hovered == op || s.view_tool == op || (s.drag != 0 && drag_mode(op) == s.drag);
    let edit_mode = editor.doc.pmm.timeline.edit_mode;
    if let Some(rig) = &o.rig {
        let colour = |i: usize, b: &BoneState| match (b.selected, i as i32 == rig.selected_bone) {
            (true, true) => SELECTED,
            (true, false) => MARKED,
            _ => UNMARKED,
        };
        for (i, b) in rig.bones.iter().enumerate() {
            let shown = b.flags & flag::VISIBLE != 0 && !rig.simulated(b);
            let Some((p, _)) = o.screen[i].filter(|_| shown) else {
                continue;
            };
            let marker = match edit_mode {
                0 | 1 => matches!(b.kind, 0 | 1 | 2 | 4 | 5 | 6 | 8),
                3 | 4 => {
                    b.selected
                        && i as i32 != rig.selected_bone
                        && (b.kind == kind::MOVE || b.kind == kind::IK)
                }
                _ => false,
            };
            if edit_mode < 2 && b.kind < kind::FIXED_AXIS {
                let tail = usize::try_from(b.tail_bone).ok().filter(|&t| t > 0);
                if let Some((q, _)) = tail.and_then(|t| o.screen.get(t).copied().flatten()) {
                    painter.line_segment([at(p), at(q)], Stroke::new(1.5, colour(i, b)));
                }
            }
            if marker || (edit_mode != 2 && i as i32 == rig.selected_bone) {
                let r = Rect::from_min_size(at(p) - Vec2::splat(9.5), Vec2::splat(18.0));
                let stroke = Stroke::new(2.0, colour(i, b));
                if matches!(b.kind, kind::MOVE | kind::IK) {
                    painter.rect_stroke(r, 0.0, stroke, egui::StrokeKind::Inside);
                } else {
                    painter.circle_stroke(r.center(), 7.0, stroke);
                }
            }
        }
        if let Some((c, _)) = o.center {
            let c = at(c);
            let stroke = |op: u8, col: Color32| {
                Stroke::new(
                    if hot(op) { 5.0 } else { 3.0 },
                    if hot(op) { HOT } else { col },
                )
            };
            if edit_mode == 3 {
                for sign in [-1.0, 1.0] {
                    painter.line_segment(
                        [
                            c + Vec2::new(8.0 * sign, 0.0),
                            c + Vec2::new(34.0 * sign, 0.0),
                        ],
                        stroke(3, Color32::RED),
                    );
                    painter.line_segment(
                        [
                            c + Vec2::new(0.0, 8.0 * sign),
                            c + Vec2::new(0.0, 34.0 * sign),
                        ],
                        stroke(4, Color32::GREEN),
                    );
                }
                painter.circle_stroke(c, 40.0, stroke(5, Color32::BLUE));
            } else if edit_mode == 4 {
                let cell = |l: f32, t: f32, r: f32, b: f32| {
                    Rect::from_min_max(c + Vec2::new(l, t), c + Vec2::new(r, b))
                };
                painter.rect_stroke(
                    cell(42.0, -7.0, 60.0, 7.0),
                    0.0,
                    stroke(6, Color32::RED),
                    egui::StrokeKind::Inside,
                );
                painter.rect_stroke(
                    cell(-12.0, -60.0, 7.0, -43.0),
                    0.0,
                    stroke(7, Color32::GREEN),
                    egui::StrokeKind::Inside,
                );
                painter.rect_stroke(
                    cell(-12.0, -15.0, 10.0, 7.0),
                    0.0,
                    stroke(8, Color32::BLUE),
                    egui::StrokeKind::Inside,
                );
            }
        }
        if let Some(start) = s.box_start {
            let r = Rect::from_two_pos(at(start), at(s.prev));
            painter.rect_stroke(
                r,
                0.0,
                Stroke::new(1.0, Color32::BLACK),
                egui::StrokeKind::Inside,
            );
        }
    }
    let english = ctx.egui.as_ref().is_some_and(super::help::english);
    let text = |ja: &'static str, en: &'static str| if english { en } else { ja };
    let font = egui::FontId::proportional(11.0);
    let cell = |op: u8, r: Rect, label: &str| {
        painter.rect_filled(r, 3.0, if hot(op) { HOT } else { TOOL });
        painter.text(
            r.center(),
            egui::Align2::CENTER_CENTER,
            label,
            font.clone(),
            Color32::WHITE,
        );
    };
    let (w, h) = (rect.width(), rect.height());
    let local = |l: f32, t: f32, r: f32, b: f32| {
        Rect::from_min_max(rect.min + Vec2::new(l, t), rect.min + Vec2::new(r, b))
    };
    cell(1, local(w - 59.0, 1.0, w - 37.0, 24.0), text("距", "dist"));
    cell(2, local(w - 29.0, 1.0, w - 7.0, 24.0), text("移", "pan"));
    let coordinate = match s.coordinate {
        0 => text("ローカル", "local"),
        1 => text("グローバル", "global"),
        _ => text("アクセサリ", "accessory"),
    };
    cell(21, local(w - 119.0, h - 104.0, w - 96.0, h - 81.0), "L");
    painter.text(
        rect.min + Vec2::new(w - 92.0, h - 92.0),
        egui::Align2::LEFT_CENTER,
        coordinate,
        font.clone(),
        Color32::BLACK,
    );
    let camera = camera_mode(editor);
    let (upper, lower) = if camera { (18, 15) } else { (9, 12) };
    let columns = [(127.0, 92.0), (86.0, 51.0), (48.0, 13.0)];
    for (c, (l, r)) in columns.into_iter().enumerate() {
        let axis = ["X", "Y", "Z"][c];
        cell(
            upper + c as u8,
            local(w - l + 1.0, h - 79.0, w - r - 1.0, h - 51.0),
            &format!("{}{axis}", text("回", "R")),
        );
        cell(
            lower + c as u8,
            local(w - l + 1.0, h - 39.0, w - r - 1.0, h - 11.0),
            &format!("{}{axis}", text("移", "M")),
        );
    }
    if camera && editor.doc.pmm.appearance.camera_parent_model < 0 {
        let c = rect.center();
        painter.line_segment(
            [c - Vec2::new(8.0, 0.0), c + Vec2::new(8.0, 0.0)],
            Stroke::new(1.0, Color32::BLACK),
        );
        painter.line_segment(
            [c - Vec2::new(0.0, 8.0), c + Vec2::new(0.0, 8.0)],
            Stroke::new(1.0, Color32::BLACK),
        );
    }
}

pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}
