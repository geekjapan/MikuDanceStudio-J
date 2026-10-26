#![allow(dead_code)]
#[path = "../../rust/crates/mds-bullet/src/core/mod.rs"]
mod core;
use core::activation::{ActivationState, BodyActivation, CollisionClassification};
use core::body::{BodyInit, RigidBody};
use core::contact::ContactPoint;
use core::contact_solver::ContactManifold;
use core::islands::{IslandManifold, IslandObject, SimulationIslands, SolverEvent};
use core::math::{Basis, Transform, Vec3};
use core::solver::{GroupSelection, GroupSolver, SolverMode, SolverWorkspace};
struct Reader<'a>(std::str::SplitWhitespace<'a>);
impl Reader<'_> {
    fn token(&mut self, s: &str) {
        assert_eq!(self.0.next(), Some(s));
    }
    fn int(&mut self) -> usize {
        self.0.next().unwrap().parse().unwrap()
    }
    fn scalar(&mut self) -> f32 {
        f32::from_bits(u32::from_str_radix(self.0.next().unwrap(), 16).unwrap())
    }
    fn vec(&mut self) -> Vec3 {
        Vec3(std::array::from_fn(|_| self.scalar()))
    }
}
fn main() {
    let a: Vec<_> = std::env::args().collect();
    let text = std::fs::read_to_string(&a[1]).unwrap();
    let mut r = Reader(text.split_whitespace());
    let mut bodies: Vec<RigidBody> = Vec::new();
    let mut objects = Vec::new();
    let mut ids = Vec::new();
    let mut workspace = SolverWorkspace::default();
    let mut islands = SimulationIslands::default();
    let dt = 1.0_f32 / 60.0;
    let mut prior_impulses = std::collections::HashMap::new();
    for step in 0..2 {
        r.token("STEP");
        let nb = r.int();
        let nm = r.int();
        let np = r.int();
        for i in 0..nb {
            r.token("B");
            let id = r.int();
            let flags = r.int();
            let inv = r.scalar();
            let inv_i = r.vec();
            let world = Transform {
                basis: Basis(std::array::from_fn(|_| r.vec().0)),
                origin: r.vec(),
            };
            let linear = r.vec();
            let angular = r.vec();
            if step == 0 {
                ids.push(id);
                let mut body = RigidBody::new(BodyInit {
                    mass: if inv == 0.0 { 0.0 } else { 1.0 / inv },
                    local_inertia: Vec3(inv_i.0.map(|v| if v == 0.0 { 0.0 } else { 1.0 / v })),
                    center_of_mass: world,
                    linear_damping: 0.0,
                    angular_damping: 0.0,
                });
                body.set_kinematic(flags & 2 != 0);
                body.set_gravity(Vec3([0.0, -10.0, 0.0]));
                bodies.push(body);
                objects.push(IslandObject {
                    activation: BodyActivation {
                        state: ActivationState::DisableDeactivation,
                        ..BodyActivation::default()
                    },
                    classification: if flags & 2 != 0 {
                        CollisionClassification::Kinematic
                    } else if flags & 1 != 0 {
                        CollisionClassification::Static
                    } else {
                        CollisionClassification::Dynamic
                    },
                    contact_response: true,
                    island_tag: -1,
                    companion_id: -1,
                    hit_fraction: 1.0,
                });
            }
            let b = &mut bodies[i];
            if flags & 3 == 0 {
                b.apply_gravity();
                b.integrate_velocities(dt);
                b.apply_damping(dt);
            } else if flags & 2 != 0 {
                b.set_linear_velocity(Vec3::ZERO);
                b.set_angular_velocity(Vec3::ZERO);
            }
            let state = b.snapshot();
            assert_eq!(
                state.world, world,
                "incoming transform step {step} body {id}"
            );
            assert_eq!(
                state.linear_velocity, linear,
                "incoming velocity step {step} body {id}"
            );
            assert_eq!(
                state.angular_velocity, angular,
                "incoming angular step {step} body {id}"
            );
        }
        let mut owners = Vec::new();
        let mut thresholds = Vec::new();
        let mut points = Vec::new();
        for _ in 0..nm {
            r.token("M");
            owners.push([r.int(), r.int()]);
            let n = r.int();
            thresholds.push(r.scalar());
            let mut p = Vec::new();
            for _ in 0..n {
                r.token("P");
                p.push(ContactPoint {
                    local_a: r.vec(),
                    local_b: r.vec(),
                    world_a: r.vec(),
                    world_b: r.vec(),
                    normal_on_b: r.vec(),
                    distance: r.scalar(),
                    combined_friction: r.scalar(),
                    combined_restitution: r.scalar(),
                    applied_impulse: r.scalar(),
                    lifetime: r.int() as i32,
                    ..ContactPoint::EMPTY
                });
            }
            points.push(p);
        }
        if step != 0 {
            for (mi, p) in points.iter().enumerate() {
                for (pi, q) in p.iter().enumerate() {
                    assert_eq!(
                        Some(&q.applied_impulse.to_bits()),
                        prior_impulses.get(&(owners[mi], pi)),
                        "incoming normal warmstart differs"
                    );
                }
            }
        }
        let pairs: Vec<_> = (0..np)
            .map(|_| {
                r.token("PAIR");
                [r.int(), r.int()]
            })
            .collect();
        let mut manifolds: Vec<_> = points
            .iter_mut()
            .enumerate()
            .map(|(i, p)| ContactManifold {
                bodies: owners[i],
                points: p,
                processing_threshold: thresholds[i],
            })
            .collect();
        let im: Vec<_> = owners
            .iter()
            .map(|&bodies| IslandManifold { bodies })
            .collect();
        islands.calculate(&mut objects, pairs, &[]);
        islands.solve_constraints(&mut objects, &im, &[], true, |objects, event| {
            if let SolverEvent::SolveGroup {
                island,
                constraints,
            } = event
            {
                print!("G {}", island.bodies.len());
                for i in island.bodies {
                    print!(" {i}");
                }
                print!(" {}", island.manifolds.len());
                for i in island.manifolds {
                    print!(" {i}");
                }
                println!(" {}", constraints.len());
                println!(
                    "BPOOL {} {}",
                    workspace.live_len(),
                    workspace.native_capacity()
                );
                let mut s = GroupSolver::setup(
                    &mut workspace,
                    objects,
                    &bodies,
                    &mut [],
                    &mut manifolds,
                    GroupSelection {
                        bodies: island.bodies,
                        joints: constraints,
                        manifolds: island.manifolds,
                    },
                    dt,
                    SolverMode::Simd,
                )
                .unwrap();
                print!(
                    "S {} {} {}",
                    s.bodies.live_len(),
                    s.bodies.native_capacity(),
                    s.normals.len()
                );
                for n in &s.normals {
                    for i in n.numeric.bodies {
                        print!(" {i}");
                    }
                }
                for b in s.bodies.live_entries() {
                    print!(" {}", b.original.map_or(-1, |i| ids[i] as i32));
                }
                println!();
                s.iterate(&bodies, &[], |_, _| {}).unwrap();
                s.writeback(&mut bodies, &mut manifolds);
            }
        });
        prior_impulses.clear();
        for (mi, m) in manifolds.iter().enumerate() {
            for (pi, p) in m.points.iter().enumerate() {
                prior_impulses.insert((owners[mi], pi), p.applied_impulse.to_bits());
            }
        }
        for (i, b) in bodies.iter_mut().enumerate() {
            print!("V {step} {}", ids[i]);
            for v in [b.snapshot().linear_velocity, b.snapshot().angular_velocity] {
                for word in v.0 {
                    print!(" {:08x}", word.to_bits());
                }
            }
            println!();
            if !b.snapshot().is_static && !b.snapshot().is_kinematic {
                b.set_center_of_mass_transform(b.predict_transform(dt));
            }
            b.clear_forces();
        }
        assert_eq!(workspace.live_len(), 0);
    }
    assert!(r.0.next().is_none());
}
