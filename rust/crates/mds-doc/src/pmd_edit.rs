//! The model edits that the PMD writer ("save enhanced model", menu 263,
//! `SaveEnhancedModel`, `src/window/enhance_model_io.cpp`) saves: the
//! English names, the toon file names and the physics model of a PMD.

use crate::add_model::sjis;
use crate::{not, Document, Error, ModelFile, PhysicsField};
use mds_formats::pmd::{Joint, Pmd, Rigid};
use mds_formats::text::{decode_sjis, FixedSjis};

/// The English name the dialog of menu 259 edits
/// (`CollectEnglishNameEdit`, `src/window/english_name_dialog.cpp` 118-205,
/// and `ApplyEnglishNameDialog` 325-362).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EnglishName {
    /// `nameEn`, at most 19 bytes. The PMM saves it too.
    Model,
    /// `commentEn`, at most 255 bytes, without `\r`.
    Comment,
    /// Bone `n`, at most 19 bytes.
    Bone(u32),
    /// Morph `n` of the PMD, `n >= 1` (the base morph has none), at most 19
    /// bytes.
    Morph(u32),
    /// Bone group `n` of the PMD (`Pmd::bone_groups`), at most 49 bytes.
    Group(u32),
}

/// `strcpy_s`: the bytes and a NUL; the rest of the buffer keeps what it
/// held, and the writer saves the whole buffer.
fn strcpy<const N: usize>(f: &mut FixedSjis<N>, bytes: &[u8]) -> Result<(), Error> {
    if bytes.len() >= N {
        return Err(not("a name longer than its buffer (strcpy_s fails)"));
    }
    f.raw[..bytes.len()].copy_from_slice(bytes);
    f.raw[bytes.len()] = 0;
    f.text = decode_sjis(&f.raw);
    Ok(())
}

/// The dialog's text cut to `max` bytes (`buf[max] = 0`).
fn cut(text: &str, max: usize) -> Vec<u8> {
    let mut raw = sjis(text, usize::MAX).raw;
    raw.truncate(max);
    raw
}

impl Document {
    pub(crate) fn selected_pmd(&mut self) -> Result<(usize, &mut Pmd), Error> {
        let i = self.active_model()?;
        match &mut self.models[i] {
            ModelFile::Pmd(p) => Ok((i, p)),
            _ => Err(not(
                "an edit of the PMD writer on a model that is not a PMD",
            )),
        }
    }

    /// [`crate::Command::SetEnglishName`]. The C++ writes the name on OK and
    /// on cancel alike; a PMX model takes only [`EnglishName::Model`], which
    /// the PMM saves (its other English names are never saved).
    pub(crate) fn set_english_name(&mut self, name: EnglishName, text: &str) -> Result<(), Error> {
        let i = self.active_model()?;
        if name == EnglishName::Model {
            self.pmm.models[i].name_en = mds_formats::text::Sjis::from_raw(cut(text, 19));
            if !matches!(self.models[i], ModelFile::Pmd(_)) {
                return Ok(());
            }
        }
        let (_, pmd) = self.selected_pmd()?;
        let e = pmd
            .extension
            .as_mut()
            .and_then(|x| x.english.as_mut())
            .ok_or(not("a PMD without English names"))?;
        let at = |n: u32| n as usize;
        match name {
            EnglishName::Model => strcpy(&mut e.name, &cut(text, 19)),
            EnglishName::Comment => {
                let mut raw = cut(text, 255);
                raw.retain(|&b| b != b'\r');
                strcpy(&mut e.comment, &raw)
            }
            EnglishName::Bone(n) => strcpy(
                e.bone_names.get_mut(at(n)).ok_or(not("no such bone"))?,
                &cut(text, 19),
            ),
            EnglishName::Morph(n) => strcpy(
                at(n)
                    .checked_sub(1)
                    .and_then(|n| e.morph_names.get_mut(n))
                    .ok_or(not("no such morph"))?,
                &cut(text, 19),
            ),
            EnglishName::Group(n) => strcpy(
                e.group_names
                    .get_mut(at(n))
                    .ok_or(not("no such bone group"))?,
                &cut(text, 49),
            ),
        }
    }

