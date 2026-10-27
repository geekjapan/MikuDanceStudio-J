//! Can also run with rustc --test and only the pure mds-crtmath rlib.

#[path = "pure_bullet/axis_sweep.rs"]
mod axis_sweep;
#[path = "pure_bullet/body_kernel.rs"]
mod body_kernel;
#[path = "pure_bullet/contact_solver.rs"]
mod contact_solver;
#[path = "../src/core/mod.rs"]
mod core;
#[path = "pure_bullet/joint_coordinates.rs"]
mod joint_coordinates;
#[path = "pure_bullet/joint_rows.rs"]
mod joint_rows;
#[path = "pure_bullet/joint_solver.rs"]
mod joint_solver;
#[path = "pure_bullet/math_vectors.rs"]
mod math_vectors;
#[path = "pure_bullet/pair_cache.rs"]
mod pair_cache;
#[path = "support/pilot_cases.rs"]
mod pilot_cases;
#[path = "pure_bullet/shapes.rs"]
mod shapes;

#[path = "pure_bullet/simplex.rs"]
mod simplex;

use core::body::FreeBody;
use core::math::{Quat, Vec3};
use core::time::StepClock;
use core::InvalidArgument;
use pilot_cases as cases;

#[test]
fn native_fixture_matches_every_rust_float_bit_and_hash() {
    let expected = include_str!("data/free-sphere-native.tsv");
    let mut lines = expected.lines();
    for case in 0..cases::CASES {
        let mut clock = StepClock::new();
        let mut bodies: [_; cases::BODIES] = std::array::from_fn(|i| {
            FreeBody::sphere(
                0.5,
                cases::MASSES[i],
                cases::DAMPING[i],
                Vec3(cases::GRAVITY),
                Vec3(cases::POSITIONS[i]),
                Quat(cases::ROTATIONS[i]),
            )
            .unwrap()
        });
        for frame in 0..cases::FRAMES {
            let (dt, max, fixed) = cases::timing(case, frame);
            let step = clock.advance(dt, max, fixed).unwrap();
            let mut hash = 1_469_598_103_934_665_603;
            for body in &mut bodies {
                body.step(step);
                body.hash_into(&mut hash);
            }
            let transforms = std::array::from_fn(|i| {
                let t = bodies[i].transform();
                (t.origin.0, t.basis.rotation().0)
            });
            let actual = cases::row(case, frame, step.requested, hash, transforms);
            assert_eq!(
                actual.trim_end(),
                lines.next().expect("native fixture row"),
                "case {case}, frame {frame}"
            );
        }
    }
    assert!(lines.next().is_none());
}

#[test]
fn clock_keeps_initial_time_and_unclamped_return_count() {
    let fixed = 1.0 / 60.0;
    let mut clock = StepClock::new();
    let step = clock.advance(0.0, 1, fixed).unwrap();
    assert_eq!((step.requested, step.executed, step.remainder), (1, 1, 0.0));
    let step = clock.advance(1.0 / 30.0, 1, fixed).unwrap();
    assert_eq!((step.requested, step.executed, step.remainder), (2, 1, 0.0));
    let step = clock.advance(0.0, 1, fixed).unwrap();
    assert_eq!((step.requested, step.executed), (0, 0));
}

#[test]
fn invalid_boundary_inputs_do_not_advance_the_clock() {
    let fixed = 1.0 / 60.0;
    for (dt, max, step) in [
        (f32::NAN, 1, fixed),
        (-1.0, 1, fixed),
        (fixed, -1, fixed),
        (fixed, 1, 0.0),
        (fixed, 1, f32::INFINITY),
        (f32::MAX, 1, f32::MIN_POSITIVE),
    ] {
        let mut clock = StepClock::new();
        assert_eq!(clock.advance(dt, max, step), Err(InvalidArgument));
        assert_eq!(clock.advance(0.0, 1, fixed).unwrap().requested, 1);
    }
    for (radius, mass, damping, rotation) in [
        (0.0, 1.0, 0.0, [0.0, 0.0, 0.0, 1.0]),
        (1.0, 0.0, 0.0, [0.0, 0.0, 0.0, 1.0]),
        (1.0, 1.0, f32::NAN, [0.0, 0.0, 0.0, 1.0]),
        (1.0, 1.0, 0.0, [0.0; 4]),
    ] {
        assert!(FreeBody::sphere(
            radius,
            mass,
            damping,
            Vec3::ZERO,
            Vec3::ZERO,
            Quat(rotation)
        )
        .is_err());
    }
}
