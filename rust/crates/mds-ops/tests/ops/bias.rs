//! Menu 219 (`src/window/command_file_menu.cpp` 1042-1093).

use super::common::*;
use mds_ops::*;

#[test]
fn root_bones_marked_keys_move_by_the_offset() {
    // 1058-1081: for every record with allocated != 0, the bone is the record
    // itself below the bone count, else found by following `previous`; a key
    // moves when bones[bone].parent == -1. Chain8 has two roots: bone 0 and
    // the IK bone 8.
    let mut p = swing600();
    let f = facts(&p, 0);
    {
        let pool = &mut p.models[0].bone_keys;
        pool.heads_mut()[8].position = [1.0, 1.0, 1.0];
        pool.get_mut(70).unwrap().allocated = 0; // last key of bone 8, unmarked
        pool.get_mut(70).unwrap().position = [0.0, 0.0, -0.02];
    }
    center_position_bias(&mut p, &f, [10.0, 20.0, 30.0]).unwrap();
    let pool = &p.models[0].bone_keys;
    // Bone 0: head and its key 62 (previous 0, a head).
    assert_eq!(pool.heads()[0].position, [10.0, 20.0, 30.0]);
    assert_eq!(pool.get(62).unwrap().position, [-0.08 + 10.0, 20.0, 30.0]);
    // Bone 8: the head and key 38 move, the unmarked key 70 does not.
    assert_eq!(pool.heads()[8].position, [11.0, 21.0, 31.0]);
    assert_eq!(pool.get(38).unwrap().position, [10.0, 20.0, 30.0]);
    assert_eq!(pool.get(70).unwrap().position, [0.0, 0.0, -0.02]);
    // Bones with a parent do not move, whatever their mark.
    assert_eq!(pool.heads()[1].position, [0.0; 3]);
    assert_eq!(pool.get(24).unwrap().position, [0.0; 3]);
    assert_eq!(pool.get(63).unwrap().position, [0.0, -0.01, 0.0]);
    assert_valid(&p);
}

#[test]
fn a_key_resolves_to_its_bone_through_the_whole_track() {
    // The walk `bone = keys[bone].previous` runs until the index is below the
    // bone count, however many keys the track has: key 70 (bone 8) reaches
    // bone 8 through key 38.
    let mut p = swing600();
    let mut f = facts(&p, 0);
    for b in &mut f.bones {
        b.parent = 0;
    }
    f.bones[8].parent = -1;
    center_position_bias(&mut p, &f, [1.0, 0.0, 0.0]).unwrap();
    let pool = &p.models[0].bone_keys;
    assert_eq!(pool.get(70).unwrap().position, [1.0, 0.0, -0.02]);
    assert_eq!(pool.get(38).unwrap().position, [1.0, 0.0, 0.0]);
    assert_eq!(
        pool.get(62).unwrap().position,
        [-0.08, 0.0, 0.0],
        "bone 0 has a parent here"
    );
}

#[test]
fn offset_is_added_in_single_precision() {
    // 1076-1078: key.position[i] += offset (float).
    let mut p = swing600();
    let f = facts(&p, 0);
    p.models[0].bone_keys.heads_mut()[0].position = [0.1, 0.0, 0.0];
    center_position_bias(&mut p, &f, [0.2, 0.0, 0.0]).unwrap();
    assert_eq!(
        p.models[0].bone_keys.heads()[0].position[0],
        0.1f32 + 0.2f32
    );
}

#[test]
fn camera_mode_and_a_loop_in_previous_links_are_refused() {
    let mut p = swing600();
    let f = facts(&p, 0);
    camera_mode(&mut p, true);
    assert_eq!(
        center_position_bias(&mut p, &f, [1.0; 3]),
        Err(Error::WrongMode)
    );
    camera_mode(&mut p, false);
    // Key 9 and 11 point at each other: the walk never reaches a head.
    p.models[0].bone_keys.get_mut(9).unwrap().previous = 11;
    p.models[0].bone_keys.get_mut(11).unwrap().previous = 9;
    assert_eq!(
        center_position_bias(&mut p, &f, [1.0; 3]),
        Err(Error::Corrupt)
    );
}
