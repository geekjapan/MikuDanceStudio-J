#[path = "../../rust/crates/mds-bullet/src/core/math.rs"]
pub mod math;
#[path = "../../rust/crates/mds-bullet/src/core/simplex.rs"]
pub mod simplex;
pub mod core {
    pub use crate::{math, simplex};
}
#[path = "../../rust/crates/mds-bullet/tests/pure_bullet/simplex.rs"]
mod trace;
fn main() {
    let paths: Vec<String> = std::env::args().collect();
    let input = std::fs::read_to_string(&paths[1]).unwrap();
    if let Some(expected) = paths.get(2) {
        trace::compare_trace(&input, &std::fs::read_to_string(expected).unwrap());
    } else {
        print!("{}", trace::trace(&input));
    }
}
