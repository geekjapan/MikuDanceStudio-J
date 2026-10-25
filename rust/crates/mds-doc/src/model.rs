//! Model-mode key commands: `mds-edit` does the pool work, this module adds
//! the C++ around it (`src/model/model_keyframe_edit.cpp`,
//! `src/window/command_frame_register.cpp`, `command_frame_edit.cpp`,
//! `frame_clipboard.cpp`): mark clearing, undo entries with the records each
//! step touches (`AppendBoneKeyToUndo`), and the frame bookkeeping.

use crate::global::walk;
use crate::history::{snapshot, Entry, History, PoseSnapshot};
use crate::{Error, ModelFile};
use mds_edit::{
    BoneClip, BoneExtra, BoneInfo, BoneTarget, DisplayClip, Extra, IkChain, MorphClip, MorphInfo,
    Rig, Selector, Tracks,
};
use mds_formats::key_pool::{Key, KeyPool};
use mds_formats::pmm::{self, BoneKey};
use mds_pose::model::{flag, kind, Model as PoseModel};
use std::collections::BTreeMap;

/// What the editor needs of the model file, per bone.
#[derive(Clone, Debug)]
pub struct Skeleton {
    pub pmx: bool,
    /// `(writes_position, twist, rigid_body)` per bone.
    pub bones: Vec<(bool, bool, bool)>,
    /// The twist axis the registrars read per bone: `BoneRecord::axis` for
    /// PMX, the tail bone's rest position minus the bone's for PMD.
    pub axes: Vec<[f32; 3]>,
}

impl Skeleton {
    /// The bone types and rigid-body links the loaders leave
    /// (`mds_pose::model`). `None` for a missing file or one whose bone count
    /// differs from the PMM's (the C++ remaps by name; this port does not).
    pub fn new(file: &ModelFile, pmm_model: &pmm::Model) -> Option<Skeleton> {
        let m: PoseModel = match file {
            ModelFile::Pmx(p) => PoseModel::from_pmx(pmm_model.slot, p).ok()?,
            ModelFile::Pmd(p) => PoseModel::from_pmd(pmm_model.slot, p).ok()?,
            ModelFile::Missing => return None,
        };
        let axis = |b: &mds_pose::model::Bone| {
            if m.pmx {
                return b.axis;
            }
            let tail = usize::try_from(b.tail_bone).ok().and_then(|t| m.bones.get(t));
            tail.map_or([0.0; 3], |t| std::array::from_fn(|c| t.position[c] - b.position[c]))
        };
        (m.bones.len() == pmm_model.bone_names.len()).then(|| Skeleton {
            pmx: m.pmx,
            axes: m.bones.iter().map(axis).collect(),
            bones: m
                .bones
                .iter()
                .map(|b| {
                    (
                        b.kind <= kind::IK,
                        b.kind == kind::FIXED_AXIS
                            || (b.kind == kind::UNDER_IK && b.flags & flag::FIXED_AXIS != 0),
                        b.has_rigid_body != 0,
                    )
                })
                .collect(),
        })
    }
}

/// The display group count the loaders give a model (`groupCount`): the
/// PMX display frames (`src/model/pmx_load.cpp`), or the PMD bone groups
/// plus the root and "Disp/IK/OP" groups (`pmd_load.cpp`), plus the facial
/// group when any morph is displayed. Counts are bytes, as in the C++.
pub fn group_count(file: &ModelFile) -> Option<u8> {
    match file {
        ModelFile::Pmx(p) => {
            let morphs = p
                .frames
                .iter()
                .flat_map(|f| &f.entries)
                .filter(|e| e.0 != 0)
                .count() as u8;
            Some((p.frames.len() as u8).wrapping_add(u8::from(morphs != 0)))
        }
        ModelFile::Pmd(p) => Some(
            (p.bone_groups.len() as u8)
                .wrapping_add(2)
                .wrapping_add(u8::from(p.morph_display.len() as u8 != 0)),
        ),
        ModelFile::Missing => None,
    }
}

