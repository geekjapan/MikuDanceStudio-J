//! Gate: every output in `tests/fixtures/rust/math/d3dx-vectors.txt` matches bit for bit.

use mds_math::{Mat4, Quat, Vec3};
use std::collections::BTreeMap;

const VECTORS: &str = include_str!("../../../../tests/fixtures/rust/math/d3dx-vectors.txt");
/// The oracle fills outputs with this pattern; a null return leaves it untouched.
const SENTINEL: u32 = 0x3f80_0001;

type Fields<'a> = BTreeMap<&'a str, Vec<u32>>;

fn words<const N: usize>(f: &Fields, key: &str) -> [f32; N] {
    let v = &f[key];
    assert_eq!(v.len(), N, "{key}");
    std::array::from_fn(|i| f32::from_bits(v[i]))
}

fn bits(v: &[f32]) -> Vec<u32> {
    v.iter().map(|x| x.to_bits()).collect()
}

/// Returns `Err(message)` for the first field that differs.
fn check(name: &str, f: &Fields) -> Result<(), String> {
    let ret = f.get("ret").map(|r| r[0] == 1);
    let expect = |key: &str, got: &[f32]| -> Result<(), String> {
        if bits(got) == f[key] {
            Ok(())
        } else {
            Err(format!(
                "{key}: got {:08x?} want {:08x?}",
                bits(got),
                f[key]
            ))
        }
    };
    match name {
        "multiply" => {
            let out = Mat4::multiply(&Mat4(words(f, "a")), &Mat4(words(f, "b")));
            expect("out", &out.0)
        }
        "inverse" => {
            let got = Mat4(words(f, "m")).inverse();
            if got.is_some() != ret.unwrap() {
                return Err(format!("ret: got {} want {:?}", got.is_some(), ret));
            }
            let Some((out, det)) = got else {
                return if f["out"].iter().all(|&w| w == SENTINEL) {
                    Ok(())
                } else {
                    Err("a null return must leave out untouched".into())
                };
            };
            expect("out", &out.0)?;
            if f["detarg"][0] == 1 {
                expect("det", &[det])?;
            }
            Ok(())
        }
        "quatFromMatrix" => expect("out", &Quat::from_matrix(&Mat4(words(f, "m"))).0),
        "vec3Normalize" => expect("out", &Vec3(words(f, "v")).normalize().0),
        "quatMultiply" => expect(
            "out",
            &Quat::multiply(Quat(words(f, "a")), Quat(words(f, "b"))).0,
        ),
        "matrixRotationQuaternion" => {
            expect("out", &Mat4::rotation_quaternion(Quat(words(f, "q"))).0)
        }
        "quatToAxisAngle" => {
            let (axis, angle) = Quat(words(f, "q")).to_axis_angle();
            expect("axis", &axis.0)?;
            expect("angle", &[angle])
        }
        "quatNormalize" => expect("out", &Quat(words(f, "q")).normalize().0),
        "rotX" | "rotY" | "rotZ" => {
            let [angle] = words(f, "angle");
            let out = match name {
                "rotX" => Mat4::rotation_x(angle),
                "rotY" => Mat4::rotation_y(angle),
                _ => Mat4::rotation_z(angle),
            };
            expect("out", &out.0)
        }
        "translation" => {
            let [x, y, z] = words(f, "t");
            expect("out", &Mat4::translation(x, y, z).0)
        }
        other => Err(format!("no implementation for {other}")),
    }
}

#[test]
fn every_vector_matches_bit_for_bit() {
    let mut matched: BTreeMap<&str, usize> = BTreeMap::new();
    let mut total: BTreeMap<&str, usize> = BTreeMap::new();
    let mut summary: BTreeMap<&str, usize> = BTreeMap::new();
    let mut first_miss: Vec<String> = Vec::new();
    for line in VECTORS.lines() {
        let mut parts = line.split_whitespace();
        match parts.next() {
            Some("summary") => {
                parts.next(); // "d3dx"
                let name = parts.next().unwrap();
                summary.insert(name, parts.next().unwrap().parse().unwrap());
            }
            Some("d3dx") => {
                let name = parts.next().unwrap();
                let index = parts.next().unwrap();
                let fields: Fields = parts
                    .map(|kv| {
                        let (k, v) = kv.split_once('=').unwrap();
                        (
                            k,
                            v.split(',')
                                .map(|w| u32::from_str_radix(w, 16).unwrap())
                                .collect(),
                        )
                    })
                    .collect();
                *total.entry(name).or_default() += 1;
                match check(name, &fields) {
                    Ok(()) => *matched.entry(name).or_default() += 1,
                    Err(e) => first_miss.push(format!("{name} {index}: {e}")),
                }
            }
            _ => {}
        }
    }
    assert_eq!(
        total, summary,
        "the file must hold the cases its summary lines promise"
    );
    assert_eq!(total.len(), 12, "every function of the oracle is covered");
    for (name, n) in &total {
        eprintln!("{name}: {}/{n} match", matched.get(name).unwrap_or(&0));
    }
    assert!(
        first_miss.is_empty(),
        "{} mismatches, first: {}",
        first_miss.len(),
        first_miss[0]
    );
}
