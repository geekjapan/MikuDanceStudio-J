#[path = "../../rust/crates/mds-bullet/src/core/activation.rs"]
pub mod activation;
#[path = "../../rust/crates/mds-bullet/src/core/islands.rs"]
pub mod islands;
extern crate bullet_core_support as base;
pub use base::{joint_coordinates, joint_rows, math, time, InvalidArgument};
#[path = "../../rust/crates/mds-bullet/src/core/body.rs"]
pub mod body;
#[path = "../../rust/crates/mds-bullet/src/core/box_box.rs"]
pub mod box_box;
#[path = "../../rust/crates/mds-bullet/src/core/contact.rs"]
pub mod contact;
#[path = "../../rust/crates/mds-bullet/src/core/contact_solver.rs"]
pub mod contact_solver;
#[path = "../../rust/crates/mds-bullet/src/core/gjk_epa.rs"]
pub mod gjk_epa;
#[path = "../../rust/crates/mds-bullet/src/core/gjk_pair.rs"]
pub mod gjk_pair;
#[allow(dead_code)]
#[path = "../../rust/crates/mds-bullet/src/core/shape.rs"]
pub mod shape;
#[path = "../../rust/crates/mds-bullet/src/core/simplex.rs"]
pub mod simplex;
#[path = "../../rust/crates/mds-bullet/src/core/solver.rs"]
pub mod solver;
use body::{BodyInit, RigidBody};
use contact::ContactPoint;
use contact_solver::ContactManifold;
use joint_rows::{AngularMotor, AxisMotor, JointState, Spring};
use math::{Basis, Transform, Vec3};
use solver::{
    GroupSelection, GroupSolver, ImpulseRow, Joint, Phase, RowKind, SolveEvent, SolverMode,
    SolverWorkspace,
};
use std::io::Write;
struct Reader<'a>(std::str::SplitWhitespace<'a>);
impl Reader<'_> {
    fn word(&mut self) -> u32 {
        u32::from_str_radix(self.0.next().expect("input word"), 16).unwrap()
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
    fn point(&mut self) -> ContactPoint {
        ContactPoint {
            local_a: self.vector(),
            local_b: self.vector(),
            world_a: self.vector(),
            world_b: self.vector(),
            normal_on_b: self.vector(),
            distance: self.scalar(),
            combined_friction: self.scalar(),
            combined_restitution: self.scalar(),
            applied_impulse: self.scalar(),
            lateral_impulses: [self.scalar(), self.scalar()],
            lifetime: self.word() as i32,
            lateral_initialized: self.word() != 0,
            lateral_directions: [self.vector(), self.vector()],
        }
    }
}
fn vector(w: &mut Vec<u32>, v: Vec3) {
    w.extend(v.0.map(f32::to_bits));
}
fn transform(w: &mut Vec<u32>, t: Transform) {
    for v in t.basis.0 {
        vector(w, Vec3(v));
    }
    vector(w, t.origin);
}
fn point(w: &mut Vec<u32>, p: ContactPoint) {
    for v in [p.local_a, p.local_b, p.world_a, p.world_b, p.normal_on_b] {
        vector(w, v);
    }
    w.extend(
        [
            p.distance,
            p.combined_friction,
            p.combined_restitution,
            p.applied_impulse,
            p.lateral_impulses[0],
            p.lateral_impulses[1],
        ]
        .map(f32::to_bits),
    );
    w.extend([p.lifetime as u32, u32::from(p.lateral_initialized)]);
    for v in p.lateral_directions {
        vector(w, v);
    }
}
fn originals(
    w: &mut Vec<u32>,
    bodies: &[RigidBody],
    manifolds: &[ContactManifold<'_>],
    companions: Option<&[i32]>,
) {
    w.push(bodies.len() as u32);
    for (i, b) in bodies.iter().enumerate() {
        if let Some(companions) = companions {
            w.push(companions[i] as u32);
        }
        let bstate = b.snapshot();
        transform(w, bstate.world);
        for v in [
            bstate.linear_velocity,
            bstate.angular_velocity,
            b.linear_factor(),
            b.angular_factor(),
        ] {
            vector(w, v);
        }
        w.push(bstate.inverse_mass.to_bits());
        vector(w, bstate.inverse_inertia_local);
        for v in bstate.inverse_inertia_world.0 {
            vector(w, Vec3(v));
        }
        vector(w, bstate.total_force);
        vector(w, bstate.total_torque);
        w.extend([
            b.contact_body().friction.to_bits(),
            b.contact_body().restitution.to_bits(),
        ]);
        transform(w, bstate.interpolation_world);
        for v in [
            bstate.interpolation_linear_velocity,
            bstate.interpolation_angular_velocity,
            bstate.gravity_acceleration,
        ] {
            vector(w, v);
        }
        w.extend([
            bstate.linear_damping.to_bits(),
            bstate.angular_damping.to_bits(),
            u32::from(bstate.is_static),
            u32::from(bstate.is_kinematic),
        ]);
    }
    w.push(manifolds.len() as u32);
    for m in manifolds {
        w.push(m.points.len() as u32);
        for &p in m.points.iter() {
            point(w, p);
        }
    }
}
fn row(w: &mut Vec<u32>, r: ImpulseRow) {
    w.extend(r.bodies.map(|i| i as u32));
    for v in [
        r.normal,
        r.angular[0],
        r.angular[1],
        r.angular_components[0],
        r.angular_components[1],
    ] {
        vector(w, v);
    }
    w.extend(
        [
            r.diagonal_inverse,
            r.rhs,
            r.cfm,
            r.lower_impulse,
            r.upper_impulse,
            r.applied_impulse,
        ]
        .map(f32::to_bits),
    );
}
fn numeric(r: solver::SolverRow) -> ImpulseRow {
    ImpulseRow {
        bodies: r.bodies,
        normal: r.joint_row.j1_linear,
        angular: [r.joint_row.j1_angular, r.joint_row.j2_angular],
        angular_components: r.angular_components,
        diagonal_inverse: r.diagonal_inverse,
        rhs: r.rhs,
        cfm: r.joint_row.cfm,
        lower_impulse: r.joint_row.lower_impulse,
        upper_impulse: r.joint_row.upper_impulse,
        applied_impulse: r.applied_impulse,
    }
}
fn snapshot(s: &GroupSolver, bodies: &[RigidBody], manifolds: &[ContactManifold<'_>]) -> Vec<u32> {
    let mut w = vec![s.bodies.live_len() as u32];
    for b in s.bodies.live_entries() {
        w.push(b.original.map_or(u32::MAX, |i| i as u32));
        for v in [
            b.inverse_mass,
            b.angular_factor,
            b.delta_linear,
            b.delta_angular,
            Vec3::ZERO,
            Vec3::ZERO,
        ] {
            vector(&mut w, v);
        }
    }
    w.push(s.joint_rows.len() as u32);
    for &r in &s.joint_rows {
        row(&mut w, numeric(r));
        w.extend([0, 0, 0, 0, 0, 1]);
    }
    w.push(s.normals.len() as u32);
    for (index, r) in s.normals.iter().enumerate() {
        row(&mut w, r.numeric);
        w.extend(r.point.map(|i| i as u32));
        w.push(r.friction.to_bits());
        w.extend([0, 0, index as u32]);
    }
    w.push(s.frictions.len() as u32);
    for r in &s.frictions {
        row(&mut w, r.numeric);
        w.push(r.normal_index as u32);
        w.extend([
            0,
            s.normals[r.normal_index].friction.to_bits(),
            u32::MAX,
            u32::MAX,
            1,
        ]);
    }
    originals(
        &mut w,
        bodies,
        manifolds,
        Some(
            &(0..bodies.len())
                .map(|i| s.bodies.companion_id(i).map_or(-1, |id| id as i32))
                .collect::<Vec<_>>(),
        ),
    );
    w
}
fn emit(out: &mut impl Write, prefix: &str, words: Vec<u32>) {
    write!(out, "{prefix}").unwrap();
    for w in words {
        write!(out, "\t{w:08x}").unwrap();
    }
    writeln!(out).unwrap();
}
fn main() {
    let args: Vec<_> = std::env::args().collect();
    let input = std::fs::read_to_string(&args[1]).unwrap();
    let mut trace = std::io::BufWriter::new(std::fs::File::create(&args[2]).unwrap());
    let mut output = std::io::BufWriter::new(std::io::stdout());
    for line in input.lines() {
        let mut r = Reader(line.split_whitespace());
        let case = r.0.next().unwrap().parse::<usize>().unwrap();
        let dt = r.scalar();
        let mode = match r.word() {
            260 => SolverMode::Simd,
            4 => SolverMode::Scalar,
            _ => panic!("mode"),
        };
        let nb = r.word();
        let steps = r.word();
        let mut bodies: Vec<_> = (0..nb)
            .map(|_| {
                let mass = r.scalar();
                let inertia = r.vector();
                let world = r.transform();
                let mut b = RigidBody::new(BodyInit {
                    mass,
                    local_inertia: inertia,
                    center_of_mass: world,
                    linear_damping: 0.,
                    angular_damping: 0.,
                });
                b.set_linear_velocity(r.vector());
                b.set_angular_velocity(r.vector());
                b.set_linear_factor(r.vector());
                b.set_angular_factor(r.vector());
                b.set_kinematic(r.word() != 0);
                b
            })
            .collect();
        let nj = r.word();
        let mut joints: Vec<_> = (0..nj)
            .map(|_| {
                let ids = [r.word() as usize, r.word() as usize];
                let frames = [r.transform(), r.transform()];
                let empty = AxisMotor {
                    lower: 1.,
                    upper: -1.,
                    enabled: false,
                    target_velocity: 0.,
                    max_motor_force: 0.,
                    current_position: 0.,
                    current_limit: 0,
                    current_limit_error: 0.,
                };
                let mut state = JointState {
                    linear: [empty; 3],
                    angular: [AngularMotor {
                        motor: empty,
                        erp: 0.5,
                        bounce: 0.,
                    }; 3],
                    linear_erp: 0.5,
                    springs: [Spring {
                        enabled: false,
                        equilibrium: 0.,
                        stiffness: 0.,
                        damping: 0.,
                    }; 6],
                };
                for axis in 0..6 {
                    let motor = AxisMotor {
                        lower: r.scalar(),
                        upper: r.scalar(),
                        enabled: r.word() != 0,
                        target_velocity: r.scalar(),
                        max_motor_force: r.scalar(),
                        ..empty
                    };
                    state.springs[axis] = Spring {
                        enabled: r.word() != 0,
                        equilibrium: r.scalar(),
                        stiffness: r.scalar(),
                        damping: r.scalar(),
                    };
                    if axis < 3 {
                        state.linear[axis] = motor;
                    } else {
                        state.angular[axis - 3].motor = motor;
                    }
                }
                Joint {
                    bodies: ids,
                    frames,
                    state,
                }
            })
            .collect();
        let nm = r.word();
        let mut owners = Vec::new();
        let mut thresholds = Vec::new();
        let mut points: Vec<Vec<_>> = (0..nm)
            .map(|_| {
                owners.push([r.word() as usize, r.word() as usize]);
                thresholds.push(r.scalar());
                let n = r.word();
                (0..n).map(|_| r.point()).collect()
            })
            .collect();
        assert!(r.0.next().is_none());
        let mut manifolds: Vec<_> = points
            .iter_mut()
            .enumerate()
            .map(|(i, p)| ContactManifold {
                bodies: owners[i],
                points: p,
                processing_threshold: thresholds[i],
            })
            .collect();
        for step in 0..steps {
            let mut workspace = SolverWorkspace::default();
            let mut objects: Vec<_> = (0..bodies.len())
                .map(|_| crate::islands::IslandObject {
                    activation: crate::activation::BodyActivation::default(),
                    classification: crate::activation::CollisionClassification::Dynamic,
                    contact_response: true,
                    island_tag: -1,
                    companion_id: -1,
                    hit_fraction: 1.0,
                })
                .collect();
            let body_indices: Vec<_> = (0..bodies.len()).collect();
            let joint_indices: Vec<_> = (0..joints.len()).collect();
            let manifold_indices: Vec<_> = (0..manifolds.len()).collect();
            let selection = GroupSelection {
                bodies: &body_indices,
                joints: &joint_indices,
                manifolds: &manifold_indices,
            };
            let mut s = GroupSolver::setup(
                &mut workspace,
                &mut objects,
                &bodies,
                &mut joints,
                &mut manifolds,
                selection,
                dt,
                mode,
            )
            .unwrap();
            emit(
                &mut trace,
                &format!("{case}\t{step}\t0\t-1\t-1"),
                snapshot(&s, &bodies, &manifolds),
            );
            s.iterate(&bodies, &joints, |s, event| {
                let (kind, it, index) = match event {
                    SolveEvent::Row {
                        kind,
                        phase,
                        iteration,
                        index,
                    } => {
                        let k = match kind {
                            RowKind::Joint => 1,
                            RowKind::Normal => 3,
                            RowKind::Friction => 5,
                        };
                        (k + usize::from(phase == Phase::After), iteration, index)
                    }
                    SolveEvent::Obsolete {
                        phase,
                        iteration,
                        joint,
                        ..
                    } => (7 + usize::from(phase == Phase::After), iteration, joint),
                    SolveEvent::FrictionSkipped { iteration, index } => (9, iteration, index),
                };
                emit(
                    &mut trace,
                    &format!("{case}\t{step}\t{kind}\t{it}\t{index}"),
                    snapshot(s, &bodies, &manifolds),
                );
            })
            .unwrap();
            // Keep the final owned state for comparison after consuming writeback.
            let mut end = snapshot(&s, &bodies, &manifolds);
            let tail = {
                let mut w = Vec::new();
                originals(
                    &mut w,
                    &bodies,
                    &manifolds,
                    Some(
                        &(0..bodies.len())
                            .map(|i| s.bodies.companion_id(i).map_or(-1, |id| id as i32))
                            .collect::<Vec<_>>(),
                    ),
                );
                w.len()
            };
            let companions: Vec<_> = (0..bodies.len())
                .map(|i| s.bodies.companion_id(i).map_or(-1, |id| id as i32))
                .collect();
            let pool_originals: Vec<_> =
                s.bodies.live_entries().iter().map(|b| b.original).collect();
            let before = end.clone();
            let body_offset = end.len() - tail + 1;
            s.writeback(&mut bodies, &mut manifolds);
            // The final snapshot retains pool/rows and records the actual written bodies and points.
            end.truncate(end.len() - tail);
            originals(&mut end, &bodies, &manifolds, Some(&companions));
            let mut written = end.clone();
            for i in 0..bodies.len() {
                let start = body_offset + 71 * i + 13;
                written[start..start + 6].copy_from_slice(&before[start..start + 6]);
            }
            for (index, original) in pool_originals.iter().enumerate() {
                emit(
                    &mut trace,
                    &format!("{case}\t{step}\t11\t-1\t{index}"),
                    written.clone(),
                );
                if let Some(i) = original {
                    let start = body_offset + 71 * i + 13;
                    written[start..start + 6].copy_from_slice(&end[start..start + 6]);
                }
                emit(
                    &mut trace,
                    &format!("{case}\t{step}\t12\t-1\t{index}"),
                    written.clone(),
                );
            }
            emit(&mut trace, &format!("{case}\t{step}\t10\t-1\t-1"), end);
            let mut final_words = Vec::new();
            originals(&mut final_words, &bodies, &manifolds, None);
            emit(&mut output, &format!("{case}\t{step}"), final_words);
            if case % 48 >= 40 && step == 0 {
                for b in &mut bodies {
                    let state = b.snapshot();
                    if !state.is_static && !state.is_kinematic {
                        let next = b.predict_transform(dt);
                        b.set_center_of_mass_transform(next);
                    }
                }
                for m in &mut manifolds {
                    for p in m.points.iter_mut() {
                        p.world_a = bodies[m.bodies[0]]
                            .snapshot()
                            .world
                            .origin
                            .sub(p.normal_on_b.scale(0.5));
                        p.distance = p.world_a.0[1];
                        p.world_b = p.world_a.sub(p.normal_on_b.scale(p.distance));
                    }
                }
            }
        }
    }
}
