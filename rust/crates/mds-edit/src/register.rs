//! The registrars: `key_registrars.cpp` (VMD load and paste), the register
//! buttons (`command_frame_register.cpp`, `command_frame_edit.cpp`), and the
//! paste handler (`frame_clipboard.cpp`).

use crate::link::{
    attach, full, locate, rebuild_interpolation, reset_interpolation, scan_free, slot, Link, Spot,
};
use crate::{BoneExtra, Error, Extra, Result, Rig, Tracks};
use mds_formats::key_pool::KeyPool;
use mds_math::{Quat, Vec3};

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

/// Which bone a bone registrar writes the clip to.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BoneTarget {
    /// The bone named `clip.name` (`RegisterBoneKey`, `useSelected = 0`).
    Named,
    /// The selected bone, whatever the clip's name (`useSelected = 1`).
    /// `-1` (no selection) registers nothing.
    Selected(i32),
    /// The left/right counterpart of `clip.name`, with the pose reflected
    /// across the model's YZ plane (`RegisterMirroredBoneKey`, VA 0x49E310).
    Mirrored,
}

fn cstr(s: &[u8]) -> &[u8] {
    &s[..s.iter().position(|&b| b == 0).unwrap_or(s.len())]
}

/// `strstr` on C strings: the offset of the first `needle` in `hay`.
fn find(hay: &[u8], needle: &[u8]) -> Option<usize> {
    hay.windows(needle.len()).position(|w| w == needle)
}

/// `FindMirroredBone` (`key_registrars.cpp`): a name with 左 (Shift-JIS
/// 0x8D 0xB6) maps to the first bone with 右 (0x89 0x45) and the same text
/// after it; only a name without 左 tries 右 to 左. Otherwise the bone of the
/// same name.
fn mirrored_bone(rig: &Rig, name: &[u8]) -> Option<usize> {
    const RIGHT: &[u8] = b"\x89\x45";
    const LEFT: &[u8] = b"\x8D\xB6";
    let name = cstr(name);
    let opposite = |marker: &[u8], other: &[u8]| -> Option<usize> {
        let suffix = &name[find(name, marker)? + 2..];
        rig.bones.iter().position(|b| {
            let b = cstr(&b.name);
            find(b, other).is_some_and(|at| &b[at + 2..] == suffix)
        })
    };
    opposite(LEFT, RIGHT)
        .or_else(|| opposite(RIGHT, LEFT))
        .or_else(|| rig.bones.iter().position(|b| cstr(&b.name) == name))
}

/// The twist axis of `bone` as the registrars use it.
fn twist_axis(rig: &Rig, extra: &Extra, bone: usize) -> Result<[f32; 3]> {
    let e = extra.bones.get(bone).ok_or(Error::Unsupported(
        "fixed-axis twist correction without the bone axis",
    ))?;
    Ok(if rig.pmx {
        e.axis
    } else {
        Vec3(e.axis).normalize().0
    })
}

fn dot(a: [f32; 3], b: [f32; 3]) -> f32 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

fn norm(a: [f32; 3]) -> f32 {
    dot(a, a).sqrt()
}

/// The start of both twist corrections: the quaternion's axis, and
/// `sin(angle / 2)` from `w` (a non-finite `w` reads as 1, `|w| > 1` as 1
/// with a zero sine).
fn twist_parts(q: &mut [f32; 4]) -> ([f32; 3], f32) {
    let (axis, _) = Quat(*q).to_axis_angle();
    if !q[3].is_finite() {
        q[3] = 1.0;
    }
    let ww = q[3] * q[3];
    let sin_half = if ww <= 1.0 {
        (1.0 - ww).sqrt()
    } else {
        q[3] = 1.0;
        0.0
    };
    (axis.0, sin_half)
}

/// The twist correction of `RegisterBoneKey`: the sine takes the sign of the
/// angle between the bone axis and the quaternion's axis, which it scales.
fn twist(bone_axis: [f32; 3], mut q: [f32; 4]) -> [f32; 4] {
    let (axis, mut sin_half) = twist_parts(&mut q);
    if dot(bone_axis, axis) / (norm(axis) * norm(bone_axis)) < 0.0 {
        sin_half = -sin_half;
    }
    for i in 0..3 {
        q[i] = sin_half * axis[i];
    }
    Quat(q).normalize().0
}

