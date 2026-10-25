//! The key drag, model delete, camera reference, lip sync, accessory and
//! PMD-file commands. Each expected value is read off the C++ named in the
//! test's comment.

use mds_doc::history::Entry;
use mds_doc::{Command, Document, EnglishName, GlobalTrack, SelectAll, Track};
use mds_formats::key_pool::{Key, KeyPool};
use mds_formats::text::Sjis;
use std::path::PathBuf;

fn dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

fn read(name: &str) -> Vec<u8> {
    std::fs::read(dir().join(name)).unwrap()
}

/// `name`: slot 0 is chain8_ik.pmx (9 bones, bone keys), slot 1 morph4.pmx.
fn load(name: &str) -> Document {
    Document::load(&read(name), |p| std::fs::read(dir().join(p)).ok()).unwrap()
}

fn run(d: &mut Document, cmds: impl IntoIterator<Item = Command>) {
    for c in cmds {
        let what = format!("{c:?}");
        d.apply(c).unwrap_or_else(|e| panic!("{what}: {e}"));
    }
}

/// The record indices of the track of `head`, in chain order.
fn chain<K: Key>(pool: &KeyPool<K>, head: u32) -> Vec<u32> {
    let mut out = vec![head];
    while let Some(k) = pool.get(*out.last().unwrap()) {
        if k.next() == 0 {
            break;
        }
        out.push(k.next());
    }
    out
}

fn frame<K: Key>(pool: &KeyPool<K>, i: u32) -> u32 {
    pool.get(i).unwrap().frame()
}

#[test]
fn a_forward_drag_moves_every_marked_record_and_raises_the_maxima() {
    // RemapList, row > 0 (ui_mousemove.cpp 150-171): from the last frame
    // down, so every key of a fully marked track moves by the row; head
    // keys (idx < boneCount) stay; maxFrame and lastRegisteredFrame follow.
    // The mouse-down pushes the marked bone records (ui_editor_click.cpp
    // 189-258).
    let mut d = load("swing600.pmm");
    run(
        &mut d,
        [Command::SelectModel(0), Command::SelectAll(SelectAll::Bone)],
    );
    let m = &d.pmm.models[0];
    let heads = m.bone_keys.heads().len() as u32;
    let before: Vec<(u32, u32)> = m
        .bone_keys
        .records()
        .iter()
        .map(|(i, k)| (*i, k.frame))
        .collect();
    let head_frames: Vec<u32> = m.bone_keys.heads().iter().map(|k| k.frame).collect();
    assert!(before.iter().all(|&(i, _)| i >= heads) && !before.is_empty());
    run(&mut d, [Command::MoveSelectedKeys(5)]);
    let m = &d.pmm.models[0];
    for &(i, f) in &before {
        assert_eq!(frame(&m.bone_keys, i), f + 5, "record {i}");
    }
    let now: Vec<u32> = m.bone_keys.heads().iter().map(|k| k.frame).collect();
    assert_eq!(now, head_frames);
    let max = before.iter().map(|&(_, f)| f + 5).max().unwrap();
    assert!(m.selection.max_frame >= max);
    assert!(d.pmm.timeline.last_registered_frame as u32 >= m.selection.max_frame);
    let h = &d.edit.models[0].history;
    assert!(matches!(&h.undo[h.cursor], Entry::BoneKeys { keys, .. } if !keys.is_empty()));
    validate(&d);
}

#[test]
fn a_dragged_key_stops_next_to_its_unmarked_neighbours() {
    // RemapList: row > 0 clamps to next.frame - 1 (161-166), row < 0 to
    // previous.frame + 1 (136-148).
    let base = load("swing600.pmm");
    let pool = &base.pmm.models[0].bone_keys;
    let (bone, track) = (0..pool.heads().len() as u32)
        .map(|b| (b, chain(pool, b)))
        .find(|(_, c)| c.len() >= 3)
        .expect("a track with three keys");
    let (mid, prev, next) = (track[1], frame(pool, track[0]), frame(pool, track[2]));
    let at = frame(pool, mid);
    for (row, want) in [(10_000, next - 1), (-10_000, prev + 1)] {
        let mut d = base.clone();
        run(
            &mut d,
            [
                Command::SelectModel(0),
                Command::ReplaceKeySelection {
                    track: Track::Bone(bone),
                    from: at,
                    to: at,
                },
                Command::MoveSelectedKeys(row),
            ],
        );
        assert_eq!(frame(&d.pmm.models[0].bone_keys, mid), want, "row {row}");
    }
}

