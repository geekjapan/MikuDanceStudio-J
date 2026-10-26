//! The modal list dialogs and the English name dialog as the script's
//! `dialog` lines drive them (`tests/fixtures/rust/script4/README.md`,
//! `../script3/README.md`): the dialog-local state between the controls
//! and the [`Command`]s their buttons send.

use super::{atol, e};
use crate::{Command, Document, EnglishName, ModelFile, OutsideParent};

fn item(s: &str) -> Result<usize, String> {
    s.parse().map_err(|_| format!("bad item {s}"))
}

/// The list box rows of the order dialogs, up (630) and down (631).
#[derive(Default)]
struct Rows {
    slots: Vec<u8>,
    sel: Option<usize>,
}

impl Rows {
    fn select(&mut self, i: usize) -> Result<(), String> {
        if i >= self.slots.len() {
            return Err(format!("no row {i}"));
        }
        self.sel = Some(i);
        Ok(())
    }

    fn step(&mut self, up: bool) {
        let Some(s) = self.sel else { return };
        let to = match up {
            true => s.checked_sub(1),
            false => Some(s + 1).filter(|&n| n < self.slots.len()),
        };
        if let Some(to) = to {
            self.slots.swap(s, to);
            self.sel = Some(to);
        }
    }
}

/// The model draw order (menu 288) or calculation order (menu 289) dialog
/// (`model_order_dialog.cpp`): the models in combo order or in calculation
/// order, OK 632.
pub(super) struct ModelOrderDialog {
    calc: bool,
    rows: Rows,
}

impl ModelOrderDialog {
    pub(super) fn open(doc: &Document, calc: bool) -> ModelOrderDialog {
        let mut models: Vec<_> = doc.pmm.models.iter().collect();
        models.sort_by_key(|m| match calc {
            true => m.display_order,
            false => m.selection.combo_index,
        });
        let slots = models.into_iter().map(|m| m.slot).collect();
        ModelOrderDialog {
            calc,
            rows: Rows { slots, sel: None },
        }
    }

    pub(super) fn run(&mut self, doc: &mut Document, w: &[&str]) -> Result<bool, String> {
        match w {
            ["select", "628", i] => self.rows.select(item(i)?)?,
            ["click", "630"] => self.rows.step(true),
            ["click", "631"] => self.rows.step(false),
            ["click", "632"] => {
                let slots = std::mem::take(&mut self.rows.slots);
                let cmd = match self.calc {
                    true => Command::SetModelCalcOrder(slots),
                    false => Command::SetModelDrawOrder(slots),
                };
                doc.apply(cmd).map_err(e)?;
                return Ok(true);
            }
            ["cancel"] => return Ok(true),
            _ => return Err("not ported".into()),
        }
        Ok(false)
    }
}

/// The accessory order dialog of menu 249 (`AccessorySettingsDlgProc`,
/// `command_file_menu.cpp` 741-900): the combo rows and their texts, the
/// name edit 629 and the render split count edit 635.
pub(super) struct AccessoryOrderDialog {
    rows: Rows,
    names: Vec<String>,
    name: String,
    split: String,
}

impl AccessoryOrderDialog {
    pub(super) fn open(doc: &Document) -> AccessoryOrderDialog {
        let a = &doc.pmm.accessories;
        AccessoryOrderDialog {
            rows: Rows {
                slots: a.iter().map(|a| a.slot).collect(),
                sel: None,
            },
            names: a.iter().map(|a| a.list_name.text.clone()).collect(),
            name: String::new(),
            split: doc.pmm.physics.accessory_render_order.to_string(),
        }
    }

    /// `EN_CHANGE` of 635: the count clamped to `0..=` the rows (the text
    /// rewritten when clamped), and the row of that number selected.
    fn split_changed(&mut self) {
        let count = self.rows.slots.len() as i64;
        let mut n = atol(&self.split, 256);
        if n > 0 {
            if n > count {
                n = count;
                self.split = count.to_string();
            }
        } else {
            n = 0;
            self.split = "0".into();
        }
        self.rows.sel = (n < count).then_some(n as usize);
    }

