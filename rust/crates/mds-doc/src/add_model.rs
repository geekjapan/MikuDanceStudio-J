//! "Add model" (button 435): `LoadModelFile` (`src/model/add_model.cpp`, VA
//! 0x00460430), `ModelInitDefaults` (`src/model/model_init.cpp`), the loaders
//! `pmx_load.cpp` and `pmd_load.cpp`, and the morph lanes of `PostLoadInit`
//! (`src/model/post_load_init.cpp`), as far as the PMM model block holds them.

use crate::{Error, ModelFile};
use encoding_rs::SHIFT_JIS;
use mds_formats::key_pool::{KeyPool, BONE_KEY_CAPACITY, DISPLAY_KEY_CAPACITY, MORPH_KEY_CAPACITY};
use mds_formats::pmm::{self, BoneKey, BonePose, DisplayKey, MorphKey, Selection};
use mds_formats::text::{FixedSjis, Sjis};
use mds_pose::model::Model as PoseModel;

/// `WideToSjis` (`src/main/charset_conv.cpp`): code page 932, cut to
/// `width - 1` bytes (`strncpy_s` with `_TRUNCATE`).
// ponytail: an unmappable character becomes '?'; the C++ falls back to its
// locale chain instead. Port that chain when a model needs it.
fn sjis(text: &str, width: usize) -> Sjis {
    let mut raw = Vec::new();
    let mut buf = [0u8; 4];
    for c in text.chars() {
        let (bytes, _, bad) = SHIFT_JIS.encode(c.encode_utf8(&mut buf));
        if bad {
            raw.push(b'?');
        } else {
            raw.extend_from_slice(&bytes);
        }
    }
    raw.truncate(width - 1);
    Sjis::from_raw(raw)
}

/// A fixed field up to its NUL.
fn until_nul(raw: &[u8]) -> Sjis {
    let n = raw.iter().position(|&b| b == 0).unwrap_or(raw.len());
    Sjis::from_raw(raw[..n].to_vec())
}

/// A PMX text, with `ReadTextBuf`'s `Null_%02d` for an empty one.
fn pmx_text(t: &str, nulls: &mut u32) -> String {
    if !t.is_empty() {
        return t.to_string();
    }
    *nulls += 1;
    format!("Null_{:02}", *nulls - 1)
}

