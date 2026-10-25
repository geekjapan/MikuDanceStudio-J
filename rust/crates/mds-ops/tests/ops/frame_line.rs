//! Menus 255 to 258 (`src/window/frame_line_edit.cpp`: insert bone/camera
//! 184-249, delete bone/camera 252-389, insert facial/light 392-432, delete
//! facial/light 435-526).

use super::common::*;
use mds_formats::key_pool::KeyPool;
use mds_formats::pmm::{BoneKey, CameraKey};
use mds_ops::*;

/// The frames of every track of `old`, shifted the way the C++ does for a
/// command at `at`: `up` adds one at or after `at`.
fn inserted(old: &[Vec<u32>], at: u32) -> Vec<Vec<u32>> {
    old.iter()
        .map(|t| t.iter().map(|&f| if f >= at { f + 1 } else { f }).collect())
        .collect()
}

/// Keys at `at` are removed, keys after it move down by one.
fn deleted(old: &[Vec<u32>], at: u32) -> Vec<Vec<u32>> {
    old.iter()
        .map(|t| {
            t.iter()
                .filter(|&&f| f != at)
                .map(|&f| if f > at { f - 1 } else { f })
                .collect()
        })
        .collect()
}

#[test]
fn insert_bone_shifts_every_key_from_the_current_frame() {
    // 187-232: keyFrame != 0 && i >= boneCount && keyFrame >= currentFrame
    // -> frame + 1; maxFrame rises to the largest new frame.
    let mut p = swing600();
    p.timeline.current_frame = 100;
    let before = all_frames(&p.models[0].bone_keys);
    let links = shape(&p.models[0].bone_keys)
        .into_iter()
        .map(|(i, _, prev, next)| (i, prev, next))
        .collect::<Vec<_>>();
    p.models[0].selection.max_frame = 0;
    insert_bone_camera_frame_line(&mut p).unwrap();
    let pool = &p.models[0].bone_keys;
    assert_eq!(all_frames(pool), inserted(&before, 100));
    let after = shape(pool)
        .into_iter()
        .map(|(i, _, prev, next)| (i, prev, next))
        .collect::<Vec<_>>();
    assert_eq!(after, links, "links do not change");
    // Keys at 100 are now at 101, the key at 90 stays.
    assert_eq!(pool.get(14).unwrap().frame, 101);
    assert_eq!(pool.get(13).unwrap().frame, 90);
    // The last frame was 599; 600 is the largest new frame.
    assert_eq!(p.models[0].selection.max_frame, 600);
    assert_valid(&p);
}

#[test]
fn insert_bone_past_the_last_key_changes_nothing() {
    // 199-200: nothing affected, return before any write.
    let mut p = swing600();
    p.timeline.current_frame = 1000;
    p.models[0].selection.max_frame = 7;
    let before = shape(&p.models[0].bone_keys);
    insert_bone_camera_frame_line(&mut p).unwrap();
    assert_eq!(shape(&p.models[0].bone_keys), before);
    assert_eq!(p.models[0].selection.max_frame, 7);
}

#[test]
fn insert_camera_shifts_the_camera_track_and_the_registered_frame() {
    // 234-249: camera keys at or after the frame move up; the registered
    // frame becomes the largest new frame when it is larger.
    let mut p = camera3();
    camera_mode(&mut p, true);
    p.timeline.current_frame = 200;
    p.timeline.last_registered_frame = 0;
    insert_bone_camera_frame_line(&mut p).unwrap();
    assert_eq!(frames(&p.camera, 0), [201, 401]);
    assert_eq!(p.timeline.last_registered_frame, 401);
    // The bone keys are untouched in camera mode.
    assert_eq!(frames(&p.models[0].bone_keys, 1)[0], 100);
    assert_valid(&p);
}