    pub(super) fn run(&mut self, doc: &mut Document, w: &[&str]) -> Result<bool, String> {
        match w {
            ["select", "628", i] => {
                let i = item(i)?;
                self.rows.select(i)?;
                self.name = self.names[i].clone();
            }
            ["click", c @ ("630" | "631")] => {
                let before = self.rows.sel;
                self.rows.step(*c == "630");
                if let (Some(a), Some(b)) = (before, self.rows.sel) {
                    self.names.swap(a, b);
                }
            }
            ["text", "629", t] => self.name = t.to_string(),
            ["text", "635", t] => {
                self.split = t.to_string();
                self.split_changed();
            }
            // The click focuses the button, so the focus is not on 635.
            ["click", "633"] => {
                let text = super::edit_text(&self.name, 256);
                if let Some(s) = self.rows.sel.filter(|_| !text.is_empty()) {
                    self.names[s] = text.to_string();
                }
            }
            ["click", "632"] => {
                for (&slot, name) in self.rows.slots.iter().zip(&self.names) {
                    let a = doc.pmm.accessories.iter().find(|a| a.slot == slot);
                    if a.is_some_and(|a| a.list_name.text != *name) {
                        let cmd = Command::RenameAccessory {
                            slot,
                            name: name.clone(),
                        };
                        doc.apply(cmd).map_err(e)?;
                    }
                }
                let slots = self.rows.slots.clone();
                doc.apply(Command::SetAccessoryOrder(slots)).map_err(e)?;
                let split = atol(&self.split, 256) as i32;
                doc.apply(Command::SetAccessoryRenderSplit(split))
                    .map_err(e)?;
                return Ok(true);
            }
            ["cancel"] => return Ok(true),
            _ => return Err("not ported".into()),
        }
        Ok(false)
    }
}

/// The outside-parent dialog of button 442 (`SelectNavDlgProc`,
/// `dialog_select_ops.cpp`): the copy of the selected model's selector
/// records it edits, and the cursors of combos 669 (the selector), 673
/// (none, ground, then the models in calculation order) and 677 (the
/// target bone).
pub(super) struct OutsideParentDialog {
    records: Vec<OutsideParent>,
    models: Vec<u8>,
    bones: Vec<u32>,
    selector: usize,
    target: usize,
}

impl OutsideParentDialog {
    /// `InitSelectNavDialog` (113-196) and `SyncSelectAttachCombo`.
    pub(super) fn open(doc: &Document) -> Result<OutsideParentDialog, String> {
        if doc.camera_mode() {
            return Err("button 442 is a model-mode button".into());
        }
        let m = doc.selected_model().ok_or("no model selected")?;
        let records = m
            .selector_pose
            .iter()
            .map(|s| match (s[2], s[3]) {
                (-2, _) => OutsideParent::Ground,
                (model, bone) if model >= 0 => OutsideParent::Bone {
                    model: model as u8,
                    bone: bone.max(0) as u32,
                },
                _ => OutsideParent::None,
            })
            .collect();
        let mut order: Vec<_> = doc.pmm.models.iter().collect();
        order.sort_by_key(|m| m.display_order);
        let at = m.selection.selected_bone;
        let selector = m
            .selector_bones
            .iter()
            .rposition(|&b| b == at)
            .filter(|&k| k > 0)
            .unwrap_or(1);
        let mut d = OutsideParentDialog {
            records,
            models: order.into_iter().map(|m| m.slot).collect(),
            bones: Vec::new(),
            selector,
            target: 0,
        };
        d.sync(doc);
        Ok(d)
    }