/// The editor's view of a model: names and the saved pose from the PMM,
/// bone flags from the file.
pub fn rig(m: &pmm::Model, s: &Skeleton, auto_interpolation: bool) -> Rig {
    Rig {
        bones: m
            .bone_names
            .iter()
            .zip(&m.bone_pose)
            .zip(&s.bones)
            .map(|((n, p), &(writes_position, twist, rigid_body))| BoneInfo {
                name: n.raw.clone(),
                writes_position,
                twist,
                rigid_body,
                rotation: p.rotation,
                translation: p.translation,
            })
            .collect(),
        morphs: m
            .morph_names
            .iter()
            .zip(&m.morph_pose)
            .map(|(n, &value)| MorphInfo {
                name: n.raw.clone(),
                value,
            })
            .collect(),
        ik_chains: m
            .ik_bones
            .iter()
            .zip(&m.ik_pose)
            .map(|(&b, &enabled)| IkChain {
                bone: b as u32,
                enabled,
            })
            .collect(),
        selectors: m
            .selector_bones
            .iter()
            .zip(&m.selector_pose)
            .map(|(&b, p)| Selector {
                bone: b as u32,
                linked_model: p[2],
                linked_bone: p[3],
            })
            .collect(),
        pmx: s.pmx,
        load_complete: m.selection.load_complete,
        auto_interpolation,
    }
}

fn empty<K: Key>() -> KeyPool<K> {
    KeyPool::new(0, Vec::new()).expect("empty pool")
}

/// Runs `f` on the model's pools as `mds_edit::Tracks`.
pub fn with_tracks<R>(m: &mut pmm::Model, cursor: &mut u32, f: impl FnOnce(&mut Tracks) -> R) -> R {
    let mut t = Tracks {
        bone: std::mem::replace(&mut m.bone_keys, empty()),
        morph: std::mem::replace(&mut m.morph_keys, empty()),
        display: std::mem::replace(&mut m.display_keys, empty()),
        search_cursor: *cursor,
        max_frame: m.selection.max_frame,
    };
    let r = f(&mut t);
    m.bone_keys = t.bone;
    m.morph_keys = t.morph;
    m.display_keys = t.display;
    m.selection.max_frame = t.max_frame;
    *cursor = t.search_cursor;
    r
}

/// The bone records `AppendBoneKeyToUndo` captures, first touch wins.
#[derive(Default)]
struct Touched(BTreeMap<u32, Option<BoneKey>>);

impl Touched {
    fn add(&mut self, pool: &KeyPool<BoneKey>, i: u32) {
        self.0.entry(i).or_insert_with(|| pool.get(i).cloned());
    }
    /// The records a register of `frame` on the track of `head` touches:
    /// `{cur}` on an exact hit, `{cur, fresh}` on append, `{prev, cur,
    /// fresh}` on insert. Nothing when no record is free.
    fn register(&mut self, t: &Tracks, head: u32, frame: u32) -> Result<(), Error> {
        let pool = &t.bone;
        let cur = walk(pool, head, frame)?;
        let k = pool.get(cur).ok_or(Error::Edit(mds_edit::Error::Corrupt))?;
        if k.frame == frame {
            self.add(pool, cur);
            return Ok(());
        }
        let Some(fresh) = pool.allocate_from_cursor(&mut t.search_cursor.clone()) else {
            return Ok(());
        };
        if k.frame >= frame {
            self.add(pool, k.previous);
        }
        self.add(pool, cur);
        self.add(pool, fresh);
        Ok(())
    }
    fn into_keys(self) -> Vec<(u32, Option<BoneKey>)> {
        self.0.into_iter().collect()
    }
}

/// The C++ undo slot is filled as the step runs; this one is pushed empty
/// and filled at the end of the command.
fn fill_keys(h: &mut History, keys: Touched) {
    if let Entry::BoneKeys { keys: k, .. } = &mut h.undo[h.cursor] {
        *k = keys.into_keys();
    }
}

fn first_err(first: &mut Result<(), Error>, r: Result<(), mds_edit::Error>) -> bool {
    match r {
        Ok(()) => false,
        Err(e) => {
            if first.is_ok() {
                *first = Err(e.into());
            }
            true
        }
    }
}

