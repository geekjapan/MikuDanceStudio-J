use crate::labels;
use crate::rig::Rig;
use mds_app::actions::{self, Handler};
use mds_app::ui::{dialog, physics};
use mds_doc::{Command, GlobalTrack, SelectAll};

fn area_rows() -> Vec<String> {
    labels::inventory()
        .into_iter()
        .filter(|r| r.area == "physics")
        .map(|r| r.id)
        .collect()
}

#[test]
fn every_row_has_an_action() {
    let registered: Vec<&str> = physics::actions().iter().map(|a| a.id).collect();
    let rows = area_rows();
    assert_eq!(rows.len(), 16);
    let missing: Vec<_> = rows
        .iter()
        .filter(|r| !registered.contains(&r.as_str()))
        .collect();
    assert!(missing.is_empty(), "{missing:?}");
    assert!(physics::actions()
        .iter()
        .all(|a| matches!(a.handler, Handler::Run(_))));
}

#[test]
fn the_labels_are_the_inventory_labels() {
    labels::check("physics", physics::LABELS);
}

/// `command_view_menu.cpp:1154`: the next pump settles (`PhysicsResetPending`), which seats the
/// bodies on their bones' pose with no velocity (`PhysicsFrame`, `physics_frame.cpp`).
#[test]
fn reset_seats_the_bodies_on_the_bone_pose() {
    let mut r = Rig::open("swing600.pmm");
    let origin = |r: &Rig| {
        let m = &r.editor.physics.scene.models[0];
        let p = physics::world_poses(&r.editor);
        let at = p[&(m.slot, 7)].0;
        [at[12], at[13], at[14]]
    };
    let bind = {
        r.editor.physics.tick(0.0).unwrap();
        origin(&r)
    };
    for _ in 0..38 {
        r.editor.physics.tick(1.0 / 30.0).unwrap();
    }
    let swung = origin(&r);
    let far = |a: [f32; 3]| (0..3).map(|c| (a[c] - bind[c]).powi(2)).sum::<f32>().sqrt();
    assert!(
        far(swung) > 0.5,
        "the body did not swing: {swung:?} from {bind:?}"
    );

    r.run("menu:268").unwrap();
    r.editor.physics.tick(0.0).unwrap();
    assert!(
        far(origin(&r)) < far(swung) / 2.0,
        "{:?} after the reset, {swung:?} before, bind {bind:?}",
        origin(&r)
    );
}

#[test]
fn the_playtime_mode_switch_plays_in_physics_mode_2() {
    let mut r = Rig::open("swing600-golden.pmm");
    r.editor.doc.pmm.physics.playback_mode = 1;
    r.editor.physics.scene.physics_mode = 1;
    assert!(!r.editor.physics.always_on_off);
    r.run("menu:271").unwrap();
    assert!(r.editor.physics.always_on_off);
    // `UpdateBoneFrames` (playback_state.cpp:312): `PlaybackPhysicsMode() = 2` once play starts,
    // and `StopPlayback` puts the saved mode back (playback_state.cpp:379).
    r.run("ctl:408").unwrap();
    assert_eq!(r.editor.physics.scene.physics_mode, 2);
    r.run("ctl:408").unwrap();
    assert_eq!(r.editor.physics.scene.physics_mode, 1);
    r.run("menu:271").unwrap();
    assert!(!r.editor.physics.always_on_off);
    r.run("ctl:408").unwrap();
    assert_eq!(r.editor.physics.scene.physics_mode, 1);
}

fn selected_marks(r: &Rig) -> Vec<bool> {
    let m = r.editor.doc.selected_model().unwrap();
    m.bone_pose.iter().map(|p| p.flags[2] != 0).collect()
}

