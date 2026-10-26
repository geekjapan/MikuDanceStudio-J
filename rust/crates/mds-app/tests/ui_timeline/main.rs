//! The `timeline` area through `Ctx::run` and the pure functions behind its mouse rows, with the
//! saved PMM compared to the C++ output of `tests/fixtures/rust/script/` where a script covers the
//! operation, and expected values read off the C++ handlers where none does.

mod drag;
mod rig;
mod scale;

use egui::{Key, Modifiers, Vec2};
use mds_app::actions::{self, Handler};
use mds_app::ui::timeline::{self, Hit, RowKind};
use mds_app::ui::{chord, Ctx};
use mds_doc::{GlobalTrack, Track};
use rig::{assert_bytes, expected, global, Rig};

fn inventory_ids() -> Vec<String> {
    let path = rig::fixtures().join("../../../tools/ui_inventory/inventory.tsv");
    let text = std::fs::read_to_string(path).unwrap();
    text.lines()
        .skip(1)
        .filter_map(|l| {
            let f: Vec<_> = l.split('\t').collect();
            (f[5] == "timeline").then(|| f[0].to_string())
        })
        .collect()
}

#[test]
fn every_row_has_an_action() {
    let ids = inventory_ids();
    assert_eq!(ids.len(), 52);
    let missing: Vec<_> = ids
        .iter()
        .filter(|id| !timeline::actions().iter().any(|a| a.id == id.as_str()))
        .collect();
    assert!(missing.is_empty(), "{missing:?}");
    for a in timeline::actions() {
        assert!(
            ids.iter().any(|i| i == a.id),
            "{} is not a timeline row",
            a.id
        );
        assert!(!matches!(a.handler, Handler::Dropped(_)));
    }
}

#[test]
fn key_presses_map_to_the_registered_chords() {
    let ctrl = Modifiers::COMMAND;
    for (key, mods, id) in [
        (Key::C, ctrl, "key:Ctrl+C"),
        (Key::V, ctrl, "key:Ctrl+V"),
        (Key::G, Modifiers::NONE, "key:G"),
        (Key::Delete, Modifiers::NONE, "key:Delete"),
        (Key::Z, ctrl, "key:Ctrl+Z"),
        (Key::X, ctrl, "key:Ctrl+X"),
    ] {
        assert_eq!(
            chord(key, mods).map(|c| format!("key:{c}")).as_deref(),
            Some(id)
        );
        assert!(actions::find(id).is_some(), "{id}");
    }
    // The arrows are the area's own (held keys repeat); Enter has a camera-mode variant.
    assert_eq!(chord(Key::ArrowLeft, Modifiers::NONE), None);
    assert!(actions::find("key:Enter@camera-mode").is_some());
}

#[test]
fn the_frame_buttons_and_go() {
    // morphs.txt line 24: last registered frame is 24.
    let mut rig = Rig::replay("morphs", 24);
    let last = rig.editor.doc.pmm.timeline.last_registered_frame as u32;
    assert_eq!(last, 24);
    // 553 (command_frame_register.cpp:697): the edit's frame becomes the current frame.
    rig.goto(50);
    assert_eq!(rig.editor.current_frame(), 50);
    // 558 (:751) frame 0, 559 (:762) the last registered frame.
    rig.run("ctl:558").unwrap();
    assert_eq!(rig.editor.current_frame(), 0);
    rig.run("ctl:559").unwrap();
    assert_eq!(rig.editor.current_frame(), last);
    // 555 (:714) echoes the current frame into the go-to edit; G (key_ladder.cpp:166) is 553.
    rig.update(|p| p.goto = 7);
    rig.run("ctl:555").unwrap();
    assert_eq!(rig.panel().goto, last);
    rig.update(|p| p.goto = 3);
    rig.run("key:G").unwrap();
    assert_eq!(rig.editor.current_frame(), 3);
    assert_eq!(
        rig.editor.physics_opens, 1,
        "a seek keeps the physics world"
    );
}

#[test]
fn the_frame_buttons_stop_during_playback() {
    let mut rig = Rig::open("swing600.pmm");
    rig.run("ctl:408").unwrap();
    for id in [
        "ctl:553", "ctl:558", "ctl:559", "ctl:532", "ctl:533", "ctl:415", "ctl:420",
    ] {
        assert_eq!(rig.run(id), Err(format!("{id}: not while playing")));
    }
    // 555 only copies the current frame to an edit (playback_state.cpp:334 leaves it alone).
    rig.run("ctl:555").unwrap();
}

