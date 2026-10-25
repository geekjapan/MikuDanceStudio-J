//! The runtime model record: what the PMD and PMX loaders
//! (`src/model/pmd_load.cpp`, `src/model/pmx_load.cpp`) and the PMM v2
//! state load (`src/io/pmm_load_v2.cpp`) leave in `BoneRecord`, `IkChain`,
//! `MorphRecord` and the selector table (`BoneOrderEntry`).

use mds_formats::pmm;
use mds_formats::{pmd::Pmd, pmx::Offsets, pmx::Pmx};
use mds_math::{Mat4, Vec3};

/// `BoneType`, the type byte of `BoneRecord` (`bone_layout.hpp`).
pub mod kind {
    pub const MOVE: u8 = 1;
    pub const IK: u8 = 2;
    pub const UNDER_IK: u8 = 4;
    pub const ROTATE_GRANT: u8 = 5;
    pub const EFFECTOR: u8 = 6;
    pub const INERT_TIP: u8 = 7;
    pub const FIXED_AXIS: u8 = 8;
    pub const CO_ROTATE: u8 = 9;
}

/// Bone flag bits (`kBoneFlag*`).
pub mod flag {
    pub const MOVABLE: u16 = 0x0004;
    pub const VISIBLE: u16 = 0x0008;
    pub const IK: u16 = 0x0020;
    pub const ROT_INHERIT: u16 = 0x0100;
    pub const TRANS_INHERIT: u16 = 0x0200;
    pub const INHERIT_MASK: u16 = 0x0300;
    pub const FIXED_AXIS: u16 = 0x0400;
    pub const AFTER_PHYSICS: u16 = 0x1000;
}

const ZERO: Mat4 = Mat4([0.0; 16]);

/// `BoneRecord`, the fields the pose code reads or writes.
#[derive(Clone, Debug)]
pub struct Bone {
    /// SJIS name, for the PMD knee test (left zero for PMX bones).
    pub name: [u8; 20],
    pub parent: i32,
    pub mat_init: Mat4,
    pub mat_local: Mat4,
    pub mat_world: Mat4,
    pub mat_extra: Mat4,
    pub position: [f32; 3],
    pub trans: [f32; 3],
    pub rot_quat: [f32; 4],
    pub rot_quat2: [f32; 4],
    pub physics_offset: [f32; 3],
    pub physics_quat: [f32; 4],
    /// Position then quaternion, written by the physics readback.
    pub ik_backup: [f32; 7],
    pub tail_bone: i32,
    pub kind: u8,
    pub tail_idx: i32,
    pub has_rigid_body: u8,
    pub physics_disabled: u8,
    pub layer: i32,
    pub flags: u16,
    pub inherit_ratio: f32,
    pub axis: [f32; 3],
    pub twist_enable: u8,
    pub ik_limit_min: [f32; 3],
    pub ik_limit_max: [f32; 3],
    pub has_flag: u8,
    pub slot_index: i32,
}

impl Bone {
    fn new(name: [u8; 20], parent: i32, position: [f32; 3]) -> Bone {
        Bone {
            name,
            parent,
            mat_init: ZERO,
            mat_local: ZERO,
            mat_world: Mat4::IDENTITY,
            mat_extra: ZERO,
            position,
            trans: [0.0; 3],
            rot_quat: [0.0, 0.0, 0.0, 1.0],
            rot_quat2: [0.0, 0.0, 0.0, 1.0],
            physics_offset: [0.0; 3],
            physics_quat: [0.0; 4],
            ik_backup: [0.0; 7],
            tail_bone: 0,
            kind: 0,
            tail_idx: 0,
            has_rigid_body: 0,
            physics_disabled: 0,
            layer: 0,
            flags: 0,
            inherit_ratio: 0.0,
            axis: [0.0; 3],
            twist_enable: 0,
            ik_limit_min: [0.0; 3],
            ik_limit_max: [0.0; 3],
            has_flag: 0,
            slot_index: -1,
        }
    }
}

