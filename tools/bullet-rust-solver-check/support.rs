// Existing kernels are a separate crate so focused lint covers the changed code.
#[path = "../../rust/crates/mds-bullet/src/core/joint_coordinates.rs"]
pub mod joint_coordinates;
#[path = "../../rust/crates/mds-bullet/src/core/joint_rows.rs"]
pub mod joint_rows;
#[path = "../../rust/crates/mds-bullet/src/core/math.rs"]
pub mod math;
#[path = "../../rust/crates/mds-bullet/src/core/time.rs"]
pub mod time;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct InvalidArgument;
