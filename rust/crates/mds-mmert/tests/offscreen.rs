//! Offscreen turns on `tests/data/turn.fx` (a carrier whose `DefaultEffect` rows hide the
//! owner, give `chain*.pmx` `draw.fx`, give `Miku.pmx` its main effect, and leave the rest to
//! the host) and on the fixtures' `offscreen.fx` (`self=hide; *=none;`).

use std::path::{Path, PathBuf};

use mds_mme::sas::{parse, Location, Sas, BACKBUFFER, SEM_OFFSCREEN};
use mds_mmert::emm::Assignment;
use mds_mmert::scene::{turn_draw, TurnDraw, TurnObject};

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
