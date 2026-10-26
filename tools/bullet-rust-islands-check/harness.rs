#![allow(dead_code)]
#![allow(clippy::should_implement_trait)]
#[path = "../../rust/crates/mds-bullet/src/core/activation.rs"]
pub mod activation;
#[path = "../../rust/crates/mds-bullet/src/core/islands.rs"]
pub mod islands;
#[path = "../../rust/crates/mds-bullet/src/core/math.rs"]
pub mod math;
mod core {
    pub use super::{activation, islands};
}
#[path = "../../rust/crates/mds-bullet/tests/pure_bullet/islands.rs"]
mod tests;
