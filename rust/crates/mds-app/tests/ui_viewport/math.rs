use super::close;
use mds_app::ui::viewport::{
    self, drag_mode, local_axes, next_coordinate, pick, project, selection_list, tool_at,
    BoneState, Hit, Pointer,
};
use mds_math::Mat4;
use mds_doc::CameraControls as Camera;

fn camera() -> Camera {
    Camera {
        target: [1.0, 10.0, -2.0],
        rotation: [0.3, -0.7, 0.0],
        distance: -45.0,
        fov_deg: 30.0,
        orthographic: false,
    }
}

/// `ProjectBonePoint` (`sprite_overlay.cpp:87..108`): the camera target lands on the integer
/// centre `(left + right) / 2`; up on screen is smaller y; a point behind the eye has none.
#[test]
fn projection_follows_project_bone_point() {
    let c = camera();
    let view = render(c).view(801, 601);
    let (p, w) = project(&view, [801, 601], c.target).unwrap();
    assert_eq!(p, [400, 300]);
    assert!((w - 45.0).abs() < 1e-3, "clip w is the depth: {w}");
    let up = Camera {
        rotation: [0.0; 3],
        ..c
    };
    let view = render(up).view(800, 600);
    let ([_, y], _) = project(&view, [800, 600], [1.0, 11.0, -2.0]).unwrap();
    assert!(y < 300, "{y}");
    assert!(project(&view, [800, 600], [1.0, 10.0, -100.0]).is_none());
}

fn hit(edit_mode: i32, camera_mode: bool) -> Hit {
    Hit {
        size: [800, 600],
        camera_mode,
        playing: false,
        edit_mode,
        center: Some([300, 300]),
        dragging: false,
    }
}

/// `ViewportToolAtPoint` (`frame_modes.cpp:115..223`), each zone at its open bounds.
#[test]
fn tool_zones_follow_viewport_tool_at_point() {
    let model = hit(0, false);
    // View tools (`:131..136`, moved into the picture's top 25 points).
    assert_eq!(tool_at(&model, 741, 12), 1);
    assert_eq!(tool_at(&model, 740, 12), 0);
    assert_eq!(tool_at(&model, 793, 24), 2);
    assert_eq!(tool_at(&model, 793, 25), 0);
    // Corner rows (`:147..177`): model 9..14, camera 15..20.
    for (x, column) in [(674, 0), (707, 0), (715, 1), (753, 2), (786, 2)] {
        assert_eq!(tool_at(&model, x, 521), 9 + column, "{x}");
        assert_eq!(tool_at(&model, x, 589), 12 + column, "{x}");
        assert_eq!(tool_at(&hit(0, true), x, 549), 18 + column, "{x}");
        assert_eq!(tool_at(&hit(0, true), x, 561), 15 + column, "{x}");
    }
    assert_eq!(tool_at(&model, 673, 535), 0);
    assert_eq!(tool_at(&model, 690, 555), 0, "between the rows");
    // Coordinate tool (`:209..215`), not while a drag runs.
    assert_eq!(tool_at(&model, 681, 496), 21);
    assert_eq!(tool_at(&model, 704, 519), 21);
    assert_eq!(tool_at(&model, 705, 519), 0);
    let dragging = Hit {
        dragging: true,
        ..model
    };
    assert_eq!(tool_at(&dragging, 690, 505), 0);
    // Rotate gizmo (`:180..197`) about the centre (300, 300).
    let rotate = hit(3, false);
    assert_eq!(tool_at(&rotate, 308, 306), 3);
    assert_eq!(tool_at(&rotate, 266, 294), 3);
    assert_eq!(tool_at(&rotate, 307, 300), 0, "inside 7 pixels");
    assert_eq!(tool_at(&rotate, 306, 334), 4);
    assert_eq!(tool_at(&rotate, 340, 300), 5, "ring");
    assert_eq!(
        tool_at(&rotate, 335, 300),
        0,
        "35 is not past the ring's 1225"
    );
    assert_eq!(tool_at(&rotate, 345, 300), 0);
    // Move gizmo (`:198..207`).
    let mv = hit(4, false);
    assert_eq!(tool_at(&mv, 342, 307), 6);
    assert_eq!(tool_at(&mv, 307, 240), 7);
    assert_eq!(tool_at(&mv, 288, 285), 8);
    assert_eq!(tool_at(&mv, 310, 307), 8);
    assert_eq!(tool_at(&mv, 311, 300), 0);
    assert_eq!(
        tool_at(&hit(0, false), 342, 307),
        0,
        "no gizmo in bone mode"
    );
    // Playback leaves the view tools only (`:144`).
    let playing = Hit {
        playing: true,
        ..rotate
    };
    assert_eq!(tool_at(&playing, 340, 300), 0);
    assert_eq!(tool_at(&playing, 690, 535), 0);
    assert_eq!(tool_at(&playing, 750, 12), 1);
}

