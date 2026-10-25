//! The panel, view and timeline commands (`mds_doc::panel`). Each expected
//! value is read off the C++ named in the test's comment.

use mds_doc::history::Entry;
use mds_doc::{Command, Document, GlobalTrack, ModelFlag, Track, ViewOption};
use mds_math::{Mat4, Quat};
use std::path::PathBuf;

fn dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

/// swing600.pmm: slot 0 is chain8_ik.pmx (9 bones, bone keys), slot 1
/// morph4.pmx.
fn doc() -> Document {
    let data = std::fs::read(dir().join("swing600.pmm")).unwrap();
    Document::load(&data, |p| std::fs::read(dir().join(p)).ok()).unwrap()
}

fn run(d: &mut Document, cmds: impl IntoIterator<Item = Command>) {
    for c in cmds {
        let what = format!("{c:?}");
        d.apply(c).unwrap_or_else(|e| panic!("{what}: {e}"));
    }
}

/// The document after a save and a load: what the PMM keeps.
fn reloaded(d: &Document) -> Document {
    Document::load(&d.save().unwrap(), |p| std::fs::read(dir().join(p)).ok()).unwrap()
}

#[test]
fn a_frame_strip_click_keeps_the_selection_and_clears_the_edited_marks() {
    // HandleLButtonDown_FrameStripHit (ui_editor_click.cpp 791-830): the
    // snapshot is taken at the frame left, then bonePhysicsState is cleared;
    // boneSelection is not touched. The frame edit (RefreshAfterFrameApply,
    // ui_frame_step.cpp 35-54) clears boneSelection instead.
    let mut d = doc();
    run(
        &mut d,
        [
            Command::SetFrame(30),
            Command::SelectBones(vec![2]),
            Command::SetBonePose {
                bone: 2,
                translation: [0.0; 3],
                rotation: [0.0, 0.0, 0.0, 1.0],
            },
            Command::ClickFrame(40),
        ],
    );
    let m = &d.pmm.models[0];
    assert_eq!(d.pmm.timeline.current_frame, 40);
    assert_eq!(m.bone_pose[2].flags[2], 1, "still selected");
    assert!(m.bone_pose.iter().all(|p| p.flags[1] == 0));
    let h = &d.edit.models[0].history;
    assert!(matches!(
        h.undo[h.cursor],
        Entry::BonePoseWithFrame { frame: 30, .. }
    ));
    run(&mut d, [Command::SetFrame(50)]);
    assert_eq!(
        d.pmm.models[0].bone_pose[2].flags[2], 0,
        "the edit clears it"
    );
}

#[test]
fn panel_switches_write_the_fields_the_pmm_saves() {
    // 490-493 edit mode; 439-441 (command_frame_edit.cpp 1566-1592) the model
    // flags; 444/445 (1598-1617) ik_pose; OptionFlagRefresh the panel flags;
    // 411/413/414 the play options; 211, 215, 221, 254, 279 and 234-236 the
    // view; 253 edge_scale; 286 outline colour; 212 the render size.
    let mut d = doc();
    run(
        &mut d,
        [
            Command::SetEditMode(3),
            Command::SetModelFlag {
                flag: ModelFlag::Visible,
                on: false,
            },
            Command::SetModelFlag {
                flag: ModelFlag::Shadow,
                on: true,
            },
            Command::SetModelFlag {
                flag: ModelFlag::AddBlend,
                on: true,
            },
            Command::SetIkEnabled {
                chain: 0,
                on: false,
            },
            Command::SetPanelExpanded {
                panel: 4,
                expanded: false,
            },
            Command::SetPlayback {
                looped: true,
                return_to_start: true,
                from_current: true,
                start_frame: 12,
                stop_frame: 345,
            },
            Command::SetViewOption {
                option: ViewOption::Information,
                on: true,
            },
            Command::SetViewOption {
                option: ViewOption::CoordinateAxis,
                on: false,
            },
            Command::SetViewOption {
                option: ViewOption::GroundShadow,
                on: false,
            },
            Command::SetViewOption {
                option: ViewOption::GroundShadowTransparency,
                on: true,
            },
            Command::SetViewOption {
                option: ViewOption::SelfShadow,
                on: false,
            },
            Command::SetFpsLimit(60.0),
            Command::SetEdgeScale(1.5),
            Command::SetOutlineColor([10, 20, 30]),
            Command::SetRenderSize {
                width: 640,
                height: 360,
            },
        ],
    );
    let r = reloaded(&d);
    let p = &r.pmm;
    let m = &p.models[0];
    assert_eq!(p.timeline.edit_mode, 3);
    assert_eq!((m.selection.load_complete, m.toon, m.post_load), (0, 1, 1));
    assert_eq!(m.ik_pose[0], 0);
    assert_eq!(p.settings.options[4], 0);
    let t = &p.timeline;
    assert_eq!(
        (t.playback_loop, t.return_to_start, t.start_at_current),
        (1, 1, 1)
    );
    assert_eq!((t.play_start_frame, t.play_stop_frame), (12, 345));
    let v = &p.view;
    assert_eq!((v.fps_overlay, v.ground_grid, v.ground_shadow), (1, 0, 0));
    assert_eq!(p.physics.projected_shadow_blend, 1);
    assert_eq!(p.self_shadow_mode, 0);
    assert_eq!(v.fps_limit, 60.0);
    assert_eq!(m.edge_scale, 1.5);
    assert_eq!(p.appearance.outline_color, [10, 20, 30]);
    assert_eq!(
        (p.settings.render_width, p.settings.render_height),
        (640, 360)
    );

    // ScreenSizeDlgProc keeps the dialog open above the device limit.
    d.edit.max_texture_size = Some([4096, 4096]);
    assert!(d
        .apply(Command::SetRenderSize {
            width: 4097,
            height: 10
        })
        .is_err());
    assert_eq!(d.pmm.settings.render_width, 640);
    assert!(d
        .apply(Command::SetPanelExpanded {
            panel: 0,
            expanded: true
        })
        .is_err());
}

