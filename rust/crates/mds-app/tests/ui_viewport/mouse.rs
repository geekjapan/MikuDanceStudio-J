use super::*;
use mds_app::actions::{self, Handler};
use mds_app::ui::viewport::RecordTarget;

/// Every viewport row has an action.
#[test]
fn every_row_has_an_action() {
    for id in [
        "key:L",
        "mouse:bone-pick",
        "mouse:bone-box-select",
        "mouse:bone-drag",
        "mouse:record-drag",
        "mouse:shift-rmb-drag",
        "mouse:rmb-dblclick",
        "mouse:tool-view-dolly",
        "mouse:tool-coordinate-cycle",
        "mouse:tool-camera-rotate-z",
    ] {
        let a = actions::find(id).unwrap_or_else(|| panic!("{id}"));
        assert!(
            matches!(a.handler, Handler::Run(_) | Handler::Inline),
            "{id}"
        );
    }
}

/// Key L (`key_ladder.cpp:183..190`): `++coordinateSystem`, wrapping at 2 in model mode and at 3
/// in camera mode.
#[test]
fn key_l_cycles_the_coordinate_target() {
    let mut r = Rig::new(startup());
    let mut seen = Vec::new();
    for _ in 0..4 {
        r.run("key:L");
        seen.push(r.state().coordinate);
    }
    assert_eq!(seen, [1, 2, 0, 1], "camera mode");
    let mut r = Rig::new(chain());
    let mut seen = Vec::new();
    for _ in 0..3 {
        r.run("key:L");
        seen.push(r.state().coordinate);
    }
    assert_eq!(seen, [1, 0, 1], "model mode");
}

/// The coordinate tool (operation 21, `frame_modes.cpp:210` and `:363`): a click in the 25-pixel
/// cell at (right - 120, bottom - 105) steps it the same way.
#[test]
fn the_coordinate_tool_cycles_on_a_click() {
    let mut r = Rig::new(chain());
    r.click([800.0 - 110.0, 600.0 - 95.0], false);
    assert_eq!(r.state().coordinate, 1);
    r.click([800.0 - 110.0, 600.0 - 95.0], false);
    assert_eq!(r.state().coordinate, 0);
}

/// `PickBoneAtPoint` (`frame_modes.cpp:411..458`): a click within 8 pixels selects that bone
/// only; with Shift it toggles the bone and makes it `selectedBone`.
#[test]
fn a_click_picks_a_bone_and_shift_toggles() {
    let mut r = Rig::new(chain());
    assert_eq!(r.selection(), (vec![0], 0), "the load selects bone 0");
    let center = r.bone_at(1);
    r.click([center[0] + 3.0, center[1] - 4.0], false);
    assert_eq!(r.selection(), (vec![1], 1));
    let neck = r.bone_at(3);
    r.click(neck, true);
    assert_eq!(r.selection(), (vec![1, 3], 3));
    r.click([400.0, 100.0], false);
    assert_eq!(
        r.selection(),
        (vec![1, 3], 3),
        "a click on nothing keeps it"
    );
}

/// Overlapping markers: repeated plain clicks take the first bone after `selectedBone` and then
/// wrap (`frame_modes.cpp:440..450`); bones 5 to 7 have rigid bodies, which physics mode 2 hides
/// from the pick (`:424`). On a 100 x 80 viewport the chain is three pixels a bone.
#[test]
fn repeated_clicks_cycle_through_overlapping_bones() {
    let mut r = Rig::new(chain());
    let size = [100.0, 80.0];
    let at = {
        let rig = viewport::rig(&r.e).unwrap();
        let view = r.e.camera.view(100, 80);
        let s = viewport::screen(&rig, &view, [100, 80]);
        let ([x, y], _) = s[2].unwrap();
        [x as f32, y as f32]
    };
    let mut picked = Vec::new();
    for _ in 0..6 {
        for left in [KeyState::Pressed, KeyState::Released] {
            r.pass(viewport::Input {
                size,
                ..input(Some(at), left, false)
            });
        }
        picked.push(r.selection().1);
    }
    assert_eq!(picked, [1, 2, 3, 4, 0, 1]);
}

