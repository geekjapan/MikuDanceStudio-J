//! Pool invariants of `.claude/skills/verify-keyframe-pool/SKILL.md` over
//! random operation sequences, and what the operations must leave behind.
//! A small deterministic generator, so a failure names its seed.

use mds_edit::{
    BoneClip, BoneInfo, BoneTarget, DisplayClip, Error, Extra, IkChain, MorphClip, MorphInfo, Rig,
    Selector, Tracks,
};
use mds_formats::key_pool::{Key, KeyPool, DISPLAY_KEY_CAPACITY, MORPH_KEY_CAPACITY};
use mds_formats::pmm::MorphKey;

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
    fn below(&mut self, n: usize) -> usize {
        (self.next() >> 33) as usize % n
    }
}

fn rig() -> Rig {
    let names = |p: &str, n: usize| (0..n).map(|i| format!("{p}{i}")).collect::<Vec<_>>();
    Rig {
        bones: names("bone", 3).iter().map(|n| BoneInfo::new(n)).collect(),
        morphs: names("morph", 3)
            .into_iter()
            .map(|n| MorphInfo {
                name: n.into_bytes(),
                value: 0.5,
            })
            .collect(),
        ik_chains: vec![
            IkChain {
                bone: 1,
                enabled: 1,
            },
            IkChain {
                bone: 2,
                enabled: 0,
            },
        ],
        selectors: vec![
            Selector {
                bone: 0,
                linked_model: -1,
                linked_bone: 0,
            },
            Selector {
                bone: 2,
                linked_model: 1,
                linked_bone: 4,
            },
        ],
        pmx: true,
        load_complete: 1,
        auto_interpolation: false,
    }
}

/// The frames of the non-head keys of a track, in chain order.
fn frames<K: Key>(pool: &KeyPool<K>, head: u32) -> Vec<u32> {
    let mut out = Vec::new();
    let mut i = pool.get(head).unwrap().next();
    while i != 0 {
        let k = pool.get(i).unwrap();
        out.push(k.frame());
        i = k.next();
        assert!(out.len() < 100_000, "chain does not end");
    }
    out
}

fn check(t: &Tracks, what: &str) {
    for (name, r) in [
        ("bone", t.bone.validate_tracks()),
        ("morph", t.morph.validate_tracks()),
        ("display", t.display.validate_tracks()),
    ] {
        if let Err(e) = r {
            panic!("{name} pool broken after {what}: {e}");
        }
    }
}

/// Marks one random key (head included) of a random track.
fn mark_random(t: &mut Tracks, r: &mut Rng, rig: &Rig) {
    fn go<K: mds_edit::Link>(p: &mut KeyPool<K>, head: u32, r: &mut Rng) {
        let mut i = head;
        for _ in 0..r.below(4) {
            match p.get(i).unwrap().next() {
                0 => break,
                n => i = n,
            }
        }
        p.get_mut(i).unwrap().set_allocated(1);
    }
    match r.below(3) {
        0 => go(&mut t.bone, r.below(rig.bones.len()) as u32, r),
        1 => go(&mut t.morph, r.below(rig.morphs.len()) as u32, r),
        _ => go(&mut t.display, 0, r),
    }
}

/// Frames of the marked non-head keys of a track.
fn marked<K: mds_edit::Link>(p: &KeyPool<K>, head: u32) -> Vec<u32> {
    let (mut out, mut i) = (Vec::new(), p.get(head).unwrap().next());
    while i != 0 {
        let k = p.get(i).unwrap();
        if k.allocated() != 0 {
            out.push(k.frame());
        }
        i = k.next();
    }
    out
}

fn clip_frames(r: &mut Rng) -> (i32, u32) {
    (r.below(10) as i32, r.below(3) as u32)
}

