use super::core::body::{BodyInit, RigidBody};
use super::core::joint_rows::*;
use super::core::math::{Basis, Transform, Vec3};
use super::core::solver::{GroupSolver, Joint, Phase, RowKind, SolveEvent, SolverMode};
#[cfg(target_arch = "aarch64")]
const NATIVE_PROFILE: &str = include_str!("../solver_data/native.tsv");
#[cfg(target_arch = "x86_64")]
const NATIVE_PROFILE: &str = include_str!("../solver_data/native-x86_64.tsv");
#[cfg(not(any(target_arch = "aarch64", target_arch = "x86_64")))]
compile_error!("joint native fixture supports only aarch64 and x86_64 targets");

struct Words<'a>(std::slice::Iter<'a, u32>);
impl Words<'_> {
    fn word(&mut self) -> u32 {
        *self.0.next().expect("fixture word")
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
    fn motor(&mut self) -> AxisMotor {
        AxisMotor {
            lower: self.scalar(),
            upper: self.scalar(),
            enabled: self.word() != 0,
            target_velocity: self.scalar(),
            max_motor_force: self.scalar(),
            current_position: self.scalar(),
            current_limit: self.word() as u8,
            current_limit_error: self.scalar(),
        }
    }
    fn state(&mut self) -> JointState {
        JointState {
            linear: std::array::from_fn(|_| self.motor()),
            angular: std::array::from_fn(|_| AngularMotor {
                motor: self.motor(),
                erp: self.scalar(),
                bounce: self.scalar(),
            }),
            linear_erp: self.scalar(),
            springs: std::array::from_fn(|_| Spring {
                enabled: self.word() != 0,
                equilibrium: self.scalar(),
                stiffness: self.scalar(),
                damping: self.scalar(),
            }),
        }
    }
}
fn vector(out: &mut Vec<u32>, v: Vec3) {
    out.extend(v.0.map(f32::to_bits));
}
#[test]
fn native_joint_solver_matches_every_setup_iteration_and_writeback_bit() {
    let mut cases = 0;
    let mut previous = None;
    let mut zero_rows = 0;
    let mut row_events = 0;
    let mut checked_words = 0;
    let mut setup_rows = 0;
    let mut spring_targets = [false; 2];
    let mut zero_inertia_cases = [0; 2];
    let mut negative_motor_cases = [0; 2];
    let mut nonzero_equilibrium = false;
    for line in NATIVE_PROFILE.lines() {
        let mut fields = line.split('\t');
        let id = fields.next().unwrap();
        let input: Vec<_> = fields
            .map(|x| u32::from_str_radix(x, 16).unwrap())
            .collect();
        let mut w = Words(input.iter());
        let dt = w.scalar();
        let mode = if w.word() == 260 {
            SolverMode::Simd
        } else {
            SolverMode::Scalar
        };
        let nb = w.word();
        let nj = w.word();
        let mut bodies: Vec<_> = (0..nb)
            .map(|_| {
                let mass = w.scalar();
                let inertia = w.vector();
                let world = w.transform();
                let mut body = RigidBody::new(BodyInit {
                    mass,
                    local_inertia: inertia,
                    center_of_mass: world,
                    linear_damping: 0.0,
                    angular_damping: 0.0,
                });
                body.set_linear_velocity(w.vector());
                body.set_angular_velocity(w.vector());
                body.set_linear_factor(w.vector());
                body.set_angular_factor(w.vector());
                body.set_kinematic(w.word() != 0);
                body
            })
            .collect();
        let mut joints: Vec<_> = (0..nj)
            .map(|_| Joint {
                bodies: [w.word() as usize, w.word() as usize],
                frames: [w.transform(), w.transform()],
                state: w.state(),
            })
            .collect();
        if cases < 512 && cases % 2 == 1 {
            let (prior_bodies, prior_joints): (Vec<RigidBody>, Vec<Joint>) =
                previous.take().unwrap();
            for (a, b) in bodies.iter().zip(&prior_bodies) {
                assert_eq!(a.snapshot(), b.snapshot(), "case {id} repeated body state");
            }
            bodies = prior_bodies;
            joints = prior_joints;
        }
        let mut solver = GroupSolver::setup(&bodies, &mut joints, &mut [], dt, mode);
        for joint in &joints {
            for i in 0..6 {
                let spring = joint.state.springs[i];
                let motor = if i < 3 {
                    joint.state.linear[i]
                } else {
                    joint.state.angular[i - 3].motor
                };
                spring_targets[usize::from(i >= 3)] |=
                    spring.enabled && motor.target_velocity != 0.0;
                nonzero_equilibrium |= spring.enabled && spring.equilibrium != 0.0;
            }
        }
        if (512..516).contains(&cases) {
            assert_eq!(solver.joint_rows.len(), 2);
            for row in &solver.joint_rows {
                assert_eq!(row.diagonal_inverse, f32::INFINITY);
                assert!(row.rhs.is_nan());
                assert_eq!(row.joint_row.lower_impulse, -2.0);
                assert_eq!(row.joint_row.upper_impulse, 2.0);
            }
        }
        if cases >= 516 {
            negative_motor_cases[usize::from(mode == SolverMode::Scalar)] += 1;
            assert_eq!(solver.joint_rows.len(), 2);
            for row in &solver.joint_rows {
                assert!(row.diagonal_inverse.is_finite());
                assert_eq!(row.rhs, 0.0);
                assert_eq!(row.joint_row.lower_impulse, 2.0);
                assert_eq!(row.joint_row.upper_impulse, -2.0);
            }
        }
        setup_rows += solver.joint_rows.len();
        let original_worlds: Vec<_> = bodies.iter().map(|body| body.snapshot().world).collect();
        let expected: Vec<_> = w.0.copied().collect();
        let mut actual = vec![solver.joint_rows.len() as u32];
        for r in &solver.joint_rows {
            actual.extend(r.bodies.map(|i| i as u32));
            for v in [
                r.joint_row.j1_linear,
                r.joint_row.j1_angular,
                r.joint_row.j2_angular,
                r.angular_components[0],
                r.angular_components[1],
            ] {
                vector(&mut actual, v);
            }
            actual.extend(
                [
                    r.diagonal_inverse,
                    r.rhs,
                    r.joint_row.cfm,
                    r.joint_row.lower_impulse,
                    r.joint_row.upper_impulse,
                    r.applied_impulse,
                ]
                .map(f32::to_bits),
            );
        }
        let mut trace = Vec::new();
        zero_rows += usize::from(solver.joint_rows.is_empty());
        if mode == SolverMode::Simd {
            solver.iterate(&bodies, &joints, |solver, event| {
                let SolveEvent::Row {
                    kind: RowKind::Joint,
                    phase: Phase::After,
                    index,
                    ..
                } = event
                else {
                    return;
                };
                row_events += 1;
                let r = solver.joint_rows[index];
                trace.push(r.applied_impulse.to_bits());
                for i in r.bodies {
                    let b = solver.bodies.entries[i];
                    vector(&mut trace, b.delta_linear);
                    vector(&mut trace, b.delta_angular);
                }
            });
        } else {
            solver.iterate(&bodies, &joints, |_, _| {});
        }
        let final_rows = solver.joint_rows.clone();
        solver.writeback(&mut bodies, &mut []);
        if (512..516).contains(&cases) {
            let simd = mode == SolverMode::Simd;
            zero_inertia_cases[usize::from(!simd)] += 1;
            for row in &final_rows {
                if simd {
                    assert_eq!(row.applied_impulse, row.joint_row.upper_impulse);
                } else {
                    assert!(row.applied_impulse.is_nan());
                }
            }
            for body in &bodies {
                let state = body.snapshot();
                for value in state
                    .linear_velocity
                    .0
                    .into_iter()
                    .chain(state.angular_velocity.0)
                {
                    assert_eq!(value.is_finite(), simd);
                }
            }
        }
        for (b, world) in bodies.iter().zip(original_worlds) {
            let s = b.snapshot();
            assert_eq!(s.world, world, "case {id} must not integrate transforms");
            vector(&mut actual, s.linear_velocity);
            vector(&mut actual, s.angular_velocity);
        }
        actual.extend(final_rows.iter().map(|r| r.applied_impulse.to_bits()));
        actual.extend(trace);
        assert_eq!(actual.len(), expected.len(), "case {id} words");
        for (index, (a, b)) in actual.iter().zip(&expected).enumerate() {
            assert_eq!(a, b, "case {id} word {index}: Rust {a:08x}, native {b:08x}");
        }
        checked_words += actual.len();
        previous = Some((bodies, joints));
        cases += 1;
    }
    assert_eq!(cases, 518);
    assert_eq!(negative_motor_cases, [1, 1]);
    assert_eq!(zero_inertia_cases, [2, 2]);
    assert!(zero_rows >= 4);
    assert_eq!(row_events, 20_580);
    assert!(spring_targets.into_iter().all(|seen| seen));
    assert!(nonzero_equilibrium);
    println!("{cases} solves, {setup_rows} setup rows, {row_events} SIMD row events, {zero_rows} zero-row solves, {checked_words} output words");
}
