//! Menu 227 (`src/window/command_file_menu.cpp` 1352-1438). The generator is
//! the MSVC CRT `rand()`; its sequence from the default seed 1 is 41, 18467,
//! 6334, 26500, 19169, 15724, 11478, 29358, 26962, 24464, so
//! `q = rand() * 230 / 32768` is 0, 129, 44, 186, 134, 110, 80, 206, 189, 171.

use super::common::*;
use mds_formats::pmm::Pmm;
use mds_ops::*;

fn scene() -> (Pmm, ModelFacts) {
    let mut p = swing600();
    select(&mut p, 1);
    let f = facts(&p, 1);
    (p, f)
}

/// `(frame, value)` along morph 0's track.
fn blinks(p: &Pmm) -> Vec<(u32, f32)> {
    let pool = &p.models[1].morph_keys;
    walk(pool, 0)
        .into_iter()
        .map(|(i, f)| (f, pool.get(i).unwrap().value))
        .collect()
}

#[test]
fn blinks_follow_the_generator_and_the_phase_byte() {
    // Step 1: q = 0 < 90 and phase 0 <= 0 -> frame 0 + 7, phase 3, blink at 7.
    // Step 2: q = 129; not < 90; > 50 -> frame 7 + 129 = 136, phase 2, blink
    // at 136; 136 >= 60 ends the loop. Each blink is 0, 1, 1, 0 at +0, +2, +3, +6.
    let (mut p, f) = scene();
    p.models[1].morph_pose[0] = 0.7;
    let (mut rng, mut phase) = (MsvcRand::default(), 0u8);
    assert_eq!(
        random_blinks(&mut p, &f, 0, 60, &mut rng, &mut phase),
        Ok(2)
    );
    assert_eq!(
        blinks(&p),
        [
            (7, 0.0),
            (9, 1.0),
            (10, 1.0),
            (13, 0.0),
            (100, original(100)),
            (110, original(110)),
            (136, 0.0),
            (138, 1.0),
            (139, 1.0),
            (142, 0.0),
            (400, original(400)),
            (410, original(410)),
        ]
    );
    assert_eq!(phase, 2);
    let mut again = MsvcRand::default();
    again.rand();
    again.rand();
    assert_eq!(rng, again, "two draws");
    // The new keys take the first free records in order: 16 .. 23.
    let pool = &p.models[1].morph_keys;
    let new: Vec<(u32, u32)> = pool
        .records()
        .iter()
        .filter(|(i, _)| *i >= 16)
        .map(|(i, k)| (*i, k.frame))
        .collect();
    assert_eq!(
        new,
        [
            (16, 7),
            (17, 9),
            (18, 10),
            (19, 13),
            (20, 136),
            (21, 138),
            (22, 139),
            (23, 142)
        ]
    );
    // The live weight ends at the last registered value, 0.
    assert_eq!(p.models[1].morph_pose[0], 0.0);
    // 599 is already past the new keys, so the scene's last frame stays.
    assert_eq!(p.models[1].selection.max_frame, 599);
    assert_eq!(p.timeline.last_registered_frame, 599);
    assert_valid(&p);
}

/// The value of morph 0's original key at `frame` in `swing600.pmm`.
fn original(frame: u32) -> f32 {
    let p = swing600();
    let pool = &p.models[1].morph_keys;
    walk(pool, 0)
        .into_iter()
        .find(|&(_, f)| f == frame)
        .map(|(i, _)| pool.get(i).unwrap().value)
        .unwrap()
}

#[test]
fn a_positive_phase_skips_the_short_branch_and_a_small_q_draws_again() {
    // phase 1: step 1 has q = 0 (not > 50) and the first branch needs
    // phase <= 0, so nothing happens and the loop draws again; step 2 has
    // q = 129 -> frame 129, phase 0, one blink.
    let (mut p, f) = scene();
    let (mut rng, mut phase) = (MsvcRand::default(), 1u8);
    assert_eq!(
        random_blinks(&mut p, &f, 0, 10, &mut rng, &mut phase),
        Ok(1)
    );
    assert_eq!(phase, 0);
    let fr: Vec<u32> = blinks(&p).iter().map(|b| b.0).collect();
    assert_eq!(fr, [100, 110, 129, 131, 132, 135, 400, 410]);
}

#[test]
fn a_negative_phase_byte_counts_as_not_positive() {
    // 1393: the phase is read as a signed byte, so 0xFF is -1.
    let (mut p, f) = scene();
    let (mut rng, mut phase) = (MsvcRand::default(), 0xFFu8);
    assert_eq!(random_blinks(&mut p, &f, 0, 7, &mut rng, &mut phase), Ok(1));
    assert_eq!(phase, 3);
    assert_eq!(blinks(&p)[0], (7, 0.0));
}

#[test]
fn an_empty_range_registers_nothing() {
    let (mut p, f) = scene();
    let before = shape(&p.models[1].morph_keys);
    let (mut rng, mut phase) = (MsvcRand::default(), 0u8);
    assert_eq!(
        random_blinks(&mut p, &f, 50, 50, &mut rng, &mut phase),
        Ok(0)
    );
    assert_eq!(shape(&p.models[1].morph_keys), before);
    assert_eq!((rng, phase), (MsvcRand::default(), 0));
}

#[test]
fn the_last_frame_of_the_scene_follows_a_blink_past_it() {
    // 1424-1427.
    let (mut p, f) = scene();
    p.models[1].selection.max_frame = 0;
    p.timeline.last_registered_frame = 0;
    let (mut rng, mut phase) = (MsvcRand::default(), 0u8);
    random_blinks(&mut p, &f, 0, 60, &mut rng, &mut phase).unwrap();
    assert_eq!(p.models[1].selection.max_frame, 142);
    assert_eq!(p.timeline.last_registered_frame, 142);
}

#[test]
fn a_model_without_the_blink_morph_is_refused() {
    // 1362-1378: the 9-byte name compare, then the message box.
    let mut p = swing600();
    let f = facts(&p, 0);
    let (mut rng, mut phase) = (MsvcRand::default(), 0u8);
    assert_eq!(
        random_blinks(&mut p, &f, 0, 60, &mut rng, &mut phase),
        Err(Error::NoBlinkMorph)
    );
    let (mut p, f) = scene();
    p.models[1].morph_names[0].raw = b"blink".to_vec();
    assert_eq!(
        random_blinks(&mut p, &f, 0, 60, &mut rng, &mut phase),
        Err(Error::NoBlinkMorph)
    );
    camera_mode(&mut p, true);
    assert_eq!(
        random_blinks(&mut p, &f, 0, 60, &mut rng, &mut phase),
        Err(Error::WrongMode)
    );
    assert_eq!((rng, phase), (MsvcRand::default(), 0));
}

#[test]
fn a_full_pool_does_not_stop_the_loop() {
    // RegisterMorphKeyCurrent's result is ignored (1402-1415): the blink
    // count still grows and the first error is reported after the loop.
    let (mut p, f) = scene();
    p.models[1].morph_keys = pool(6, 4, &[], morph_key);
    let (mut rng, mut phase) = (MsvcRand::default(), 0u8);
    let r = random_blinks(&mut p, &f, 0, 60, &mut rng, &mut phase);
    assert_eq!(
        r,
        Err(Error::Edit(mds_edit::Error::Full {
            pool: "morph",
            limit: 6
        }))
    );
    // The two free records took the first two keys of the first blink.
    assert_eq!(blinks(&p), [(7, 0.0), (9, 1.0)]);
    assert_eq!(phase, 2, "both steps ran");
    assert_valid(&p);
}
