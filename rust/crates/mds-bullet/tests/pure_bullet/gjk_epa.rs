use super::core::{
    gjk_epa::{self, PenDepth, QueryResult, Status},
    math::{Basis, Transform, Vec3},
    shape::Shape,
};
fn shape(kind: &str, v: &[f32]) -> Shape {
    match kind {
        "0" => Shape::Sphere { radius: v[0] },
        "1" => Shape::box_shape(Vec3([v[0], v[1], v[2]])),
        "2" => Shape::capsule_y(v[0], v[1]),
        _ => panic!("shape"),
    }
}
fn vector(out: &mut String, v: Vec3) {
    use std::fmt::Write;
    for x in v.0 {
        write!(out, "\t{:08x}", x.to_bits()).unwrap();
    }
}
fn query(out: &mut String, q: QueryResult, success: Status) {
    use std::fmt::Write;
    match q {
        QueryResult::Failure(s) => write!(out, "\t0\t{}", status(s)).unwrap(),
        QueryResult::Success(s) => {
            write!(out, "\t1\t{}", status(success)).unwrap();
            for w in s.witnesses {
                vector(out, w);
            }
            vector(out, s.normal);
            write!(out, "\t{:08x}", s.distance.to_bits()).unwrap();
        }
    }
}
fn status(s: Status) -> u8 {
    match s {
        Status::Separated => 0,
        Status::Penetrating => 1,
        Status::GjkFailed => 2,
        Status::EpaFailed => 3,
    }
}
fn host_native(raw: bool) -> &'static str {
    if cfg!(all(target_os = "macos", target_arch = "aarch64")) {
        if raw {
            include_str!("../gjk_epa_data/raw-native.tsv")
        } else {
            include_str!("../gjk_epa_data/native.tsv")
        }
    } else if cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        if raw {
            include_str!("../gjk_epa_data/raw-native-linux-x64.tsv")
        } else {
            include_str!("../gjk_epa_data/native-linux-x64.tsv")
        }
    } else {
        panic!("unreviewed GJK/EPA host profile; run the native capture workflow")
    }
}

#[test]
fn internal_queries_match_native_words() {
    let full_inputs = std::env::var("MDS_GJK_EPA_INPUTS")
        .ok()
        .map(|p| std::fs::read_to_string(p).unwrap());
    let full_native = std::env::var("MDS_GJK_EPA_NATIVE")
        .ok()
        .map(|p| std::fs::read_to_string(p).unwrap());
    let inputs = full_inputs
        .as_deref()
        .unwrap_or(include_str!("../gjk_epa_data/inputs.tsv"));
    let native = full_native.as_deref().unwrap_or_else(|| host_native(false));
    replay(inputs, native, "MDS_GJK_EPA_ACTUAL");
}

#[test]
fn directed_raw_inputs_match_native_words() {
    let inputs = std::env::var("MDS_GJK_EPA_RAW_INPUTS")
        .ok()
        .map(|p| std::fs::read_to_string(p).unwrap());
    let native = std::env::var("MDS_GJK_EPA_RAW_NATIVE")
        .ok()
        .map(|p| std::fs::read_to_string(p).unwrap());
    replay(
        inputs
            .as_deref()
            .unwrap_or(include_str!("../gjk_epa_data/raw-inputs.tsv")),
        native.as_deref().unwrap_or_else(|| host_native(true)),
        "MDS_GJK_EPA_RAW_ACTUAL",
    );
}

fn replay(inputs: &str, native: &str, output_variable: &str) {
    assert_eq!(inputs.lines().count(), native.lines().count());
    let start: usize = inputs.split_whitespace().next().unwrap().parse().unwrap();
    assert!(start == 0 || start == 6801);
    let mut capture = String::new();
    let mut mismatches = Vec::new();
    for (index, (input, expected)) in inputs.lines().zip(native.lines()).enumerate() {
        let c: Vec<_> = input.split_whitespace().collect();
        assert_eq!(c.len(), 36);
        assert_eq!(c[0], (start + index).to_string());
        let v: Vec<_> = c[3..]
            .iter()
            .map(|s| f32::from_bits(u32::from_str_radix(s, 16).unwrap()))
            .collect();
        let shapes = [shape(c[1], &v), shape(c[2], &v[3..])];
        let transforms = std::array::from_fn(|i| {
            let p = &v[6 + 12 * i..];
            Transform {
                basis: Basis(std::array::from_fn(|r| {
                    std::array::from_fn(|j| p[r * 3 + j])
                })),
                origin: Vec3([p[9], p[10], p[11]]),
            }
        });
        let guess = Vec3([v[30], v[31], v[32]]);
        let mut actual = c[0].to_owned();
        query(
            &mut actual,
            gjk_epa::distance(shapes, transforms, guess),
            Status::Separated,
        );
        query(
            &mut actual,
            gjk_epa::penetration(shapes, transforms, guess, false),
            Status::Penetrating,
        );
        query(
            &mut actual,
            gjk_epa::penetration(shapes, transforms, guess, true),
            Status::Penetrating,
        );
        let (yes, w, n) = match gjk_epa::calc_pen_depth(shapes, transforms) {
            PenDepth::Penetrating(s) => (true, s.witnesses, s.normal),
            PenDepth::Separated(s) => (false, s.witnesses, s.normal),
            PenDepth::Failed => (
                false,
                [Vec3([21.0, 22.0, 23.0]), Vec3([31.0, 32.0, 33.0])],
                Vec3([11.0, 12.0, 13.0]),
            ),
        };
        actual.push_str(if yes { "\t1" } else { "\t0" });
        for v in w {
            vector(&mut actual, v);
        }
        vector(&mut actual, n);
        capture.push_str(&actual);
        capture.push('\n');
        if actual != expected {
            mismatches.push(format!(
                "query {} input {input} actual {actual} expected {expected}",
                c[0]
            ));
        }
    }
    if let Ok(path) = std::env::var(output_variable) {
        let capture = if cfg!(target_os = "windows") {
            capture.replace('\n', "\r\n")
        } else {
            capture
        };
        std::fs::write(path, capture).unwrap();
    }
    assert!(mismatches.is_empty(), "{}", mismatches.join("\n"));
    assert!(!inputs.is_empty());
}