/// `kDragMode` (`frame_modes.cpp:338`) and the coordinate wrap (`:364..367`).
#[test]
fn drag_modes_and_coordinate_targets() {
    let modes: Vec<u8> = (0..=21).map(drag_mode).collect();
    assert_eq!(
        modes,
        [0, 0, 0, 1, 2, 3, 7, 8, 9, 4, 5, 6, 10, 11, 12, 13, 14, 15, 16, 17, 18, 0]
    );
    assert_eq!(
        (0..3).map(|c| next_coordinate(c, true)).collect::<Vec<_>>(),
        [1, 2, 0]
    );
    assert_eq!(next_coordinate(1, false), 0);
    assert_eq!(
        next_coordinate(2, false),
        0,
        "a camera-mode 2 wraps in model mode"
    );
}

fn bone(name: &[u8], position: [f32; 3], tail: i32) -> BoneState {
    BoneState {
        parent: -1,
        flags: 0x0008,
        position,
        tail_bone: tail,
        name: name.to_vec(),
        mat_init: Mat4::IDENTITY.0,
        mat_world: Mat4::IDENTITY.0,
        rotation: [0.0, 0.0, 0.0, 1.0],
        ..Default::default()
    }
}

fn rig(bones: Vec<BoneState>, selected: i32, pmx: bool) -> viewport::Rig {
    viewport::Rig {
        pmx,
        physics_mode: 2,
        selected_bone: selected,
        bones,
    }
}

/// `BoneLocalAxes` (`frame_modes_bone.cpp:318..370`): PMX local axes give the rows `a` (X),
/// `c` and `e` of the C++ crosses; an arm name gives the 2D bone direction; anything else is the
/// identity.
#[test]
fn local_axes_follow_bone_local_axes() {
    // 左腕 pointing down-left to its tail.
    let arm = rig(
        vec![
            bone(b"\x8D\xB6\x98\x72", [0.0, 0.0, 0.0], 1),
            bone(b"tail", [-3.0, -4.0, 0.0], 0),
        ],
        0,
        false,
    );
    let m = local_axes(&arm);
    close(&m[..2], &[-0.6, -0.8], "x row");
    close(&m[4..6], &[0.8, -0.6], "y row");
    assert_eq!(m[10], 1.0);
    // 左腕先 is not an exact match, but a finger (指) anywhere is.
    let other = rig(
        vec![
            bone(b"\x8D\xB6\x98\x72\x90\xE6", [0.0; 3], 1),
            bone(b"t", [1.0, 0.0, 0.0], 0),
        ],
        0,
        false,
    );
    assert_eq!(local_axes(&other), Mat4::IDENTITY.0);
    let finger = rig(
        vec![
            bone(b"\x89\x45\x90\x65\x8E\x77\x82\x50", [0.0; 3], 1),
            bone(b"t", [0.0, 2.0, 0.0], 0),
        ],
        0,
        false,
    );
    close(&local_axes(&finger)[..2], &[0.0, 1.0], "finger");
    // PMX local axes X = (0, 0, 2), Z = (1, 0, 0).
    let mut b = bone(b"x", [0.0; 3], -1);
    b.local_axes = [0.0, 0.0, 2.0, 1.0, 0.0, 0.0];
    let m = local_axes(&rig(vec![b.clone()], 0, true));
    close(&m[..3], &[0.0, 0.0, 1.0], "a");
    // c = (b1 a2 - b2 a1, b2 a0 - b0 a2, b0 a1 - b1 a0) = (0, -1, 0), negated (0, 1, 0).
    close(&m[4..7], &[0.0, 1.0, 0.0], "c");
    // e = (c2 a1 - c1 a2, a2 c0 - c2 a0, a0 c1 - c0 a1) = (-1, 0, 0).
    close(&m[8..11], &[-1.0, 0.0, 0.0], "e");
    assert_eq!(
        local_axes(&rig(vec![b], 0, false)),
        Mat4::IDENTITY.0,
        "PMD ignores them"
    );
    assert_eq!(local_axes(&rig(vec![], -1, true)), Mat4::IDENTITY.0);
}