/// `command_view_menu.cpp:1180` to `:1205`: `sel[i] = 1` and `selectedBone = i` for each bone with
/// a rigid body, 0 for the others.
#[test]
fn select_physical_bones_marks_the_bones_with_bodies() {
    let mut r = Rig::open("swing600.pmm");
    r.editor.apply(Command::SelectBones(vec![1, 2])).unwrap();
    r.run("menu:273").unwrap();
    let rigid: Vec<bool> = r.editor.physics.scene.models[0]
        .bones
        .iter()
        .map(|b| b.has_rigid_body != 0)
        .collect();
    assert_eq!(rigid.iter().filter(|&&b| b).count(), 3);
    assert_eq!(selected_marks(&r), rigid);
    let last = rigid.iter().rposition(|&b| b).unwrap();
    assert_eq!(
        r.editor
            .doc
            .selected_model()
            .unwrap()
            .selection
            .selected_bone,
        last as i32
    );
}

#[test]
fn the_physics_selections_are_model_mode_only() {
    let mut r = Rig::open("swing600.pmm");
    r.editor.apply(Command::SelectCameraMode).unwrap();
    for id in ["menu:273", "menu:274", "menu:275"] {
        assert!(!r.with_enabled(id), "{id}");
        assert_eq!(r.run(id), Err(format!("{id}: model mode only")));
    }
    assert_eq!(dialog::current(&r.egui), None);
}

impl Rig {
    fn with_enabled(&mut self, id: &str) -> bool {
        actions::enabled(&self.ctx(), id)
    }
}

/// The keys of `bone` as `(frame, physicsDisabled, selected)`, head first.
fn chain(r: &Rig, bone: u32) -> Vec<(u32, u8, u8)> {
    let pool = &r.editor.doc.selected_model().unwrap().bone_keys;
    let (mut i, mut out) = (bone, Vec::new());
    loop {
        let k = pool.get(i).unwrap();
        out.push((k.frame, k.physics_disabled, k.allocated));
        if k.next as i32 <= 0 {
            return out;
        }
        i = k.next;
    }
}

/// `SelectPhysicsOnBoneKeys` (`model_keyframe_edit.cpp:730`): the marks of the model's key pools
/// are cleared, then each key of a bone with a rigid body whose `physicsDisabled` is 0 is marked.
#[test]
fn select_physics_on_frames_marks_the_on_keys_of_the_bodies() {
    let mut r = Rig::open("swing600.pmm");
    // Keys at 10 with the physics check box on, at 20 and 35 with it off (`record.physicsDisabled`
    // is the negated box, model_keyframe_edit.cpp:277), then at 40 with it on again.
    for (frame, on) in [(10, true), (20, false), (35, false), (40, true)] {
        if r.editor.doc.edit.physics_checkbox != on {
            r.run("ctl:499").unwrap();
        }
        r.editor.apply(Command::SetFrame(frame)).unwrap();
        r.run("menu:273").unwrap();
        r.editor.apply(Command::RegisterBoneKeys).unwrap();
    }
    let keys = chain(&r, 7);
    for (frame, off) in [(10, 0), (20, 1), (30, 1), (35, 1), (40, 0)] {
        let ok = keys.iter().any(|k| k.0 == frame && k.1 == off);
        assert!(ok || frame == 30 || frame == 35, "frame {frame}: {keys:?}");
    }
    r.editor.apply(Command::SelectAll(SelectAll::Bone)).unwrap();
    assert!(chain(&r, 7).iter().all(|k| k.2 == 1));
    assert!(chain(&r, 1).iter().all(|k| k.2 == 1));

    r.run("menu:274").unwrap();

    for bone in 5..=7 {
        for (frame, off, selected) in chain(&r, bone) {
            assert_eq!(selected, 1 - off, "bone {bone} frame {frame}");
        }
    }
    for bone in [0, 1, 2, 3, 4, 8] {
        assert!(
            chain(&r, bone).iter().all(|k| k.2 == 0),
            "bone {bone} has no body"
        );
    }
}

