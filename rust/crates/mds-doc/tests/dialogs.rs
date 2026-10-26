//! The outside-parent, order, physics model and background commands, the
//! bone drag, the view offset, and the document-dependent `marks_modified`.
//! Each expected value is read off the C++ named in the test's comment.

use mds_doc::{Command, Document, OutsideParent, PhysicsField, SelectAll, ViewOption};
use mds_formats::pmm::Pmm;
use mds_media::background::Viewport;
use mds_pose::model::Model as PoseModel;
use std::path::PathBuf;

fn dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

fn read(name: &str) -> Vec<u8> {
    std::fs::read(dir().join(name)).unwrap()
}

/// swing600.pmm: slot 0 is chain8_ik.pmx (9 bones; selectors -1, 0, 1, 8;
/// bone 1 a move bone under bone 0), slot 1 morph4.pmx.
fn load(name: &str) -> Document {
    Document::load(&read(name), |p| std::fs::read(dir().join(p)).ok()).unwrap()
}

fn run(d: &mut Document, cmds: impl IntoIterator<Item = Command>) {
    for c in cmds {
        let what = format!("{c:?}");
        d.apply(c).unwrap_or_else(|e| panic!("{what}: {e}"));
    }
}

fn reload(d: &Document) -> Pmm {
    Pmm::read(&d.save().unwrap()).unwrap()
}

/// The rest point of `bone` of model `i` through its `matInit` in the saved
/// pose without physics, and the rotation rows of that matrix.
fn world(d: &Document, i: usize, bone: usize) -> ([f32; 3], [f32; 9]) {
    let mds_doc::ModelFile::Pmx(p) = &d.models[i] else {
        panic!("a PMX")
    };
    let m = &d.pmm.models[i];
    let mut pose = PoseModel::from_pmx(m.slot, p).unwrap();
    pose.apply_pmm(m).unwrap();
    mds_pose::pose::apply_morphs(&mut pose);
    let mode = i32::from(d.pmm.physics.playback_mode);
    mds_pose::pose::set_physics_mode(&mut pose, 0, &mds_pose::pose::Others::NONE, mode);
    let b = &pose.bones[bone];
    let (t, p) = (&b.mat_init.0, b.position);
    let point =
        std::array::from_fn(|c| p[0] * t[c] + p[1] * t[4 + c] + p[2] * t[8 + c] + t[12 + c]);
    let rot = std::array::from_fn(|k| t[(k / 3) * 4 + k % 3]);
    (point, rot)
}

fn close(a: &[f32], b: &[f32]) -> bool {
    a.iter().zip(b).all(|(x, y)| (x - y).abs() < 1e-4)
}

/// A pose on bones 0 and 1 of slot 0, so that bone 1's world matrix has a
/// rotation and a translation.
fn posed_chain() -> Document {
    let mut d = load("swing600.pmm");
    let half = std::f32::consts::FRAC_1_SQRT_2;
    run(
        &mut d,
        [
            Command::SelectModel(0),
            Command::SetFrame(10),
            Command::DragBonePose {
                bone: 0,
                translation: [1.0, 0.5, -2.0],
                rotation: [0.0, 0.0, half, half],
            },
            Command::DragBonePose {
                bone: 1,
                translation: [0.0, 0.25, 0.0],
                rotation: [half, 0.0, 0.0, half],
            },
        ],
    );
    d
}