#[test]
fn the_frame_field_shows_the_playback_cursor() {
    let mut rig = Rig::open("swing600.pmm");
    rig.run("ctl:408").unwrap();
    rig.editor.pump(500).unwrap();
    let ctx = rig.ctx();
    // The document's current frame stays at the frame play started from.
    assert_eq!(ctx.editor.current_frame(), 0);
    assert_eq!(timeline::frame_field(&ctx), 15);
    assert_ne!(timeline::frame_field(&ctx), ctx.editor.current_frame());
}

#[test]
fn range_select_copy_and_paste_save_what_the_cpp_saved() {
    // morphs.txt lines 25 to 29: select all morph, copy, frame 50, paste, save.
    let mut rig = Rig::replay("morphs", 24);
    rig.range(0, 99_999, 1);
    rig.run("ctl:415").unwrap();
    rig.run("ctl:420").unwrap();
    rig.goto(50);
    rig.run("ctl:421").unwrap();
    assert_bytes("pasted.pmm", &rig.save(), &expected("morphs", "pasted.pmm"));
}

#[test]
fn ctrl_c_and_ctrl_v_are_copy_and_paste() {
    let mut rig = Rig::replay("morphs", 24);
    rig.range(0, 99_999, 1);
    rig.run("ctl:415").unwrap();
    rig.run("key:Ctrl+C").unwrap();
    rig.goto(50);
    rig.run("key:Ctrl+V").unwrap();
    assert_bytes("pasted.pmm", &rig.save(), &expected("morphs", "pasted.pmm"));
}

#[test]
fn delete_saves_what_the_cpp_saved() {
    // morphs.txt lines 38 to 44; the two select-all menus after the delete belong to `edit`.
    let mut rig = Rig::replay("morphs", 37);
    rig.range(0, 99_999, 1);
    rig.run("ctl:415").unwrap();
    rig.goto(51);
    rig.run("ctl:423").unwrap();
    for all in [mds_doc::SelectAll::Morph, mds_doc::SelectAll::Display] {
        rig.editor.apply(mds_doc::Command::SelectAll(all)).unwrap();
    }
    assert_bytes("morphs.pmm", &rig.save(), &expected("morphs", "morphs.pmm"));
}

#[test]
fn the_delete_key_is_delete() {
    let mut rig = Rig::replay("morphs", 37);
    rig.range(0, 99_999, 1);
    rig.run("ctl:415").unwrap();
    rig.goto(51);
    rig.run("key:Delete").unwrap();
    let mut by_button = Rig::replay("morphs", 37);
    by_button.range(0, 99_999, 1);
    by_button.run("ctl:415").unwrap();
    by_button.goto(51);
    by_button.run("ctl:423").unwrap();
    assert_bytes("delete key", &rig.save(), &by_button.save());
}

#[test]
fn camera_mode_range_select_copy_paste_and_delete() {
    // camera.txt lines 33 to 37 and 48 to 51.
    let mut rig = Rig::replay("camera", 32);
    rig.range(0, 99_999, 0);
    rig.run("ctl:415").unwrap();
    rig.run("ctl:420").unwrap();
    rig.goto(100);
    rig.run("ctl:421").unwrap();
    assert_bytes("pasted.pmm", &rig.save(), &expected("camera", "pasted.pmm"));

    let mut rig = Rig::replay("camera", 47);
    rig.range(0, 99_999, 0);
    rig.run("ctl:415").unwrap();
    rig.goto(101);
    rig.run("ctl:423").unwrap();
    assert_bytes(
        "deleted.pmm",
        &rig.save(),
        &expected("camera", "deleted.pmm"),
    );
}

#[test]
fn enter_registers_the_selected_rows() {
    // camera.txt line 10 `register camera`, line 14 `register light`.
    for (upto, row, line) in [(9, GlobalTrack::Camera, 10), (13, GlobalTrack::Light, 14)] {
        let mut by_button = rig::runner("camera", upto);
        let text = std::fs::read_to_string(rig::fixtures().join("script/camera.txt")).unwrap();
        let register = text.lines().nth(line - 1).unwrap();
        by_button.run_line(register, &mut |_| None).unwrap();

        let mut rig = Rig::replay("camera", upto);
        rig.run("ctl:555").unwrap();
        rig.update(|p| {
            p.global_rows = [
                row == GlobalTrack::Camera,
                row == GlobalTrack::Light,
                false,
                false,
            ]
        });
        rig.run("key:Enter@camera-mode").unwrap();
        assert_bytes(register, &rig.save(), &by_button.doc.save().unwrap());
    }
}

