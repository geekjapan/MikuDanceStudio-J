//! The two pmm load prompts and the drawing of every dialog.

use super::Rig;
use egui::{Event, Key, Modifiers};
use mds_app::editor::Editor;
use mds_app::ui::dialog::{self, LoadChoice, Prompt};

fn escape() -> Vec<Event> {
    vec![Event::Key {
        key: Key::Escape,
        physical_key: None,
        pressed: true,
        repeat: false,
        modifiers: Modifiers::NONE,
    }]
}

#[test]
fn the_missing_model_prompt_names_the_model() {
    let rig = Rig::new(Editor::empty());
    let prompt = Prompt::MissingModel {
        model_name: "ミク",
        source_name: "miku.pmd",
    };
    dialog::ask(&rig.egui, prompt);
    assert_eq!(rig.shown(), Some("IDD_PMM_MISSING_MODEL"));
    // `kJpQuoted` of `pmm_load_v2.cpp`: the name between double quotes.
    assert_eq!(
        dialog::prompt_message(&rig.egui).as_deref(),
        Some("\"ミク\"")
    );
    assert_eq!(dialog::take_choice(&rig.egui), None);
}

#[test]
fn the_mismatch_prompt_says_when_it_is_the_second_file() {
    let rig = Rig::new(Editor::empty());
    for (again, want) in [
        (false, "\"ミク\""),
        (
            true,
            "このモデルの構造もpmm保存時の\"ミク\"のものと異なります",
        ),
    ] {
        dialog::ask(
            &rig.egui,
            Prompt::ModelMismatch {
                model_name: "ミク",
                source_name: "a.pmd",
                again,
            },
        );
        assert_eq!(rig.shown(), Some("IDD_PMM_MODEL_MISMATCH"));
        assert_eq!(dialog::prompt_message(&rig.egui).as_deref(), Some(want));
    }
}

/// The close button returns 2 from `DialogBoxParamA`, which the loaders treat as stopping the
/// whole load (`DialogFuncStub`, `late_ports.cpp:314`).
#[test]
fn closing_a_prompt_aborts_the_load() {
    for name in ["IDD_PMM_MISSING_MODEL", "IDD_PMM_MODEL_MISMATCH"] {
        let mut rig = Rig::new(Editor::empty());
        rig.run(&format!("dlg:{name}")).unwrap();
        rig.draw(Vec::new());
        assert_eq!(rig.shown(), Some(name));
        rig.draw(escape());
        assert_eq!(rig.shown(), None, "{name}");
        assert_eq!(dialog::take_choice(&rig.egui), Some(LoadChoice::Abort));
        assert_eq!(dialog::take_choice(&rig.egui), None, "once");
    }
}

#[test]
fn every_dialog_draws_and_escape_closes_it() {
    let names = [
        "IDD_CENTER_POSITION_BIAS",
        "IDD_SCREEN_SIZE",
        "IDD_AVI_OUTPUT",
        "IDD_FRAME_SHIFT",
        "IDD_REGISTER_BLINKING",
        "IDD_BONE_FRAME_MULTIPLY",
        "IDD_MORPH_MULTIPLY",
        "IDD_EDGE_THICKNESS",
        "IDD_GRAVITY",
        "IDD_PHYSICS_FRAME_CONVERSION",
        "IDD_PMM_MISSING_MODEL",
        "IDD_PMM_MODEL_MISMATCH",
    ];
    for name in names {
        let mut rig = Rig::open("swing600.pmm");
        rig.run(&format!("dlg:{name}"))
            .unwrap_or_else(|e| panic!("{name}: {e}"));
        rig.draw(Vec::new());
        rig.draw(Vec::new());
        assert_eq!(rig.shown(), Some(name));
        rig.draw(escape());
        assert_eq!(rig.shown(), None, "{name}");
    }
    for name in ["IDD_CAMERA_FRAME_MULTIPLY", "IDD_CAMERA_NUMERIC_INPUT"] {
        let mut rig = Rig::open("camera3.pmm");
        rig.editor
            .apply(mds_doc::Command::SelectCameraMode)
            .unwrap();
        rig.run(&format!("dlg:{name}"))
            .unwrap_or_else(|e| panic!("{name}: {e}"));
        rig.draw(Vec::new());
        assert_eq!(rig.shown(), Some(name));
        rig.draw(escape());
        assert_eq!(rig.shown(), None, "{name}");
    }
}