#[test]
fn the_outside_parent_bake_keeps_the_bone_where_it_is() {
    // ApplyBoneAttach (dialog_select_ops.cpp 382-460): X for the parent,
    // trans = p·X - p, rotQuat of X without its translation; then the bone
    // alone selected (437-441) and RegisterSelectedBoneKeys (443). With the
    // dialog's record written by 632 (ResetModelSelection, 334-376), the
    // bone's world matrix is the one it had.
    for (selector, parent) in [
        (2, OutsideParent::Ground),
        (2, OutsideParent::None),
        (2, OutsideParent::Bone { model: 0, bone: 0 }),
    ] {
        let mut d = posed_chain();
        let before = world(&d, 0, 1);
        let old = d.pmm.models[0].bone_pose[1].clone();
        run(&mut d, [Command::ApplyOutsideParent { selector, parent }]);
        let m = &d.pmm.models[0];
        let sel: Vec<u8> = m.bone_pose.iter().map(|p| p.flags[2]).collect();
        assert_eq!(sel, [0, 1, 0, 0, 0, 0, 0, 0, 0], "{parent:?}");
        // The register: a key at frame 10 on bone 1 with the baked pose.
        let p = &m.bone_pose[1];
        let key = m
            .bone_keys
            .records()
            .iter()
            .find(|(_, k)| k.frame == 10)
            .map(|(_, k)| k)
            .unwrap_or_else(|| panic!("no key at frame 10 ({parent:?})"));
        assert_eq!((key.position, key.rotation), (p.translation, p.rotation));
        assert!(d.pmm.timeline.last_registered_frame >= 10);
        if parent != OutsideParent::None {
            assert_ne!(p.rotation, old.rotation, "{parent:?}");
        }
        let mut records = vec![OutsideParent::None; 4];
        records[selector as usize] = parent;
        run(&mut d, [Command::RegisterOutsideParents(records)]);
        let after = world(&d, 0, 1);
        assert!(
            close(&before.0, &after.0),
            "{parent:?}: {before:?} {after:?}"
        );
        assert!(
            close(&before.1, &after.1),
            "{parent:?}: {before:?} {after:?}"
        );
    }
}

#[test]
fn the_outside_parent_records_become_a_display_key_and_the_close_seeks() {
    // ResetModelSelection: SceneModified, every mark cleared, the records
    // into the model, RegisterDisplayKeyCurrent at the current frame. The
    // close (command_frame_edit.cpp 1344-1378) seeks only after 630 or 632
    // (AccessoryApplyGate), and its cancel returns IDOK (dialog_procs.cpp
    // 116), so it always marks the scene modified.
    let mut d = posed_chain();
    run(&mut d, [Command::SelectAll(SelectAll::Bone)]);
    let records = vec![
        OutsideParent::None,
        OutsideParent::Ground,
        OutsideParent::Bone { model: 1, bone: 1 },
        OutsideParent::None,
    ];
    run(&mut d, [Command::RegisterOutsideParents(records)]);
    let m = &d.pmm.models[0];
    let links: Vec<[i32; 2]> = m.selector_pose.iter().map(|s| [s[2], s[3]]).collect();
    assert_eq!(links, [[-1, 0], [-2, 0], [1, 1], [-1, 0]]);
    let key = m
        .display_keys
        .records()
        .iter()
        .find(|(_, k)| k.frame == 10)
        .map(|(_, k)| k)
        .expect("a display key at frame 10");
    assert_eq!(key.selectors, [[-1, 0], [-2, 0], [1, 1], [-1, 0]]);
    assert!(m.bone_keys.records().iter().all(|(_, k)| k.allocated == 0));
    assert!(m.bone_keys.heads().iter().all(|k| k.allocated == 0));
    assert!(d.edit.outside_parent_applied);
    // The pose of frame 10 is the keys', not the drag's.
    run(&mut d, [Command::CloseOutsideParentDialog]);
    assert!(!d.edit.outside_parent_applied);
    assert_ne!(d.pmm.models[0].bone_pose[1].translation, [0.0, 0.25, 0.0]);
    // A second close with nothing applied leaves an edit alone.
    run(
        &mut d,
        [
            Command::DragBonePose {
                bone: 1,
                translation: [0.0, 0.25, 0.0],
                rotation: [0.0, 0.0, 0.0, 1.0],
            },
            Command::CloseOutsideParentDialog,
        ],
    );
    assert_eq!(d.pmm.models[0].bone_pose[1].translation, [0.0, 0.25, 0.0]);
    assert!(Command::CloseOutsideParentDialog.marks_modified());
    assert!(Command::RegisterOutsideParents(Vec::new()).marks_modified());

    assert!(d
        .apply(Command::RegisterOutsideParents(vec![OutsideParent::None]))
        .is_err());
    // Selector 0 is the root dummy (bone -1).
    let ground = OutsideParent::Ground;
    assert!(d
        .apply(Command::ApplyOutsideParent {
            selector: 0,
            parent: ground
        })
        .is_err());
    run(&mut d, [Command::SelectCameraMode]);
    assert!(d
        .apply(Command::ApplyOutsideParent {
            selector: 2,
            parent: ground
        })
        .is_err());
}

