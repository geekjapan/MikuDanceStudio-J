use super::*;

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
pub fn compare_trace(input: &str, expected: &str) -> (usize, usize) {
    let mut expected = expected.lines();
    let mut shapes = [Shape::capsule_y(1.0, 2.0); 2];
    let mut manifold = PairManifold::new(shapes[0], shapes[1]).unwrap();
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
                assert_eq!(words.next().unwrap(), "0");
                shapes = [
                    Shape::capsule_y(scalar(&mut words), scalar(&mut words)),
                    Shape::capsule_y(scalar(&mut words), scalar(&mut words)),
                ];
                manifold = PairManifold::new(shapes[0], shapes[1]).unwrap();
                assert_eq!(manifold.kind(), PairKind::CapsuleCapsule);
                assert!(words.next().is_none());
                continue;
            }
            "T" => {
                bodies = [body(&mut words), body(&mut words)];
                manifold.process(bodies[0], bodies[1]);
                candidates += manifold.contacts().len();
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
            "R" => manifold.refresh(bodies[0].world, bodies[1].world),
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
    (operations, candidates)
}

#[test]
fn native_capsule_capsule_traces_match_production_manifold() {
    let (operations, candidates) = compare_trace(
        include_str!("../capsule_capsule_data/inputs.tsv"),
        include_str!("../capsule_capsule_data/native.tsv"),
    );
    assert_eq!((operations, candidates), (286, 173));
}