#[test]
fn the_dialog_rows_open_their_dialogs() {
    let mut r = Rig::open("swing600.pmm");
    r.run("menu:266").unwrap();
    assert_eq!(dialog::current(&r.egui), Some("IDD_GRAVITY"));
    r.run("menu:275").unwrap();
    assert_eq!(
        dialog::current(&r.egui),
        Some("IDD_PHYSICS_FRAME_CONVERSION")
    );
    // Camera mode: 266 opens (the C++ handler has no gate), 275 is greyed out.
    let mut r = Rig::open("swing600.pmm");
    r.editor.apply(Command::SelectCameraMode).unwrap();
    r.run("menu:266").unwrap();
    assert_eq!(dialog::current(&r.egui), Some("IDD_GRAVITY"));
}

#[test]
fn about_opens_its_window_with_the_text_of_the_message_box() {
    let mut r = Rig::new();
    r.run("menu:267").unwrap();
    let id = egui::Id::unique("physics-about");
    assert_eq!(r.egui.data(|d| d.get_temp::<bool>(id)), Some(true));
    // command_view_menu.cpp:1137.
    assert_eq!(
        physics::ABOUT,
        "Bullet Physics Library Ver.2.75\n\nhttp://www.bulletphysics.com/"
    );
}

/// Check box 530 (`command_frame_register.cpp:556`, read by `RegisterBoneKeys` at
/// `model_keyframe_edit.cpp:245`) and `]` (`pump_edit_keys.cpp:222`), which flips the box.
#[test]
fn the_bracket_key_and_the_check_box_flip_automatic_interpolation() {
    let mut r = Rig::new();
    assert!(r.editor.doc.edit.auto_interpolation);
    r.run("ctl:530").unwrap();
    assert!(!r.editor.doc.edit.auto_interpolation);
    r.run("key:]").unwrap();
    assert!(r.editor.doc.edit.auto_interpolation);
    // The key is the `!playing` gate of `PumpInterpolationToggle`; the box is not gated.
    let mut r = Rig::open("swing600-golden.pmm");
    r.run("ctl:408").unwrap();
    assert_eq!(r.run("key:]"), Err("key:]: not while playing".into()));
    r.run("ctl:530").unwrap();
    assert!(!r.editor.doc.edit.auto_interpolation);
}

#[test]
fn the_bracket_press_reaches_the_action() {
    let mut r = Rig::new();
    let press = egui::Event::Key {
        key: egui::Key::CloseBracket,
        physical_key: None,
        pressed: true,
        repeat: false,
        modifiers: egui::Modifiers::NONE,
    };
    r.frame(vec![press], mds_app::ui::keys);
    assert!(!r.editor.doc.edit.auto_interpolation);
}

/// `RegisterCameraState`: an existing key's curve is kept unless the box is on
/// (`mds-doc/tests/commands.rs`, `camera_register_on_a_key_keeps_its_curve_unless_reset`).
#[test]
fn the_check_box_decides_whether_a_registered_camera_key_keeps_its_curve() {
    let mut r = Rig::new();
    r.editor.apply(Command::SelectCameraMode).unwrap();
    r.editor.doc.pmm.camera.heads_mut()[0].interpolation[0][0] = 77;
    let register = |r: &mut Rig| {
        r.editor
            .apply(Command::RegisterGlobalKeys(vec![GlobalTrack::Camera]))
            .unwrap();
        r.editor.doc.pmm.camera.heads()[0].interpolation[0][0]
    };
    r.run("ctl:530").unwrap();
    assert_eq!(register(&mut r), 77);
    r.run("key:]").unwrap();
    assert_eq!(register(&mut r), 20);
}

#[test]
fn display_bodies_flips_and_a_new_scene_clears_it() {
    let mut r = Rig::open("swing600.pmm");
    assert!(!physics::bodies_shown(&r.egui, &r.editor));
    r.run("menu:264").unwrap();
    assert!(physics::bodies_shown(&r.egui, &r.editor));
    r.run("menu:264").unwrap();
    assert!(!physics::bodies_shown(&r.egui, &r.editor));
    r.run("menu:264").unwrap();
    // `rigidBodyDisplayEnabled = 0` in the scene load (pmm_load_v2.cpp:2164, reset_app_state.cpp:83).
    r.editor.apply(Command::NewScene).unwrap();
    assert!(!physics::bodies_shown(&r.egui, &r.editor));
}