/// The edit state of one model.
#[derive(Clone, Debug, Default)]
pub struct ModelEdit {
    pub search_cursor: u32,
    pub history: History,
    /// `BoneRecord::ikBackup` per bone, `(rotation, translation)`: the pose
    /// the last physics step left, which the frame loop (not the document)
    /// computes. `None` until a frame loop reports one; a register that
    /// needs it is refused then.
    pub physics_pose: Option<Vec<([f32; 4], [f32; 3])>>,
}

/// The physics controls the bone registrars read.
#[derive(Clone, Copy, Debug)]
pub struct Physics {
    /// The physics checkbox (499), checked at start-up (`ui_init.cpp`).
    pub checkbox: bool,
    /// `PlaybackPhysicsMode` (`pmm.physics.playback_mode`).
    pub mode: u8,
}

/// The [`Extra`] of a model: twist axes from the file, `physicsDisabled`
/// from the saved pose flag 0, the physics pose of `e`.
pub fn extra(m: &pmm::Model, s: &Skeleton, e: &ModelEdit, physics: Physics) -> Extra {
    let pose = |i: usize| {
        e.physics_pose
            .as_ref()
            .and_then(|v| v.get(i).copied())
            .unwrap_or(([0.0, 0.0, 0.0, 1.0], [0.0; 3]))
    };
    Extra {
        bones: m
            .bone_pose
            .iter()
            .zip(&s.axes)
            .enumerate()
            .map(|(i, (p, &axis))| BoneExtra {
                axis,
                physics_rotation: pose(i).0,
                physics_translation: pose(i).1,
                physics_disabled: p.flags[0],
            })
            .collect(),
        physics_checkbox: physics.checkbox,
        physics_mode: i32::from(physics.mode),
    }
}

/// Whether `RegisterBonePoseAtFrame` stores the physics pose of `bone`.
fn takes_physics_pose(m: &pmm::Model, s: &Skeleton, physics: Physics, bone: usize) -> bool {
    s.bones[bone].2 && (physics.mode == 1 || (physics.mode >= 2 && m.bone_pose[bone].flags[0] == 0))
}

/// `RegisterSelectedBoneKeys` (VA 0x004C2080), the register button (500):
/// an undo entry for every bone's pose, every mark cleared, then the pose
/// of each selected bone at `frame` (`RegisterBonePoseAtFrame` VA
/// 0x004B38A0), clearing its edited mark. A full pool skips that bone, as
/// the C++ loop ignores the result. A selected bone that takes the physics
/// pose without a [`ModelEdit::physics_pose`] refuses the command first.
pub fn register_bones(
    m: &mut pmm::Model,
    s: &Skeleton,
    e: &mut ModelEdit,
    auto_interpolation: bool,
    physics: Physics,
    frame: u32,
) -> Result<(), Error> {
    let mut rig = rig(m, s, auto_interpolation);
    let selected: Vec<usize> = (0..rig.bones.len())
        .filter(|&i| m.bone_pose[i].flags[2] != 0)
        .collect();
    if e.physics_pose.is_none() && selected.iter().any(|&b| takes_physics_pose(m, s, physics, b)) {
        return Err(mds_edit::Error::Unsupported("pose of a bone with a rigid body").into());
    }
    let mut extra = extra(m, s, e, physics);
    e.history.push(Entry::BoneKeys {
        frame,
        pose: snapshot(m, 0..rig.bones.len()),
        keys: Vec::new(),
    });
    let mut touched = Touched::default();
    let mut first = Ok(());
    with_tracks(m, &mut e.search_cursor, |t| {
        t.clear_marks();
        for &b in &selected {
            touched.register(t, b as u32, frame)?;
            first_err(
                &mut first,
                t.register_bone_pose_with(&mut rig, &mut extra, b, frame),
            );
        }
        Ok::<_, Error>(())
    })?;
    for ((p, b), x) in m.bone_pose.iter_mut().zip(&rig.bones).zip(&extra.bones) {
        p.rotation = b.rotation;
        p.translation = b.translation;
        p.flags[0] = x.physics_disabled;
    }
    for &b in &selected {
        m.bone_pose[b].flags[1] = 0;
    }
    fill_keys(&mut e.history, touched);
    first
}