/// Box selection (edit mode 1, `frame_modes.cpp:377..381` and `UpdateBoneBoxSelection` `:298`):
/// bones strictly inside the box, rigid bodies included; Shift keeps the bones outside.
#[test]
fn a_box_selects_the_bones_inside() {
    let mut r = Rig::new(chain());
    r.apply(Command::SetEditMode(1));
    let (top, bottom) = (r.bone_at(4)[1] - 5.0, r.bone_at(1)[1] + 5.0);
    r.left_drag([380.0, top], &[[400.0, 300.0], [420.0, bottom]], false);
    assert_eq!(r.selection().0, [1, 2, 3, 4]);
    assert!(r.state().box_start.is_none(), "the release ends the box");
    r.select(&[0]);
    let top = r.bone_at(7)[1] - 5.0;
    r.left_drag([380.0, top], &[[420.0, r.bone_at(5)[1] + 5.0]], true);
    assert_eq!(r.selection().0, [0, 5, 6, 7], "Shift adds to bone 0");
}

/// `BoneEditModes` mode 1 (`frame_modes_bone.cpp:416..427`, the horizontal handle 7 to 35 pixels
/// either side of the gizmo, `frame_modes.cpp:185`): an unrotated camera gives the axis
/// `(w1, w5, w9)` of the identity `matWorld`, Y, and `dq = (sin a * axis, cos a)` with the full
/// angle `a = (prevX - x) * 0.005` (`:510..516`) multiplied onto the pose; Shift is 5 times.
#[test]
fn the_rotate_gizmo_turns_the_selected_bone() {
    let mut r = Rig::new(chain());
    r.apply(Command::SetEditMode(3));
    r.select(&[2]);
    let c = r.bone_at(2);
    r.left_drag([c[0] + 20.0, c[1]], &[[c[0] + 10.0, c[1]]], false);
    let a = (10.0f64 * 0.004999999888241291) as f32;
    close(&r.pose(2).1, &[0.0, a.sin(), 0.0, a.cos()], "mode 1");
    assert_eq!(r.e.doc.pmm.timeline.edit_mode, 3);

    let mut r = Rig::new(chain());
    r.apply(Command::SetEditMode(3));
    r.select(&[2]);
    r.left_drag([c[0] + 20.0, c[1]], &[[c[0] + 10.0, c[1]]], true);
    let a = (5.0 * f64::from(a)) as f32;
    close(&r.pose(2).1, &[0.0, a.sin(), 0.0, a.cos()], "Shift");
}

/// Mode 2, the vertical handle (`frame_modes_bone.cpp:428..438`): axis `(w0, w4, w8)`, X, angle
/// `(prevY - y) * 0.005`. The selected root bone 0 (type 1, no selected parent) turns too, about
/// the world point of the selected bone (`:524..548`): its translation becomes `r - off` with
/// `off` = (0, -2, 0) and `r` = `off` turned by `dq`, a turn of 2a about X.
#[test]
fn the_vertical_handle_turns_about_x_and_carries_the_selected_roots() {
    let mut r = Rig::new(chain());
    r.apply(Command::SetEditMode(3));
    r.select(&[2, 0]);
    let c = r.bone_at(2);
    r.left_drag([c[0], c[1] - 20.0], &[[c[0], c[1] - 32.0]], false);
    let a = (12.0f64 * 0.004999999888241291) as f32;
    let dq = [a.sin(), 0.0, 0.0, a.cos()];
    close(&r.pose(2).1, &dq, "selected bone");
    let (t, q) = r.pose(0);
    close(&q, &dq, "root rotation");
    let phi = 2.0 * a;
    close(
        &t,
        &[0.0, -2.0 * phi.cos() + 2.0, -2.0 * phi.sin()],
        "root translation",
    );
}

