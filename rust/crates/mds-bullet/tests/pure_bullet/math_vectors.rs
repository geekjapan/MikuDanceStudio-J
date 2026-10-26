//! Standalone native-free primitive gate; only mds-crtmath is required.
#![forbid(unsafe_code)]

use super::core::math::{Basis, Quat, Transform, Vec3};

fn take<const N: usize>(words: &mut impl Iterator<Item = f32>) -> [f32; N] {
    std::array::from_fn(|_| words.next().expect("complete oracle input"))
}
fn basis(words: &mut impl Iterator<Item = f32>) -> Basis {
    Basis(std::array::from_fn(|_| take(words)))
}
fn transform(words: &mut impl Iterator<Item = f32>) -> Transform {
    Transform {
        basis: basis(words),
        origin: Vec3(take(words)),
    }
}
fn append_basis(out: &mut Vec<f32>, basis: Basis) {
    out.extend(basis.0.into_iter().flatten());
}
fn append_transform(out: &mut Vec<f32>, t: Transform) {
    append_basis(out, t.basis);
    out.extend(t.origin.0);
}

#[test]
fn all_primitives_match_vendored_native_bits() {
    let mut counts = [0; 5];
    for (row, line) in include_str!("../data/math-native-bits.tsv")
        .lines()
        .enumerate()
    {
        let mut fields = line.split('\t');
        let op = fields.next().unwrap();
        let mut words = fields.map(|w| f32::from_bits(u32::from_str_radix(w, 16).unwrap()));
        let mut actual = Vec::new();
        match op {
            "vector" => {
                counts[0] += 1;
                let a = Vec3(take(&mut words));
                let b = Vec3(take(&mut words));
                actual.extend(a.add(b).0);
                actual.extend(a.sub(b).0);
                actual.extend(a.negate().0);
                actual.extend(a.cross(b).0);
                actual.extend([a.dot(b), a.length2(), a.length()]);
                actual.extend(a.normalize().0);
                actual.push(a.dot_sse(b));
            }
            "quaternion" => {
                counts[1] += 1;
                let axis = Vec3(take(&mut words));
                let angle = words.next().unwrap();
                let other = Quat(take(&mut words));
                let v = Vec3(take(&mut words));
                let q = Quat::from_axis_angle(axis, angle);
                actual.extend(q.0);
                actual.extend(q.inverse().0);
                actual.extend(q.multiply(other).0);
                actual.extend(q.rotate(v).0);
                actual.push(q.length2());
                actual.extend(q.normalize().0);
                append_basis(&mut actual, Basis::from_rotation(q));
            }
            "basis" => {
                counts[2] += 1;
                let a = basis(&mut words);
                let b = basis(&mut words);
                let v = Vec3(take(&mut words));
                append_basis(&mut actual, a.multiply(b));
                append_basis(&mut actual, a.inverse());
                append_basis(&mut actual, a.transpose());
                actual.extend(a.apply(v).0);
            }
            "transform" => {
                counts[3] += 1;
                let a = transform(&mut words);
                let b = transform(&mut words);
                let v = Vec3(take(&mut words));
                append_transform(&mut actual, a.multiply(b));
                append_transform(&mut actual, a.inverse());
                actual.extend(a.apply(v).0);
                actual.extend(a.inverse_apply(v).0);
                actual.extend(a.basis.rotation().0);
            }
            "integrate" => {
                counts[4] += 1;
                let a = transform(&mut words);
                let linear = Vec3(take(&mut words));
                let angular = Vec3(take(&mut words));
                let dt = words.next().unwrap();
                append_transform(&mut actual, a.integrate(linear, angular, dt));
            }
            _ => panic!("unknown oracle operation {op}"),
        }
        let expected: Vec<u32> = words.map(f32::to_bits).collect();
        let actual: Vec<u32> = actual.into_iter().map(f32::to_bits).collect();
        assert_eq!(actual.len(), expected.len(), "row {row}, {op} field count");
        for (field, (a, e)) in actual.into_iter().zip(expected).enumerate() {
            assert_eq!(
                a, e,
                "native row {row}, {op}, output {field}: {a:08x} != {e:08x}"
            );
        }
    }
    assert_eq!(counts, [49, 25, 16, 25, 1000]);
}

#[test]
fn scalar_and_solver_dot_orders_remain_distinct() {
    let a = Vec3([33554432.0, -33554432.0, 1.0]);
    let b = Vec3([1.0; 3]);
    assert_eq!(a.dot(b).to_bits(), 1.0f32.to_bits());
    assert_eq!(a.dot_sse(b).to_bits(), 0.0f32.to_bits());
    assert_eq!(Basis::from_rotation(Quat::IDENTITY), Basis::IDENTITY);
    assert_eq!(Transform::IDENTITY.apply(a), a);
}
