//! `Command::RegisterKinectCapture` against `RegisterKinectPoseCapture` and
//! `RegisterTraceBoneKey` (`src/app/oni_skeleton_pump.cpp` 214-310,
//! 318-487) and the pump tail (510-524).

use mds_doc::history::Entry;
use mds_doc::{Command, Document, Error, Track};
use mds_formats::key_pool::{Key, KeyPool};
use mds_formats::pmm::BoneKey;
use mds_kinect::KeyRegistration;
use std::path::PathBuf;

fn dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

/// swing600.pmm: slot 0 is chain8_ik.pmx (9 bones: 全ての親, センター,
/// 上半身, 首, ...); bone 1 has keys at 100, 200, 300, 400, 500 and 599,
/// bone 3 at 120, 240, 360, 480 and 599. The model's max frame is 599, and
/// the free bone records are 34 and 71 on.
fn doc() -> Document {
    let data = std::fs::read(dir().join("swing600.pmm")).unwrap();
    Document::load(&data, |p| std::fs::read(dir().join(p)).ok()).unwrap()
}

/// `(index, frame)` of the keys of a track, head first.
fn track<K: Key>(pool: &KeyPool<K>, head: u32) -> Vec<(u32, u32)> {
    let mut out = vec![(head, pool.get(head).unwrap().frame())];
    let mut i = pool.get(head).unwrap().next();
    while i != 0 {
        out.push((i, pool.get(i).unwrap().frame()));
        i = pool.get(i).unwrap().next();
    }
    out
}

fn frames(pool: &KeyPool<BoneKey>, head: u32) -> Vec<u32> {
    track(pool, head).iter().map(|k| k.1).collect()
}

/// A run of `n` keys of `bone` from `frame`, sample `k` at position
/// `(k, bone, 0)`.
fn run(bone: usize, frame: u32, n: u32) -> Vec<KeyRegistration> {
    (0..n)
        .map(|k| KeyRegistration {
            bone,
            frame: frame + k,
            position: [k as f32, bone as f32, 0.0],
            rotation: [0.0, 0.0, 0.5, 0.5],
        })
        .collect()
}

fn register(d: &mut Document, frame: u32, samples: u32, keys: Vec<KeyRegistration>) {
    d.apply(Command::RegisterKinectCapture {
        frame,
        samples,
        keys,
    })
    .unwrap();
}

fn validate(d: &Document) {
    let m = &d.pmm.models[0];
    m.bone_keys.validate_tracks().unwrap();
    m.morph_keys.validate_tracks().unwrap();
    m.display_keys.validate_tracks().unwrap();
}

#[test]
fn samples_go_into_fresh_records_between_the_keys() {
    // 0x7FF7CB4F2AD3: no record at the sample's frame -> the free record
    // after the current one, FillTraceKey (interpolation 20/20/107/107,
    // allocated 1), and the successor linked back after it.
    let mut d = doc();
    d.edit.models[0].search_cursor = 80;
    register(&mut d, 150, 3, run(1, 150, 3));
    let m = &d.pmm.models[0];
    let t = track(&m.bone_keys, 1);
    let f: Vec<u32> = t.iter().map(|k| k.1).collect();
    assert_eq!(f, [0, 100, 150, 151, 152, 200, 300, 400, 500, 599]);
    for (n, &(i, _)) in t[2..5].iter().enumerate() {
        let k = m.bone_keys.get(i).unwrap();
        assert_eq!(k.position, [n as f32, 1.0, 0.0]);
        assert_eq!(k.rotation, [0.0, 0.0, 0.5, 0.5]);
        assert_eq!(k.interpolation, mds_kinect::register::INTERPOLATION);
        assert_eq!(k.allocated, 1);
    }
    // The free scan starts at boneCount (9), not at the search cursor, and
    // skips the records in use (0x7FF7CB4F2451, 0x7FF7CB4F2D88).
    let fresh: Vec<u32> = t[2..5].iter().map(|k| k.0).collect();
    assert_eq!(fresh, [34, 71, 72]);
    validate(&d);
}

#[test]
fn a_sample_on_a_key_overwrites_it() {
    // 0x7FF7CB4F2813: the successor at the sample's frame is overwritten in
    // place and becomes the current record.
    let mut d = doc();
    let idx200 = track(&d.pmm.models[0].bone_keys, 1)[2].0;
    let count = d.pmm.models[0].bone_keys.records().len();
    register(&mut d, 199, 3, run(1, 199, 3));
    let m = &d.pmm.models[0];
    let t = track(&m.bone_keys, 1);
    assert_eq!(t[3], (idx200, 200));
    assert_eq!(
        frames(&m.bone_keys, 1),
        [0, 100, 199, 200, 201, 300, 400, 500, 599]
    );
    let k = m.bone_keys.get(idx200).unwrap();
    assert_eq!((k.position, k.allocated), ([1.0, 1.0, 0.0], 1));
    assert_eq!(m.bone_keys.records().len(), count + 2);
    validate(&d);
}

