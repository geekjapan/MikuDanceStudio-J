#![allow(dead_code)]
#[path = "../../rust/crates/mds-bullet/src/core/box_box.rs"]
mod box_box;
#[path = "../../rust/crates/mds-bullet/src/core/math.rs"]
mod math;
#[path = "../../rust/crates/mds-bullet/src/core/shape.rs"]
mod shape;
mod contact {
    include!(env!("BOX_CONTACT_ADAPTER"));
}

fn main() {
    let paths: Vec<String> = std::env::args().collect();
    let input = std::fs::read_to_string(&paths[1]).unwrap();
    let expected = std::fs::read_to_string(&paths[2]).unwrap();
    let (operations, candidates) = contact::box_box_tests::compare_trace(&input, &expected);
    println!("Exact native parity for {operations} operations and {candidates} ordered candidates.");
}

#[path = "../../rust/crates/mds-bullet/src/core/simplex.rs"]
pub mod simplex;
#[path = "../../rust/crates/mds-bullet/src/core/gjk_epa.rs"]
pub mod gjk_epa;
#[path = "../../rust/crates/mds-bullet/src/core/gjk_pair.rs"]
pub mod gjk_pair;