/// The morph register button (`command_frame_register.cpp`): every mark
/// cleared, then `RegisterMorphKeyCurrent` (VA 0x0049EEE0).
pub fn register_morph(
    m: &mut pmm::Model,
    s: &Skeleton,
    e: &mut ModelEdit,
    morph: i32,
    frame: u32,
) -> Result<(), Error> {
    let rig = rig(m, s, false);
    with_tracks(m, &mut e.search_cursor, |t| {
        t.clear_marks();
        t.register_morph_current(&rig, morph, frame)
    })?;
    Ok(())
}

/// Button 438 (`command_frame_edit.cpp`): every mark cleared, then
/// `RegisterDisplayKeyCurrent` (VA 0x0049F480).
pub fn register_display(
    m: &mut pmm::Model,
    s: &Skeleton,
    e: &mut ModelEdit,
    frame: u32,
) -> Result<(), Error> {
    let rig = rig(m, s, false);
    with_tracks(m, &mut e.search_cursor, |t| {
        t.clear_marks();
        t.register_display_current(&rig, frame)
    })?;
    Ok(())
}

/// The model-mode clipboard (`CopySelectedKeyframes`, model branch).
#[derive(Clone, Debug, Default)]
pub struct ModelClipboard {
    pub bones: Vec<BoneClip>,
    pub morphs: Vec<MorphClip>,
    pub displays: Vec<DisplayClip>,
}

/// `kLightNameRoot`: the name the copy gives selector 0 instead of its bone's.
const ROOT: &[u8] = b"\x83\x8B\x81\x5B\x83\x67";

fn marked<K: mds_edit::Link>(pool: &KeyPool<K>) -> Vec<(u32, &K)> {
    let heads = pool.heads().iter().enumerate().map(|(i, k)| (i as u32, k));
    heads
        .chain(pool.records().iter().map(|(i, k)| (*i, k)))
        .filter(|(_, k)| k.allocated() != 0)
        .collect()
}

/// The head a record belongs to: `previous` until below the head count.
fn head_of<K: Key>(pool: &KeyPool<K>, mut i: u32) -> Result<u32, Error> {
    let heads = pool.heads().len() as u32;
    for _ in 0..=pool.capacity() {
        if i < heads {
            return Ok(i);
        }
        i = pool.get(i).map_or(0, |k| k.previous());
    }
    Err(Error::Edit(mds_edit::Error::Corrupt))
}

/// `CopySelectedKeyframes`, model mode: every marked key, frames relative
/// to the earliest one over the three pools.
pub fn copy(m: &pmm::Model) -> Result<ModelClipboard, Error> {
    let (bones, morphs, displays) = (
        marked(&m.bone_keys),
        marked(&m.morph_keys),
        marked(&m.display_keys),
    );
    let min = bones
        .iter()
        .map(|k| k.1.frame)
        .chain(morphs.iter().map(|k| k.1.frame))
        .chain(displays.iter().map(|k| k.1.frame))
        .min()
        .unwrap_or(0);
    let name = |i: i32| -> Result<Vec<u8>, Error> {
        Ok(m.bone_names
            .get(i as usize)
            .ok_or(Error::Edit(mds_edit::Error::Corrupt))?
            .raw
            .clone())
    };
    let mut clip = ModelClipboard::default();
    for (i, k) in bones {
        clip.bones.push(BoneClip {
            name: name(head_of(&m.bone_keys, i)? as i32)?,
            frame: k.frame.wrapping_sub(min),
            rotation: k.rotation,
            position: k.position,
            physics_disabled: k.physics_disabled,
            interpolation: k.interpolation,
        });
    }
    if !m.morph_names.is_empty() {
        for (i, k) in morphs {
            clip.morphs.push(MorphClip {
                name: m.morph_names[head_of(&m.morph_keys, i)? as usize]
                    .raw
                    .clone(),
                frame: k.frame.wrapping_sub(min),
                value: k.value,
            });
        }
    }
    for (_, k) in displays {
        let mut selectors = Vec::new();
        for (j, (&b, s)) in m.selector_bones.iter().zip(&k.selectors).enumerate() {
            let n = if j == 0 { ROOT.to_vec() } else { name(b)? };
            selectors.push((n, s[0], s[1]));
        }
        clip.displays.push(DisplayClip {
            frame: k.frame.wrapping_sub(min) as i32,
            visible: k.visible,
            ik: m
                .ik_bones
                .iter()
                .zip(&k.ik_enabled)
                .map(|(&b, &f)| Ok((name(b)?, f)))
                .collect::<Result<_, Error>>()?,
            selectors,
        });
    }
    Ok(clip)
}

