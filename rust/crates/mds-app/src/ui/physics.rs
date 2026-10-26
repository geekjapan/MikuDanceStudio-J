//! The `physics` area: the Physics menu (`MDS_CMD_*` 264 to 275 and 285, `src/window/
//! command_view_menu.cpp:1029` to `:1222` and `:1437`) and the two physics check boxes (499, 530)
//! with the `]` key (`src/app/pump_edit_keys.cpp:222`).
//!
//! Here: display bodies (264, [`segments`]: the wire frames of `DrawPhysicsCollisionDebug`,
//! `src/render/debug_geometry.cpp:272`, painted over the viewport by [`pass`]), the playtime
//! on/off mode switch (271, [`mds_physics::PhysicsScene::always_on_off`], which the C++ keeps in
//! `playbackAlwaysOnOffMode` and never saves), the gravity dialog (266, the dialog area's
//! `IDD_GRAVITY`), reset (268), select physical bones (273), select physics ON frames (274,
//! `SelectPhysicsOnBoneKeys`, `src/model/model_keyframe_edit.cpp:730`), the ON/OFF frame
//! conversion dialog (275), the about box (267) and the automatic interpolation check box (530,
//! `Command::SetAutoInterpolation`; `]` flips it).
//!
//! The mode radios 265, 269, 270 and 272 are [`Command::SetPhysicsMode`] (`PlaybackPhysicsMode`,
//! `command_view_menu.cpp:1048` to `:1110`), after which the editor calls
//! [`mds_physics::PhysicsScene::set_physics_mode`] (`ModelKinematicSync` of every model); modes 1
//! to 3 request a settle, which the document sets. Item 270 is greyed while playing
//! (`DisablePlaybackMenus`, `src/app/playback_state.cpp:77`), in camera mode
//! (`ui_model_reload.cpp:474`) and for a PMX model (`ui_model_reload.cpp:553`); the other three
//! are never greyed. Menu 285 is [`Command::SetFloorVisible`] (`command_view_menu.cpp:1437`),
//! after which the editor sets the ground body's collision flags
//! ([`mds_physics::PhysicsScene::set_floor_visible`]) and keeps the state for every world it
//! builds. Check box 499 is
//! [`Command::SetPhysicsCheckbox`] (`EditState::physics_checkbox`, which "register" stores
//! negated as `physicsDisabled`, `src/model/model_keyframe_edit.cpp:277`).
//!
//! The bodies are drawn at the pose Bullet has for them ([`world_poses`], from
//! [`mds_physics::PhysicsScene::body_poses`]); [`body_matrix`], the `BuildFollowMatrix` of the
//! bone's `mat_init`, is the same for the bone followers and the fallback for a body that has no
//! Bullet body.

use super::{help, viewport, Ctx};
use crate::actions::{self, Action, Mode};
use crate::editor::Editor;
use egui::{Color32, Id, LayerId, Order, Rect, Stroke};
use mds_doc::{Command, Track};
use mds_math::{Mat4, Quat};
use mds_pose::model::{Model, Rigid};
use std::collections::HashMap;

