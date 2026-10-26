//! Replay real native body operation fixtures, comparing every initialized word.
use crate::core::body::{BodyInit, BodySnapshot, RigidBody};
use crate::core::math::{Basis, Transform, Vec3};
use crate::core::shape::Shape;

fn vector(values: &mut impl Iterator<Item = f32>) -> Vec3 {
    Vec3(std::array::from_fn(|_| values.next().unwrap()))
}

fn transform(values: &mut impl Iterator<Item = f32>) -> Transform {
    Transform {
        basis: Basis(std::array::from_fn(|_| vector(values).0)),
        origin: vector(values),
    }
}

fn transform_words(t: Transform) -> impl Iterator<Item = f32> {
    t.basis.0.into_iter().flatten().chain(t.origin.0)
}

fn words(s: BodySnapshot) -> Vec<u32> {
    let mut result: Vec<u32> = [s.inverse_mass]
        .into_iter()
        .chain(s.inverse_inertia_local.0)
        .chain(s.inverse_inertia_world.0.into_iter().flatten())
        .chain(transform_words(s.world))
        .chain(transform_words(s.interpolation_world))
        .chain(s.linear_velocity.0)
        .chain(s.angular_velocity.0)
        .chain(s.interpolation_linear_velocity.0)
        .chain(s.interpolation_angular_velocity.0)
        .chain(s.gravity_acceleration.0)
        .chain(s.gravity_force.0)
        .chain(s.total_force.0)
        .chain(s.total_torque.0)
        .chain([s.linear_damping, s.angular_damping])
        .map(f32::to_bits)
        .collect();
    result.extend([u32::from(s.is_static), u32::from(s.is_kinematic)]);
    result
}