#[test]
fn a_backward_drag_in_camera_mode_moves_the_camera_keys_in_frame_order() {
    // RemapList over the camera band (ui_mousemove.cpp 136-148, 376-380):
    // ascending frames, each key at max(previous + 1, frame + row); a
    // backward move raises nothing.
    let mut d = load("camera3.pmm");
    run(
        &mut d,
        [
            Command::SelectCameraMode,
            Command::ClearKeySelection,
            Command::SelectKeys {
                track: Track::Global(GlobalTrack::Camera),
                from: 1,
                to: u32::MAX,
            },
        ],
    );
    let track = chain(&d.pmm.camera, 0);
    assert!(track.len() >= 3);
    let before: Vec<u32> = track.iter().map(|&i| frame(&d.pmm.camera, i)).collect();
    let last = d.pmm.timeline.last_registered_frame;
    run(&mut d, [Command::MoveSelectedKeys(-2)]);
    let mut pf = before[0];
    for (&i, &f) in track.iter().zip(&before).skip(1) {
        let want = (f as i32 - 2).max(pf as i32 + 1) as u32;
        assert_eq!(frame(&d.pmm.camera, i), want);
        pf = want;
    }
    assert_eq!(d.pmm.timeline.last_registered_frame, last);
}

#[test]
fn deleting_a_model_cuts_every_link_to_its_slot() {
    // DeleteSelectedModel (command_frame_edit.cpp 1243-1335): combo and
    // display orders above it move down, the camera parent and camera keys
    // lose it (bone 0), accessory parents lose it (bone 0), accessory keys
    // lose it and their visible flag but keep the bone, then
    // ApplyModelComboSelection on the camera entry.
    let mut d = load("swing600.pmm");
    run(
        &mut d,
        [
            Command::SelectModel(0),
            Command::LoadAccessory {
                path: "C:\\acc\\cube.x".into(),
                data: read("accessory/cube.x"),
            },
            Command::SetAccessoryParentModel(Some(0)),
            Command::SetAccessoryParentBone(3),
        ],
    );
    let count = d.pmm.models.len();
    let combo = d.pmm.models[1].selection.combo_index;
    let order = d.pmm.models[1].display_order;
    let deleted = d.pmm.models[0].selection.combo_index;
    let deleted_order = d.pmm.models[0].display_order;
    assert!(combo > deleted);
    d.pmm.appearance.camera_parent_model = 0;
    d.pmm.appearance.camera_parent_bone = 4;
    d.pmm.camera.heads_mut()[0].parent_model = 0;
    d.pmm.camera.heads_mut()[0].parent_bone = 4;
    let k = &mut d.pmm.accessories[0].keys.heads_mut()[0];
    (k.parent_model, k.parent_bone) = (0, 3);
    k.opacity_visible |= 1;
    run(&mut d, [Command::DeleteModel(0)]);
    let p = &d.pmm;
    assert_eq!(p.models.len(), count - 1);
    assert_eq!(p.models[0].slot, 1);
    assert_eq!(p.models[0].selection.combo_index, combo - 1);
    let want = if order > deleted_order {
        order - 1
    } else {
        order
    };
    assert_eq!(p.models[0].display_order, want);
    let a = &p.appearance;
    assert_eq!((a.camera_parent_model, a.camera_parent_bone), (-1, 0));
    let c = &p.camera.heads()[0];
    assert_eq!((c.parent_model, c.parent_bone), (-1, 0));
    // The camera-mode entry then applies the accessory track, so the state
    // takes the key's kept bone.
    let acc = &p.accessories[0];
    assert_eq!((acc.state.parent_model, acc.state.parent_bone), (-1, 3));
    let k = &acc.keys.heads()[0];
    assert_eq!(
        (k.parent_model, k.parent_bone, k.opacity_visible & 1),
        (-1, 3, 0)
    );
    assert_eq!(p.settings.options[0], 1, "camera mode");
    assert_eq!(d.models.len(), count - 1);
    assert!(d.apply(Command::DeleteModel(0)).is_err());
    let again = Document::load(&d.save().unwrap(), |p| std::fs::read(dir().join(p)).ok()).unwrap();
    assert_eq!(again.pmm.models.len(), count - 1);
}

