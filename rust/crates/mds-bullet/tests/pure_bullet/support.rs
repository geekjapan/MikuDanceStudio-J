fn host_native() -> &'static str {
    if cfg!(all(target_os = "macos", target_arch = "aarch64")) {
        include_str!("../support_data/native.tsv")
    } else if cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        include_str!("../support_data/native-linux-x64.tsv")
    } else {
        panic!("unreviewed support host profile; run the native capture workflow")
    }
}

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
    let expected = full_expected.as_deref().unwrap_or_else(|| host_native());
    assert_eq!(inputs.lines().count(), expected.lines().count());
    let mut capture = String::new();
    let mut mismatches = Vec::new();
    for (index, (input, output)) in inputs.lines().zip(expected.lines()).enumerate() {
        let c: Vec<_> = input.split_whitespace().collect();
        assert_eq!(c.len(), 8);
        assert_eq!(c[0], index.to_string());
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
        use std::fmt::Write;
        write!(capture, "{}", c[0]).unwrap();
        for word in &actual {
            write!(capture, "\t{word:08x}").unwrap();
        }
        capture.push('\n');
        let output_fields: Vec<_> = output.split_whitespace().collect();
        assert_eq!(output_fields.len(), 10);
        assert_eq!(output_fields[0], c[0]);
        let words: Vec<_> = output
            .split_whitespace()
            .skip(1)
            .map(|w| u32::from_str_radix(w, 16).unwrap())
            .collect();
        if actual != words {
            mismatches.push(format!(
                "support case {} actual {actual:08x?} expected {words:08x?}",
                c[0]
            ));
        }
    }
    if let Ok(path) = std::env::var("MDS_SUPPORT_ACTUAL") {
        let capture = if cfg!(target_os = "windows") {
            capture.replace('\n', "\r\n")
        } else {
            capture
        };
        std::fs::write(path, capture).unwrap();
    }
    assert!(mismatches.is_empty(), "{}", mismatches.join("\n"));
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