#[test]
fn the_order_dialogs_write_the_order_bytes() {
    // ApplyModelDisplayOrderDialog (model_order_dialog.cpp 85-93): row i
    // gets comboSelIndex i + 1, then CB_SETCURSEL 0 and
    // ApplyModelComboSelection: camera mode, edit mode none
    // (ui_model_reload.cpp 403-446). ApplyModelCalculateOrderDialog (54-61):
    // row i gets comboSelIndex2 i. pmm_save.cpp 464 and 611 save both.
    let mut d = load("swing600.pmm");
    run(
        &mut d,
        [
            Command::SelectModel(0),
            Command::SetModelDrawOrder(vec![2, 0, 3, 1]),
        ],
    );
    assert_eq!(d.pmm.settings.options[0], 1);
    assert_eq!(d.pmm.timeline.edit_mode, 2);
    run(&mut d, [Command::SetModelCalcOrder(vec![3, 1, 0, 2])]);
    let p = reload(&d);
    let combo: Vec<u8> = p.models.iter().map(|m| m.selection.combo_index).collect();
    let calc: Vec<u8> = p.models.iter().map(|m| m.display_order).collect();
    assert_eq!(combo, [2, 4, 1, 3]);
    assert_eq!(calc, [2, 1, 3, 0]);
    for bad in [vec![0, 1, 2], vec![0, 1, 2, 2], vec![0, 1, 2, 3, 4]] {
        assert!(d.apply(Command::SetModelDrawOrder(bad.clone())).is_err());
        assert!(d.apply(Command::SetModelCalcOrder(bad)).is_err());
    }
    assert!(!Command::SetModelDrawOrder(Vec::new()).marks_modified());
}

#[test]
fn the_accessory_order_dialog_reorders_renames_and_selects() {
    // ApplyAccessoryOrderIndices (dialog_order_arrays.hpp 35-47): row i gets
    // order i and its list text as name; the selected accessory is row 0.
    // The combo is rebuilt from the rows (command_file_menu.cpp 798-805),
    // which the PMM saves by position (pmm_save.cpp 678-690). Rename (633)
    // replaces a row; an empty edit is ignored (888-895). The split count
    // is clamped to 0..=count (858-874).
    let mut d = Document::startup();
    for name in ["a", "b", "c"] {
        run(
            &mut d,
            [Command::LoadAccessory {
                path: format!("C:\\acc\\{name}.x"),
                data: read("accessory/cube.x"),
            }],
        );
    }
    run(
        &mut d,
        [
            Command::RenameAccessory {
                slot: 0,
                name: "first".into(),
            },
            Command::RenameAccessory {
                slot: 1,
                name: String::new(),
            },
            Command::SetAccessoryOrder(vec![2, 0, 1]),
            Command::SetAccessoryRenderSplit(7),
        ],
    );
    assert_eq!(d.pmm.selected_accessory_slot, 2);
    assert_eq!(d.pmm.physics.accessory_render_order, 3);
    let p = reload(&d);
    let rows: Vec<&str> = p
        .accessories
        .iter()
        .map(|a| a.list_name.text.as_str())
        .collect();
    assert_eq!(rows, ["c.x", "first", "b.x"]);
    let by_slot: Vec<(u8, u8, &str)> = p
        .accessories
        .iter()
        .map(|a| (a.slot, a.order, a.name.text.as_str()))
        .collect();
    assert_eq!(by_slot, [(0, 1, "first"), (1, 2, "b.x"), (2, 0, "c.x")]);
    // A reloaded document keeps the rows with their accessories.
    let d2 = Document::load(&d.save().unwrap(), |_| None).unwrap();
    let rows: Vec<(u8, &str)> = d2
        .pmm
        .accessories
        .iter()
        .map(|a| (a.slot, a.list_name.text.as_str()))
        .collect();
    assert_eq!(rows, [(2, "c.x"), (0, "first"), (1, "b.x")]);
    assert_eq!(d2.save().unwrap(), d.save().unwrap());
    run(&mut d, [Command::SetAccessoryRenderSplit(-4)]);
    assert_eq!(d.pmm.physics.accessory_render_order, 0);
    assert!(d.apply(Command::SetAccessoryOrder(vec![0, 1])).is_err());
}

