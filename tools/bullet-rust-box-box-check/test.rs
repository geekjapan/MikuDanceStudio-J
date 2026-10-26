#![allow(dead_code)]
#[path = "../../rust/crates/mds-bullet/src/core/box_box.rs"]
mod box_box;
#[path = "../../rust/crates/mds-bullet/src/core/math.rs"]
mod math;
#[path = "../../rust/crates/mds-bullet/src/core/shape.rs"]
mod shape;
mod contact {
    include!(env!("BOX_CONTACT_ADAPTER"));
}
use contact::{ContactBody, PairManifold};
use math::{Basis, Transform, Vec3};
use shape::Shape;

fn scalar(words: &mut std::str::SplitWhitespace<'_>) -> f32 {
    f32::from_bits(u32::from_str_radix(words.next().unwrap(), 16).unwrap())
}
fn vector(words: &mut std::str::SplitWhitespace<'_>) -> Vec3 {
    Vec3(std::array::from_fn(|_| scalar(words)))
}
fn body(words: &mut std::str::SplitWhitespace<'_>) -> ContactBody {
    ContactBody {
        world: Transform {
            origin: vector(words),
            basis: Basis(std::array::from_fn(|_| {
                std::array::from_fn(|_| scalar(words))
            })),
        },
        friction: scalar(words),
        restitution: scalar(words),
    }
}
fn word(output: &mut String, value: f32) {
    use std::fmt::Write;
    write!(output, "\t{:08x}", value.to_bits()).unwrap();
}
fn vec_words(output: &mut String, value: Vec3) {
    for v in value.0 {
        word(output, v);
    }
}
fn main() {
    let paths: Vec<String> = std::env::args().collect();
    let input = std::fs::read_to_string(&paths[1]).unwrap();
    let expected = std::fs::read_to_string(&paths[2]).unwrap();
    let mut expected = expected.lines();
    let mut shapes = [Shape::box_shape(Vec3([1.0; 3])); 2];
    let mut manifold = PairManifold::box_test_new(shapes);
    let mut borrowed = false;
    let mut bodies = [ContactBody {
        world: Transform::IDENTITY,
        friction: 0.0,
        restitution: 0.0,
    }; 2];
    let mut operations = 0;
    let mut candidates = 0;
    for line in input.lines() {
        let mut words = line.split_whitespace();
        let op = words.next().unwrap();
        match op {
            "N" => {
                borrowed = words.next().unwrap() == "1";
                shapes = [
                    Shape::box_shape(vector(&mut words)),
                    Shape::box_shape(vector(&mut words)),
                ];
                manifold = PairManifold::box_test_new(shapes);
            }
            "T" => {
                bodies = [body(&mut words), body(&mut words)];
                let points = box_box::box_box_contacts(
                    shapes[0],
                    bodies[0].world,
                    shapes[1],
                    bodies[1].world,
                )
                .unwrap();
                let mut output = format!("C\t{}", points.len());
                candidates += points.len();
                for point in &points {
                    vec_words(&mut output, point.normal_on_b);
                    vec_words(&mut output, point.point_on_b);
                    word(&mut output, point.distance);
                    manifold.box_test_add(*point, bodies);
                }
                assert_eq!(
                    output,
                    expected.next().unwrap(),
                    "candidates at operation {operations}: {line}"
                );
                if !borrowed {
                    manifold.box_test_refresh(bodies);
                }
            }
            "J" => {
                for (i, p) in manifold.contacts_mut().iter_mut().enumerate() {
                    p.applied_impulse = 2.0 + i as f32;
                    p.lateral_impulses = [3.0 + i as f32, 4.0 + i as f32];
                    p.lifetime = 10 + i as i32;
                    p.lateral_initialized = true;
                    p.lateral_directions = [Vec3([1.0, 0.0, 0.0]), Vec3([0.0, 0.0, 1.0])];
                }
            }
            "R" => manifold.box_test_refresh(bodies),
            _ => panic!("unknown operation"),
        }
        assert!(words.next().is_none());
        let mut output = format!("M\t{op}\t{}", manifold.contacts().len());
        word(&mut output, manifold.contact_breaking_threshold());
        for p in manifold.contacts() {
            for v in [p.local_a, p.local_b, p.world_a, p.world_b, p.normal_on_b] {
                vec_words(&mut output, v);
            }
            for v in [
                p.distance,
                p.combined_friction,
                p.combined_restitution,
                p.applied_impulse,
                p.lateral_impulses[0],
                p.lateral_impulses[1],
            ] {
                word(&mut output, v);
            }
            use std::fmt::Write;
            write!(
                output,
                "\t{}\t{}",
                p.lifetime,
                u8::from(p.lateral_initialized)
            )
            .unwrap();
            for direction in if p.lateral_initialized {
                p.lateral_directions
            } else {
                [Vec3::ZERO; 2]
            } {
                vec_words(&mut output, direction);
            }
        }
        assert_eq!(
            output,
            expected.next().unwrap(),
            "manifold at operation {operations}: {line}"
        );
        operations += 1;
    }
    assert!(expected.next().is_none());
    assert!(box_box::box_box_contacts(
        Shape::Sphere { radius: 1.0 },
        Transform::IDENTITY,
        shapes[1],
        Transform::IDENTITY
    )
    .is_none());
    println!(
        "Exact native parity for {operations} operations and {candidates} ordered candidates."
    );
}
