#![allow(dead_code)]

use mds_formats::key_pool::{Key, KeyPool};
use mds_formats::pmm::{BoneKey, CameraKey, DisplayKey, LightKey, MorphKey, Pmm, SelfShadowKey};
use mds_ops::{BoneFacts, ModelFacts};

pub const SWING600: &[u8] = include_bytes!("../../../../../tests/fixtures/rust/swing600.pmm");
pub const CAMERA3: &[u8] = include_bytes!("../../../../../tests/fixtures/rust/camera3.pmm");

/// `swing600.pmm`: model slot 0 is `chain8` with an IK bone (9 bones, 62 bone
/// keys, 3 display keys), slot 1 is `morph4` (2 bones, 4 morphs, 12 morph
/// keys), slots 2 and 3 are `chain8` without keys.
pub fn swing600() -> Pmm {
    Pmm::read(SWING600).expect("swing600.pmm reads")
}

/// `camera3.pmm`: `swing600.pmm` plus 2 camera keys (200, 400) and 2 light
/// keys (300, 450).
pub fn camera3() -> Pmm {
    Pmm::read(CAMERA3).expect("camera3.pmm reads")
}

/// The model-file facts of the fixture models, as the tests define them:
/// `chain8` is a chain of seven bones under a root and an IK root (parents
/// of `chain8.pmx`, the IK bone a root), all with rigid bodies but the IK
/// bone; `morph4` has two bones and four morphs whose `morph_type` bytes
/// are the PMX morph kinds of `morph4.pmx` (four vertex morphs), the byte
/// the C++ `MorphRecord::type` holds.
pub fn facts(pmm: &Pmm, model: usize) -> ModelFacts {
    let m = &pmm.models[model];
    let bone = |parent: i32, kind: u8, rigid_body: bool| BoneFacts {
        parent,
        kind,
        flags: 0,
        rigid_body,
        axis: [0.0; 3],
    };
    let bones = if m.bone_names.len() == 9 {
        let mut b: Vec<_> = (0..8)
            .map(|i| bone(i - 1, if i == 1 { 1 } else { 0 }, true))
            .collect();
        b.push(bone(-1, 2, false));
        b
    } else if m.bone_names.len() == 2 {
        vec![bone(-1, 1, false), bone(0, 0, false)]
    } else {
        (0..m.bone_names.len() as i32)
            .map(|i| bone(i - 1, 0, true))
            .collect()
    };
    ModelFacts {
        bones,
        morph_type: if m.morph_names.len() == 4 {
            vec![1, 1, 1, 1]
        } else {
            vec![0; m.morph_names.len()]
        },
        pmx: true,
    }
}

/// Selects the model in `slot` as the one the menus edit.
pub fn select(pmm: &mut Pmm, slot: u8) {
    pmm.selected_model_slot = slot;
}

/// The mode gate of the handlers: camera/light (true) or model (false).
pub fn camera_mode(pmm: &mut Pmm, on: bool) {
    pmm.settings.options[0] = u8::from(on);
}

/// `(pool index, frame)` along the track of `head`.
pub fn walk<K: Key>(pool: &KeyPool<K>, head: u32) -> Vec<(u32, u32)> {
    let mut out = Vec::new();
    let mut at = pool.get(head).expect("head").next();
    while at != 0 {
        let k = pool.get(at).expect("linked record exists");
        out.push((at, k.frame()));
        at = k.next();
        assert!(out.len() < 100_000, "track does not end");
    }
    out
}

/// The frames along the track of `head`.
pub fn frames<K: Key>(pool: &KeyPool<K>, head: u32) -> Vec<u32> {
    walk(pool, head).into_iter().map(|(_, f)| f).collect()
}

/// The frames of every track of the pool, by head.
pub fn all_frames<K: Key>(pool: &KeyPool<K>) -> Vec<Vec<u32>> {
    (0..pool.heads().len() as u32)
        .map(|h| frames(pool, h))
        .collect()
}

