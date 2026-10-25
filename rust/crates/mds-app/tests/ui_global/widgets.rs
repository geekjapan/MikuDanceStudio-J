//! The panels drawn by egui with no window: `show` runs in both modes, and an edit box commits
//! a typed value on Enter as the C++ edit subclass does.

use crate::support::{camera_mode, model_mode};
use mds_app::editor::Editor;
use mds_app::ui::{camera_panel, light_panel, shadow_panel, Ctx};

fn pass(
    egui: &egui::Context,
    editor: &mut Editor,
    events: Vec<egui::Event>,
    focus: Option<egui::Id>,
    show: fn(&mut egui::Ui, &mut Ctx),
) -> String {
    let mut status = String::new();
    let input = egui::RawInput {
        events,
        ..Default::default()
    };
    let output = egui.run_ui(input, |ui| {
        if let Some(id) = focus {
            ui.memory_mut(|m| m.request_focus(id));
        }
        let mut ctx = Ctx {
            editor,
            now_ms: 0,
            egui: Some(ui.ctx().clone()),
            viewport: None,
            status: &mut status,
        };
        show(ui, &mut ctx);
    });
    output.drop_without_applying_deltas();
    status
}

fn key(key: egui::Key, modifiers: egui::Modifiers) -> egui::Event {
    egui::Event::Key {
        key,
        physical_key: Some(key),
        pressed: true,
        repeat: false,
        modifiers,
    }
}

#[test]
fn every_panel_draws_in_both_modes() {
    let egui = egui::Context::default();
    let areas: [fn(&mut egui::Ui, &mut Ctx); 3] =
        [camera_panel::show, light_panel::show, shadow_panel::show];
    for mut editor in [camera_mode(), model_mode()] {
        for show in areas {
            assert_eq!(pass(&egui, &mut editor, vec![], None, show), "");
        }
    }
}

#[test]
fn an_edit_box_commits_on_enter() {
    let egui = egui::Context::default();
    let mut editor = camera_mode();
    let id = egui::Id::unique(("mds-edit-box", "readout-0")).with("text");
    let show = camera_panel::show;
    pass(&egui, &mut editor, vec![], None, show);
    pass(&egui, &mut editor, vec![], Some(id), show);
    let typed = vec![
        key(egui::Key::A, egui::Modifiers::COMMAND),
        egui::Event::Text("7.5".into()),
    ];
    pass(&egui, &mut editor, typed, None, show);
    assert_ne!(
        editor.doc.pmm.camera_state[0], 7.5,
        "typing alone commits nothing"
    );
    pass(
        &egui,
        &mut editor,
        vec![key(egui::Key::Enter, egui::Modifiers::NONE)],
        None,
        show,
    );
    pass(&egui, &mut editor, vec![], None, show);
    assert_eq!(editor.doc.pmm.camera_state[0], 7.5);
}
