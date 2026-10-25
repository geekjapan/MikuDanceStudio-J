//! Menus 217, 218, 220 (`SelectFrameGroup`, `src/window/frame_line_edit.cpp`
//! 536-581) and 237 to 241 (`src/window/command_file_menu.cpp` 1964-2043).

use super::common::*;
use mds_formats::key_pool::KeyPool;
use mds_formats::pmm::{Accessory, AccessoryKey, AccessoryState, BoneKey, MorphKey};
use mds_formats::text::FixedSjis;
use mds_ops::*;

fn marks_bone(pool: &KeyPool<BoneKey>) -> Vec<(u32, u8)> {
    let heads = pool.heads().iter().enumerate();
    let heads = heads.map(|(i, k)| (i as u32, k.allocated));
    heads
        .chain(pool.records().iter().map(|(i, k)| (*i, k.allocated)))
        .collect()
}

#[test]
fn bone_marks_heads_and_keys_and_clears_free_records() {
    // 540-553: allocated = 0; then 1 when i < boneCount or frame != 0.
    let mut p = swing600();
    {
        let pool = &mut p.models[0].bone_keys;
        // A free record (frame 0) that still carries a mark, and a key
        // whose physics byte must survive: only +0x38 is stored.
        pool.insert(
            100,
            BoneKey {
                allocated: 1,
                ..BoneKey::default()
            },
        );
        pool.get_mut(9).unwrap().allocated = 0;
        pool.get_mut(9).unwrap().physics_disabled = 1;
        pool.heads_mut()[3].allocated = 0;
    }
    select_all_bone_frames(&mut p).unwrap();
    let pool = &p.models[0].bone_keys;
    for (i, mark) in marks_bone(pool) {
        let expect = i < 9 || pool.get(i).unwrap().frame != 0;
        assert_eq!(mark, u8::from(expect), "record {i}");
    }
    assert_eq!(
        pool.get(100).unwrap().allocated,
        0,
        "free record is cleared"
    );
    assert_eq!(pool.get(9).unwrap().physics_disabled, 1);
    assert_valid(&p);
}

#[test]
fn display_marks_keys_and_forces_record_zero() {
    // 554-565: allocated = (frame != 0); frames[0].allocated = 1 afterwards.
    let mut p = swing600();
    p.models[0].display_keys.heads_mut()[0].allocated = 0;
    p.models[0].display_keys.get_mut(2).unwrap().allocated = 0;
    select_all_display_frames(&mut p).unwrap();
    let pool = &p.models[0].display_keys;
    assert_eq!(pool.heads()[0].allocated, 1);
    let keys: Vec<_> = pool
        .records()
        .iter()
        .map(|(i, k)| (*i, k.allocated))
        .collect();
    assert_eq!(keys, [(1, 1), (2, 1), (3, 1)]);
    assert_valid(&p);
}

#[test]
fn display_head_is_forced_even_without_keys() {
    let mut p = swing600();
    select(&mut p, 2);
    select_all_display_frames(&mut p).unwrap();
    assert_eq!(p.models[2].display_keys.heads()[0].allocated, 1);
}

#[test]
fn morph_marks_heads_and_keys() {
    // 566-577: allocated = 1 when i < morphCount or frame != 0.
    let mut p = swing600();
    select(&mut p, 1);
    for (i, _) in p.models[1].morph_keys.records().to_vec() {
        p.models[1].morph_keys.get_mut(i).unwrap().allocated = 0;
    }
    p.models[1].morph_keys.insert(
        40,
        MorphKey {
            allocated: 1,
            ..MorphKey::default()
        },
    );
    select_all_morph_frames(&mut p).unwrap();
    let pool = &p.models[1].morph_keys;
    assert!(pool.heads().iter().all(|k| k.allocated == 1));
    for (i, k) in pool.records() {
        assert_eq!(k.allocated, u8::from(k.frame != 0), "record {i}");
    }
    assert_eq!(
        pool.records()
            .iter()
            .filter(|(_, k)| k.allocated == 1)
            .count(),
        12
    );
    assert_valid(&p);
}