#[test]
fn enter_with_no_row_selected_registers_nothing() {
    let mut rig = Rig::replay("camera", 9);
    let frames = |rig: &Rig| timeline::keys_of(&rig.editor.doc, global(GlobalTrack::Camera));
    let before = frames(&rig);
    rig.update(|p| p.global_rows = [false; 4]);
    timeline::set_marks(&mut rig.ctx(), vec![(global(GlobalTrack::Camera), 0)]).unwrap();
    assert_eq!(
        rig.marks()
            .iter()
            .filter(|m| matches!(m.0, Track::Global(_)))
            .count(),
        1
    );
    rig.run("key:Enter@camera-mode").unwrap();
    // The marks are cleared (pump_edit_keys.cpp:332); no key is added.
    assert_eq!(
        frames(&rig).iter().map(|k| k.0).collect::<Vec<_>>(),
        before.iter().map(|k| k.0).collect::<Vec<_>>()
    );
    let global_marks = |rig: &Rig| {
        rig.marks()
            .into_iter()
            .filter(|m| matches!(m.0, Track::Global(_)))
            .count()
    };
    assert_eq!(global_marks(&rig), 0);
}

#[test]
fn range_select_replaces_only_the_swept_tracks_marks() {
    // bones.txt lines 3 to 12: chain8.pmx with bone keys of センター (frame 10) and 上半身 (20).
    let mut rig = Rig::replay("bones", 12);
    let (center, upper) = (rig.bone("センター"), rig.bone("上半身"));
    // Scope 2, all bones: every bone key in 5..=15 and nothing else (head keys at 0 are out).
    rig.range(5, 15, 2);
    rig.run("ctl:415").unwrap();
    assert_eq!(rig.marks(), vec![(Track::Bone(center), 10)]);
    // Scope 4, selected facial (none selected): clears no bone mark and adds none.
    rig.range(0, 99_999, 4);
    rig.run("ctl:415").unwrap();
    assert_eq!(rig.marks(), vec![(Track::Bone(center), 10)]);
    // Scope 3, selected bone (上半身, from `select bone`): its marks are replaced; the other
    // track keeps its mark.
    rig.range(15, 25, 3);
    rig.run("ctl:415").unwrap();
    assert_eq!(
        rig.marks(),
        vec![(Track::Bone(center), 10), (Track::Bone(upper), 20)]
    );
    // Scope 0, all frames, a range with no key: every track is swept, so all marks go.
    rig.range(500, 600, 0);
    rig.run("ctl:415").unwrap();
    assert_eq!(rig.marks(), vec![]);
}

#[test]
fn vertical_select_marks_the_frames_of_the_marked_keys_in_every_track() {
    let mut rig = Rig::replay("bones", 12);
    let center = rig.bone("センター");
    let doc = &rig.editor.doc;
    let at_zero: Vec<_> = (0..doc.pmm.models[0].bone_keys.heads().len() as u32)
        .map(Track::Bone)
        .chain((0..doc.pmm.models[0].morph_keys.heads().len() as u32).map(Track::Morph))
        .chain([Track::Display])
        .map(|t| (t, 0))
        .collect();
    // One mark on a frame-0 key: 416 marks the frame-0 key of every bone, morph and display track
    // (SyncKeyframeSelection, command_frame_edit.cpp:843, loops A to C).
    timeline::set_marks(&mut rig.ctx(), vec![(Track::Bone(center), 0)]).unwrap();
    rig.run("ctl:416").unwrap();
    let mut want = at_zero.clone();
    want.sort_by_key(|(t, f)| (format!("{t:?}"), *f));
    let mut got = rig.marks();
    got.sort_by_key(|(t, f)| (format!("{t:?}"), *f));
    assert_eq!(got, want);
    // A mark on a frame no other track keys leaves the others alone.
    timeline::set_marks(&mut rig.ctx(), vec![(Track::Bone(center), 10)]).unwrap();
    rig.run("ctl:416").unwrap();
    assert_eq!(rig.marks(), vec![(Track::Bone(center), 10)]);
}

#[test]
fn camera_mode_vertical_select_reaches_every_camera_mode_track() {
    let mut rig = Rig::replay("camera", 24);
    let frame = |rig: &Rig, g| {
        timeline::keys_of(&rig.editor.doc, global(g))
            .iter()
            .map(|k| k.0)
            .collect::<Vec<_>>()
    };
    // Every track has its head key at frame 0.
    for g in [
        GlobalTrack::Camera,
        GlobalTrack::Light,
        GlobalTrack::SelfShadow,
        GlobalTrack::Gravity,
    ] {
        assert_eq!(frame(&rig, g)[0], 0);
    }
    timeline::set_marks(&mut rig.ctx(), vec![(global(GlobalTrack::Camera), 0)]).unwrap();
    rig.run("ctl:416").unwrap();
    let marked: Vec<_> = rig
        .marks()
        .into_iter()
        .filter(|m| m.1 == 0)
        .map(|m| m.0)
        .collect();
    for g in [
        GlobalTrack::Camera,
        GlobalTrack::Light,
        GlobalTrack::SelfShadow,
        GlobalTrack::Gravity,
    ] {
        assert!(marked.contains(&global(g)), "{g:?}");
    }
}

