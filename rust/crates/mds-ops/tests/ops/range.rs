//! Menu 424 (`ApplyFrameRangeScale`, `src/window/frame_range_apply.cpp`
//! 297-340, with `ScaledRelativeFrame` 68-76 and the three `Scale*Keys`
//! 107-290).
//!
//! The frame of a key in `[start, end]` becomes `start + trunc((frame -
//! start) * scale)`; a key after `end` moves by `trunc((end - start) *
//! scale) - (end - start)`.

use super::common::*;
use mds_formats::pmm::Pmm;
use mds_ops::*;

fn morphs(start: i32, end: i32, scale: f64) -> RangeScale {
    RangeScale {
        start,
        end,
        scale,
        bones: false,
        morphs: true,
        display: false,
    }
}

fn scene() -> (Pmm, ModelFacts) {
    let mut p = swing600();
    select(&mut p, 1);
    let f = facts(&p, 1);
    (p, f)
}

/// `(frame, value)` along the track of morph `m`.
fn values(p: &Pmm, m: u32) -> Vec<(u32, f32)> {
    let pool = &p.models[1].morph_keys;
    walk(pool, m)
        .into_iter()
        .map(|(i, f)| (f, pool.get(i).unwrap().value))
        .collect()
}

#[test]
fn morph_keys_are_rebuilt_at_the_scaled_frames() {
    // Range [100, 300], scale 2: 100 -> 100, 110 -> 120, 150 -> 200, 200 ->
    // 300, 260 -> 420, 300 -> 500; after the range, +200: 400 -> 600,
    // 410 -> 610, 450 -> 650, 500 -> 700. The keys at 30 and 50 stay.
    let (mut p, f) = scene();
    let old: Vec<Vec<(u32, f32)>> = (0..4).map(|m| values(&p, m)).collect();
    scale_frame_range(&mut p, &f, &morphs(100, 300, 2.0)).unwrap();
    let map = |t: &[(u32, f32)], to: &[u32]| -> Vec<(u32, f32)> {
        t.iter().zip(to).map(|(&(_, v), &f)| (f, v)).collect()
    };
    assert_eq!(values(&p, 0), map(&old[0], &[100, 120, 600, 610]));
    let m1 = values(&p, 1);
    assert_eq!(m1[0], old[1][0], "the key at 50 is before the range");
    assert_eq!(m1[1..], map(&old[1][1..], &[200, 500, 650]));
    assert_eq!(values(&p, 2), map(&old[2], &[300, 420]));
    let m3 = values(&p, 3);
    assert_eq!(m3[0], old[3][0]);
    assert_eq!(m3[1..], map(&old[3][1..], &[700]));
    // The copies are registered in the order of the old records into the
    // first free records, which are the freed ones: each key keeps its index.
    let pool = &p.models[1].morph_keys;
    let at = |i: u32| pool.get(i).unwrap().frame;
    assert_eq!(
        (6..=15).map(at).collect::<Vec<_>>(),
        [100, 120, 200, 300, 420, 500, 600, 610, 650, 700]
    );
    assert_eq!(p.models[1].selection.max_frame, 700);
    assert_eq!(p.timeline.last_registered_frame, 700);
    assert_valid(&p);
}

#[test]
fn the_product_and_its_truncation_stay_in_single_precision() {
    // frame_range_apply.cpp 61-67: (float)20 * (float)1.05 rounds to 21.0f,
    // which truncates to 21; a double product truncates to 20.
    let (mut p, f) = scene();
    p.models[1].morph_keys = pool(20_000, 4, &[&[(4, 120)]], morph_key);
    p.models[1].morph_keys.get_mut(4).unwrap().value = 0.5;
    scale_frame_range(&mut p, &f, &morphs(100, 200, 1.05)).unwrap();
    assert_eq!(values(&p, 0), [(121, 0.5)]);
    assert_valid(&p);
}

#[test]
fn scaling_down_moves_later_keys_earlier() {
    // Range [100, 200], scale 0.5: 150 -> 125; 300 -> 300 + 50 - 100 = 250.
    let (mut p, f) = scene();
    p.models[1].morph_keys = pool(20_000, 4, &[&[(4, 150), (5, 300)]], morph_key);
    scale_frame_range(&mut p, &f, &morphs(100, 200, 0.5)).unwrap();
    assert_eq!(frames(&p.models[1].morph_keys, 0), [125, 250]);
    assert_valid(&p);
}

