//! Menus 225, 226, 228, 229, 230 and 231 (`src/window/command_file_menu.cpp`:
//! 1242-1321, 1323-1347, 1440-1465, 1654-1707, 1709-1735, 1737-1765, and
//! `PurgeMorphFrames` 372-411).
//!
//! The model is `morph4` (slot 1), whose pool in `swing600.pmm` is
//!
//! ```text
//! morph 0 (eye)   100 (6), 110 (7), 400 (12), 410 (13)
//! morph 1 (mouth)  50 (5), 150 (8), 300 (11), 450 (14)
//! morph 2 (mouth) 200 (9), 260 (10)
//! morph 3 (mouth)  30 (4), 500 (15)
//! ```
//!
//! The menus compare `MorphRecord::type`, the PMX morph kind, which is 1
//! (vertex) for all four morphs of `morph4.pmx`. So that each menu finds a
//! track, the scene gives them the kinds [2, 3, 3, 3] (a bone morph and three
//! UV morphs); `tests/fixtures/rust/script2/` covers the real kinds.

use super::common::*;
use mds_formats::pmm::Pmm;
use mds_ops::*;

fn scene() -> (Pmm, ModelFacts) {
    let mut p = swing600();
    select(&mut p, 1);
    let mut f = facts(&p, 1);
    f.morph_type = vec![2, 3, 3, 3];
    (p, f)
}

/// `(frame, previous, next, allocated, value)` of a morph record.
fn record(p: &Pmm, i: u32) -> (u32, u32, u32, u8, f32) {
    let k = p.models[1].morph_keys.get(i).unwrap();
    (k.frame, k.previous, k.next, k.allocated, k.value)
}

fn invalid(p: &Pmm) -> String {
    p.models[1].morph_keys.validate_tracks().unwrap_err()
}

#[test]
fn lip_shift_moves_every_key_of_the_lip_morphs() {
    // 1260-1316 with a positive shift: each key of a type 3 morph moves,
    // the tail included (1301-1311); the eye morph is not touched.
    let (mut p, f) = scene();
    shift_lip_frames(&mut p, &f, 10).unwrap();
    let pool = &p.models[1].morph_keys;
    assert_eq!(
        all_frames(pool),
        [
            vec![100, 110, 400, 410],
            vec![60, 160, 310, 460],
            vec![210, 270],
            vec![40, 510],
        ]
    );
    assert_valid(&p);
}

#[test]
fn lip_shift_drops_keys_that_reach_frame_zero_and_leaves_stale_previous_links() {
    // 1285-1297: v <= 0 -> frames[m].next = frames[cur].next; the record is
    // zeroed; frames[next].previous is NOT rewritten.
    let (mut p, f) = scene();
    let kept = record(&p, 8);
    shift_lip_frames(&mut p, &f, -50).unwrap();
    let pool = &p.models[1].morph_keys;
    // Morph 1: 50 becomes 0 and is dropped; 150, 300, 450 become 100, 250, 400.
    assert_eq!(frames(pool, 1), [100, 250, 400]);
    assert_eq!(pool.heads()[1].next, 8);
    assert_eq!(record(&p, 5), (0, 0, 0, 0, 0.0));
    // Record 8 still points back at the dropped record.
    assert_eq!(record(&p, 8), (100, 5, 11, kept.3, kept.4));
    // Morph 3: 30 becomes -20 and is dropped, the tail 500 becomes 450.
    assert_eq!(frames(pool, 3), [450]);
    assert_eq!(record(&p, 4).0, 0);
    assert_eq!(record(&p, 15).1, 4);
    // Morph 2 moves, morph 0 does not.
    assert_eq!(frames(pool, 2), [150, 210]);
    assert_eq!(frames(pool, 0), [100, 110, 400, 410]);
    assert_eq!(invalid(&p), "record 8 previous 5 != 1");
}

#[test]
fn lip_shift_that_drops_a_whole_track_leaves_it_empty() {
    // 1299-1311: the tail is dropped too when its new frame is not positive.
    let (mut p, f) = scene();
    shift_lip_frames(&mut p, &f, -1000).unwrap();
    let pool = &p.models[1].morph_keys;
    assert_eq!(
        all_frames(pool),
        [vec![100, 110, 400, 410], vec![], vec![], vec![]]
    );
    for i in [4, 5, 8, 9, 10, 11, 14, 15] {
        assert_eq!(record(&p, i), (0, 0, 0, 0, 0.0), "record {i}");
    }
    assert_valid(&p);
}

