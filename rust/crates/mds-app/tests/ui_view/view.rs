use crate::labels;
use crate::rig::Rig;
use mds_app::actions::{self, Handler};
use mds_app::ui::view::{self, ViewOptions};
use mds_doc::Command;

type Field = fn(&ViewOptions) -> bool;

/// Every switch with the ids that flip it and the C++ handler that flips the flag.
const SWITCHES: &[(&[&str], Field, &str)] = &[
    (
        &["menu:211", "ctl:551"],
        |o| o.info,
        "command_dispatch.cpp:487, command_frame_register.cpp:835",
    ),
    (
        &["menu:215", "ctl:557"],
        |o| o.axes,
        "command_dispatch.cpp:528, command_frame_register.cpp:865",
    ),
    (
        &["menu:221"],
        |o| o.ground_shadow,
        "command_file_menu.cpp:1095",
    ),
    (
        &["menu:254"],
        |o| o.ground_shadow_transparent,
        "command_view_menu.cpp:853",
    ),
    (
        &["menu:279"],
        |o| o.self_shadow,
        "command_view_menu.cpp:1352",
    ),
    (
        &["menu:214", "key:V"],
        |o| o.transparent_models,
        "command_dispatch.cpp:514, key_ladder.cpp:79",
    ),
    (
        &["menu:283", "key:Shift+V"],
        |o| o.hide_models,
        "command_view_menu.cpp:1413, key_ladder.cpp:68",
    ),
    (&["menu:277"], |o| o.antialias, "command_view_menu.cpp:1327"),
    (&["menu:298"], |o| o.mipmap, "command_view_menu.cpp:1696"),
    (&["menu:287"], |o| o.wireframe, "command_view_menu.cpp:1500"),
    (
        &["menu:299", "ctl:552"],
        |o| o.low_power,
        "command_view_menu.cpp:1715, command_frame_register.cpp:849",
    ),
    (
        &["menu:280"],
        |o| o.separate_window,
        "command_view_menu.cpp:1367",
    ),
    (&["menu:281"], |o| o.on_top, "command_view_menu.cpp:1380"),
    (
        &["menu:290", "key:Alt+Enter"],
        |o| o.fullscreen,
        "command_view_menu.cpp:1540, pump_edit_keys.cpp:305",
    ),
];

#[test]
fn every_id_of_a_switch_flips_the_one_flag() {
    for (ids, field, at) in SWITCHES {
        let mut rig = Rig::new();
        for id in *ids {
            let before = field(&rig.options());
            rig.run(id).unwrap_or_else(|e| panic!("{id}: {e}"));
            assert_eq!(field(&rig.options()), !before, "{id} ({at})");
            rig.run(id).unwrap();
            assert_eq!(field(&rig.options()), before, "{id} twice ({at})");
        }
    }
}

#[test]
fn a_switch_changes_only_its_own_flag() {
    for (ids, _, _) in SWITCHES {
        let mut rig = Rig::new();
        let before = rig.options();
        rig.run(ids[0]).unwrap();
        let after = rig.options();
        let changed = SWITCHES
            .iter()
            .filter(|(_, f, _)| f(&before) != f(&after))
            .count();
        assert_eq!(changed, 1, "{}", ids[0]);
    }
}

/// `MDS_CMD_FPS_*` store 1000 (`flt_52FCE8`), 30 and 60 and check the one item
/// (`command_file_menu.cpp:1913` to `:1932`).
#[test]
fn the_fps_radio_stores_its_limit() {
    let mut rig = Rig::new();
    for (id, limit) in [
        ("menu:234", 1000.0),
        ("menu:235", 30.0),
        ("menu:236", 60.0),
        ("menu:235", 30.0),
    ] {
        rig.run(id).unwrap();
        assert_eq!(rig.options().fps_limit, limit, "{id}");
    }
}

/// The PMM values `ProcessLoaded` (pmm_load_v2.cpp:2098) reads into the flags: here the
/// fixtures' view block, which differs from the start-up scene's in `fps_limit`.
#[test]
fn opening_a_pmm_loads_the_flags_it_stores() {
    let mut rig = Rig::open("camera3.pmm");
    let p = &rig.editor.doc.pmm;
    let o = rig.options();
    assert_eq!(p.view.fps_limit, 30.0);
    assert_eq!(o.fps_limit, 30.0);
    assert_eq!(o.axes, p.view.ground_grid != 0);
    assert_eq!(o.ground_shadow, p.view.ground_shadow != 0);
    assert_eq!(o.info, p.view.fps_overlay != 0);
    assert_eq!(
        o.ground_shadow_transparent,
        p.physics.projected_shadow_blend != 0
    );
    assert_eq!(o.self_shadow, p.self_shadow_mode != 0);

    // New scene reloads those and keeps what no document stores.
    rig.run("menu:287").unwrap();
    rig.run("menu:290").unwrap();
    rig.run("menu:211").unwrap();
    rig.editor.apply(Command::NewScene).unwrap();
    let o = rig.options();
    let p = &rig.editor.doc.pmm;
    assert_eq!(o.fps_limit, p.view.fps_limit);
    assert_ne!(o.fps_limit, 30.0, "the start-up scene caps at 60");
    assert_eq!(o.info, p.view.fps_overlay != 0);
    assert!(o.wireframe && o.fullscreen);
}

