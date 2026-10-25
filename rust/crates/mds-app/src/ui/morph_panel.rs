//! The `morph-panel` area: four lanes (eyebrow, eye, lip, other), each with a morph combo, a
//! weight slider and edit, previous and next buttons, and a register button; and the panel's
//! collapse and expand buttons.
//!
//! * Combo 504, 509, 514, 519: `MorphRowSelect` (`src/window/command_dispatch.cpp:109`).
//! * Slider 505, 510, 515, 520: `HandleMorphSlider` (`src/window/ui_hscroll.cpp:95`), 0 to 100.
//! * Edit 506, 511, 516, 521: `CommitEditControl` (`src/window/ui_edit_commit.cpp:405`).
//! * Previous and next 507 to 523: `MorphStep` (`src/window/command_frame_register.cpp:253`).
//! * Register 525, 524, 527, 526 for lanes 0 to 3 (`command_frame_register.cpp:496`).
//! * Collapse and expand 528 and 529 (`command_frame_register.cpp:528`): the panel's rows are
//!   hidden or shown. The C++ keeps the state in `options[5]` of the PMM, which no command sets,
//!   so here it only lives in the window.
//!
//! The C++ disables 504 to 527 while playing (`StartPlayback`, `src/app/playback_state.cpp:337`),
//! and so does the table through `needs_document`.

use super::model_panel::selected_index;
use super::Ctx;
use crate::actions::Action;
use mds_doc::{Command, Document, ModelFile};