#[test]
fn a_capture_at_frame_0_writes_the_head() {
    // 0x7FF7CB4F2503: the current record (the head, frame 0) is the
    // sample's frame: overwritten, then the successor is linked back.
    let mut d = doc();
    register(&mut d, 0, 2, run(1, 0, 2));
    let m = &d.pmm.models[0];
    let head = &m.bone_keys.heads()[1];
    assert_eq!(
        (head.frame, head.position, head.allocated),
        (0, [0.0, 1.0, 0.0], 1)
    );
    assert_eq!(
        frames(&m.bone_keys, 1),
        [0, 1, 100, 200, 300, 400, 500, 599]
    );
    validate(&d);
}

#[test]
fn max_frame_follows_the_samples_and_the_tail_raises_the_last_registered_frame() {
    // 0x7FF7CB4F2DC9: maxFrame per sample; the pump tail (522-523):
    // lastRegisteredFrame = max(lastRegisteredFrame, maxFrame) and a settle.
    let mut d = doc();
    d.pmm.timeline.last_registered_frame = 0;
    d.edit.physics_reset_pending = false;
    register(&mut d, 598, 4, run(1, 598, 4));
    let m = &d.pmm.models[0];
    assert_eq!(m.selection.max_frame, 601);
    assert_eq!(d.pmm.timeline.last_registered_frame, 601);
    assert!(d.edit.physics_reset_pending);
    assert_eq!(
        frames(&m.bone_keys, 1),
        [0, 100, 200, 300, 400, 500, 598, 599, 600, 601]
    );
    validate(&d);
}

#[test]
fn runs_of_several_bones_and_one_undo_entry() {
    // 0x7FF7CB4F2FB2..0x7FF7CB4F318C: one type-2 slot, the pose of every bone
    // with its selection byte; AppendBoneKeyToUndo of {current, successor,
    // free} per sample, each record once (keyVisitMap).
    let mut d = doc();
    d.apply(Command::SelectBones(vec![2])).unwrap();
    let before: Vec<(u32, u32, u32, u32)> = [1u32, 3]
        .iter()
        .flat_map(|&b| track(&d.pmm.models[0].bone_keys, b))
        .map(|(i, f)| {
            let k = d.pmm.models[0].bone_keys.get(i).unwrap();
            (i, f, k.previous, k.next)
        })
        .collect();
    let cursor = d.edit.models[0].history.cursor;
    let keys = [run(1, 150, 2), run(3, 150, 2)].concat();
    register(&mut d, 150, 2, keys);
    let m = &d.pmm.models[0];
    let h = &d.edit.models[0].history;
    assert_eq!(h.cursor, (cursor + 1) % 30);
    let Entry::BoneKeys { frame, pose, keys } = &h.undo[h.cursor] else {
        panic!("{:?}", h.undo[h.cursor]);
    };
    assert_eq!((*frame, pose.len()), (150, 9));
    assert_eq!(pose[2].edited, 1, "the selection byte");
    assert_eq!(pose[1].edited, 0);
    // Each run scans from boneCount again.
    let fresh: Vec<u32> = [1, 3]
        .iter()
        .flat_map(|&b| track(&m.bone_keys, b))
        .filter(|k| k.1 == 150 || k.1 == 151)
        .map(|k| k.0)
        .collect();
    assert_eq!(fresh, [34, 71, 72, 73]);
    for i in &fresh {
        assert!(keys.iter().any(|k| k.0 == *i && k.1.is_none()), "{i}");
    }
    let mut seen: Vec<u32> = keys.iter().map(|k| k.0).collect();
    seen.dedup();
    assert_eq!(seen.len(), keys.len());
    validate(&d);

    d.apply(Command::Undo).unwrap();
    let after: Vec<(u32, u32, u32, u32)> = [1u32, 3]
        .iter()
        .flat_map(|&b| track(&d.pmm.models[0].bone_keys, b))
        .map(|(i, f)| {
            let k = d.pmm.models[0].bone_keys.get(i).unwrap();
            (i, f, k.previous, k.next)
        })
        .collect();
    assert_eq!(after, before);
}

