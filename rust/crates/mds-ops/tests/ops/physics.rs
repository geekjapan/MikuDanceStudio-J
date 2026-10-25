//! Menu 275 (`ApplyPhysicsOnOff`, `src/window/misc_dialogs.cpp` 652-768).

use super::common::*;
use mds_ops::*;

#[test]
fn marked_keys_of_rigid_body_bones_take_the_dialog_choice() {
    // 745-764: for each bone with hasRigidBody, the marked keys on its track
    // from the head get physicsDisabled = (choice != 0).
    let mut p = swing600();
    let f = facts(&p, 0);
    {
        let pool = &mut p.models[0].bone_keys;
        pool.get_mut(24).unwrap().allocated = 0; // bone 1, 200
        pool.heads_mut()[3].allocated = 0;
    }
    set_physics_on_off(&mut p, &f, true).unwrap();
    let pool = &p.models[0].bone_keys;
    let disabled = |i: u32| pool.get(i).unwrap().physics_disabled;
    for h in 0..8 {
        let expect = u8::from(h != 3);
        assert_eq!(pool.heads()[h].physics_disabled, expect, "head {h}");
    }
    // Bone 8 (the IK bone) has no rigid body: head, 38 and 70 keep 0.
    assert_eq!(pool.heads()[8].physics_disabled, 0);
    assert_eq!((disabled(38), disabled(70)), (0, 0));
    assert_eq!((disabled(14), disabled(24), disabled(63)), (1, 0, 1));
    // Every key of the other bones is marked in the fixture.
    let on: usize = pool
        .records()
        .iter()
        .filter(|(_, k)| k.physics_disabled == 1)
        .count();
    assert_eq!(
        on,
        62 - 3 - 1,
        "all keys but bone 8's two and the unmarked one"
    );
    assert_valid(&p);

    // Choice 0 ("ON (X mark)") writes 0 on the same keys.
    set_physics_on_off(&mut p, &f, false).unwrap();
    let pool = &p.models[0].bone_keys;
    assert!(pool.records().iter().all(|(_, k)| k.physics_disabled == 0));
    assert_eq!(pool.heads()[0].physics_disabled, 0);
}

#[test]
fn without_a_marked_key_nothing_changes() {
    // 685-686: marked == 0 returns before any write.
    let mut p = swing600();
    let f = facts(&p, 0);
    for i in 0..9 {
        p.models[0].bone_keys.heads_mut()[i].allocated = 0;
    }
    let ids: Vec<u32> = p.models[0]
        .bone_keys
        .records()
        .iter()
        .map(|r| r.0)
        .collect();
    for i in ids {
        p.models[0].bone_keys.get_mut(i).unwrap().allocated = 0;
    }
    // The fixture has one key with the flag set (record 17); it stays.
    set_physics_on_off(&mut p, &f, false).unwrap();
    let flagged: Vec<u32> = p.models[0]
        .bone_keys
        .records()
        .iter()
        .filter(|(_, k)| k.physics_disabled != 0)
        .map(|r| r.0)
        .collect();
    assert_eq!(flagged, [17]);
}

#[test]
fn it_does_not_need_the_model_mode() {
    // The menu case has no mode gate (1222-1229).
    let mut p = swing600();
    let f = facts(&p, 0);
    camera_mode(&mut p, true);
    set_physics_on_off(&mut p, &f, true).unwrap();
    assert_eq!(p.models[0].bone_keys.heads()[0].physics_disabled, 1);
}
