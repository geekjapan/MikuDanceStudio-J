use super::core::{
    contact::{ContactBody, PairKind, PairManifold},
    gjk_pair::closest_points,
    math::{Basis, Transform, Vec3},
    shape::Shape,
    simplex::VoronoiSimplexSolver,
};
use std::fmt::Write;
fn shape(kind: &str, v: &[f32]) -> Shape {
    match kind {
        "0" => Shape::Sphere { radius: v[0] },
        "1" => Shape::box_shape(Vec3([v[0], v[1], v[2]])),
        "2" => Shape::capsule_y(v[0], v[1]),
        _ => unreachable!(),
    }
}
fn vector(out: &mut String, v: Vec3) {
    for x in v.0 {
        write!(out, "\t{:08x}", x.to_bits()).unwrap();
    }
}
fn word(out: &mut String, x: f32) {
    write!(out, "\t{:08x}", x.to_bits()).unwrap();
}
#[test]
fn outer_and_persistent_mixed_pairs_match_native_words() {
    let inputs = std::env::var("MDS_GJK_PAIR_INPUTS")
        .ok()
        .map(|p| std::fs::read_to_string(p).unwrap());
    let native = std::env::var("MDS_GJK_PAIR_NATIVE")
        .ok()
        .map(|p| std::fs::read_to_string(p).unwrap());
    replay(
        inputs
            .as_deref()
            .unwrap_or(include_str!("../gjk_pair_data/inputs.tsv")),
        native
            .as_deref()
            .unwrap_or(include_str!("../gjk_pair_data/native.tsv")),
    );
}
fn replay(inputs: &str, native: &str) {
    assert_eq!(inputs.lines().count(), native.lines().count());
    let mut simplex = VoronoiSimplexSolver::default();
    simplex.add_vertex(Vec3([1., 2., 3.]), Vec3([4., 5., 6.]), Vec3([3., 3., 3.]));
    let mut seed = Vec3::ZERO;
    assert!(simplex.closest(&mut seed));
    let mut manifold = None;
    for (input, expected) in inputs.lines().zip(native.lines()) {
        let c: Vec<_> = input.split_whitespace().collect();
        let v: Vec<_> = c[4..]
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
        if c[3] == "1" {
            let m = PairManifold::new(shapes[0], shapes[1]).unwrap();
            assert_eq!(m.kind(), PairKind::ConvexConvex);
            manifold = Some(m);
        }
        let q = closest_points(shapes, transforms, v[30], &mut simplex);
        let mut actual = format!(
            "{}\t{}\t{}\t{}\t{}",
            c[0],
            u8::from(q.contact.is_some()),
            q.method,
            q.iterations,
            q.degeneracy
        );
        vector(&mut actual, q.cached_axis);
        word(&mut actual, q.cached_distance);
        if let Some(p) = q.contact {
            vector(&mut actual, p.normal_on_b);
            vector(&mut actual, p.point_on_b);
            word(&mut actual, p.distance);
        }
        let m = manifold.as_mut().unwrap();
        m.process(
            ContactBody {
                world: transforms[0],
                friction: v[31],
                restitution: v[33],
            },
            ContactBody {
                world: transforms[1],
                friction: v[32],
                restitution: v[34],
            },
            &mut simplex,
        );
        write!(actual, "\t{}", m.contacts().len()).unwrap();
        word(&mut actual, m.contact_breaking_threshold());
        for (i, p) in m.contacts_mut().iter_mut().enumerate() {
            for x in [p.local_a, p.local_b, p.world_a, p.world_b, p.normal_on_b] {
                vector(&mut actual, x);
            }
            for x in [
                p.distance,
                p.combined_friction,
                p.combined_restitution,
                p.applied_impulse,
                p.lateral_impulses[0],
                p.lateral_impulses[1],
            ] {
                word(&mut actual, x);
            }
            write!(
                actual,
                "\t{}\t{}",
                p.lifetime,
                u8::from(p.lateral_initialized)
            )
            .unwrap();
            if p.lateral_initialized {
                for direction in p.lateral_directions {
                    vector(&mut actual, direction);
                }
            }
            p.lateral_initialized = true;
            p.lateral_directions = [Vec3([1.0, 2.0, 3.0]), Vec3([4.0, 5.0, 6.0])];
            p.applied_impulse = 3.25 + i as f32;
            p.lateral_impulses = [0.75, -0.5];
        }
        assert_eq!(actual, expected, "input {input}");
    }
}

#[test]
fn seeded_cache_survives_reset_and_first_support_exit() {
    let mut simplex = VoronoiSimplexSolver::default();
    simplex.add_vertex(Vec3([1.0, 2.0, 3.0]), Vec3([4.0, 5.0, 6.0]), Vec3([3.0; 3]));
    let mut axis = Vec3::ZERO;
    assert!(simplex.closest(&mut axis));
    let query = closest_points(
        [
            Shape::Sphere { radius: 0.75 },
            Shape::box_shape(Vec3([0.8, 0.6, 1.1])),
        ],
        [
            Transform::IDENTITY,
            Transform {
                origin: Vec3([0.0, -1e10, 0.0]),
                ..Transform::IDENTITY
            },
        ],
        0.0,
        &mut simplex,
    );
    assert_eq!(simplex.num_vertices(), 0);
    assert_eq!(simplex.cached_p1, Vec3([4.0, 5.0, 6.0]));
    assert_eq!(simplex.cached_p2, Vec3([3.0; 3]));
    assert_eq!(
        (query.iterations, query.degeneracy, query.method),
        (0, 0, 1)
    );
    assert_eq!(query.contact.unwrap().normal_on_b, Vec3([1.0, 2.0, 3.0]));
    assert!(query.contact.unwrap().distance > 0.0);
}
