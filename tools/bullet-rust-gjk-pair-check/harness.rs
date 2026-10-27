#![allow(dead_code)]
#![allow(clippy::should_implement_trait)]
#[path = "../../rust/crates/mds-bullet/src/core/math.rs"]
pub mod math;
#[path = "../../rust/crates/mds-bullet/src/core/shape.rs"]
pub mod shape;
#[path = "../../rust/crates/mds-bullet/src/core/simplex.rs"]
pub mod simplex;
#[path = "../../rust/crates/mds-bullet/src/core/gjk_epa.rs"]
pub mod gjk_epa;
#[path = "../../rust/crates/mds-bullet/src/core/gjk_pair.rs"]
pub mod gjk_pair;
#[path = "../../rust/crates/mds-bullet/src/core/box_box.rs"]
pub mod box_box;
#[path = "../../rust/crates/mds-bullet/src/core/contact.rs"]
pub mod contact;
mod core {
    pub use crate::{contact, gjk_pair, math, shape, simplex};
}
#[path = "../../rust/crates/mds-bullet/tests/pure_bullet/gjk_pair.rs"]
mod gjk_pair_tests;
