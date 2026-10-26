use crate::labels;
use crate::rig::{fixtures, Rig};
use mds_app::actions::{self, Handler};
use mds_app::ui::{dialog, help};

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

/// Menu 278 waits for an `Editor` call that loads the textures again.
#[test]
fn restore_textures_is_not_faked() {
    assert!(actions::find("menu:278").is_none());
}

/// Menus 259, 261 and 262 open their dialogs through the action of the dialog area, in model mode
/// only (`command_view_menu.cpp:911`, `:938`, `:968`). Until the dialog area registers an action
/// for a dialog the menu reports that, and the test says SKIP.
#[test]
fn the_model_dialogs_open_through_the_dialog_area() {
    for (menu, dialog) in [
        ("menu:259", "IDD_ENGLISH_NAMES"),
        ("menu:261", "IDD_TOON_TEXTURE"),
        ("menu:262", "IDD_PHYSICS_MODEL"),
    ] {
        let action = format!("dlg:{dialog}");
        let mut rig = pmd_rig();
        assert!(matches!(
            actions::find(menu).map(|a| a.handler),
            Some(Handler::Run(_))
        ));
        if actions::find(&action).is_none() {
            println!("SKIP: {menu} opens {action}, which the dialog area does not register yet");
            assert_eq!(rig.run(menu), Err(format!("{action}: not implemented")));
            continue;
        }
        rig.run(menu).unwrap();
        assert_eq!(dialog::current(rig.egui.as_ref().unwrap()), Some(dialog));
    }
}

/// The three handlers return in camera mode, which also greys the items.
#[test]
fn the_model_dialogs_keep_to_the_model_mode() {
    let mut rig = pmd_rig();
    rig.editor
        .apply(mds_doc::Command::SelectCameraMode)
        .unwrap();
    for id in ["menu:259", "menu:261", "menu:262"] {
        assert_eq!(rig.run(id), Err(format!("{id}: model mode only")), "{id}");
        assert!(!rig.with_ctx(|c| c.enabled(id)), "{id}");
    }
    assert_eq!(dialog::current(rig.egui.as_ref().unwrap()), None);
}

/// They are not among the menus `DisablePlaybackMenus` greys (`playback_state.cpp:67`).
#[test]
fn the_model_dialogs_are_not_playback_menus() {
    for id in ["menu:259", "menu:261", "menu:262"] {
        assert!(!actions::find(id).unwrap().needs_document, "{id}");
    }
}

fn pmd_rig() -> Rig {
    let mut rig = Rig::new();
    rig.editor
        .apply(mds_doc::Command::LoadModel {
            path: "chain8.pmd".into(),
            data: std::fs::read(fixtures().join("chain8.pmd")).unwrap(),
        })
        .unwrap();
    rig
}

fn temp(name: &str) -> std::path::PathBuf {
    std::env::temp_dir().join(format!("mds-uimenus2-help-{}-{name}", std::process::id()))
}

/// Menu 263 on a PMD writes what the C++ `SaveEnhancedModel` wrote for `save pmd` in
/// `script/bones.txt`, and the saved file becomes the model's path.
#[test]
fn save_enhanced_model_writes_the_pmd_of_the_oracle() {
    let mut rig = pmd_rig();
    let path = temp("chain8-saved.pmd");
    rig.editor.modified = false;
    rig.with_ctx(|ctx| help::save_enhanced(ctx, &path)).unwrap();
    let bytes = std::fs::read(&path).unwrap();
    std::fs::remove_file(&path).unwrap();
    let want = fixtures().join("script/expected/bones/chain8-saved.pmd");
    if !want.exists() {
        println!("SKIP: {} is missing", want.display());
        return;
    }
    assert!(bytes == std::fs::read(want).unwrap());
    assert_eq!(
        rig.editor.doc.pmm.models[0].path.text,
        path.display().to_string()
    );
    assert!(
        !rig.editor.modified,
        "SaveEnhancedModel sets no modified flag"
    );
}

/// The C++ writer ends the process on a PMX model; here it is an error, and nothing is written.
#[test]
fn save_enhanced_model_refuses_a_pmx_model_and_no_model() {
    let mut rig = Rig::new();
    let path = temp("none.pmd");
    assert!(rig.with_ctx(|ctx| help::save_enhanced(ctx, &path)).is_err());
    rig.editor
        .apply(mds_doc::Command::LoadModel {
            path: "chain8.pmx".into(),
            data: std::fs::read(fixtures().join("chain8.pmx")).unwrap(),
        })
        .unwrap();
    let err = rig
        .with_ctx(|ctx| help::save_enhanced(ctx, &path))
        .unwrap_err();
    assert!(err.contains("not a PMD"), "{err}");
    assert!(!path.exists());
}

#[test]
fn save_enhanced_model_needs_a_window_for_its_dialog() {
    let mut rig = pmd_rig();
    rig.egui = None;
    assert_eq!(rig.run("menu:263"), Err("no window".into()));
}
