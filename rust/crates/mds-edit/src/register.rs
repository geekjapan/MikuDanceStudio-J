//! The registrars: `key_registrars.cpp` (VMD load and paste), the register
//! buttons (`command_frame_register.cpp`, `command_frame_edit.cpp`), and the
//! paste handler (`frame_clipboard.cpp`).

use crate::link::{attach, full, locate, reset_interpolation, scan_free, slot, Link, Spot};
use crate::{Error, Result, Rig, Tracks};
use mds_formats::key_pool::KeyPool;

/// A bone key as the clipboard or a VMD record carries it
/// (the 0x54-byte parse buffer).
#[derive(Clone, Debug)]
pub struct BoneClip {
    pub name: Vec<u8>,
    pub frame: u32,
    pub rotation: [f32; 4],
    pub position: [f32; 3],
    pub physics_disabled: u8,
    pub interpolation: [u8; 16],
}

#[derive(Clone, Debug)]
pub struct MorphClip {
    pub name: Vec<u8>,
    pub frame: u32,
    pub value: f32,
}

/// A display/IK/outside-parent key of the clipboard.
#[derive(Clone, Debug)]
pub struct DisplayClip {
    pub frame: i32,
    pub visible: u8,
    /// `(bone name, flag)`: sets the IK chain whose bone has that name.
    pub ik: Vec<(Vec<u8>, u8)>,
    /// `(bone name, model, bone)`: sets the selector whose bone has that name.
    pub selectors: Vec<(Vec<u8>, i32, i32)>,
}

fn cstr(s: &[u8]) -> &[u8] {
    &s[..s.iter().position(|&b| b == 0).unwrap_or(s.len())]
}

/// How a registrar filled the record it was given.
enum Put {
    Exact(u32),
    /// A free record linked in after the last key.
    Append(u32),
    /// A free record linked in before a later key.
    Insert(u32),
}

/// Finds or makes the record for `frame` on the track of `head`. `alloc`
/// finds the free record; the pool is unchanged when it finds none.
fn put<K: Link>(
    pool: &mut KeyPool<K>,
    rig: &Rig,
    name: &'static str,
    head: u32,
    frame: u32,
    alloc: impl FnOnce(&KeyPool<K>) -> Option<u32>,
) -> Result<Put> {
    let spot = locate(pool, head, frame)?;
    if let Spot::Exact(i) = spot {
        return Ok(Put::Exact(i));
    }
    let fresh = alloc(pool).ok_or_else(|| full(pool, name))?;
    attach(pool, rig, spot, fresh, frame)?;
    Ok(match spot {
        Spot::After(_) => Put::Append(fresh),
        _ => Put::Insert(fresh),
    })
}

impl Tracks {
    fn bump(&mut self, frame: u32) {
        self.max_frame = self.max_frame.max(frame);
    }

    /// `RegisterBoneKey` (VA 0x49D880) without `useSelected`: the key of
    /// `clip` at `frame_offset + clip.frame` on the bone named `clip.name`.
    /// An unknown name registers nothing.
    pub fn register_bone_key(
        &mut self,
        rig: &Rig,
        clip: &BoneClip,
        frame_offset: i32,
    ) -> Result<()> {
        let frame = (frame_offset as u32).wrapping_add(clip.frame);
        let want = cstr(&clip.name);
        let Some(bone) = rig.bones.iter().position(|b| cstr(&b.name) == want) else {
            return Ok(());
        };
        if rig.bones[bone].twist {
            return Err(Error::Unsupported("fixed-axis twist correction"));
        }
        let write_position = rig.bones[bone].writes_position;
        let cursor = &mut self.search_cursor;
        let placed = put(&mut self.bone, rig, "bone", bone as u32, frame, |p| {
            p.allocate_from_cursor(cursor)
        })?;
        let (Put::Exact(at) | Put::Append(at) | Put::Insert(at)) = placed;
        let k = slot(&mut self.bone, rig, at)?;
        k.rotation = clip.rotation;
        if write_position {
            k.position = clip.position;
        }
        k.physics_disabled = clip.physics_disabled;
        k.interpolation = clip.interpolation;
        k.allocated = 1;
        match placed {
            Put::Append(_) => self.bump(frame),
            // The original bumps with the raw offset here.
            _ => self.bump(frame_offset as u32),
        }
        Ok(())
    }