/// Mode 3, the ring 35 to 45 pixels out (`frame_modes.cpp:194`, `frame_modes_bone.cpp:439..460`):
/// the angle is half the change of `atan2(dx, dy)` about the centre where the drag began; the
/// unrotated camera's view axis is Z.
#[test]
fn the_ring_turns_in_the_view_plane() {
    let mut r = Rig::new(chain());
    r.apply(Command::SetEditMode(3));
    r.select(&[2]);
    let c = r.bone_at(2);
    r.left_drag([c[0] + 40.0, c[1]], &[[c[0], c[1] + 40.0]], false);
    let ang = (0.0f64 * 0.5) as f32 - ((std::f64::consts::FRAC_PI_2) * 0.5) as f32;
    close(&r.pose(2).1, &[0.0, 0.0, ang.sin(), ang.cos()], "mode 3");
}

/// The move gizmo (`frame_modes.cpp:198..207`) and `ApplyScreenPlaneBoneMove`
/// (`frame_modes_bone.cpp:234..278`): the upper handle moves the selected roots up by
/// `(prevY - y) * clipW / height * 1.05` (perspective), the right handle sideways by
/// `(x - prevX) * clipW / width * width / height`. Clip w of the centre bone is 45 here.
#[test]
fn the_move_gizmo_moves_the_selected_root_bones() {
    let mut r = Rig::new(chain());
    r.apply(Command::SetEditMode(4));
    r.select(&[1]);
    let c = r.bone_at(1);
    r.left_drag([c[0], c[1] - 50.0], &[[c[0], c[1] - 60.0]], false);
    let up = (10.0 * 45.0 / 600.0 * 1.05f64) as f32;
    close(&r.pose(1).0, &[0.0, up, 0.0], "upper handle");

    let mut r = Rig::new(chain());
    r.apply(Command::SetEditMode(4));
    r.select(&[1]);
    r.left_drag([c[0] + 50.0, c[1]], &[[c[0] + 60.0, c[1]]], false);
    let side = (10.0 * 45.0 / 800.0 * (800.0 / 600.0f64)) as f32;
    close(&r.pose(1).0, &[side, 0.0, 0.0], "right handle");
    assert_eq!(r.pose(1).1, [0.0, 0.0, 0.0, 1.0]);
}

/// The model tool rows (`frame_modes.cpp:147..177`, operations 9..14): the upper row X turns the
/// selected bone about its local X (mode 4, `frame_modes_bone.cpp:461..487`, identity basis for a
/// bone without local axes); the lower row moves the selected roots along local X by
/// `(prevY - y) * 0.05` and along Z by `(y - prevY) * 0.05` (`:280..308`).
#[test]
fn the_model_tool_rows_turn_and_move_on_local_axes() {
    let mut r = Rig::new(chain());
    r.select(&[2]);
    r.left_drag([690.0, 535.0], &[[690.0, 525.0]], false);
    let a = (10.0f64 * 0.004999999888241291) as f32;
    close(&r.pose(2).1, &[a.sin(), 0.0, 0.0, a.cos()], "upper X");

    let mut r = Rig::new(chain());
    r.select(&[1]);
    r.left_drag([690.0, 575.0], &[[690.0, 565.0]], false);
    close(&r.pose(1).0, &[0.5, 0.0, 0.0], "lower X");
    r.left_drag([770.0, 575.0], &[[770.0, 565.0]], false);
    close(&r.pose(1).0, &[0.5, 0.0, -0.5], "lower Z");
}