const ACTIONS: &[Action] = &[
    Action::run("menu:265", |c| set_mode(c, 1), false),
    Action::run("menu:269", |c| set_mode(c, 2), false),
    Action::run("menu:270", trace_mode, true).in_mode(Mode::Model),
    Action::run("menu:272", |c| set_mode(c, 0), false),
    Action::run("menu:285", toggle_floor, false),
    Action::run("ctl:499", toggle_checkbox, false),
    Action::run("menu:264", toggle_bodies, false),
    // Not greyed while playing: `DisablePlaybackMenus` (`playback_state.cpp:67` to `:77`) leaves
    // 266 enabled.
    Action::run("menu:266", gravity, false),
    Action::run("menu:267", about, false),
    Action::run("menu:268", reset, false),
    Action::run("menu:271", toggle_playback_on_off, false),
    Action::run("menu:273", select_physics_bones, false).in_mode(Mode::Model),
    Action::run("menu:274", select_physics_on_frames, false).in_mode(Mode::Model),
    Action::run("menu:275", frame_conversion, true).in_mode(Mode::Model),
    Action::run("ctl:530", toggle_auto_interpolation, false),
    Action::run("key:]", toggle_auto_interpolation, true),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

// ---- display bodies (264) ----------------------------------------------------------------------

/// `rigidBodyDisplayEnabled`, which every document load clears (`pmm_load_v2.cpp:2164`,
/// `reset_app_state.cpp:83`): reset whenever the editor built a new world, as the view options are.
#[derive(Clone, Default)]
struct Bodies {
    opens: usize,
    on: bool,
}

fn bodies_id() -> Id {
    Id::unique("physics-bodies")
}

fn bodies_on(egui: &egui::Context, editor: &Editor) -> bool {
    egui.data_mut(|d| {
        let s = d.get_temp_mut_or_insert_with(bodies_id(), || Bodies {
            opens: editor.physics_opens,
            on: false,
        });
        if s.opens != editor.physics_opens {
            *s = Bodies {
                opens: editor.physics_opens,
                on: false,
            };
        }
        s.on
    })
}

fn set_bodies(egui: &egui::Context, editor: &Editor, on: bool) {
    bodies_on(egui, editor);
    egui.data_mut(|d| d.get_temp_mut_or_default::<Bodies>(bodies_id()).on = on);
}

fn window(ctx: &Ctx) -> Result<egui::Context, String> {
    ctx.egui.clone().ok_or_else(|| "no window".to_string())
}

/// Menu 264: the flag flips (`command_view_menu.cpp:1029`).
fn toggle_bodies(ctx: &mut Ctx) -> Result<(), String> {
    let egui = window(ctx)?;
    let on = bodies_on(&egui, ctx.editor);
    set_bodies(&egui, ctx.editor, !on);
    Ok(())
}

/// Whether the bodies are displayed now.
pub fn bodies_shown(egui: &egui::Context, editor: &Editor) -> bool {
    bodies_on(egui, editor)
}

// ---- the wire frames ---------------------------------------------------------------------------

/// One line of the wire frame, in picture points from the top-left.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Segment {
    pub from: [i32; 2],
    pub to: [i32; 2],
    /// The body has mass (`getInvMass() != 0`), which the C++ draws in red; the others
    /// (the bone followers) in yellow-green.
    pub dynamic: bool,
}

const RING: usize = 16;

/// `BuildFollowMatrix` (`mds-physics`): `Rz * Rx * Ry * T(rigid)`, then `* T(bone position) *
/// bone world` for the bone the body follows (a body with no bone and a mode follows the centre
/// bone, as `ModelDynamicReseat` seats it).
pub fn body_matrix(model: &Model, r: &Rigid) -> Mat4 {
    let rz_rx = Mat4::multiply(
        &Mat4::rotation_z(r.rotation[2]),
        &Mat4::rotation_x(r.rotation[0]),
    );
    let mut o = Mat4::multiply(&rz_rx, &Mat4::rotation_y(r.rotation[1]));
    let [x, y, z] = r.position;
    o = Mat4::multiply(&o, &Mat4::translation(x, y, z));
    let bone = match usize::try_from(r.bone) {
        Ok(b) => Some(b),
        Err(_) if r.mode > 0 => Some(model.center_bone),
        Err(_) => None,
    };
    if let Some(b) = bone.and_then(|b| model.bones.get(b)) {
        let [x, y, z] = b.position;
        o = Mat4::multiply(&o, &Mat4::translation(x, y, z));
        o = Mat4::multiply(&o, &b.mat_init);
    }
    o
}

fn ring(plane: usize, radius: f32, centre: [f32; 3]) -> Vec<[f32; 3]> {
    (0..=RING)
        .map(|i| {
            let a = std::f32::consts::TAU * i as f32 / RING as f32;
            let (s, c) = (a.sin() * radius, a.cos() * radius);
            let mut p = centre;
            p[plane] += s;
            p[(plane + 1) % 3] += c;
            p
        })
        .collect()
}

fn sphere(radius: f32, centre: [f32; 3]) -> Vec<Vec<[f32; 3]>> {
    (0..3).map(|plane| ring(plane, radius, centre)).collect()
}