#[test]
fn lip_shift_skips_a_morph_without_keys_and_needs_the_model_mode() {
    let (mut p, mut f) = scene();
    f.morph_type = vec![0, 0, 3, 0];
    p.models[1].morph_keys.heads_mut()[2].next = 0;
    shift_lip_frames(&mut p, &f, 5).unwrap();
    camera_mode(&mut p, true);
    assert_eq!(shift_lip_frames(&mut p, &f, 5), Err(Error::WrongMode));
}

#[test]
fn delete_lip_frames_clears_all_but_the_last_key_of_each_lip_track() {
    // PurgeMorphFrames 372-411: the loop stops when the next record has no
    // successor, so the tail of the chain survives with the head's next = 0.
    let (mut p, f) = scene();
    let tails = [
        (14, record(&p, 14)),
        (10, record(&p, 10)),
        (15, record(&p, 15)),
    ];
    delete_lip_frames(&mut p, &f).unwrap();
    let pool = &p.models[1].morph_keys;
    assert_eq!(
        all_frames(pool),
        [vec![100, 110, 400, 410], vec![], vec![], vec![]]
    );
    // The cleared records keep their `next` (the C++ does not touch it).
    assert_eq!(record(&p, 5), (0, 0, 8, 0, 0.0));
    assert_eq!(record(&p, 8), (0, 0, 11, 0, 0.0));
    assert_eq!(record(&p, 11), (0, 0, 14, 0, 0.0));
    assert_eq!(record(&p, 9), (0, 0, 10, 0, 0.0));
    assert_eq!(record(&p, 4), (0, 0, 15, 0, 0.0));
    // The heads: frame, previous, mark and value cleared, next 0.
    for h in 1..4 {
        let k = &pool.heads()[h];
        assert_eq!(
            (k.frame, k.previous, k.next, k.allocated, k.value),
            (0, 0, 0, 0, 0.0)
        );
    }
    // The tails stay, untouched, on no track.
    for (i, before) in tails {
        assert_eq!(record(&p, i), before, "record {i}");
        assert_ne!(before.0, 0);
    }
    assert_eq!(invalid(&p), "record 10 is on no track");
}

#[test]
fn delete_eye_and_eyebrow_frames_purge_their_own_morphs() {
    // 1440-1465 (type 2) and 1737-1765 (type 1).
    let (mut p, f) = scene();
    delete_eye_frames(&mut p, &f).unwrap();
    assert_eq!(frames(&p.models[1].morph_keys, 0), Vec::<u32>::new());
    assert_eq!(record(&p, 13).0, 410, "the last key survives");
    assert_eq!(record(&p, 6), (0, 0, 7, 0, 0.0));
    assert_eq!(
        frames(&p.models[1].morph_keys, 2),
        [200, 260],
        "the mouth is untouched"
    );

    let (mut p, mut f) = scene();
    delete_eyebrow_frames(&mut p, &f).unwrap();
    assert_eq!(
        all_frames(&p.models[1].morph_keys),
        all_frames(&swing600().models[1].morph_keys)
    );
    f.morph_type = vec![0, 1, 0, 0];
    delete_eyebrow_frames(&mut p, &f).unwrap();
    assert_eq!(frames(&p.models[1].morph_keys, 1), Vec::<u32>::new());
    assert_eq!(record(&p, 14).0, 450);
}

#[test]
fn a_purged_track_with_one_key_keeps_that_key() {
    // 392-398: for head -> a, a.next == 0 stops the loop at a, so the only
    // key survives, unreachable.
    let (mut p, mut f) = scene();
    f.morph_type = vec![0, 0, 0, 3];
    p.models[1].morph_keys = pool(20_000, 4, &[&[], &[], &[], &[(9, 30)]], morph_key);
    p.models[1].morph_keys.get_mut(9).unwrap().value = 0.5;
    delete_lip_frames(&mut p, &f).unwrap();
    assert_eq!(p.models[1].morph_keys.heads()[3].next, 0);
    assert_eq!(record(&p, 9), (30, 3, 0, 0, 0.5));
    assert_eq!(invalid(&p), "record 9 is on no track");
}