#[test]
fn insert_morph_and_light() {
    // 414-431 (morph, 0x14-byte records) and 395-411 (light).
    let mut p = swing600();
    select(&mut p, 1);
    p.timeline.current_frame = 100;
    p.models[1].selection.max_frame = 0;
    let before = all_frames(&p.models[1].morph_keys);
    insert_morph_light_frame_line(&mut p).unwrap();
    assert_eq!(all_frames(&p.models[1].morph_keys), inserted(&before, 100));
    assert_eq!(p.models[1].selection.max_frame, 501);
    assert_valid(&p);

    let mut p = camera3();
    camera_mode(&mut p, true);
    p.timeline.current_frame = 300;
    p.timeline.last_registered_frame = 0;
    insert_morph_light_frame_line(&mut p).unwrap();
    assert_eq!(frames(&p.light, 0), [301, 451]);
    assert_eq!(p.timeline.last_registered_frame, 451);
    assert_valid(&p);
}

#[test]
fn delete_bone_removes_keys_at_the_frame_and_shifts_later_keys() {
    // 252-351: keyFrame == current -> unlink and ClearBoneKeyRecord, then
    // prev = next = 0; current < keyFrame -> frame - 1.
    let mut p = swing600();
    p.timeline.current_frame = 100;
    let before = all_frames(&p.models[0].bone_keys);
    delete_bone_camera_frame_line(&mut p).unwrap();
    let pool = &p.models[0].bone_keys;
    assert_eq!(all_frames(pool), deleted(&before, 100));
    // Bone 1's track was 14 (100) -> 24 (200); 14 is unlinked.
    assert_eq!(pool.heads()[1].next, 24);
    assert_eq!(pool.get(24).unwrap().previous, 1);
    // The removed record keeps its curves and physics byte, nothing else.
    let k = pool.get(14).unwrap();
    assert_eq!((k.frame, k.previous, k.next, k.allocated), (0, 0, 0, 0));
    assert_eq!((k.position, k.rotation), ([0.0; 3], [0.0, 0.0, 0.0, 1.0]));
    assert_eq!(k.interpolation[0], 20);
    assert_valid(&p);
}

#[test]
fn delete_of_a_last_key_writes_previous_of_record_zero() {
    // 303-304: keys[next].previous = prev with next == 0 writes record 0.
    // Every track of the fixture ends at 599, so the last of them (70, whose
    // previous is 38) decides.
    let mut p = swing600();
    p.timeline.current_frame = 599;
    delete_bone_camera_frame_line(&mut p).unwrap();
    let pool = &p.models[0].bone_keys;
    assert_eq!(pool.heads()[0].previous, 38);
    assert_eq!(pool.heads()[0].next, 0, "bone 0's only key was removed");
    assert_valid(&p);
}

#[test]
fn delete_bone_moves_a_key_that_lands_on_frame_zero_into_the_head() {
    // 318-342: keyFrame - 1 == 0 -> payload into keys[previous], its next
    // moves up, then ClearBoneKeyRecord; the emptied record keeps its links.
    let mut p = swing600();
    let mut a = bone_key(1, 5, 11);
    a.position = [1.0, 2.0, 3.0];
    a.rotation = [0.5, 0.5, 0.5, 0.5];
    a.interpolation = [9; 16];
    a.allocated = 1;
    a.physics_disabled = 1;
    let b = bone_key(5, 10, 0);
    let mut bones = pool(
        600_000,
        9,
        &[&[], &[], &[], &[], &[], &[(10, 1), (11, 5)]],
        bone_key,
    );
    bones.insert(10, a);
    bones.insert(11, b);
    p.models[0].bone_keys = bones;
    p.timeline.current_frame = 0;
    delete_bone_camera_frame_line(&mut p).unwrap();
    let pool = &p.models[0].bone_keys;
    let head = &pool.heads()[5];
    assert_eq!(head.next, 11);
    assert_eq!(head.position, [1.0, 2.0, 3.0]);
    assert_eq!(head.rotation, [0.5, 0.5, 0.5, 0.5]);
    assert_eq!(head.interpolation, [9; 16]);
    assert_eq!(head.allocated, 1);
    assert_eq!(head.physics_disabled, 0, "the physics byte is not copied");
    assert_eq!(pool.get(11).unwrap().previous, 5);
    assert_eq!(pool.get(11).unwrap().frame, 4);
    let e = pool.get(10).unwrap();
    assert_eq!((e.frame, e.allocated, e.position), (0, 0, [0.0; 3]));
    assert_eq!((e.previous, e.next), (5, 11), "links are left as they were");
    assert_eq!(e.physics_disabled, 1);
    assert_valid(&p);
}

