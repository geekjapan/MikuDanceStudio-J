use crate::labels;
use crate::rig::{fixtures, Rig};
use mds_app::ui::help;

#[test]
fn the_language_switch_flips_every_label() {
    let mut rig = Rig::new();
    let egui = rig.egui.clone().unwrap();
    assert!(!help::english(&egui), "the application starts in Japanese");
    assert_eq!(
        help::pick(&egui, "情報表示", "information display"),
        "情報表示"
    );
    // `englishUI = (cur == 0) ? 1 : 0` (command_view_menu.cpp:923).
    rig.run("menu:260").unwrap();
    assert!(help::english(&egui));
    assert_eq!(
        help::pick(&egui, "情報表示", "information display"),
        "information display"
    );
    rig.run("menu:260").unwrap();
    assert!(!help::english(&egui));
}

#[test]
fn the_language_survives_a_new_document() {
    let mut rig = Rig::new();
    rig.run("menu:260").unwrap();
    rig.editor.apply(mds_doc::Command::NewScene).unwrap();
    assert!(help::english(rig.egui.as_ref().unwrap()));
}

/// `command_dispatch.cpp:436` to `:441`: the version, the 64-bit tag, a blank line, and the
/// author line, which in Japanese is the Shift-JIS bytes 94 F3 8C FB 97 44.
#[test]
fn the_about_text_is_the_banner_of_the_c_plus_plus() {
    let version = std::fs::read_to_string(fixtures().join("../../../VERSION")).unwrap();
    let version = version.trim();
    assert_eq!(
        help::about_text(true),
        format!("MikuDanceStudio Ver.{version}\n  (64bitOS Version)\n\nprogrammed by Yu Higuchi")
    );
    let author = mds_formats::text::decode_sjis(&[0x94, 0xF3, 0x8C, 0xFB, 0x97, 0x44]);
    assert_eq!(
        help::about_text(false),
        format!("MikuDanceStudio Ver.{version}\n  (64bitOS Version)\n\nprogrammed by {author}")
    );
}

#[test]
fn about_opens_its_window() {
    let mut rig = Rig::new();
    rig.run("menu:201").unwrap();
    let id = egui::Id::unique("help-about");
    assert_eq!(
        rig.egui.as_ref().unwrap().data(|d| d.get_temp::<bool>(id)),
        Some(true)
    );
}

#[test]
fn without_a_window_the_actions_say_so() {
    let mut rig = Rig::new();
    rig.egui = None;
    assert_eq!(rig.run("menu:260"), Err("no window".into()));
}

#[test]
fn the_labels_are_those_of_the_inventory() {
    labels::check("help", help::LABELS);
}
