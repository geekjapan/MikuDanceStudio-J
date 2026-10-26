//! [`mds_app::actions::enabled`] and [`mds_app::actions::run`] by edit mode.

use super::{fixtures, run};
use mds_app::actions::{self, Action, Mode};
use mds_app::editor::Editor;
use mds_app::ui::Ctx;

fn enabled(editor: &mut Editor, id: &str) -> bool {
    let mut status = String::new();
    let ctx = Ctx {
        editor,
        now_ms: 0,
        egui: None,
        viewport: None,
        status: &mut status,
    };
    actions::enabled(&ctx, id)
}

/// The Enter rows of the table: `@camera-mode` registers the camera-mode tracks
/// (`PumpGlobalEnterRegister`), `@model-mode` the bones; each is refused in the other mode.
#[test]
fn a_moded_action_runs_in_its_mode_only() {
    let mut e = Editor::open(&fixtures().join("swing600.pmm")).unwrap();
    let model = e.doc.pmm.settings.options[0] == 0;
    let (mine, other) = match model {
        true => ("key:Enter@model-mode", "key:Enter@camera-mode"),
        false => ("key:Enter@camera-mode", "key:Enter@model-mode"),
    };
    assert!(enabled(&mut e, mine));
    assert!(!enabled(&mut e, other));
    let err = run(&mut e, other).unwrap_err();
    assert!(err.ends_with("mode only"), "{err}");
    e.toggle_play(0).unwrap();
    assert!(!enabled(&mut e, mine), "and not while playing");
}

#[test]
fn the_mode_comes_from_the_builder_or_the_id() {
    fn f(_: &mut Ctx) -> Result<(), String> {
        Ok(())
    }
    assert_eq!(Action::run("menu:205", f, true).mode(), Mode::Any);
    assert_eq!(
        Action::run("menu:202", f, true).in_mode(Mode::Model).mode(),
        Mode::Model
    );
    assert_eq!(Action::inline("key:Enter@camera-mode").mode(), Mode::Camera);
}
