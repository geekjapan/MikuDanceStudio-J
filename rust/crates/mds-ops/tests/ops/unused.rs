//! Menu 222 (`src/window/command_file_menu.cpp` 1118-1145 and
//! `MarkRedundantModelKeys`, `src/model/model_key_reduction.cpp` 15-103).

use super::common::*;
use mds_formats::pmm::{BoneKey, DisplayKey, MorphKey};
use mds_ops::*;

fn marks_of<K: mds_formats::key_pool::Key>(
    pool: &mds_formats::key_pool::KeyPool<K>,
    f: impl Fn(&K) -> u8,
) -> u32 {
    let heads: u32 = pool.heads().iter().map(|k| u32::from(f(k))).sum();
    heads
        + pool
            .records()
            .iter()
            .map(|(_, k)| u32::from(f(k)))
            .sum::<u32>()
}

#[test]
fn fixture_duplicates_are_deleted_and_every_mark_is_cleared() {
    // 15-18: every mark is cleared first, then 24-52 mark interior keys equal
    // to both neighbours. In swing600 bone 1 holds the identity pose at
    // 100..500 and bone 4 at 100, 200, 400, 500; the last key of a track is
    // never a candidate so bone 1 loses
    // 100, 200, 300, 400 and bone 4 loses 100, 200, 400. Nothing else in the
    // fixture equals both neighbours.
    let mut p = swing600();
    let f = facts(&p, 0);
    let before = all_frames(&p.models[0].bone_keys);
    assert_eq!(remove_unused_keys(&mut p, &f), Ok(7));
    let m = &p.models[0];
    let mut expect = before;
    expect[1] = vec![500, 599];
    expect[4] = vec![500, 599];
    assert_eq!(all_frames(&m.bone_keys), expect);
    // The freed records are those the marks named (14, 24, 32, 45; 15, 25, 46).
    for i in [14, 24, 32, 45, 15, 25, 46] {
        let k = m.bone_keys.get(i).unwrap();
        assert_eq!(
            (k.frame, k.previous, k.next, k.allocated),
            (0, 0, 0, 0),
            "record {i}"
        );
    }
    assert_eq!(m.bone_keys.heads()[1].next, 55);
    assert_eq!(m.bone_keys.get(55).unwrap().previous, 1);
    assert_eq!(marks_of(&m.bone_keys, |k| k.allocated), 0);
    assert_eq!(marks_of(&m.display_keys, |k| k.allocated), 0);
    assert_eq!(marks_of(&m.morph_keys, |k| k.allocated), 0);
    assert_valid(&p);
}

#[test]
fn a_morph_equal_to_both_neighbours_is_deleted_and_the_last_key_is_never_a_candidate() {
    // 54-70: current = head.next; while keys[current].next != 0: compare with
    // previous and next (head included); the last key is skipped.
    let mut p = swing600();
    select(&mut p, 1);
    let f = facts(&p, 1);
    let mut morphs = pool(
        20_000,
        4,
        &[
            &[(10, 10), (11, 20), (12, 30), (13, 40)],
            &[(14, 5), (15, 6)],
        ],
        morph_key,
    );
    // Head 0: 0.5; keys 10, 20, 30 hold 0.5, key 40 holds 0.9.
    for (i, v) in [
        (10, 0.5),
        (11, 0.5),
        (12, 0.5),
        (13, 0.9),
        (14, 0.2),
        (15, 0.2),
    ] {
        morphs.get_mut(i).unwrap().value = v;
    }
    morphs.heads_mut()[0].value = 0.5;
    p.models[1].morph_keys = morphs;
    // Keys 10 and 11 equal both neighbours at the time of marking, even
    // though key 10 goes first: marking ends before any deletion.
    assert_eq!(remove_unused_keys(&mut p, &f), Ok(2));
    let pool = &p.models[1].morph_keys;
    assert_eq!(frames(pool, 0), [30, 40]);
    // The track of two keys has no interior key with a successor... key 5 has
    // successor 6 and equals the head? head value is 0, key 5 holds 0.2.
    assert_eq!(frames(pool, 1), [5, 6]);
    for i in [10, 11] {
        let k = pool.get(i).unwrap();
        assert_eq!(
            (k.frame, k.previous, k.next, k.allocated, k.value),
            (0, 0, 0, 0, 0.0)
        );
    }
    assert_eq!(pool.heads()[0].next, 12);
    assert_eq!(pool.get(12).unwrap().previous, 0);
    assert_valid(&p);
}

