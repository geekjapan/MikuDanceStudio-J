//! `AccessoryPlacement` (`src/render/accessory.cpp:89`) against matrices worked out by
//! hand, the `.vac` loader (`accessory.cpp:462`), and the shadow decisions.
//!
//! `camera3.pmm` has no accessory (checked below), so the cases are constructed. A
//! D3D matrix multiplies row vectors: `p' = p * M`.

use mds_accessory::transform::*;
use mds_accessory::vac;
use mds_accessory::{AccessoryState, TextureKind};
use mds_math::Mat4;
use std::f32::consts::FRAC_PI_2;
use std::path::PathBuf;

fn point(p: [f32; 3], m: &Mat4) -> [f32; 3] {
    let m = &m.0;
    std::array::from_fn(|j| p[0] * m[j] + p[1] * m[4 + j] + p[2] * m[8 + j] + m[12 + j])
}

fn near(a: [f32; 3], b: [f32; 3]) {
    for i in 0..3 {
        assert!((a[i] - b[i]).abs() < 1e-5, "{a:?} != {b:?}");
    }
}

fn state(scale: f32, position: [f32; 3], rotation: [f32; 3]) -> AccessoryState {
    AccessoryState {
        scale,
        position,
        rotation,
        ..Default::default()
    }
}

#[test]
fn the_pmm_fixtures_have_no_accessory() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust");
    for name in [
        "camera3.pmm",
        "swing600.pmm",
        "swing600-golden.pmm",
        "swing600-nophys.pmm",
    ] {
        let pmm = mds_formats::pmm::Pmm::read(&std::fs::read(root.join(name)).unwrap()).unwrap();
        assert!(pmm.accessories.is_empty(), "{name}");
    }
}

#[test]
fn scale_is_ten_times_the_record_scale() {
    // C++ 92: scale * 10. A new accessory (scale 1) is drawn at 10x.
    let m = world_matrix(&AccessoryState::default(), None);
    let mut want = [0.0f32; 16];
    (want[0], want[5], want[10], want[15]) = (10.0, 10.0, 10.0, 1.0);
    assert_eq!(m.0, want);
}

#[test]
fn position_is_added_after_the_scale() {
    // S(20) * T(1,2,3): the translation is not scaled.
    let m = world_matrix(&state(2.0, [1., 2., 3.], [0.; 3]), None);
    assert_eq!(
        m.0,
        [20., 0., 0., 0., 0., 20., 0., 0., 0., 0., 20., 0., 1., 2., 3., 1.]
    );
}

#[test]
fn rotation_about_x() {
    let m = world_matrix(&state(0.5, [0.; 3], [FRAC_PI_2, 0., 0.]), None);
    // D3DXMatrixRotationX: y -> z. (0,1,0) * 5 = (0,5,0) -> (0,0,5).
    near(point([0., 1., 0.], &m), [0., 0., 5.]);
    near(point([1., 0., 0.], &m), [5., 0., 0.]);
}

#[test]
fn rotation_order_is_z_then_x_then_y() {
    // (1,0,0): Rz(90) -> (0,1,0); then Rx(90) -> (0,0,1). Rx first would give (0,1,0).
    let m = world_matrix(&state(0.1, [0.; 3], [FRAC_PI_2, 0., FRAC_PI_2]), None);
    near(point([1., 0., 0.], &m), [0., 0., 1.]);
    // (0,1,0): Rx(90) -> (0,0,1); then Ry(90) -> (1,0,0). Ry first would give (0,0,1).
    let m = world_matrix(&state(0.1, [0.; 3], [FRAC_PI_2, FRAC_PI_2, 0.]), None);
    near(point([0., 1., 0.], &m), [1., 0., 0.]);
    // All three, then the position: (1,0,0) -Rz-> (0,1,0) -Rx-> (0,0,1) -Ry-> (1,0,0), + (1,2,3).
    let m = world_matrix(&state(0.1, [1., 2., 3.], [FRAC_PI_2; 3]), None);
    near(point([1., 0., 0.], &m), [2., 2., 3.]);
}

#[test]
fn parent_bone_adds_its_translation_and_matrix() {
    let bone = ParentBone {
        position: [1., 2., 3.],
        // Rotation of 90 degrees about Z, then translation (5,6,7).
        matrix: Mat4([
            0., 1., 0., 0., -1., 0., 0., 0., 0., 0., 1., 0., 5., 6., 7., 1.,
        ]),
    };
    let m = world_matrix(&state(0.5, [0.; 3], [0.; 3]), Some(&bone));
    // (1,0,0) * 5 = (5,0,0); + bone position = (6,2,3); * matrix = (-2+5, 6+6, 3+7).
    assert_eq!(point([1., 0., 0.], &m), [3., 12., 10.]);
    // The accessory's own position goes inside the bone's frame.
    let m = world_matrix(&state(0.5, [1., 0., 0.], [0.; 3]), Some(&bone));
    // (5,0,0) + (1,0,0) + (1,2,3) = (7,2,3) -> (-2+5, 7+6, 3+7)
    assert_eq!(point([1., 0., 0.], &m), [3., 13., 10.]);
}

#[test]
fn parent_slots() {
    // C++ 104-109 (the slot count is the x64 kModelSlotCount).
    assert_eq!(parent_model_slot(-1), None);
    assert_eq!(parent_model_slot(0), Some(0));
    assert_eq!(parent_model_slot(254), Some(254));
    assert_eq!(parent_model_slot(255), None);
    // C++ 113: std::max(parentBone, 0).
    assert_eq!(parent_bone_index(-5), 0);
    assert_eq!(parent_bone_index(7), 7);
}

