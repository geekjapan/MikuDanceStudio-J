//! `CONTROLOBJECT` on `offscreen.fx` (`Morph` from `ctrl.pmx`, `Bone` from `(self)`'s `Root`),
//! with the values `ResolveOneControl` writes when the object is found and when it is not.

use std::path::Path;

use mds_mme::sas::{parse, Location, BACKBUFFER};
use mds_mmert::bind::{initial, IDENTITY};
use mds_mmert::control::{resolve, Controls, Object};

#[test]
fn control_objects_read_morphs_bones_and_defaults() {
    let root =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust/mme/effects");
    let fx = mds_fx::Effect::parse_file(&root.join("offscreen.fx")).unwrap();
    let loc = Location {
        root: &root,
        dir: String::new(),
        backbuffer: BACKBUFFER,
    };
    let sas = parse(mds_mme::fx::Fx::new(&fx), "<root>/offscreen.fx", &loc).unwrap();
    let param = |n: &str| sas.fx.param_by_name(n).unwrap();
    let mut values: Vec<Vec<f32>> = sas.fx.params.iter().map(initial).collect();

    let mut owner = Object::model("chain8.pmx", 1);
    let mut root_bone = IDENTITY;
    root_bone[12] = 3.0;
    owner.bones.push(("Root".into(), root_bone));
    let mut ctrl = Object::model("ctrl.pmx", 2);
    ctrl.morphs.push(("Morph".into(), 0.75));
    let controls = Controls {
        objects: vec![owner, ctrl],
    };
    resolve(&sas, &mut values, &controls, Some(0), None);
    assert_eq!(values[param("Morph")], [0.75]);
    assert_eq!(values[param("Bone")], root_bone);

    // Not found: an item reads 0, and a matrix of a name that is not an accessory's the identity.
    let alone = Controls {
        objects: vec![Object::model("chain8.pmx", 1)],
    };
    resolve(&sas, &mut values, &alone, Some(0), None);
    assert_eq!(values[param("Morph")], [0.0]);
    assert_eq!(values[param("Bone")], IDENTITY, "(self) has no Root bone");
    resolve(&sas, &mut values, &alone, None, None);
    assert_eq!(values[param("Bone")], IDENTITY);
}
