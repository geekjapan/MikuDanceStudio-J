use crate::rig::Rig;
use egui::{Color32, Shape};
use mds_app::ui::physics::{self, body_matrix, segments, world_poses};
use mds_app::ui::Ctx;

/// The bone-derived `BuildFollowMatrix` (`mds-physics`) is the pose Bullet has for a body the
/// bone drives or follows; a body of mode 2 keeps only the bone's rotation (the readback drops its
/// translation, `ModelPhysicsReadback`), which is why the overlay reads the world's poses.
#[test]
fn the_world_poses_are_the_bone_poses_except_for_mode_2() {
    let mut r = Rig::open("swing600.pmm");
    let (mut compared, mut apart) = (0, 0.0f32);
    for n in 0..40 {
        r.editor.physics.tick(1.0 / 30.0).unwrap();
        if n % 13 != 12 {
            continue;
        }
        let poses = world_poses(&r.editor);
        for model in &r.editor.physics.scene.models {
            for (i, rigid) in model.rigids.iter().enumerate() {
                let world = poses[&(model.slot, i)];
                let bone = body_matrix(model, rigid);
                let worst = (0..16)
                    .map(|c| (world.0[c] - bone.0[c]).abs())
                    .fold(0.0, f32::max);
                if rigid.mode == 2 {
                    apart = apart.max(worst);
                } else {
                    assert!(worst < 2e-3, "slot {} body {i} at {n}: {worst}", model.slot);
                    compared += 1;
                }
            }
        }
    }
    assert!(compared > 50, "{compared}");
    assert!(apart > 0.05, "no mode 2 body left its bone: {apart}");
}

/// Sphere: 3 rings of 16 lines; box: 12 edges; capsule: 2 spheres and 4 lines
/// (`DrawSphere`, `DrawBox`, `DrawCapsule`, `debug_geometry.cpp:70` to `:123`).
fn lines_of(shape: u8) -> usize {
    [48, 12, 100][shape as usize]
}

#[test]
fn the_wire_frames_have_the_lines_of_each_shape_and_the_colour_of_the_mass() {
    let r = Rig::open("swing600.pmm");
    let (mut all, mut dynamic) = (0, 0);
    for m in &r.editor.physics.scene.models {
        for rigid in &m.rigids {
            all += lines_of(rigid.shape);
            if rigid.static_flag == 0 && rigid.mass > 0.0 {
                dynamic += lines_of(rigid.shape);
            }
        }
    }
    let lines = segments(&r.editor, [640, 480]);
    assert_eq!(lines.len(), all);
    assert_eq!(lines.iter().filter(|s| s.dynamic).count(), dynamic);
    assert!(dynamic > 0 && dynamic < all);
    assert!(segments(&r.editor, [0, 480]).is_empty());
}

/// The camera is orthographic and 45 units wide: moving it 5 units right moves every line 5 units
/// left in the picture, 10 pixels per unit at 450 pixels.
#[test]
fn a_body_is_drawn_where_the_camera_sees_it() {
    let mut r = Rig::open("swing600.pmm");
    let size = [450, 450];
    let at = |r: &Rig| {
        let lines = segments(&r.editor, size);
        let xs: Vec<i32> = lines.iter().flat_map(|s| [s.from[0], s.to[0]]).collect();
        (*xs.iter().min().unwrap(), *xs.iter().max().unwrap())
    };
    let (lo, hi) = at(&r);
    assert!(lo > 0 && hi < size[0], "{lo} {hi}");
    r.editor.camera.target[0] += 5.0;
    let (lo2, hi2) = at(&r);
    // The camera moved right, so the picture moves left by 5 units = 50 pixels.
    assert!((49..=51).contains(&(lo - lo2)) && (49..=51).contains(&(hi - hi2)));
}

#[test]
fn pass_paints_the_bodies_over_the_picture_the_viewport_area_allocated() {
    let mut r = Rig::open("swing600.pmm");
    r.run("menu:264").unwrap();
    let screen = egui::Rect::from_min_size(egui::pos2(0.0, 0.0), egui::vec2(800.0, 600.0));
    let (red, green) = (Color32::from_rgb(255, 0, 0), Color32::from_rgb(155, 255, 0));
    let mut painted = Vec::new();
    for _ in 0..3 {
        let mut picture = egui::Rect::NOTHING;
        let input = egui::RawInput {
            screen_rect: Some(screen),
            ..Default::default()
        };
        let mut out = r.egui.clone().run_ui(input, |ui| {
            let mut ctx = Ctx {
                editor: &mut r.editor,
                now_ms: 0,
                egui: Some(ui.ctx().clone()),
                viewport: None,
                status: &mut r.status,
            };
            physics::pass(ui, &mut ctx);
            // The timeline's strip: larger than the picture, and it runs off the window.
            egui::Panel::bottom("strip").show(ui, |ui| {
                ui.allocate_exact_size(egui::vec2(9000.0, 150.0), egui::Sense::click_and_drag());
            });
            egui::CentralPanel::default().show(ui, |ui| {
                picture = ui
                    .allocate_exact_size(ui.available_size(), egui::Sense::click_and_drag())
                    .0;
            });
        });
        out.textures_delta.clear();
        painted = out
            .shapes
            .iter()
            .filter_map(|s| match &s.shape {
                Shape::LineSegment { points, stroke } if [red, green].contains(&stroke.color) => {
                    Some((points[0], stroke.color))
                }
                _ => None,
            })
            .collect();
        let size = [picture.width() as i32, picture.height() as i32];
        let expected = segments(&r.editor, size);
        if painted.len() == expected.len() {
            let first = expected[0];
            let at = picture.min + egui::vec2(first.from[0] as f32, first.from[1] as f32);
            assert!(painted.iter().any(|&(p, _)| p == at));
            assert!(painted.iter().any(|p| p.1 == red) && painted.iter().any(|p| p.1 == green));
            return;
        }
    }
    panic!("{} lines painted, never the wire frames", painted.len());
}

#[test]
fn nothing_is_painted_while_the_bodies_are_off() {
    let mut r = Rig::open("swing600.pmm");
    let screen = egui::Rect::from_min_size(egui::pos2(0.0, 0.0), egui::vec2(800.0, 600.0));
    for _ in 0..3 {
        let input = egui::RawInput {
            screen_rect: Some(screen),
            ..Default::default()
        };
        let mut out = r.egui.clone().run_ui(input, |ui| {
            let mut ctx = Ctx {
                editor: &mut r.editor,
                now_ms: 0,
                egui: Some(ui.ctx().clone()),
                viewport: None,
                status: &mut r.status,
            };
            physics::pass(ui, &mut ctx);
            egui::CentralPanel::default().show(ui, |ui| {
                ui.allocate_exact_size(ui.available_size(), egui::Sense::click_and_drag());
            });
        });
        out.textures_delta.clear();
        assert!(!out
            .shapes
            .iter()
            .any(|s| matches!(s.shape, Shape::LineSegment { .. })));
    }
}

#[test]
fn the_menu_draws_in_both_languages() {
    let mut r = Rig::open("swing600.pmm");
    for english in [false, true] {
        if english {
            r.run("menu:260").unwrap();
        }
        r.frame(vec![], physics::show);
    }
}