/// `ApplyPlaybackMenus` greys 212 to 232 while playing; the display switches stay.
#[test]
fn the_switches_work_while_playing() {
    let mut rig = Rig::new();
    rig.editor.toggle_play(0).unwrap();
    assert!(rig.editor.playing());
    for (ids, field, _) in SWITCHES {
        let before = field(&rig.options());
        rig.run(ids[0]).unwrap();
        assert_ne!(field(&rig.options()), before, "{}", ids[0]);
    }
}

/// `PumpFullscreenKeys`: Alt+Enter flips full screen, Esc leaves it and does nothing otherwise.
#[test]
fn escape_leaves_full_screen_only() {
    let mut rig = Rig::new();
    rig.run("key:Esc@fullscreen").unwrap();
    assert!(!rig.options().fullscreen);
    rig.run("key:Alt+Enter").unwrap();
    assert!(rig.options().fullscreen);
    rig.run("key:Esc@fullscreen").unwrap();
    assert!(!rig.options().fullscreen);
}

/// `ui_scroll_mouse.cpp:108`: `FrameNormalization = 100 - TBM_GETPOS`, slider range 0 to 100.
#[test]
fn the_frame_volume_slider_stores_a_hundred_less_its_position() {
    let mut rig = Rig::new();
    assert_eq!(rig.options().frame_normalization, 100);
    for (position, stored) in [(30, 70), (0, 100), (100, 0), (250, 0)] {
        let mut ctx = mds_app::ui::Ctx {
            editor: &mut rig.editor,
            now_ms: 0,
            egui: rig.egui.clone(),
            viewport: None,
            status: &mut rig.status,
        };
        view::set_frame_volume(&mut ctx, position).unwrap();
        assert_eq!(
            rig.options().frame_normalization,
            stored,
            "position {position}"
        );
    }
}

#[test]
fn the_shadow_color_dialog_opens() {
    let mut rig = Rig::new();
    assert!(!rig.options().shadow_color_dialog);
    rig.run("menu:248").unwrap();
    assert!(rig.options().shadow_color_dialog);
}

#[test]
fn without_a_window_there_is_nowhere_to_keep_a_switch() {
    let mut rig = Rig::new();
    rig.egui = None;
    assert_eq!(rig.run("menu:211"), Err("no window".into()));
}

#[test]
fn the_labels_are_those_of_the_inventory() {
    labels::check("view", view::LABELS);
}

#[test]
fn the_area_registers_each_id_once_and_runs_what_it_can() {
    let ids: Vec<_> = view::actions().iter().map(|a| a.id).collect();
    let mut sorted = ids.clone();
    sorted.sort();
    sorted.dedup();
    assert_eq!(sorted.len(), ids.len());
    let inline: Vec<_> = view::actions()
        .iter()
        .filter(|a| matches!(a.handler, Handler::Inline))
        .map(|a| a.id)
        .collect();
    assert_eq!(inline, ["ctl:534", "mouse:sidebar-resize"]);
}

fn escape() -> egui::Event {
    egui::Event::Key {
        key: egui::Key::Escape,
        physical_key: None,
        pressed: true,
        repeat: false,
        modifiers: egui::Modifiers::NONE,
    }
}

/// The pass of the area runs Esc@fullscreen itself, since `ui::keys` never looks that id up.
#[test]
fn the_pass_leaves_full_screen_on_escape() {
    let mut rig = Rig::new();
    rig.frame(vec![escape()], view::pass);
    assert!(!rig.options().fullscreen);
    rig.run("menu:290").unwrap();
    rig.frame(vec![], view::pass);
    assert!(rig.options().fullscreen, "no key, no change");
    rig.frame(vec![escape()], view::pass);
    assert!(!rig.options().fullscreen);
}

#[test]
fn the_menus_draw_in_both_languages() {
    let mut rig = Rig::open("camera3.pmm");
    rig.run("menu:248").unwrap();
    rig.run("menu:201").unwrap();
    for _ in 0..2 {
        rig.frame(vec![], |ui, ctx| {
            mds_app::ui::help::pass(ui, ctx);
            view::pass(ui, ctx);
            view::show(ui, ctx);
            mds_app::ui::help::show(ui, ctx);
            mds_app::ui::expression::show(ui, ctx);
        });
        rig.run("menu:260").unwrap();
    }
}

fn form_boxes(rig: &Rig) -> Option<Vec<String>> {
    let form = mds_app::ui::edit::current(rig.egui.as_ref().unwrap())?;
    Some(form.fields.into_iter().map(|f| f.text).collect())
}