    /// [`crate::Command::SetToonFileNames`].
    pub(crate) fn set_toon_file_names(&mut self, names: &[String; 10]) -> Result<(), Error> {
        let (_, pmd) = self.selected_pmd()?;
        let x = pmd
            .extension
            .as_mut()
            .ok_or(not("a PMD without the toon section"))?;
        for (i, (name, slot)) in names.iter().zip(&mut x.toon_textures).enumerate() {
            if *name == format!("toon{:02}.bmp", i + 1) {
                continue;
            }
            strcpy(slot, &cut(name, 255))?;
        }
        Ok(())
    }

    /// [`crate::Command::SetPhysicsModel`]. The skeleton's rigid-body flags
    /// follow the new bodies.
    pub(crate) fn set_physics_model(
        &mut self,
        rigids: Vec<Rigid>,
        joints: Vec<Joint>,
    ) -> Result<(), Error> {
        let (i, pmd) = self.selected_pmd()?;
        let x = pmd
            .extension
            .as_mut()
            .ok_or(not("a PMD without the toon section"))?;
        x.physics = Some(mds_formats::pmd::Physics {
            rigids,
            joints: Some(joints),
        });
        self.skeletons[i] = crate::model::Skeleton::new(&self.models[i], &self.pmm.models[i]);
        Ok(())
    }

    /// [`crate::Command::EditPhysicsRecord`], `EditModeRecord`
    /// (`frame_modes_bone.cpp` 158-224): `v - dy * step` in double, stored
    /// as a float; the size floor is the float 0.1. The C++ echoes the value
    /// into the dialog's edit box; that box is the caller's.
    pub(crate) fn edit_physics_record(
        &mut self,
        joint: bool,
        index: u32,
        field: PhysicsField,
        axis: u8,
        dy: i32,
    ) -> Result<(), Error> {
        let (rigids, joints) = self
            .edit
            .physics_scratch
            .as_mut()
            .ok_or(not("the physics model dialog is closed"))?;
        let (a, i) = (usize::from(axis), index as usize);
        if a > 2 {
            return Err(not("no such axis"));
        }
        // `kAccDrag` (62) and `kStep`, the float 0.05 widened (195).
        let step = |v: f32, s: f64| (f64::from(v) - f64::from(dy) * s) as f32;
        let (rotation, position) = (0.01, f64::from(0.05f32));
        if joint {
            let j = joints.get_mut(i).ok_or(not("no such joint"))?;
            match field {
                PhysicsField::Rotation => j.rotation[a] = step(j.rotation[a], rotation),
                PhysicsField::Position => j.position[a] = step(j.position[a], position),
                PhysicsField::Size => return Err(not("a joint has no size")),
            }
        } else {
            let r = rigids.get_mut(i).ok_or(not("no such rigid body"))?;
            match field {
                PhysicsField::Rotation => r.rotation[a] = step(r.rotation[a], rotation),
                PhysicsField::Position => r.position[a] = step(r.position[a], position),
                PhysicsField::Size => {
                    let v = step(r.size[a], position);
                    r.size[a] = if v < 0.1 { 0.1 } else { v };
                }
            }
        }
        Ok(())
    }

    /// [`crate::Command::SetModelPath`]: `wcscpy_s(model.path, 0x100, path)`
    /// (`enhance_model_io.cpp` 357), which the PMM saves.
    pub(crate) fn set_model_path(&mut self, slot: u8, path: &str) -> Result<(), Error> {
        let m = self
            .pmm
            .models
            .iter_mut()
            .find(|m| m.slot == slot)
            .ok_or(not("no model in that slot"))?;
        let raw = sjis(path, 256).raw;
        let p = &mut m.path;
        p.raw.fill(0);
        p.raw[..raw.len()].copy_from_slice(&raw);
        p.text = path.to_string();
        Ok(())
    }
}