/// The camera tool rows (`ModeCameraAdjust` `frame_modes.cpp:601..649`, `ModeAngleAdjust`
/// `:651..686`): the lower row moves the target by `dy * 0.05` along the camera's own axis
/// (`RotZ(-roll) * RotX(-pitch) * RotY(-yaw)`) or, with the coordinate target 1, the world axis;
/// the upper row adds `dy * 0.02` to the angle.
#[test]
fn the_camera_tool_rows_move_and_turn_the_camera() {
    let mut r = Rig::new(startup());
    r.e.camera.rotation = [0.0, std::f32::consts::FRAC_PI_2, 0.0];
    let start = r.e.camera.target;
    r.left_drag([690.0, 575.0], &[[690.0, 585.0]], false);
    let t = r.e.camera.target;
    close(
        &t,
        &[start[0], start[1], start[2] + 0.5],
        "local X with a quarter yaw is Z",
    );
    r.run("key:L");
    r.left_drag([690.0, 575.0], &[[690.0, 585.0]], false);
    close(&r.e.camera.target, &[t[0] + 0.5, t[1], t[2]], "global X");
    r.left_drag([730.0, 535.0], &[[730.0, 545.0]], false);
    close(
        &r.e.camera.rotation,
        &[0.0, std::f32::consts::FRAC_PI_2 + 0.2, 0.0],
        "yaw",
    );
}

/// With the coordinate target 2 in camera mode the same rows edit the selected accessory
/// (`frame_modes.cpp:618..627`, `:670..679`): position `-= dy * 0.05`, rotation `+= dy * 0.02`
/// radians.
#[test]
fn the_camera_tool_rows_edit_the_accessory_on_target_2() {
    let mut r = Rig::new(startup());
    let data = std::fs::read(fixtures().join("accessory/cube.x")).unwrap();
    r.apply(Command::LoadAccessory {
        path: "C:\\acc\\cube.x".into(),
        data,
    });
    let slot = r.e.doc.pmm.accessories[0].slot;
    r.apply(Command::SelectAccessory(slot));
    let camera = r.e.camera;
    r.run("key:L");
    r.run("key:L");
    r.left_drag([730.0, 575.0], &[[730.0, 585.0]], false);
    r.left_drag([770.0, 535.0], &[[770.0, 545.0]], false);
    let a = &r.e.doc.pmm.accessories[0].state;
    close(&a.position, &[0.0, -0.5, 0.0], "position Y");
    close(&a.rotation, &[0.0, 0.0, 0.2], "rotation Z");
    assert_eq!(r.e.camera.target, camera.target, "the camera stays");
}

/// The view tools (`frame_modes.cpp:131..136`, here in the top 25 points; `:525..538`): tool 1
/// dollies by `dy * 0.1`, tool 2 pans the camera target as the middle drag does.
#[test]
fn the_view_tools_dolly_and_pan() {
    let mut r = Rig::new(startup());
    r.left_drag([750.0, 12.0], &[[750.0, 22.0]], false);
    assert_eq!(r.e.camera.distance, -46.0);
    let mut want = r.e.camera;
    mds_app::navigation::middle_drag(&mut want, 4, -2, mds_app::navigation::Modifiers::default());
    r.left_drag([780.0, 12.0], &[[784.0, 10.0]], false);
    assert_eq!(r.e.camera.target, want.target);
}

/// `ConsumeRightButtonDrag` in model mode with Shift (`pump_navigation.cpp:330..334`):
/// `ViewOffsetY += dy * 0.1`, `ViewOffsetX -= dx * 0.1`, saved in `camera_state[3..5]`. The view
/// camera has no offsets; its target moves by the same amount along the camera's right and up
/// axes, which draws the same picture.
#[test]
fn shift_right_drag_pans_the_view_in_model_mode() {
    let mut r = Rig::new(chain());
    let start = r.e.camera;
    let (offset, modified) = (r.offset(), r.e.modified);
    r.pass(viewport::Input {
        right: KeyState::Held,
        pixels: [10, -4],
        ..input(Some([300.0, 300.0]), KeyState::Idle, true)
    });
    close(&r.offset(), &[offset[0] - 1.0, offset[1] - 0.4], "offsets");
    close(
        &r.e.camera.target,
        &[
            start.target[0] - 1.0,
            start.target[1] - 0.4,
            start.target[2],
        ],
        "pan",
    );
    assert_eq!(r.e.camera.rotation, start.rotation, "no orbit");
    assert_eq!(r.e.modified, modified, "a view change is not a scene edit");
}

