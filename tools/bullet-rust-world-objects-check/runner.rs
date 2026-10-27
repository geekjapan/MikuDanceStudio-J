#![allow(dead_code)]
#[path = "../../rust/crates/mds-bullet/src/core/mod.rs"]
mod core;
use core::activation::ActivationState;
use core::math::{Quat, Transform, Vec3};
use core::world_objects::{BodyDesc, JointDesc, Pose, WorldObjects};
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
fn dump(w: &WorldObjects, k: &str, r: usize) {
    print!("W {k} {r}");
    vec(w.gravity());
    print!(" N {}", w.non_static().len());
    for i in w.non_static() {
        print!(" {i}")
    }
    println!();
    for (i, b) in w.bodies().iter().enumerate() {
        let s = b.snapshot();
        let d = &w.data()[i];
        print!("B {k} {r} {i}");
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
        println!(
            " {} {} {} {} {}",
            d.collision_flags,
            w.objects()[i].activation.state as i32,
            d.filter[0],
            d.filter[1],
            d.disabled_collision_refs.len()
        );
    }
    for (i, j) in w.joints().iter().enumerate() {
        print!("J {k} {r} {i}");
        for m in j.state.linear {
            word(m.lower);
            word(m.upper);
            print!(" {}", i32::from(m.enabled));
            word(m.target_velocity);
            word(m.max_motor_force);
        }
        for a in j.state.angular {
            let m = a.motor;
            word(m.lower);
            word(m.upper);
            print!(" {}", i32::from(m.enabled));
            word(m.target_velocity);
            word(m.max_motor_force);
            word(a.erp);
            word(a.bounce);
        }
        for s in j.state.springs {
            print!(" {}", i32::from(s.enabled));
            word(s.equilibrium);
            word(s.stiffness);
            word(s.damping);
        }
        if let Some(uid) = w.joint_data()[i].mmd_uid {
            print!(" {uid}")
        }
        println!();
        if k == "Q" || k == "N" {
            print!("T {k} {r} {i}");
            trans(j.frames[0]);
            trans(j.frames[1]);
            println!();
        }
    }
    // OBSERVER_ANCHOR
}
fn jd(a: core::world_objects::BodyHandle, b: core::world_objects::BodyHandle) -> JointDesc {
    JointDesc {
        bodies: [a, b],
        frames: [pose(0.0); 2],
        linear_lower: Vec3::ZERO,
        linear_upper: Vec3::ZERO,
        angular_lower: Vec3([-0.0, -7.0, 0.0]),
        angular_upper: Vec3([0.0, 7.0, 0.0]),
        spring_enabled: [false; 6],
        spring_stiffness: [0.0; 6],
        use_linear_reference_frame_a: true,
        disable_collisions: false,
    }
}
fn public(rotated: bool) {
    let kind = if rotated { "Q" } else { "P" };
    let mut w = WorldObjects::public();
    let mut h = Vec::new();
    dump(&w, kind, 15);
    w.set_gravity(Vec3([1.0, -7.0, 2.0])).unwrap();
    dump(&w, kind, 0);
    for i in 0..7 {
        let mut d = desc();
        d.shape_kind = i % 4;
        d.pose = pose(i as f32);
        if rotated {
            d.pose.rotation = Quat([0.25, 0.5, -0.125, 1.0]);
        }
        if i == 3 {
            d.mass = 0.0;
            d.shape_params = [0.0, 1.0, 0.0, 0.0]
        }
        if i == 4 {
            d.kinematic = true
        }
        if i == 5 {
            d.filter = Some([i16::MIN, -2])
        }
        h.push(w.create_public_body(d).unwrap());
        println!("C {kind} {i} 0");
        dump(&w, kind, i as usize + 1);
    }
    let p = Pose {
        position: Vec3([-0.0, 3.0, 4.0]),
        ..pose(0.0)
    };
    let p = if rotated {
        Pose {
            rotation: Quat([-0.5, 0.125, 0.25, 1.0]),
            ..p
        }
    } else {
        p
    };
    w.set_public_transform(h[0], p).unwrap();
    w.set_public_transform(h[4], p).unwrap();
    dump(&w, kind, 8);
    {
        let (_, o, _) = w.solver_parts();
        o[0].activation
            .force_activation_state(ActivationState::IslandSleeping);
        o[1].activation
            .force_activation_state(ActivationState::DisableSimulation);
    }
    w.set_kinematic(h[2], true).unwrap();
    w.set_gravity(Vec3([3.0, -5.0, 6.0])).unwrap();
    dump(&w, kind, 9);
    w.solver_parts().1[0]
        .activation
        .force_activation_state(ActivationState::Active);
    w.set_gravity(Vec3([4.0, -6.0, 7.0])).unwrap();
    dump(&w, kind, 10);
    for j in 0..3 {
        let mut d = jd(h[0], h[1]);
        if rotated {
            rotated_frames(&mut d);
        }
        d.disable_collisions = j == 0;
        d.use_linear_reference_frame_a = j % 2 != 0;
        if j == 1 {
            d.spring_enabled = [true; 6];
            d.spring_stiffness = std::array::from_fn(|k| (k + 1) as f32)
        }
        w.create_joint(d, None).unwrap();
        println!("K {kind} {j} 0");
        dump(&w, kind, 11 + j);
    }
    let mut bad = desc();
    bad.mass = 1.0;
    bad.shape_params = [0.0; 4];
    assert!(w.create_public_body(bad).is_err());
    println!("R {kind} -2 {}", w.bodies().len());
    let mut f = WorldObjects::public();
    assert!(f.set_public_transform(h[0], p).is_err());
    println!("F {kind} -1");
    dump(&w, kind, 14);
    if rotated {
        for i in 0..4 {
            let mut d = desc();
            match i {
                0 => d.mass = -2.0,
                1 => d.mass = f32::INFINITY,
                2 => d.pose.position.0[0] = f32::NAN,
                _ => d.friction = f32::NAN,
            }
            assert!(w.create_public_body(d).is_err());
            println!("V Q {i} -2 {}", w.bodies().len());
        }
        dump(&w, kind, 16);
    }
}
fn mmd(rotated: bool) {
    let kind = if rotated { "N" } else { "M" };
    let mut w = WorldObjects::mmd();
    let mut h = Vec::new();
    dump(&w, kind, 0);
    for i in 0..4 {
        let mut d = desc();
        d.shape_kind = i % 3;
        d.pose = pose(i as f32);
        if rotated {
            d.pose.rotation = Quat([0.25, 0.5, -0.125, 1.0]);
        }
        if i == 3 {
            d.mass = 0.0
        }
        d.filter = Some([i16::MIN, -2]);
        h.push(w.create_mmd_body(d, i % 3).unwrap());
        println!("C {kind} {i} 0");
        dump(&w, kind, i as usize + 1);
    }
    let mut m = Transform::IDENTITY;
    m.origin = Vec3([3.0, 4.0, 5.0]);
    if rotated {
        m.basis = core::math::Basis([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]);
    }
    w.set_motion_state(h[1], m).unwrap();
    dump(&w, kind, 5);
    {
        let (b, _, _) = w.solver_parts();
        b[2].set_linear_velocity(Vec3([1.0, 2.0, 3.0]));
        b[2].set_angular_velocity(Vec3([4.0, 5.0, 6.0]));
        b[2].set_interpolation_velocities(Vec3([7.0, 8.0, 9.0]), Vec3([10.0, 11.0, 12.0]));
    }
    w.stop_at(h[1], Vec3([9.0, 8.0, 7.0])).unwrap();
    dump(&w, kind, 6);
    w.reseat(h[1], m).unwrap();
    dump(&w, kind, 7);
    w.set_kinematic(h[1], true).unwrap();
    w.set_gravity(Vec3([3.0, -4.0, 5.0])).unwrap();
    dump(&w, kind, 8);
    w.solver_parts().1[2]
        .activation
        .force_activation_state(ActivationState::IslandSleeping);
    w.set_gravity(Vec3([6.0, -7.0, 8.0])).unwrap();
    dump(&w, kind, 9);
    w.set_floor(false).unwrap();
    dump(&w, kind, 10);
    w.set_floor(true).unwrap();
    dump(&w, kind, 11);
    for j in 0..3 {
        let mut d = jd(h[0], h[1]);
        if rotated {
            rotated_frames(&mut d);
        }
        if j == 1 {
            d.spring_stiffness[0] = 2.0
        }
        if j == 2 {
            d.spring_stiffness[4] = 3.0
        }
        w.create_joint(d, Some(17 + j as i32)).unwrap();
        println!("K {kind} {j} 0");
        dump(&w, kind, 12 + j);
    }
    if rotated {
        for i in 0..2 {
            let mut d = desc();
            d.mass = if i == 0 { -2.0 } else { 2.0 };
            d.friction = if i == 0 { f32::NAN } else { f32::INFINITY };
            d.restitution = d.friction;
            d.filter = Some([1, -1]);
            w.create_mmd_body(d, 1).unwrap();
            println!("V N {i} 0 {}", w.bodies().len());
            dump(&w, kind, 15 + i);
        }
    }
}
fn rotated_frames(d: &mut JointDesc) {
    d.frames[0] = Pose {
        position: Vec3([1.0, 0.0, 0.0]),
        rotation: Quat([0.125, -0.25, 0.5, 1.0]),
    };
    d.frames[1] = Pose {
        position: Vec3([0.0, 2.0, 0.0]),
        rotation: Quat([-0.5, 0.125, 0.25, 1.0]),
    };
}
fn offsets() {
    use core::world_objects::MotionState;
    let start = Pose {
        position: Vec3([3.0, 4.0, 5.0]),
        rotation: Quat([0.25, 0.5, -0.125, 1.0]),
    }
    .transform();
    let offset = Pose {
        position: Vec3([1.0, -2.0, 0.5]),
        rotation: Quat([-0.5, 0.125, 0.25, 1.0]),
    }
    .transform();
    let mut motion = MotionState::new(start, offset);
    for row in 0..2 {
        if row == 1 {
            motion.set_world_transform(offset);
        }
        print!("O P {row}");
        trans(motion.graphics_world);
        trans(motion.center_of_mass_offset);
        trans(motion.start_world);
        trans(motion.get_world_transform());
        println!();
    }
}
fn main() {
    public(false);
    public(true);
    mmd(false);
    mmd(true);
    offsets();
}