/// Menu 212 (`ScreenSizeDlgProc`, `command_file_menu.cpp:436`): the boxes open with the render
/// size as `"%3d"`; a size above the device's limit is refused and the dialog stays; a size within
/// it is stored and the dialog closes.
#[test]
fn the_screen_size_dialog_refuses_what_the_device_cannot_draw() {
    use mds_app::ui::edit;
    let mut rig = Rig::new();
    let s = &rig.editor.doc.pmm.settings;
    let shown = vec![
        format!("{:3}", s.render_width),
        format!("{:3}", s.render_height),
    ];
    rig.run("menu:212").unwrap();
    assert_eq!(form_boxes(&rig), Some(shown.clone()));

    rig.editor.doc.edit.max_texture_size = Some([2048, 2048]);
    let egui = rig.egui.clone().unwrap();
    edit::set_text(&egui, 0, "4096");
    edit::set_text(&egui, 1, "512");
    let err = rig.submit().unwrap_err();
    assert!(err.contains("too big"), "{err}");
    assert!(form_boxes(&rig).is_some(), "the dialog stays open");
    let s = &rig.editor.doc.pmm.settings;
    assert_eq!(
        vec![
            format!("{:3}", s.render_width),
            format!("{:3}", s.render_height)
        ],
        shown
    );
    assert!(!rig.editor.modified);

    edit::set_text(&egui, 0, "1024");
    edit::set_text(&egui, 1, "768 ");
    rig.submit().unwrap();
    assert_eq!(form_boxes(&rig), None);
    let s = &rig.editor.doc.pmm.settings;
    assert_eq!([s.render_width, s.render_height], [1024, 768]);
    assert!(rig.editor.modified);
}

/// Menu 247 flips `followCameraEnabled` through the document command and shows it.
#[test]
fn camera_and_lighting_tracking_flips_the_document_flag() {
    let (mut rig, mut direct) = (Rig::open("camera3.pmm"), Rig::open("camera3.pmm"));
    let before = rig.editor.doc.pmm.appearance.follow_camera;
    rig.run("menu:247").unwrap();
    direct
        .editor
        .apply(Command::SetFollowCamera(before == 0))
        .unwrap();
    assert_eq!(
        rig.editor.doc.pmm.appearance.follow_camera,
        u8::from(before == 0)
    );
    assert!(rig.editor.doc.save().unwrap() == direct.editor.doc.save().unwrap());
    rig.run("menu:247").unwrap();
    assert_eq!(rig.editor.doc.pmm.appearance.follow_camera, before);
}

/// Menu 253 (`command_view_menu.cpp:550`): model mode only; the slider is `TBM_GETPOS / 100.0`
/// from 0 to 200 and sets the selected model's edge scale as it moves.
#[test]
fn the_edge_thickness_slider_sets_the_edge_scale() {
    let mut rig = Rig::open("camera3.pmm");
    rig.editor.apply(Command::SelectCameraMode).unwrap();
    assert_eq!(
        rig.run("menu:253"),
        Err("menu:253: not in this mode".into())
    );
    assert!(!rig.options().edge_dialog);

    let mut rig = Rig::open("swing600.pmm");
    rig.run("menu:253").unwrap();
    assert!(rig.options().edge_dialog);
    for (position, want) in [(150, 1.5), (0, 0.0), (7, 0.07), (999, 2.0)] {
        rig.with_ctx(|ctx| view::set_edge_thickness(ctx, position))
            .unwrap();
        assert_eq!(rig.editor.doc.pmm.models[0].edge_scale, want, "{position}");
    }
    assert!(rig.editor.modified);
    rig.frame(vec![], view::pass);
    assert!(
        rig.options().edge_dialog,
        "the dialog stays until it is closed"
    );

    rig.editor.toggle_play(0).unwrap();
    assert_eq!(
        rig.run("menu:253"),
        Err("menu:253: not while playing".into())
    );
}

/// Menu 286 (`command_view_menu.cpp:1464`): the picker starts on the model outline color and OK
/// stores the chosen one; camera mode has no gate.
#[test]
fn the_edge_color_picker_stores_the_chosen_color() {
    let mut rig = Rig::open("camera3.pmm");
    rig.editor.apply(Command::SelectCameraMode).unwrap();
    let c = rig.editor.doc.pmm.appearance.outline_color;
    rig.run("menu:286").unwrap();
    assert_eq!(rig.options().outline_dialog, Some(c.map(|v| v as u8)));
    rig.frame(vec![], view::pass);
    assert!(rig.options().outline_dialog.is_some());

    rig.with_ctx(|ctx| view::set_outline_color(ctx, [10, 20, 30]))
        .unwrap();
    assert_eq!(rig.editor.doc.pmm.appearance.outline_color, [10, 20, 30]);
    assert!(rig.editor.modified);
}

#[test]
fn the_document_menus_are_refused_while_playing() {
    let mut rig = Rig::new();
    rig.editor.toggle_play(0).unwrap();
    for id in ["menu:212", "menu:247", "menu:253", "menu:286"] {
        assert_eq!(rig.run(id), Err(format!("{id}: not while playing")));
    }
}

#[test]
fn every_row_of_the_area_has_an_action() {
    for id in ["menu:212", "menu:247", "menu:253", "menu:286"] {
        assert!(matches!(
            actions::find(id).map(|a| a.handler),
            Some(Handler::Run(_))
        ));
    }
}