#[test]
fn delete_camera_clears_the_record_the_way_the_c_code_lists() {
    // 353-385 and ClearCameraKeyRecord 167-179: eye z, target z, the last two
    // curve bytes of each row and the parent stay; the rest is zeroed.
    let mut p = camera3();
    camera_mode(&mut p, true);
    p.timeline.current_frame = 200;
    {
        let k = p.camera.get_mut(1).unwrap();
        k.eye = [1.0, 2.0, 3.0];
        k.target = [4.0, 5.0, 6.0];
        k.parent_model = 2;
        k.parent_bone = 3;
        k.interpolation = [[7; 6]; 4];
        k.selected = 1;
    }
    delete_bone_camera_frame_line(&mut p).unwrap();
    assert_eq!(frames(&p.camera, 0), [399]);
    assert_eq!(p.camera.heads()[0].next, 2);
    assert_eq!(p.camera.get(2).unwrap().previous, 0);
    let k = p.camera.get(1).unwrap();
    assert_eq!((k.frame, k.previous, k.next, k.selected), (0, 0, 0, 0));
    assert_eq!((k.perspective, k.fov, k.distance), (0, 0, 0.0));
    assert_eq!(k.eye, [0.0, 0.0, 3.0]);
    assert_eq!(k.target, [0.0, 0.0, 6.0]);
    assert_eq!((k.parent_model, k.parent_bone), (2, 3));
    assert_eq!(k.interpolation, [[0, 0, 0, 0, 7, 7]; 4]);
    assert_valid(&p);
}

#[test]
fn delete_camera_moves_a_key_that_lands_on_frame_zero_into_the_head() {
    // 373-383 and CopyCameraKeyPayload 152-160.
    let mut p = camera3();
    camera_mode(&mut p, true);
    let k1 = CameraKey {
        distance: -10.0,
        eye: [1.0, 2.0, 3.0],
        target: [4.0, 5.0, 6.0],
        parent_model: 8,
        parent_bone: 9,
        interpolation: [[1, 2, 3, 4, 5, 6]; 4],
        perspective: 0,
        fov: 55,
        selected: 1,
        ..camera_key(1, 0, 2)
    };
    p.camera = pool(10_000, 1, &[&[(1, 1), (2, 3)]], camera_key);
    p.camera.insert(1, k1);
    p.timeline.current_frame = 0;
    delete_bone_camera_frame_line(&mut p).unwrap();
    let h = &p.camera.heads()[0];
    assert_eq!(h.next, 2);
    assert_eq!(
        (h.distance, h.eye, h.target, h.fov),
        (-10.0, [1.0, 2.0, 3.0], [4.0, 5.0, 6.0], 55)
    );
    assert_eq!(h.interpolation, [[1, 2, 3, 4, 0, 0]; 4]);
    assert_eq!((h.parent_model, h.parent_bone, h.selected), (0, 0, 0));
    assert_eq!(p.camera.get(2).unwrap().previous, 0);
    assert_eq!(p.camera.get(2).unwrap().frame, 2);
    let e = p.camera.get(1).unwrap();
    assert_eq!(
        (e.frame, e.next, e.fov),
        (0, 2, 55),
        "the emptied record is left as it was"
    );
    assert_valid(&p);
}