#[test]
fn a_cell_click_follows_toggle_model_key_allocated() {
    // ui_editor_click.cpp:403: an unmarked key becomes the only mark; a marked key stays; Shift
    // toggles; an empty cell clears the marks unless Shift is held.
    let mut rig = Rig::replay("bones", 12);
    let (center, upper) = (
        Track::Bone(rig.bone("センター")),
        Track::Bone(rig.bone("上半身")),
    );
    let click =
        |rig: &mut Rig, t, f, shift| timeline::click_cell(&mut rig.ctx(), t, f, shift).unwrap();
    click(&mut rig, center, 10, false);
    assert_eq!(rig.marks(), vec![(center, 10)]);
    click(&mut rig, upper, 20, true);
    assert_eq!(rig.marks(), vec![(center, 10), (upper, 20)]);
    // A marked key without Shift: the marks stay (the drag would take them).
    click(&mut rig, center, 10, false);
    assert_eq!(rig.marks(), vec![(center, 10), (upper, 20)]);
    click(&mut rig, center, 10, true);
    assert_eq!(rig.marks(), vec![(upper, 20)]);
    click(&mut rig, center, 11, true);
    assert_eq!(rig.marks(), vec![(upper, 20)]);
    click(&mut rig, center, 11, false);
    assert_eq!(rig.marks(), vec![]);
    // Marks are no edit.
    assert!(!rig.editor.modified);
}

#[test]
fn a_box_marks_the_keys_inside() {
    let mut rig = Rig::replay("bones", 12);
    let (center, upper) = (
        Track::Bone(rig.bone("センター")),
        Track::Bone(rig.bone("上半身")),
    );
    timeline::box_select(&mut rig.ctx(), &[center, upper], 5, 25, false).unwrap();
    assert_eq!(rig.marks(), vec![(center, 10), (upper, 20)]);
    timeline::box_select(&mut rig.ctx(), &[upper], 0, 0, true).unwrap();
    assert_eq!(rig.marks(), vec![(center, 10), (upper, 0), (upper, 20)]);
    timeline::box_select(&mut rig.ctx(), &[center], 0, 99, false).unwrap();
    assert_eq!(rig.marks(), vec![(center, 0), (center, 10)]);
}

#[test]
fn the_frame_strip_sets_the_current_frame() {
    let mut rig = Rig::replay("bones", 12);
    timeline::click_strip(&mut rig.ctx(), 7).unwrap();
    assert_eq!(rig.editor.current_frame(), 7);
    assert_eq!(rig.editor.physics_opens, 1);
}

#[test]
fn the_frame_strip_keeps_the_bone_selection_and_the_frame_edit_clears_it() {
    // ClickFrame keeps `selectedBone` (HandleLButtonDown_FrameStripHit, ui_editor_click.cpp:801);
    // the frame edit 417 goes through SetFrame, which clears it.
    let mut rig = Rig::replay("bones", 12);
    let c = rig.bone("センター");
    let row = rig.row(Track::Bone(c));
    timeline::click_name(&mut rig.ctx(), &row, false).unwrap();
    timeline::click_strip(&mut rig.ctx(), 7).unwrap();
    assert_eq!(rig.editor.current_frame(), 7);
    assert_eq!(selected(&rig), vec![c]);
    assert!(!rig.editor.modified, "a strip click is no scene edit");
    rig.editor.seek(8).unwrap();
    assert_eq!(selected(&rig), Vec::<u32>::new());
}

#[test]
fn the_frame_strip_stops_during_playback() {
    let mut rig = Rig::open("swing600.pmm");
    rig.run("ctl:408").unwrap();
    assert_eq!(
        timeline::click_strip(&mut rig.ctx(), 7),
        Err("not while playing".into())
    );
}

#[test]
fn reverse_paste_makes_the_key_pools_the_script_makes() {
    // bones.txt lines 20 to 25: select all bone, copy, frame 40, paste, frame 60, `paste reverse`.
    // The script runner pumps the frame loop after each line, which moves the saved pose, so the
    // key pools are compared and not the PMM bytes.
    let pools = |rig: &Rig| format!("{:?}", rig.editor.doc.pmm.models[0].bone_keys);
    let mut rig = Rig::replay("bones", 24);
    let before = pools(&rig);
    rig.run("ctl:422").unwrap();
    assert_ne!(pools(&rig), before);
    assert!(
        pools(&rig) == pools(&Rig::replay("bones", 25)),
        "key pools differ"
    );
}

