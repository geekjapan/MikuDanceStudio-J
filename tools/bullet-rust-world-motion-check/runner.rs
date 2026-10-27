#![allow(dead_code)]
#[path = "../../rust/crates/mds-bullet/src/core/mod.rs"]
mod core;
use core::activation::ActivationState;
use core::math::{Quat, Transform, Vec3};
use core::world_objects::{BodyDesc, Pose, WorldObjects};
fn word(f: f32) {
    print!(" {:08x}", f.to_bits());
}
fn vec(v: Vec3) {
    for f in v.0 {
        word(f)
    }
}
fn trans(t: Transform) {
    for r in t.basis.0 {
        vec(Vec3(r))
    }
    vec(t.origin)
}
fn pose(x: f32) -> Pose {
    Pose {
        position: Vec3([x, 0.0, 0.0]),
        rotation: Quat([0.0, 0.0, 0.0, 1.0]),
    }
}
fn desc() -> BodyDesc {
    BodyDesc {
        shape_kind: 0,
        shape_params: [0.5, 1.0, 0.75, 0.0],
        mass: 2.0,
        pose: pose(0.0),
        kinematic: false,
        linear_damping: 0.0,
        angular_damping: 0.0,
        restitution: 0.0,
        friction: 0.5,
        filter: None,
    }
}
fn dump(w: &WorldObjects, k: &str, variant: usize, r: usize) {
    print!("W {k} {variant} {r}");
    vec(w.gravity());
    print!(" N {}", w.non_static().len());
    for i in w.non_static() {
        print!(" {i}")
    }
    println!();
    for (i, b) in w.bodies().iter().enumerate() {
        let s = b.snapshot();
        let d = &w.data()[i];
        print!("B {k} {variant} {r} {i}");
        for t in [
            s.world,
            s.interpolation_world,
            d.motion.graphics_world,
            d.motion.center_of_mass_offset,
            d.motion.start_world,
            d.motion.get_world_transform(),
        ] {
            trans(t)
        }
        for v in [
            s.linear_velocity,
            s.angular_velocity,
            s.interpolation_linear_velocity,
            s.interpolation_angular_velocity,
            s.gravity_acceleration,
            s.inverse_inertia_local,
        ] {
            vec(v)
        }
        for row in s.inverse_inertia_world.0 {
            vec(Vec3(row))
        }
        vec(s.total_force);
        vec(s.total_torque);
        for v in [
            s.inverse_mass,
            s.linear_damping,
            s.angular_damping,
            b.contact_body().friction,
            b.contact_body().restitution,
            d.processing_threshold,
        ] {
            word(v)
        }
        print!(
            " {} {} {} {} {}",
            d.collision_flags,
            w.objects()[i].activation.state as i32,
            d.filter[0],
            d.filter[1],
            d.disabled_collision_refs.len()
        );
        word(w.objects()[i].hit_fraction);
        println!();
    }
    // OBSERVER_ANCHOR
}
fn fixture(variant: usize, i: usize, next: bool, mmd: bool) -> Transform {
    use core::math::Basis;
    let rotation = match (variant + i + if next { 2 + variant % 2 } else { 0 }) % 5 {
        0 => Quat::IDENTITY,
        1 => Quat([1.0, 0.0, 0.0, 0.0]),
        2 => Quat([0.0, 1.0, 0.0, 0.0]),
        3 => Quat([0.0, 0.0, 1.0, 0.0]),
        _ => Quat([0.25, 0.5, -0.125, 1.0]),
    };
    let mut t = Pose {
        position: Vec3([
            (i + if next { 3 } else { 0 }) as f32,
            if next { -2.0 } else { 1.0 },
            0.5,
        ]),
        rotation,
    }
    .transform();
    if mmd && variant == 3 {
        t.basis = if next {
            Basis([[0.75, 0.125, -0.25], [0.25, 1.25, 0.5], [-0.125, 0.25, 1.5]])
        } else {
            Basis([
                [1.25, 0.25, -0.125],
                [0.125, 0.75, 0.25],
                [0.5, -0.125, 1.5],
            ])
        };
    }
    t
}
fn set(
    w: &mut WorldObjects,
    handles: &[core::world_objects::BodyHandle],
    j: usize,
    t: Transform,
    op: usize,
    mmd: bool,
) {
    let h = handles[j];
    match op {
        0 if !mmd => w
            .set_public_transform(
                h,
                Pose {
                    position: t.origin,
                    rotation: t.basis.rotation(),
                },
            )
            .unwrap(),
        0 | 1 => w.set_motion_state(h, t).unwrap(),
        2 => w.reseat(h, t).unwrap(),
        _ => w.stop_at(h, t.origin).unwrap(),
    }
}
fn replay(mmd: bool, variant: usize) {
    let mut w = if mmd {
        WorldObjects::mmd()
    } else {
        WorldObjects::public()
    };
    let base = usize::from(mmd);
    let k = if mmd { "M" } else { "P" };
    let mut handles = Vec::new();
    for j in 0..8 {
        let mut d = desc();
        d.mass = if j == 4 || j == 7 { 0.0 } else { 2.0 };
        d.kinematic = j == 3;
        d.linear_damping = 0.125;
        d.angular_damping = 0.25;
        handles.push(if mmd {
            d.filter = Some([1, -1]);
            w.create_mmd_body(d, if j == 3 { 0 } else { 1 }).unwrap()
        } else {
            w.create_public_body(d).unwrap()
        });
    }
    let states = [
        ActivationState::Active,
        ActivationState::IslandSleeping,
        ActivationState::DisableSimulation,
        ActivationState::DisableSimulation,
        ActivationState::DisableDeactivation,
        ActivationState::Active,
        ActivationState::WantsDeactivation,
        ActivationState::Active,
    ];
    for j in 0..8 {
        let i = base + j;
        if j == 4 || j == 5 {
            w.set_kinematic(handles[j], true).unwrap();
        }
        let (b, o, _) = w.solver_parts();
        o[i].activation.force_activation_state(states[j]);
        b[i].set_world_transform(fixture(variant, j, false, mmd));
        b[i].set_interpolation_world_transform(fixture(variant, j + 1, false, mmd));
        b[i].set_linear_velocity(Vec3([1.0, 0.5, -0.25]));
        b[i].set_angular_velocity(Vec3([0.125, -0.25, 0.5]));
        b[i].set_interpolation_velocities(Vec3([-2.0, 1.0, 0.25]), Vec3([0.25, 0.125, -0.5]));
        b[i].add_force(Vec3([3.0, -2.0, 1.0]));
        b[i].add_torque(Vec3([0.5, 0.25, -0.125]));
        o[i].hit_fraction = match j % 3 {
            0 => 0.0,
            1 => 0.25,
            _ => 1.0,
        };
        set(&mut w, &handles, j, fixture(variant, j, true, mmd), 1, mmd);
    }
    dump(&w, k, variant, 0);
    w.save_kinematic_state(0.0);
    dump(&w, k, variant, 1);
    w.save_kinematic_state(1.0 / 60.0);
    dump(&w, k, variant, 2);
    w.apply_gravity();
    dump(&w, k, variant, 3);
    w.predict_unconstraint_motion(0.0);
    dump(&w, k, variant, 4);
    w.predict_unconstraint_motion(1.0 / 60.0);
    dump(&w, k, variant, 5);
    w.synchronize_motion_states(0.0, false);
    dump(&w, k, variant, 6);
    w.synchronize_motion_states(0.007, false);
    dump(&w, k, variant, 7);
    w.synchronize_motion_states(0.007, true);
    dump(&w, k, variant, 8);
    set(&mut w, &handles, 0, fixture(variant, 7, true, mmd), 0, mmd);
    dump(&w, k, variant, 9);
    set(&mut w, &handles, 0, fixture(variant, 4, false, mmd), 2, mmd);
    dump(&w, k, variant, 10);
    w.synchronize_motion_states(0.007, false);
    dump(&w, k, variant, 11);
    set(&mut w, &handles, 0, fixture(variant, 6, true, mmd), 3, mmd);
    dump(&w, k, variant, 12);
    w.predict_unconstraint_motion(0.007);
    dump(&w, k, variant, 13);
    w.clear_forces();
    dump(&w, k, variant, 14);
    w.solver_parts().1[base + 3]
        .activation
        .force_activation_state(ActivationState::IslandSleeping);
    set(&mut w, &handles, 3, fixture(variant, 5, false, mmd), 1, mmd);
    w.save_kinematic_state(0.007);
    dump(&w, k, variant, 15);
    w.solver_parts().1[base + 3]
        .activation
        .force_activation_state(ActivationState::DisableSimulation);
    w.save_kinematic_state(0.007);
    dump(&w, k, variant, 16);
    w.clear_forces();
    dump(&w, k, variant, 17);
}
fn main() {
    for mmd in [false, true] {
        for variant in 0..4 {
            replay(mmd, variant);
        }
    }
}