/// The middle button in model mode (`ConsumeMiddleButtonPan`, `pump_navigation.cpp:376..380`):
/// `ViewOffsetY += dy * scale`, `ViewOffsetX -= dx * scale`, the scale 0.05, 0.5 with Shift and
/// 0.005 with Ctrl; and the pan tool (`frame_modes.cpp:530..537`, `DragScale`) the same.
#[test]
fn the_middle_button_and_the_pan_tool_write_the_view_offsets() {
    let mut r = Rig::new(chain());
    let (offset, modified) = (r.offset(), r.e.modified);
    let middle = |shift, ctrl| viewport::Input {
        middle: KeyState::Held,
        pixels: [10, -4],
        ctrl,
        ..input(Some([300.0, 300.0]), KeyState::Idle, shift)
    };
    r.pass(middle(false, false));
    close(&r.offset(), &[offset[0] - 0.5, offset[1] - 0.2], "plain");
    r.pass(middle(true, false));
    close(&r.offset(), &[offset[0] - 5.5, offset[1] - 2.2], "Shift");
    r.pass(middle(false, true));
    close(&r.offset(), &[offset[0] - 5.55, offset[1] - 2.22], "Ctrl");

    let mut r = Rig::new(chain());
    let offset = r.offset();
    r.left_drag([780.0, 12.0], &[[784.0, 10.0]], false);
    close(&r.offset(), &[offset[0] - 0.2, offset[1] - 0.1], "pan tool");
    assert_eq!(r.e.modified, modified);
}

/// In camera mode the same drags move the camera, and the saved offsets stay.
#[test]
fn the_camera_mode_pans_leave_the_view_offsets() {
    let mut r = Rig::new(startup());
    let offset = r.offset();
    r.pass(viewport::Input {
        middle: KeyState::Held,
        pixels: [10, -4],
        ..input(Some([300.0, 300.0]), KeyState::Idle, false)
    });
    assert_eq!(r.offset(), offset);
}

/// `HandleMouseActivate` (`ui_mouse_misc.cpp:284..355`): over the viewport in model mode, edit
/// mode bone select goes to none and anything else to bone select; in camera mode the model of
/// the combo comes back.
#[test]
fn a_right_double_click_switches_the_modes() {
    let mut r = Rig::new(chain());
    let dbl = viewport::Input {
        right_double_click: true,
        ..input(Some([300.0, 300.0]), KeyState::Idle, false)
    };
    r.pass(dbl);
    assert_eq!(r.e.doc.pmm.timeline.edit_mode, 2);
    r.pass(dbl);
    assert_eq!(r.e.doc.pmm.timeline.edit_mode, 0);
    r.apply(Command::SelectCameraMode);
    assert_ne!(r.e.doc.pmm.settings.options[0], 0);
    r.pass(dbl);
    assert_eq!(r.e.doc.pmm.settings.options[0], 0, "model mode again");
}

/// Playback disables the tools and the pick (`frame_modes.cpp:144`, `:369`).
#[test]
fn nothing_but_the_view_tools_while_playing() {
    let mut r = Rig::new(chain());
    r.apply(Command::SetEditMode(3));
    r.select(&[2]);
    let before = r.pose(2);
    let c = r.bone_at(2);
    r.run("ctl:408");
    r.left_drag([c[0] + 20.0, c[1]], &[[c[0] + 10.0, c[1]]], false);
    assert_eq!(r.pose(2), before);
    assert_eq!(r.selection(), (vec![2], 2));
}

