use std::cell::RefCell;
use std::collections::BTreeMap;
#[derive(Default)]
struct Ledger {
    row: usize,
    next_algorithm: usize,
    next_manifold: usize,
    algorithms: BTreeMap<u32, usize>,
    manifolds: BTreeMap<u32, usize>,
}
thread_local! { static LEDGER: RefCell<Ledger> = RefCell::new(Ledger::default()); }
pub fn row(row: usize) { LEDGER.with(|s| s.borrow_mut().row = row); }
pub fn algorithm_alloc(key: u32) {
    LEDGER.with(|s| {
        let mut s = s.borrow_mut(); s.next_algorithm += 1; let generation = s.next_algorithm;
        assert!(s.algorithms.insert(key, generation).is_none());
        println!("E {} A+ {}", s.row, generation);
    });
}
pub fn algorithm_free(key: u32) {
    LEDGER.with(|s| {
        let mut s = s.borrow_mut(); let generation = s.algorithms.remove(&key).unwrap();
        assert!(!s.manifolds.contains_key(&key)); println!("E {} A- {}", s.row, generation);
    });
}
pub fn manifold_alloc(key: u32, bodies: [usize; 2]) {
    LEDGER.with(|s| {
        let mut s = s.borrow_mut(); s.next_manifold += 1; let generation = s.next_manifold;
        assert!(s.manifolds.insert(key, generation).is_none());
        println!("E {} M+ {} {} {}", s.row, generation, bodies[0], bodies[1]);
    });
}
pub fn manifold_free(key: u32) {
    LEDGER.with(|s| {
        let mut s = s.borrow_mut(); let generation = s.manifolds.remove(&key).unwrap();
        println!("E {} M- {}", s.row, generation);
    });
}
pub fn unregister(owner: usize) { LEDGER.with(|s| println!("E {} U {}", s.borrow().row, owner)); }
pub fn algorithm(key: u32) -> usize { LEDGER.with(|s| s.borrow().algorithms[&key]) }
pub fn manifold(key: u32) -> usize { LEDGER.with(|s| s.borrow().manifolds[&key]) }
pub fn empty() { LEDGER.with(|s| { let s = s.borrow(); assert!(s.algorithms.is_empty()); assert!(s.manifolds.is_empty()); }); }
pub fn update(owner: usize, start: bool) {
    LEDGER.with(|s| println!("E {} {} {}", s.borrow().row, if start { "U+" } else { "U-" }, owner));
}