#[test]
fn the_camera_reference_re_anchors_the_view_in_model_mode_only() {
    // ApplyCameraReferenceModeChange (frame_modes.cpp 741-789) from mode 0
    // to mode 1 with no camera rotation and no parent: the view offset and
    // distance move by the center bone's matInit translation.
    let mut d = load("swing600.pmm");
    run(&mut d, [Command::SelectModel(0)]);
    d.pmm.camera_state[6..].fill(0.0);
    d.pmm.appearance.camera_parent_model = -1;
    d.pmm.timeline.camera_reference_mode = 0;
    let before = d.pmm.camera_state;
    let mds_doc::ModelFile::Pmx(pmx) = &d.models[0] else {
        panic!("chain8_ik.pmx")
    };
    let mut pose = mds_pose::model::Model::from_pmx(0, pmx).unwrap();
    pose.apply_pmm(&d.pmm.models[0]).unwrap();
    mds_pose::pose::apply_morphs(&mut pose);
    let mode = i32::from(d.pmm.physics.playback_mode);
    mds_pose::pose::set_physics_mode(&mut pose, 0, &mds_pose::pose::Others::NONE, mode);
    let t = pose.bones[pose.center_bone].mat_init.0;
    run(&mut d, [Command::SetCameraReference(1)]);
    let s = d.pmm.camera_state;
    assert_eq!(d.pmm.timeline.camera_reference_mode, 1);
    assert_eq!(
        [s[3], s[4], s[5]],
        [before[3] - t[12], before[4] - t[13], before[5] - t[14]]
    );
    // Camera mode stores the mode only (command_frame_edit.cpp 1455).
    run(&mut d, [Command::SelectCameraMode]);
    let s = d.pmm.camera_state;
    run(&mut d, [Command::SetCameraReference(2)]);
    assert_eq!(d.pmm.camera_state, s);
    assert_eq!(d.pmm.timeline.camera_reference_mode, 2);
}

/// Shift-JIS of あ, い, う, お.
const FACES: [&[u8]; 4] = [b"\x82\xa0", b"\x82\xa2", b"\x82\xa4", b"\x82\xa8"];

#[test]
fn lip_sync_registers_the_vowel_keys_and_moves_to_the_last_note() {
    // LoadVsqFile (vsq_load.cpp 805-883): marks of the three pools cleared,
    // VsqMorphKey per key, the current frame (int)(end * 30) of the last
    // note, lastRegisteredFrame raised to maxFrame, the seek, and the
    // timeline start six frames before. The keys are mds_vsq's (checked
    // against the C++ in mds-vsq/tests/dumps.rs).
    let mut d = load("swing600.pmm");
    run(&mut d, [Command::SelectModel(1)]);
    let m = &mut d.pmm.models[1];
    assert!(m.morph_names.len() >= 4);
    for (n, f) in m.morph_names.iter_mut().zip(FACES) {
        *n = Sjis::from_raw(f.to_vec());
    }
    let vsq = read("vsq/basic.vsq");
    let names: Vec<&[u8]> = d.pmm.models[1]
        .morph_names
        .iter()
        .map(|n| n.raw.as_slice())
        .collect();
    let want = mds_vsq::lip_sync(&vsq, &names).outcome.unwrap();
    assert!(!want.keys.is_empty());
    let got = d.lip_sync(&vsq, false).unwrap();
    assert_eq!(got.outcome.as_ref().unwrap(), &want);
    let f = want.final_frame.unwrap();
    let t = &d.pmm.timeline;
    assert_eq!(t.current_frame, f);
    assert_eq!(t.start_frame, (f - 6).max(0));
    let m = &d.pmm.models[1];
    assert!(t.last_registered_frame as u32 >= m.selection.max_frame);
    for k in &want.keys {
        let last = want
            .keys
            .iter()
            .rfind(|o| o.morph == k.morph && o.frame == k.frame)
            .unwrap();
        let pool = &m.morph_keys;
        let rec = chain(pool, k.morph as u32)
            .into_iter()
            .map(|i| pool.get(i).unwrap())
            .find(|r| r.frame == k.frame as u32)
            .unwrap_or_else(|| panic!("no key at {} on morph {}", k.frame, k.morph));
        assert_eq!((rec.value, rec.allocated), (last.weight, 1));
    }
    assert!(m.bone_keys.records().iter().all(|(_, k)| k.allocated == 0));
    assert!(m.display_keys.heads().iter().all(|k| k.allocated == 0));
    // A dropped .vsq is refused in camera mode (ui_dropfiles.cpp 252); the
    // menu is not (command_file_menu.cpp 1147).
    let mut d = d.clone();
    run(&mut d, [Command::SelectCameraMode]);
    assert!(d.lip_sync(&vsq, true).is_err());
    assert!(d.lip_sync(&vsq, false).unwrap().outcome.is_ok());
}

