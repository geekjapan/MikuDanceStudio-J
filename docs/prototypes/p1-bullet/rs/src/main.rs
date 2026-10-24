use std::ffi::c_void;
extern "C" {
    fn bt_world_new(links: i32) -> *mut c_void;
    fn bt_world_step(w: *mut c_void, frame: i32);
    fn bt_world_hash(w: *mut c_void) -> u64;
    fn bt_world_tip_y(w: *mut c_void) -> f32;
}
fn main() {
    let frames: i32 = std::env::args().nth(1).map_or(600, |s| s.parse().unwrap());
    unsafe {
        let w = bt_world_new(8);
        let mut trace = String::new();
        for f in 0..frames {
            bt_world_step(w, f);
            trace.push_str(&format!("{f} {:016x}\n", bt_world_hash(w)));
        }
        std::fs::write("trace.txt", &trace).unwrap();
        println!("final {:016x} tip_y {:.9}", bt_world_hash(w), bt_world_tip_y(w));
    }
}