#[test]
fn real_bullet_body_operations_match_every_float_bit() {
    let fixture = std::env::var("MDS_BODY_FIXTURE")
        .map(|path| std::fs::read_to_string(path).unwrap())
        .unwrap_or_else(|_| include_str!("../body_data/native.tsv").to_owned());
    let mut body = None;
    let mut count = 0;
    let mut signed_zero_constructors = 0;
    let mut signed_zero_commits = std::collections::BTreeSet::new();
    let mut operations = std::collections::BTreeSet::new();
    let mut shape_kinds = std::collections::BTreeSet::new();
    let mut flags = std::collections::BTreeSet::new();
    let mut angular_inputs = std::collections::BTreeSet::new();
    let mut mass_kinds = std::collections::BTreeSet::new();
    let mut damping_clamps = std::collections::BTreeSet::new();
    let mut inertia_cases = std::collections::BTreeSet::new();
    let mut basis_cases = std::collections::BTreeSet::new();
    let mut block_counts = std::collections::BTreeMap::<usize, usize>::new();
    let mut block_length = 0;
    for (row, line) in fixture.lines().enumerate() {
        let (input, output) = line.split_once('|').unwrap();
        let mut tokens = input.split_whitespace();
        let op = tokens.next().unwrap();
        let mut values = tokens.map(|s| f32::from_bits(u32::from_str_radix(s, 16).unwrap()));
        operations.insert(op.to_owned());
        if op == "N" {
            if block_length != 0 {
                *block_counts.entry(block_length).or_default() += 1;
            }
            block_length = 0;
            let mass = values.next().unwrap();
            let linear_damping = values.next().unwrap();
            let angular_damping = values.next().unwrap();
            let kind = values.next().unwrap() as u32;
            shape_kinds.insert(kind);
            mass_kinds.insert(if mass == 0.0 {
                0
            } else if mass < 0.0 {
                1
            } else {
                2
            });
            damping_clamps.insert(if linear_damping < 0.0 {
                0
            } else if angular_damping > 1.0 {
                1
            } else {
                2
            });
            // The same constructor checks both sides of the clamp.
            if angular_damping > 1.0 {
                damping_clamps.insert(1);
            }
            let dims = vector(&mut values);
            let shape = match kind {
                0 => Shape::Sphere { radius: dims.0[0] },
                1 => Shape::box_shape(dims),
                2 => Shape::capsule_y(dims.0[0], dims.0[1]),
                3 => Shape::static_plane(dims, 0.7),
                _ => panic!("shape kind"),
            };
            let center_of_mass = transform(&mut values);
            basis_cases.insert(
                center_of_mass
                    .basis
                    .0
                    .into_iter()
                    .flatten()
                    .map(f32::to_bits)
                    .collect::<Vec<_>>(),
            );
            let custom = values.next().unwrap() != 0.0;
            let inertia = vector(&mut values);
            if custom {
                let nonzero = inertia.0.iter().filter(|v| **v != 0.0).count();
                inertia_cases.insert((kind, nonzero));
            }
            body = Some(RigidBody::new(BodyInit {
                mass,
                local_inertia: if custom {
                    inertia
                } else {
                    shape.local_inertia(mass)
                },
                center_of_mass,
                linear_damping,
                angular_damping,
            }));
            let snapshot = body.as_ref().unwrap().snapshot();
            let expected: Vec<_> = transform_words(center_of_mass).map(f32::to_bits).collect();
            assert_eq!(
                transform_words(snapshot.world)
                    .map(f32::to_bits)
                    .collect::<Vec<_>>(),
                expected
            );
            assert_eq!(
                transform_words(snapshot.interpolation_world)
                    .map(f32::to_bits)
                    .collect::<Vec<_>>(),
                expected
            );
            if expected.contains(&(-0.0_f32).to_bits()) {
                signed_zero_constructors += 1;
            }
        }
        block_length += 1;
        let b = body.as_mut().unwrap();
        let mut prediction = None;
        match op {
            "N" => (),
            "M" => b.set_mass_properties(values.next().unwrap(), vector(&mut values)),
            "U" => b.update_inertia_tensor(),
            "G" => b.set_gravity(vector(&mut values)),
            "F" => b.add_force(vector(&mut values)),
            "T" => b.add_torque(vector(&mut values)),
            "A" => b.apply_gravity(),
            "I" => b.integrate_velocities(values.next().unwrap()),
            "D" => b.apply_damping(values.next().unwrap()),
            "P" => prediction = Some(b.predict_transform(values.next().unwrap())),
            "C" => {
                let center_of_mass = transform(&mut values);
                let before = b.snapshot();
                b.set_center_of_mass_transform(center_of_mass);
                if transform_words(center_of_mass).any(|v| v.to_bits() == (-0.0_f32).to_bits()) {
                    signed_zero_commits.insert((before.is_static, before.is_kinematic));
                    let interpolation = if before.is_static || before.is_kinematic {
                        before.world
                    } else {
                        center_of_mass
                    };
                    let after = b.snapshot();
                    assert_eq!(
                        transform_words(after.world)
                            .map(f32::to_bits)
                            .collect::<Vec<_>>(),
                        transform_words(center_of_mass)
                            .map(f32::to_bits)
                            .collect::<Vec<_>>()
                    );
                    assert_eq!(
                        transform_words(after.interpolation_world)
                            .map(f32::to_bits)
                            .collect::<Vec<_>>(),
                        transform_words(interpolation)
                            .map(f32::to_bits)
                            .collect::<Vec<_>>()
                    );
                }
            }
            "Z" => b.clear_forces(),
            "L" => b.set_linear_velocity(vector(&mut values)),
            "W" => {
                let velocity = vector(&mut values);
                angular_inputs.insert(velocity.0[0].to_bits());
                b.set_angular_velocity(velocity);
            }
            "K" => b.set_kinematic(values.next().unwrap() != 0.0),
            _ => panic!("unknown operation {op}"),
        }
        assert!(values.next().is_none(), "unconsumed inputs at row {row}");
        let snapshot = b.snapshot();
        flags.insert((snapshot.is_static, snapshot.is_kinematic));
        let mut actual = words(snapshot);
        if let Some(t) = prediction {
            actual.extend(transform_words(t).map(f32::to_bits));
        }
        let expected: Vec<u32> = output
            .split_whitespace()
            .map(|s| u32::from_str_radix(s, 16).unwrap())
            .collect();
        assert_eq!(actual.len(), expected.len(), "row {row} operation {op}");
        for (index, (actual, expected)) in actual.iter().zip(&expected).enumerate() {
            assert_eq!(actual, expected,
                "row {row} operation {op} word {index}: actual {actual:08x}, expected {expected:08x}");
        }
        count += 1;
    }
    *block_counts.entry(block_length).or_default() += 1;
    // 144 shape/mass/basis/damping traces, 14 angular traces, 36 custom-inertia
    // traces, one gravity/mass transition trace and three signed-zero COM traces.
    assert_eq!(
        count,
        4 * 4 * 3 * 3 * 32 + 7 * 2 * 13 + 4 * 3 * 3 * 12 + 10 + 3 * 5
    );
    assert_eq!(
        block_counts,
        [(5, 3), (10, 1), (12, 36), (13, 14), (32, 144)].into()
    );
    assert_eq!(
        operations,
        ["N", "M", "U", "G", "F", "T", "A", "I", "D", "P", "C", "Z", "L", "W", "K"]
            .map(str::to_owned)
            .into()
    );
    assert_eq!(shape_kinds, [0, 1, 2, 3].into());
    assert_eq!(mass_kinds, [0, 1, 2].into());
    assert_eq!(damping_clamps, [0, 1, 2].into());
    assert_eq!(basis_cases.len(), 4);
    assert_eq!(signed_zero_constructors, 3);
    assert_eq!(
        signed_zero_commits,
        [(false, false), (true, false), (false, true)].into()
    );
    assert_eq!(
        flags,
        [(false, false), (false, true), (true, false), (true, true)].into()
    );
    for kind in 0..4 {
        for nonzero in 0..3 {
            assert!(inertia_cases.contains(&(kind, nonzero)));
        }
    }
    let half_pi = std::f32::consts::PI * 0.5;
    for speed in [
        half_pi - f32::EPSILON / 2.0,
        half_pi,
        half_pi + f32::EPSILON / 2.0,
        1000.0,
        0.00001,
        0.0,
        -0.0,
    ] {
        assert!(angular_inputs.contains(&speed.to_bits()));
    }
}