#[test]
fn model_commands_need_a_model_in_the_selected_slot() {
    let mut p = swing600();
    p.selected_model_slot = 9;
    assert_eq!(select_all_bone_frames(&mut p), Err(Error::NoModel));
    assert_eq!(select_all_display_frames(&mut p), Err(Error::NoModel));
    assert_eq!(select_all_morph_frames(&mut p), Err(Error::NoModel));
}

#[test]
fn camera_light_shadow_and_gravity_mark_keys_and_record_zero() {
    // 1964-2027: selected = 1 when frame != 0 or the walk counter is 0.
    let mut p = camera3();
    p.camera.get_mut(2).unwrap().selected = 1;
    p.light.heads_mut()[0].selected = 1;
    p.light.get_mut(1).unwrap().selected = 1;
    p.gravity.heads_mut()[0].selected = 0;
    select_all_camera_frames(&mut p);
    select_all_light_frames(&mut p);
    select_all_self_shadow_frames(&mut p);
    select_all_gravity_frames(&mut p);
    let sel = |v: Vec<u8>| v;
    assert_eq!(
        sel(vec![
            p.camera.heads()[0].selected,
            p.camera.get(1).unwrap().selected,
            p.camera.get(2).unwrap().selected
        ]),
        [1, 1, 1]
    );
    assert_eq!(
        vec![
            p.light.heads()[0].selected,
            p.light.get(1).unwrap().selected,
            p.light.get(2).unwrap().selected
        ],
        [1, 1, 1]
    );
    assert_eq!(
        vec![
            p.self_shadow.heads()[0].selected,
            p.self_shadow.get(1).unwrap().selected
        ],
        [1, 1]
    );
    // Record 0 is selected although the gravity track holds no key.
    assert_eq!(p.gravity.heads()[0].selected, 1);
    assert!(p.gravity.records().is_empty());
    assert_valid(&p);
}

#[test]
fn unselected_records_without_keys_are_cleared() {
    let mut p = camera3();
    p.camera.insert(
        50,
        mds_formats::pmm::CameraKey {
            selected: 1,
            ..Default::default()
        },
    );
    select_all_camera_frames(&mut p);
    assert_eq!(p.camera.get(50).unwrap().selected, 0);
}

fn accessory(frames: &[u32]) -> Accessory {
    let mut keys = KeyPool::new(10_000, vec![AccessoryKey::default()]).unwrap();
    let mut prev = 0;
    for (n, &f) in frames.iter().enumerate() {
        let index = n as u32 + 1;
        keys.insert(
            index,
            AccessoryKey {
                frame: f,
                previous: prev,
                ..Default::default()
            },
        )
        .unwrap();
        if prev == 0 {
            keys.heads_mut()[0].next = index;
        } else {
            keys.get_mut(prev).unwrap().next = index;
        }
        prev = index;
    }
    Accessory {
        list_name: FixedSjis {
            raw: [0; 100],
            text: String::new(),
        },
        slot: 0,
        name: FixedSjis {
            raw: [0; 100],
            text: String::new(),
        },
        path: FixedSjis {
            raw: [0; 256],
            text: String::new(),
        },
        order: 0,
        keys,
        state: AccessoryState::default(),
    }
}

#[test]
fn accessory_tables_each_restart_at_record_zero() {
    // 2029-2043: esi is reset per table, so every table's record 0 is selected.
    let mut p = camera3();
    p.accessories = vec![accessory(&[10, 20]), accessory(&[])];
    select_all_accessory_frames(&mut p);
    let marks = |a: &Accessory| -> Vec<u8> {
        std::iter::once(a.keys.heads()[0].selected)
            .chain(a.keys.records().iter().map(|(_, k)| k.selected))
            .collect()
    };
    assert_eq!(marks(&p.accessories[0]), [1, 1, 1]);
    assert_eq!(marks(&p.accessories[1]), [1]);
    assert_valid(&p);
}
