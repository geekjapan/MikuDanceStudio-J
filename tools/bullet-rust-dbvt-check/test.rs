#![forbid(unsafe_code)]
#[path = "../../rust/crates/mds-bullet/src/core/dbvt.rs"]
pub mod dbvt;
pub use dbvt_math as math;
#[path = "../../rust/crates/mds-bullet/src/core/pair_cache.rs"]
pub mod pair_cache;

#[cfg(test)]
#[path = "select.rs"]
mod select;

fn policy() -> dbvt::DbvtPolicy {
    match std::env::var("DBVT_POLICY").unwrap().as_str() {
        "mmd-win64-sse" => dbvt::DbvtPolicy::MmdWin64Sse,
        "generic-reference" => dbvt::DbvtPolicy::GenericReference,
        _ => panic!("explicit DBVT_POLICY required"),
    }
}
#[test]
fn native_controlled_address_parity() {
    dbvt::tests::native_controlled_address_parity(policy());
}
#[test]
fn ordinary_native_and_production_allocator_query_sets() {
    dbvt::tests::ordinary_native_and_production_allocator_query_sets(policy());
}