#[test]
fn bones_compare_position_and_rotation_with_float_equality() {
    // 5-11 (SamePose): -0.0 equals 0.0, NaN equals nothing; 24-26: bone types
    // 6 and 7 are skipped.
    let mut p = swing600();
    let mut f = facts(&p, 0);
    let rot = [0.0, 0.0, 0.5, 0.5];
    let keyed = |frame, prev, next, pos: [f32; 3], rot: [f32; 4]| BoneKey {
        position: pos,
        rotation: rot,
        ..bone_key(frame, prev, next)
    };
    // Tracks of bones 2 (frames 10..40) and 3 (the same), each with head
    // pose (0, identity) = key 10's pose except where the test says.
    let mut bones = pool(
        600_000,
        9,
        &[
            &[],
            &[],
            &[(20, 10), (21, 20), (22, 30), (23, 40)],
            &[(30, 10), (31, 20), (32, 30), (33, 40)],
        ],
        bone_key,
    );
    for (i, pos, r) in [
        (20, [0.0; 3], rot),
        (21, [-0.0, 0.0, 0.0], rot),
        (22, [0.0; 3], rot),
        (23, [1.0; 3], rot),
        (30, [0.0; 3], rot),
        (31, [0.0; 3], [f32::NAN, 0.0, 0.5, 0.5]),
        (32, [0.0; 3], rot),
        (33, [1.0; 3], rot),
    ] {
        let k = bones.get(i).unwrap().clone();
        *bones.get_mut(i).unwrap() = keyed(k.frame, k.previous, k.next, pos, r);
    }
    bones.heads_mut()[2].rotation = rot;
    bones.heads_mut()[3].rotation = rot;
    p.models[0].bone_keys = bones;
    // Bone 2: key 20 (prev head: same, next 21: same) and key 21 (-0.0 equals
    // 0.0) are candidates; key 22's next 23 differs. Bone 3: key 31 holds a
    // NaN and equals nothing, key 30 differs from it, key 32 differs from 33.
    // Bone 3 is a tip (type 7): skipped either way.
    f.bones[3].kind = 7;
    assert_eq!(remove_unused_keys(&mut p, &f), Ok(2));
    let pool = &p.models[0].bone_keys;
    assert_eq!(frames(pool, 2), [30, 40]);
    assert_eq!(frames(pool, 3), [10, 20, 30, 40]);
    assert_valid(&p);
}

#[test]
fn display_keys_compare_visibility_ik_flags_and_selectors() {
    // 72-103: the display track compares visible, the IK flags and the
    // selector pairs, with the model's counts (1 IK chain, 4 selectors).
    let mut p = swing600();
    let f = facts(&p, 0);
    p.models[0].bone_keys = pool(600_000, 9, &[], bone_key);
    let make = |frame, prev, next, visible, ik, sel: [i32; 2]| DisplayKey {
        visible,
        ik_enabled: vec![ik],
        selectors: vec![[-1, 0], [-1, 0], sel, [-1, 0]],
        ..display_key(frame, prev, next)
    };
    let mut d = pool(
        1_000,
        1,
        &[&[(1, 10), (2, 20), (3, 30), (4, 40), (5, 50)]],
        display_key,
    );
    *d.get_mut(1).unwrap() = make(10, 0, 2, 1, 1, [-1, 0]);
    *d.get_mut(2).unwrap() = make(20, 1, 3, 1, 1, [-1, 0]);
    *d.get_mut(3).unwrap() = make(30, 2, 4, 1, 1, [-1, 0]);
    *d.get_mut(4).unwrap() = make(40, 3, 5, 1, 1, [2, 7]);
    *d.get_mut(5).unwrap() = make(50, 4, 0, 1, 0, [2, 7]);
    d.heads_mut()[0] = make(0, 0, 1, 1, 1, [-1, 0]);
    p.models[0].display_keys = d;
    // Keys 10 and 20 equal both neighbours (the head included). Key 30 has
    // a successor that differs in its selector, key 40 a predecessor that
    // does, and the last key is never a candidate.
    assert_eq!(remove_unused_keys(&mut p, &f), Ok(2));
    assert_eq!(frames(&p.models[0].display_keys, 0), [30, 40, 50]);
    assert_valid(&p);

    // A different IK flag, a different visibility.
    let mut d = pool(1_000, 1, &[&[(1, 10), (2, 20), (3, 30)]], display_key);
    *d.get_mut(2).unwrap() = make(20, 1, 3, 0, 1, [-1, 0]);
    d.heads_mut()[0] = make(0, 0, 1, 1, 1, [-1, 0]);
    p.models[0].display_keys = d;
    assert_eq!(remove_unused_keys(&mut p, &f), Ok(0));
}

#[test]
fn camera_mode_and_missing_model_are_refused() {
    let mut p = swing600();
    let f = facts(&p, 0);
    camera_mode(&mut p, true);
    assert_eq!(remove_unused_keys(&mut p, &f), Err(Error::WrongMode));
    camera_mode(&mut p, false);
    p.selected_model_slot = 9;
    assert_eq!(remove_unused_keys(&mut p, &f), Err(Error::NoModel));
}

#[allow(dead_code)]
fn _t(_: MorphKey) {}
