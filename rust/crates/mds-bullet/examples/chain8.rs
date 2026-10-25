//! The P1 prototype scene: a kinematic root capsule on a polynomial path, 8
//! capsules hanging from it on 6DOF spring joints, and a static plane.
//! `shim/bench_main.cpp` in mds-bullet-sys is the C++ twin; keep them in step.
//!
//! Prints `final <hash>` and `mean_step_us <microseconds>`. Bullet's float
//! math comes from mds-crtmath, which matches the MSVC x64 UCRT, so the hash
//! is `69c5ce49dd0962b5` on every supported CPU. The P1 prototype hash
//! `b7be367fb1ece153` came from the earlier `det_math.h` approximation.

// tests/world.rs includes this file as a module and never calls `main`.
#![allow(dead_code)]

use std::time::{Duration, Instant};

use mds_bullet::{BodyDesc, BodyId, JointDesc, Shape, Transform, World};

pub const LINKS: usize = 8;
pub const FRAMES: i32 = 600;
pub const REFERENCE_HASH: u64 = 0x69c5ce49dd0962b5;

pub struct Chain8 {
    pub world: World,
    pub root: BodyId,
}

pub fn build() -> Chain8 {
    let mut world = World::new().expect("world");
    world.set_gravity([0.0, -98.0, 0.0]).expect("gravity");

    let ground = BodyDesc::new(Shape::StaticPlane {
        normal: [0.0, 1.0, 0.0],
        constant: 0.0,
    });
    world.add_body(&ground).expect("ground");

    let mut root = None;
    let mut prev: Option<BodyId> = None;
    for i in 0..=LINKS {
        let mut desc = BodyDesc::new(Shape::Capsule {
            radius: 0.4,
            height: 1.2,
        });
        desc.mass = if i == 0 { 0.0 } else { 1.0 };
        desc.kinematic = i == 0;
        desc.linear_damping = 0.5;
        desc.angular_damping = 0.5;
        desc.transform = Transform::at([0.3 * i as f32, 20.0 - 1.6 * i as f32, 0.1 * i as f32]);
        let body = world.add_body(&desc).expect("body");
        if i == 0 {
            root = Some(body);
        }
        if let Some(prev) = prev {
            let mut joint = JointDesc::new(prev, body);
            joint.frame_a = Transform::at([0.0, -0.8, 0.0]);
            joint.frame_b = Transform::at([0.0, 0.8, 0.0]);
            joint.angular_lower = [-0.6, -0.3, -0.6];
            joint.angular_upper = [0.6, 0.3, 0.6];
            joint.spring_enabled = [false, false, false, true, true, true];
            joint.spring_stiffness = [0.0, 0.0, 0.0, 30.0, 30.0, 30.0];
            world.add_joint(&joint).expect("joint");
        }
        prev = Some(body);
    }
    Chain8 {
        world,
        root: root.expect("root"),
    }
}

impl Chain8 {
    /// Moves the root along its path and steps once. Returns the time spent in
    /// the step call alone.
    pub fn step_frame(&mut self, frame: i32) -> Duration {
        let t = frame as f32 / 60.0;
        let x = 4.0 * t * (1.0 - t / 10.0);
        // Same arithmetic as btQuaternion(axis (0,0,1), angle): the sine and
        // cosine go through double and round to float, like det_math.h.
        let half = 0.02 * frame as f32 * 0.5;
        let s = ((half as f64).sin() as f32) / 1.0;
        let rotation = [0.0 * s, 0.0 * s, 1.0 * s, (half as f64).cos() as f32];
        let t = Transform {
            position: [x, 20.0, 0.0],
            rotation,
        };
        self.world
            .set_transform(self.root, &t)
            .expect("set_transform");
        let start = Instant::now();
        self.world.step(1.0 / 30.0, 1, 1.0 / 60.0).expect("step");
        start.elapsed()
    }
}

fn main() {
    let mut scene = build();
    let mut total = Duration::ZERO;
    for frame in 0..FRAMES {
        total += scene.step_frame(frame);
    }
    println!("final {:016x}", scene.world.state_hash().expect("hash"));
    println!(
        "mean_step_us {:.3}",
        total.as_secs_f64() * 1e6 / FRAMES as f64
    );
}