#[test]
fn reset_morphs_zeroes_the_weights_and_no_key() {
    // 1709-1735.
    let (mut p, _) = scene();
    p.models[1].morph_pose = vec![0.25, 0.5, 0.75, 1.0];
    let keys = shape(&p.models[1].morph_keys);
    reset_morphs(&mut p).unwrap();
    assert_eq!(p.models[1].morph_pose, [0.0; 4]);
    assert_eq!(shape(&p.models[1].morph_keys), keys);
    camera_mode(&mut p, true);
    assert_eq!(reset_morphs(&mut p), Err(Error::WrongMode));
}

#[test]
fn register_all_puts_the_live_weight_of_every_morph_at_the_current_frame() {
    // 1654-1707 and RegisterMorphKeyCurrent: the marks of the three pools
    // are cleared first; every morph gets a key at frame 100, an existing one
    // updated in place, a new one in the first free record (16, 17, 18).
    let (mut p, f) = scene();
    p.models[1].morph_pose = vec![0.25, 0.5, 0.75, 1.0];
    p.timeline.current_frame = 100;
    p.timeline.last_registered_frame = 0;
    p.models[1].selection.max_frame = 0;
    register_all_morph_frames(&mut p, &f).unwrap();
    let pool = &p.models[1].morph_keys;
    assert_eq!(
        all_frames(pool),
        [
            vec![100, 110, 400, 410],
            vec![50, 100, 150, 300, 450],
            vec![100, 200, 260],
            vec![30, 100, 500],
        ]
    );
    assert_eq!(
        record(&p, 6),
        (100, 0, 7, 1, 0.25),
        "morph 0 had a key at 100"
    );
    assert_eq!(record(&p, 16), (100, 5, 8, 1, 0.5));
    assert_eq!(record(&p, 17), (100, 2, 9, 1, 0.75));
    assert_eq!(record(&p, 18), (100, 4, 15, 1, 1.0));
    // Marks: only the keys just registered; the other keys lost theirs.
    let marked: Vec<u32> = pool
        .records()
        .iter()
        .filter(|(_, k)| k.allocated == 1)
        .map(|r| r.0)
        .collect();
    assert_eq!(marked, [6, 16, 17, 18]);
    assert!(pool.heads().iter().all(|k| k.allocated == 0));
    // The model's last frame follows the new keys, and the scene's last
    // registered frame follows the model's.
    assert_eq!(p.models[1].selection.max_frame, 100);
    assert_eq!(p.timeline.last_registered_frame, 100);
    assert_valid(&p);
}

#[test]
fn register_all_skips_morph_zero_on_a_pmd_model() {
    // RegisterMorphKeyCurrent returns for morph 0 unless the model is PMX.
    let (mut p, mut f) = scene();
    f.pmx = false;
    p.models[1].morph_pose = vec![0.25, 0.5, 0.75, 1.0];
    p.timeline.current_frame = 120;
    register_all_morph_frames(&mut p, &f).unwrap();
    let pool = &p.models[1].morph_keys;
    assert_eq!(frames(pool, 0), [100, 110, 400, 410]);
    assert_eq!(frames(pool, 1), [50, 120, 150, 300, 450]);
    assert_valid(&p);
}

#[test]
fn register_all_continues_past_a_full_pool_and_reports_the_first_one() {
    // 1690-1699 ignore the result of RegisterMorphKeyCurrent and keep going;
    // here two records are free for four morphs.
    let (mut p, f) = scene();
    p.models[1].morph_keys = pool(6, 4, &[], morph_key);
    p.models[1].morph_pose = vec![0.5; 4];
    p.timeline.current_frame = 7;
    let r = register_all_morph_frames(&mut p, &f);
    assert_eq!(
        r,
        Err(Error::Edit(mds_edit::Error::Full {
            pool: "morph",
            limit: 6
        }))
    );
    let pool = &p.models[1].morph_keys;
    assert_eq!(all_frames(pool), [vec![7], vec![7], vec![], vec![]]);
    assert_valid(&p);
}

#[test]
fn facial_menus_need_the_model_mode_and_a_model() {
    let (mut p, f) = scene();
    camera_mode(&mut p, true);
    assert_eq!(delete_lip_frames(&mut p, &f), Err(Error::WrongMode));
    assert_eq!(delete_eye_frames(&mut p, &f), Err(Error::WrongMode));
    assert_eq!(delete_eyebrow_frames(&mut p, &f), Err(Error::WrongMode));
    assert_eq!(register_all_morph_frames(&mut p, &f), Err(Error::WrongMode));
    camera_mode(&mut p, false);
    p.selected_model_slot = 9;
    assert_eq!(delete_lip_frames(&mut p, &f), Err(Error::NoModel));
}
