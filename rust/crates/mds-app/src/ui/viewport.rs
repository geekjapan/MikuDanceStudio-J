//! The `viewport` area, so far: the picture ([`crate::viewport`]), the camera-mode navigation of
//! [`crate::navigation`] (right and middle drags, the wheel, the numpad presets), and the view
//! buttons 402 to 407. The model-mode view offsets, bone picking and the gizmos come later.

use super::{button, Ctx};
use crate::actions::Action;
use crate::navigation::{self, Modifiers, ViewButton, WHEEL_DELTA};
use egui::{Event, MouseWheelUnit, PointerButton, Sense};

const ACTIONS: &[Action] = &[
    Action::run("ctl:402", |c| view(c, ViewButton::Front), false),
    Action::run("ctl:403", |c| view(c, ViewButton::Back), false),
    Action::run("ctl:404", |c| view(c, ViewButton::Top), false),
    Action::run("ctl:405", |c| view(c, ViewButton::Left), false),
    Action::run("ctl:406", |c| view(c, ViewButton::Right), false),
    Action::run("ctl:407", |c| view(c, ViewButton::Bottom), false),
    Action::run("key:Numpad0", |c| numpad(c, 0), false),
    Action::run("key:Numpad1", |c| numpad(c, 1), false),
    Action::run("key:Numpad2", |c| numpad(c, 2), false),
    Action::run("key:Numpad4", |c| numpad(c, 4), false),
    Action::run("key:Numpad5", |c| numpad(c, 5), false),
    Action::run("key:Numpad6", |c| numpad(c, 6), false),
    Action::run("key:Numpad8", |c| numpad(c, 8), false),
    Action::inline("mouse:rmb-drag"),
    Action::inline("mouse:ctrl-rmb-drag"),
    Action::inline("mouse:mmb-drag"),
    Action::inline("mouse:wheel"),
];

pub fn actions() -> &'static [Action] {
    ACTIONS
}

fn view(ctx: &mut Ctx, b: ViewButton) -> Result<(), String> {
    b.apply(&mut ctx.editor.camera);
    Ok(())
}

/// `ConsumeNumpadViewPresets` runs in the stopped branch of the pump only.
fn numpad(ctx: &mut Ctx, digit: u8) -> Result<(), String> {
    if !ctx.editor.playing() {
        navigation::numpad(&mut ctx.editor.camera, digit);
    }
    Ok(())
}

pub fn show(ui: &mut egui::Ui, ctx: &mut Ctx) {
    ui.horizontal(|ui| {
        for (b, a) in ViewButton::ALL.into_iter().zip(ACTIONS) {
            button(ui, ctx, a.id, b.label());
        }
    });
    let (rect, response) = ui.allocate_exact_size(ui.available_size(), Sense::drag());
    let ppp = ui.ctx().pixels_per_point();
    let (m, wheel) = ui.input(|i| {
        let wheel: f32 = i
            .events
            .iter()
            .filter_map(|e| match e {
                Event::MouseWheel {
                    unit: MouseWheelUnit::Line,
                    delta,
                    ..
                } => Some(delta.y * f32::from(WHEEL_DELTA)),
                // ponytail: a trackpad point counts as one WM_MOUSEWHEEL unit; tune if the
                // zoom feels wrong.
                Event::MouseWheel { delta, .. } => Some(delta.y),
                _ => None,
            })
            .sum();
        let m = Modifiers {
            shift: i.modifiers.shift,
            ctrl: i.modifiers.ctrl || i.modifiers.mac_cmd,
        };
        (m, wheel)
    });
    let pixels = |v: f32| (v * ppp).round() as i32;
    let delta = response.drag_delta();
    let camera = &mut ctx.editor.camera;
    if response.dragged_by(PointerButton::Secondary) {
        navigation::right_drag(camera, pixels(delta.x), pixels(delta.y), m);
    }
    if response.dragged_by(PointerButton::Middle) {
        navigation::middle_drag(camera, pixels(delta.x), pixels(delta.y), m);
    }
    if response.hovered() && wheel != 0.0 {
        navigation::wheel(camera, wheel.round() as i16);
    }

    let size = [(rect.width() * ppp) as u32, (rect.height() * ppp) as u32];
    let Some(viewport) = ctx
        .viewport
        .as_deref_mut()
        .filter(|_| size[0] > 0 && size[1] > 0)
    else {
        return;
    };
    match viewport.show(ctx.editor, size) {
        Ok(texture) => {
            let uv = egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0));
            ui.painter().image(texture, rect, uv, egui::Color32::WHITE);
        }
        Err(e) => *ctx.status = e,
    }
}

pub fn pass(_ui: &mut egui::Ui, _ctx: &mut Ctx) {}