#[test]
fn pmd_edits_reach_the_pmd_writer() {
    // CollectEnglishNameEdit (english_name_dialog.cpp 118-205): bone names
    // cut to 19 bytes, strcpy_s keeps the bytes after the NUL;
    // CollectToonFileNames (enhance_model_io.cpp 57-95) skips a name equal
    // to toonNN.bmp; CommitPhysicsEdits replaces both tables; the writer
    // saves them (enhance_model_io.cpp 304-354).
    let mut d = Document::startup();
    run(
        &mut d,
        [Command::LoadModel {
            path: "chain8.pmd".into(),
            data: read("chain8.pmd"),
        }],
    );
    let mds_doc::ModelFile::Pmd(old) = d.models[0].clone() else {
        panic!("a PMD")
    };
    let ext = old.extension.as_ref().unwrap();
    let phys = ext.physics.as_ref().unwrap();
    let mut rigid = phys.rigids[0].clone();
    rigid.mass = 2.5;
    let mut toons: Vec<String> = (1..=10).map(|i| format!("toon{i:02}.bmp")).collect();
    toons[1] = "mine.bmp".into();
    run(
        &mut d,
        [
            Command::SetEnglishName {
                name: EnglishName::Bone(0),
                text: "Center".into(),
            },
            Command::SetEnglishName {
                name: EnglishName::Model,
                text: "A model name longer than nineteen".into(),
            },
            Command::SetEnglishName {
                name: EnglishName::Comment,
                text: "line 1\r\nline 2".into(),
            },
            Command::SetToonFileNames(toons),
            Command::SetPhysicsModel {
                rigids: vec![rigid.clone()],
                joints: Vec::new(),
            },
        ],
    );
    assert_eq!(d.pmm.models[0].name_en.raw, b"A model name longer");
    let saved = d.save_pmd("C:\\out\\saved.pmd").unwrap();
    let p = mds_formats::pmd::Pmd::read(&saved).unwrap();
    let e = p.extension.as_ref().unwrap();
    let en = e.english.as_ref().unwrap();
    let mut want = ext.english.as_ref().unwrap().bone_names[0].raw;
    want[..7].copy_from_slice(b"Center\0");
    assert_eq!(en.bone_names[0].raw, want);
    assert_eq!(&en.name.raw[..20], b"A model name longer\0");
    assert_eq!(&en.comment.raw[..14], b"line 1\nline 2\0");
    assert_eq!(
        en.comment.raw[14..],
        ext.english.as_ref().unwrap().comment.raw[14..]
    );
    assert_eq!(e.toon_textures[0].raw, ext.toon_textures[0].raw);
    assert_eq!(&e.toon_textures[1].raw[..9], b"mine.bmp\0");
    let ph = e.physics.as_ref().unwrap();
    assert_eq!(ph.rigids, vec![rigid]);
    assert_eq!(ph.joints.as_deref(), Some(&[][..]));
    assert_eq!(d.pmm.models[0].path.text, "C:\\out\\saved.pmd");
}