struct FactorWords<'a>(std::slice::Iter<'a, u32>);
impl FactorWords<'_> {
    fn word(&mut self) -> u32 {
        *self.0.next().expect("factor fixture word")
    }
    fn scalar(&mut self) -> f32 {
        f32::from_bits(self.word())
    }
    fn vector(&mut self) -> Vec3 {
        Vec3(std::array::from_fn(|_| self.scalar()))
    }
    fn transform(&mut self) -> Transform {
        Transform {
            basis: Basis(std::array::from_fn(|_| self.vector().0)),
            origin: self.vector(),
        }
    }
}
fn factor_snapshot(body: &RigidBody, output: &mut Vec<u32>) {
    let s = body.snapshot();
    for v in [
        body.linear_factor(),
        body.angular_factor(),
        s.total_force,
        s.total_torque,
        s.gravity_acceleration,
        s.linear_velocity,
        s.angular_velocity,
    ] {
        output.extend(v.0.map(f32::to_bits));
    }
    for row in s.inverse_inertia_world.0 {
        output.extend(row.map(f32::to_bits));
    }
    output.push(s.inverse_mass.to_bits());
}
#[test]
fn nonunit_factors_affect_existing_body_operations_like_native() {
    let mut cases = 0;
    for line in include_str!("../solver_data/factors.tsv").lines() {
        let mut fields = line.split('\t');
        let id = fields.next().unwrap();
        let input: Vec<_> = fields
            .map(|x| u32::from_str_radix(x, 16).unwrap())
            .collect();
        let mut w = FactorWords(input.iter());
        let mass = w.scalar();
        let inertia = w.vector();
        let world = w.transform();
        let lf = w.vector();
        let af = w.vector();
        let force = w.vector();
        let torque = w.vector();
        let gravity = w.vector();
        let dt = w.scalar();
        let kin = w.word() != 0;
        let expected: Vec<_> = w.0.copied().collect();
        let mut actual = Vec::new();
        let mut body = RigidBody::new(BodyInit {
            mass,
            local_inertia: inertia,
            center_of_mass: world,
            linear_damping: 0.0,
            angular_damping: 0.0,
        });
        body.set_kinematic(kin);
        body.set_linear_factor(lf);
        body.set_angular_factor(af);
        body.set_gravity(gravity);
        factor_snapshot(&body, &mut actual);
        body.add_force(force);
        body.add_torque(torque);
        factor_snapshot(&body, &mut actual);
        body.apply_gravity();
        factor_snapshot(&body, &mut actual);
        body.integrate_velocities(dt);
        factor_snapshot(&body, &mut actual);
        body.clear_forces();
        factor_snapshot(&body, &mut actual);
        body.set_linear_factor(af);
        body.set_angular_factor(lf);
        body.add_force(force);
        body.add_torque(torque);
        factor_snapshot(&body, &mut actual);
        assert_eq!(actual, expected, "factor case {id}");
        cases += 1;
    }
    assert_eq!(cases, 64);
}