#[test]
fn every_mark_is_cleared_and_no_samples_push_nothing() {
    // 0x7FF7CB4F2EC1..0x7FF7CB4F2F5F clears the allocated byte of the three
    // tables before the `samples > 0` gate (0x7FF7CB4F2F72).
    let mut d = doc();
    for c in [
        Command::SelectKeys {
            track: Track::Bone(1),
            from: 0,
            to: 599,
        },
        Command::SelectKeys {
            track: Track::Display,
            from: 0,
            to: 599,
        },
    ] {
        d.apply(c).unwrap();
    }
    let m = &d.pmm.models[0];
    assert!(m.bone_keys.records().iter().any(|(_, k)| k.allocated != 0));
    let history = format!("{:?}", d.edit.models[0].history.undo);
    register(&mut d, 150, 0, Vec::new());
    let m = &d.pmm.models[0];
    assert!(m.bone_keys.records().iter().all(|(_, k)| k.allocated == 0));
    assert!(m.bone_keys.heads().iter().all(|k| k.allocated == 0));
    assert!(m.display_keys.heads().iter().all(|k| k.allocated == 0));
    assert!(m
        .display_keys
        .records()
        .iter()
        .all(|(_, k)| k.allocated == 0));
    assert_eq!(format!("{:?}", d.edit.models[0].history.undo), history);
}

#[test]
fn keys_that_are_not_runs_are_refused_before_any_change() {
    let mut d = doc();
    let before = format!("{:?}", d.pmm.models[0].bone_keys);
    let bad = [
        (150, 3, run(1, 150, 2)),
        (150, 2, run(1, 151, 2)),
        (150, 2, run(9, 150, 2)),
        (150, 0, run(1, 150, 1)),
        (150, 2, [run(1, 150, 1), run(2, 151, 1)].concat()),
    ];
    for (frame, samples, keys) in bad {
        let r = d.apply(Command::RegisterKinectCapture {
            frame,
            samples,
            keys,
        });
        assert!(matches!(r, Err(Error::NotApplicable(_))));
    }
    assert_eq!(format!("{:?}", d.pmm.models[0].bone_keys), before);
    d.apply(Command::SelectCameraMode).unwrap();
    assert!(d
        .apply(Command::RegisterKinectCapture {
            frame: 0,
            samples: 1,
            keys: run(1, 0, 1),
        })
        .is_err());
}

#[test]
fn the_keys_of_mds_kinect_register() {
    // The bone list of 0x7FF7CB4F3247..: センター takes the position of trace
    // slot 0 (mode 0), 上半身 and 首 (1.40+) the rotation of slots 3 and 7
    // (mode 1); FillTraceKey copies them as mds_kinect::register reads them.
    let mut d = doc();
    let trace: Vec<[f32; 77]> = (0..3)
        .map(|k| std::array::from_fn(|i| (100 * k + i) as f32))
        .collect();
    let bones: Vec<mds_kinect::Bone> = d.pmm.models[0]
        .bone_names
        .iter()
        .map(|n| {
            let mut name = [0u8; 20];
            let raw = &n.raw[..20.min(n.raw.len())];
            name[..raw.len()].copy_from_slice(raw);
            mds_kinect::Bone {
                name,
                bind_y: 0.0,
                translation: [0.0; 3],
                rotation: [0.0, 0.0, 0.0, 1.0],
            }
        })
        .collect();
    let keys = mds_kinect::register::register(&trace, 15, 10, &bones, &[]);
    let order: Vec<usize> = keys.iter().map(|k| k.bone).collect();
    assert_eq!(order, [1, 1, 1, 2, 2, 2, 3, 3, 3]);
    register(&mut d, 10, 3, keys);
    let pool = &d.pmm.models[0].bone_keys;
    let key = |bone: u32, frame: u32| {
        let t = track(pool, bone);
        pool.get(t.iter().find(|k| k.1 == frame).unwrap().0)
            .unwrap()
            .clone()
    };
    let center = key(1, 12);
    assert_eq!(center.position, [200.0, 201.0, 202.0]);
    assert_eq!(center.rotation, [0.0, 0.0, 0.0, 1.0]);
    let upper = key(2, 11);
    assert_eq!(upper.position, [0.0; 3]);
    assert_eq!(upper.rotation, [104.0, 105.0, 106.0, 103.0]);
    assert_eq!(key(3, 10).rotation, [8.0, 9.0, 10.0, 7.0]);
    for b in 1..=3 {
        assert_eq!(&frames(pool, b)[..4], [0, 10, 11, 12]);
    }
    validate(&d);
}