#[test]
fn the_margin_toggles_the_group_flag_the_pmm_saves() {
    // ToggleDisplayGroup flips DisplayGroups[type].flags (ui_editor_click.cpp:451), type being
    // the PMX frame index, plus one when the model has the facial group (pmx_load.cpp:1417 and
    // :1432). morph4.pmx has morphs and so the facial group at 2; its frames from 2 on are
    // groups 3 and up.
    let mut rig = Rig::replay("morphs", 5);
    let before = rig.save();
    let flags = |rig: &Rig| rig.editor.doc.pmm.models[0].selection.group_flags.clone();
    let start = flags(&rig);
    let rows = timeline::rows(&rig.editor.doc, &[]);
    let morphs = rows
        .iter()
        .find(|r| r.kind == RowKind::Header(timeline::MORPHS))
        .unwrap()
        .clone();
    assert_eq!(
        timeline::group_flag(&rig.editor.doc, timeline::MORPHS),
        Some(2)
    );
    timeline::click_plus(&mut rig.ctx(), &morphs).unwrap();
    let mut want = start.clone();
    want[2] = u8::from(start[2] == 0);
    assert_eq!(flags(&rig), want);
    assert!(!rig.editor.modified);
    assert_ne!(rig.save(), before, "the PMM saves the flag");
    timeline::click_margin(&mut rig.ctx(), &morphs).unwrap();
    assert_bytes("toggled twice", &rig.save(), &before);
}

#[test]
fn a_bone_group_flag_follows_the_frame_index() {
    let rig = Rig::replay("bones", 12);
    let doc = &rig.editor.doc;
    let groups = flags_of_headers(doc);
    // The root frame lists its bones under a header too, but it is no flag group.
    let mds_doc::ModelFile::Pmx(pmx) = &doc.models[0] else {
        panic!("chain8.pmx")
    };
    let facial = pmx
        .frames
        .iter()
        .any(|f| f.entries.iter().any(|e| e.0 == 1));
    let bone_frames: Vec<usize> = pmx
        .frames
        .iter()
        .enumerate()
        .filter(|(_, f)| f.entries.iter().any(|e| e.0 == 0))
        .map(|(n, _)| n)
        .collect();
    assert!(bone_frames.len() > 1);
    assert_eq!(
        groups,
        bone_frames
            .iter()
            .map(|&n| (n >= 2).then(|| (n + usize::from(facial)) as u8))
            .collect::<Vec<_>>()
    );
}

fn flags_of_headers(doc: &mds_doc::Document) -> Vec<Option<u8>> {
    timeline::rows(doc, &[])
        .iter()
        .filter_map(|r| match r.kind {
            RowKind::Header(g) if g != timeline::MORPHS => Some(timeline::group_flag(doc, g)),
            _ => None,
        })
        .collect()
}

#[test]
fn the_margin_of_a_row_without_a_flag_does_nothing() {
    let mut rig = Rig::replay("bones", 12);
    let before = rig.save();
    let row = rig.row(Track::Display);
    timeline::click_margin(&mut rig.ctx(), &row).unwrap();
    assert_bytes("display row", &rig.save(), &before);
}

#[test]
fn curve_buttons_copy_paste_and_reset_the_channel_of_the_combo() {
    // CopyInterpolationCurve, PasteInterpolationCurve and ResetInterpolationCurves
    // (command_frame_edit.cpp:987, :1033, :1082): a bone channel is the bytes [ch], [4+ch],
    // [8+ch], [12+ch] of the key; copy reads the first marked key, paste writes every marked key,
    // reset writes 20, 20, 107, 107. The combo starts on rotation (3).
    let mut rig = Rig::replay("bones", 12);
    let (c, u) = (rig.bone("センター"), rig.bone("上半身"));
    assert_eq!(rig.panel().curve, 3);
    let bytes = |rig: &Rig, bone: u32, frame: u32, ch: usize| {
        let pool = &rig.editor.doc.pmm.models[0].bone_keys;
        let mut i = pool.heads()[bone as usize].next;
        while pool.get(i).unwrap().frame != frame {
            i = pool.get(i).unwrap().next;
        }
        let k = pool.get(i).unwrap().interpolation;
        [k[ch], k[4 + ch], k[8 + ch], k[12 + ch]]
    };
    let key = |rig: &Rig, bone: u32, frame: u32| {
        let pool = &rig.editor.doc.pmm.models[0].bone_keys;
        let mut i = pool.heads()[bone as usize].next;
        while pool.get(i).unwrap().frame != frame {
            i = pool.get(i).unwrap().next;
        }
        i
    };
    let at = key(&rig, c, 10);
    let k = rig.editor.doc.pmm.models[0].bone_keys.get_mut(at).unwrap();
    k.interpolation[3] = 1;
    k.interpolation[7] = 2;
    k.interpolation[11] = 3;
    k.interpolation[15] = 4;
    timeline::click_cell(&mut rig.ctx(), Track::Bone(c), 10, false).unwrap();
    rig.run("ctl:430").unwrap();
    timeline::click_cell(&mut rig.ctx(), Track::Bone(u), 20, false).unwrap();
    let other = bytes(&rig, u, 20, 0);
    rig.run("ctl:431").unwrap();
    assert_eq!(bytes(&rig, u, 20, 3), [1, 2, 3, 4]);
    assert_eq!(bytes(&rig, u, 20, 0), other, "only the combo's channel");
    rig.run("ctl:432").unwrap();
    assert_eq!(bytes(&rig, u, 20, 3), [20, 20, 107, 107]);
    assert_eq!(bytes(&rig, c, 10, 3), [1, 2, 3, 4], "unmarked keys stay");
    // The "all" entry resets the four channels.
    rig.update(|p| p.curve = 6);
    rig.run("ctl:432").unwrap();
    for ch in 0..4 {
        assert_eq!(bytes(&rig, u, 20, ch), [20, 20, 107, 107]);
    }
}

