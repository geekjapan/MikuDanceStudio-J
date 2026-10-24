#[path = "../examples/chain8.rs"]
mod chain8;

use std::sync::{Mutex, MutexGuard};

use mds_bullet::{live_counts, BodyDesc, BodyId, Error, Filter, Shape, Transform, World};

// The live counters are process-wide, so tests that create worlds take turns.
static SERIAL: Mutex<()> = Mutex::new(());

fn serial() -> MutexGuard<'static, ()> {
    SERIAL.lock().unwrap_or_else(|e| e.into_inner())
}

#[test]
fn chain8_hash_matches_the_p1_reference() {
    let _g = serial();
    let mut scene = chain8::build();
    for frame in 0..chain8::FRAMES {
        scene.step_frame(frame);
    }
    assert_eq!(scene.world.state_hash().unwrap(), chain8::REFERENCE_HASH);
}

#[test]
fn dropping_a_world_frees_its_bodies_and_joints() {
    let _g = serial();
    let before = live_counts();
    let scene = chain8::build();
    let during = live_counts();
    assert_eq!(during.worlds, before.worlds + 1);
    assert_eq!(during.bodies, before.bodies + 1 + 9); // ground + root + 8 links
    assert_eq!(during.joints, before.joints + 8);
    assert_eq!(scene.world.body_count(), 10);
    assert_eq!(scene.world.joint_count(), 8);
    drop(scene);
    assert_eq!(live_counts(), before);
}

fn body_falling_onto_plane(plane_filter: Filter, body_filter: Filter) -> f32 {
    let mut world = World::new().unwrap();
    world.set_gravity([0.0, -98.0, 0.0]).unwrap();
    let mut plane = BodyDesc::new(Shape::StaticPlane {
        normal: [0.0, 1.0, 0.0],
        constant: 0.0,
    });
    plane.filter = Some(plane_filter);
    world.add_body(&plane).unwrap();
    let mut ball = BodyDesc::new(Shape::Sphere { radius: 0.5 });
    ball.mass = 1.0;
    ball.filter = Some(body_filter);
    ball.transform = Transform::at([0.0, 5.0, 0.0]);
    let ball = world.add_body(&ball).unwrap();
    for _ in 0..120 {
        world.step(1.0 / 60.0, 1, 1.0 / 60.0).unwrap();
    }
    world.transform(ball).unwrap().position[1]
}

#[test]
fn collision_filter_decides_whether_a_body_lands_on_the_plane() {
    let _g = serial();
    let plane = Filter { group: 1, mask: 1 };
    // The plane's mask excludes group 2, so the body falls through.
    let through = body_falling_onto_plane(
        plane,
        Filter {
            group: 2,
            mask: 0xffff,
        },
    );
    assert!(
        through < -5.0,
        "expected a fall through the plane, y = {through}"
    );
    // Control: group 1 is in the plane's mask, so the body rests on it.
    let rests = body_falling_onto_plane(
        plane,
        Filter {
            group: 1,
            mask: 0xffff,
        },
    );
    eprintln!("excluded group y = {through}, control group y = {rests}");
    assert!(
        (0.0..1.0).contains(&rests),
        "expected a body resting on the plane, y = {rests}"
    );
}

#[test]
fn bad_handles_and_arguments_are_errors() {
    let _g = serial();
    let mut a = World::new().unwrap();
    let mut b = World::new().unwrap();
    let ball = BodyDesc {
        mass: 1.0,
        ..BodyDesc::new(Shape::Sphere { radius: 1.0 })
    };
    let in_a = a.add_body(&ball).unwrap();
    assert_eq!(b.transform(in_a), Err(Error::InvalidHandle));
    assert_eq!(
        b.set_transform(in_a, &Transform::IDENTITY),
        Err(Error::InvalidHandle)
    );
    let b0 = b.add_body(&ball).unwrap();
    assert_eq!(
        a.add_joint(&mds_bullet::JointDesc::new(in_a, b0)),
        Err(Error::InvalidHandle)
    );
    assert_eq!(
        a.add_joint(&mds_bullet::JointDesc::new(in_a, in_a)),
        Err(Error::InvalidArgument)
    );

    for bad in [
        BodyDesc { mass: -1.0, ..ball },
        BodyDesc {
            mass: f32::NAN,
            ..ball
        },
        BodyDesc::new(Shape::Sphere { radius: 0.0 }),
        BodyDesc::new(Shape::Box {
            half_extents: [1.0, f32::INFINITY, 1.0],
        }),
        BodyDesc::new(Shape::StaticPlane {
            normal: [0.0, 2.0, 0.0],
            constant: 0.0,
        }),
        BodyDesc {
            transform: Transform {
                position: [0.0; 3],
                rotation: [0.0; 4],
            },
            ..ball
        },
    ] {
        assert_eq!(a.add_body(&bad), Err(Error::InvalidArgument), "{bad:?}");
    }
    assert_eq!(a.body_count(), 1);

    let ground = a
        .add_body(&BodyDesc::new(Shape::Box {
            half_extents: [1.0; 3],
        }))
        .unwrap();
    assert_eq!(
        a.set_transform(ground, &Transform::IDENTITY),
        Err(Error::InvalidArgument)
    );
    assert_eq!(a.step(f32::NAN, 1, 1.0 / 60.0), Err(Error::InvalidArgument));
    assert_eq!(a.step(1.0 / 60.0, 1, 0.0), Err(Error::InvalidArgument));
    assert_eq!(
        a.set_gravity([0.0, f32::NAN, 0.0]),
        Err(Error::InvalidArgument)
    );
}

#[test]
fn a_dynamic_body_can_be_moved() {
    let _g = serial();
    let mut w = World::new().unwrap();
    let ball: BodyId = w
        .add_body(&BodyDesc {
            mass: 1.0,
            ..BodyDesc::new(Shape::Sphere { radius: 1.0 })
        })
        .unwrap();
    w.set_transform(ball, &Transform::at([1.0, 2.0, 3.0]))
        .unwrap();
    assert_eq!(w.transform(ball).unwrap().position, [1.0, 2.0, 3.0]);
}

#[cfg(unix)]
fn rss_kib() -> u64 {
    let out = std::process::Command::new("ps")
        .args(["-o", "rss=", "-p", &std::process::id().to_string()])
        .output()
        .expect("run ps");
    String::from_utf8(out.stdout)
        .unwrap()
        .trim()
        .parse()
        .expect("rss")
}

#[cfg(unix)]
#[test]
fn creating_and_dropping_10000_worlds_does_not_grow_memory() {
    let _g = serial();
    let churn = |n: usize| {
        for _ in 0..n {
            let mut scene = chain8::build();
            scene.step_frame(0);
            scene.step_frame(1);
        }
    };
    churn(200); // allocator warm-up
    let before = rss_kib();
    churn(10_000);
    let after = rss_kib();
    let grown = after.saturating_sub(before);
    eprintln!("rss before {before} KiB, after {after} KiB, grown {grown} KiB");
    assert!(grown < 5 * 1024, "RSS grew by {grown} KiB");
    assert_eq!(live_counts().worlds, 0);
}