#[test]
fn a_vac_places_its_mesh_with_the_file_values() {
    // LoadAccessoryObject's .vac branch (accessory.cpp 461-488): line 2 is
    // the mesh, then scale, position, rotation, two lines skipped, and the
    // shadow-disabled int; the name is the mesh's, the path the .vac's; the
    // head key copies the record (650-658).
    let vac = b"Vocaloid Accessory\ncube.x\n2.5\n1,2,3\n0.1,0.2,0.3\nskipped\n1\n".to_vec();
    assert_eq!(mds_doc::vac_mesh_name(&vac), b"cube.x");
    let mut d = Document::startup();
    run(
        &mut d,
        [Command::LoadVac {
            path: "C:\\acc\\cube.vac".into(),
            vac,
            mesh_path: "C:\\acc\\cube.x".into(),
            mesh: read("accessory/cube.x"),
        }],
    );
    let a = &d.pmm.accessories[0];
    assert_eq!(a.name.text, "cube.x");
    assert_eq!(a.path.text, "C:\\acc\\cube.vac");
    let s = &a.state;
    assert_eq!(
        (s.scale, s.position, s.rotation, s.shadow),
        (2.5, [1.0, 2.0, 3.0], [0.1, 0.2, 0.3], 0)
    );
    let k = &a.keys.heads()[0];
    assert_eq!(
        (k.scale, k.position, k.rotation, k.shadow),
        (2.5, [1.0, 2.0, 3.0], [0.1, 0.2, 0.3], 0)
    );
}

#[test]
fn the_parent_bone_combo_lists_bone_types_below_7_and_8() {
    // RepopulateBoneCombo (command_dispatch.cpp 72-85).
    let mut d = Document::startup();
    run(
        &mut d,
        [Command::LoadModel {
            path: "chain8.pmd".into(),
            data: read("chain8.pmd"),
        }],
    );
    let mds_doc::ModelFile::Pmd(pmd) = &d.models[0] else {
        panic!("chain8.pmd")
    };
    let pose = mds_pose::model::Model::from_pmd(0, pmd).unwrap();
    let want: Vec<u32> = (0..pose.bones.len() as u32)
        .filter(|&b| matches!(pose.bones[b as usize].kind, 0..=6 | 8))
        .collect();
    assert_eq!(d.accessory_parent_bones(0), want);
    assert!(d.accessory_parent_bones(9).is_empty());
}

#[test]
fn menu_250_in_camera_mode_pastes_onto_the_selected_accessory() {
    // command_file_menu.cpp 1596-1637: every global mark cleared, then
    // PasteAccessoryKeyRecord onto the selected slot at the current frame
    // plus the key's offset (accessory_paste.cpp 202-263).
    let mut d = load("swing600.pmm");
    let x = read("accessory/cube.x");
    for n in ["a", "b"] {
        run(
            &mut d,
            [Command::LoadAccessory {
                path: format!("C:\\acc\\{n}.x"),
                data: x.clone(),
            }],
        );
    }
    let (a, b) = (d.pmm.accessories[0].slot, d.pmm.accessories[1].slot);
    run(
        &mut d,
        [
            Command::SelectCameraMode,
            Command::SelectAccessory(a),
            Command::SetFrame(10),
            Command::AccessoryEdit {
                field: 0,
                value: 4.0,
            },
            Command::RegisterGlobalKeys(vec![GlobalTrack::Accessory(a)]),
            Command::Copy,
            Command::SelectAccessory(b),
            Command::SetFrame(30),
            Command::PasteToSelectedBone,
        ],
    );
    let keys = &d.pmm.accessories[1].keys;
    let at = chain(keys, 0)
        .into_iter()
        .map(|i| keys.get(i).unwrap())
        .find(|k| k.frame == 30)
        .expect("a key at 30");
    assert_eq!((at.position[0], at.selected), (4.0, 1));
    let src = &d.pmm.accessories[0].keys;
    assert!(chain(src, 0)
        .iter()
        .all(|&i| src.get(i).unwrap().selected == 0));
    assert!(d.pmm.timeline.last_registered_frame >= 30);
}

#[test]
fn marks_modified_follows_the_handlers() {
    // ui_mousemove.cpp 334, command_frame_edit.cpp 1239; the frame edit
    // and the reference check boxes write nothing.
    assert!(Command::MoveSelectedKeys(1).marks_modified());
    assert!(Command::DeleteModel(0).marks_modified());
    assert!(!Command::SetFrame(0).marks_modified());
    assert!(!Command::SetCameraReference(1).marks_modified());
}

fn validate(d: &Document) {
    for m in &d.pmm.models {
        m.bone_keys.validate_tracks().unwrap();
        m.morph_keys.validate_tracks().unwrap();
        m.display_keys.validate_tracks().unwrap();
    }
}
