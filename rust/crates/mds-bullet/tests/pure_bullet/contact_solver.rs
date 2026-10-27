use crate::core::body::{BodyInit, RigidBody};
use crate::core::contact::ContactPoint;
use crate::core::contact_solver::{ContactManifold, ContactSolver};
use crate::core::math::{Basis, Transform, Vec3};
use crate::core::solver::ImpulseRow;

struct Words<'a> {
    words: std::str::Split<'a, char>,
    case: usize,
    position: usize,
}
impl Words<'_> {
    fn word(&mut self) -> u32 {
        self.position += 1;
        u32::from_str_radix(self.words.next().unwrap(), 16).unwrap()
    }
    fn float(&mut self) -> f32 {
        f32::from_bits(self.word())
    }
    fn vector(&mut self) -> Vec3 {
        Vec3(std::array::from_fn(|_| self.float()))
    }
    fn expect(&mut self, actual: u32) {
        let expected = self.word();
        assert_eq!(
            actual, expected,
            "case {}, word {}",
            self.case, self.position
        );
    }
    fn scalar(&mut self, actual: f32) {
        self.expect(actual.to_bits());
    }
    fn vec(&mut self, actual: Vec3) {
        for x in actual.0 {
            self.scalar(x);
        }
    }
    fn point(&mut self) -> ContactPoint {
        ContactPoint {
            world_a: self.vector(),
            world_b: self.vector(),
            normal_on_b: self.vector(),
            distance: self.float(),
            combined_friction: self.float(),
            combined_restitution: self.float(),
            applied_impulse: self.float(),
            lateral_impulses: [self.float(), self.float()],
            lifetime: self.word() as i32,
            lateral_initialized: self.word() != 0,
            lateral_directions: [self.vector(), self.vector()],
            ..ContactPoint::EMPTY
        }
    }
    fn check_point(&mut self, p: &ContactPoint) {
        self.vec(p.world_a);
        self.vec(p.world_b);
        self.vec(p.normal_on_b);
        for f in [
            p.distance,
            p.combined_friction,
            p.combined_restitution,
            p.applied_impulse,
            p.lateral_impulses[0],
            p.lateral_impulses[1],
        ] {
            self.scalar(f);
        }
        self.expect(p.lifetime as u32);
        self.expect(u32::from(p.lateral_initialized));
        self.vec(p.lateral_directions[0]);
        self.vec(p.lateral_directions[1]);
    }
    fn row(&mut self, row: ImpulseRow) {
        for i in row.bodies {
            self.expect(i as u32);
        }
        self.vec(row.normal);
        for v in row.angular {
            self.vec(v);
        }
        for v in row.angular_components {
            self.vec(v);
        }
        for f in [
            row.diagonal_inverse,
            row.rhs,
            row.cfm,
            row.lower_impulse,
            row.upper_impulse,
            row.applied_impulse,
        ] {
            self.scalar(f);
        }
    }
}

#[test]
fn native_contact_setup_iterations_and_writeback_match_every_bit() {
    replay_native_contacts(true);
}

#[test]
fn native_contact_unobserved_iteration_and_writeback_match_every_bit() {
    replay_native_contacts(false);
}

