//! Offscreen turns on `tests/data/turn.fx` (a carrier whose `DefaultEffect` rows hide the
//! owner, give `chain*.pmx` `draw.fx`, give `Miku.pmx` its main effect, and leave the rest to
//! the host) and on the fixtures' `offscreen.fx` (`self=hide; *=none;`). The turn test draws
//! `chain8.pmx` red with `draw.fx` into the blue-cleared target, and the carrier then samples it.

use std::path::{Path, PathBuf};

use mds_mme::sas::{parse, Location, Sas, BACKBUFFER, SEM_OFFSCREEN};
use mds_mmert::bind::{look_at_lh, DRAW_OBJECT};
use mds_mmert::emm::Assignment;
use mds_mmert::scene::{turn_draw, TurnDraw, TurnObject};
use mds_mmert::{DrawInput, Effect, Gpu, Model, Scene, Target, BACKBUFFER as MAIN};

fn data() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/data")
}

fn load(root: &Path, name: &str) -> Sas {
    let fx = mds_fx::Effect::parse_file(&root.join(name)).unwrap();
    let loc = Location {
        root,
        dir: String::new(),
        backbuffer: BACKBUFFER,
    };
    parse(mds_mme::fx::Fx::new(&fx), &format!("<root>/{name}"), &loc).unwrap()
}

fn object<'a>(name: &'a str, main: &'a Assignment) -> TurnObject<'a> {
    TurnObject {
        name,
        owner: false,
        render_class: 0,
        main,
    }
}

#[test]
fn default_effect_rows_pick_the_turn_draw() {
    let sas = load(&data(), "turn.fx");
    let r = sas
        .resources
        .iter()
        .find(|r| r.semantic == SEM_OFFSCREEN)
        .unwrap();
    let plain = Assignment::default();
    let mut miku = Assignment {
        effect: "C:\\fx\\main.fx".into(),
        ..Assignment::default()
    };
    miku.subsets.insert(1, "C:\\fx\\hair.fx".into());
    miku.subset_shows.insert(2, false);

    let owner = TurnObject {
        owner: true,
        ..object("chain8.pmx", &plain)
    };
    assert_eq!(turn_draw(r, &owner, None), TurnDraw::Hide);
    assert_eq!(
        turn_draw(r, &object("chain8.pmx", &plain), Some(0)),
        TurnDraw::Effect(data().join("draw.fx"))
    );
    let m = object("Miku.pmx", &miku);
    assert_eq!(
        turn_draw(r, &m, None),
        TurnDraw::Effect("C:\\fx\\main.fx".into())
    );
    assert_eq!(
        turn_draw(r, &m, Some(1)),
        TurnDraw::Effect("C:\\fx\\hair.fx".into())
    );
    assert_eq!(turn_draw(r, &m, Some(2)), TurnDraw::Hide);
    assert_eq!(
        turn_draw(r, &object("Miku.pmx", &plain), None),
        TurnDraw::Host
    );
    assert_eq!(
        turn_draw(r, &object("stage.x", &plain), None),
        TurnDraw::Host
    );
    let carrier = TurnObject {
        render_class: 1,
        ..object("stage.x", &plain)
    };
    assert_eq!(turn_draw(r, &carrier, None), TurnDraw::Hide);

    let root =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust/mme/effects");
    let sas = load(&root, "offscreen.fx");
    let r = sas
        .resources
        .iter()
        .find(|r| r.semantic == SEM_OFFSCREEN)
        .unwrap();
    assert_eq!(turn_draw(r, &owner, None), TurnDraw::Hide);
    assert_eq!(
        turn_draw(r, &object("chain8.pmx", &plain), None),
        TurnDraw::Host
    );
}