    /// `RegisterMorphKeyFromRecord` (VA 0x49F190).
    pub fn register_morph_key(
        &mut self,
        rig: &Rig,
        clip: &MorphClip,
        frame_offset: i32,
    ) -> Result<()> {
        let frame = (frame_offset as u32).wrapping_add(clip.frame);
        let want = cstr(&clip.name);
        let Some(morph) = rig.morphs.iter().position(|m| cstr(&m.name) == want) else {
            return Ok(());
        };
        let cursor = &mut self.search_cursor;
        let placed = put(&mut self.morph, rig, "morph", morph as u32, frame, |p| {
            p.allocate_from_cursor(cursor)
        })?;
        let (Put::Exact(at) | Put::Append(at) | Put::Insert(at)) = placed;
        let k = slot(&mut self.morph, rig, at)?;
        k.value = clip.value;
        k.allocated = 1;
        if !matches!(placed, Put::Exact(_)) {
            self.bump(frame);
        }
        Ok(())
    }

    /// `RegisterDisplayKeyFromRecord` (VA 0x49F8C0).
    pub fn register_display_key(
        &mut self,
        rig: &Rig,
        clip: &DisplayClip,
        frame_offset: i32,
    ) -> Result<()> {
        let frame = (frame_offset.wrapping_add(clip.frame)) as u32;
        let cursor = &mut self.search_cursor;
        let placed = put(&mut self.display, rig, "display", 0, frame, |p| {
            p.allocate_from_cursor(cursor)
        })?;
        let (Put::Exact(at) | Put::Append(at) | Put::Insert(at)) = placed;
        let k = slot(&mut self.display, rig, at)?;
        k.visible = clip.visible;
        // The first entry with the bone's name wins, as the strcmp scan does.
        for (i, chain) in rig.ik_chains.iter().enumerate() {
            let bone = cstr(
                &rig.bones
                    .get(chain.bone as usize)
                    .ok_or(Error::Corrupt)?
                    .name,
            );
            if let Some((_, flag)) = clip.ik.iter().find(|(n, _)| cstr(n) == bone) {
                *ik_entry(&mut k.ik_enabled, i) = *flag;
            }
        }
        for (i, sel) in rig.selectors.iter().enumerate() {
            let bone = cstr(&rig.bones.get(sel.bone as usize).ok_or(Error::Corrupt)?.name);
            if let Some((_, model, bone)) = clip.selectors.iter().find(|(n, ..)| cstr(n) == bone) {
                if k.selectors.len() <= i {
                    k.selectors.resize(i + 1, [-1, 0]);
                }
                k.selectors[i] = [*model, *bone];
            }
        }
        k.allocated = 1;
        if !matches!(placed, Put::Exact(_)) {
            self.bump(frame);
        }
        Ok(())
    }

    /// `RegisterMorphKeyCurrent` (VA 0x49EEE0): the live weight of `morph` at
    /// `frame`, with its own free-record scan.
    pub fn register_morph_current(&mut self, rig: &Rig, morph: i32, frame: u32) -> Result<()> {
        if morph < 0 || (!rig.pmx && morph == 0) || rig.morphs.is_empty() {
            return Ok(());
        }
        let value = rig.morphs.get(morph as usize).ok_or(Error::Corrupt)?.value;
        let placed = put(
            &mut self.morph,
            rig,
            "morph",
            morph as u32,
            frame,
            scan_free,
        )?;
        let (Put::Exact(at) | Put::Append(at) | Put::Insert(at)) = placed;
        let k = slot(&mut self.morph, rig, at)?;
        k.value = value;
        k.allocated = 1;
        if !matches!(placed, Put::Exact(_)) {
            self.bump(frame);
        }
        Ok(())
    }