#[test]
fn a_bone_drag_pushes_one_undo_entry() {
    // PushBoneEditUndo at the drag start (frame_modes.cpp 351, 353), none
    // per move; one undo puts the pose back as it was before the drag.
    let mut d = load("swing600.pmm");
    run(
        &mut d,
        [Command::SelectModel(0), Command::SelectBones(vec![1, 2])],
    );
    let start = d.pmm.models[0].bone_pose[1].clone();
    let cursor = d.edit.models[0].history.cursor;
    run(&mut d, [Command::BeginBoneEdit]);
    let pushed = d.edit.models[0].history.cursor;
    assert_ne!(pushed, cursor);
    for k in 1..=3 {
        run(
            &mut d,
            [Command::DragBonePose {
                bone: 1,
                translation: [0.0, k as f32, 0.0],
                rotation: [0.0, 0.0, 0.0, 1.0],
            }],
        );
    }
    assert_eq!(d.edit.models[0].history.cursor, pushed);
    let p = &d.pmm.models[0].bone_pose[1];
    assert_eq!((p.translation, p.flags[1]), ([0.0, 3.0, 0.0], 1));
    run(&mut d, [Command::Undo]);
    let p = &d.pmm.models[0].bone_pose[1];
    assert_eq!(
        (p.translation, p.rotation),
        (start.translation, start.rotation)
    );
    assert!(!Command::BeginBoneEdit.marks_modified());
}

#[test]
fn the_view_offset_is_saved() {
    // ConsumeRightButtonDrag (pump_navigation.cpp 330-334) writes
    // viewOffsetX/Y; pmm_save.cpp 638-639 saves them after the position.
    let mut d = load("swing600.pmm");
    run(&mut d, [Command::SetViewOffset([1.5, -2.25])]);
    assert_eq!(reload(&d).camera_state[3..5], [1.5, -2.25]);
    assert!(!Command::SetViewOffset([0.0; 2]).marks_modified());
}