/// `PasteSelectedKeyframes`, model mode, at `frame`. `bone_counts` maps a
/// model slot to its bone count, for the selector fix-up that severs links
/// to models that are gone (and which the C++ writes back into the
/// clipboard).
pub fn paste(
    m: &mut pmm::Model,
    s: &Skeleton,
    e: &mut ModelEdit,
    clip: &mut ModelClipboard,
    frame: i32,
    bone_counts: impl Fn(i32) -> Option<i32>,
) -> Result<(), Error> {
    if clip.bones.is_empty() && clip.morphs.is_empty() && clip.displays.is_empty() {
        return Ok(());
    }
    let rig = rig(m, s, false);
    let extra = extra(m, s, e, Physics { checkbox: true, mode: 0 });
    let pose = snapshot(m, 0..rig.bones.len());
    let mut touched = Touched::default();
    let mut first = Ok(());
    with_tracks(m, &mut e.search_cursor, |t| {
        t.clear_marks();
        if !clip.bones.is_empty() {
            e.history.push(Entry::BoneKeys {
                frame: frame as u32,
                pose,
                keys: Vec::new(),
            });
        }
        t.reset_bone_cursor(&rig);
        for c in &clip.bones {
            let want = cstr(&c.name);
            if let Some(b) = rig.bones.iter().position(|b| cstr(&b.name) == want) {
                touched.register(t, b as u32, (frame as u32).wrapping_add(c.frame))?;
            }
            let r = t.register_bone_key_with(&rig, &extra, c, frame, BoneTarget::Named);
            if first_err(&mut first, r) {
                break;
            }
        }
        t.reset_morph_cursor(&rig);
        for c in &clip.morphs {
            if first_err(&mut first, t.register_morph_key(&rig, c, frame)) {
                break;
            }
        }
        t.reset_display_cursor();
        for c in &mut clip.displays {
            for (_, model, bone) in &mut c.selectors {
                if *model < 0 {
                    continue;
                }
                match bone_counts(*model) {
                    None => (*model, *bone) = (-1, 0),
                    Some(n) if n < *bone => *bone = 0,
                    _ => {}
                }
            }
            if first_err(&mut first, t.register_display_key(&rig, c, frame)) {
                break;
            }
        }
        Ok::<_, Error>(())
    })?;
    if !clip.bones.is_empty() {
        fill_keys(&mut e.history, touched);
    }
    first
}

/// `strstr` on C strings.
fn find(hay: &[u8], needle: &[u8]) -> Option<usize> {
    hay.windows(needle.len()).position(|w| w == needle)
}

/// `FindMirroredBone` (`key_registrars.cpp`), as `mds-edit` resolves it, for
/// the undo records: a name with 左 maps to the first bone with 右 and the
/// same text after it, else 右 to 左, else the bone of the same name.
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