#[test]
fn the_curve_box_shows_and_drags_the_first_marked_key() {
    // DragInterpolationControlPoint (ui_selection_reeval.cpp:115): the start point is
    // interpolation[0 and 1][ch] of a camera key, the end point [2 and 3][ch]; the point is
    // clamped to 0..127 and 'all' (6 and up) shows channel 0.
    let mut rig = Rig::replay("camera", 10);
    let camera = global(GlobalTrack::Camera);
    rig.editor
        .apply(mds_doc::Command::ClearKeySelection)
        .unwrap();
    assert_eq!(timeline::curve_points(&rig.editor.doc, 2), None);
    timeline::click_cell(&mut rig.ctx(), camera, 30, false).unwrap();
    rig.update(|p| p.curve = 2);
    timeline::drag_curve_point(&mut rig.ctx(), false, [5, 6]).unwrap();
    timeline::drag_curve_point(&mut rig.ctx(), true, [-3, 300]).unwrap();
    let key = (rig.editor.doc.pmm.camera.records().iter())
        .find(|(_, k)| k.frame == 30)
        .unwrap()
        .1
        .clone();
    assert_eq!([key.interpolation[0][2], key.interpolation[1][2]], [5, 6]);
    assert_eq!([key.interpolation[2][2], key.interpolation[3][2]], [0, 127]);
    assert_eq!(
        timeline::curve_points(&rig.editor.doc, 2),
        Some([[5, 6], [0, 127]])
    );
    assert_eq!(
        timeline::curve_points(&rig.editor.doc, 6),
        Some([
            [key.interpolation[0][0], key.interpolation[1][0]],
            [key.interpolation[2][0], key.interpolation[3][0]]
        ])
    );
}

#[test]
fn name_clicks_select_rows() {
    let mut rig = Rig::replay("bones", 12);
    let (c, u) = (rig.bone("センター"), rig.bone("上半身"));
    let click = |rig: &mut Rig, t, shift| {
        let row = rig.row(t);
        timeline::click_name(&mut rig.ctx(), &row, shift).unwrap();
    };
    click(&mut rig, Track::Bone(c), false);
    assert_eq!(selected(&rig), vec![c]);
    click(&mut rig, Track::Bone(u), true);
    assert_eq!(selected(&rig), vec![u, c]);
    click(&mut rig, Track::Bone(u), true);
    assert_eq!(selected(&rig), vec![c]);
    click(&mut rig, Track::Bone(u), false);
    assert_eq!(selected(&rig), vec![u]);
    // The display row toggles (`displayKeyframesPresent`, ui_editor_click.cpp:447).
    click(&mut rig, Track::Display, false);
    assert!(rig.panel().display_row);
    click(&mut rig, Track::Display, false);
    assert!(!rig.panel().display_row);
}

fn selected(rig: &Rig) -> Vec<u32> {
    let m = &rig.editor.doc.pmm.models[0];
    let mut v: Vec<u32> = (0..m.bone_pose.len() as u32)
        .filter(|&b| m.bone_pose[b as usize].flags[2] != 0)
        .collect();
    if let Some(at) = v
        .iter()
        .position(|&b| b as i32 == m.selection.selected_bone)
    {
        v.swap(0, at);
    }
    v
}