    /// `RegisterDisplayKeyCurrent` (VA 0x49F480): the model's display, IK
    /// and selector state at `frame`.
    pub fn register_display_current(&mut self, rig: &Rig, frame: u32) -> Result<()> {
        let placed = put(&mut self.display, rig, "display", 0, frame, scan_free)?;
        let (Put::Exact(at) | Put::Append(at) | Put::Insert(at)) = placed;
        let k = slot(&mut self.display, rig, at)?;
        k.visible = rig.load_complete;
        for (i, chain) in rig.ik_chains.iter().enumerate() {
            *ik_entry(&mut k.ik_enabled, i) = chain.enabled;
        }
        if k.selectors.len() < rig.selectors.len() {
            k.selectors.resize(rig.selectors.len(), [-1, 0]);
        }
        for (i, sel) in rig.selectors.iter().enumerate() {
            k.selectors[i] = [sel.linked_model, sel.linked_bone];
        }
        k.allocated = 1;
        if !matches!(placed, Put::Exact(_)) {
            self.bump(frame);
        }
        Ok(())
    }

    /// `RegisterBonePoseAtFrame` (VA 0x4B38A0): the current pose of bone
    /// `bone` at `frame`.
    pub fn register_bone_pose(&mut self, rig: &Rig, bone: usize, frame: u32) -> Result<()> {
        let info = rig.bones.get(bone).ok_or(Error::Corrupt)?;
        if info.rigid_body {
            return Err(Error::Unsupported("pose of a bone with a rigid body"));
        }
        if rig.auto_interpolation {
            return Err(Error::Unsupported("automatic interpolation"));
        }
        let cursor = &mut self.search_cursor;
        let placed = put(&mut self.bone, rig, "bone", bone as u32, frame, |p| {
            p.allocate_from_cursor(cursor)
        })?;
        let (Put::Exact(at) | Put::Append(at) | Put::Insert(at)) = placed;
        let k = slot(&mut self.bone, rig, at)?;
        k.rotation = info.rotation;
        k.position = info.translation;
        reset_interpolation(k);
        k.allocated = 1;
        self.bump(frame);
        Ok(())
    }

    /// `RegisterSelectedBoneKeys` (VA 0x4C2080), the register button: clears
    /// every mark, then registers the pose of each selected bone.
    pub fn register_selected_bone_keys(
        &mut self,
        rig: &Rig,
        selected: &[bool],
        frame: u32,
    ) -> Result<()> {
        self.clear_marks();
        for (bone, _) in selected.iter().enumerate().filter(|(_, s)| **s) {
            self.register_bone_pose(rig, bone, frame)?;
        }
        Ok(())
    }

    /// `PasteSelectedKeyframes` (`frame_clipboard.cpp`, model mode): clears
    /// the marks, then resets the cursor and registers the bone, morph and
    /// display keys in turn, at `frame_offset`. A full pool stops its own
    /// loop only, as in the original; the first error is returned at the end.
    pub fn paste(
        &mut self,
        rig: &Rig,
        bones: &[BoneClip],
        morphs: &[MorphClip],
        displays: &[DisplayClip],
        frame_offset: i32,
    ) -> Result<()> {
        if bones.is_empty() && morphs.is_empty() && displays.is_empty() {
            return Ok(());
        }
        let mut first = Ok(());
        self.clear_marks();
        self.reset_bone_cursor(rig);
        for clip in bones {
            if let Err(e) = self.register_bone_key(rig, clip, frame_offset) {
                first = first.and(Err(e));
                break;
            }
        }
        self.reset_morph_cursor(rig);
        for clip in morphs {
            if let Err(e) = self.register_morph_key(rig, clip, frame_offset) {
                first = first.and(Err(e));
                break;
            }
        }
        self.reset_display_cursor();
        for clip in displays {
            if let Err(e) = self.register_display_key(rig, clip, frame_offset) {
                first = first.and(Err(e));
                break;
            }
        }
        first
    }
}

fn ik_entry(v: &mut Vec<u8>, i: usize) -> &mut u8 {
    if v.len() <= i {
        v.resize(i + 1, 1);
    }
    &mut v[i]
}