#[test]
fn scroll_and_display_group_fold() {
    // ui_hscroll.cpp 274-313 start_frame; HandleVScroll bone_list_pos (model
    // mode) and the display list scroll (camera mode); the margin column
    // toggles DisplayGroups[type].flags (ui_editor_click.cpp 439-453), never
    // group 0.
    let mut d = doc();
    let before = d.pmm.models[0].selection.group_flags[1];
    run(
        &mut d,
        [
            Command::SetTimelineStart(77),
            Command::SetTrackListScroll(3),
            Command::ToggleDisplayGroup(1),
        ],
    );
    assert_eq!(d.pmm.timeline.start_frame, 77);
    assert_eq!(d.pmm.models[0].selection.bone_list_pos, 3);
    assert_eq!(
        d.pmm.models[0].selection.group_flags[1],
        u8::from(before == 0)
    );
    assert!(d.apply(Command::ToggleDisplayGroup(0)).is_err());
    run(
        &mut d,
        [Command::SelectCameraMode, Command::SetTrackListScroll(5)],
    );
    assert_eq!(d.pmm.display_list_scroll, 5);
}

#[test]
fn select_all_and_unregistered_bones() {
    // 494 (command_panel_toggles.cpp 658-690): types 0..6 and fixed axis,
    // added to the selection, edit mode bone. 501
    // (command_frame_register.cpp 399-420): selection = edited, selectedBone
    // -1.
    let mut d = doc();
    run(&mut d, [Command::SetEditMode(2), Command::SelectAllBones]);
    assert!(d.pmm.models[0].bone_pose.iter().all(|p| p.flags[2] == 1));
    assert_eq!(d.pmm.timeline.edit_mode, 0);
    run(
        &mut d,
        [
            Command::SelectBones(vec![4]),
            Command::SetBonePose {
                bone: 4,
                translation: [0.0; 3],
                rotation: [0.0, 0.0, 0.0, 1.0],
            },
            Command::SelectAllBones,
            Command::SelectUnregisteredBones,
        ],
    );
    let m = &d.pmm.models[0];
    let selected: Vec<usize> = (0..m.bone_pose.len())
        .filter(|&i| m.bone_pose[i].flags[2] != 0)
        .collect();
    assert_eq!(selected, [4]);
    assert_eq!(m.selection.selected_bone, -1);
}