/// The twist correction of `RegisterMirroredBoneKey`: the source axis
/// mirrored in x and the sine negated before the sign test; the result
/// lies on the bone axis with y and z negated.
fn mirrored_twist(bone_axis: [f32; 3], mut q: [f32; 4]) -> [f32; 4] {
    let (mut axis, sin_half) = twist_parts(&mut q);
    axis[0] = -axis[0];
    let mut sin_half = -sin_half;
    if dot(bone_axis, axis) / (norm(bone_axis) * norm(axis)) < 0.0 {
        sin_half = -sin_half;
    }
    q[0] = sin_half * bone_axis[0];
    q[1] = -sin_half * bone_axis[1];
    q[2] = -sin_half * bone_axis[2];
    Quat(q).normalize().0
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
    /// An unknown name registers nothing. A fixed-axis bone needs
    /// [`Tracks::register_bone_key_with`].
    pub fn register_bone_key(
        &mut self,
        rig: &Rig,
        clip: &BoneClip,
        frame_offset: i32,
    ) -> Result<()> {
        self.register_bone_key_with(
            rig,
            &Extra::default(),
            clip,
            frame_offset,
            BoneTarget::Named,
        )
    }

    /// `RegisterBoneKey` (VA 0x49D880) and `RegisterMirroredBoneKey` (VA
    /// 0x49E310): the key of `clip` at `frame_offset + clip.frame` on the
    /// bone `target` picks, with the twist correction for a fixed-axis bone.
    pub fn register_bone_key_with(
        &mut self,
        rig: &Rig,
        extra: &Extra,
        clip: &BoneClip,
        frame_offset: i32,
        target: BoneTarget,
    ) -> Result<()> {
        let frame = (frame_offset as u32).wrapping_add(clip.frame);
        let bone = match target {
            BoneTarget::Named => {
                let want = cstr(&clip.name);
                rig.bones.iter().position(|b| cstr(&b.name) == want)
            }
            BoneTarget::Selected(-1) => None,
            BoneTarget::Selected(i) => Some(
                usize::try_from(i)
                    .ok()
                    .filter(|&i| i < rig.bones.len())
                    .ok_or(Error::Corrupt)?,
            ),
            BoneTarget::Mirrored => mirrored_bone(rig, &clip.name),
        };
        let Some(bone) = bone else {
            return Ok(());
        };
        let mirrored = target == BoneTarget::Mirrored;
        let mut rotation = clip.rotation;
        if rig.bones[bone].twist {
            let axis = twist_axis(rig, extra, bone)?;
            rotation = if mirrored {
                mirrored_twist(axis, rotation)
            } else {
                twist(axis, rotation)
            };
        }
        let write_position = rig.bones[bone].writes_position;
        let cursor = &mut self.search_cursor;
        let placed = put(&mut self.bone, rig, "bone", bone as u32, frame, |p| {
            p.allocate_from_cursor(cursor)
        })?;
        let (Put::Exact(at) | Put::Append(at) | Put::Insert(at)) = placed;
        let k = slot(&mut self.bone, rig, at)?;
        k.rotation = rotation;
        if mirrored {
            // FillMirroredBoneRecord: the reflection, and always the position.
            k.rotation[1] = -k.rotation[1];
            k.rotation[2] = -k.rotation[2];
            k.position = clip.position;
            k.position[0] = -k.position[0];
        } else if write_position {
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
            // The root selector (bone -1) has no bone. The C++ compares the
            // names with the bytes before the bone table, which match none
            // (tools/keypool_check, FindingRun).
            let Some(bone) = rig.bones.get(sel.bone as usize) else {
                continue;
            };
            let bone = cstr(&bone.name);
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
    /// `bone` at `frame`. A bone with a rigid body needs
    /// [`Tracks::register_bone_pose_with`].
    pub fn register_bone_pose(&mut self, rig: &Rig, bone: usize, frame: u32) -> Result<()> {
        self.bone_pose(rig, None, bone, frame).map(|_| ())
    }

    /// `RegisterBonePoseAtFrame` (VA 0x4B38A0) with the physics state. For a
    /// bone with a rigid body that physics drives (mode 1, or mode 2 and up
    /// with physics on for the bone), the key and the bone's pose in `rig`
    /// take the physics pose. Then the bone's `physics_disabled` and the
    /// key's take the negation of the physics checkbox.
    pub fn register_bone_pose_with(
        &mut self,
        rig: &mut Rig,
        extra: &mut Extra,
        bone: usize,
        frame: u32,
    ) -> Result<()> {
        let (checkbox, mode) = (extra.physics_checkbox, extra.physics_mode);
        let physics = extra.bones.get_mut(bone).map(|e| (e, checkbox, mode));
        if let Some((rotation, translation)) = self.bone_pose(rig, physics, bone, frame)? {
            rig.bones[bone].rotation = rotation;
            rig.bones[bone].translation = translation;
        }
        Ok(())
    }

    /// The body of `RegisterBonePoseAtFrame`. Returns the physics pose when
    /// the bone takes it.
    #[allow(clippy::type_complexity)]
    fn bone_pose(
        &mut self,
        rig: &Rig,
        physics: Option<(&mut BoneExtra, bool, i32)>,
        bone: usize,
        frame: u32,
    ) -> Result<Option<([f32; 4], [f32; 3])>> {
        let info = rig.bones.get(bone).ok_or(Error::Corrupt)?;
        let physics = match (info.rigid_body, physics) {
            (false, _) => None,
            (true, None) => return Err(Error::Unsupported("pose of a bone with a rigid body")),
            (true, Some(p)) => Some(p),
        };
        let cursor = &mut self.search_cursor;
        let placed = put(&mut self.bone, rig, "bone", bone as u32, frame, |p| {
            p.allocate_from_cursor(cursor)
        })?;
        let (Put::Exact(at) | Put::Append(at) | Put::Insert(at)) = placed;
        let k = slot(&mut self.bone, rig, at)?;
        let mut posed = None;
        k.rotation = info.rotation;
        k.position = info.translation;
        if let Some((e, checkbox, mode)) = physics {
            if mode == 1 || (mode >= 2 && e.physics_disabled == 0) {
                k.rotation = e.physics_rotation;
                k.position = e.physics_translation;
                posed = Some((e.physics_rotation, e.physics_translation));
            }
            e.physics_disabled = u8::from(!checkbox);
            k.physics_disabled = e.physics_disabled;
        }
        if rig.auto_interpolation {
            for lane in 0..4 {
                rebuild_interpolation(&mut self.bone, rig, at, lane)?;
            }
        } else {
            reset_interpolation(k);
        }
        slot(&mut self.bone, rig, at)?.allocated = 1;
        self.bump(frame);
        Ok(posed)
    }

    /// `RegisterSelectedBoneKeys` (VA 0x4C2080), the register button: clears
    /// every mark, then registers the pose of each selected bone. A bone
    /// with a rigid body needs [`Tracks::register_selected_bone_keys_with`].
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

    /// [`Tracks::register_selected_bone_keys`] with the physics state, as
    /// [`Tracks::register_bone_pose_with`] registers each bone.
    pub fn register_selected_bone_keys_with(
        &mut self,
        rig: &mut Rig,
        extra: &mut Extra,
        selected: &[bool],
        frame: u32,
    ) -> Result<()> {
        self.clear_marks();
        for (bone, _) in selected.iter().enumerate().filter(|(_, s)| **s) {
            self.register_bone_pose_with(rig, extra, bone, frame)?;
        }
        Ok(())
    }

    /// `PasteSelectedKeyframes` (`frame_clipboard.cpp`, model mode): clears
    /// the marks, then resets the cursor and registers the bone, morph and
    /// display keys in turn, at `frame_offset`. A full pool stops its own
    /// loop only, as in the original; the first error is returned at the end.
    /// Fixed-axis bones need [`Tracks::paste_with`].
    pub fn paste(
        &mut self,
        rig: &Rig,
        bones: &[BoneClip],
        morphs: &[MorphClip],
        displays: &[DisplayClip],
        frame_offset: i32,
    ) -> Result<()> {
        let extra = &Extra::default();
        self.paste_with(rig, extra, bones, morphs, displays, frame_offset)
    }

    /// [`Tracks::paste`] with the twist axes of `extra`.
    pub fn paste_with(
        &mut self,
        rig: &Rig,
        extra: &Extra,
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
            let r = self.register_bone_key_with(rig, extra, clip, frame_offset, BoneTarget::Named);
            if let Err(e) = r {
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

    /// The bone loop of reverse paste (command 422,
    /// `PasteMirroredBoneKeyframes`) and of "paste to the selected bone"
    /// (`MDS_CMD_PASTE_AT_DIFFERENT_FRAME`, `command_file_menu.cpp`), at
    /// `frame_offset`: clears the marks and resets the cursor, then registers
    /// the bone keys on `target` until one fails. A `BoneTarget::Selected(-1)`
    /// (no bone selected) changes nothing; morph and display keys are not
    /// pasted.
    pub fn paste_bones(
        &mut self,
        rig: &Rig,
        extra: &Extra,
        bones: &[BoneClip],
        frame_offset: i32,
        target: BoneTarget,
    ) -> Result<()> {
        if bones.is_empty() || target == BoneTarget::Selected(-1) {
            return Ok(());
        }
        self.clear_marks();
        self.reset_bone_cursor(rig);
        for clip in bones {
            self.register_bone_key_with(rig, extra, clip, frame_offset, target)?;
        }
        Ok(())
    }
}

fn ik_entry(v: &mut Vec<u8>, i: usize) -> &mut u8 {
    if v.len() <= i {
        v.resize(i + 1, 1);
    }
    &mut v[i]
}