/// `IkChain`. `bone_index` is the IK bone, `target_bone` the effector.
#[derive(Clone, Debug)]
pub struct IkChain {
    pub bone_index: i32,
    pub target_bone: i32,
    pub links: Vec<u16>,
    pub iterations: u16,
    pub enabled: u8,
    pub max_angle: f32,
}

/// `BoneOrderEntry`: an IK-off window and an outside parent.
#[derive(Clone, Copy, Debug)]
pub struct Selector {
    pub bone_index: i32,
    pub window_start: u32,
    pub window_end: u32,
    /// -1 none, -2 ground, otherwise a model slot.
    pub linked_model: i32,
    pub linked_bone: i32,
}

/// The morph fields the pose reads. Material, vertex and UV morphs do not
/// reach the bones, so their entries are not kept.
#[derive(Clone, Debug)]
pub struct Morph {
    pub kind: u8,
    pub value: f32,
    /// Bone morph entries: index into `Model::bone_morph_offsets`,
    /// translation, rotation.
    pub bone_entries: Vec<(usize, [f32; 3], [f32; 4])>,
    /// Group morph entries: morph index and weight.
    pub group_entries: Vec<(usize, f32)>,
}

/// `BoneMorphOffsetRecord`.
#[derive(Clone, Copy, Debug)]
pub struct BoneMorphOffset {
    pub bone_index: usize,
    pub translation: [f32; 3],
    pub rotation: [f32; 4],
}

/// Playback cursors of one track.
#[derive(Clone, Debug, Default)]
pub struct Cursors {
    pub index: Vec<u32>,
    pub active: Vec<bool>,
}

/// One loaded model: its bones and IK chains, its PMM key tracks and its
/// playback cursors.
#[derive(Clone, Debug)]
pub struct Model {
    pub slot: u8,
    /// `ModelRecord::physicsMode == 2`: the file is a PMX.
    pub pmx: bool,
    /// `comboSelIndex2`, the calculation order.
    pub order: u8,
    pub max_layer: i32,
    pub bones: Vec<Bone>,
    pub iks: Vec<IkChain>,
    pub selectors: Vec<Selector>,
    pub morphs: Vec<Morph>,
    pub bone_morph_offsets: Vec<BoneMorphOffset>,
    pub bone_keys: mds_formats::key_pool::KeyPool<pmm::BoneKey>,
    pub morph_keys: mds_formats::key_pool::KeyPool<pmm::MorphKey>,
    pub display_keys: mds_formats::key_pool::KeyPool<pmm::DisplayKey>,
    pub display_cursor: u32,
    pub display_active: bool,
    pub morph_cursors: Cursors,
    pub bone_cursors: Cursors,
}

fn name20(raw: &[u8]) -> [u8; 20] {
    let mut name = [0; 20];
    let n = raw.len().min(20);
    name[..n].copy_from_slice(&raw[..n]);
    name
}

impl Model {
    fn empty(slot: u8, pmx: bool, bones: Vec<Bone>) -> Model {
        Model {
            slot,
            pmx,
            order: 0,
            max_layer: 0,
            bones,
            iks: Vec::new(),
            selectors: Vec::new(),
            morphs: Vec::new(),
            bone_morph_offsets: Vec::new(),
            bone_keys: mds_formats::key_pool::KeyPool::new(0, Vec::new()).unwrap(),
            morph_keys: mds_formats::key_pool::KeyPool::new(0, Vec::new()).unwrap(),
            display_keys: mds_formats::key_pool::KeyPool::new(0, Vec::new()).unwrap(),
            display_cursor: 0,
            display_active: false,
            morph_cursors: Cursors::default(),
            bone_cursors: Cursors::default(),
        }
    }

