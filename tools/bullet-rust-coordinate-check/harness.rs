#[path = "../../rust/crates/mds-bullet/src/core/joint_coordinates.rs"]
pub mod joint_coordinates;
#[path = "../../rust/crates/mds-bullet/src/core/joint_rows.rs"]
pub mod joint_rows;
#[path = "../../rust/crates/mds-bullet/src/core/math.rs"]
pub mod math;
mod core {
    pub use crate::{joint_coordinates, math};
}
#[path = "../../rust/crates/mds-bullet/tests/pure_bullet/joint_coordinates.rs"]
mod tests;
