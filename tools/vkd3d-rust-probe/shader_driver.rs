//! Prototype C ABI caller. The compiler archive is generated Rust; native is comparison only.
use std::{
    ffi::{CStr, CString, c_char, c_void},
    ptr,
};
#[repr(C)]
struct Code {
    code: *const c_void,
    size: usize,
}
#[repr(C)]
struct OptionValue {
    name: u32,
    value: u32,
}
#[repr(C)]
struct CompileInfo {
    ty: u32,
    next: *const c_void,
    source: Code,
    source_type: u32,
    target_type: u32,
    options: *const OptionValue,
    option_count: u32,
    log_level: u32,
    source_name: *const c_char,
}
#[repr(C)]
struct HlslInfo {
    ty: u32,
    next: *const c_void,
    entry: *const c_char,
    secondary: Code,
    profile: *const c_char,
}
#[repr(C)]
struct SpirvTargetInfo {
    ty: u32,
    next: *const c_void,
    entry_point: *const c_char,
    environment: u32,
    extensions: *const u32,
    extension_count: u32,
    parameters: *const c_void,
    parameter_count: u32,
    dual_source_blending: bool,
    output_swizzles: *const u32,
    output_swizzle_count: u32,
}
type Compile = unsafe extern "C" fn(*const CompileInfo, *mut Code, *mut *mut c_char) -> i32;
type FreeCode = unsafe extern "C" fn(*mut Code);
type FreeMessages = unsafe extern "C" fn(*mut c_char);
unsafe extern "C" {
    fn vkd3d_shader_compile(
        info: *const CompileInfo,
        out: *mut Code,
        messages: *mut *mut c_char,
    ) -> i32;
    fn vkd3d_shader_free_shader_code(code: *mut Code);
    fn vkd3d_shader_free_messages(messages: *mut c_char);
    fn dlopen(path: *const c_char, mode: i32) -> *mut c_void;
    fn dlsym(handle: *mut c_void, symbol: *const c_char) -> *mut c_void;
    fn dlclose(handle: *mut c_void) -> i32;
}
fn main() {
    let args: Vec<_> = std::env::args().collect();
    assert!(
        args.len() == 6 || (args.len() == 7 && args[6] == "no-float-controls"),
        "source profile target output native-library-or-dash [no-float-controls]"
    );
    let source = std::fs::read(&args[1]).unwrap();
    let profile = CString::new(args[2].as_str()).unwrap();
    let target: u32 = args[3].parse().unwrap();
    let options = [OptionValue { name: 4, value: 21 }];
    let extensions = [6u32]; // VKD3D_SHADER_SPIRV_EXTENSION_KHR_FLOAT_CONTROLS.
    let spirv = SpirvTargetInfo {
        ty: 4,
        next: ptr::null(),
        entry_point: ptr::null(),
        environment: 2, // Preserve the default Vulkan 1.0 environment.
        extensions: extensions.as_ptr(),
        extension_count: u32::from(args.len() == 6),
        parameters: ptr::null(),
        parameter_count: 0,
        dual_source_blending: false,
        output_swizzles: ptr::null(),
        output_swizzle_count: 0,
    };
    let hlsl = HlslInfo {
        ty: 6,
        next: if target == 1 {
            (&spirv as *const SpirvTargetInfo).cast()
        } else {
            ptr::null()
        },
        entry: c"main".as_ptr(),
        secondary: Code {
            code: ptr::null(),
            size: 0,
        },
        profile: profile.as_ptr(),
    };
    let info = CompileInfo {
        ty: 0,
        next: (&hlsl as *const HlslInfo).cast(),
        source: Code {
            code: source.as_ptr().cast(),
            size: source.len(),
        },
        source_type: 2,
        target_type: target,
        options: options.as_ptr(),
        option_count: 1,
        log_level: 1,
        source_name: c"matrix.hlsl".as_ptr(),
    };
    unsafe {
        let mut handle = ptr::null_mut();
        let (compile, free_code, free_messages): (Compile, FreeCode, FreeMessages) =
            if args[5] == "-" {
                (
                    vkd3d_shader_compile,
                    vkd3d_shader_free_shader_code,
                    vkd3d_shader_free_messages,
                )
            } else {
                let path = CString::new(args[5].as_str()).unwrap();
                handle = dlopen(path.as_ptr(), 2);
                assert!(!handle.is_null(), "native baseline dlopen failed");
                let a = dlsym(handle, c"vkd3d_shader_compile".as_ptr());
                let b = dlsym(handle, c"vkd3d_shader_free_shader_code".as_ptr());
                let c = dlsym(handle, c"vkd3d_shader_free_messages".as_ptr());
                assert!(
                    !a.is_null() && !b.is_null() && !c.is_null(),
                    "native API missing"
                );
                (
                    std::mem::transmute::<*mut c_void, Compile>(a),
                    std::mem::transmute::<*mut c_void, FreeCode>(b),
                    std::mem::transmute::<*mut c_void, FreeMessages>(c),
                )
            };
        let mut out = Code {
            code: ptr::null(),
            size: 0,
        };
        let mut messages = ptr::null_mut();
        let result = compile(&info, &mut out, &mut messages);
        std::fs::write(format!("{}.status", args[4]), result.to_string()).unwrap();
        let diagnostics = if messages.is_null() {
            &[][..]
        } else {
            CStr::from_ptr(messages).to_bytes()
        };
        std::fs::write(format!("{}.diagnostics", args[4]), diagnostics).unwrap();
        // Failed compilation can leave an output pointer already freed by the compiler.
        let bytes = if result < 0 || out.code.is_null() {
            &[][..]
        } else {
            std::slice::from_raw_parts(out.code.cast::<u8>(), out.size)
        };
        std::fs::write(&args[4], bytes).unwrap();
        if result >= 0 {
            free_code(&mut out);
        }
        if !messages.is_null() {
            free_messages(messages);
        }
        if !handle.is_null() {
            dlclose(handle);
        }
    }
}