    /// The PMX loader: bones, the IK chain records, the layer pass, the
    /// selector table and the bone morphs.
    pub fn from_pmx(slot: u8, pmx: &Pmx) -> Result<Model, String> {
        let count = pmx.bones.len();
        let index = |i: i32| -> Result<usize, String> {
            usize::try_from(i)
                .ok()
                .filter(|&i| i < count)
                .ok_or_else(|| format!("bone index {i} out of range"))
        };
        let mut max_layer = 0;
        let mut bones = Vec::with_capacity(count);
        for b in &pmx.bones {
            // The SJIS name only feeds the PMD knee test.
            let mut bone = Bone::new([0; 20], b.parent, b.position);
            bone.layer = b.layer;
            max_layer = max_layer.max(b.layer);
            bone.flags = b.flags;
            bone.tail_bone = b.tail_bone;
            if b.flags & flag::MOVABLE != 0 {
                bone.kind = kind::MOVE;
            }
            if b.flags & flag::INHERIT_MASK != 0 {
                bone.tail_idx = b.inherit_parent;
                bone.inherit_ratio = b.inherit_ratio;
            }
            if b.flags & flag::FIXED_AXIS != 0 {
                bone.kind = kind::FIXED_AXIS;
                bone.axis = Vec3(b.fixed_axis).normalize().0;
            }
            if b.flags & flag::VISIBLE == 0 {
                bone.kind = kind::INERT_TIP;
            }
            bones.push(bone);
        }
        let mut model = Model::empty(slot, true, bones);
        for (i, b) in pmx.bones.iter().enumerate() {
            if b.flags & flag::IK == 0 {
                continue;
            }
            model.bones[i].kind = kind::IK;
            model.bones[index(b.ik.target)?].kind = kind::EFFECTOR;
            let max_angle = b.ik.angle * 0.25;
            let mut iterations = b.ik.loops as u16;
            if max_angle != 0.0 {
                // 0x40490FD8, the float pi of the loader.
                let limit = (f32::from_bits(0x4049_0fd8) / max_angle).min(360.0);
                if i32::from(iterations) < limit as i32 {
                    iterations = limit as i32 as u16;
                }
            }
            let mut links = Vec::with_capacity(b.ik.links.len());
            for link in b.ik.links.iter().take(usize::from(b.ik.links.len() as u8)) {
                let l = index(link.bone)?;
                let lb = &mut model.bones[l];
                lb.kind = kind::UNDER_IK;
                links.push(l as u16);
                if link.has_limits == 1 {
                    lb.twist_enable = 1;
                    lb.ik_limit_min = link.limits[0];
                    lb.ik_limit_max = link.limits[1];
                }
            }
            model.iks.push(IkChain {
                bone_index: i as i32,
                target_bone: b.ik.target,
                links,
                iterations,
                enabled: 1,
                max_angle,
            });
        }
        // Transform-layer inheritance pass.
        for i in 0..count {
            model.bones[i].has_flag = 0;
            let parent = model.bones[i].parent;
            let tail_kind = model.bones[index(model.bones[i].tail_idx)?].kind;
            let bone = &model.bones[i];
            if (parent >= 0 && model.bones[index(parent)?].has_flag != 0)
                || ((bone.kind == kind::ROTATE_GRANT || bone.flags & flag::INHERIT_MASK != 0)
                    && tail_kind == kind::UNDER_IK)
            {
                model.bones[i].has_flag = 1;
            } else if parent >= 0 {
                let p = &model.bones[index(parent)?];
                let (pl, pk) = (p.layer, p.kind);
                let bone = &mut model.bones[i];
                if bone.layer < pl {
                    bone.layer = pl;
                }
                if bone.kind != kind::UNDER_IK
                    && bone.kind != kind::EFFECTOR
                    && (pk == kind::UNDER_IK || pk == kind::EFFECTOR)
                {
                    bone.layer += 1;
                    max_layer = max_layer.max(bone.layer);
                }
            }
        }
        model.max_layer = max_layer;
        model.init_selectors();

        // Bone morphs index a table of the bones they move, in first-seen order.
        for m in &pmx.morphs {
            let mut morph = Morph {
                kind: m.kind,
                value: 0.0,
                bone_entries: Vec::new(),
                group_entries: Vec::new(),
            };
            match &m.offsets {
                Offsets::Group(entries) if m.kind == 0 => {
                    for &(target, weight) in entries {
                        let target = usize::try_from(target).unwrap_or(0);
                        if target >= pmx.morphs.len() {
                            return Err(format!("group morph index {target} out of range"));
                        }
                        morph.group_entries.push((target, weight));
                    }
                }
                Offsets::Bone(entries) => {
                    for &(bone, translation, rotation) in entries {
                        let bone = index(bone.max(0))?;
                        let slot = match model
                            .bone_morph_offsets
                            .iter()
                            .position(|r| r.bone_index == bone)
                        {
                            Some(p) => p,
                            None => {
                                model.bone_morph_offsets.push(BoneMorphOffset {
                                    bone_index: bone,
                                    translation: [0.0; 3],
                                    rotation: [0.0; 4],
                                });
                                model.bone_morph_offsets.len() - 1
                            }
                        };
                        morph.bone_entries.push((slot, translation, rotation));
                    }
                }
                _ => {}
            }
            model.morphs.push(morph);
        }
        for rigid in &pmx.rigids {
            if rigid.mode > 0 && rigid.bone >= 0 {
                model.bones[index(rigid.bone)?].has_rigid_body = 1;
            }
        }
        if !pmx.rigids.is_empty() {
            model.load_pose_passes();
        }
        Ok(model)
    }