#[test]
fn reset_bone_pose_follows_the_three_cases() {
    // bone_pose_edit.cpp 25-143: bone 0 loses Y and its rotation; a bone
    // with a parent becomes the identity; a root bone takes bone 0's
    // rotation and p·R(own rotation) - p + bone 0's translation (x64 float).
    let mut d = doc();
    let q = [0.0, 0.247_403_96, 0.0, 0.968_912_4]; // 0.5 rad about Y
    for (bone, t) in [
        (0, [1.0, 2.0, 3.0]),
        (3, [0.5, 0.0, 0.0]),
        (8, [0.0, 1.0, 0.0]),
    ] {
        run(
            &mut d,
            [Command::SetBonePose {
                bone,
                translation: t,
                rotation: q,
            }],
        );
    }
    // chain8_ik parents bone 8 to bone 0; detach it in the file so it takes
    // the root-bone case.
    let p8 = {
        let mds_doc::ModelFile::Pmx(pmx) = &mut d.models[0] else {
            panic!()
        };
        pmx.bones[8].parent = -1;
        pmx.bones[8].position
    };
    run(
        &mut d,
        [Command::SelectBones(vec![0, 3, 8]), Command::ResetBonePose],
    );
    let b = &d.pmm.models[0].bone_pose;
    assert_eq!(b[0].translation, [1.0, 0.0, 3.0]);
    assert_eq!(b[0].rotation, [0.0, 0.0, 0.0, 1.0]);
    assert_eq!(
        (b[3].translation, b[3].rotation),
        ([0.0; 3], [0.0, 0.0, 0.0, 1.0])
    );
    let t = Mat4::rotation_quaternion(Quat(q)).0;
    let root = [1.0, 0.0, 3.0];
    let want: [f32; 3] = std::array::from_fn(|c| {
        p8[0] * t[c] + p8[1] * t[4 + c] + p8[2] * t[8 + c] + t[12 + c] - p8[c] + root[c]
    });
    assert_eq!(b[8].translation, want);
    assert_eq!(b[8].rotation, [0.0, 0.0, 0.0, 1.0]);
    assert_eq!(b[8].flags[1], 1);
    let h = &d.edit.models[0].history;
    let Entry::BonePose(s) = &h.undo[h.cursor] else {
        panic!("PushBoneEditUndo")
    };
    assert_eq!(s.iter().map(|s| s.bone).collect::<Vec<_>>(), [0, 3, 8]);
}

#[test]
fn copy_and_paste_bone_pose() {
    // bone_pose_clipboard.cpp 34-292: copy the selected saved poses; paste
    // clears the selection, writes each pose onto its bone (mirror: x of the
    // translation, y and z of the rotation negated; a name without 左/右
    // mirrors onto itself), selects it and marks it edited.
    let mut d = doc();
    let q = [0.1, 0.2, 0.3, 0.927_361_8];
    run(
        &mut d,
        [
            Command::SetBonePose {
                bone: 2,
                translation: [1.0, 2.0, 3.0],
                rotation: q,
            },
            Command::SelectBones(vec![2]),
            Command::CopyBonePose,
            Command::SetBonePose {
                bone: 2,
                translation: [0.0; 3],
                rotation: [0.0, 0.0, 0.0, 1.0],
            },
            Command::SelectBones(vec![5]),
            Command::PasteBonePose { mirror: false },
        ],
    );
    let m = &d.pmm.models[0];
    assert_eq!(
        (m.bone_pose[2].translation, m.bone_pose[2].rotation),
        ([1.0, 2.0, 3.0], q)
    );
    assert_eq!((m.bone_pose[2].flags[2], m.bone_pose[5].flags[2]), (1, 0));
    assert_eq!(m.selection.selected_bone, 2);
    run(&mut d, [Command::PasteBonePose { mirror: true }]);
    let p = &d.pmm.models[0].bone_pose[2];
    assert_eq!(p.translation, [-1.0, 2.0, 3.0]);
    assert_eq!(p.rotation, [0.1, -0.2, -0.3, 0.927_361_8]);
    assert!(d.edit.physics_reset_pending);
}