#[test]
fn a_morph_name_selects_the_morph_of_its_lane() {
    // morph4.pmx: まばたき is in lane 1 (eye) and あ in lane 2 (lip), as morphs.txt lines 6 and 7.
    let mut rig = Rig::replay("morphs", 5);
    let (blink, a) = (rig.morph("まばたき"), rig.morph("あ"));
    for (n, lane) in [(blink, 1), (a, 2)] {
        let row = rig.row(Track::Morph(n));
        timeline::click_name(&mut rig.ctx(), &row, false).unwrap();
        assert_eq!(
            rig.editor.doc.pmm.models[0].selection.selected_morphs[lane],
            n as i32
        );
    }
}

#[test]
fn a_header_folds_its_group_and_only_the_view() {
    let mut rig = Rig::replay("bones", 12);
    let before = rig.save();
    let doc = &rig.editor.doc;
    let all = timeline::rows(doc, &[]);
    let header = all
        .iter()
        .find(|r| matches!(r.kind, RowKind::Header(g) if g != timeline::MORPHS))
        .unwrap()
        .clone();
    timeline::click_name(&mut rig.ctx(), &header, false).unwrap();
    let folded = rig.panel().folded;
    let rows = timeline::rows(&rig.editor.doc, &folded);
    assert!(rows.len() < all.len());
    assert!(rows.contains(&header));
    assert_bytes("fold", &rig.save(), &before);
    timeline::click_name(&mut rig.ctx(), &header, false).unwrap();
    assert!(rig.panel().folded.is_empty());
}

#[test]
fn the_plus_square_registers_the_row() {
    // bones.txt line 8 `register bone`, morphs.txt line 10 `register morph 1`.
    let mut by_script = rig::runner("bones", 8);
    let mut rig = Rig::replay("bones", 7);
    let c = rig.bone("センター");
    let row = rig.row(Track::Bone(c));
    timeline::click_plus(&mut rig.ctx(), &row).unwrap();
    assert_bytes("register bone", &rig.save(), &by_script.doc.save().unwrap());

    by_script = rig::runner("morphs", 10);
    let mut rig = Rig::replay("morphs", 9);
    let row = rig.row(Track::Morph(rig.morph("まばたき")));
    timeline::click_plus(&mut rig.ctx(), &row).unwrap();
    assert_bytes(
        "register morph",
        &rig.save(),
        &by_script.doc.save().unwrap(),
    );
}

#[test]
fn keyframe_jumps_follow_the_selected_rows() {
    // JumpNextKeyframe and JumpPrevKeyframe (app_utilities.cpp:352, :571) over the selected bones.
    let mut rig = Rig::replay("bones", 12);
    let (c, u) = (rig.bone("センター"), rig.bone("上半身"));
    let pick = |rig: &mut Rig, t| {
        let row = rig.row(t);
        timeline::click_name(&mut rig.ctx(), &row, false).unwrap();
    };
    rig.goto(0);
    pick(&mut rig, Track::Bone(c));
    rig.run("ctl:532").unwrap();
    assert_eq!(rig.editor.current_frame(), 10);
    // No later key: the frame stays.
    rig.run("key:Ctrl+Right").unwrap();
    assert_eq!(rig.editor.current_frame(), 10);
    rig.run("ctl:533").unwrap();
    assert_eq!(rig.editor.current_frame(), 0);
    // Previous with no earlier key goes to 0.
    rig.run("key:Ctrl+Left").unwrap();
    assert_eq!(rig.editor.current_frame(), 0);
    // Two rows: the nearest key of either.
    rig.goto(10);
    pick(&mut rig, Track::Bone(c));
    let row = rig.row(Track::Bone(u));
    timeline::click_name(&mut rig.ctx(), &row, true).unwrap();
    rig.run("ctl:532").unwrap();
    assert_eq!(rig.editor.current_frame(), 20);
    rig.run("ctl:533").unwrap();
    assert_eq!(rig.editor.current_frame(), 10);
    assert_eq!(rig.editor.physics_opens, 1);
}

#[test]
fn up_and_down_walk_the_displayed_bones() {
    let mut rig = Rig::replay("bones", 12);
    let order: Vec<u32> = timeline::rows(&rig.editor.doc, &[])
        .iter()
        .filter_map(|r| match r.kind {
            RowKind::Bone(b) => Some(b),
            _ => None,
        })
        .collect();
    let first = order[0];
    let row = rig.row(Track::Bone(first));
    timeline::click_name(&mut rig.ctx(), &row, false).unwrap();
    // The first bone has no previous one (SelectPreviousDisplayBone: the root stays).
    rig.run("key:Up").unwrap();
    assert_eq!(selected(&rig), vec![first]);
    for &b in &order[1..] {
        rig.run("key:Down").unwrap();
        assert_eq!(selected(&rig), vec![b]);
    }
    rig.run("key:Down").unwrap();
    assert_eq!(selected(&rig), vec![*order.last().unwrap()]);
    rig.run("key:Up").unwrap();
    assert_eq!(selected(&rig), vec![order[order.len() - 2]]);
}

