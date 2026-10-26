use super::*;
use std::fmt::Write;

struct Input<'a>(std::str::SplitWhitespace<'a>);
impl Input<'_> {
    fn word(&mut self) -> f32 {
        f32::from_bits(u32::from_str_radix(self.0.next().unwrap(), 16).unwrap())
    }
    fn integer(&mut self) -> usize {
        self.0.next().unwrap().parse().unwrap()
    }
    fn vector(&mut self) -> Vec3 {
        Vec3(std::array::from_fn(|_| self.word()))
    }
    fn transform(&mut self) -> Transform {
        let origin = self.vector();
        let q = Quat(std::array::from_fn(|_| self.word()));
        Transform {
            origin,
            basis: Basis::from_rotation(q),
        }
    }
    fn body(&mut self) -> ContactBody {
        ContactBody {
            world: self.transform(),
            friction: self.word(),
            restitution: self.word(),
        }
    }
    fn shape(&mut self) -> Shape {
        let kind = self.integer();
        let [a, b, c, d] = std::array::from_fn(|_| self.word());
        match kind {
            0 => Shape::Sphere { radius: a },
            1 => Shape::box_shape(Vec3([a, b, c])),
            2 => Shape::capsule_y(a, b),
            3 => Shape::static_plane(Vec3([a, b, c]), d),
            _ => panic!("unknown shape"),
        }
    }
}
fn word(out: &mut String, f: f32) {
    write!(out, "\t{:08x}", f.to_bits()).unwrap();
}
fn vector(out: &mut String, v: Vec3) {
    for f in v.0 {
        word(out, f);
    }
}

#[test]
fn native_contact_traces_match_every_initialized_bit() {
    let mut expected = include_str!("../contact_data/native.tsv").lines();
    let mut pair =
        PairManifold::new(Shape::Sphere { radius: 1.0 }, Shape::Sphere { radius: 1.0 }).unwrap();
    let mut replaced = [false; 4];
    let mut perturb_only = [false; 2];
    for (row, line) in include_str!("../contact_data/inputs.tsv")
        .lines()
        .enumerate()
    {
        let mut input = Input(line.split_whitespace());
        let op = input.0.next().unwrap();
        let mut out = format!("{row}\t{op}");
        match op {
            "S" => {
                let shape = input.shape();
                let dir = input.vector();
                word(&mut out, shape.angular_motion_disc());
                vector(&mut out, shape.supporting_vertex(dir).unwrap());
                assert_eq!(out, expected.next().unwrap(), "row {row}: {line}");
                continue;
            }
            "N" => {
                let a = input.shape();
                let b = input.shape();
                pair = PairManifold::new(a, b).unwrap();
                assert_eq!(*pair.shapes(), [a, b]);
                assert_eq!(
                    pair.kind(),
                    match (a, b) {
                        (Shape::Sphere { .. }, Shape::Sphere { .. }) => PairKind::SphereSphere,
                        (Shape::StaticPlane { .. }, _) => PairKind::ConvexPlane { swapped: true },
                        _ => PairKind::ConvexPlane { swapped: false },
                    }
                );
            }
            "T" => {
                let a = input.body();
                let b = input.body();
                if let PairKind::ConvexPlane { swapped } = pair.kind() {
                    if pair.count == 0 {
                        let mut probe = PairManifold::new(pair.shapes[0], pair.shapes[1]).unwrap();
                        probe.plane_contact(Quat::IDENTITY, [a, b], swapped);
                        pair.process(a, b);
                        if probe.count == 0 && pair.count > 0 {
                            perturb_only[usize::from(swapped)] = true;
                        }
                    } else {
                        pair.process(a, b);
                    }
                } else {
                    pair.process(a, b);
                }
            }
            "C" => {
                pair.count = 0;
                pair.threshold = input.word();
            }
            "I" => {
                let p = ContactPoint {
                    local_a: input.vector(),
                    local_b: input.vector(),
                    world_a: input.vector(),
                    world_b: input.vector(),
                    normal_on_b: input.vector(),
                    distance: input.word(),
                    combined_friction: input.word(),
                    combined_restitution: input.word(),
                    applied_impulse: input.word(),
                    lateral_impulses: [input.word(), input.word()],
                    lifetime: input.integer() as i32,
                };
                if pair.count == 4 && pair.nearest(p).is_none() {
                    replaced[pair.replacement(p)] = true;
                }
                pair.insert(p);
            }
            "D" => pair.remove(input.integer()),
            "R" => {
                let a = input.transform();
                let b = input.transform();
                pair.refresh(a, b);
            }
            _ => panic!("unknown operation"),
        }
        assert!(input.0.next().is_none());
        write!(out, "\t{}", pair.contacts().len()).unwrap();
        word(&mut out, pair.contact_breaking_threshold());
        for p in pair.contacts() {
            for v in [p.local_a, p.local_b, p.world_a, p.world_b, p.normal_on_b] {
                vector(&mut out, v);
            }
            for f in [
                p.distance,
                p.combined_friction,
                p.combined_restitution,
                p.applied_impulse,
                p.lateral_impulses[0],
                p.lateral_impulses[1],
            ] {
                word(&mut out, f);
            }
            write!(out, "\t{}", p.lifetime).unwrap();
        }
        assert_eq!(out, expected.next().unwrap(), "row {row}: {line}");
    }
    assert!(expected.next().is_none());
    assert_eq!(
        perturb_only, [true; 2],
        "perturb-only contacts in both input orders"
    );
    assert_eq!(
        replaced, [true; 4],
        "all four full-cache replacement slots covered"
    );
}

