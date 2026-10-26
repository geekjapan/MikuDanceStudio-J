//! The `timeline` area: the frame bands, the buttons and edits around them, and the key grid.
//!
//! Ported from `src/window`:
//!
//! * the frame step buttons 418 and 419 and the arrows (`StepFrame`, `ui_frame_step.cpp`; the hold
//!   repeat of `ConsumeArrowKeyNavigation`, `src/app/pump_navigation.cpp:238`), Ctrl+Left and
//!   Ctrl+Right (`JumpPrevKeyframe` and `JumpNextKeyframe`, `src/app/app_utilities.cpp:352` and
//!   `:571`, buttons 532 and 533), Up and Down (`SelectPreviousDisplayBone` and
//!   `SelectPrevEditTarget`, `src/model/model_query_helpers.cpp:331`);
//! * undo and redo 400 and 401, the current frame edit 417, the first and last frame buttons 558
//!   and 559, the go-to edit 554 with Go 553 / G and Set 555 (`command_frame_register.cpp:697`),
//!   and 429 (scroll the timeline to the current frame, `command_frame_edit.cpp:1486`);
//! * range selection 415 and vertical selection 416 (`SelectKeyframesInRange`,
//!   `SyncKeyframeSelection`, `command_frame_edit.cpp:701` and `:843`), copy 420, paste 421 and
//!   delete 423 with Ctrl+C, Ctrl+V and Delete (`CopySelectedKeyframes` and the others,
//!   `command_frame_edit.cpp:1650` to `:1672`), and Enter in camera mode (`PumpGlobalEnterRegister`,
//!   `src/app/pump_edit_keys.cpp:324`);
//! * the grid, in egui painting: one row for each display / IK track, bone and morph of the
//!   selected model, or for each camera-mode track; the mouse rows of `ui_editor_click.cpp`
//!   (margin and name columns, cell hits, the frame strip) and `ui_mousemove.cpp` (box selection
//!   and hover).
//!
//! # State
//!
//! The edits and the row selection of the C++ panel live in [`Panel`], under one id of egui's
//! memory ([`panel_id`]); the actions read it through `Ctx::egui`, so a test drives them with a
//! headless `egui::Context`. A `Ctx` without `egui` reads the defaults and loses writes.
//!
//! # Key marks
//!
//! The document has `ClearKeySelection` and `SelectKeys`, which only add marks. Every change of
//! the mark set therefore reads the marks ([`marks`]), computes the wanted set and, when it
//! differs, clears and marks again ([`set_marks`]); the C++ range sweep that replaces the marks of
//! the swept tracks only is [`replace_marks`].
//!
//! # The curve
//!
//! Buttons 430 to 432 copy, paste and reset the interpolation curve of the channel in the combo
//! 433 (`CopyInterpolationCurve` and the others, `command_frame_edit.cpp:987` to `:1124`); the
//! curve box beside them is the C++ curve panel, whose two control points drag with
//! `DragInterpolationControlPoint` (`ui_selection_reeval.cpp:115`).
//!
//! # The key drag
//!
//! Pressing a marked key (without Shift) and dragging moves the marked keys (`HandleMouseMove`,
//! `ui_mousemove.cpp:331`). The grid shows where the keys would land and the release applies one
//! [`Command::MoveSelectedKeys`] with the whole move in frames, so a drag is one undo entry (the
//! C++ pushes its entry at the mouse-down). A drag that ends where it began applies nothing.
//!
//! # Button 424
//!
//! Range scaling opens the dialog area's `IDD_FRAME_SCALE` (`FrameRangeDlgProc`,
//! `src/window/dialog_procs.cpp:62`), which starts from the range edits 425 and 426. Model mode
//! only (`command_frame_edit.cpp:1686`).

use super::Ctx;
use crate::actions::{self, Action, Mode};
use crate::navigation::{KeyState, Repeat};
use egui::{Align2, Color32, FontId, Id, Key, Pos2, Rect, Sense, Stroke, Vec2};
use mds_doc::{Command, Document, GlobalTrack, ModelFile, Track};
use mds_formats::key_pool::{Key as PoolKey, KeyPool};