/// The bone loops of reverse paste (button 422, `PasteMirroredBoneKeyframes`,
/// `frame_clipboard.cpp`) and of "paste to the selected bone"
/// (`MDS_CMD_PASTE_AT_DIFFERENT_FRAME`, `command_file_menu.cpp`) at `frame`:
/// with any copied bone key, every mark cleared, an undo entry of every
/// bone's pose and the records the registers touch, then the bone keys on
/// `target` until one fails. Morph and display keys are not pasted.
pub fn paste_bones(
    m: &mut pmm::Model,
    s: &Skeleton,
    e: &mut ModelEdit,
    clip: &ModelClipboard,
    frame: i32,
    target: BoneTarget,
) -> Result<(), Error> {
    if clip.bones.is_empty() {
        return Ok(());
    }
    let rig = rig(m, s, false);
    let extra = extra(m, s, e, Physics { checkbox: true, mode: 0 });
    e.history.push(Entry::BoneKeys {
        frame: frame as u32,
        pose: snapshot(m, 0..rig.bones.len()),
        keys: Vec::new(),
    });
    let mut touched = Touched::default();
    let r = with_tracks(m, &mut e.search_cursor, |t| {
        t.clear_marks();
        t.reset_bone_cursor(&rig);
        for c in &clip.bones {
            let bone = match target {
                BoneTarget::Named => {
                    let want = cstr(&c.name);
                    rig.bones.iter().position(|b| cstr(&b.name) == want)
                }
                BoneTarget::Selected(b) => usize::try_from(b).ok(),
                BoneTarget::Mirrored => mirrored_bone(&rig, &c.name),
            };
            if let Some(b) = bone {
                touched.register(t, b as u32, (frame as u32).wrapping_add(c.frame))?;
            }
            t.register_bone_key_with(&rig, &extra, c, frame, target)?;
        }
        Ok::<_, Error>(())
    });
    fill_keys(&mut e.history, touched);
    r
}

fn cstr(s: &[u8]) -> &[u8] {
    &s[..s.iter().position(|&b| b == 0).unwrap_or(s.len())]
}

/// "Load motion" onto a model (`LoadVmdMotion`, model branch,
/// `src/model/vmd_load.cpp`, VA 0x00434B60), at `frame`: every mark
/// cleared, an undo entry of the bone keys, then each bone key
/// (`RegisterBoneKey`), morph key (`RegisterMorphKeyFromRecord`) and IK key
/// (`RegisterDisplayKeyFromRecord`) of the file offset by `frame`, each list
/// stopping at its first failure. The caller checks the model name. `data`
/// is the file `vmd` was read from, for the IK section ([`load_vmd_ik`]).
pub fn load_vmd(
    m: &mut pmm::Model,
    s: &Skeleton,
    e: &mut ModelEdit,
    vmd: &mds_formats::vmd::Vmd,
    data: &[u8],
    frame: u32,
) -> Result<(), Error> {
    let rig = rig(m, s, false);
    let extra = extra(m, s, e, Physics { checkbox: true, mode: 0 });
    // The name is cut at a newline (`strchr(text, 10)`).
    let name = |raw: &[u8]| -> Vec<u8> {
        let n = cstr(raw);
        n[..n.iter().position(|&b| b == b'\n').unwrap_or(n.len())].to_vec()
    };
    e.history.push(Entry::BoneKeys {
        frame,
        pose: snapshot(m, 0..rig.bones.len()),
        keys: Vec::new(),
    });
    let mut touched = Touched::default();
    let mut first = Ok(());
    with_tracks(m, &mut e.search_cursor, |t| {
        t.clear_marks();
        t.reset_bone_cursor(&rig);
        for k in &vmd.bones {
            let c = &k.interpolation;
            // Byte 0 of each 4-byte cell; channel 0 holds the physics marker
            // in bytes 2..4.
            let mut interpolation = [0; 16];
            for ch in 0..4 {
                for row in 0..4 {
                    interpolation[ch + 4 * row] = c[16 * ch + 4 * row];
                }
            }
            let clip = BoneClip {
                name: name(&k.name.raw),
                frame: k.frame,
                rotation: k.rotation,
                position: k.position,
                physics_disabled: u8::from(u16::from_le_bytes([c[2], c[3]]) == 3939),
                interpolation,
            };
            let want = cstr(&clip.name);
            if let Some(b) = rig.bones.iter().position(|b| cstr(&b.name) == want) {
                touched.register(t, b as u32, frame.wrapping_add(clip.frame))?;
            }
            let r = t.register_bone_key_with(&rig, &extra, &clip, frame as i32, BoneTarget::Named);
            if first_err(&mut first, r) {
                break;
            }
        }
        t.reset_morph_cursor(&rig);
        for k in &vmd.morphs {
            let clip = MorphClip {
                name: name(&k.name.raw),
                frame: k.frame,
                value: if k.value.is_finite() { k.value } else { 0.0 },
            };
            if first_err(&mut first, t.register_morph_key(&rig, &clip, frame as i32)) {
                break;
            }
        }
        load_vmd_ik(t, &rig, &mut first, vmd, data, frame as i32);
        Ok::<_, Error>(())
    })?;
    fill_keys(&mut e.history, touched);
    first
}