/// The PMM model block of a model just loaded into `slot`, the
/// `combo`-th entry of the model combo.
pub(crate) fn record(
    slot: u8,
    path: &str,
    file: &ModelFile,
    combo: u8,
) -> Result<pmm::Model, Error> {
    let pose = match file {
        ModelFile::Pmx(p) => PoseModel::from_pmx(slot, p),
        ModelFile::Pmd(p) => PoseModel::from_pmd(slot, p),
        ModelFile::Missing => return Err(Error::NotApplicable("the model file is missing")),
    }
    .map_err(Error::Format)?;
    let format = |e: &str| Error::Format(format!("{path}: {e}"));
    let (name, name_en, bone_names, morphs) = match file {
        ModelFile::Pmx(p) => {
            // The counter runs over the model names, then (skipping the
            // texture and material names, which this port does not count)
            // the bone and morph names in file order.
            let mut nulls = 0;
            let name = sjis(&pmx_text(&p.name.text, &mut nulls), 50);
            let name_en = sjis(&pmx_text(&p.name_en.text, &mut nulls), 50);
            let mut bones = Vec::new();
            for b in &p.bones {
                bones.push(sjis(&pmx_text(&b.name.text, &mut nulls), 20));
                pmx_text(&b.name_en.text, &mut nulls);
            }
            let mut morphs = Vec::new();
            for m in &p.morphs {
                morphs.push((sjis(&pmx_text(&m.name.text, &mut nulls), 20), m.panel));
                pmx_text(&m.name_en.text, &mut nulls);
            }
            (name, name_en, bones, morphs)
        }
        ModelFile::Pmd(p) => {
            let name = until_nul(&p.name.raw);
            let english = p.extension.as_ref().and_then(|e| e.english.as_ref());
            let name_en = english.map_or(name.clone(), |e| until_nul(&e.name.raw[..19]));
            let bones = p.bones.iter().map(|b| until_nul(&b.name.raw)).collect();
            let morphs = p
                .morphs
                .iter()
                .map(|m| (until_nul(&m.name.raw), m.panel))
                .collect();
            (name, name_en, bones, morphs)
        }
        ModelFile::Missing => unreachable!(),
    };
    let bones = bone_names.len();
    if bones == 0 {
        return Err(format("a model without bones (not ported)"));
    }
    let group_count = crate::model::group_count(file).unwrap_or(0);
    // `PostLoadInit`: each morph lane selects its first morph (panels 1..4).
    let mut selected_morphs = [-1; 4];
    for (lane, sel) in selected_morphs.iter_mut().enumerate() {
        if let Some(i) = morphs.iter().position(|m| usize::from(m.1) == lane + 1) {
            *sel = i as i32;
        }
    }
    let ik_bones: Vec<i32> = pose.iks.iter().map(|k| k.bone_index).collect();
    let selector_bones: Vec<i32> = pose.selectors.iter().map(|s| s.bone_index).collect();
    let bone_head = BoneKey {
        frame: 0,
        previous: 0,
        next: 0,
        interpolation: [
            20, 20, 20, 20, 20, 20, 20, 20, 107, 107, 107, 107, 107, 107, 107, 107,
        ],
        position: [0.0; 3],
        rotation: [0.0, 0.0, 0.0, 1.0],
        allocated: 0,
        physics_disabled: 0,
    };
    let display_head = DisplayKey {
        visible: 1,
        ik_enabled: vec![1; ik_bones.len()],
        selectors: vec![[-1, 0]; selector_bones.len()],
        ..DisplayKey::default()
    };
    let pool = |what| move || format(what);
    let mut bone_pose = vec![
        BonePose {
            translation: [0.0; 3],
            rotation: [0.0, 0.0, 0.0, 1.0],
            flags: [0; 3],
        };
        bones
    ];
    // The loader selects bone 0 (`boneSelection[0] = 1`).
    bone_pose[0].flags[2] = 1;
    Ok(pmm::Model {
        slot,
        name,
        name_en,
        path: {
            let mut raw = [0; 256];
            let p = sjis(path, 256).raw;
            raw[..p.len()].copy_from_slice(&p);
            FixedSjis {
                raw,
                text: path.to_string(),
            }
        },
        group_count,
        bone_names,
        morph_names: morphs.iter().map(|m| m.0.clone()).collect(),
        selection: Selection {
            combo_index: combo,
            load_complete: 1,
            selected_bone: 0,
            selected_morphs,
            group_count_repeat: group_count,
            group_flags: vec![0; usize::from(group_count)],
            bone_list_pos: 0,
            max_frame: 0,
        },
        bone_keys: KeyPool::new(BONE_KEY_CAPACITY, vec![bone_head; bones])
            .ok_or_else(pool("too many bones"))?,
        morph_keys: KeyPool::new(MORPH_KEY_CAPACITY, vec![MorphKey::default(); morphs.len()])
            .ok_or_else(pool("too many morphs"))?,
        display_keys: KeyPool::new(DISPLAY_KEY_CAPACITY, vec![display_head])
            .ok_or_else(pool("display keys"))?,
        bone_pose,
        morph_pose: vec![0.0; morphs.len()],
        ik_pose: vec![1; ik_bones.len()],
        selector_pose: vec![[0, 0, -1, 0]; selector_bones.len()],
        ik_bones,
        selector_bones,
        post_load: 0,
        edge_scale: 1.0,
        toon: 1,
        display_order: combo,
    })
}
