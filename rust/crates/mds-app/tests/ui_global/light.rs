use crate::support::{camera_mode, model_mode, run, with_ctx};
use mds_app::editor::Editor;
use mds_app::ui::light_panel::{color_edit, color_slider, direction_edit, direction_slider};

fn light(e: &Editor) -> [f32; 6] {
    e.doc.pmm.light_state
}

#[test]
fn the_colour_controls_store_a_256th_per_step() {
    // ui_hscroll.cpp:168 to :199 (slider position * 0.00390625); ui_edit_commit.cpp:291
    // (`atol` of the first 7 characters, no clamp).
    let mut e = camera_mode();
    let before = light(&e);
    with_ctx(&mut e, |c| color_slider(c, 0, 128)).0.unwrap();
    with_ctx(&mut e, |c| color_edit(c, 1, "200")).0.unwrap();
    with_ctx(&mut e, |c| color_edit(c, 2, " 300 ")).0.unwrap();
    let l = light(&e);
    assert_eq!([l[0], l[1], l[2]], [0.5, 0.78125, 1.171875]);
    assert_eq!(l[3..], before[3..], "the direction stays");
    with_ctx(&mut e, |c| color_edit(c, 0, "1234567890"))
        .0
        .unwrap();
    assert_eq!(light(&e)[0], 1234567.0 * 0.00390625);
    with_ctx(&mut e, |c| color_edit(c, 0, "12.9")).0.unwrap();
    assert_eq!(light(&e)[0], 12.0 * 0.00390625);
}

#[test]
fn the_direction_controls_store_a_hundredth_per_step() {
    // ui_hscroll.cpp:203 to :229 (slider position / 100.0); ui_edit_commit.cpp:308 (`atof`).
    let mut e = camera_mode();
    let before = light(&e);
    with_ctx(&mut e, |c| direction_slider(c, 0, -50)).0.unwrap();
    with_ctx(&mut e, |c| direction_edit(c, 1, "0.25"))
        .0
        .unwrap();
    with_ctx(&mut e, |c| direction_edit(c, 2, "-1.5abc"))
        .0
        .unwrap();
    let l = light(&e);
    assert_eq!([l[3], l[4], l[5]], [-0.5, 0.25, -1.5]);
    assert_eq!(l[..3], before[..3], "the colour stays");
    with_ctx(&mut e, |c| direction_slider(c, 0, 100)).0.unwrap();
    assert_eq!(light(&e)[3], 1.0);
}

#[test]
fn reset_restores_the_default_light() {
    // command_panel_toggles.cpp:405: direction (-0.5, -1, 0.5), every channel 0.602f
    // (0x3F1A1CAC).
    let mut e = camera_mode();
    with_ctx(&mut e, |c| color_edit(c, 0, "5")).0.unwrap();
    with_ctx(&mut e, |c| direction_edit(c, 0, "7")).0.unwrap();
    run(&mut e, "ctl:467").unwrap();
    let l = light(&e);
    assert_eq!(
        l[..3].iter().map(|v| v.to_bits()).collect::<Vec<_>>(),
        [0x3F1A1CAC; 3]
    );
    assert_eq!(l[3..], [-0.5, -1.0, 0.5]);
}

#[test]
fn register_stores_the_light_at_the_current_frame() {
    // command_panel_toggles.cpp:459 (RegisterLightState at currentFrame).
    let mut e = camera_mode();
    e.seek(45).unwrap();
    with_ctx(&mut e, |c| color_edit(c, 0, "200")).0.unwrap();
    with_ctx(&mut e, |c| direction_edit(c, 0, "0.5")).0.unwrap();
    run(&mut e, "ctl:468").unwrap();
    let track = &e.doc.pmm.light;
    let key = track
        .records()
        .iter()
        .map(|(_, k)| k)
        .chain(track.heads())
        .find(|k| k.frame == 45)
        .unwrap();
    assert_eq!((key.color[0], key.direction[0]), (0.78125, 0.5));
}

#[test]
fn the_light_panel_belongs_to_camera_mode_and_to_stopped_playback() {
    // StartPlayback greys 415..=468 (playback_state.cpp:333); PostModelReload2 shows the panel in
    // camera mode only.
    let mut e = model_mode();
    assert_eq!(
        with_ctx(&mut e, |c| color_edit(c, 0, "1")).0,
        Err("camera mode only".into())
    );
    assert_eq!(run(&mut e, "ctl:467"), Err("camera mode only".into()));
    run(&mut e, "ctl:408").unwrap();
    for id in ["ctl:467", "ctl:468"] {
        assert_eq!(run(&mut e, id), Err(format!("{id}: not while playing")));
    }
}