fn run(seed: u64, ops: usize) {
    let rig = rig();
    let mut t = Tracks::new(&rig);
    let mut r = Rng(seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) | 1);
    for _ in 0..ops {
        let (before_b, before_m, before_d) = (
            (0..3).map(|i| frames(&t.bone, i)).collect::<Vec<_>>(),
            (0..3).map(|i| frames(&t.morph, i)).collect::<Vec<_>>(),
            frames(&t.display, 0),
        );
        let what;
        match r.below(8) {
            0 | 1 => {
                // paste a random mix of clips
                let (offset, _) = clip_frames(&mut r);
                let bones: Vec<BoneClip> = (0..r.below(3))
                    .map(|_| BoneClip {
                        name: format!("bone{}", r.below(3)).into_bytes(),
                        frame: r.below(3) as u32,
                        rotation: [0.0, 0.0, 0.0, 1.0],
                        position: [1.0, 2.0, 3.0],
                        physics_disabled: 0,
                        interpolation: [7; 16],
                    })
                    .collect();
                let morphs: Vec<MorphClip> = (0..r.below(3))
                    .map(|_| MorphClip {
                        name: format!("morph{}", r.below(3)).into_bytes(),
                        frame: r.below(3) as u32,
                        value: 0.25,
                    })
                    .collect();
                let displays: Vec<DisplayClip> = (0..r.below(2))
                    .map(|_| DisplayClip {
                        frame: r.below(3) as i32,
                        visible: 0,
                        ik: vec![(b"bone1".to_vec(), 0)],
                        selectors: vec![(b"bone2".to_vec(), 3, 4)],
                    })
                    .collect();
                what = format!(
                    "paste {} bones {} morphs {} displays at {offset}",
                    bones.len(),
                    morphs.len(),
                    displays.len()
                );
                t.paste_with(&rig, &Extra::default(), &bones, &morphs, &displays, offset)
                    .unwrap();
                check(&t, &what);
                for c in &bones {
                    let b = c.name[4] as usize - b'0' as usize;
                    assert!(
                        frames(&t.bone, b as u32).contains(&(offset as u32 + c.frame))
                            || offset as u32 + c.frame == 0,
                        "{what}: bone key lost"
                    );
                }
                for c in &morphs {
                    let m = c.name[5] as usize - b'0' as usize;
                    assert!(
                        frames(&t.morph, m as u32).contains(&(offset as u32 + c.frame))
                            || offset as u32 + c.frame == 0,
                        "{what}: morph key lost"
                    );
                }
                for c in &displays {
                    assert!(
                        frames(&t.display, 0).contains(&(offset as u32 + c.frame as u32))
                            || offset as u32 + c.frame as u32 == 0,
                        "{what}: display key lost"
                    );
                }
            }
            2 => {
                let selected: Vec<bool> = (0..3).map(|_| r.below(2) == 1).collect();
                let frame = r.below(12) as u32;
                what = format!("register bones {selected:?} at {frame}");
                t.register_selected_bone_keys_with(
                    &mut rig.clone(),
                    &mut Extra::default(),
                    &selected,
                    frame,
                )
                .unwrap();
                check(&t, &what);
                for (b, _) in selected.iter().enumerate().filter(|(_, s)| **s) {
                    assert!(
                        frame == 0 || frames(&t.bone, b as u32).contains(&frame),
                        "{what}: lost"
                    );
                }
            }
            3 => {
                let (morph, frame) = (r.below(3), r.below(12) as u32);
                what = format!("register morph {morph} at {frame}");
                t.clear_marks();
                t.register_morph_current(&rig, morph as i32, frame).unwrap();
                check(&t, &what);
                assert!(
                    frame == 0 || frames(&t.morph, morph as u32).contains(&frame),
                    "{what}: lost"
                );
            }
            4 => {
                let frame = r.below(12) as u32;
                what = format!("register display at {frame}");
                t.clear_marks();
                t.register_display_current(&rig, frame).unwrap();
                check(&t, &what);
                assert!(
                    frame == 0 || frames(&t.display, 0).contains(&frame),
                    "{what}: lost"
                );
            }
            5 | 6 => {
                what = "mark a random key".to_string();
                if r.below(3) == 0 {
                    t.clear_marks();
                }
                mark_random(&mut t, &mut r, &rig);
            }
            _ => {
                what = "delete marked keys".to_string();
                let gone_b: Vec<Vec<u32>> = (0..3).map(|i| marked(&t.bone, i)).collect();
                let gone_m: Vec<Vec<u32>> = (0..3).map(|i| marked(&t.morph, i)).collect();
                let gone_d = marked(&t.display, 0);
                t.delete_marked(&rig).unwrap();
                check(&t, &what);
                let left = |all: &[u32], gone: &[u32]| {
                    all.iter()
                        .copied()
                        .filter(|f| !gone.contains(f))
                        .collect::<Vec<_>>()
                };
                for i in 0..3 {
                    assert_eq!(
                        frames(&t.bone, i as u32),
                        left(&before_b[i], &gone_b[i]),
                        "{what}: bone {i}"
                    );
                    assert_eq!(
                        frames(&t.morph, i as u32),
                        left(&before_m[i], &gone_m[i]),
                        "{what}: morph {i}"
                    );
                }
                assert_eq!(
                    frames(&t.display, 0),
                    left(&before_d, &gone_d),
                    "{what}: display"
                );
                assert!(t.bone.heads().iter().all(|k| k.allocated == 0));
                assert!(t.bone.records().iter().all(|(_, k)| k.allocated == 0));
                assert!(t.morph.records().iter().all(|(_, k)| k.allocated == 0));
                assert!(t.display.records().iter().all(|(_, k)| k.allocated == 0));
            }
        }
        let _ = what;
    }
    // Registering never moves a key to another track: each track still ends.
    for i in 0..3 {
        frames(&t.bone, i);
        frames(&t.morph, i);
    }
}

#[test]
fn pools_stay_well_formed_over_random_sequences() {
    for seed in 0..1500 {
        let result = std::panic::catch_unwind(|| run(seed, 40));
        if let Err(e) = result {
            let msg = e.downcast_ref::<String>().cloned().unwrap_or_default();
            panic!("seed {seed}: {msg}");
        }
    }
}