/// `_read` on the file: copies what is left, returns the count.
struct Stream<'a>(&'a [u8]);

impl Stream<'_> {
    fn read(&mut self, buf: &mut [u8]) -> usize {
        let n = buf.len().min(self.0.len());
        buf[..n].copy_from_slice(&self.0[..n]);
        self.0 = &self.0[n..];
        n
    }
}

/// The IK section of the model branch of `LoadVmdMotion`, on the bytes as
/// the C++ reads them: it reads the camera, light and self-shadow counts as
/// three dwords without skipping their records, so a file with camera keys
/// takes the IK count from inside the first camera record and parses the
/// records after it from there. Short reads keep the bytes of the buffer;
/// the visible and IK flags are tested on a 16-bit `word` whose high byte
/// the last bone key's physics marker left.
fn load_vmd_ik(
    t: &mut Tracks,
    rig: &Rig,
    first: &mut Result<(), Error>,
    vmd: &mds_formats::vmd::Vmd,
    data: &[u8],
    frame_offset: i32,
) {
    let name_len = if vmd.is_v2() { 20 } else { 10 };
    let start = 30 + name_len + 4 + vmd.bones.len() * 111 + 4 + vmd.morphs.len() * 23;
    let mut s = Stream(data.get(start..).unwrap_or(&[]));
    // The last `_read(&word, 2)` of the bone loop: bytes 49..51 of the record.
    let mut word = data
        .get(start.saturating_sub(4 + vmd.morphs.len() * 23 + 62)..)
        .filter(|_| !vmd.bones.is_empty())
        .map_or(0, |b| u16::from_le_bytes([b[0], b[1]]));
    let mut count = [0u8; 4];
    for _ in 0..3 {
        s.read(&mut count);
    }
    if s.read(&mut count) == 0 {
        return;
    }
    t.reset_display_cursor();
    // ponytail: the record buffer starts zeroed (the C++ holds the last
    // morph name there) and short entry reads see zeros (uninitialized heap
    // in the C++); both only matter for a file that ends inside a record.
    let mut rec = [0u8; 12];
    let mut byte = [0u8; 1];
    let mut idle = false;
    for _ in 0..u32::from_le_bytes(count) {
        // At the end of the file every pass repeats the last one.
        if s.0.is_empty() && std::mem::replace(&mut idle, true) {
            break;
        }
        s.read(&mut rec[0..4]);
        if s.read(&mut byte) == 1 {
            word = (word & 0xFF00) | u16::from(byte[0]);
        }
        let visible = u8::from(word != 0);
        s.read(&mut rec[8..12]);
        let n = u32::from_le_bytes(rec[8..12].try_into().unwrap());
        if n > 0x2710 {
            break;
        }
        let mut ik = Vec::new();
        for _ in 0..n {
            let mut entry = [0u8; 20];
            s.read(&mut entry);
            if s.read(&mut byte) == 1 {
                word = (word & 0xFF00) | u16::from(byte[0]);
            }
            ik.push((cstr(&entry).to_vec(), u8::from(word != 0)));
        }
        let clip = DisplayClip {
            frame: i32::from_le_bytes(rec[0..4].try_into().unwrap()),
            visible,
            ik,
            selectors: Vec::new(),
        };
        if first.is_ok() {
            first_err(first, t.register_display_key(rig, &clip, frame_offset));
        }
    }
}