fn replay_native_contacts(observe: bool) {
    let mut cases = 0;
    for (case, line) in include_str!("../contact_solver_data/native.tsv")
        .lines()
        .enumerate()
    {
        let mut fields = line.split('\t');
        assert_eq!(fields.next().unwrap().parse::<usize>().unwrap(), case);
        let mut w = Words {
            words: fields,
            case,
            position: 0,
        };
        let dt = w.float();
        let mut bodies: [_; 3] = std::array::from_fn(|_| {
            let mass = w.float();
            let inertia = w.vector();
            let world = Transform {
                basis: Basis(std::array::from_fn(|_| w.vector().0)),
                origin: w.vector(),
            };
            let linear = w.vector();
            let angular = w.vector();
            let lf = w.vector();
            let af = w.vector();
            let mut body = RigidBody::new(BodyInit {
                mass,
                local_inertia: inertia,
                center_of_mass: world,
                linear_damping: 0.0,
                angular_damping: 0.0,
            });
            body.set_linear_velocity(linear);
            body.set_angular_velocity(angular);
            body.set_linear_factor(lf);
            body.set_angular_factor(af);
            body
        });
        let mut owners = [[0; 2]; 2];
        let mut points: [Vec<ContactPoint>; 2] = std::array::from_fn(|mi| {
            owners[mi] = [w.word() as usize, w.word() as usize];
            (0..w.word()).map(|_| w.point()).collect()
        });
        let mut manifolds: Vec<_> = points
            .iter_mut()
            .enumerate()
            .map(|(mi, p)| ContactManifold::new(owners[mi], p))
            .collect();
        let mut solver = ContactSolver::setup(&bodies, &mut manifolds, dt);
        w.expect(solver.normals.len() as u32);
        for row in &solver.normals {
            w.row(row.numeric);
        }
        for row in &solver.frictions {
            w.row(row.numeric);
        }
        w.expect(solver.bodies.len() as u32);
        for body in &solver.bodies {
            w.vec(body.delta_linear);
            w.vec(body.delta_angular);
        }
        for manifold in &manifolds {
            for point in &*manifold.points {
                w.check_point(point);
            }
        }
        let mut events = Vec::new();
        if observe {
            solver.iterate_with_observer(|s, iteration, friction, index| {
                let row = if friction {
                    s.frictions[index].numeric
                } else {
                    s.normals[index].numeric
                };
                let [a, b] = row.bodies.map(|i| s.bodies[i]);
                let mut event = vec![
                    iteration as u32,
                    u32::from(friction),
                    index as u32,
                    row.applied_impulse.to_bits(),
                ];
                for v in [
                    a.delta_linear,
                    a.delta_angular,
                    b.delta_linear,
                    b.delta_angular,
                ] {
                    event.extend(v.0.map(f32::to_bits));
                }
                events.push(event);
            });
        } else {
            solver.iterate();
        }
        solver.writeback(&mut bodies, &mut manifolds);
        for body in &bodies {
            w.vec(body.snapshot().linear_velocity);
            w.vec(body.snapshot().angular_velocity);
        }
        for manifold in &manifolds {
            for point in &*manifold.points {
                w.check_point(point);
            }
        }
        if observe {
            w.expect(events.len() as u32);
            for event in events {
                for word in event {
                    w.expect(word);
                }
            }
            assert!(w.words.next().is_none());
        }
        cases += 1;
    }
    assert_eq!(cases, 144);
}

#[test]
fn material_defaults_and_setters_are_owned_by_rigid_body() {
    let mut body = RigidBody::new(BodyInit {
        mass: 1.0,
        local_inertia: Vec3([1.0; 3]),
        center_of_mass: Transform::IDENTITY,
        linear_damping: 0.0,
        angular_damping: 0.0,
    });
    assert_eq!(body.contact_body().friction, 0.5);
    assert_eq!(body.contact_body().restitution, 0.0);
    body.set_friction(-12.0);
    body.set_restitution(3.0);
    assert_eq!(body.contact_body().friction, -12.0);
    assert_eq!(body.contact_body().restitution, 3.0);
    let moved = Transform {
        origin: Vec3([2.0, 3.0, 4.0]),
        ..Transform::IDENTITY
    };
    body.set_center_of_mass_transform(moved);
    assert_eq!(body.contact_body().world, moved);
}

#[test]
fn native_normal_row_ignores_upper_limit_and_preserves_unordered_sum() {
    use crate::core::solver::{resolve, SolverBody, SolverMode};
    for (case, line) in include_str!("../contact_solver_data/edges.tsv")
        .lines()
        .enumerate()
    {
        let mut w = Words {
            words: line.split('\t'),
            case,
            position: 0,
        };
        let rhs = w.float();
        let body = SolverBody {
            original: None,
            inverse_mass: Vec3::ZERO,
            angular_factor: Vec3([1.0; 3]),
            delta_linear: Vec3::ZERO,
            delta_angular: Vec3::ZERO,
        };
        let mut bodies = [body; 2];
        let mut row = ImpulseRow {
            bodies: [0, 1],
            normal: Vec3([1.0, 0.0, 0.0]),
            angular: [Vec3::ZERO; 2],
            angular_components: [Vec3::ZERO; 2],
            diagonal_inverse: 1.0,
            rhs,
            cfm: 0.0,
            lower_impulse: 0.0,
            upper_impulse: 1e10,
            applied_impulse: 0.0,
        };
        resolve(&mut bodies, &mut row, SolverMode::Simd, true);
        w.scalar(row.applied_impulse);
        for body in bodies {
            w.vec(body.delta_linear);
            w.vec(body.delta_angular);
        }
        assert!(w.words.next().is_none());
    }
}
