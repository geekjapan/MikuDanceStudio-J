use super::core::math::Vec3;
use super::core::shape::Shape;

#[test]
fn nonvirtual_support_matches_native_words() {
    let full_inputs = std::env::var("MDS_SUPPORT_INPUTS")
        .ok()
        .map(|p| std::fs::read_to_string(p).unwrap());
    let full_expected = std::env::var("MDS_SUPPORT_NATIVE")
        .ok()
        .map(|p| std::fs::read_to_string(p).unwrap());
    let inputs = full_inputs
        .as_deref()
        .unwrap_or(include_str!("../support_data/inputs.tsv"));
    let expected = full_expected
        .as_deref()
        .unwrap_or(include_str!("../support_data/native.tsv"));
    assert_eq!(inputs.lines().count(), expected.lines().count());
    for (input, output) in inputs.lines().zip(expected.lines()) {
        let c: Vec<_> = input.split_whitespace().collect();
        let v: Vec<_> = c[2..]
            .iter()
            .map(|w| f32::from_bits(u32::from_str_radix(w, 16).unwrap()))
            .collect();
        let shape = match c[1] {
            "0" => Shape::Sphere { radius: v[0] },
            "1" => Shape::box_shape(Vec3([v[0], v[1], v[2]])),
            "2" => Shape::capsule_y(v[0], v[1]),
            _ => panic!("invalid shape"),
        };
        let d = Vec3([v[3], v[4], v[5]]);
        let actual: Vec<_> = [
            shape
                .supporting_vertex_without_margin_nonvirtual(d)
                .unwrap(),
            shape.supporting_vertex_nonvirtual(d).unwrap(),
            shape.supporting_vertex(d).unwrap(),
        ]
        .into_iter()
        .flat_map(|v| v.0)
        .map(f32::to_bits)
        .collect();
        let words: Vec<_> = output
            .split_whitespace()
            .skip(1)
            .map(|w| u32::from_str_radix(w, 16).unwrap())
            .collect();
        assert_eq!(actual, words, "support case {}", c[0]);
    }
    if full_inputs.is_none() {
        assert_eq!(inputs.lines().count(), 1600);
    }
    let plane = Shape::StaticPlane {
        normal: Vec3([0.0, 1.0, 0.0]),
        constant: 0.0,
    };
    assert_eq!(plane.supporting_vertex_nonvirtual(Vec3::ZERO), None);
    assert_eq!(
        plane.supporting_vertex_without_margin_nonvirtual(Vec3::ZERO),
        None
    );
}