const ACTIONS: &[Action] = &[
    Action::run("ctl:400", undo, true),
    Action::run("ctl:401", redo, true),
    Action::run("key:Ctrl+Z", undo, true),
    Action::run("key:Ctrl+X", redo, true),
    Action::run("ctl:415", select_range, true),
    Action::run("ctl:416", sync_marks, true),
    Action::inline("ctl:417"),
    Action::run("ctl:418", previous, true),
    Action::run("ctl:419", next, true),
    Action::run("ctl:420", copy, true),
    Action::run("ctl:421", paste, true),
    Action::run("ctl:422", paste_mirrored, true),
    Action::run("ctl:423", delete, true),
    Action::run("ctl:424", open_scale, true).in_mode(Mode::Model),
    Action::inline("ctl:425"),
    Action::inline("ctl:426"),
    Action::inline("ctl:427"),
    Action::inline("ctl:428"),
    Action::run("ctl:429", show_current, true),
    Action::run("ctl:430", copy_curve, true),
    Action::run("ctl:431", paste_curve, true),
    Action::run("ctl:432", reset_curve, true),
    Action::inline("ctl:433"),
    Action::inline("ctl:434"),
    Action::run("ctl:532", next_keyframe, true),
    Action::run("ctl:533", previous_keyframe, true),
    Action::run("ctl:553", go, true),
    Action::inline("ctl:554"),
    Action::run("ctl:555", set_goto, false),
    Action::run("ctl:558", first_frame, true),
    Action::run("ctl:559", last_frame, true),
    Action::run("key:Ctrl+V", paste, true),
    Action::run("key:Ctrl+C", copy, true),
    Action::run("key:G", go, true),
    Action::run("key:Right", next, true),
    Action::run("key:Ctrl+Right", next_keyframe, true),
    Action::run("key:Left", previous, true),
    Action::run("key:Ctrl+Left", previous_keyframe, true),
    Action::run("key:Up", up, true),
    Action::run("key:Down", down, true),
    Action::run("key:Enter@camera-mode", register_rows, true),
    Action::run("key:Delete", delete, true),
    Action::inline("key:Tab@panel-edits"),
    Action::inline("mouse:timeline-margin-click"),
    Action::inline("mouse:timeline-name-click"),
    Action::inline("mouse:timeline-name-rect-click"),
    Action::inline("mouse:timeline-cell-click"),
    Action::inline("mouse:timeline-frame-strip-click"),
    Action::inline("mouse:timeline-dblclick"),
    Action::inline("mouse:timeline-hover"),
    Action::inline("mouse:timeline-key-drag"),
    Action::inline("mouse:curve-point-drag"),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

// ---- the panel state ----------------------------------------------------------------------

/// What the C++ panel keeps in its controls and row flags, which the document does not save.
#[derive(Clone, Debug, PartialEq)]
pub struct Panel {
    /// The go-to-frame edit 554.
    pub goto: u32,
    /// The range edits 425 and 426.
    pub range: [u32; 2],
    /// The range scope combo 434: an index into [`scopes`].
    pub scope: usize,
    /// The interpolation curve combo 433: an index into [`CURVES`].
    pub curve: usize,
    /// The camera-mode rows that are selected: camera, light, self shadow, gravity
    /// (`GlobalTrackSelected`). Enter registers them and the keyframe jumps follow them.
    pub global_rows: [bool; 4],
    /// The selected accessory rows, by accessory slot (`rowSelected`).
    pub accessory_rows: Vec<u8>,
    /// The display / IK row of the model mode is selected (`displayKeyframesPresent`).
    pub display_row: bool,
    /// The folded groups as `(model slot, group)`; only the view folds, not the PMM flag.
    pub folded: Vec<(u8, usize)>,
    /// 429 was pressed: the next draw scrolls the current frame into view.
    pub scroll_to_current: bool,
    /// The frame on screen at the last draw; a change scrolls it into view.
    pub last_shown: u32,
    /// The scroll offset of the grid at the last draw.
    pub scroll: [f32; 2],
    /// The grid's visible frame columns at the last draw.
    pub columns: u32,
    /// Where a box selection started and where the pointer is: `(row, frame)`.
    pub drag: Option<[(usize, u32); 2]>,
    /// The control point of the curve box under the pointer: `false` the start, `true` the end
    /// (`PendingTimelineSelectionRow` 1 and 2).
    pub curve_drag: Option<bool>,
    /// A drag of the marked keys: the column it began on and the column the pointer is over.
    pub key_drag: Option<[i32; 2]>,
}

impl Default for Panel {
    fn default() -> Panel {
        Panel {
            goto: 0,
            range: [0, 0],
            scope: 0,
            curve: 3,
            // `SelectTimelineTrack(GlobalTimelineTrack::Camera)` is where every reset ends.
            global_rows: [true, false, false, false],
            accessory_rows: Vec::new(),
            display_row: false,
            folded: Vec::new(),
            scroll_to_current: false,
            last_shown: 0,
            scroll: [0.0; 2],
            columns: 40,
            drag: None,
            curve_drag: None,
            key_drag: None,
        }
    }
}

pub fn panel_id() -> Id {
    Id::unique("mds-app timeline panel")
}

pub fn panel(ctx: &Ctx) -> Panel {
    ctx.egui
        .as_ref()
        .and_then(|e| e.data(|d| d.get_temp(panel_id())))
        .unwrap_or_default()
}

pub fn set_panel(ctx: &Ctx, p: Panel) {
    if let Some(e) = &ctx.egui {
        e.data_mut(|d| d.insert_temp(panel_id(), p));
    }
}

pub fn update(ctx: &Ctx, f: impl FnOnce(&mut Panel)) {
    let mut p = panel(ctx);
    f(&mut p);
    set_panel(ctx, p);
}

/// The channels of the curve combo 433 (`reset_app_state.cpp:241`).
pub const CURVES: [&str; 7] = [
    "X軸移動",
    "Y軸移動",
    "Z軸移動",
    "回転",
    "距離",
    "視野角",
    "全て",
];

/// The entries of the scope combo 434 (`reset_app_state.cpp:191` and `SelectKeyframesInRange`).
pub fn scopes(doc: &Document) -> Vec<String> {
    if camera_mode(doc) {
        let mut v: Vec<String> = ["カメラ", "照明", "セルフ影", "重力"]
            .map(String::from)
            .into();
        v.extend(accessories(doc).into_iter().map(|a| a.1));
        v
    } else {
        [
            "全フレーム",
            "全表情フレーム",
            "全ボーンフレーム",
            "選択ボーン",
            "選択表情",
        ]
        .map(String::from)
        .into()
    }
}

// ---- the document, read -----------------------------------------------------------------

fn camera_mode(doc: &Document) -> bool {
    doc.pmm.settings.options[0] != 0
}

/// The index in `pmm.models` of the model in the selected slot.
fn active(doc: &Document) -> Option<usize> {
    let slot = doc.pmm.selected_model_slot;
    doc.pmm.models.iter().position(|m| m.slot == slot)
}

/// `(slot, name)` of the accessories in display order.
fn accessories(doc: &Document) -> Vec<(u8, String)> {
    let mut v: Vec<_> = doc
        .pmm
        .accessories
        .iter()
        .map(|a| (a.order, a.slot, a.name.text.clone()))
        .collect();
    v.sort();
    v.into_iter().map(|(_, s, n)| (s, n)).collect()
}

fn chain<K: PoolKey>(
    pool: &KeyPool<K>,
    head: u32,
    marked: impl Fn(&K) -> bool,
) -> Vec<(u32, bool)> {
    let mut out = Vec::new();
    let mut i = head;
    for _ in 0..pool.capacity() {
        let Some(k) = pool.get(i) else { break };
        out.push((k.frame(), marked(k)));
        i = k.next();
        if i == 0 {
            break;
        }
    }
    out
}

/// The keys of a track in frame order, as `(frame, marked)`. The head record is the key at
/// frame 0 that every track has.
pub fn keys_of(doc: &Document, track: Track) -> Vec<(u32, bool)> {
    let model = active(doc).map(|i| &doc.pmm.models[i]);
    let p = &doc.pmm;
    match track {
        Track::Bone(b) => {
            model.map_or(Vec::new(), |m| chain(&m.bone_keys, b, |k| k.allocated != 0))
        }
        Track::Morph(n) => model.map_or(Vec::new(), |m| {
            chain(&m.morph_keys, n, |k| k.allocated != 0)
        }),
        Track::Display => model.map_or(Vec::new(), |m| {
            chain(&m.display_keys, 0, |k| k.allocated != 0)
        }),
        Track::Global(GlobalTrack::Camera) => chain(&p.camera, 0, |k| k.selected != 0),
        Track::Global(GlobalTrack::Light) => chain(&p.light, 0, |k| k.selected != 0),
        Track::Global(GlobalTrack::SelfShadow) => chain(&p.self_shadow, 0, |k| k.selected != 0),
        Track::Global(GlobalTrack::Gravity) => chain(&p.gravity, 0, |k| k.selected != 0),
        Track::Global(GlobalTrack::Accessory(s)) => p
            .accessories
            .iter()
            .find(|a| a.slot == s)
            .map_or(Vec::new(), |a| chain(&a.keys, 0, |k| k.selected != 0)),
    }
}

/// The tracks that `ClearKeySelection` clears in the camera-mode half of the document.
fn global_tracks(doc: &Document) -> Vec<Track> {
    let mut v: Vec<Track> = [
        GlobalTrack::Camera,
        GlobalTrack::Light,
        GlobalTrack::SelfShadow,
        GlobalTrack::Gravity,
    ]
    .map(Track::Global)
    .into();
    v.extend(
        doc.pmm
            .accessories
            .iter()
            .map(|a| Track::Global(GlobalTrack::Accessory(a.slot))),
    );
    v
}

/// The tracks of the model in the selected slot.
fn model_tracks(doc: &Document) -> Vec<Track> {
    let Some(i) = active(doc) else {
        return Vec::new();
    };
    let m = &doc.pmm.models[i];
    let mut v = vec![Track::Display];
    v.extend((0..m.bone_keys.heads().len() as u32).map(Track::Bone));
    v.extend((0..m.morph_keys.heads().len() as u32).map(Track::Morph));
    v
}

fn order(t: &Track) -> (u8, u32) {
    match t {
        Track::Bone(b) => (0, *b),
        Track::Morph(n) => (1, *n),
        Track::Display => (2, 0),
        Track::Global(GlobalTrack::Camera) => (3, 0),
        Track::Global(GlobalTrack::Light) => (3, 1),
        Track::Global(GlobalTrack::SelfShadow) => (3, 2),
        Track::Global(GlobalTrack::Gravity) => (3, 3),
        Track::Global(GlobalTrack::Accessory(s)) => (4, u32::from(*s)),
    }
}

/// Every marked key of the document as `(track, frame)`, sorted.
pub fn marks(doc: &Document) -> Vec<(Track, u32)> {
    let mut out: Vec<(Track, u32)> = Vec::new();
    for t in global_tracks(doc).into_iter().chain(model_tracks(doc)) {
        out.extend(
            keys_of(doc, t)
                .into_iter()
                .filter(|k| k.1)
                .map(|k| (t, k.0)),
        );
    }
    out.sort_by_key(|(t, f)| (order(t), *f));
    out
}

/// Makes `want` the set of marked keys.
pub fn set_marks(ctx: &mut Ctx, mut want: Vec<(Track, u32)>) -> Result<(), String> {
    want.sort_by_key(|(t, f)| (order(t), *f));
    want.dedup();
    if marks(&ctx.editor.doc) == want {
        return Ok(());
    }
    ctx.editor.apply(Command::ClearKeySelection)?;
    for (track, frame) in want {
        ctx.editor.apply(Command::SelectKeys {
            track,
            from: frame,
            to: frame,
        })?;
    }
    Ok(())
}

/// The sweep of range selection: the marks of `tracks` become the keys with a frame in
/// `from..=to`, and the marks of every other track stay (`SelectModelFrameRange` clears the mark
/// byte of its own track first, `command_frame_edit.cpp:696`).
pub fn replace_marks(ctx: &mut Ctx, tracks: &[Track], from: u32, to: u32) -> Result<(), String> {
    let doc = &ctx.editor.doc;
    let mut want: Vec<_> = marks(doc)
        .into_iter()
        .filter(|(t, _)| !tracks.contains(t))
        .collect();
    for &t in tracks {
        want.extend(
            keys_of(doc, t)
                .into_iter()
                .filter(|k| (from..=to).contains(&k.0))
                .map(|k| (t, k.0)),
        );
    }
    set_marks(ctx, want)
}

// ---- the rows -------------------------------------------------------------------------------

/// The group id of the morph rows, which no display frame of a model uses.
pub const MORPHS: usize = usize::MAX;

#[derive(Clone, Debug, PartialEq)]
pub enum RowKind {
    /// A group of rows, folded by clicking it.
    Header(usize),
    /// The display and IK keys of the model.
    Display,
    Bone(u32),
    Morph(u32),
    Global(GlobalTrack),
}

#[derive(Clone, Debug, PartialEq)]
pub struct Row {
    pub kind: RowKind,
    pub label: String,
}

impl Row {
    pub fn track(&self) -> Option<Track> {
        match self.kind {
            RowKind::Header(_) => None,
            RowKind::Display => Some(Track::Display),
            RowKind::Bone(b) => Some(Track::Bone(b)),
            RowKind::Morph(n) => Some(Track::Morph(n)),
            RowKind::Global(g) => Some(Track::Global(g)),
        }
    }
}

/// Whether the model has the facial display group (`facialFrameCount != 0`), which the C++ puts
/// at group 2 and which moves the bone groups up by one.
fn facial(doc: &Document, i: usize) -> bool {
    match &doc.models[i] {
        ModelFile::Pmx(p) => p.frames.iter().any(|f| f.entries.iter().any(|e| e.0 == 1)),
        ModelFile::Pmd(p) => !p.morph_display.is_empty(),
        ModelFile::Missing => false,
    }
}

/// The bones of each display group of the model file, with the group's index in the PMM's
/// `group_flags` (`DisplayGroups`, `pmx_load.cpp:1421`), or all of them in one group when the
/// file has none that fits the PMM. The first two PMX frames (the root and the facial frame) are
/// no flag groups; neither is the fallback group.
fn bone_groups(doc: &Document, i: usize) -> Vec<(String, Vec<u32>, Option<u8>)> {
    let count = doc.pmm.models[i].bone_names.len();
    let mut groups = Vec::new();
    if let ModelFile::Pmx(p) = &doc.models[i] {
        if p.bones.len() == count {
            let facial = usize::from(facial(doc, i));
            for (n, f) in p.frames.iter().enumerate() {
                let bones: Vec<u32> = f
                    .entries
                    .iter()
                    .filter(|e| e.0 == 0 && (0..count as i32).contains(&e.1))
                    .map(|e| e.1 as u32)
                    .collect();
                if !bones.is_empty() {
                    let flag = (n >= 2).then(|| (n + facial) as u8);
                    groups.push((f.name.text.clone(), bones, flag));
                }
            }
        }
    }
    if groups.is_empty() {
        groups.push(("ボーン".into(), (0..count as u32).collect(), None));
    }
    groups
}

/// The panel (lane) 0 to 3 of morph `n`, or `None` for a morph that no lane lists.
fn morph_lane(doc: &Document, i: usize, n: u32) -> Option<u8> {
    let panel = match &doc.models[i] {
        ModelFile::Pmx(p) => p.morphs.get(n as usize)?.panel,
        ModelFile::Pmd(p) => p.morphs.get(n as usize)?.panel,
        ModelFile::Missing => return None,
    };
    (1..=4).contains(&panel).then(|| panel - 1)
}

/// The timeline rows of the document in its mode.
pub fn rows(doc: &Document, folded: &[(u8, usize)]) -> Vec<Row> {
    let row = |kind, label: &str| Row {
        kind,
        label: label.into(),
    };
    if camera_mode(doc) {
        let mut v = vec![
            row(RowKind::Global(GlobalTrack::Camera), "カメラ"),
            row(RowKind::Global(GlobalTrack::Light), "照明"),
            row(RowKind::Global(GlobalTrack::SelfShadow), "セルフ影"),
            row(RowKind::Global(GlobalTrack::Gravity), "重力"),
        ];
        v.extend(
            accessories(doc)
                .iter()
                .map(|(s, n)| row(RowKind::Global(GlobalTrack::Accessory(*s)), n)),
        );
        return v;
    }
    let Some(i) = active(doc) else {
        return Vec::new();
    };
    let m = &doc.pmm.models[i];
    let open = |g| !folded.contains(&(m.slot, g));
    let mut v = vec![row(RowKind::Display, "表示・IK")];
    for (g, (name, bones, _)) in bone_groups(doc, i).into_iter().enumerate() {
        v.push(row(RowKind::Header(g), &name));
        if open(g) {
            v.extend(
                bones
                    .iter()
                    .map(|&b| row(RowKind::Bone(b), &m.bone_names[b as usize].text)),
            );
        }
    }
    let morphs: Vec<u32> = (0..m.morph_names.len() as u32)
        .filter(|&n| match &doc.models[i] {
            ModelFile::Missing => true,
            _ => morph_lane(doc, i, n).is_some(),
        })
        .collect();
    if !morphs.is_empty() {
        v.push(row(RowKind::Header(MORPHS), "表情"));
        if open(MORPHS) {
            v.extend(
                morphs
                    .iter()
                    .map(|&n| row(RowKind::Morph(n), &m.morph_names[n as usize].text)),
            );
        }
    }
    v
}

/// The index in `group_flags` of the group that header `g` stands for, if it has a flag.
pub fn group_flag(doc: &Document, g: usize) -> Option<u8> {
    let i = active(doc)?;
    match g {
        MORPHS => facial(doc, i).then_some(2),
        _ => bone_groups(doc, i).get(g)?.2,
    }
}

fn selected_bones(doc: &Document) -> Vec<u32> {
    let Some(i) = active(doc) else {
        return Vec::new();
    };
    let m = &doc.pmm.models[i];
    let mut v: Vec<u32> = m
        .bone_pose
        .iter()
        .enumerate()
        .filter(|(_, p)| p.flags[2] != 0)
        .map(|(b, _)| b as u32)
        .collect();
    // `selectedBone` leads the list, as `SelectBones` takes the first for it.
    if let Some(at) = v
        .iter()
        .position(|&b| b as i32 == m.selection.selected_bone)
    {
        v.swap(0, at);
    }
    v
}

fn selected_morphs(doc: &Document) -> Vec<u32> {
    let Some(i) = active(doc) else {
        return Vec::new();
    };
    let mut v: Vec<u32> = doc.pmm.models[i]
        .selection
        .selected_morphs
        .iter()
        .filter_map(|&n| u32::try_from(n).ok())
        .collect();
    v.dedup();
    v
}

fn row_selected(doc: &Document, p: &Panel, kind: &RowKind) -> bool {
    match kind {
        RowKind::Header(_) => false,
        RowKind::Display => p.display_row,
        RowKind::Bone(b) => selected_bones(doc).contains(b),
        RowKind::Morph(n) => selected_morphs(doc).contains(n),
        RowKind::Global(g) => is_global_selected(p, *g),
    }
}

fn is_global_selected(p: &Panel, g: GlobalTrack) -> bool {
    match g {
        GlobalTrack::Camera => p.global_rows[0],
        GlobalTrack::Light => p.global_rows[1],
        GlobalTrack::SelfShadow => p.global_rows[2],
        GlobalTrack::Gravity => p.global_rows[3],
        GlobalTrack::Accessory(s) => p.accessory_rows.contains(&s),
    }
}

fn set_global_selected(p: &mut Panel, g: GlobalTrack, on: bool) {
    match g {
        GlobalTrack::Camera => p.global_rows[0] = on,
        GlobalTrack::Light => p.global_rows[1] = on,
        GlobalTrack::SelfShadow => p.global_rows[2] = on,
        GlobalTrack::Gravity => p.global_rows[3] = on,
        GlobalTrack::Accessory(s) => {
            p.accessory_rows.retain(|&x| x != s);
            if on {
                p.accessory_rows.push(s);
            }
        }
    }
}

// ---- the actions ------------------------------------------------------------------------

fn undo(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.apply(Command::Undo)
}

fn redo(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.apply(Command::Redo)
}

fn previous(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.step_frame(false)
}

fn next(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.step_frame(true)
}

/// The tracks that `SelectKeyframesInRange` sweeps for the scope combo's entry.
fn scope_tracks(doc: &Document, scope: usize) -> Result<Vec<Track>, String> {
    if camera_mode(doc) {
        return match scope {
            0 => Ok(vec![Track::Global(GlobalTrack::Camera)]),
            1 => Ok(vec![Track::Global(GlobalTrack::Light)]),
            2 => Ok(vec![Track::Global(GlobalTrack::SelfShadow)]),
            3 => Ok(vec![Track::Global(GlobalTrack::Gravity)]),
            n => accessories(doc)
                .get(n - 4)
                .map(|a| vec![Track::Global(GlobalTrack::Accessory(a.0))])
                .ok_or_else(|| "no such accessory".into()),
        };
    }
    let i = active(doc).ok_or("no model selected")?;
    let m = &doc.pmm.models[i];
    let bones = || (0..m.bone_keys.heads().len() as u32).map(Track::Bone);
    let morphs = || (0..m.morph_keys.heads().len() as u32).map(Track::Morph);
    Ok(match scope {
        0 => bones().chain(morphs()).chain([Track::Display]).collect(),
        1 => morphs().collect(),
        2 => bones().collect(),
        3 => selected_bones(doc).into_iter().map(Track::Bone).collect(),
        _ => selected_morphs(doc).into_iter().map(Track::Morph).collect(),
    })
}

/// 415.
fn select_range(ctx: &mut Ctx) -> Result<(), String> {
    let p = panel(ctx);
    let tracks = scope_tracks(&ctx.editor.doc, p.scope)?;
    replace_marks(ctx, &tracks, p.range[0], p.range[1])
}

/// 416: every marked frame is marked in the other tracks too (`SyncKeyframeSelection`).
fn sync_marks(ctx: &mut Ctx) -> Result<(), String> {
    let doc = &ctx.editor.doc;
    let tracks = if camera_mode(doc) {
        global_tracks(doc)
    } else {
        model_tracks(doc)
    };
    let marked = marks(doc);
    let frames: Vec<u32> = marked
        .iter()
        .filter(|(t, _)| tracks.contains(t))
        .map(|k| k.1)
        .collect();
    let mut want = marked;
    for t in tracks {
        want.extend(
            keys_of(doc, t)
                .into_iter()
                .filter(|k| frames.contains(&k.0))
                .map(|k| (t, k.0)),
        );
    }
    set_marks(ctx, want)
}

fn copy(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.apply(Command::Copy)
}

fn paste(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.apply(Command::Paste)
}

fn delete(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.apply(Command::DeleteSelectedKeys)
}

/// 424 (`command_frame_edit.cpp:1686`): the dialog area's frame scale.
fn open_scale(ctx: &mut Ctx) -> Result<(), String> {
    actions::run(ctx, "dlg:IDD_FRAME_SCALE")
}

/// The end of a key drag (`mouse:timeline-key-drag`): the marked keys move by `frames`.
pub fn move_keys(ctx: &mut Ctx, frames: i32) -> Result<(), String> {
    if ctx.editor.playing() {
        return Err("not while playing".into());
    }
    ctx.editor.apply(Command::MoveSelectedKeys(frames))
}

/// Whether a press on `frame` of `track` takes the marked keys along (`ToggleModelKeyAllocated`
/// and `ToggleTimelineCell` leave a marked key marked and flag the selection as changed).
pub fn grabs_marked_key(doc: &Document, track: Track, frame: u32) -> bool {
    keys_of(doc, track).contains(&(frame, true))
}

/// 422.
fn paste_mirrored(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.apply(Command::PasteMirrored)
}

/// The combo 433 channel as the document commands take it.
fn channel(ctx: &Ctx) -> u8 {
    panel(ctx).curve.min(CURVES.len() - 1) as u8
}

/// 430.
fn copy_curve(ctx: &mut Ctx) -> Result<(), String> {
    let channel = channel(ctx);
    ctx.editor
        .apply(Command::CopyInterpolationCurve { channel })
}

/// 431.
fn paste_curve(ctx: &mut Ctx) -> Result<(), String> {
    let channel = channel(ctx);
    ctx.editor
        .apply(Command::PasteInterpolationCurve { channel })
}

/// 432: the linear curve, the bytes 20, 20, 107, 107.
fn reset_curve(ctx: &mut Ctx) -> Result<(), String> {
    let channel = channel(ctx);
    ctx.editor
        .apply(Command::ResetInterpolationCurves { channel })
}

/// The control points `[start, end]` as `[x, y]` (0 to 127, y up) of the channel in the combo, on
/// the first marked key: the curve the C++ panel draws (`DrawCurve` and `DrawControlPoints`). The
/// "all" entry shows channel 0 (`ui_selection_reeval.cpp:176`). `None` without a marked key.
pub fn curve_points(doc: &Document, channel: usize) -> Option<[[u8; 2]; 2]> {
    fn first<K: PoolKey + Clone>(pool: &KeyPool<K>, marked: impl Fn(&K) -> bool) -> Option<K> {
        let heads = pool.heads().iter().enumerate().map(|(i, k)| (i as u32, k));
        heads
            .chain(pool.records().iter().map(|(i, k)| (*i, k)))
            .filter(|(_, k)| marked(k))
            .min_by_key(|(i, _)| *i)
            .map(|(_, k)| k.clone())
    }
    if camera_mode(doc) {
        let k = first(&doc.pmm.camera, |k| k.selected != 0)?;
        let ch = if channel < 6 { channel } else { 0 };
        let i = &k.interpolation;
        return Some([[i[0][ch], i[1][ch]], [i[2][ch], i[3][ch]]]);
    }
    let k = first(&doc.pmm.models[active(doc)?].bone_keys, |k| {
        k.allocated != 0
    })?;
    let ch = if channel < 4 { channel } else { 0 };
    let i = &k.interpolation;
    Some([[i[ch], i[4 + ch]], [i[8 + ch], i[12 + ch]]])
}

/// The drag of a control point of the curve box: the point goes to `pos`, in curve units, on
/// every marked key (`DragInterpolationControlPoint`; the document clamps to 0 to 127).
pub fn drag_curve_point(ctx: &mut Ctx, end: bool, point: [i32; 2]) -> Result<(), String> {
    let channel = channel(ctx);
    ctx.editor.apply(Command::SetKeyInterpolation {
        channel,
        end,
        point,
    })
}

/// 429.
fn show_current(ctx: &mut Ctx) -> Result<(), String> {
    update(ctx, |p| p.scroll_to_current = true);
    Ok(())
}

/// The tracks whose keys the keyframe jumps follow: the selected rows.
fn active_tracks(ctx: &Ctx) -> Vec<Track> {
    let doc = &ctx.editor.doc;
    let p = panel(ctx);
    if camera_mode(doc) {
        return global_tracks(doc)
            .into_iter()
            .filter(|t| matches!(t, Track::Global(g) if is_global_selected(&p, *g)))
            .collect();
    }
    let mut v = Vec::new();
    if p.display_row {
        v.push(Track::Display);
    }
    v.extend(selected_morphs(doc).into_iter().map(Track::Morph));
    v.extend(selected_bones(doc).into_iter().map(Track::Bone));
    v
}

/// 532 and 533: the nearest key after (or before) the current frame in the selected rows. Without
/// one, forward stays and backward goes to frame 0 (`JumpPrevKeyframe` starts from 0).
fn jump(ctx: &mut Ctx, forward: bool) -> Result<(), String> {
    let current = ctx.editor.current_frame();
    let frames = active_tracks(ctx)
        .into_iter()
        .flat_map(|t| keys_of(&ctx.editor.doc, t))
        .map(|k| k.0);
    let target = if forward {
        frames.filter(|&f| f > current).min()
    } else {
        frames.filter(|&f| f < current).max().or(Some(0))
    };
    let Some(f) = target else {
        return Ok(());
    };
    // `SetFrame` clears the bone selection (mds-doc reads it as the C++ edit flags, which the
    // frame change clears); the rows selected by name stay selected, so a second jump finds them.
    let selected = selected_bones(&ctx.editor.doc);
    ctx.editor.seek(f)?;
    match selected.is_empty() {
        true => Ok(()),
        false => ctx.editor.apply(Command::SelectBones(selected)),
    }
}

fn next_keyframe(ctx: &mut Ctx) -> Result<(), String> {
    jump(ctx, true)
}

fn previous_keyframe(ctx: &mut Ctx) -> Result<(), String> {
    jump(ctx, false)
}

/// 553 and G.
fn go(ctx: &mut Ctx) -> Result<(), String> {
    let frame = panel(ctx).goto;
    ctx.editor.seek(frame)
}

/// 555: the current frame into the go-to edit.
fn set_goto(ctx: &mut Ctx) -> Result<(), String> {
    let frame = ctx.editor.current_frame();
    update(ctx, |p| p.goto = frame);
    Ok(())
}

/// 558.
fn first_frame(ctx: &mut Ctx) -> Result<(), String> {
    ctx.editor.seek(0)
}

/// 559: the last registered frame.
fn last_frame(ctx: &mut Ctx) -> Result<(), String> {
    let last = ctx.editor.doc.pmm.timeline.last_registered_frame.max(0) as u32;
    ctx.editor.seek(last)
}

/// The camera-mode edit targets in the order of Up and Down.
fn targets(doc: &Document) -> Vec<GlobalTrack> {
    let mut v = vec![
        GlobalTrack::Camera,
        GlobalTrack::Light,
        GlobalTrack::SelfShadow,
        GlobalTrack::Gravity,
    ];
    v.extend(
        accessories(doc)
            .into_iter()
            .map(|a| GlobalTrack::Accessory(a.0)),
    );
    v
}

/// Selects one camera-mode row alone.
fn select_target(ctx: &mut Ctx, g: GlobalTrack) -> Result<(), String> {
    update(ctx, |p| {
        p.global_rows = [false; 4];
        p.accessory_rows.clear();
        set_global_selected(p, g, true);
    });
    match g {
        GlobalTrack::Accessory(s) => ctx.editor.apply(Command::SelectAccessory(s)),
        _ => Ok(()),
    }
}

/// Up and Down: the previous or next edit target in camera mode, else the previous or next bone
/// of the displayed rows (`SelectPrevEditTarget`, `SelectPreviousDisplayBone`).
fn step_target(ctx: &mut Ctx, forward: bool) -> Result<(), String> {
    let doc = &ctx.editor.doc;
    let p = panel(ctx);
    if camera_mode(doc) {
        let all = targets(doc);
        let at = all.iter().position(|&g| is_global_selected(&p, g));
        let to = match (at, forward) {
            (None, _) => 0,
            (Some(i), true) => (i + 1).min(all.len() - 1),
            (Some(i), false) => i.saturating_sub(1),
        };
        return select_target(ctx, all[to]);
    }
    let bones: Vec<u32> = rows(doc, &p.folded)
        .iter()
        .filter_map(|r| match r.kind {
            RowKind::Bone(b) => Some(b),
            _ => None,
        })
        .collect();
    let current = selected_bones(doc).first().copied();
    let at = current.and_then(|c| bones.iter().position(|&b| b == c));
    let to = match (at, forward) {
        (None, _) => bones.first().copied(),
        (Some(i), true) => bones.get(i + 1).copied(),
        (Some(i), false) => i.checked_sub(1).and_then(|j| bones.get(j)).copied(),
    };
    match to {
        Some(b) => ctx.editor.apply(Command::SelectBones(vec![b])),
        None => Ok(()),
    }
}

fn up(ctx: &mut Ctx) -> Result<(), String> {
    step_target(ctx, false)
}

fn down(ctx: &mut Ctx) -> Result<(), String> {
    step_target(ctx, true)
}

/// Enter in camera mode: the selected rows register a key at the current frame.
fn register_rows(ctx: &mut Ctx) -> Result<(), String> {
    let p = panel(ctx);
    let mut tracks: Vec<GlobalTrack> = [
        GlobalTrack::Camera,
        GlobalTrack::Light,
        GlobalTrack::SelfShadow,
        GlobalTrack::Gravity,
    ]
    .into_iter()
    .filter(|&g| is_global_selected(&p, g))
    .collect();
    tracks.extend(p.accessory_rows.iter().map(|&s| GlobalTrack::Accessory(s)));
    ctx.editor.apply(Command::RegisterGlobalKeys(tracks))
}

// ---- the mouse ---------------------------------------------------------------------------

/// A click on the frame strip, and a double click (`HandleLButtonDown_FrameStripHit`,
/// `ui_editor_click.cpp:801`): the clicked column becomes the current frame. Unlike the frame edit
/// (`SetFrame`) it keeps the bone selection ([`Command::ClickFrame`]).
pub fn click_strip(ctx: &mut Ctx, frame: u32) -> Result<(), String> {
    if ctx.editor.playing() {
        return Err("not while playing".into());
    }
    ctx.editor.apply(Command::ClickFrame(frame))
}

/// A click on a cell (`HandleLButtonDown_TimelineAreaHit`, `ui_editor_click.cpp:685`;
/// `ToggleModelKeyAllocated` at `:403`). Without Shift a key outside the selection becomes the
/// only marked key and a marked key stays (so a drag can take the selection); an empty cell clears
/// the marks. With Shift the key's mark toggles and an empty cell changes nothing.
pub fn click_cell(ctx: &mut Ctx, track: Track, frame: u32, shift: bool) -> Result<(), String> {
    let doc = &ctx.editor.doc;
    let key = keys_of(doc, track).into_iter().find(|k| k.0 == frame);
    let mut want = marks(doc);
    match (key, shift) {
        (Some((_, true)), false) | (None, true) => return Ok(()),
        (Some((_, marked)), true) => {
            if marked {
                want.retain(|&m| m != (track, frame));
            } else {
                want.push((track, frame));
            }
        }
        (Some(_), false) => want = vec![(track, frame)],
        (None, false) => want.clear(),
    }
    set_marks(ctx, want)
}

/// The end of a box drag (`ui_mousemove.cpp:406`): the keys of `tracks` with a frame in
/// `from..=to` are marked, and without Shift they are the only marked keys.
pub fn box_select(
    ctx: &mut Ctx,
    tracks: &[Track],
    from: u32,
    to: u32,
    shift: bool,
) -> Result<(), String> {
    let doc = &ctx.editor.doc;
    let mut want = if shift { marks(doc) } else { Vec::new() };
    for &t in tracks {
        want.extend(
            keys_of(doc, t)
                .into_iter()
                .filter(|k| (from..=to).contains(&k.0))
                .map(|k| (t, k.0)),
        );
    }
    set_marks(ctx, want)
}

/// A click on a row name (`HandleLButtonDown_NameColumnHit`, `ui_editor_click.cpp:461`): a bone
/// selects it (Shift adds or removes it), a morph becomes its lane's morph, the display row
/// toggles, a header folds its group, a camera-mode row becomes the edit target.
pub fn click_name(ctx: &mut Ctx, row: &Row, shift: bool) -> Result<(), String> {
    let doc = &ctx.editor.doc;
    match row.kind {
        RowKind::Header(g) => {
            let slot = doc.pmm.selected_model_slot;
            update(ctx, |p| {
                match p.folded.iter().position(|&f| f == (slot, g)) {
                    Some(at) => {
                        p.folded.remove(at);
                    }
                    None => p.folded.push((slot, g)),
                }
            });
            Ok(())
        }
        RowKind::Display => {
            update(ctx, |p| p.display_row = !p.display_row);
            Ok(())
        }
        RowKind::Bone(b) => {
            let mut sel = selected_bones(doc);
            if !shift {
                sel = vec![b];
            } else if let Some(at) = sel.iter().position(|&x| x == b) {
                sel.remove(at);
            } else {
                sel.insert(0, b);
            }
            ctx.editor.apply(Command::SelectBones(sel))
        }
        RowKind::Morph(n) => {
            let i = active(doc).ok_or("no model selected")?;
            let lane = morph_lane(doc, i, n).ok_or("this morph is in no lane")?;
            ctx.editor
                .apply(Command::SelectMorphLane { lane, morph: n })
        }
        RowKind::Global(g) => {
            if shift {
                let on = !is_global_selected(&panel(ctx), g);
                update(ctx, |p| set_global_selected(p, g, on));
                match g {
                    GlobalTrack::Accessory(s) if on => {
                        ctx.editor.apply(Command::SelectAccessory(s))
                    }
                    _ => Ok(()),
                }
            } else {
                select_target(ctx, g)
            }
        }
    }
}

/// The `+` square of a name (`HandleLButtonDown_NameRowRectHit`, `ui_editor_click.cpp:934`): the
/// row registers a key at the current frame.
pub fn click_plus(ctx: &mut Ctx, row: &Row) -> Result<(), String> {
    match row.kind {
        RowKind::Bone(b) => {
            ctx.editor.apply(Command::SelectBones(vec![b]))?;
            ctx.editor.apply(Command::RegisterBoneKeys)
        }
        RowKind::Morph(n) => ctx.editor.apply(Command::RegisterMorphKey(n as i32)),
        RowKind::Display => ctx.editor.apply(Command::RegisterDisplayKey),
        RowKind::Global(g) => ctx.editor.apply(Command::RegisterGlobalKeys(vec![g])),
        RowKind::Header(_) => click_margin(ctx, row),
    }
}

/// The margin column of a display group row (`HandleLButtonDown_MarginColumnToggle`,
/// `ui_editor_click.cpp:439`): the group's flag, which the PMM saves. The view's fold stays with
/// the name click.
pub fn click_margin(ctx: &mut Ctx, row: &Row) -> Result<(), String> {
    let RowKind::Header(g) = row.kind else {
        return Ok(());
    };
    match group_flag(&ctx.editor.doc, g) {
        Some(n) => ctx.editor.apply(Command::ToggleDisplayGroup(n)),
        None => Ok(()),
    }
}

// ---- the grid ---------------------------------------------------------------------------

/// The width of a frame column, the height of a row, the name column and the frame strip.
pub const CELL: f32 = 12.0;
pub const ROW: f32 = 14.0;
pub const NAME: f32 = 190.0;
pub const HEAD: f32 = 16.0;
/// The `+` square at the left of a name.
pub const PLUS: f32 = 14.0;
const GRID_HEIGHT: f32 = 196.0;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Hit {
    Strip(u32),
    Name { row: usize, plus: bool },
    Cell { row: usize, frame: u32 },
    None,
}

/// What lies under `p`, the pointer relative to the top left of the visible grid, when the grid is
/// scrolled by `scroll`. The name column and the strip stay in place.
pub fn hit(p: Vec2, scroll: Vec2, rows: usize) -> Hit {
    if p.x < 0.0 || p.y < 0.0 {
        return Hit::None;
    }
    if p.y < HEAD {
        return match p.x >= NAME {
            true => Hit::Strip(((p.x - NAME + scroll.x) / CELL) as u32),
            false => Hit::None,
        };
    }
    let row = ((p.y - HEAD + scroll.y) / ROW) as usize;
    if row >= rows {
        return Hit::None;
    }
    if p.x < NAME {
        return Hit::Name {
            row,
            plus: p.x < PLUS,
        };
    }
    Hit::Cell {
        row,
        frame: ((p.x - NAME + scroll.x) / CELL) as u32,
    }
}

enum Event {
    Seek(u32),
    Strip(u32),
    Cell(Track, u32, bool),
    Name(Row, bool),
    Plus(Row),
    Box(Vec<Track>, u32, u32, bool),
    /// A control point of the curve box moved: `(end, [x, y])`.
    Curve(bool, [i32; 2]),
    /// The marked keys dragged by this many frames.
    Move(i32),
}

fn run_event(ctx: &mut Ctx, e: Event) -> Result<(), String> {
    match e {
        Event::Seek(f) => ctx.editor.seek(f),
        Event::Strip(f) => click_strip(ctx, f),
        Event::Curve(end, point) => drag_curve_point(ctx, end, point),
        Event::Cell(t, f, shift) => click_cell(ctx, t, f, shift),
        Event::Name(row, shift) => click_name(ctx, &row, shift),
        Event::Plus(row) => click_plus(ctx, &row),
        Event::Box(tracks, from, to, shift) => box_select(ctx, &tracks, from, to, shift),
        Event::Move(frames) => move_keys(ctx, frames),
    }
}

struct Colors;

impl Colors {
    const BACK: Color32 = Color32::from_gray(28);
    const ALT: Color32 = Color32::from_gray(34);
    const HEADER: Color32 = Color32::from_rgb(52, 58, 76);
    const PICKED: Color32 = Color32::from_rgb(60, 80, 120);
    const LINE: Color32 = Color32::from_gray(52);
    const KEY: Color32 = Color32::from_rgb(150, 190, 235);
    const MARKED: Color32 = Color32::from_rgb(255, 150, 60);
    const NOW: Color32 = Color32::from_rgba_premultiplied(200, 60, 60, 70);
    const HOVER: Color32 = Color32::from_rgba_premultiplied(255, 255, 255, 30);
}

fn grid(ui: &mut egui::Ui, ctx: &Ctx, p: &mut Panel, events: &mut Vec<Event>) {
    let doc = &ctx.editor.doc;
    let rows = rows(doc, &p.folded);
    let shown = ctx.editor.shown_frame();
    let t = &doc.pmm.timeline;
    let last = (t.last_registered_frame.max(t.play_stop_frame).max(0) as u32).max(shown);
    let content = Vec2::new(
        NAME + (last + 120) as f32 * CELL,
        HEAD + rows.len() as f32 * ROW,
    );
    let mut area = egui::ScrollArea::both()
        .id_salt("timeline grid")
        .max_height(GRID_HEIGHT)
        // The bottom panel lays the area out in a horizontal row, whose height is one line.
        .min_scrolled_height(GRID_HEIGHT)
        .auto_shrink([false, true]);
    // The shown frame scrolls into view when it changes (a step, a jump, playback) or on 429.
    let first = (p.scroll[0] / CELL) as u32;
    let outside = shown < first || shown >= first + p.columns.max(1);
    if p.scroll_to_current || (shown != p.last_shown && outside) {
        let x = shown.saturating_sub(p.columns.saturating_sub(2)) as f32 * CELL;
        area = area.horizontal_scroll_offset(x);
        p.scroll_to_current = false;
    }
    p.last_shown = shown;
    let out = area.show_viewport(ui, |ui, viewport| {
        let (rect, resp) = ui.allocate_exact_size(content, Sense::click_and_drag());
        let scroll = viewport.min.to_vec2();
        let view = Rect::from_min_size(rect.min + scroll, viewport.size());
        let painter = ui.painter_at(view);
        let columns = (((view.width() - NAME) / CELL).ceil() as u32).max(1);
        let f0 = (scroll.x / CELL) as u32;
        let r0 = (scroll.y / ROW) as usize;
        let r1 = rows
            .len()
            .min(((scroll.y + view.height() - HEAD) / ROW).ceil() as usize + 1);
        let x_of = |f: u32| view.min.x + NAME + f as f32 * CELL - scroll.x;
        let y_of = |r: usize| view.min.y + HEAD + r as f32 * ROW - scroll.y;
        let pointer = resp
            .hover_pos()
            .map(|pos| hit(pos - view.min, scroll, rows.len()));
        let shift = ui.input(|i| i.modifiers.shift);

        painter.rect_filled(view, 0.0, Colors::BACK);
        for (r, row) in rows.iter().enumerate().take(r1).skip(r0) {
            let y = y_of(r);
            let line = Rect::from_min_size(Pos2::new(view.min.x, y), Vec2::new(view.width(), ROW));
            let picked = row_selected(doc, p, &row.kind);
            let fill = match (&row.kind, picked) {
                (RowKind::Header(_), _) => Colors::HEADER,
                (_, true) => Colors::PICKED,
                _ if r % 2 == 1 => Colors::ALT,
                _ => Colors::BACK,
            };
            painter.rect_filled(line, 0.0, fill);
            if let Some(track) = row.track() {
                for (f, marked) in keys_of(doc, track) {
                    if f < f0 || f > f0 + columns {
                        continue;
                    }
                    let c = Pos2::new(x_of(f) + CELL / 2.0, y + ROW / 2.0);
                    let color = if marked { Colors::MARKED } else { Colors::KEY };
                    painter.circle_filled(c, CELL / 2.0 - 2.0, color);
                    if let (true, Some([a, b])) = (marked, p.key_drag) {
                        // Where the drag would put the key (the move is applied on release).
                        let to = f as i32 + b - a;
                        if to >= 0 {
                            let ghost = Pos2::new(x_of(to as u32) + CELL / 2.0, y + ROW / 2.0);
                            painter.circle_stroke(
                                ghost,
                                CELL / 2.0 - 2.0,
                                Stroke::new(1.5, Colors::MARKED),
                            );
                        }
                    }
                }
            }
        }
        for f in (f0 - f0 % 5..f0 + columns + 5).step_by(5) {
            let x = x_of(f);
            painter.line_segment(
                [Pos2::new(x, view.min.y + HEAD), Pos2::new(x, view.max.y)],
                Stroke::new(1.0, Colors::LINE),
            );
        }
        let now = Rect::from_min_size(
            Pos2::new(x_of(shown), view.min.y),
            Vec2::new(CELL, view.height()),
        );
        painter.rect_filled(now, 0.0, Colors::NOW);
        match pointer {
            Some(Hit::Cell { row, frame }) => {
                let r =
                    Rect::from_min_size(Pos2::new(x_of(frame), y_of(row)), Vec2::new(CELL, ROW));
                painter.rect_filled(r, 0.0, Colors::HOVER);
            }
            Some(Hit::Name { row, .. }) => {
                let r = Rect::from_min_size(Pos2::new(view.min.x, y_of(row)), Vec2::new(NAME, ROW));
                painter.rect_filled(r, 0.0, Colors::HOVER);
            }
            _ => {}
        }
        if let Some([a, b]) = p.drag {
            let (r, c) = ((a.0.min(b.0), a.0.max(b.0)), (a.1.min(b.1), a.1.max(b.1)));
            let boxed = Rect::from_min_max(
                Pos2::new(x_of(c.0), y_of(r.0)),
                Pos2::new(x_of(c.1 + 1), y_of(r.1 + 1)),
            );
            painter.rect_stroke(
                boxed,
                0.0,
                Stroke::new(1.0, Color32::WHITE),
                egui::StrokeKind::Inside,
            );
        }
        // The name column and the frame strip, over the cells.
        let names = Rect::from_min_size(view.min, Vec2::new(NAME, view.height()));
        painter.rect_filled(names, 0.0, Colors::BACK);
        let font = FontId::proportional(11.0);
        for (r, row) in rows.iter().enumerate().take(r1).skip(r0) {
            let y = y_of(r);
            let line = Rect::from_min_size(Pos2::new(view.min.x, y), Vec2::new(NAME, ROW));
            let picked = row_selected(doc, p, &row.kind);
            let header = matches!(row.kind, RowKind::Header(_));
            let fill = match (header, picked) {
                (true, _) => Colors::HEADER,
                (_, true) => Colors::PICKED,
                _ => Colors::BACK,
            };
            painter.rect_filled(line, 0.0, fill);
            let mut text = row.label.clone();
            if let RowKind::Header(g) = row.kind {
                let folded = p.folded.contains(&(doc.pmm.selected_model_slot, g));
                text = format!("{} {}", if folded { "▶" } else { "▼" }, text);
                // The margin glyph is the group's saved flag: `+` closed, `-` open
                // (`ui_panel_sweep.cpp:219` and `:243`).
                if let Some(n) = group_flag(doc, g) {
                    let open = active(doc)
                        .and_then(|i| doc.pmm.models[i].selection.group_flags.get(usize::from(n)))
                        .is_some_and(|&f| f != 0);
                    painter.text(
                        Pos2::new(view.min.x + PLUS / 2.0, y + ROW / 2.0),
                        Align2::CENTER_CENTER,
                        if open { "-" } else { "+" },
                        font.clone(),
                        Color32::GRAY,
                    );
                }
            } else {
                painter.text(
                    Pos2::new(view.min.x + PLUS / 2.0, y + ROW / 2.0),
                    Align2::CENTER_CENTER,
                    "+",
                    font.clone(),
                    Color32::GRAY,
                );
            }
            painter.text(
                Pos2::new(view.min.x + PLUS + 4.0, y + ROW / 2.0),
                Align2::LEFT_CENTER,
                text,
                font.clone(),
                Color32::LIGHT_GRAY,
            );
        }
        let strip = Rect::from_min_size(view.min, Vec2::new(view.width(), HEAD));
        painter.rect_filled(strip, 0.0, Colors::HEADER);
        for f in (f0 - f0 % 5..f0 + columns + 5).step_by(5) {
            let x = x_of(f);
            if x >= view.min.x + NAME {
                painter.text(
                    Pos2::new(x + 1.0, view.min.y + HEAD / 2.0),
                    Align2::LEFT_CENTER,
                    f.to_string(),
                    font.clone(),
                    Color32::LIGHT_GRAY,
                );
            }
        }
        painter.text(
            Pos2::new(view.min.x + 4.0, view.min.y + HEAD / 2.0),
            Align2::LEFT_CENTER,
            format!("frame {shown}"),
            font,
            Color32::WHITE,
        );

        let at = |pos: Pos2| hit(pos - view.min, scroll, rows.len());
        if resp.clicked() || resp.double_clicked() {
            if let Some(pos) = resp.interact_pointer_pos() {
                match at(pos) {
                    Hit::Strip(f) => events.push(Event::Strip(f)),
                    Hit::Name { row, plus: true } => events.push(Event::Plus(rows[row].clone())),
                    Hit::Name { row, plus: false } => {
                        events.push(Event::Name(rows[row].clone(), shift))
                    }
                    Hit::Cell { row, frame } => {
                        if let Some(t) = rows[row].track() {
                            events.push(Event::Cell(t, frame, shift));
                        }
                    }
                    Hit::None => {}
                }
            }
        }
        if resp.drag_started() {
            if let Some(Hit::Cell { row, frame }) = resp.interact_pointer_pos().map(at) {
                let grabbed = !shift
                    && !ctx.editor.playing()
                    && rows[row]
                        .track()
                        .is_some_and(|t| grabs_marked_key(doc, t, frame));
                if grabbed {
                    p.key_drag = Some([frame as i32; 2]);
                } else {
                    p.drag = Some([(row, frame); 2]);
                }
            }
        }
        if let (Some([a, _]), Some(pos)) = (p.key_drag, resp.interact_pointer_pos()) {
            let column = ((pos.x - view.min.x - NAME + scroll.x) / CELL).floor() as i32;
            p.key_drag = Some([a, column]);
        }
        if let (Some([a, _]), Some(pos)) = (p.drag, resp.interact_pointer_pos()) {
            if let Hit::Cell { row, frame } = at(pos) {
                p.drag = Some([a, (row, frame)]);
            }
        }
        if resp.drag_stopped() {
            if let Some([a, b]) = p.key_drag.take().filter(|[a, b]| a != b) {
                events.push(Event::Move(b - a));
            }
            if let Some([a, b]) = p.drag.take() {
                let tracks = (a.0.min(b.0)..=a.0.max(b.0))
                    .filter_map(|r| rows[r].track())
                    .collect();
                events.push(Event::Box(tracks, a.1.min(b.1), a.1.max(b.1), shift));
            }
        }
        columns
    });
    let offset = out.state.clamped_offset();
    p.scroll = [offset.x, offset.y];
    p.columns = out.inner;
}

// ---- the panel ---------------------------------------------------------------------------

/// What the frame edit and its slider show: the frame on screen, which is the playback cursor's
/// while playing (the document's current frame only changes when playback stops).
pub fn frame_field(ctx: &Ctx) -> u32 {
    ctx.editor.shown_frame()
}

fn tb(ui: &mut egui::Ui, ctx: &Ctx, run: &mut Vec<&'static str>, id: &'static str, label: &str) {
    if ui
        .add_enabled(ctx.enabled(id), egui::Button::new(label))
        .clicked()
    {
        run.push(id);
    }
}

fn toolbar(
    ui: &mut egui::Ui,
    ctx: &Ctx,
    p: &mut Panel,
    run: &mut Vec<&'static str>,
    ev: &mut Vec<Event>,
) {
    let playing = ctx.editor.playing();
    ui.horizontal(|ui| {
        tb(ui, ctx, run, "ctl:400", "元に戻す");
        tb(ui, ctx, run, "ctl:401", "やり直し");
        ui.separator();
        tb(ui, ctx, run, "ctl:558", "|<");
        tb(ui, ctx, run, "ctl:533", ".<");
        tb(ui, ctx, run, "ctl:418", "＜");
        // The frame on screen: the playback cursor's while playing (the document's current frame
        // only changes when playback stops).
        let mut frame = frame_field(ctx);
        let t = &ctx.editor.doc.pmm.timeline;
        let last = (t.last_registered_frame.max(t.play_stop_frame).max(0) as u32).max(frame);
        let changed = ui
            .add_enabled_ui(!playing, |ui| {
                ui.add(egui::DragValue::new(&mut frame).range(0..=99_999))
                    .changed()
                    | ui.add(egui::Slider::new(&mut frame, 0..=last).show_value(false))
                        .changed()
            })
            .inner;
        if changed {
            ev.push(Event::Seek(frame));
        }
        tb(ui, ctx, run, "ctl:419", "＞");
        tb(ui, ctx, run, "ctl:532", ">.");
        tb(ui, ctx, run, "ctl:559", ">|");
        ui.separator();
        ui.add_enabled(
            !playing,
            egui::DragValue::new(&mut p.goto).range(0..=99_999),
        );
        tb(ui, ctx, run, "ctl:553", "Go");
        tb(ui, ctx, run, "ctl:555", "ｾｯﾄ");
        tb(ui, ctx, run, "ctl:429", "現フレーム");
    });
    ui.horizontal(|ui| {
        tb(ui, ctx, run, "ctl:415", "範囲選択");
        tb(ui, ctx, run, "ctl:416", "縦選択");
        ui.add_enabled_ui(!playing, |ui| {
            ui.add(egui::DragValue::new(&mut p.range[0]).range(0..=99_999));
            ui.label("～");
            ui.add(egui::DragValue::new(&mut p.range[1]).range(0..=99_999));
            let names = scopes(&ctx.editor.doc);
            p.scope = p.scope.min(names.len().saturating_sub(1));
            egui::ComboBox::from_id_salt("timeline scope")
                .selected_text(names.get(p.scope).cloned().unwrap_or_default())
                .show_ui(ui, |ui| {
                    for (i, n) in names.iter().enumerate() {
                        ui.selectable_value(&mut p.scope, i, n);
                    }
                });
        });
        ui.separator();
        tb(ui, ctx, run, "ctl:420", "コピー");
        tb(ui, ctx, run, "ctl:421", "ﾍﾟｰｽﾄ");
        tb(ui, ctx, run, "ctl:422", "反転P");
        tb(ui, ctx, run, "ctl:423", "削　除");
        tb(ui, ctx, run, "ctl:424", "拡大縮小");
    });
    ui.horizontal(|ui| {
        ui.label("補間曲線");
        ui.add_enabled_ui(!playing, |ui| {
            egui::ComboBox::from_id_salt("timeline curve")
                .selected_text(CURVES[p.curve.min(CURVES.len() - 1)])
                .show_ui(ui, |ui| {
                    for (i, n) in CURVES.iter().enumerate() {
                        ui.selectable_value(&mut p.curve, i, *n);
                    }
                });
        });
        tb(ui, ctx, run, "ctl:430", "コピー");
        tb(ui, ctx, run, "ctl:431", "ペースト");
        tb(ui, ctx, run, "ctl:432", "線形補間");
    });
}

/// The side of the curve box in points; curve units (0 to 127) scale to it.
const CURVE_BOX: f32 = 96.0;

/// The curve panel: the curve of the first marked key and its two control points, which drag.
fn curve_box(ui: &mut egui::Ui, ctx: &Ctx, p: &mut Panel, events: &mut Vec<Event>) {
    let (rect, resp) = ui.allocate_exact_size(Vec2::splat(CURVE_BOX), Sense::drag());
    let painter = ui.painter_at(rect);
    painter.rect_filled(rect, 0.0, Color32::WHITE);
    let unit = CURVE_BOX / 127.0;
    // Curve units to the screen, y up.
    let to_screen = |c: [u8; 2]| {
        Pos2::new(
            rect.min.x + f32::from(c[0]) * unit,
            rect.max.y - f32::from(c[1]) * unit,
        )
    };
    let Some(points) = curve_points(&ctx.editor.doc, p.curve) else {
        return;
    };
    let [a, b] = points.map(to_screen);
    painter.add(egui::epaint::CubicBezierShape::from_points_stroke(
        [to_screen([0, 0]), a, b, to_screen([127, 127])],
        false,
        Color32::TRANSPARENT,
        Stroke::new(1.5, Color32::BLACK),
    ));
    painter.line_segment([to_screen([0, 0]), a], Stroke::new(1.0, Color32::BLACK));
    painter.line_segment([to_screen([127, 127]), b], Stroke::new(1.0, Color32::BLACK));
    for c in [a, b] {
        let arm = Vec2::splat(3.0);
        painter.line_segment([c - arm, c + arm], Stroke::new(2.0, Color32::RED));
        painter.line_segment(
            [c + Vec2::new(arm.x, -arm.y), c + Vec2::new(-arm.x, arm.y)],
            Stroke::new(2.0, Color32::RED),
        );
    }
    if ctx.editor.playing() {
        return;
    }
    // The point within reach of the press is the one that follows the pointer.
    if resp.drag_started() {
        p.curve_drag = resp.interact_pointer_pos().and_then(|pos| {
            let near = |c: Pos2| c.distance(pos) <= 8.0;
            [(false, a), (true, b)]
                .into_iter()
                .filter(|(_, c)| near(*c))
                .min_by(|x, y| x.1.distance(pos).total_cmp(&y.1.distance(pos)))
                .map(|(end, _)| end)
        });
    }
    if let (Some(end), Some(pos)) = (p.curve_drag, resp.interact_pointer_pos()) {
        let at = |v: f32| (v / unit).round() as i32;
        events.push(Event::Curve(
            end,
            [at(pos.x - rect.min.x), at(rect.max.y - pos.y)],
        ));
    }
    if resp.drag_stopped() {
        p.curve_drag = None;
    }
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let mut p = panel(ctx);
    let (mut run, mut events) = (Vec::new(), Vec::new());
    ui.vertical(|ui| {
        ui.horizontal(|ui| {
            ui.vertical(|ui| toolbar(ui, ctx, &mut p, &mut run, &mut events));
            curve_box(ui, ctx, &mut p, &mut events);
        });
        grid(ui, ctx, &mut p, &mut events);
    });
    set_panel(ctx, p);
    for id in run {
        ctx.run(id);
    }
    for e in events {
        if let Err(m) = run_event(ctx, e) {
            *ctx.status = m;
        }
    }
}

// ---- the keys ----------------------------------------------------------------------------

/// The arrows' hold state between passes.
#[derive(Clone, Copy, Default)]
struct Arrows {
    repeat: Repeat,
    down: [bool; 4],
}

/// The first system font that has Japanese glyphs. egui's built-in fonts have none, so the bone
/// and morph names of a model would show as boxes.
fn install_japanese_font(ctx: &egui::Context) {
    const CANDIDATES: &[&str] = &[
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "C:\\Windows\\Fonts\\YuGothR.ttc",
        "C:\\Windows\\Fonts\\msgothic.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ];
    let id = Id::unique("mds-app japanese font");
    if ctx.data(|d| d.get_temp::<bool>(id)).is_some() {
        return;
    }
    ctx.data_mut(|d| d.insert_temp(id, true));
    let Some(bytes) = CANDIDATES.iter().find_map(|p| std::fs::read(p).ok()) else {
        return;
    };
    let families = [egui::FontFamily::Proportional, egui::FontFamily::Monospace]
        .map(|family| egui::epaint::text::InsertFontFamily {
            family,
            priority: egui::epaint::text::FontPriority::Lowest,
        })
        .to_vec();
    ctx.add_font(egui::epaint::text::FontInsert::new(
        "japanese",
        egui::FontData::from_owned(bytes),
        families,
    ));
}

pub fn pass(ui: &mut egui::Ui, ctx: &mut Ctx) {
    install_japanese_font(ui.ctx());
    let id = Id::unique("timeline-arrows");
    let mut s: Arrows = ui.data(|d| d.get_temp(id)).unwrap_or_default();
    let free = !ui.ctx().egui_wants_keyboard_input() && !ctx.editor.playing();
    let (dt, ctrl, keys) = ui.input(|i| {
        let ctrl = i.modifiers.command || i.modifiers.ctrl;
        let keys = [
            Key::ArrowLeft,
            Key::ArrowRight,
            Key::ArrowUp,
            Key::ArrowDown,
        ]
        .map(|k| free && i.key_down(k));
        (i.unstable_dt, ctrl, keys)
    });
    let ids = [
        ("key:Left", Some("key:Ctrl+Left")),
        ("key:Right", Some("key:Ctrl+Right")),
        ("key:Up", None),
        ("key:Down", None),
    ];
    for (k, (action, jump)) in ids.into_iter().enumerate() {
        let state = KeyState::of(s.down[k], keys[k]);
        s.down[k] = keys[k];
        match jump {
            // Ctrl jumps to a keyframe on the press and does not repeat.
            Some(jump) if ctrl => {
                if state == KeyState::Pressed {
                    ctx.run(jump);
                }
            }
            _ => {
                if s.repeat.step(state, false, dt) {
                    ctx.run(action);
                }
            }
        }
    }
    ui.data_mut(|d| d.insert_temp(id, s));
}