    /// The PMD loader. PMD bones keep their file type, have layer 0 and get
    /// only the visible flag.
    pub fn from_pmd(slot: u8, pmd: &Pmd) -> Result<Model, String> {
        let count = pmd.bones.len();
        let index = |i: i32| -> Result<usize, String> {
            usize::try_from(i)
                .ok()
                .filter(|&i| i < count)
                .ok_or_else(|| format!("bone index {i} out of range"))
        };
        let mut bones = Vec::with_capacity(count);
        for b in &pmd.bones {
            let mut bone = Bone::new(name20(&b.name.raw), i32::from(b.parent), b.position);
            bone.tail_bone = i32::from(b.tail);
            bone.kind = b.kind;
            bone.tail_idx = i32::from(b.ik_parent);
            bone.flags |= flag::VISIBLE;
            bones.push(bone);
        }
        let mut model = Model::empty(slot, false, bones);
        for ik in &pmd.ik_chains {
            model.iks.push(IkChain {
                bone_index: i32::from(ik.bone),
                target_bone: i32::from(ik.target),
                links: ik.links.clone(),
                iterations: ik.iterations,
                enabled: 1,
                max_angle: ik.max_angle,
            });
        }
        for i in 0..count {
            let tail_kind = model.bones[index(model.bones[i].tail_idx)?].kind;
            let parent = model.bones[i].parent;
            let arm1 = parent >= 0 && model.bones[index(parent)?].has_flag != 0;
            let arm2 = model.bones[i].kind == kind::ROTATE_GRANT
                && (tail_kind == kind::IK || tail_kind == kind::UNDER_IK);
            model.bones[i].has_flag = u8::from(arm1 || arm2);
        }
        model.init_selectors();
        model.morphs = pmd
            .morphs
            .iter()
            .map(|_| Morph {
                kind: 1,
                value: 0.0,
                bone_entries: Vec::new(),
                group_entries: Vec::new(),
            })
            .collect();
        if let Some(physics) = pmd.extension.as_ref().and_then(|e| e.physics.as_ref()) {
            for rigid in &physics.rigids {
                if rigid.mode > 0 && rigid.bone >= 0 {
                    model.bones[index(i32::from(rigid.bone))?].has_rigid_body = 1;
                }
            }
            model.load_pose_passes();
        }
        Ok(model)
    }