/// `BeginOrEndViewportToolDrag` (`frame_modes.cpp:349..357`) pushes `PushBoneEditUndo` at the
/// press of a gizmo or a model tool row, not at each move: a drag of any length is one undo
/// entry, and one undo gives the pose back. A pose edit does not set `SceneModified`.
#[test]
fn a_bone_drag_is_one_undo_entry() {
    let cursor = |r: &Rig| r.e.doc.edit.models[0].history.cursor;
    let slots = mds_doc::history::SLOTS;
    for (name, drag) in [
        ("gizmo", [(0.0, 20.0), (-5.0, 20.0), (-10.0, 20.0)]),
        ("tool row", [(0.0, 0.0), (0.0, -4.0), (0.0, -10.0)]),
    ] {
        let mut r = Rig::new(chain());
        let (start, path): ([f32; 2], Vec<[f32; 2]>) = if name == "gizmo" {
            r.apply(Command::SetEditMode(3));
            r.select(&[2]);
            let c = r.bone_at(2);
            (
                [c[0] + 20.0, c[1]],
                drag.iter().map(|d| [c[0] + 20.0 + d.0, c[1]]).collect(),
            )
        } else {
            r.select(&[2]);
            (
                [690.0, 535.0],
                drag.iter().map(|d| [690.0 + d.0, 535.0 + d.1]).collect(),
            )
        };
        let (pose, entries, modified) = (r.pose(2), cursor(&r), r.e.modified);
        r.left_drag(start, &path, false);
        assert_ne!(r.pose(2), pose, "{name}: the bone turned");
        assert_eq!(cursor(&r), (entries + 1) % slots, "{name}: one entry");
        assert_eq!(r.e.modified, modified, "{name}");
        r.apply(Command::Undo);
        assert_eq!(r.pose(2), pose, "{name}: one undo undoes the drag");
    }
}

/// Two drags are two entries; a press that only picks a bone pushes none.
#[test]
fn each_drag_pushes_its_own_entry_and_a_pick_none() {
    let cursor = |r: &Rig| r.e.doc.edit.models[0].history.cursor;
    let mut r = Rig::new(chain());
    r.select(&[1]);
    let before = cursor(&r);
    r.left_drag([690.0, 575.0], &[[690.0, 565.0]], false);
    r.left_drag([690.0, 575.0], &[[690.0, 565.0]], false);
    assert_eq!(cursor(&r), before + 2);
    let c = r.bone_at(3);
    r.click(c, false);
    assert_eq!(cursor(&r), before + 2);
}

/// The record drag (`BoneEditModes`, `frame_modes_bone.cpp:373..378`) while the physics model
/// dialog is open (`physics_scratch`): the upper model row turns the selected record
/// (`EditModeRecord` `:158..177`, `value - dy * 0.01`), the lower one moves it
/// (`:194..222`, `value - dy * 0.05f`), with Shift a rigid body is resized and floored at 0.1,
/// and a joint has no size. The bones stay.
#[test]
fn the_model_rows_drag_the_selected_physics_record() {
    let mut r = Rig::new(chain_pmd());
    r.select(&[2]);
    let mds_doc::ModelFile::Pmd(pmd) = &r.e.doc.models[0] else {
        panic!("a PMD")
    };
    let phys = pmd.extension.as_ref().unwrap().physics.as_ref().unwrap();
    let (rigids, joints) = (phys.rigids.clone(), phys.joints.clone().unwrap());
    r.e.doc.edit.physics_scratch = Some((rigids.clone(), joints.clone()));
    let (pose, modified) = (r.pose(2), r.e.modified);
    let step = |v: f32, dy: i32, s: f64| (f64::from(v) - f64::from(dy) * s) as f32;
    let five = f64::from(0.05f32);
    let scratch = |r: &Rig| r.e.doc.edit.physics_scratch.clone().unwrap();

    r.with(|c| {
        viewport::set_record_target(
            c.egui.as_ref().unwrap(),
            Some(RecordTarget {
                joint: false,
                index: 1,
            }),
        )
    });
    // Upper row, Y (operation 10, mode 5): axis 1, dy = -10.
    r.left_drag([730.0, 535.0], &[[730.0, 525.0]], false);
    let (rs, _) = scratch(&r);
    assert_eq!(rs[1].rotation[1], step(rigids[1].rotation[1], -10, 0.01));
    // Lower row, Z (operation 14, mode 12): axis 2, dy = 4.
    r.left_drag([770.0, 575.0], &[[770.0, 579.0]], false);
    let (rs, _) = scratch(&r);
    assert_eq!(rs[1].position[2], step(rigids[1].position[2], 4, five));
    // With Shift the lower row resizes: X (mode 10), dy = 6, floored at 0.1 by a long drag.
    r.left_drag([690.0, 575.0], &[[690.0, 581.0]], true);
    let (rs, _) = scratch(&r);
    assert_eq!(rs[1].size[0], step(rigids[1].size[0], 6, five).max(0.1));
    r.left_drag([690.0, 575.0], &[[690.0, 1175.0]], true);
    assert_eq!(scratch(&r).0[1].size[0], 0.1);
    assert_eq!(scratch(&r).0[0], rigids[0], "only the selected body");
    assert_eq!(r.pose(2), pose, "the bones stay");
    assert_eq!(r.e.modified, modified);

    // The joint page: rotation and position, no size even with Shift.
    r.with(|c| {
        viewport::set_record_target(
            c.egui.as_ref().unwrap(),
            Some(RecordTarget {
                joint: true,
                index: 0,
            }),
        )
    });
    r.left_drag([690.0, 535.0], &[[690.0, 540.0]], false);
    r.left_drag([690.0, 575.0], &[[690.0, 580.0]], true);
    let (_, js) = scratch(&r);
    assert_eq!(js[0].rotation[0], step(joints[0].rotation[0], 5, 0.01));
    assert_eq!(js[0].position[0], step(joints[0].position[0], 5, five));
}

