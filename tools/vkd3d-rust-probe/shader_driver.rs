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
#[cfg(not(native_only))]
unsafe extern "C" {
    fn vkd3d_shader_compile(
        info: *const CompileInfo,
        out: *mut Code,
        messages: *mut *mut c_char,
    ) -> i32;
    fn vkd3d_shader_free_shader_code(code: *mut Code);
    fn vkd3d_shader_free_messages(messages: *mut c_char);
}

#[cfg(unix)]
mod loader {
    use super::*;
    unsafe extern "C" {
        fn dlopen(path: *const c_char, mode: i32) -> *mut c_void;
        fn dlsym(handle: *mut c_void, symbol: *const c_char) -> *mut c_void;
        fn dlclose(handle: *mut c_void) -> i32;
    }
    pub unsafe fn open(path: &str) -> *mut c_void {
        let path = CString::new(path).unwrap();
        unsafe { dlopen(path.as_ptr(), 2) }
    }
    pub unsafe fn symbol(handle: *mut c_void, name: &CStr) -> *mut c_void {
        unsafe { dlsym(handle, name.as_ptr()) }
    }
    pub unsafe fn close(handle: *mut c_void) {
        unsafe {
            dlclose(handle);
        }
    }
    #[cfg(target_os = "linux")]
    pub fn modules() -> Vec<String> {
        std::fs::read_to_string("/proc/self/maps")
            .unwrap()
            .lines()
            .filter_map(|line| line.find('/').map(|start| line[start..].to_owned()))
            .collect()
    }
    #[cfg(target_os = "macos")]
    pub fn modules() -> Vec<String> {
        unsafe extern "C" {
            fn _dyld_image_count() -> u32;
            fn _dyld_get_image_name(index: u32) -> *const c_char;
        }
        unsafe {
            (0.._dyld_image_count())
                .map(|index| {
                    CStr::from_ptr(_dyld_get_image_name(index))
                        .to_str()
                        .unwrap()
                        .to_owned()
                })
                .collect()
        }
    }
}

#[cfg(windows)]
mod loader {
    use super::*;
    use std::os::windows::ffi::{OsStrExt, OsStringExt};
    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn LoadLibraryExW(path: *const u16, file: *mut c_void, flags: u32) -> *mut c_void;
        fn GetProcAddress(handle: *mut c_void, name: *const c_char) -> *mut c_void;
        fn FreeLibrary(handle: *mut c_void) -> i32;
        fn GetModuleFileNameW(handle: *mut c_void, path: *mut u16, size: u32) -> u32;
        fn GetCurrentProcess() -> *mut c_void;
        fn K32EnumProcessModules(
            process: *mut c_void,
            modules: *mut *mut c_void,
            bytes: u32,
            needed: *mut u32,
        ) -> i32;
    }
    pub unsafe fn open(path: &str) -> *mut c_void {
        assert!(
            std::path::Path::new(path).is_absolute(),
            "native DLL path must be absolute"
        );
        let wide: Vec<u16> = std::ffi::OsStr::new(path)
            .encode_wide()
            .chain(Some(0))
            .collect();
        unsafe { LoadLibraryExW(wide.as_ptr(), ptr::null_mut(), 0x100 | 0x1000) }
    }
    pub unsafe fn symbol(handle: *mut c_void, name: &CStr) -> *mut c_void {
        unsafe { GetProcAddress(handle, name.as_ptr()) }
    }
    pub unsafe fn close(handle: *mut c_void) {
        unsafe {
            FreeLibrary(handle);
        }
    }
    pub fn modules() -> Vec<String> {
        let mut modules = vec![ptr::null_mut(); 1024];
        let mut needed = 0;
        unsafe {
            assert_ne!(
                K32EnumProcessModules(
                    GetCurrentProcess(),
                    modules.as_mut_ptr(),
                    (modules.len() * size_of::<*mut c_void>()) as u32,
                    &mut needed
                ),
                0,
                "module enumeration failed"
            );
            assert!(
                (needed as usize) <= modules.len() * size_of::<*mut c_void>(),
                "module list truncated"
            );
            modules.truncate(needed as usize / size_of::<*mut c_void>());
            modules
                .into_iter()
                .map(|module| {
                    let mut path = vec![0u16; 32768];
                    let count = GetModuleFileNameW(module, path.as_mut_ptr(), path.len() as u32);
                    assert!(
                        count > 0 && (count as usize) < path.len(),
                        "module path unavailable"
                    );
                    std::ffi::OsString::from_wide(&path[..count as usize])
                        .into_string()
                        .unwrap()
                })
                .collect()
        }
    }
}

unsafe fn native_api(path: &str, handle: &mut *mut c_void) -> (Compile, FreeCode, FreeMessages) {
    unsafe {
        *handle = loader::open(path);
        assert!(!handle.is_null(), "native baseline load failed");
        let a = loader::symbol(*handle, c"vkd3d_shader_compile");
        let b = loader::symbol(*handle, c"vkd3d_shader_free_shader_code");
        let c = loader::symbol(*handle, c"vkd3d_shader_free_messages");
        if a.is_null() || b.is_null() || c.is_null() {
            loader::close(*handle);
            panic!("native API missing");
        }
        (
            std::mem::transmute::<*mut c_void, Compile>(a),
            std::mem::transmute::<*mut c_void, FreeCode>(b),
            std::mem::transmute::<*mut c_void, FreeMessages>(c),
        )
    }
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
        #[cfg(native_only)]
        let (compile, free_code, free_messages) = {
            assert_ne!(args[5], "-", "native-only caller requires a library");
            native_api(&args[5], &mut handle)
        };
        #[cfg(not(native_only))]
        let (compile, free_code, free_messages): (Compile, FreeCode, FreeMessages) =
            if args[5] == "-" {
                (
                    vkd3d_shader_compile,
                    vkd3d_shader_free_shader_code,
                    vkd3d_shader_free_messages,
                )
            } else {
                native_api(&args[5], &mut handle)
            };
        if !handle.is_null() {
            let mut paths = loader::modules();
            paths.sort();
            paths.dedup();
            std::fs::write(format!("{}.modules", args[4]), paths.join("\n")).unwrap();
        }
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
            loader::close(handle);
        }
    }
}