#[test]
fn a_start_of_zero_rebuilds_the_track_heads_too() {
    // 126-130: a head (i < morphCount) is marked when frame >= start, which
    // holds for start 0; DeleteMarked frees it and the registrar writes the
    // copy back to the same head. 50 -> 100; the keys after the range move by
    // trunc(100 * 2) - 100 = 100.
    let (mut p, f) = scene();
    p.models[1].morph_keys.heads_mut()[1].value = 0.3;
    scale_frame_range(&mut p, &f, &morphs(0, 100, 2.0)).unwrap();
    let h = &p.models[1].morph_keys.heads()[1];
    assert_eq!((h.value, h.allocated, h.frame), (0.3, 1, 0));
    assert_eq!(frames(&p.models[1].morph_keys, 1), [100, 250, 400, 550]);
    assert_valid(&p);
}

#[test]
fn the_other_families_marks_are_cleared_when_a_family_runs() {
    // 144-145, 191-192, 267-268: the keys of the other two pools lose their
    // marks before the delete; a family with nothing to move returns first.
    let (mut p, f) = scene();
    assert!(p.models[1]
        .bone_keys
        .heads()
        .iter()
        .all(|k| k.allocated == 1));
    p.models[1].bone_keys.heads_mut()[0].allocated = 1;
    p.models[1].display_keys.heads_mut()[0].allocated = 1;
    scale_frame_range(&mut p, &f, &morphs(1000, 2000, 2.0)).unwrap();
    assert_eq!(
        p.models[1].bone_keys.heads()[0].allocated,
        1,
        "no morph key at or after 1000"
    );
    scale_frame_range(&mut p, &f, &morphs(100, 300, 2.0)).unwrap();
    assert_eq!(p.models[1].bone_keys.heads()[0].allocated, 0);
    assert_eq!(p.models[1].display_keys.heads()[0].allocated, 0);
}

#[test]
fn bone_keys_keep_their_pose_and_curves() {
    // Range [100, 200], scale 0.5 on bones 1 and 5 of the chain: 150 -> 125,
    // 120 -> 110, 400 -> 400 + 50 - 200 + 100 = 350 (the registrar adds
    // `start`). The copies take the first free records after the freed ones.
    let mut p = swing600();
    let f = facts(&p, 0);
    let mut bones = pool(
        600_000,
        9,
        &[
            &[],
            &[(10, 50), (11, 150), (12, 400)],
            &[],
            &[],
            &[],
            &[(13, 120)],
        ],
        bone_key,
    );
    for (i, z) in [(10, 0.1), (11, 0.2), (12, 0.3), (13, 0.4)] {
        let k = bones.get_mut(i).unwrap();
        k.rotation = [0.0, 0.0, z, 0.9];
        k.position = [i as f32, 0.0, 0.0];
        k.interpolation = [i as u8; 16];
        k.physics_disabled = (i % 2) as u8;
    }
    p.models[0].bone_keys = bones;
    let s = RangeScale {
        bones: true,
        morphs: false,
        ..morphs(100, 200, 0.5)
    };
    scale_frame_range(&mut p, &f, &s).unwrap();
    let pool = &p.models[0].bone_keys;
    assert_eq!(frames(pool, 1), [50, 125, 350]);
    assert_eq!(frames(pool, 5), [110]);
    let pose = |bone: u32, frame: u32| {
        let (i, _) = walk(pool, bone)
            .into_iter()
            .find(|&(_, f)| f == frame)
            .unwrap();
        let k = pool.get(i).unwrap();
        (
            i,
            k.rotation[2],
            k.position[0],
            k.interpolation[0],
            k.physics_disabled,
        )
    };
    // Old records 11, 12, 13 are freed; the copies are allocated from the
    // first free record at or after the bone count, in index order.
    assert_eq!(pose(1, 125), (9, 0.2, 11.0, 11, 1));
    assert_eq!(pose(1, 350), (11, 0.3, 12.0, 12, 0));
    assert_eq!(pose(5, 110), (12, 0.4, 13.0, 13, 1));
    assert_eq!(pose(1, 50), (10, 0.1, 10.0, 10, 0));
    assert_valid(&p);
}