/// `DeleteMarkedModelKeys` (VA 0x004A09E0): with any bone key marked, an
/// undo entry whose records are `{i, previous, next}` of each marked bone
/// key in index order, read through the links as the unlinks leave them.
pub fn delete(
    m: &mut pmm::Model,
    s: &Skeleton,
    e: &mut ModelEdit,
    auto_interpolation: bool,
    frame: u32,
) -> Result<(), Error> {
    let rig = rig(m, s, auto_interpolation);
    let pool = &m.bone_keys;
    let marked: Vec<u32> = marked(pool).iter().map(|k| k.0).collect();
    if !marked.is_empty() {
        let heads = pool.heads().len() as u32;
        let mut links: BTreeMap<u32, (u32, u32)> = BTreeMap::new();
        let get = |l: &BTreeMap<u32, (u32, u32)>, i: u32| {
            l.get(&i)
                .copied()
                .unwrap_or_else(|| pool.get(i).map_or((0, 0), |k| (k.previous, k.next)))
        };
        let mut touched = Touched::default();
        for &i in &marked {
            let (prev, next) = get(&links, i);
            for j in [i, prev, next] {
                touched.add(pool, j);
            }
            if i >= heads {
                let p = get(&links, prev);
                links.insert(prev, (p.0, next));
                let n = get(&links, next);
                links.insert(next, (prev, n.1));
                links.insert(i, (0, 0));
            } else {
                let h = get(&links, i);
                links.insert(i, (0, h.1));
            }
        }
        e.history.push(Entry::BoneKeys {
            frame,
            pose: snapshot(m, 0..rig.bones.len()),
            keys: touched.into_keys(),
        });
    }
    with_tracks(m, &mut e.search_cursor, |t| t.delete_marked(&rig))?;
    Ok(())
}

/// `SnapshotPose` of the bone frame-line commands (`frame_line_edit.cpp`):
/// every bone's pose, with the selection byte where the other snapshots
/// keep the edited mark.
pub fn selection_snapshot(m: &pmm::Model) -> Vec<PoseSnapshot> {
    let mut pose = snapshot(m, 0..m.bone_pose.len());
    for (s, p) in pose.iter_mut().zip(&m.bone_pose) {
        s.edited = p.flags[2];
    }
    pose
}

/// Whether `DeleteBoneCameraFrameLine` at `frame` reaches its curve rebuild:
/// a bone key at `frame` is removed, or one shifts onto frame 0.
pub fn line_delete_rebuilds(m: &pmm::Model, frame: u32) -> bool {
    m.bone_keys
        .records()
        .iter()
        .any(|(_, k)| k.frame != 0 && (k.frame == frame || (frame < k.frame && k.frame == 1)))
}

/// `PushBoneEditUndo` (VA 0x0042D6E0) before a pose edit: the selected
/// bones, when there are any.
pub fn push_pose_edit(m: &pmm::Model, h: &mut History) {
    let selected: Vec<usize> = (0..m.bone_pose.len())
        .filter(|&i| m.bone_pose[i].flags[2] != 0)
        .collect();
    if !selected.is_empty() {
        h.push(Entry::BonePose(snapshot(m, selected.into_iter())));
    }
}

/// `SnapshotPoseBeforeFrameChange` (VA 0x004A0080): with any bone edited
/// and not registered, every bone's pose and the frame being left.
pub fn push_frame_change(m: &pmm::Model, h: &mut History, frame: u32) {
    if m.bone_pose.iter().any(|p| p.flags[1] != 0) {
        h.push(Entry::BonePoseWithFrame {
            frame,
            pose: snapshot(m, 0..m.bone_pose.len()),
        });
    }
}

/// Marks the keys of the track of `head` with a frame in `from..=to`.
pub fn select<K: mds_edit::Link>(
    pool: &mut KeyPool<K>,
    head: u32,
    from: u32,
    to: u32,
) -> Result<(), Error> {
    if head as usize >= pool.heads().len() {
        return Err(Error::NotApplicable("no such track"));
    }
    let mut i = head;
    for _ in 0..pool.capacity() {
        let k = pool
            .get_mut(i)
            .ok_or(Error::Edit(mds_edit::Error::Corrupt))?;
        if (from..=to).contains(&k.frame()) {
            k.set_allocated(1);
        }
        i = k.next();
        if i == 0 {
            return Ok(());
        }
    }
    Err(Error::Edit(mds_edit::Error::Corrupt))
}