/// The lines of a shape in the body's frame: `DrawSphere`, `DrawBox` and `DrawCapsule`
/// (`debug_geometry.cpp:70` to `:123`). `size` is the PMD rigid size: the radius, the half
/// extents, and the radius and the length of the capsule's cylinder.
fn shape_lines(shape: u8, size: [f32; 3]) -> Vec<Vec<[f32; 3]>> {
    match shape {
        0 => sphere(size[0], [0.0; 3]),
        1 => {
            let corner = |i: usize| -> [f32; 3] {
                std::array::from_fn(|k| if i >> k & 1 == 1 { size[k] } else { -size[k] })
            };
            let mut edges = Vec::new();
            for a in 0..8 {
                for k in 0..3 {
                    if a >> k & 1 == 0 {
                        edges.push(vec![corner(a), corner(a | 1 << k)]);
                    }
                }
            }
            edges
        }
        2 => {
            let (r, h) = (size[0], size[1] * 0.5);
            let mut lines = sphere(r, [0.0, -h, 0.0]);
            lines.extend(sphere(r, [0.0, h, 0.0]));
            for (x, z) in [(r, 0.0), (-r, 0.0), (0.0, r), (0.0, -r)] {
                lines.push(vec![[x, -h, z], [x, h, z]]);
            }
            lines
        }
        _ => Vec::new(),
    }
}

fn transform(m: &Mat4, p: [f32; 3]) -> [f32; 3] {
    std::array::from_fn(|c| p[0] * m.0[c] + p[1] * m.0[4 + c] + p[2] * m.0[8 + c] + m.0[12 + c])
}

/// The pose of every Bullet body, by model slot and rigid index (`PhysicsScene::body_poses`):
/// origin and rotation. A body of a shape the loaders build no Bullet body for has none.
pub fn world_poses(editor: &Editor) -> HashMap<(u8, usize), Mat4> {
    let Ok(poses) = editor.physics.body_poses() else {
        return HashMap::new();
    };
    let mut out = HashMap::new();
    for (model, bodies) in editor.physics.scene.models.iter().zip(poses) {
        for (i, pose) in bodies.into_iter().enumerate() {
            if let Some((o, q)) = pose {
                let mut m = Mat4::rotation_quaternion(Quat(q));
                m.0[12..15].copy_from_slice(&o);
                out.insert((model.slot, i), m);
            }
        }
    }
    out
}

/// The wire frames of every rigid body of the world, projected into a picture `size` points wide
/// and high from the editor's view camera (`DrawPhysicsCollisionDebug` draws with the depth test
/// off, so none is hidden). Bodies of the loaders' unsupported shapes have no Bullet body and no
/// lines.
pub fn segments(editor: &Editor, size: [i32; 2]) -> Vec<Segment> {
    if size[0] <= 0 || size[1] <= 0 {
        return Vec::new();
    }
    let view = crate::scene::view(&editor.doc, &editor.camera, size.map(|v| v as u32));
    let poses = world_poses(editor);
    let mut out = Vec::new();
    for model in &editor.physics.scene.models {
        for (i, r) in model.rigids.iter().enumerate() {
            let m = poses
                .get(&(model.slot, i))
                .copied()
                .unwrap_or_else(|| body_matrix(model, r));
            let dynamic = r.static_flag == 0 && r.mass > 0.0;
            for line in shape_lines(r.shape, r.size) {
                let points: Vec<_> = line
                    .iter()
                    .map(|&p| viewport::project(&view, size, transform(&m, p)))
                    .collect();
                for w in points.windows(2) {
                    if let [Some((from, _)), Some((to, _))] = w {
                        out.push(Segment {
                            from: *from,
                            to: *to,
                            dynamic,
                        });
                    }
                }
            }
        }
    }
    out
}

