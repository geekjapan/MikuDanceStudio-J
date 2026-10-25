//! Model-mode key commands: `mds-edit` does the pool work, this module adds
//! the C++ around it (`src/model/model_keyframe_edit.cpp`,
//! `src/window/command_frame_register.cpp`, `command_frame_edit.cpp`,
//! `frame_clipboard.cpp`): mark clearing, undo entries with the records each
//! step touches (`AppendBoneKeyToUndo`), and the frame bookkeeping.

use crate::global::walk;
use crate::history::{snapshot, Entry, History};
use crate::{Error, ModelFile};
use mds_edit::{
    BoneClip, BoneInfo, DisplayClip, IkChain, MorphClip, MorphInfo, Rig, Selector, Tracks,
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
        (m.bones.len() == pmm_model.bone_names.len()).then(|| Skeleton {
            pmx: m.pmx,
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
}

/// `RegisterSelectedBoneKeys` (VA 0x004C2080), the register button (500):
/// an undo entry for every bone's pose, every mark cleared, then the pose
/// of each selected bone at `frame` (`RegisterBonePoseAtFrame` VA
/// 0x004B38A0), clearing its edited mark. A full pool skips that bone, as
/// the C++ loop ignores the result.
pub fn register_bones(
    m: &mut pmm::Model,
    s: &Skeleton,
    e: &mut ModelEdit,
    auto_interpolation: bool,
    frame: u32,
) -> Result<(), Error> {
    let rig = rig(m, s, auto_interpolation);
    let selected: Vec<usize> = (0..rig.bones.len())
        .filter(|&i| m.bone_pose[i].flags[2] != 0)
        .collect();
    if auto_interpolation {
        return Err(mds_edit::Error::Unsupported("automatic interpolation").into());
    }
    if selected.iter().any(|&i| rig.bones[i].rigid_body) {
        return Err(mds_edit::Error::Unsupported("pose of a bone with a rigid body").into());
    }
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
            first_err(&mut first, t.register_bone_pose(&rig, b, frame));
        }
        Ok::<_, Error>(())
    })?;
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
                if !rig.bones[b].twist {
                    let at = (frame as u32).wrapping_add(c.frame);
                    touched.register(t, b as u32, at)?;
                }
            }
            if first_err(&mut first, t.register_bone_key(&rig, c, frame)) {
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

fn cstr(s: &[u8]) -> &[u8] {
    &s[..s.iter().position(|&b| b == 0).unwrap_or(s.len())]
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
    if auto_interpolation {
        return Err(mds_edit::Error::Unsupported("automatic interpolation").into());
    }
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
