use super::core::math::{Basis, Quat, Transform, Vec3};
use super::core::shape::Shape;

#[test]
fn shape_float_words_match_native_bullet() {
    let mut count = 0;
    for line in include_str!("../shape_data/native.tsv").lines() {
        let columns: Vec<_> = line.split('\t').collect();
        let id: usize = columns[0].parse().unwrap();
        let kind: i32 = columns[1].parse().unwrap();
        let words: Vec<_> = columns[2..]
            .iter()
            .map(|v| u32::from_str_radix(v, 16).unwrap())
            .collect();
        let v: Vec<_> = words.iter().copied().map(f32::from_bits).collect();
        let shape = match kind {
            0 => Shape::Sphere { radius: v[0] },
            1 => Shape::box_shape(Vec3([v[0], v[1], v[2]])),
            2 => Shape::capsule_y(v[0], v[1]),
            3 => Shape::static_plane(Vec3([v[0], v[1], v[2]]), v[3]),
            _ => panic!("invalid fixture kind"),
        };
        let dimensions = match shape {
            Shape::Sphere { radius } => [radius, 0.0, 0.0],
            Shape::Box {
                half_extents_without_margin,
            } => half_extents_without_margin.0,
            Shape::CapsuleY {
                radius,
                half_height,
            } => [radius, half_height, radius],
            Shape::StaticPlane { normal, constant } => {
                assert_eq!(constant.to_bits(), v[3].to_bits());
                normal.0
            }
        };
        let transform = Transform {
            basis: Basis::from_rotation(Quat([v[8], v[9], v[10], v[11]])),
            origin: Vec3([v[5], v[6], v[7]]),
        };
        let (minimum, maximum) = shape.aabb(transform);
        let actual: Vec<_> = [shape.margin()]
            .into_iter()
            .chain(dimensions)
            .chain(shape.local_inertia(v[4]).0)
            .chain(minimum.0)
            .chain(maximum.0)
            .map(f32::to_bits)
            .collect();
        assert_eq!(actual, words[12..], "native shape case {id}, kind {kind}");
        count += 1;
    }
    assert_eq!(count, 288);
}
