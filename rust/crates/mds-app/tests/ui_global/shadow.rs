use crate::support::{camera_mode, run, with_ctx};
use mds_app::actions;
use mds_app::editor::Editor;
use mds_app::ui::shadow_panel::{self, commit_range, set_range};
use mds_app::ui::Ctx;

fn distance(e: &Editor) -> f32 {
    e.doc.pmm.physics_interval
}

#[test]
fn the_mode_buttons_set_the_mode_and_keep_the_range() {
    // command_frame_register.cpp:773 to :797 (SelfShadowMode = 0, 1, 2).
    let mut e = camera_mode();
    let before = distance(&e);
    for (id, mode) in [
        ("ctl:562", 0),
        ("ctl:563", 1),
        ("ctl:564", 2),
        ("ctl:563", 1),
    ] {
        run(&mut e, id).unwrap();
        assert_eq!(e.doc.edit.self_shadow_mode, mode, "{id}");
    }
    assert_eq!(distance(&e), before);
}

#[test]
fn the_range_is_ten_thousand_minus_the_value_over_a_hundred_thousand() {
    // ui_hscroll.cpp:262 (slider) and ui_edit_commit.cpp:332 (`atof` of 7 characters).
    let mut e = camera_mode();
    run(&mut e, "ctl:564").unwrap();
    with_ctx(&mut e, |c| set_range(c, 8000.0)).0.unwrap();
    assert_eq!(distance(&e), ((10000.0 - 8000.0) / 100000.0) as f32);
    with_ctx(&mut e, |c| commit_range(c, "9990.5xyz"))
        .0
        .unwrap();
    assert_eq!(distance(&e), ((10000.0 - 9990.5) / 100000.0) as f32);
    with_ctx(&mut e, |c| commit_range(c, "12345678")).0.unwrap();
    assert_eq!(distance(&e), ((10000.0 - 1234567.0) / 100000.0) as f32);
    assert_eq!(
        e.doc.edit.self_shadow_mode, 2,
        "the range edit keeps the mode"
    );
}

#[test]
fn register_stores_the_mode_and_range_at_the_current_frame() {
    // command_frame_register.cpp:799 (RegisterSelfShadowState at currentFrame).
    let mut e = camera_mode();
    e.seek(50).unwrap();
    run(&mut e, "ctl:564").unwrap();
    with_ctx(&mut e, |c| commit_range(c, "8000")).0.unwrap();
    run(&mut e, "ctl:565").unwrap();
    let track = &e.doc.pmm.self_shadow;
    let key = track
        .records()
        .iter()
        .map(|(_, k)| k)
        .chain(track.heads())
        .find(|k| k.frame == 50)
        .unwrap();
    assert_eq!((key.mode, key.distance), (2, 0.02));
}

#[test]
fn the_panel_is_not_greyed_while_playing() {
    // StartPlayback greys 415..=468 and 536..=550; the shadow controls 556..=567 stay on.
    let mut e = camera_mode();
    run(&mut e, "ctl:408").unwrap();
    run(&mut e, "ctl:563").unwrap();
    run(&mut e, "ctl:565").unwrap();
    assert_eq!(e.doc.edit.self_shadow_mode, 1);
}

#[test]
fn ctrl_g_says_the_fine_shadow_mode_moved() {
    // FineShadowModeNotice, command_view_menu.cpp:777: the Shift-JIS bytes of kMsgFineShadowJp.
    let mut e = camera_mode();
    let (r, status) = with_ctx(&mut e, |c| actions::run(c, "key:Ctrl+G"));
    assert_eq!(r, Ok(()));
    let sjis: &[u8] = b"\x82\xB1\x82\xCC\x89\x42\x82\xB5\x83\x52\x83\x7D\x83\x93\x83\x68\x82\xCD\x89\xE6\x96\xCA\x89\x45\x8F\xE3\x82\xCC\x81\x75\x94\xFC\x81\x40\x89\x65\x81\x76\x83\x7B\x83\x5E\x83\x93\x82\xC9\x8E\xE6\x82\xC1\x82\xC4\x95\xCF\x82\xED\x82\xE8\x82\xDC\x82\xB5\x82\xBD";
    let text = sjis_to_utf8(sjis);
    assert_eq!(status, text);
}

/// The characters of the C++ message bytes, through the table below (a decoder crate for one
/// message would cost more than the table).
fn sjis_to_utf8(bytes: &[u8]) -> String {
    let mut out = String::new();
    let mut i = 0;
    while i < bytes.len() {
        let pair = u16::from_be_bytes([bytes[i], bytes[i + 1]]);
        out.push(
            SJIS.iter()
                .find(|(code, _)| *code == pair)
                .unwrap_or_else(|| panic!("{pair:04X}"))
                .1,
        );
        i += 2;
    }
    out
}

/// The Shift-JIS code of each character of the notice.
const SJIS: &[(u16, char)] = &[
    (0x82B1, 'こ'),
    (0x82CC, 'の'),
    (0x8942, '隠'),
    (0x82B5, 'し'),
    (0x8352, 'コ'),
    (0x837D, 'マ'),
    (0x8393, 'ン'),
    (0x8368, 'ド'),
    (0x82CD, 'は'),
    (0x89E6, '画'),
    (0x96CA, '面'),
    (0x8945, '右'),
    (0x8FE3, '上'),
    (0x8175, '「'),
    (0x94FC, '美'),
    (0x8140, '　'),
    (0x8965, '影'),
    (0x8176, '」'),
    (0x837B, 'ボ'),
    (0x835E, 'タ'),
    (0x82C9, 'に'),
    (0x8EE6, '取'),
    (0x82C1, 'っ'),
    (0x82C4, 'て'),
    (0x95CF, '変'),
    (0x82ED, 'わ'),
    (0x82E8, 'り'),
    (0x82DC, 'ま'),
    (0x82BD, 'た'),
];

/// Shift+G shows the shadow map over the viewport (`key_ladder.cpp:158`), which `mds-render` has
/// no map to do.
#[test]
fn the_shadow_map_display_key_is_not_implemented() {
    let mut e = camera_mode();
    assert_eq!(
        run(&mut e, "key:Shift+G"),
        Err("key:Shift+G: not implemented".into())
    );
}

/// Check box 556 sets the size of the shadow map, 0x1000 when checked and 0x800 when not
/// (`command_frame_register.cpp:722` to `:747`); it is window state and no part of the scene.
#[test]
fn fshadow_sets_the_map_size_in_the_window() {
    let mut e = camera_mode();
    let saved = e.doc.save().unwrap();
    let egui = egui::Context::default();
    assert_eq!(shadow_panel::map_size(&egui), 0x800);
    for want in [0x1000, 0x800, 0x1000] {
        let mut status = String::new();
        mds_app::actions::run(
            &mut Ctx {
                editor: &mut e,
                now_ms: 0,
                egui: Some(egui.clone()),
                viewport: None,
                status: &mut status,
            },
            "ctl:556",
        )
        .unwrap();
        assert_eq!(shadow_panel::map_size(&egui), want);
    }
    assert_eq!(e.doc.save().unwrap(), saved);
    assert!(!e.modified);
    run(&mut e, "ctl:556").unwrap();
    assert_eq!(
        shadow_panel::map_size(&egui),
        0x1000,
        "no window, no change"
    );
}