    /// `InitBoneSortOrder`: slot 0 is the root dummy, then one slot per
    /// move or IK bone.
    fn init_selectors(&mut self) {
        self.selectors = vec![Selector {
            bone_index: -1,
            window_start: 0,
            window_end: 0,
            linked_model: -1,
            linked_bone: 0,
        }];
        for (i, bone) in self.bones.iter_mut().enumerate() {
            if bone.kind == kind::MOVE || bone.kind == kind::IK {
                bone.slot_index = self.selectors.len() as i32;
                self.selectors.push(Selector {
                    bone_index: i as i32,
                    ..self.selectors[0]
                });
            }
        }
    }

    /// The two `SetPhysicsMode(m, 0/1, nullptr, 0)` calls at the end of a
    /// load, before the rigid bodies are read.
    fn load_pose_passes(&mut self) {
        crate::pose::set_physics_mode(self, 0, &crate::pose::Others::NONE, 0);
        crate::pose::set_physics_mode(self, 1, &crate::pose::Others::NONE, 0);
    }

    /// Copies the PMM model block into the model: key tracks, the saved pose,
    /// morph weights, IK switches, selectors and the calculation order. The
    /// tables must match the model one to one (the C++ remaps by name; this
    /// port requires the identity mapping).
    pub fn apply_pmm(&mut self, source: &pmm::Model) -> Result<(), String> {
        if source.bone_names.len() != self.bones.len()
            || source.bone_pose.len() != self.bones.len()
            || source.bone_keys.heads().len() != self.bones.len()
            || source.morph_names.len() != self.morphs.len()
            || source.morph_pose.len() != self.morphs.len()
            || source.morph_keys.heads().len() != self.morphs.len()
            || source.ik_bones.len() != self.iks.len()
            || source.ik_pose.len() != self.iks.len()
            || source.selector_bones.len() != self.selectors.len()
            || source.selector_pose.len() != self.selectors.len()
            || source.display_keys.heads().len() != 1
        {
            return Err(format!(
                "slot {}: the PMM tables do not match the model file",
                source.slot
            ));
        }
        let display_ok = source
            .display_keys
            .heads()
            .iter()
            .chain(source.display_keys.records().iter().map(|(_, k)| k))
            .all(|k| {
                k.ik_enabled.len() == self.iks.len() && k.selectors.len() == self.selectors.len()
            });
        if !display_ok {
            return Err(format!(
                "slot {}: display key tables do not match",
                source.slot
            ));
        }
        for (bone, pose) in self.bones.iter_mut().zip(&source.bone_pose) {
            bone.trans = pose.translation;
            bone.rot_quat = pose.rotation;
            bone.physics_disabled = u8::from(pose.flags[0] == 1);
        }
        for (morph, &value) in self.morphs.iter_mut().zip(&source.morph_pose) {
            morph.value = value;
        }
        for (ik, &on) in self.iks.iter_mut().zip(&source.ik_pose) {
            ik.enabled = u8::from(on == 1);
        }
        for (selector, pose) in self.selectors.iter_mut().zip(&source.selector_pose) {
            selector.window_start = pose[0] as u32;
            selector.window_end = pose[1] as u32;
            selector.linked_model = pose[2];
            selector.linked_bone = pose[3];
        }
        self.bone_keys = source.bone_keys.clone();
        self.morph_keys = source.morph_keys.clone();
        self.display_keys = source.display_keys.clone();
        self.order = source.display_order;
        let bones = self.bones.len();
        let morphs = self.morphs.len();
        self.bone_cursors = Cursors {
            index: vec![0; bones],
            active: vec![false; bones],
        };
        self.morph_cursors = Cursors {
            index: vec![0; morphs],
            active: vec![false; morphs],
        };
        Ok(())
    }
}
