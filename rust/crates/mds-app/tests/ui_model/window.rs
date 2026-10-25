//! The panels drawn into an egui pass with no window: they draw in every state, and the key left
//! of Z (egui's `IntlBackslash`) cycles the model combo like Tab.

use super::common::*;
use egui::{Event, Key, Modifiers, RawInput};
use mds_app::editor::Editor;
use mds_app::ui::{bone_panel, model_panel, morph_panel, Ctx};

fn pass(e: &mut Editor, events: Vec<Event>, f: impl Fn(&mut egui::Ui, &mut Ctx)) {
    let mut status = String::new();
    let egui = egui::Context::default();
    let input = RawInput {
        events,
        ..RawInput::default()
    };
    let mut out = egui.run_ui(input, |ui| f(ui, &mut ctx(e, &mut status)));
    out.textures_delta.clear();
}

fn draw_all(e: &mut Editor) {
    pass(e, Vec::new(), |ui, c| {
        model_panel::show(ui, c);
        bone_panel::show(ui, c);
        morph_panel::show(ui, c);
    });
}

#[test]
fn the_panels_draw_in_camera_mode_and_with_models() {
    let mut e = editor();
    draw_all(&mut e);
    load_model(&mut e, "morph4.pmx");
    draw_all(&mut e);
    load_model(&mut e, "chain8_ik.pmx");
    draw_all(&mut e);
    run(&mut e, "ctl:408").unwrap();
    draw_all(&mut e);
}

#[test]
fn the_key_left_of_z_steps_the_combo() {
    let mut e = editor();
    load_model(&mut e, "chain8.pmx");
    load_model(&mut e, "morph4.pmx");
    let key = |shift| {
        vec![Event::Key {
            key: Key::IntlBackslash,
            physical_key: None,
            pressed: true,
            repeat: false,
            modifiers: Modifiers {
                shift,
                ..Modifiers::default()
            },
        }]
    };
    pass(&mut e, key(false), model_panel::pass);
    assert_eq!(
        model_panel::combo_cursor(&e.doc),
        0,
        "forward from the last model wraps to camera"
    );
    pass(&mut e, key(true), model_panel::pass);
    assert_eq!(model_panel::combo_cursor(&e.doc), 2, "Shift steps back");
}
