#[path = "../../rust/crates/mds-bullet/src/core/pair_cache.rs"]
pub mod pair_cache;
mod core {
    pub use crate::pair_cache;
}
#[path = "../../rust/crates/mds-bullet/tests/pure_bullet/pair_cache.rs"]
mod fixtures;