#[test]
fn unsupported_pairs_have_no_manifold() {
    let b = Shape::box_shape(Vec3([1.0; 3]));
    let c = Shape::capsule_y(1.0, 1.0);
    let p = Shape::static_plane(Vec3([0.0, 1.0, 0.0]), 0.0);
    for (a, b) in [(b, b), (b, c), (c, c), (p, p)] {
        assert!(PairManifold::new(a, b).is_none());
    }
}

#[test]
fn cache_threshold_ties_persistence_and_swap_removal() {
    let mut m =
        PairManifold::new(Shape::Sphere { radius: 1.0 }, Shape::Sphere { radius: 1.0 }).unwrap();
    m.threshold = 0.25;
    let point = |x| ContactPoint {
        local_a: Vec3([x, 0.0, 0.0]),
        distance: -0.1,
        ..ContactPoint::EMPTY
    };
    let seed = ContactPoint {
        lifetime: 17,
        applied_impulse: 3.0,
        lateral_impulses: [-2.0, 4.0],
        ..point(0.0)
    };
    m.insert(seed);
    m.insert(point(0.5));
    assert_eq!(m.nearest(point(0.25)), None, "merge threshold is strict");
    m.threshold = 0.3;
    assert_eq!(
        m.nearest(point(0.25)),
        Some(0),
        "nearest ties keep the first point"
    );
    m.insert(point(0.125));
    assert_eq!(
        (
            m.points[0].lifetime,
            m.points[0].applied_impulse,
            m.points[0].lateral_impulses
        ),
        (17, 3.0, [-2.0, 4.0])
    );
    m.remove(0);
    assert_eq!(
        m.contacts(),
        &[point(0.5)],
        "removal fills the hole with the last slot"
    );

    for (friction, expected) in [
        (-0.0, -0.0),
        (0.0, 0.0),
        (f32::NEG_INFINITY, -10.0),
        (f32::INFINITY, 10.0),
        (f32::NAN, f32::NAN),
    ] {
        let body = ContactBody {
            world: Transform::IDENTITY,
            friction,
            restitution: 0.0,
        };
        m.count = 0;
        m.process(
            body,
            ContactBody {
                friction: 1.0,
                ..body
            },
        );
        assert_eq!(m.contacts().len(), 1);
        let actual = m.contacts()[0].combined_friction;
        if expected.is_nan() {
            assert!(actual.is_nan());
        } else {
            assert_eq!(actual.to_bits(), expected.to_bits());
        }
    }
    m.threshold = f32::NAN;
    m.refresh(Transform::IDENTITY, Transform::IDENTITY);
    assert!(m.contacts().is_empty(), "unordered distances are removed");
}

#[test]
fn full_cache_keeps_deepest_and_uses_earliest_area_tie() {
    let mut m =
        PairManifold::new(Shape::Sphere { radius: 1.0 }, Shape::Sphere { radius: 1.0 }).unwrap();
    let square = [
        Vec3([0.0, 0.0, 0.0]),
        Vec3([1.0, 0.0, 0.0]),
        Vec3([1.0, 1.0, 0.0]),
        Vec3([0.0, 1.0, 0.0]),
    ];
    for deepest in 0..4 {
        m.count = 0;
        for (i, local_a) in square.into_iter().enumerate() {
            m.insert(ContactPoint {
                local_a,
                distance: if i == deepest { -2.0 } else { -0.1 },
                ..ContactPoint::EMPTY
            });
        }
        let next = ContactPoint {
            local_a: Vec3([2.0, 0.5, 0.0]),
            distance: -0.2,
            ..ContactPoint::EMPTY
        };
        assert_ne!(m.replacement(next), deepest);
    }
    for i in 0..4 {
        m.points[i] = ContactPoint {
            local_a: Vec3([i as f32, 0.0, 0.0]),
            distance: -0.1,
            ..ContactPoint::EMPTY
        };
    }
    assert_eq!(
        m.replacement(ContactPoint {
            local_a: Vec3([4.0, 0.0, 0.0]),
            distance: -0.1,
            ..ContactPoint::EMPTY
        }),
        0
    );
}