/// The picture the viewport area allocated last pass: the largest widget of the background layer
/// inside the window that senses click and drag (the timeline's strip is larger but runs off the
/// window).
// ponytail: the viewport area publishes no rect, so it is found among the previous pass's widgets;
// an overlay hook in the viewport area replaces this.
fn picture_rect(egui: &egui::Context) -> Option<Rect> {
    let window = egui.content_rect().expand(1.0);
    egui.viewport(|v| {
        v.prev_pass
            .widgets
            .layers()
            .filter(|(l, _)| l.order == Order::Background)
            .flat_map(|(_, w)| w.iter())
            .filter(|w| w.sense.senses_click() && w.sense.senses_drag())
            .map(|w| w.rect)
            .filter(|r| window.contains_rect(*r))
            .max_by(|a, b| a.area().total_cmp(&b.area()))
    })
}

const DYNAMIC: Color32 = Color32::from_rgb(255, 0, 0);
const FOLLOWER: Color32 = Color32::from_rgb(155, 255, 0);

fn paint_bodies(egui: &egui::Context, editor: &Editor) {
    let Some(rect) = picture_rect(egui) else {
        return;
    };
    let layer = LayerId::new(Order::Background, Id::unique("physics-bodies-layer"));
    // Above the panels' layer, below the windows.
    egui.move_to_top(layer);
    let painter = egui.layer_painter(layer).with_clip_rect(rect);
    let size = [rect.width() as i32, rect.height() as i32];
    let at = |p: [i32; 2]| rect.min + egui::vec2(p[0] as f32, p[1] as f32);
    for s in segments(editor, size) {
        let colour = if s.dynamic { DYNAMIC } else { FOLLOWER };
        painter.line_segment([at(s.from), at(s.to)], Stroke::new(1.0, colour));
    }
}

// ---- the other rows ----------------------------------------------------------------------------

/// Menu 266 (`command_view_menu.cpp:1117`): the dialog area's gravity setting.
fn gravity(ctx: &mut Ctx) -> Result<(), String> {
    actions::run(ctx, "dlg:IDD_GRAVITY")
}

/// Menu 275 (`command_view_menu.cpp:1222`): the dialog area's ON/OFF frame conversion.
fn frame_conversion(ctx: &mut Ctx) -> Result<(), String> {
    actions::run(ctx, "dlg:IDD_PHYSICS_FRAME_CONVERSION")
}

/// The text of the about box (`command_view_menu.cpp:1135`).
pub const ABOUT: &str = "Bullet Physics Library Ver.2.75\n\nhttp://www.bulletphysics.com/";

fn about_id() -> Id {
    Id::unique("physics-about")
}

/// Menu 267.
fn about(ctx: &mut Ctx) -> Result<(), String> {
    window(ctx)?.data_mut(|d| d.insert_temp(about_id(), true));
    Ok(())
}

/// Menu 268 (`MDS_CMD_RESET_PHYSICS_BODIES`, `command_view_menu.cpp:1154`).
fn reset(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.reset_physics();
    Ok(())
}

/// Menus 265, 269 and 272 (`command_view_menu.cpp:1048`, `:1066`, `:1098`): the playback physics
/// mode; the editor then runs every model's `ModelKinematicSync`.
fn set_mode(ctx: &mut Ctx, mode: u8) -> Result<(), String> {
    ctx.editor.apply(Command::SetPhysicsMode(mode))
}

/// Whether the selected model is a PMX (`ModelRecord::physicsMode == 2`).
fn selected_pmx(editor: &Editor) -> bool {
    let Some(m) = editor.doc.selected_model() else {
        return false;
    };
    editor
        .physics
        .scene
        .models
        .iter()
        .any(|x| x.slot == m.slot && x.pmx)
}

/// Menu 270 (`command_view_menu.cpp:1082`), greyed for a PMX model.
fn trace_mode(ctx: &mut Ctx) -> Result<(), String> {
    if selected_pmx(ctx.editor) {
        return Err("menu:270: not for a PMX model".into());
    }
    set_mode(ctx, 3)
}

/// Menu 285 (`command_view_menu.cpp:1437`): the floor flag flips.
fn toggle_floor(ctx: &mut Ctx) -> Result<(), String> {
    let on = ctx.editor.doc.pmm.appearance.floor_visible != 0;
    ctx.editor.apply(Command::SetFloorVisible(!on))
}