#[test]
fn a_new_accessory_has_the_record_defaults() {
    // InitAccessoryRecord (src/render/debug_geometry.cpp:217) and LoadAccessoryFile 630.
    let s = AccessoryState::default();
    assert!(s.visible && !s.shadow_enabled && !s.additive_blend);
    assert_eq!(
        (s.scale, s.opacity, s.parent_model, s.parent_bone),
        (1.0, 1.0, -1, 0)
    );
    assert_eq!((s.position, s.rotation), ([0.0; 3], [0.0; 3]));
}

fn fixture(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../../tests/fixtures/rust/accessory")
        .join(name)
}

#[test]
fn vac_sets_the_placement() {
    let text = std::fs::read(fixture("placed.vac")).unwrap();
    let v = vac::parse(&text);
    assert_eq!(v.mesh, "cube.x");
    assert_eq!(v.scale, 2.5);
    assert_eq!(v.position, [1.0, 2.0, 3.0]);
    assert_eq!(v.rotation, [0.5, 0.25, 0.125]);
    // fscanf("%d") reads 1 after two skipped lines: shadowDisabled = 1.
    assert!(!v.shadow_enabled);

    let acc = vac::load_file(&fixture("placed.vac")).unwrap();
    assert_eq!(acc.vertices.len(), 24);
    assert_eq!(acc.state.scale, 2.5);
    assert_eq!(acc.state.position, [1.0, 2.0, 3.0]);
    assert!(!acc.state.shadow_enabled);
    assert_eq!(acc.materials[0].texture.kind, TextureKind::Plain);
}

#[test]
fn vac_without_values_keeps_the_defaults() {
    let v = vac::parse(&std::fs::read(fixture("placed_default.vac")).unwrap());
    assert_eq!(
        (v.mesh.as_str(), v.scale, v.position, v.rotation),
        ("cube.x", 1.0, [0.0; 3], [0.0; 3])
    );
    // shadowDisabled starts at 0, so a failed read leaves the shadow on.
    assert!(v.shadow_enabled);
}

#[test]
fn x_file_loads_with_a_fresh_record() {
    let acc = vac::load_file(&fixture("cube.x")).unwrap();
    assert_eq!(acc.state, AccessoryState::default());
    assert!(vac::load_file(&fixture("missing.x")).is_err());
}

#[test]
fn shadow_decisions() {
    // C++ 795-797: visible, shadow on, not additive.
    let mut s = AccessoryState {
        shadow_enabled: true,
        ..Default::default()
    };
    assert!(casts_shadow_map(&s));
    s.additive_blend = true;
    assert!(!casts_shadow_map(&s));
    s.additive_blend = false;
    s.visible = false;
    assert!(!casts_shadow_map(&s));
    // C++ 769 and 223: the projected ground shadow needs the flag and visibility.
    assert!(!casts_projected_shadow(&s));
    s.visible = true;
    assert!(casts_projected_shadow(&s));
    s.shadow_enabled = false;
    assert!(!casts_projected_shadow(&s));

    // C++ 817: materials with diffuse alpha 0.98 are left out of the shadow map.
    let mut acc = vac::load_file(&fixture("multi_material.x")).unwrap();
    acc.materials[1].diffuse[3] = 0.98;
    assert_eq!(shadow_map_subsets(&acc).collect::<Vec<_>>(), vec![0, 2]);
    // C++ 249-254.
    assert_eq!(
        projected_shadow_material(0.25),
        ([0.0, 0.0, 0.0, 0.7], [0.25; 4], [0.0, 0.0, 0.0, 1.0])
    );
    // C++ 269.
    acc.materials[0].diffuse[3] = 0.5;
    assert_eq!(drawn_alpha(&acc.materials[0], 0.5), 0.25);
}

#[test]
fn vac_resolves_windows_mesh_names_without_changing_placement() {
    let dir = std::env::temp_dir().join(format!("mds-vac-case-{}", std::process::id()));
    std::fs::create_dir_all(dir.join("Sub")).unwrap();
    std::fs::copy(fixture("cube.x"), dir.join("Sub/mesh.x")).unwrap();
    let original = std::fs::read(fixture("placed.vac")).unwrap();
    let text = String::from_utf8(original)
        .unwrap()
        .replace("cube.x", "Sub\\Mesh.X");
    let path = dir.join("placed.vac");
    std::fs::write(&path, text.as_bytes()).unwrap();
    let acc = vac::load_vac(&path).unwrap();
    assert_eq!(vac::parse(text.as_bytes()).mesh, "Sub\\Mesh.X");
    assert_eq!(acc.vertices.len(), 24);
    assert_eq!(acc.state.scale, 2.5);
    assert_eq!(acc.state.position, [1.0, 2.0, 3.0]);
    assert!(!acc.state.shadow_enabled);
    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn vac_decodes_shift_jis_before_resolving_separators() {
    let dir = std::env::temp_dir().join(format!("mds-vac-sjis-{}", std::process::id()));
    std::fs::create_dir_all(dir.join("Sub")).unwrap();
    std::fs::copy(fixture("cube.x"), dir.join("Sub/表.x")).unwrap();
    let mut text = std::fs::read(fixture("placed.vac")).unwrap();
    let start = text.windows(6).position(|s| s == b"cube.x").unwrap();
    text.splice(start..start + 6, b"sub\\\x95\x5c.X".iter().copied());
    let path = dir.join("placed.vac");
    std::fs::write(&path, &text).unwrap();
    assert_eq!(vac::parse(&text).mesh, "sub\\表.X");
    let acc = vac::load_vac(&path).unwrap();
    assert_eq!(acc.vertices.len(), 24);
    assert_eq!(acc.state.scale, 2.5);
    assert_eq!(acc.state.position, [1.0, 2.0, 3.0]);
    assert!(!acc.state.shadow_enabled);
    std::fs::remove_dir_all(dir).unwrap();
}