/// The rotate gizmo (modes 1 to 3) edits nothing while the dialog is open and the bones stay,
/// with no selected record nothing changes either, and the move gizmo (modes 7 to 9) still moves
/// the bones (`BoneEditModes` `:373..388`).
#[test]
fn the_gizmos_and_an_unselected_record() {
    let mut r = Rig::new(chain_pmd());
    r.apply(Command::SetEditMode(3));
    r.select(&[2]);
    let mds_doc::ModelFile::Pmd(pmd) = &r.e.doc.models[0] else {
        panic!("a PMD")
    };
    let phys = pmd.extension.as_ref().unwrap().physics.as_ref().unwrap();
    let both = (phys.rigids.clone(), phys.joints.clone().unwrap());
    r.e.doc.edit.physics_scratch = Some(both.clone());
    r.with(|c| {
        viewport::set_record_target(
            c.egui.as_ref().unwrap(),
            Some(RecordTarget {
                joint: false,
                index: 0,
            }),
        )
    });
    let pose = r.pose(2);
    let c = r.bone_at(2);
    r.left_drag([c[0] + 20.0, c[1]], &[[c[0] + 10.0, c[1]]], false);
    assert_eq!(r.pose(2), pose, "mode 1 turns nothing");
    assert!(r.e.doc.edit.physics_scratch.clone().unwrap() == both);

    r.with(|c| viewport::set_record_target(c.egui.as_ref().unwrap(), None));
    r.apply(Command::SetEditMode(1));
    r.left_drag([690.0, 535.0], &[[690.0, 525.0]], false);
    assert!(
        r.e.doc.edit.physics_scratch.clone().unwrap() == both,
        "no record"
    );
    assert_eq!(r.pose(2), pose, "and no bone");

    r.apply(Command::SetEditMode(4));
    r.select(&[1]);
    let moved = r.pose(1);
    let c = r.bone_at(1);
    r.left_drag([c[0], c[1] - 50.0], &[[c[0], c[1] - 60.0]], false);
    assert_ne!(r.pose(1).0, moved.0, "the move gizmo moves the bone");
}

/// Closing the dialog (`physics_scratch` gone) gives the bones their drags back.
#[test]
fn without_the_dialog_the_rows_drag_the_bones() {
    let mut r = Rig::new(chain_pmd());
    r.select(&[2]);
    let pose = r.pose(2);
    r.left_drag([690.0, 535.0], &[[690.0, 525.0]], false);
    assert_ne!(r.pose(2), pose);
}