#[test]
fn full_pools_return_errors_and_leave_the_cursor_at_capacity() {
    let rig = rig();
    // Morph pool: every record used (unlinked, which is enough for the scan).
    let mut t = Tracks::new(&rig);
    for i in 3..MORPH_KEY_CAPACITY {
        t.morph.insert(
            i,
            MorphKey {
                frame: 1,
                ..MorphKey::default()
            },
        );
    }
    let clip = MorphClip {
        name: b"morph0".to_vec(),
        frame: 0,
        value: 1.0,
    };
    let e = t
        .paste_with(&rig, &Extra::default(), &[], &[clip], &[], 5)
        .unwrap_err();
    assert_eq!(
        e,
        Error::Full {
            pool: "morph",
            limit: MORPH_KEY_CAPACITY
        }
    );
    // The reset to the display pool ran after the failed morph loop.
    assert_eq!(t.search_cursor, 1);

    // Display pool, filled through the real registrar.
    let mut t = Tracks::new(&rig);
    for f in 1..DISPLAY_KEY_CAPACITY {
        t.register_display_current(&rig, f).unwrap();
    }
    t.display.validate_tracks().unwrap();
    assert_eq!(
        t.register_display_current(&rig, 5000),
        Err(Error::Full {
            pool: "display",
            limit: DISPLAY_KEY_CAPACITY
        })
    );
    let clip = DisplayClip {
        frame: 0,
        visible: 1,
        ik: vec![],
        selectors: vec![],
    };
    let e = t
        .paste_with(&rig, &Extra::default(), &[], &[], &[clip], 5000)
        .unwrap_err();
    assert_eq!(
        e,
        Error::Full {
            pool: "display",
            limit: DISPLAY_KEY_CAPACITY
        }
    );
    t.display.validate_tracks().unwrap();
}

#[test]
fn bone_key_bumps_max_frame_with_the_raw_offset_unless_it_appends() {
    let rig = rig();
    let mut t = Tracks::new(&rig);
    let clip = |frame| BoneClip {
        name: b"bone1".to_vec(),
        frame,
        rotation: [0.0, 0.0, 0.0, 1.0],
        position: [0.0; 3],
        physics_disabled: 0,
        interpolation: [0; 16],
    };
    t.register_bone_key_with(&rig, &Extra::default(), &clip(0), 10, BoneTarget::Named)
        .unwrap();
    assert_eq!(t.max_frame, 10); // append: the summed frame
    t.max_frame = 0;
    t.register_bone_key_with(&rig, &Extra::default(), &clip(4), 3, BoneTarget::Named)
        .unwrap(); // frame 7 goes before 10
    assert_eq!(t.max_frame, 3); // insert: the raw offset (an original quirk)
    t.register_bone_key_with(&rig, &Extra::default(), &clip(7), 3, BoneTarget::Named)
        .unwrap(); // exact: frame 10
    assert_eq!(t.max_frame, 3);
    assert_eq!(frames(&t.bone, 1), [7, 10]);
}

#[test]
fn display_names_pick_the_ik_flag_and_selector_pair() {
    let rig = rig();
    let mut t = Tracks::new(&rig);
    let clip = DisplayClip {
        frame: 2,
        visible: 0,
        ik: vec![
            (b"bone2".to_vec(), 0),
            (b"bone1".to_vec(), 7),
            (b"bone1".to_vec(), 9),
        ],
        selectors: vec![(b"bone2".to_vec(), 3, 4), (b"nobody".to_vec(), 8, 8)],
    };
    t.register_display_key(&rig, &clip, 1).unwrap();
    let k = t
        .display
        .records()
        .iter()
        .find(|(_, k)| k.frame == 3)
        .unwrap()
        .1
        .clone();
    assert_eq!(k.visible, 0);
    // chain 0 is bone1 (first match: 7), chain 1 is bone2 (0)
    assert_eq!(k.ik_enabled, [7, 0]);
    // selector 0 is bone0 (no entry: default), selector 1 is bone2
    assert_eq!(k.selectors, [[-1, 0], [3, 4]]);
    assert_eq!(t.max_frame, 3);
}

#[test]
fn reverse_paste_of_an_unsided_name_reflects_onto_the_same_bone() {
    let rig = rig();
    let mut t = Tracks::new(&rig);
    let clip = BoneClip {
        name: b"bone2".to_vec(),
        frame: 0,
        rotation: [0.0, 0.6, 0.0, 0.8],
        position: [1.0, 2.0, 3.0],
        physics_disabled: 0,
        interpolation: [0; 16],
    };
    let extra = Extra::default();
    let none = BoneTarget::Selected(-1);
    t.paste_bones(&rig, &extra, std::slice::from_ref(&clip), 5, none)
        .unwrap();
    assert_eq!(
        t.bone.records().len(),
        0,
        "no selected bone: nothing pasted"
    );
    t.paste_bones(&rig, &extra, &[clip], 5, BoneTarget::Mirrored)
        .unwrap();
    assert_eq!(frames(&t.bone, 2), [5]);
    let k = &t.bone.records()[0].1;
    assert_eq!(k.rotation, [0.0, -0.6, 0.0, 0.8]);
    assert_eq!(k.position, [-1.0, 2.0, 3.0]);
}
