#![allow(dead_code)]
#![allow(clippy::should_implement_trait)]
#[path = "../../rust/crates/mds-bullet/src/core/gjk_epa.rs"]
pub mod gjk_epa;
#[path = "../../rust/crates/mds-bullet/src/core/math.rs"]
pub mod math;
#[path = "../../rust/crates/mds-bullet/src/core/shape.rs"]
pub mod shape;
mod core {
    pub use super::{gjk_epa, math, shape};
}
#[path = "../../rust/crates/mds-bullet/tests/pure_bullet/gjk_epa.rs"]
mod tests;
