#[path = "../../rust/crates/mds-bullet/src/core/math.rs"]
pub mod math;
#[path = "../../rust/crates/mds-bullet/src/core/joint_rows.rs"]
pub mod joint_rows_core;
mod core {
    pub use crate::joint_rows_core as joint_rows;
    pub use crate::math;
}
#[path = "../../rust/crates/mds-bullet/tests/pure_bullet/joint_rows.rs"]
mod joint_rows;
