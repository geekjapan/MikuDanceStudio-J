#[path = "../../rust/crates/mds-bullet/src/core/dbvt.rs"]
pub mod dbvt;
pub use dbvt_math as math;
#[path = "../../rust/crates/mds-bullet/src/core/pair_cache.rs"]
pub mod pair_cache;

use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering::SeqCst};

struct Capture;
static ENABLED: AtomicBool = AtomicBool::new(false);
static COUNT: AtomicUsize = AtomicUsize::new(0);
static RELEASED: AtomicUsize = AtomicUsize::new(0);
static POINTERS: [AtomicUsize; 32] = [const { AtomicUsize::new(0) }; 32];
static EVENTS: [AtomicUsize; 32] = [const { AtomicUsize::new(0) }; 32];

// Observe real Box releases without allocating inside the allocator callbacks.
unsafe impl GlobalAlloc for Capture {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let pointer = unsafe { System.alloc(layout) };
        if ENABLED.load(SeqCst) && layout.align() == 16 {
            let id = COUNT.fetch_add(1, SeqCst);
            assert!(id < POINTERS.len() && !pointer.is_null());
            POINTERS[id].store(pointer as usize, SeqCst);
        }
        pointer
    }
    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        if ENABLED.load(SeqCst) && layout.align() == 16 {
            let id = POINTERS
                .iter()
                .position(|p| p.load(SeqCst) == pointer as usize)
                .unwrap();
            POINTERS[id].store(0, SeqCst);
            let event = RELEASED.fetch_add(1, SeqCst);
            EVENTS[event].store(id, SeqCst);
        }
        unsafe { System.dealloc(pointer, layout) };
    }
}
#[global_allocator]
static ALLOCATOR: Capture = Capture;

fn main() {
    for scenario in 0..5 {
        for explicit_clear in 0..2 {
            COUNT.store(0, SeqCst);
            RELEASED.store(0, SeqCst);
            ENABLED.store(true, SeqCst);
            let mut tree = dbvt::Dbvt::new();
            let n = match scenario {
                0 => 0,
                1 => 1,
                _ => 4,
            };
            for i in 0..n {
                tree.insert(
                    pair_cache::ProxyKey(i),
                    dbvt::Aabb {
                        min: math::Vec3([(i * 3) as f32, 0.0, 0.0]),
                        max: math::Vec3([(i * 3 + 1) as f32, 1.0, 1.0]),
                    },
                );
            }
            if scenario == 3 {
                tree.remove(pair_cache::ProxyKey(3));
            }
            if scenario == 4 {
                for i in 0..n {
                    tree.remove(pair_cache::ProxyKey(i));
                }
            }
            let before = RELEASED.load(SeqCst);
            let mut moved = tree;
            if explicit_clear == 1 {
                moved.clear();
                moved.clear();
            }
            drop(moved);
            ENABLED.store(false, SeqCst);
            let count = COUNT.load(SeqCst);
            let released = RELEASED.load(SeqCst);
            assert_eq!(count, if n == 0 { 0 } else { 2 * n as usize - 1 });
            assert_eq!(released, count);
            print!("{scenario},{explicit_clear},{count},{before}|");
            for event in &EVENTS[..released] {
                print!("{},", event.load(SeqCst));
            }
            println!();
        }
    }
}