#[test]
fn a_physics_record_drag_steps_the_scratch_records() {
    // EditModeRecord (frame_modes_bone.cpp 158-224): rotation
    // v - dy * 0.01 (173), position and size v - dy * (double)0.05f (195,
    // 203, 215) as floats, the size floored at 0.1f (216); the joint page
    // has rotation and position only.
    let mut d = Document::startup();
    run(
        &mut d,
        [Command::LoadModel {
            path: "chain8.pmd".into(),
            data: read("chain8.pmd"),
        }],
    );
    let mds_doc::ModelFile::Pmd(pmd) = &d.models[0] else {
        panic!("a PMD")
    };
    let phys = pmd.extension.as_ref().unwrap().physics.as_ref().unwrap();
    let (rigids, joints) = (phys.rigids.clone(), phys.joints.clone().unwrap());
    assert!(!rigids.is_empty() && !joints.is_empty());
    let edit = |joint, field, axis, dy| Command::EditPhysicsRecord {
        joint,
        index: 0,
        field,
        axis,
        dy,
    };
    assert!(d.apply(edit(false, PhysicsField::Rotation, 0, 1)).is_err());
    d.edit.physics_scratch = Some((rigids.clone(), joints.clone()));
    run(
        &mut d,
        [
            edit(false, PhysicsField::Rotation, 1, 3),
            edit(false, PhysicsField::Position, 2, -2),
            edit(false, PhysicsField::Size, 0, 1_000_000),
            edit(false, PhysicsField::Size, 1, -10),
            edit(true, PhysicsField::Rotation, 0, -5),
            edit(true, PhysicsField::Position, 1, 4),
        ],
    );
    let step = |v: f32, dy: i32, s: f64| (f64::from(v) - f64::from(dy) * s) as f32;
    let five = f64::from(0.05f32);
    let (r, j) = d.edit.physics_scratch.as_ref().unwrap();
    assert_eq!(r[0].rotation[1], step(rigids[0].rotation[1], 3, 0.01));
    assert_eq!(r[0].position[2], step(rigids[0].position[2], -2, five));
    assert_eq!(r[0].size[0], 0.1);
    assert_eq!(r[0].size[1], step(rigids[0].size[1], -10, five).max(0.1));
    assert_eq!(j[0].rotation[0], step(joints[0].rotation[0], -5, 0.01));
    assert_eq!(j[0].position[1], step(joints[0].position[1], 4, five));
    assert!(d.apply(edit(true, PhysicsField::Size, 0, 1)).is_err());
    assert!(d.apply(edit(false, PhysicsField::Size, 3, 1)).is_err());
    // The model keeps its bodies until the dialog's OK.
    let mds_doc::ModelFile::Pmd(pmd) = &d.models[0] else {
        panic!("a PMD")
    };
    assert_eq!(
        pmd.extension
            .as_ref()
            .unwrap()
            .physics
            .as_ref()
            .unwrap()
            .rigids,
        rigids
    );
    assert!(!edit(false, PhysicsField::Size, 0, 1).marks_modified());
}

/// A 24-bit bottom-up BMP of `w` by `h` grey pixels.
fn bmp(w: u32, h: u32) -> Vec<u8> {
    let stride = (w * 3).div_ceil(4) * 4;
    let size = 54 + stride * h;
    let mut b = b"BM".to_vec();
    for v in [size, 0, 54, 40] {
        b.extend(v.to_le_bytes());
    }
    b.extend(w.to_le_bytes());
    b.extend(h.to_le_bytes());
    b.extend(1u16.to_le_bytes());
    b.extend(24u16.to_le_bytes());
    for v in [0u32, stride * h, 2835, 2835, 0, 0] {
        b.extend(v.to_le_bytes());
    }
    b.resize(size as usize, 0x80);
    b
}

fn avi(w: u32, h: u32) -> Vec<u8> {
    use mds_media::avi::{AviWriter, Config};
    let cfg = Config {
        width: w,
        height: h,
        fps_num: 30,
        fps_den: 1,
        audio: None,
    };
    let mut out = std::io::Cursor::new(Vec::new());
    let mut wr = AviWriter::new(&mut out, cfg).unwrap();
    wr.write_frame(&vec![0x40; (w * h * 3) as usize]).unwrap();
    wr.finish().unwrap();
    out.into_inner()
}

/// MediaAspect (media_load.cpp 116-128), all float: w = hideLeft -
/// hideRight, h2 = (hideBottom - hideTop) / 2, zoom = (w / r * 1.2) /
/// width, pos = (int)(h2 - height * zoom * r / 1.2 * 0.5).
fn aspect(vp: &Viewport, width: i32, height: i32) -> (f32, i32) {
    let w = vp.hide_left - vp.hide_right;
    let h2 = (vp.hide_bottom - vp.hide_top) / 2;
    let r = vp.view_scale;
    let zoom = (w as f32 / r * 1.2f32) / width as f32;
    let drawn = (height as f32 * zoom * r) / 1.2f32;
    (zoom, (h2 as f32 - drawn * 0.5f32) as i32)
}