#[test]
fn delete_morph_and_light() {
    // 438-486 (morph) and 488-526 (light).
    let mut p = swing600();
    select(&mut p, 1);
    p.timeline.current_frame = 100;
    let before = all_frames(&p.models[1].morph_keys);
    delete_morph_light_frame_line(&mut p).unwrap();
    let pool = &p.models[1].morph_keys;
    assert_eq!(all_frames(pool), deleted(&before, 100));
    let k = pool.get(6).unwrap();
    assert_eq!(
        (k.frame, k.allocated, k.value, k.previous, k.next),
        (0, 0, 0.0, 0, 0)
    );
    assert_valid(&p);

    let mut p = camera3();
    camera_mode(&mut p, true);
    p.timeline.current_frame = 300;
    delete_morph_light_frame_line(&mut p).unwrap();
    assert_eq!(frames(&p.light, 0), [449]);
    let k = p.light.get(1).unwrap();
    assert_eq!((k.frame, k.previous, k.next, k.selected), (0, 0, 0, 0));
    assert_eq!(k.color, [0.75, 0.5, 0.25], "color and direction stay");
    assert_valid(&p);
}

#[test]
fn delete_morph_and_light_key_landing_on_frame_zero_merge_into_the_head() {
    // 464-477 (morph: mark and value) and 511-520 (light: direction, color).
    let mut p = swing600();
    select(&mut p, 1);
    let mut m = morph_key(1, 2, 9);
    m.value = 0.75;
    m.allocated = 1;
    let mut morphs = pool(20_000, 4, &[&[], &[], &[(8, 1), (9, 4)]], morph_key);
    morphs.insert(8, m);
    p.models[1].morph_keys = morphs;
    p.timeline.current_frame = 0;
    delete_morph_light_frame_line(&mut p).unwrap();
    let h = &p.models[1].morph_keys.heads()[2];
    assert_eq!((h.value, h.allocated, h.next), (0.75, 1, 9));
    assert_eq!(p.models[1].morph_keys.get(9).unwrap().previous, 2);
    assert_valid(&p);

    let mut p = camera3();
    camera_mode(&mut p, true);
    p.light = pool(10_000, 1, &[&[(1, 1), (2, 5)]], light_key);
    p.light.insert(
        1,
        mds_formats::pmm::LightKey {
            color: [1.0, 2.0, 3.0],
            direction: [4.0, 5.0, 6.0],
            ..light_key(1, 0, 2)
        },
    );
    p.timeline.current_frame = 0;
    delete_morph_light_frame_line(&mut p).unwrap();
    let h = &p.light.heads()[0];
    assert_eq!(
        (h.color, h.direction, h.next),
        ([1.0, 2.0, 3.0], [4.0, 5.0, 6.0], 2)
    );
    assert_eq!(frames(&p.light, 0), [4]);
    assert_valid(&p);
}

#[test]
fn a_broken_chain_is_reported_and_leaves_the_pool_alone() {
    let mut p = swing600();
    p.timeline.current_frame = 100;
    // Record 14 links to a record past the pool.
    p.models[0].bone_keys.get_mut(14).unwrap().next = 700_000;
    let before = shape(&p.models[0].bone_keys);
    assert_eq!(delete_bone_camera_frame_line(&mut p), Err(Error::Corrupt));
    assert_eq!(shape(&p.models[0].bone_keys), before);
}

#[test]
fn global_commands_do_not_need_a_model() {
    let mut p = camera3();
    camera_mode(&mut p, true);
    p.selected_model_slot = 9;
    p.timeline.current_frame = 200;
    insert_bone_camera_frame_line(&mut p).unwrap();
    delete_morph_light_frame_line(&mut p).unwrap();
    camera_mode(&mut p, false);
    assert_eq!(insert_bone_camera_frame_line(&mut p), Err(Error::NoModel));
}

#[allow(dead_code)]
fn _types(_: KeyPool<BoneKey>) {}