#[test]
fn camera_parent_attach_and_detach() {
    // command_dispatch.cpp 203-271: attaching with no parent before clears
    // the camera position and rotation, the bone becomes 0; detaching sets
    // distance -20 and no rotation, and the parent -1.
    let mut d = doc();
    run(
        &mut d,
        [
            Command::SelectCameraMode,
            Command::SetCamera {
                position: [1.0, 2.0, 3.0],
                rotation: [0.1, 0.2, 0.3],
                distance: -45.0,
                fov: 30.0,
                perspective: true,
            },
            Command::SetCameraParentModel(Some(0)),
        ],
    );
    let p = &d.pmm;
    assert_eq!(
        (
            p.appearance.camera_parent_model,
            p.appearance.camera_parent_bone
        ),
        (0, 0)
    );
    assert_eq!(p.camera_state[..3], [0.0; 3]);
    assert_eq!(p.camera_state[6..], [0.0; 3]);
    assert_eq!(p.camera_state[5], -45.0);
    run(&mut d, [Command::SetCameraParentBone(3)]);
    assert_eq!(d.pmm.appearance.camera_parent_bone, 3);
    run(&mut d, [Command::SetCameraParentModel(None)]);
    let p = &d.pmm;
    assert_eq!(p.appearance.camera_parent_model, -1);
    assert_eq!(p.camera_state[5], -20.0);
    assert_eq!(p.camera_state[6..], [0.0; 3]);
}

#[test]
fn follow_camera_zeroes_the_view_offset() {
    // command_file_menu.cpp 1771-1795.
    let mut d = doc();
    d.pmm.camera_state[3] = 5.0;
    d.pmm.camera_state[4] = 6.0;
    d.pmm.appearance.suppress_camera_transform = 1;
    run(&mut d, [Command::SetFollowCamera(true)]);
    let p = &d.pmm;
    assert_eq!(p.appearance.follow_camera, 1);
    assert_eq!(p.camera_state[3..5], [0.0, 0.0]);
    assert_eq!(p.appearance.suppress_camera_transform, 0);
    run(&mut d, [Command::SetFollowCamera(false)]);
    assert_eq!(d.pmm.appearance.follow_camera, 0);
}

#[test]
fn interpolation_curve_copy_paste_reset_and_drag() {
    // command_frame_edit.cpp 987-1124 and ui_selection_reeval.cpp 115-232:
    // a bone channel is the bytes [ch], [4+ch], [8+ch], [12+ch]; copy takes
    // the first marked key, paste and reset every marked key, reset writes
    // 20, 20, 107, 107; the drag clamps to 0..127.
    let mut d = doc();
    let m = &mut d.pmm.models[0];
    let first = m.bone_keys.heads()[1].next;
    let k = m.bone_keys.get_mut(first).unwrap();
    k.interpolation[1] = 1;
    k.interpolation[5] = 2;
    k.interpolation[9] = 3;
    k.interpolation[13] = 4;
    let frame = k.frame;
    run(
        &mut d,
        [
            Command::ClearKeySelection,
            Command::SelectKeys {
                track: Track::Bone(1),
                from: frame,
                to: frame,
            },
            Command::CopyInterpolationCurve { channel: 1 },
            Command::ReplaceKeySelection {
                track: Track::Bone(2),
                from: 0,
                to: 10_000,
            },
            Command::PasteInterpolationCurve { channel: 1 },
        ],
    );
    let m = &d.pmm.models[0];
    let pool = &m.bone_keys;
    assert_eq!(pool.get(first).unwrap().allocated, 0, "replaced");
    let mut i = pool.heads()[2].next;
    let mut n = 0;
    while i != 0 {
        let c = pool.get(i).unwrap().interpolation;
        assert_eq!([c[1], c[5], c[9], c[13]], [1, 2, 3, 4]);
        i = pool.get(i).unwrap().next;
        n += 1;
    }
    assert!(n > 0);
    run(
        &mut d,
        [
            Command::ResetInterpolationCurves { channel: 4 },
            Command::SetKeyInterpolation {
                channel: 0,
                end: true,
                point: [200, -5],
            },
        ],
    );
    let c = d.pmm.models[0]
        .bone_keys
        .get(d.pmm.models[0].bone_keys.heads()[2].next)
        .unwrap()
        .interpolation;
    assert_eq!(
        c,
        [20, 20, 20, 20, 20, 20, 20, 20, 127, 107, 107, 107, 0, 107, 107, 107]
    );

    // Camera mode: interpolation[row][channel], every marked camera key.
    run(
        &mut d,
        [
            Command::SelectCameraMode,
            Command::ReplaceKeySelection {
                track: Track::Global(GlobalTrack::Camera),
                from: 0,
                to: 0,
            },
            Command::SetKeyInterpolation {
                channel: 2,
                end: false,
                point: [5, 6],
            },
        ],
    );
    let k = d.pmm.camera.get(0).unwrap();
    assert_eq!((k.interpolation[0][2], k.interpolation[1][2]), (5, 6));
}
