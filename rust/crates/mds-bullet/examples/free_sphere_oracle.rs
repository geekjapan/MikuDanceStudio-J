//! Capture the existing native shim, not the Rust pilot.
//! cargo run -p mds-bullet --example free_sphere_oracle --release > crates/mds-bullet/tests/data/free-sphere-native.tsv

#[path = "../tests/support/pilot_cases.rs"]
mod cases;

use mds_bullet::{BodyDesc, Filter, Shape, Transform, World};

pub fn capture() -> String {
    let mut output = String::new();
    for case in 0..cases::CASES {
        let mut world = World::new().unwrap();
        world.set_gravity(cases::GRAVITY).unwrap();
        let bodies: [_; cases::BODIES] = std::array::from_fn(|i| {
            world
                .add_body(&BodyDesc {
                    mass: cases::MASSES[i],
                    linear_damping: cases::DAMPING[i],
                    filter: Some(Filter { group: 1, mask: 0 }),
                    transform: Transform {
                        position: cases::POSITIONS[i],
                        rotation: cases::ROTATIONS[i],
                    },
                    ..BodyDesc::new(Shape::Sphere { radius: 0.5 })
                })
                .unwrap()
        });
        for frame in 0..cases::FRAMES {
            let (dt, max, fixed) = cases::timing(case, frame);
            let steps = world.step(dt, max, fixed).unwrap();
            let transforms = bodies.map(|id| {
                let t = world.transform(id).unwrap();
                (t.position, t.rotation)
            });
            output.push_str(&cases::row(
                case,
                frame,
                steps,
                world.state_hash().unwrap(),
                transforms,
            ));
        }
    }
    output
}

#[allow(dead_code)]
fn main() {
    print!("{}", capture());
}
