#![allow(dead_code)]
#[path = "../../rust/crates/mds-bullet/src/core/axis_sweep.rs"]
pub mod axis_sweep;
#[path = "../../rust/crates/mds-bullet/src/core/math.rs"]
pub mod math;
#[path = "../../rust/crates/mds-bullet/src/core/pair_cache.rs"]
pub mod pair_cache;
mod core {
    pub use crate::{axis_sweep, math, pair_cache};
}
#[path = "../../rust/crates/mds-bullet/tests/pure_bullet/axis_sweep.rs"]
mod fixtures;