/// Every pool of the scene holds `KeyPool::validate_tracks`.
pub fn assert_valid(pmm: &Pmm) {
    for (i, m) in pmm.models.iter().enumerate() {
        m.bone_keys
            .validate_tracks()
            .unwrap_or_else(|e| panic!("model {i} bone keys: {e}"));
        m.morph_keys
            .validate_tracks()
            .unwrap_or_else(|e| panic!("model {i} morph keys: {e}"));
        m.display_keys
            .validate_tracks()
            .unwrap_or_else(|e| panic!("model {i} display keys: {e}"));
    }
    pmm.camera.validate_tracks().expect("camera keys");
    pmm.light.validate_tracks().expect("light keys");
    pmm.gravity.validate_tracks().expect("gravity keys");
    pmm.self_shadow.validate_tracks().expect("self-shadow keys");
    for (i, a) in pmm.accessories.iter().enumerate() {
        a.keys
            .validate_tracks()
            .unwrap_or_else(|e| panic!("accessory {i}: {e}"));
    }
}

/// `(index, frame, previous, next)` of every record of the pool, heads
/// first, for comparing whole pools.
pub fn shape<K: Key>(pool: &KeyPool<K>) -> Vec<(u32, u32, u32, u32)> {
    let heads = pool.heads().iter().enumerate().map(|(i, k)| (i as u32, k));
    let rest = pool.records().iter().map(|(i, k)| (*i, k));
    heads
        .chain(rest)
        .map(|(i, k)| (i, k.frame(), k.previous(), k.next()))
        .collect()
}

/// A pool of `heads` empty tracks with the given keys. `tracks[t]` lists
/// `(pool index, frame)` of the keys of track `t` in order; `make` builds a
/// record from `(frame, previous, next)`.
pub fn pool<K: Key + Clone + Default>(
    capacity: u32,
    heads: usize,
    tracks: &[&[(u32, u32)]],
    make: impl Fn(u32, u32, u32) -> K,
) -> KeyPool<K> {
    let mut pool = KeyPool::new(capacity, vec![K::default(); heads]).expect("heads fit");
    let mut head_next = vec![0u32; heads];
    for (t, keys) in tracks.iter().enumerate() {
        let mut prev = t as u32;
        for (n, &(index, frame)) in keys.iter().enumerate() {
            let next = keys.get(n + 1).map_or(0, |k| k.0);
            pool.insert(index, make(frame, prev, next)).expect("record");
            if n == 0 {
                head_next[t] = index;
            }
            prev = index;
        }
    }
    // The heads carry only their first link; callers set their payload.
    let heads_mut = pool.heads_mut();
    for (t, h) in heads_mut.iter_mut().enumerate() {
        *h = make(0, 0, head_next[t]);
    }
    pool
}

pub fn bone_key(frame: u32, previous: u32, next: u32) -> BoneKey {
    BoneKey {
        frame,
        previous,
        next,
        rotation: [0.0, 0.0, 0.0, 1.0],
        ..BoneKey::default()
    }
}

pub fn morph_key(frame: u32, previous: u32, next: u32) -> MorphKey {
    MorphKey {
        frame,
        previous,
        next,
        ..MorphKey::default()
    }
}

pub fn display_key(frame: u32, previous: u32, next: u32) -> DisplayKey {
    DisplayKey {
        frame,
        previous,
        next,
        visible: 1,
        ik_enabled: vec![1],
        selectors: vec![[-1, 0]; 4],
        ..DisplayKey::default()
    }
}

pub fn camera_key(frame: u32, previous: u32, next: u32) -> CameraKey {
    CameraKey {
        frame,
        previous,
        next,
        ..CameraKey::default()
    }
}

pub fn light_key(frame: u32, previous: u32, next: u32) -> LightKey {
    LightKey {
        frame,
        previous,
        next,
        ..LightKey::default()
    }
}

pub fn shadow_key(frame: u32, previous: u32, next: u32) -> SelfShadowKey {
    SelfShadowKey {
        frame,
        previous,
        next,
        ..SelfShadowKey::default()
    }
}