/// The pick's filters (`frame_modes.cpp:421..425`): hidden bones, types 7 and 9, and rigid-body
/// bones in physics mode 1, or mode 2 unless their physics is off.
#[test]
fn the_pick_skips_hidden_tip_and_simulated_bones() {
    let at = |n: usize| vec![Some(([10, 10], 1.0)); n];
    let mut hidden = bone(b"a", [0.0; 3], -1);
    hidden.flags = 0;
    let mut tip = bone(b"b", [0.0; 3], -1);
    tip.kind = 7;
    let mut simulated = bone(b"c", [0.0; 3], -1);
    simulated.rigid = true;
    let mut off = simulated.clone();
    off.physics_disabled = true;
    let r = rig(vec![hidden, tip, simulated, off], -1, true);
    assert_eq!(
        pick(&r, &at(4), 12, 12, false),
        Some((vec![false, false, false, true], 3))
    );
    let mode1 = viewport::Rig {
        physics_mode: 1,
        ..r.clone()
    };
    assert_eq!(pick(&mode1, &at(4), 12, 12, false), None);
    assert_eq!(
        pick(&r, &at(4), 18, 10, false),
        None,
        "8 pixels is out of reach"
    );
}

#[test]
fn selection_lists_lead_with_the_selected_bone() {
    assert_eq!(selection_list(&[true, false, true, true], 2), [2, 0, 3]);
    assert_eq!(selection_list(&[true, false, true], -1), [0, 2]);
    assert_eq!(selection_list(&[false; 3], 1), Vec::<u32>::new());
}

/// `ModeCameraAdjust`'s Shift and Ctrl scales (`frame_modes.cpp:574..576`).
#[test]
fn camera_moves_scale_with_shift_and_ctrl() {
    for (shift, ctrl, step) in [
        (false, false, 0.05),
        (true, false, 0.5),
        (false, true, 0.005),
    ] {
        let mut c = Camera {
            rotation: [0.0; 3],
            ..camera()
        };
        let p = Pointer {
            prev: [0, 0],
            cur: [0, 10],
            shift,
            ctrl,
            ..Default::default()
        };
        viewport::camera_move(&mut c, 1, &p, true);
        close(&c.target, &[1.0, 10.0 + 10.0 * step, -2.0], "global Y");
    }
}

#[test]
fn model_view_projection_keeps_the_reference_and_camera_mode_ignores_offsets() {
    let mut doc = mds_doc::Document::startup();
    let c = camera();
    doc.pmm.camera_state[3] = 1.5;
    doc.pmm.camera_state[4] = -0.75;
    for (mode, follow, offset) in [(0, 0, [1.5, -0.75]), (1, 0, [0.0; 2]), (0, 1, [0.0; 2])] {
        doc.pmm.settings.options[0] = mode;
        doc.pmm.appearance.follow_camera = follow;
        for reference in 0..=2 {
            doc.pmm.timeline.camera_reference_mode = reference;
            let view = mds_app::scene::view(&doc, &render(c), [640, 360]);
            let expected = render(c).view_with_offset(offset, 640, 360);
            for point in [c.target, [0.0; 3], [3.0, 5.0, 7.0]] {
                assert_eq!(view.clip(point), expected.clip(point));
            }
        }
    }
}

fn render(c: Camera) -> mds_render::CameraFrame { mds_render::Camera { target: c.target, rotation: c.rotation, distance: c.distance, fov_deg: c.fov_deg, orthographic: c.orthographic }.into() }