#[test]
fn background_media_load_with_the_cpp_placement() {
    // LoadAviFile (media_load.cpp 155-314): path, X 0, MediaAspect scale and
    // Y, enabled 1; a failure clears path and flag (AviFailTail, 96-99) and
    // keeps the placement. LoadBackgroundPicture (321-378): the same on
    // success; a decode failure clears the path and keeps the flag (361).
    // pmm_save.cpp 792-811 saves offset, scale, path and flag.
    let mut d = Document::startup();
    let movie = || Command::LoadBackgroundMovie {
        path: "C:\\bg\\m.avi".into(),
        data: avi(64, 48),
    };
    assert!(d.apply(movie()).is_err());
    let vp = Viewport {
        hide_left: 1016,
        hide_right: 216,
        hide_top: 0,
        hide_bottom: 601,
        view_scale: 0.9375,
    };
    d.edit.viewport = Some(vp);
    run(
        &mut d,
        [
            movie(),
            Command::LoadBackgroundPicture {
                path: "C:\\bg\\p.bmp".into(),
                data: bmp(40, 30),
            },
        ],
    );
    let p = reload(&d);
    let (s, y) = aspect(&vp, 64, 48);
    assert_eq!((p.avi.offset, p.avi.scale, p.avi.enabled), ([0, y], s, 1));
    assert_eq!(p.avi.path.text, "C:\\bg\\m.avi");
    let (s, y) = aspect(&vp, 40, 30);
    let pic = &p.picture;
    assert_eq!((pic.offset, pic.scale, pic.enabled), ([0, y], s, 1));
    assert_eq!(pic.path.text, "C:\\bg\\p.bmp");

    // Menus 216 and 233 (command_dispatch.cpp 541-553,
    // command_file_menu.cpp 1893-1906).
    run(&mut d, [Command::ShowBackgroundMovie(false)]);
    assert_eq!(d.pmm.avi.enabled, 0);
    run(&mut d, [Command::ShowBackgroundMovie(true)]);
    assert_eq!(d.pmm.avi.enabled, 1);

    let placed = (d.pmm.avi.offset, d.pmm.avi.scale);
    let bad = Command::LoadBackgroundMovie {
        path: "C:\\bg\\x.avi".into(),
        data: b"RIFF....AVI junk".to_vec(),
    };
    assert!(d.apply(bad).is_err());
    let a = &d.pmm.avi;
    assert_eq!((a.path.text.as_str(), a.enabled), ("", 0));
    assert_eq!((a.offset, a.scale), placed);
    // With no movie loaded, showing it does nothing.
    run(&mut d, [Command::ShowBackgroundMovie(true)]);
    assert_eq!(d.pmm.avi.enabled, 0);

    let bad = Command::LoadBackgroundPicture {
        path: "C:\\bg\\x.bmp".into(),
        data: b"not a picture".to_vec(),
    };
    assert!(d.apply(bad).is_err());
    let pic = &d.pmm.picture;
    assert_eq!((pic.path.text.as_str(), pic.enabled), ("", 1));
    run(
        &mut d,
        [
            Command::ShowBackgroundPicture(false),
            Command::ShowBackgroundPicture(true),
        ],
    );
    assert_eq!(d.pmm.picture.enabled, 0);
    assert!(movie().marks_modified());
    assert!(!Command::ShowBackgroundMovie(true).marks_modified());

    // Menu 282 and key B (command_view_menu.cpp 1401-1411).
    run(
        &mut d,
        [Command::SetViewOption {
            option: ViewOption::BlackBackground,
            on: true,
        }],
    );
    assert_eq!(reload(&d).appearance.black_background, 1);
}