/// Check box 499 (`ui_notify.cpp:152` reads it, `model_keyframe_edit.cpp:277` stores it).
fn toggle_checkbox(ctx: &mut Ctx) -> Result<(), String> {
    let on = ctx.editor.doc.edit.physics_checkbox;
    ctx.editor.apply(Command::SetPhysicsCheckbox(!on))
}

/// Menu 271 (`command_view_menu.cpp:1163`): `playbackAlwaysOnOffMode` flips; the next play runs
/// in physics mode 2.
fn toggle_playback_on_off(ctx: &mut Ctx) -> Result<(), String> {
    let p = &mut ctx.editor.physics;
    p.always_on_off = !p.always_on_off;
    Ok(())
}

/// Menu 273 (`command_view_menu.cpp:1180` to `:1196`): the bones with a rigid body are selected
/// and the last of them is the selected bone; the others are not selected. With no rigid-body bone
/// the marks are cleared and `selectedBone` stays ([`Command::ClearBoneMarks`]).
fn select_physics_bones(ctx: &mut Ctx) -> Result<(), String> {
    let Some(rig) = viewport::rig(ctx.editor) else {
        return Ok(());
    };
    if rig.bones.is_empty() {
        return Ok(());
    }
    let marks: Vec<bool> = rig.bones.iter().map(|b| b.rigid).collect();
    let cmd = match marks.iter().rposition(|&m| m) {
        Some(last) => Command::SelectBones(viewport::selection_list(&marks, last as i32)),
        None => Command::ClearBoneMarks,
    };
    ctx.editor.apply(cmd)
}

/// Menu 274 (`SelectPhysicsOnBoneKeys`, `model_keyframe_edit.cpp:730`): every mark of the model's
/// three key pools is cleared, then each key of a rigid-body bone whose `physicsDisabled` is 0 is
/// marked; the camera-mode marks stay.
fn select_physics_on_frames(ctx: &mut Ctx) -> Result<(), String> {
    let Some(rig) = viewport::rig(ctx.editor) else {
        return Ok(());
    };
    let Some(model) = ctx.editor.doc.selected_model() else {
        return Ok(());
    };
    let mut on = Vec::new();
    for (bone, b) in rig.bones.iter().enumerate() {
        if !b.rigid {
            continue;
        }
        let mut index = bone as u32;
        for _ in 0..model.bone_keys.capacity() {
            let Some(key) = model.bone_keys.get(index) else {
                break;
            };
            if key.physics_disabled == 0 {
                on.push((bone as u32, key.frame));
            }
            // The original treats the link as signed when testing the sentinel.
            if key.next as i32 <= 0 {
                break;
            }
            index = key.next;
        }
    }
    // `ReplaceKeySelection` clears the model's pools only; the empty range marks nothing.
    ctx.editor.apply(Command::ReplaceKeySelection {
        track: Track::Bone(0),
        from: 1,
        to: 0,
    })?;
    for (bone, frame) in on {
        ctx.editor.apply(Command::SelectKeys {
            track: Track::Bone(bone),
            from: frame,
            to: frame,
        })?;
    }
    Ok(())
}

/// Check box 530 and the `]` key (`pump_edit_keys.cpp:222`): the check box flips. The C++ names it
/// the physics frame check box; it is the automatic interpolation of `RegisterBoneKeys`.
fn toggle_auto_interpolation(ctx: &mut Ctx) -> Result<(), String> {
    let on = ctx.editor.doc.edit.auto_interpolation;
    ctx.editor.apply(Command::SetAutoInterpolation(!on))
}

// ---- the menu ----------------------------------------------------------------------------------