#[test]
fn up_and_down_walk_the_camera_mode_targets() {
    let mut rig = Rig::replay("camera", 4);
    assert_eq!(rig.panel().global_rows, [true, false, false, false]);
    let order = [
        [false, true, false, false],
        [false, false, true, false],
        [false, false, false, true],
    ];
    for want in order {
        rig.run("key:Down").unwrap();
        assert_eq!(rig.panel().global_rows, want);
    }
    for want in [order[1], order[0], [true, false, false, false]] {
        rig.run("key:Up").unwrap();
        assert_eq!(rig.panel().global_rows, want);
    }
}

#[test]
fn rows_and_scopes_by_mode() {
    let rig = Rig::replay("camera", 4);
    let rows = timeline::rows(&rig.editor.doc, &[]);
    assert_eq!(
        rows[..4].iter().map(|r| r.kind.clone()).collect::<Vec<_>>(),
        [
            RowKind::Global(GlobalTrack::Camera),
            RowKind::Global(GlobalTrack::Light),
            RowKind::Global(GlobalTrack::SelfShadow),
            RowKind::Global(GlobalTrack::Gravity),
        ]
    );
    assert_eq!(timeline::scopes(&rig.editor.doc).len(), rows.len());
    let rig = Rig::replay("bones", 12);
    assert_eq!(timeline::scopes(&rig.editor.doc).len(), 5);
    let rows = timeline::rows(&rig.editor.doc, &[]);
    assert_eq!(rows[0].kind, RowKind::Display);
    let bones = rows
        .iter()
        .filter(|r| matches!(r.kind, RowKind::Bone(_)))
        .count();
    assert!(bones > 0 && bones <= rig.editor.doc.pmm.models[0].bone_names.len());
}

#[test]
fn hit_testing_keeps_the_name_column_and_strip_in_place() {
    let scroll = Vec2::new(5.0 * timeline::CELL, 2.0 * timeline::ROW);
    let at = |x: f32, y: f32| timeline::hit(Vec2::new(x, y), scroll, 10);
    assert_eq!(at(timeline::NAME + 1.0, 3.0), Hit::Strip(5));
    assert_eq!(at(10.0, 3.0), Hit::None);
    assert_eq!(
        at(timeline::NAME + 1.0, timeline::HEAD + 1.0),
        Hit::Cell { row: 2, frame: 5 }
    );
    assert_eq!(
        at(
            timeline::NAME + 2.5 * timeline::CELL,
            timeline::HEAD + 3.5 * timeline::ROW
        ),
        Hit::Cell { row: 5, frame: 7 }
    );
    assert_eq!(
        at(timeline::PLUS + 1.0, timeline::HEAD + 1.0),
        Hit::Name {
            row: 2,
            plus: false
        }
    );
    assert_eq!(
        at(1.0, timeline::HEAD + 1.0),
        Hit::Name { row: 2, plus: true }
    );
    assert_eq!(
        at(timeline::NAME + 1.0, timeline::HEAD + 8.0 * timeline::ROW),
        Hit::None
    );
}

/// Draws the area in a headless egui pass: the painting must not panic in any mode.
fn draw(rig: &mut Rig) {
    let egui = rig.egui.clone();
    let mut ctx = rig.ctx();
    egui.run_ui(egui::RawInput::default(), |ui| {
        timeline::pass(ui, &mut ctx);
        timeline::show(ui, &mut ctx);
    })
    .drop_without_applying_deltas();
}

#[test]
fn the_area_draws_in_every_mode() {
    for mut rig in [
        Rig::replay("bones", 12),
        Rig::replay("morphs", 24),
        Rig::replay("camera", 24),
        Rig::of(mds_doc::Document::startup()),
        Rig::open("swing600.pmm"),
    ] {
        draw(&mut rig);
        draw(&mut rig);
    }
    let mut rig = Rig::open("swing600.pmm");
    rig.run("ctl:408").unwrap();
    rig.editor.pump(500).unwrap();
    draw(&mut rig);
    draw(&mut rig);
}

#[test]
fn a_ctx_without_egui_reads_the_defaults() {
    let mut rig = Rig::replay("morphs", 24);
    let mut status = String::new();
    let mut ctx = Ctx {
        editor: &mut rig.editor,
        now_ms: 0,
        egui: None,
        viewport: None,
        status: &mut status,
    };
    // Go to frame 0 with the default edit, and the row defaults select the camera.
    assert_eq!(timeline::panel(&ctx), timeline::Panel::default());
    actions::run(&mut ctx, "ctl:553").unwrap();
    assert_eq!(ctx.editor.current_frame(), 0);
}
