#[path = "../../rust/crates/mds-bullet/src/core/activation.rs"]
pub mod activation;
#[path = "../../rust/crates/mds-bullet/src/core/box_box.rs"]
pub mod box_box;
#[path = "../../rust/crates/mds-bullet/src/core/islands.rs"]
pub mod islands;
extern crate bullet_core_support as base;
pub use base::{joint_coordinates, joint_rows, math, time, InvalidArgument};
#[path = "../../rust/crates/mds-bullet/src/core/body.rs"]
pub mod body;
#[path = "../../rust/crates/mds-bullet/src/core/contact.rs"]
pub mod contact;
#[path = "../../rust/crates/mds-bullet/src/core/contact_solver.rs"]
pub mod contact_solver;
#[path = "../../rust/crates/mds-bullet/src/core/shape.rs"]
pub mod shape;
#[path = "../../rust/crates/mds-bullet/src/core/solver.rs"]
pub mod solver;
pub mod core {
    pub use crate::{
        activation, body, contact, contact_solver, islands, joint_rows, math, shape, solver,
    };
}
#[path = "../../rust/crates/mds-bullet/tests/pure_bullet/contact_solver.rs"]
mod contact_solver_tests;

#[path = "../../rust/crates/mds-bullet/src/core/gjk_epa.rs"]
pub mod gjk_epa;
#[path = "../../rust/crates/mds-bullet/src/core/gjk_pair.rs"]
pub mod gjk_pair;
#[path = "../../rust/crates/mds-bullet/src/core/simplex.rs"]
pub mod simplex;