    /// `SyncSelectAttachCombo` (203-229) and `RebuildTargetBoneList` with
    /// the selection kept.
    fn sync(&mut self, doc: &Document) {
        self.target = match self.records.get(self.selector) {
            Some(OutsideParent::Ground) => 1,
            Some(OutsideParent::Bone { model, .. }) => self
                .models
                .iter()
                .position(|s| s == model)
                .map_or(0, |k| k + 2),
            _ => 0,
        };
        self.target_bones(doc);
    }

    fn target_bones(&mut self, doc: &Document) {
        self.bones = match self.target.checked_sub(2) {
            Some(k) => doc.accessory_parent_bones(self.models[k]),
            None => Vec::new(),
        };
    }

    fn record(&mut self) -> Result<&mut OutsideParent, String> {
        self.records
            .get_mut(self.selector)
            .ok_or_else(|| "no such selector".into())
    }

    pub(super) fn run(&mut self, doc: &mut Document, w: &[&str]) -> Result<bool, String> {
        match w {
            ["select", "669", i] => {
                let i = item(i)?;
                if i >= self.records.len() {
                    return Err(format!("no selector {i}"));
                }
                self.selector = i;
                self.sync(doc);
            }
            // `RebuildTargetBoneList` with the selection reset: bone 0.
            ["select", "673", i] => {
                let i = item(i)?;
                let record = match i.checked_sub(2) {
                    None if i == 0 => OutsideParent::None,
                    None => OutsideParent::Ground,
                    Some(k) => OutsideParent::Bone {
                        model: *self.models.get(k).ok_or("no such model")?,
                        bone: 0,
                    },
                };
                self.target = i;
                *self.record()? = record;
                self.target_bones(doc);
            }
            // `CommitTargetBonePick`.
            ["select", "677", i] => {
                let i = item(i)?;
                let bone = *self.bones.get(i).ok_or("no such bone")?;
                if let OutsideParent::Bone { bone: b, .. } = self.record()? {
                    *b = bone;
                }
            }
            ["click", "630"] => {
                let parent = *self.record()?;
                let cmd = Command::ApplyOutsideParent {
                    selector: self.selector as u32,
                    parent,
                };
                doc.apply(cmd).map_err(e)?;
            }
            ["click", "632"] => {
                let cmd = Command::RegisterOutsideParents(self.records.clone());
                doc.apply(cmd).map_err(e)?;
            }
            // Its cancel ends the dialog with IDOK.
            ["cancel"] => {
                doc.apply(Command::CloseOutsideParentDialog).map_err(e)?;
                return Ok(true);
            }
            _ => return Err("not ported".into()),
        }
        Ok(false)
    }
}

/// The English name dialog of menu 259 (`EnglishNameDlgProc`,
/// `english_name_dialog.cpp`): edits 667 (model), 668 (comment), 672
/// (bone), 676 (morph) and 680 (group), and the cursors of combos 669, 673
/// and 677.
pub(super) struct EnglishDialog {
    texts: [String; 5],
    cursors: [usize; 3],
    counts: [usize; 3],
}

const ENGLISH_EDITS: [&str; 5] = ["667", "668", "672", "676", "680"];

impl EnglishDialog {
    /// `InitEnglishNameDialog` (`english_name_dialog.cpp` 254-323): the
    /// boxes, the edit mode 0, and bone 0 alone selected.
    pub(super) fn open(doc: &mut Document) -> Result<EnglishDialog, String> {
        let i = doc.active().ok_or("no model selected")?;
        let ModelFile::Pmd(pmd) = &doc.models[i] else {
            return Err("the English name dialog on a model that is not a PMD".into());
        };
        let en = pmd
            .extension
            .as_ref()
            .and_then(|x| x.english.as_ref())
            .ok_or("a PMD without English names")?;
        let first = |v: Option<&String>| v.cloned().unwrap_or_default();
        let comment = en.comment.text.replace("\r\n", "\n").replace('\n', "\r\n");
        let d = EnglishDialog {
            texts: [
                doc.pmm.models[i].name_en.text.clone(),
                comment,
                first(en.bone_names.first().map(|n| &n.text)),
                first(en.morph_names.first().map(|n| &n.text)),
                first(en.group_names.first().map(|n| &n.text)),
            ],
            cursors: [0; 3],
            counts: [
                en.bone_names.len(),
                en.morph_names.len(),
                en.group_names.len(),
            ],
        };
        doc.apply(Command::SetEditMode(0)).map_err(e)?;
        doc.apply(Command::SelectBones(vec![0])).map_err(e)?;
        Ok(d)
    }