#[test]
fn the_document_sees_the_paste_and_delete_key_gates() {
    // PasteSelectedKeyframes (frame_clipboard.cpp 491-516) returns before
    // SceneModified with an empty clipboard; the Delete key
    // (PumpDeleteRebuild, pump_edit_keys.cpp 241-254) calls
    // DeleteMarkedKeyframes without it, the button sets it
    // (command_frame_edit.cpp 1652).
    let mut d = load("swing600.pmm");
    run(&mut d, [Command::SelectModel(0)]);
    assert!(!d.marks_modified(&Command::Paste));
    assert!(!d.marks_modified(&Command::PasteMirrored));
    run(&mut d, [Command::SelectAll(SelectAll::Bone), Command::Copy]);
    assert!(d.marks_modified(&Command::Paste));
    assert!(d.marks_modified(&Command::PasteMirrored));
    assert!(d.marks_modified(&Command::DeleteSelectedKeys));
    assert!(!d.marks_modified(&Command::DeleteKey));
    let mut by_key = d.clone();
    run(
        &mut d,
        [Command::SetFrame(0), Command::SelectAll(SelectAll::Bone)],
    );
    run(
        &mut by_key,
        [Command::SetFrame(0), Command::SelectAll(SelectAll::Bone)],
    );
    run(&mut d, [Command::DeleteSelectedKeys]);
    run(&mut by_key, [Command::DeleteKey]);
    assert_eq!(by_key.save().unwrap(), d.save().unwrap());
}

#[test]
fn lip_sync_has_no_frame_change_side_effects() {
    // LoadVsqFile (vsq_load.cpp 862-897) writes currentFrame directly and
    // seeks the selected model only; the drop (ui_dropfiles.cpp 250-262)
    // calls it with no drop position. Unlike the frame edit
    // (RefreshAfterFrameApply), no bone selection is lost, no
    // SnapshotPoseBeforeFrameChange entry is pushed, and the other models
    // keep their poses.
    const FACES: [&[u8]; 4] = [b"\x82\xa0", b"\x82\xa2", b"\x82\xa4", b"\x82\xa8"];
    let mut d = load("swing600.pmm");
    run(&mut d, [Command::SelectModel(1)]);
    for (n, f) in d.pmm.models[1].morph_names.iter_mut().zip(FACES) {
        *n = mds_formats::text::Sjis::from_raw(f.to_vec());
    }
    run(&mut d, [Command::SelectBones(vec![0])]);
    d.pmm.models[1].bone_pose[0].flags[1] = 1;
    d.pmm.models[0].bone_pose[1].translation = [0.0, 9.0, 0.0];
    let cursor = d.edit.models[1].history.cursor;
    let run = d.lip_sync(&read("vsq/basic.vsq"), true).unwrap();
    let f = run.outcome.unwrap().final_frame.unwrap();
    assert_eq!(d.pmm.timeline.current_frame, f);
    assert_eq!(d.pmm.models[1].bone_pose[0].flags[2], 1);
    assert_eq!(d.edit.models[1].history.cursor, cursor);
    assert_eq!(d.pmm.models[0].bone_pose[1].translation, [0.0, 9.0, 0.0]);
}

#[test]
fn the_script_runner_pumps_on_request() {
    // run_line pumps the frame loop twice after a step (script_mode.cpp);
    // pump() is the same without a script line.
    let mut read = |p: &str| std::fs::read(dir().join(p)).ok();
    let mut a = mds_doc::script::Runner::new();
    let mut b = mds_doc::script::Runner::new();
    for r in [&mut a, &mut b] {
        r.run_line("load pmm swing600.pmm", &mut read).unwrap();
    }
    a.run_line("gravity open", &mut read).unwrap();
    b.pump(&mut read).unwrap();
    assert_eq!(a.doc.save().unwrap(), b.doc.save().unwrap());
    assert_eq!(
        a.doc.pmm.models[0].bone_pose[5].rotation,
        b.doc.pmm.models[0].bone_pose[5].rotation
    );
}

#[test]
fn a_vac_names_its_mesh_without_the_cr() {
    // `_wfopen_s(.., L"r")` (accessory.cpp 464) reads CRLF as LF, and the
    // second `fgets` line loses its `\n` (466-469).
    assert_eq!(
        mds_doc::vac_mesh_name(b"Vac\r\ntri2.x\r\n1.5\r\n"),
        b"tri2.x"
    );
    assert_eq!(mds_doc::vac_mesh_name(b"Vac\ntri2.x\n"), b"tri2.x");
    assert_eq!(mds_doc::vac_mesh_name(b"Vac\na\rb\n"), b"a\rb");
}