fn vkd3d() -> Option<mds_shader::vkd3d::Vkd3d> {
    let lib = match std::env::var_os("MDS_VKD3D_LIB") {
        Some(p) => PathBuf::from(p),
        None if cfg!(target_os = "macos") => {
            std::env::temp_dir().join("mds-vkd3d/macos/lib/libvkd3d-shader.1.dylib")
        }
        None => {
            let arch = if cfg!(target_arch = "x86_64") {
                "amd64"
            } else {
                "arm64"
            };
            std::env::temp_dir().join(format!("mds-vkd3d/linux-{arch}/lib/libvkd3d-shader.so.1"))
        }
    };
    mds_shader::vkd3d::Vkd3d::open(&lib)
        .map_err(|e| eprintln!("SKIP: vkd3d-shader not loaded: {e} (a skip is not a pass)"))
        .ok()
}

#[test]
fn a_turn_draws_its_objects_into_the_offscreen_target() {
    let Some(gpu) = Gpu::new().unwrap() else {
        eprintln!("SKIP: no wgpu adapter (a skip is not a pass)");
        return;
    };
    let Some(vk) = vkd3d() else { return };
    let fixtures = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust");
    let pmx =
        mds_formats::pmx::Pmx::read(&std::fs::read(fixtures.join("chain8.pmx")).unwrap()).unwrap();
    let model = Model::from_pmx(&gpu.device, &pmx).unwrap();
    let ((turn_pixels, main_pixels), errors) = gpu.scoped(|| {
        let mut carrier = Effect::load(&gpu, &vk, &data().join("turn.fx"), &data(), MAIN).unwrap();
        let r = carrier
            .sas
            .resources
            .iter()
            .position(|r| r.semantic == SEM_OFFSCREEN)
            .unwrap();
        let plain = Assignment::default();
        let TurnDraw::Effect(path) = turn_draw(
            &carrier.sas.resources[r],
            &object("chain8.pmx", &plain),
            None,
        ) else {
            panic!("chain8.pmx has draw.fx");
        };
        let mut drawer = Effect::load(&gpu, &vk, &path, &data(), MAIN).unwrap();
        let target = carrier.begin_offscreen(&gpu, r).unwrap();
        assert_eq!((target.color.width(), target.color.height()), (64, 32));
        let mut scene = Scene::default_view(64, 32);
        scene.view = look_at_lh([0.0, 4.0, 20.0], [0.0, 4.0, 0.0], [0.0, 1.0, 0.0]);
        let input = DrawInput {
            scene: &scene,
            geometry: Some((&model, 0)),
            draw_type: DRAW_OBJECT,
            controls: None,
            owner: None,
            offscreen_owner: None,
        };
        let report = drawer.draw(&gpu, &target, &input);
        assert_eq!((report.draws, report.drawn), (1, 1), "{:?}", report.skipped);
        let turn = target.read(&gpu).unwrap();

        let main = Target::new(&gpu, MAIN);
        let mut scene = Scene::default_view(MAIN.0, MAIN.1);
        scene.view = look_at_lh([0.0, 4.0, 20.0], [0.0, 4.0, 0.0], [0.0, 1.0, 0.0]);
        let input = DrawInput {
            scene: &scene,
            ..input
        };
        carrier.frame(&gpu, &main, &input);
        (turn, main.read(&gpu).unwrap())
    });
    assert!(errors.is_empty(), "wgpu errors {errors:?}");
    let px = |p: &[u8], i: usize| [p[4 * i], p[4 * i + 1], p[4 * i + 2], p[4 * i + 3]];
    let turn: Vec<[u8; 4]> = (0..64 * 32).map(|i| px(&turn_pixels, i)).collect();
    let (red, blue) = ([255, 0, 0, 255], [0, 0, 255, 255]);
    assert_eq!(turn[0], blue, "the ClearColor");
    assert!(turn.contains(&red), "chain8.pmx drawn by draw.fx");
    assert!(turn.iter().all(|&p| p == red || p == blue));
    // The carrier draws chain8.pmx in the colour at the centre of its offscreen target.
    let centre = turn[16 * 64 + 32];
    let main = main_pixels.len() / 4;
    assert!((0..main).any(|i| px(&main_pixels, i) == centre));
}
