#[path = "../../rust/crates/mds-bullet/src/core/box_box.rs"]
pub mod box_box;
extern crate bullet_core_support as base;
pub use base::{joint_coordinates, joint_rows, math, time, InvalidArgument};
#[path = "../../rust/crates/mds-bullet/src/core/body.rs"]
pub mod body;
#[path = "../../rust/crates/mds-bullet/src/core/contact.rs"]
pub mod contact;
#[path = "../../rust/crates/mds-bullet/src/core/shape.rs"]
pub mod shape;
#[path = "../../rust/crates/mds-bullet/src/core/solver.rs"]
pub mod solver;
pub mod core {
    pub use crate::{body, joint_rows, math, shape, solver};
}
#[path = "../../rust/crates/mds-bullet/tests/pure_bullet/joint_solver.rs"]
mod joint_solver;

#[path = "../../rust/crates/mds-bullet/tests/pure_bullet/body_kernel.rs"]
mod body_kernel;
