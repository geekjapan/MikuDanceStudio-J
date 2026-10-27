use std::ffi::{c_char, c_void};

#[cfg(not(any(
    all(target_os = "windows", target_arch = "x86_64"),
    all(target_os = "macos", target_arch = "aarch64"),
    all(
        target_os = "linux",
        any(target_arch = "aarch64", target_arch = "x86_64")
    )
)))]
compile_error!("unsupported native va_list target");

#[repr(C)]
#[derive(Clone, Copy)]
union Slot {
    int: i32,
    uint: u32,
    long: std::ffi::c_long,
    wide: i64,
    pointer: *const c_void,
    double: f64,
    size: usize,
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[repr(C)]
struct Cursor {
    gp_offset: u32,
    fp_offset: u32,
    overflow_arg_area: *const Slot,
    reg_save_area: *const c_void,
}
#[cfg(all(target_os = "linux", target_arch = "aarch64"))]
#[repr(C)]
struct Cursor {
    stack: *const Slot,
    gr_top: *const c_void,
    vr_top: *const c_void,
    gr_offs: i32,
    vr_offs: i32,
}
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
type Native = *mut Cursor;
#[cfg(all(target_os = "linux", target_arch = "aarch64"))]
type Native = Cursor;
#[cfg(any(target_os = "windows", target_os = "macos"))]
type Native = *const Slot;
type Callback = unsafe extern "C" fn(*const c_char, Native);
unsafe extern "C" {
    fn get_callback(mode: i32, marker: *const c_void, format: *const c_char) -> Callback;
    fn check_layout(size: usize, align: usize, slot_size: usize, slot_align: usize);
}

fn main() {
    let mode = std::env::args().nth(1).unwrap_or_else(|| "valid".into());
    assert!(matches!(
        mode.as_str(),
        "valid" | "wrong-slot" | "wrong-offset" | "wrong-promotion" | "wrong-copy"
    ));
    assert_eq!(std::mem::size_of::<Slot>(), 8);
    assert_eq!(std::mem::align_of::<Slot>(), 8);
    let marker = 0x5au8;
    let format = c"%d|%d|%u|%ld|%lld|%s|%p|%a|%.2f|%d|%d|%d|%.1f|%zu";
    let mut evaluations = 0;
    macro_rules! arg {
        ($value:expr) => {{
            evaluations += 1;
            $value
        }};
    }
    let mut slots = [
        arg!(Slot { int: -123456789 }),
        arg!(Slot {
            int: i32::from(-7i8)
        }),
        arg!(Slot {
            uint: 4_000_000_001
        }),
        arg!(Slot { long: -1234567 }),
        arg!(Slot {
            wide: -9_000_000_000_000_001
        }),
        arg!(Slot {
            pointer: c"native-cursor".as_ptr().cast()
        }),
        arg!(Slot {
            pointer: (&marker as *const u8).cast()
        }),
        arg!(Slot { double: -0.0 }),
        arg!(Slot {
            double: f64::from(3.25f32)
        }),
        arg!(Slot { int: 9 }),
        arg!(Slot { int: 10 }),
        arg!(Slot { int: 11 }),
        arg!(Slot { double: 12.5 }),
        arg!(Slot { size: 12345 }),
        Slot { wide: 0 },
        Slot { wide: 0 },
    ];
    assert_eq!(evaluations, 14);
    if mode == "wrong-slot" {
        slots[0] = Slot { int: 42 };
    }
    if mode == "wrong-promotion" {
        slots[8] = Slot {
            wide: i64::from(3.25f32.to_bits()),
        };
    }
    let stack = unsafe { slots.as_ptr().add(usize::from(mode == "wrong-offset")) };
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    let mut cursor = Cursor {
        gp_offset: 48,
        fp_offset: 176,
        overflow_arg_area: stack,
        reg_save_area: std::ptr::null(),
    };
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    let native = &mut cursor as *mut Cursor;
    #[cfg(all(target_os = "linux", target_arch = "aarch64"))]
    let native = Cursor {
        stack,
        gr_top: std::ptr::null(),
        vr_top: std::ptr::null(),
        gr_offs: 0,
        vr_offs: 0,
    };
    #[cfg(any(target_os = "windows", target_os = "macos"))]
    let native = stack;
    #[cfg(target_os = "linux")]
    let layout = (
        std::mem::size_of::<Cursor>(),
        std::mem::align_of::<Cursor>(),
    );
    #[cfg(not(target_os = "linux"))]
    let layout = (
        std::mem::size_of::<Native>(),
        std::mem::align_of::<Native>(),
    );
    unsafe {
        check_layout(
            layout.0,
            layout.1,
            std::mem::size_of::<Slot>(),
            std::mem::align_of::<Slot>(),
        );
        let callback = get_callback(
            i32::from(mode == "wrong-copy"),
            (&marker as *const u8).cast(),
            format.as_ptr(),
        );
        callback(format.as_ptr(), native);
    }
    println!("Rust mode={mode} evaluations={evaluations} PASS");
}

#[cfg(reject_unpromoted)]
fn unsupported_representation() {
    let _ = Slot { double: 3.25f32 };
    let _ = Slot { int: -7i8 };
    let _ = Slot { wide: 1u128 };
}