#[test]
fn display_keys_keep_their_flags_and_selectors() {
    // Range [250, 400], scale 0.5: 300 -> 275, 450 -> 450 + 75 - 150 + 250
    // - ... = 375; the key at 200 is before the range.
    let mut p = swing600();
    let f = facts(&p, 0);
    let before = p.models[0].display_keys.clone();
    let s = RangeScale {
        display: true,
        morphs: false,
        ..morphs(250, 400, 0.5)
    };
    scale_frame_range(&mut p, &f, &s).unwrap();
    let d = &p.models[0].display_keys;
    assert_eq!(frames(d, 0), [200, 275, 375]);
    let key = |frame: u32| {
        let (i, _) = walk(d, 0).into_iter().find(|&(_, f)| f == frame).unwrap();
        d.get(i).unwrap().clone()
    };
    let old = |frame: u32| {
        let (i, _) = walk(&before, 0)
            .into_iter()
            .find(|&(_, f)| f == frame)
            .unwrap();
        before.get(i).unwrap().clone()
    };
    for (new, was) in [(275, 300), (375, 450)] {
        let (k, o) = (key(new), old(was));
        assert_eq!(
            (k.visible, &k.ik_enabled, &k.selectors),
            (o.visible, &o.ik_enabled, &o.selectors)
        );
        assert_eq!(k.allocated, 1);
    }
    // The registrar reaches its records in the same order, so each key keeps
    // its index.
    assert_eq!(walk(d, 0), [(1, 200), (2, 275), (3, 375)]);
    assert_valid(&p);
}

#[test]
fn a_selector_that_names_every_bone_cannot_be_registered() {
    // The first selector's bone is -1, which mds-edit cannot look up; a free
    // bone stands in for it. With every bone named there is none.
    let mut p = swing600();
    let f = facts(&p, 0);
    p.models[0].selector_bones = vec![-1, 0, 1, 2, 3, 4, 5, 6, 7, 8];
    p.models[0].selector_pose = vec![[0, 0, -1, 0]; 10];
    let before = shape(&p.models[0].display_keys);
    let s = RangeScale {
        display: true,
        morphs: false,
        ..morphs(250, 400, 0.5)
    };
    assert_eq!(
        scale_frame_range(&mut p, &f, &s),
        Err(Error::Edit(mds_edit::Error::Corrupt))
    );
    assert_eq!(
        shape(&p.models[0].display_keys),
        before,
        "nothing is applied"
    );
}

#[test]
fn nothing_runs_for_an_empty_range_or_a_scale_that_changes_nothing() {
    // 306-311 and 321-323.
    let (mut p, f) = scene();
    let before = shape(&p.models[1].morph_keys);
    assert_eq!(
        scale_frame_range(&mut p, &f, &morphs(100, 100, 2.0)),
        Err(Error::EmptyRange)
    );
    assert_eq!(
        scale_frame_range(&mut p, &f, &morphs(300, 100, 2.0)),
        Err(Error::EmptyRange)
    );
    assert_eq!(
        scale_frame_range(&mut p, &f, &morphs(100, 300, 1.0)),
        Err(Error::ScaleOutOfRange)
    );
    assert_eq!(
        scale_frame_range(&mut p, &f, &morphs(100, 300, 0.000_009)),
        Err(Error::ScaleOutOfRange)
    );
    assert_eq!(
        scale_frame_range(&mut p, &f, &morphs(100, 300, 0.0)),
        Err(Error::ScaleOutOfRange)
    );
    assert_eq!(shape(&p.models[1].morph_keys), before);
    p.selected_model_slot = 9;
    assert_eq!(
        scale_frame_range(&mut p, &f, &morphs(100, 300, 2.0)),
        Err(Error::NoModel)
    );
}

#[test]
fn a_full_pool_ends_that_family_and_is_reported() {
    // 207-212: RegisterMorphKeyFromRecord returns false when no record is
    // free, which breaks the copy loop. Capacity 6 = 4 heads + 2 records.
    let (mut p, f) = scene();
    p.models[1].morph_keys = pool(6, 4, &[&[(4, 120), (5, 150)]], morph_key);
    // Scaling 100..200 by 2 moves both keys; the freed records take them
    // back, so nothing overflows here ...
    scale_frame_range(&mut p, &f, &morphs(100, 200, 2.0)).unwrap();
    assert_eq!(frames(&p.models[1].morph_keys, 0), [140, 200]);
    assert_valid(&p);
}