/// `(id, label_ja, label_en)` of the menu rows, mnemonics dropped, then the two check boxes.
pub const LABELS: &[(&str, &str, &str)] = &[
    ("menu:269", "オン/オフモード", "on/off mode"),
    ("menu:265", "常に演算", "anytime"),
    ("menu:270", "トレースモード", "trace mode"),
    ("menu:272", "演算しない", "no calculation"),
    (
        "menu:271",
        "再生時は常にオン/オフモードにする",
        "playtime use on/off mode",
    ),
    ("menu:264", "剛体表示", "display bodies"),
    ("menu:266", "重力設定", "gravity setting"),
    ("menu:268", "剛体位置初期化", "initialize bodies position"),
    ("menu:285", "床", "floor"),
    ("menu:273", "物理影響ボーン選択", "select physical bone"),
    (
        "menu:274",
        "全ての物理ONフレーム(X印)選択",
        "select physics ON frame(X mark)",
    ),
    (
        "menu:275",
        "物理ON/OFFフレーム変換",
        "change physics ON/OFF frame",
    ),
    ("menu:267", "物理エンジンについて", "about physical engine"),
    ("ctl:499", "物 理", "physics"),
    ("ctl:530", "自動補間(])", "auto interpolation(])"),
];

fn label(egui: &egui::Context, id: &str) -> &'static str {
    let &(_, ja, en) = LABELS
        .iter()
        .find(|l| l.0 == id)
        .unwrap_or_else(|| panic!("{id}: no label"));
    help::pick(egui, ja, en)
}

/// A menu item for `id` that shows `checked`, greyed out when the action cannot run.
fn item(ui: &mut egui::Ui, ctx: &mut Ctx, id: &str, checked: Option<bool>) {
    let button = egui::Button::new(label(ui.ctx(), id)).selected(checked.unwrap_or(false));
    let pmx_trace = id == "menu:270" && selected_pmx(ctx.editor);
    if ui
        .add_enabled(ctx.enabled(id) && !pmx_trace, button)
        .clicked()
    {
        ctx.run(id);
    }
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let mode = ctx.editor.doc.pmm.physics.playback_mode;
    for (id, m) in [
        ("menu:269", 2),
        ("menu:265", 1),
        ("menu:270", 3),
        ("menu:272", 0),
    ] {
        item(ui, ctx, id, Some(mode == m));
    }
    ui.separator();
    item(ui, ctx, "menu:271", Some(ctx.editor.physics.always_on_off));
    ui.separator();
    let shown = bodies_on(ui.ctx(), ctx.editor);
    item(ui, ctx, "menu:264", Some(shown));
    ui.separator();
    item(ui, ctx, "menu:266", None);
    item(ui, ctx, "menu:268", None);
    ui.separator();
    let floor = ctx.editor.doc.pmm.appearance.floor_visible != 0;
    item(ui, ctx, "menu:285", Some(floor));
    ui.separator();
    for id in ["menu:273", "menu:274", "menu:275"] {
        item(ui, ctx, id, None);
    }
    ui.separator();
    item(ui, ctx, "menu:267", None);
    ui.separator();
    let mut physics = ctx.editor.doc.edit.physics_checkbox;
    let text = label(ui.ctx(), "ctl:499");
    if ui.checkbox(&mut physics, text).changed() {
        ctx.run("ctl:499");
    }
    let mut auto = ctx.editor.doc.edit.auto_interpolation;
    let text = label(ui.ctx(), "ctl:530");
    if ui.checkbox(&mut auto, text).changed() {
        ctx.run("ctl:530");
    }
}

/// `MDS_APP_PHYSICS_BODIES=1` shows the bodies when the window starts, for screenshots.
const SHOW_BODIES_VAR: &str = "MDS_APP_PHYSICS_BODIES";

pub fn pass(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let Some(egui) = ctx.egui.clone() else {
        return;
    };
    let seeded = Id::unique("physics-bodies-seeded");
    if !egui.data(|d| d.get_temp::<bool>(seeded).is_some()) {
        egui.data_mut(|d| d.insert_temp(seeded, true));
        if std::env::var_os(SHOW_BODIES_VAR).is_some() {
            set_bodies(&egui, ctx.editor, true);
        }
    }
    let id = about_id();
    let mut open = egui.data(|d| d.get_temp(id).unwrap_or(false));
    if open {
        egui::Window::new(label(&egui, "menu:267"))
            .open(&mut open)
            .collapsible(false)
            .resizable(false)
            .show(ui.ctx(), |ui| {
                ui.label(ABOUT);
            });
        egui.data_mut(|d| d.insert_temp(id, open));
    }
    if bodies_on(&egui, ctx.editor) {
        paint_bodies(&egui, ctx.editor);
    }
}