    /// The names of combo `c` of the selected PMD.
    fn names(doc: &Document, c: usize) -> Vec<String> {
        let e = doc.active().and_then(|i| match &doc.models[i] {
            ModelFile::Pmd(p) => p.extension.as_ref()?.english.as_ref(),
            _ => None,
        });
        let Some(e) = e else { return Vec::new() };
        match c {
            0 => e.bone_names.iter().map(|n| n.text.clone()).collect(),
            1 => e.morph_names.iter().map(|n| n.text.clone()).collect(),
            _ => e.group_names.iter().map(|n| n.text.clone()).collect(),
        }
    }

    /// `CollectEnglishNameEdit` of box `which` (0 model, 1 comment, 2 bone,
    /// 3 morph, 4 group), at the cursor of its combo.
    fn commit(&self, doc: &mut Document, which: usize) -> Result<(), String> {
        let name = match which {
            0 => EnglishName::Model,
            1 => EnglishName::Comment,
            2 => EnglishName::Bone(self.cursors[0] as u32),
            3 => EnglishName::Morph(self.cursors[1] as u32 + 1),
            _ => EnglishName::Group(self.cursors[2] as u32),
        };
        if which >= 2 && self.counts[which - 2] == 0 {
            return Ok(());
        }
        let text = super::edit_text(&self.texts[which], 256).to_string();
        doc.apply(Command::SetEnglishName { name, text }).map_err(e)
    }

    /// `ApplyEnglishNameDialog` (325-362), which OK and cancel both run.
    fn apply(&self, doc: &mut Document) -> Result<(), String> {
        [1, 0, 2, 3, 4]
            .into_iter()
            .try_for_each(|which| self.commit(doc, which))
    }

    pub(super) fn run(&mut self, doc: &mut Document, w: &[&str]) -> Result<bool, String> {
        match w {
            ["text", c, t] => {
                let k = ENGLISH_EDITS
                    .iter()
                    .position(|id| id == c)
                    .ok_or("not ported")?;
                self.texts[k] = t.to_string();
            }
            // `SelectEnglishNameBone`, `Morph`, `Group` (364-450): the box
            // of the old entry committed, then the new entry shown.
            ["select", c @ ("669" | "673" | "677"), i] => {
                let combo = ["669", "673", "677"].iter().position(|x| x == c).unwrap();
                let i = item(i)?;
                if i >= self.counts[combo] {
                    return Err(format!("no item {i}"));
                }
                self.commit(doc, 2 + combo)?;
                self.cursors[combo] = i;
                self.texts[2 + combo] = Self::names(doc, combo)[i].clone();
                if combo == 0 {
                    let m = doc.active().ok_or("no model selected")?;
                    let kind = match &doc.models[m] {
                        ModelFile::Pmd(p) => p.bones.get(i).map_or(0, |b| b.kind),
                        _ => 0,
                    };
                    // Effector, inert tip and co-rotate bones select none.
                    let bones = match kind {
                        6 | 7 | 9 => vec![],
                        _ => vec![i as u32],
                    };
                    doc.apply(Command::SelectBones(bones)).map_err(e)?;
                }
            }
            ["ok"] | ["cancel"] => {
                self.apply(doc)?;
                return Ok(true);
            }
            _ => return Err("not ported".into()),
        }
        Ok(false)
    }
}