const ACTIONS: &[Action] = &[
    Action::inline("ctl:504"),
    Action::inline("ctl:505"),
    Action::inline("ctl:506"),
    Action::run("ctl:507", |c| step(c, 0, false), true),
    Action::run("ctl:508", |c| step(c, 0, true), true),
    Action::inline("ctl:509"),
    Action::inline("ctl:510"),
    Action::inline("ctl:511"),
    Action::run("ctl:512", |c| step(c, 1, false), true),
    Action::run("ctl:513", |c| step(c, 1, true), true),
    Action::inline("ctl:514"),
    Action::inline("ctl:515"),
    Action::inline("ctl:516"),
    Action::run("ctl:517", |c| step(c, 2, false), true),
    Action::run("ctl:518", |c| step(c, 2, true), true),
    Action::inline("ctl:519"),
    Action::inline("ctl:520"),
    Action::inline("ctl:521"),
    Action::run("ctl:522", |c| step(c, 3, false), true),
    Action::run("ctl:523", |c| step(c, 3, true), true),
    Action::run("ctl:525", |c| register(c, 0), true),
    Action::run("ctl:524", |c| register(c, 1), true),
    Action::run("ctl:527", |c| register(c, 2), true),
    Action::run("ctl:526", |c| register(c, 3), true),
    Action::inline("ctl:528"),
    Action::inline("ctl:529"),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

/// The control ids of each lane: combo, slider, edit, previous, next, register.
const LANES: [[&str; 6]; 4] = [
    ["ctl:504", "ctl:505", "ctl:506", "ctl:507", "ctl:508", "ctl:525"],
    ["ctl:509", "ctl:510", "ctl:511", "ctl:512", "ctl:513", "ctl:524"],
    ["ctl:514", "ctl:515", "ctl:516", "ctl:517", "ctl:518", "ctl:527"],
    ["ctl:519", "ctl:520", "ctl:521", "ctl:522", "ctl:523", "ctl:526"],
];
const LANE_NAMES: [&str; 4] = ["eyebrow", "eye", "lip", "other"];

/// The panel number of a morph in the model file; lane `n` lists panel `n + 1`.
fn panels(file: &ModelFile) -> Vec<u8> {
    match file {
        ModelFile::Pmx(p) => p.morphs.iter().map(|m| m.panel).collect(),
        ModelFile::Pmd(p) => p.morphs.iter().map(|m| m.panel).collect(),
        ModelFile::Missing => Vec::new(),
    }
}

/// The morphs of the selected model that lane `lane` lists, as `(index, name)`.
pub fn lane_morphs(doc: &Document, lane: u8) -> Vec<(u32, String)> {
    let Some(i) = selected_index(doc) else {
        return Vec::new();
    };
    let names = &doc.pmm.models[i].morph_names;
    panels(&doc.models[i])
        .iter()
        .zip(names)
        .enumerate()
        .filter(|(_, (&p, _))| p == lane + 1)
        .map(|(n, (_, name))| (n as u32, name.text.clone()))
        .collect()
}

/// The morph that lane `lane` has selected (`selectedMorphs`), if it is one.
pub fn selected(doc: &Document, lane: u8) -> Option<u32> {
    let m = doc.selected_model()?;
    u32::try_from(m.selection.selected_morphs[usize::from(lane)])
        .ok()
        .filter(|&n| (n as usize) < m.morph_pose.len())
}

/// Whether the selected model is a PMX (`physicsMode == 2`), the only kind whose morph 0 is one
/// the panel steps to or edits.
fn is_pmx(doc: &Document) -> bool {
    selected_index(doc).is_some_and(|i| matches!(doc.models[i], ModelFile::Pmx(_)))
}

/// Picking a combo entry (`MorphRowSelect`): the first morph of that name is the selection.
pub fn pick(ctx: &mut Ctx, lane: u8, morph: u32) -> Result<(), String> {
    let doc = &ctx.editor.doc;
    let i = selected_index(doc).ok_or("no model selected")?;
    let names = &doc.pmm.models[i].morph_names;
    let name = names.get(morph as usize).ok_or("no such morph")?;
    let first = names.iter().position(|n| n.raw == name.raw).unwrap_or(0);
    ctx.editor.apply(Command::SelectMorphLane {
        lane,
        morph: first as u32,
    })
}

/// The slider moved to `pos` (0 to 100). Nothing happens without a selected morph, or on morph 0
/// of a PMD.
pub fn slide(ctx: &mut Ctx, lane: u8, pos: i32) -> Result<(), String> {
    let doc = &ctx.editor.doc;
    let Some(morph) = selected(doc, lane) else {
        return Ok(());
    };
    if morph == 0 && !is_pmx(doc) {
        return Ok(());
    }
    let value = (f64::from(pos.clamp(0, 100)) / 100.0) as f32;
    ctx.editor.apply(Command::SetMorph { morph, value })
}

/// The edit committed with `text`: `atof` of its first 7 characters.
pub fn commit(ctx: &mut Ctx, lane: u8, text: &str) -> Result<(), String> {
    let Some(morph) = selected(&ctx.editor.doc, lane) else {
        return Ok(());
    };
    let value = atof(text, 8) as f32;
    ctx.editor.apply(Command::SetMorph { morph, value })
}

/// `atof` of `GetWindowTextA(edit, buf, max)`: the longest leading decimal number, else 0.
fn atof(text: &str, max: usize) -> f64 {
    let end = text.char_indices().nth(max - 1).map_or(text.len(), |(i, _)| i);
    let s = text[..end].trim_start();
    (1..=s.len())
        .rev()
        .filter(|&n| s.is_char_boundary(n))
        .find_map(|n| s[..n].parse::<f64>().ok())
        .unwrap_or(0.0)
}

/// `MorphStep`: from the lane's selected morph, step by one with a wrap, skipping morphs outside
/// the eyebrow panel, until one is found or the walk is back at the start. The C++ tests the
/// eyebrow panel in all four lanes, not the lane's own; this follows it.
fn step(ctx: &mut Ctx, lane: u8, next: bool) -> Result<(), String> {
    let doc = &ctx.editor.doc;
    let i = selected_index(doc).ok_or("no model selected")?;
    let Some(start) = selected(doc, lane) else {
        return Ok(());
    };
    if start == 0 && !is_pmx(doc) {
        return Ok(());
    }
    let panels = panels(&doc.models[i]);
    let count = doc.pmm.models[i].morph_names.len() as u32;
    let mut at = start;
    let found = loop {
        at = match (next, at) {
            (true, n) if n + 1 >= count => 0,
            (true, n) => n + 1,
            (false, 0) => count - 1,
            (false, n) => n - 1,
        };
        if at == start {
            return Ok(());
        }
        if panels.get(at as usize) == Some(&EYEBROW) {
            break at;
        }
    };
    ctx.editor.apply(Command::SelectMorphLane { lane, morph: found })
}

/// `mdl::MorphPanel::eyebrow`.
const EYEBROW: u8 = 1;

/// A register button: the lane's selected morph at the current frame. A lane with no selected
/// morph registers -1, which only clears the key marks (`tests/fixtures/rust/script/README.md`).
fn register(ctx: &mut Ctx, lane: u8) -> Result<(), String> {
    let doc = &ctx.editor.doc;
    let m = doc.selected_model().ok_or("no model selected")?;
    let morph = m.selection.selected_morphs[usize::from(lane)];
    ctx.editor.apply(Command::RegisterMorphKey(morph))
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    let id = egui::Id::unique("morph-panel-expanded");
    let Some(i) = selected_index(&ctx.editor.doc) else {
        ui.label("no model selected");
        return;
    };
    let initial = ctx.editor.doc.pmm.settings.options[5] != 0;
    let expanded: bool = ui.data(|d| d.get_temp(id)).unwrap_or(initial);
    // 528 collapses and 529 expands; each shows while the other state holds.
    if expanded && ui.small_button("-").clicked() {
        ui.data_mut(|d| d.insert_temp(id, false));
    } else if !expanded && ui.small_button("+").clicked() {
        ui.data_mut(|d| d.insert_temp(id, true));
    }
    if !expanded {
        return;
    }
    let playing = ctx.editor.playing();
    for lane in 0..4u8 {
        let [combo, _, _, previous, next, register] = LANES[usize::from(lane)];
        ui.separator();
        ui.label(LANE_NAMES[usize::from(lane)]);
        let current = selected(&ctx.editor.doc, lane);
        let name = |n: u32| {
            ctx.editor.doc.pmm.models[i]
                .morph_names
                .get(n as usize)
                .map_or_else(String::new, |n| n.text.clone())
        };
        let mut picked = None;
        ui.add_enabled_ui(!playing, |ui| {
            egui::ComboBox::from_id_salt(combo)
                .selected_text(current.map_or_else(String::new, name))
                .show_ui(ui, |ui| {
                    for (n, text) in lane_morphs(&ctx.editor.doc, lane) {
                        if ui.selectable_label(current == Some(n), text).clicked() {
                            picked = Some(n);
                        }
                    }
                });
        });
        if let Some(n) = picked {
            if let Err(e) = pick(ctx, lane, n) {
                *ctx.status = e;
            }
        }
        let value = current.map_or(0.0, |n| ctx.editor.doc.pmm.models[i].morph_pose[n as usize]);
        ui.horizontal(|ui| {
            super::button(ui, ctx, previous, "<<");
            super::button(ui, ctx, next, ">>");
            super::button(ui, ctx, register, "register");
        });
        ui.add_enabled_ui(!playing && current.is_some(), |ui| {
            let mut pos = (f64::from(value) * 100.0) as i32;
            if ui
                .add(egui::Slider::new(&mut pos, 0..=100).show_value(false))
                .changed()
            {
                if let Err(e) = slide(ctx, lane, pos) {
                    *ctx.status = e;
                }
            }
            let key = egui::Id::unique(("morph-edit", lane));
            let mut text: String = ui
                .data(|d| d.get_temp(key))
                .unwrap_or_else(|| format!("{value:5.4}"));
            let response = ui.add(egui::TextEdit::singleline(&mut text).desired_width(60.0));
            if response.lost_focus() {
                ui.data_mut(|d| d.remove::<String>(key));
                if let Err(e) = commit(ctx, lane, &text) {
                    *ctx.status = e;
                }
            } else if response.has_focus() {
                ui.data_mut(|d| d.insert_temp(key, text));
            }
        });
    }
}

pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}
