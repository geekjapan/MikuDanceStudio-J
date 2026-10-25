//! vkd3d-shader 2.1, loaded at run time.
//!
//! vkd3d-shader is LGPL-2.1. Gate G3 ships it as a separate shared library, so this module
//! opens it with `libloading` and declares the few C types it needs by hand from
//! `vkd3d_shader.h`. Nothing links against it at build time.

use std::ffi::{c_char, c_int, c_uint, c_void, CStr, CString};
use std::path::{Path, PathBuf};

use libloading::Library;

/// Environment variable that names the library file to load.
pub const LIB_ENV: &str = "MDS_VKD3D_LIB";

/// File names tried next to the executable, in order.
#[cfg(target_os = "macos")]
const LIB_NAMES: &[&str] = &["libvkd3d-shader.1.dylib", "libvkd3d-shader.dylib"];
#[cfg(windows)]
const LIB_NAMES: &[&str] = &["libvkd3d-shader-1.dll", "vkd3d-shader.dll"];
#[cfg(not(any(target_os = "macos", windows)))]
const LIB_NAMES: &[&str] = &["libvkd3d-shader.so.1", "libvkd3d-shader.so"];

// enum vkd3d_shader_structure_type
const STRUCTURE_TYPE_COMPILE_INFO: c_uint = 0;
const STRUCTURE_TYPE_SCAN_DESCRIPTOR_INFO: c_uint = 2;
const STRUCTURE_TYPE_SPIRV_TARGET_INFO: c_uint = 4;
const STRUCTURE_TYPE_HLSL_SOURCE_INFO: c_uint = 6;
const STRUCTURE_TYPE_SCAN_SIGNATURE_INFO: c_uint = 9;
// enum vkd3d_shader_source_type
const SOURCE_HLSL: c_uint = 2;
// enum vkd3d_shader_compile_option_name
const OPTION_FORMATTING: c_uint = 3;
const OPTION_API_VERSION: c_uint = 4;
const OPTION_FEATURE: c_uint = 0xa;
const OPTION_DENORMAL_MODE_F16: c_uint = 0xe;
const OPTION_DENORMAL_MODE_F32: c_uint = 0xf;
const OPTION_DENORMAL_MODE_F64: c_uint = 0x10;
// option values
const API_VERSION_2_1: c_uint = 21;
const FEATURE_INT64_FLOAT64: c_uint = 0x1 | 0x2;
const FORMATTING_INDENT_HEADER: c_uint = 0x2 | 0x8;
const DENORMAL_MODE_ANY: c_uint = 0;
// enum vkd3d_shader_log_level
const LOG_ERROR: c_uint = 1;
// enum vkd3d_shader_spirv_environment
const SPIRV_ENVIRONMENT_VULKAN_1_0: c_uint = 2;

#[repr(C)]
struct Code {
    code: *const c_void,
    size: usize,
}

#[repr(C)]
struct CompileOption {
    name: c_uint,
    value: c_uint,
}

#[repr(C)]
struct CompileInfo {
    ty: c_uint,
    next: *const c_void,
    source: Code,
    source_type: c_uint,
    target_type: c_uint,
    options: *const CompileOption,
    option_count: c_uint,
    log_level: c_uint,
    source_name: *const c_char,
}

#[repr(C)]
struct HlslSourceInfo {
    ty: c_uint,
    next: *const c_void,
    entry_point: *const c_char,
    secondary_code: Code,
    profile: *const c_char,
}

#[repr(C)]
struct SpirvTargetInfo {
    ty: c_uint,
    next: *const c_void,
    entry_point: *const c_char,
    environment: c_uint,
    extensions: *const c_uint,
    extension_count: c_uint,
    parameters: *const c_void,
    parameter_count: c_uint,
    dual_source_blending: bool,
    output_swizzles: *const c_uint,
    output_swizzle_count: c_uint,
}

#[repr(C)]
struct SignatureElement {
    semantic_name: *const c_char,
    semantic_index: c_uint,
    stream_index: c_uint,
    sysval_semantic: c_uint,
    component_type: c_uint,
    register_index: c_uint,
    mask: c_uint,
    used_mask: c_uint,
    min_precision: c_uint,
}

#[repr(C)]
struct Signature {
    elements: *mut SignatureElement,
    element_count: c_uint,
}

#[repr(C)]
struct ScanSignatureInfo {
    ty: c_uint,
    next: *const c_void,
    input: Signature,
    output: Signature,
    patch_constant: Signature,
}

#[repr(C)]
struct DescriptorInfo {
    ty: c_uint,
    register_space: c_uint,
    register_index: c_uint,
    resource_type: c_uint,
    resource_data_type: c_uint,
    flags: c_uint,
    count: c_uint,
}

#[repr(C)]
struct ScanDescriptorInfo {
    ty: c_uint,
    next: *const c_void,
    descriptors: *mut DescriptorInfo,
    descriptor_count: c_uint,
}

/// One element of an input or output signature (`vkd3d_shader_signature_element`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Element {
    /// The HLSL semantic, such as `TEXCOORD`, in the case the source used.
    pub semantic: String,
    pub index: u32,
    /// `v#` or `o#`; for the sm3 `VPOS` and `VFACE` inputs, the `MISCTYPE` register (0 or 1).
    pub register: u32,
    /// `enum vkd3d_shader_sysval_semantic`: [`SV_POSITION`], [`SV_IS_FRONT_FACE`], ...
    pub sysval: u32,
    pub mask: u32,
}

pub const SV_POSITION: u32 = 0x01;
pub const SV_IS_FRONT_FACE: u32 = 0x09;

/// One descriptor the shader uses (`vkd3d_shader_descriptor_info`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Descriptor {
    /// `enum vkd3d_shader_descriptor_type`: [`DESCRIPTOR_SRV`], [`DESCRIPTOR_SAMPLER`], ...
    pub kind: u32,
    pub register: u32,
    /// `enum vkd3d_shader_resource_type`: [`RESOURCE_TEXTURE_2D`], ...
    pub resource: u32,
}

pub const DESCRIPTOR_SRV: u32 = 0;
pub const DESCRIPTOR_CBV: u32 = 2;
pub const DESCRIPTOR_SAMPLER: u32 = 3;
pub const RESOURCE_TEXTURE_1D: u32 = 2;
pub const RESOURCE_TEXTURE_2D: u32 = 3;
pub const RESOURCE_TEXTURE_3D: u32 = 5;
pub const RESOURCE_TEXTURE_CUBE: u32 = 6;

/// What [`Vkd3d::scan_hlsl`] reports: the program that the SPIR-V target writes, before the
/// D3D bytecode writer, so it holds for shaders that `vkd3d_shader_compile` to D3D bytecode or
/// assembly rejects for their temp count (E9015).
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Scan {
    pub inputs: Vec<Element>,
    pub outputs: Vec<Element>,
    pub descriptors: Vec<Descriptor>,
}

type CompileFn = unsafe extern "C" fn(*const CompileInfo, *mut Code, *mut *mut c_char) -> c_int;
type ScanFn = unsafe extern "C" fn(*const CompileInfo, *mut *mut c_char) -> c_int;
type FreeSignatureFn = unsafe extern "C" fn(*mut ScanSignatureInfo);
type FreeDescriptorsFn = unsafe extern "C" fn(*mut ScanDescriptorInfo);
type FreeCodeFn = unsafe extern "C" fn(*mut Code);
type FreeMessagesFn = unsafe extern "C" fn(*mut c_char);
type GetVersionFn = unsafe extern "C" fn(*mut c_uint, *mut c_uint) -> *const c_char;

/// What `vkd3d_shader_compile` writes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Target {
    SpirvBinary = 1,
    D3dAsm = 3,
    D3dBytecode = 4,
}

/// A failed compile: the vkd3d return code and its error messages.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CompileError {
    pub code: i32,
    pub messages: String,
}

impl CompileError {
    /// The first message with an error code (`E5027: ...`), without its source location.
    pub fn summary(&self) -> String {
        let line = self
            .messages
            .lines()
            .find(|l| l.contains(": E"))
            .or_else(|| self.messages.lines().next())
            .unwrap_or("");
        let short = match line.find(": E") {
            Some(i) => &line[i + 2..],
            None => line,
        };
        if short.is_empty() {
            format!("vkd3d-shader returned {}", self.code)
        } else {
            short.to_string()
        }
    }
}

/// The loaded library.
pub struct Vkd3d {
    compile: CompileFn,
    scan: ScanFn,
    free_signature: FreeSignatureFn,
    free_descriptors: FreeDescriptorsFn,
    free_code: FreeCodeFn,
    free_messages: FreeMessagesFn,
    path: PathBuf,
    version: String,
    // Keeps the function pointers above valid.
    _lib: Library,
}

impl Vkd3d {
    /// Loads the library named by `MDS_VKD3D_LIB`, or else the one next to the executable.
    pub fn load() -> Result<Vkd3d, String> {
        if let Some(p) = std::env::var_os(LIB_ENV) {
            return Self::open(Path::new(&p));
        }
        let exe =
            std::env::current_exe().map_err(|e| format!("cannot find the executable: {e}"))?;
        let dir = exe.parent().unwrap_or(Path::new("."));
        for name in LIB_NAMES {
            let p = dir.join(name);
            if p.is_file() {
                return Self::open(&p);
            }
        }
        Err(format!(
            "vkd3d-shader not found: set {LIB_ENV} to the library file, or put {} next to {}",
            LIB_NAMES[0],
            exe.display()
        ))
    }

    /// Loads the library at `path` and checks that it is vkd3d-shader 2.1.
    pub fn open(path: &Path) -> Result<Vkd3d, String> {
        if !path.is_file() {
            return Err(format!("{}: not a file", path.display()));
        }
        let err = |e: libloading::Error| format!("{}: {e}", path.display());
        // SAFETY: loading runs the library's initializers. The path is the vkd3d-shader library
        // the operator names; the version check below rejects other libraries that happen to
        // export the same symbols.
        unsafe {
            let lib = load(path).map_err(err)?;
            let get_version: GetVersionFn = *lib.get(b"vkd3d_shader_get_version\0").map_err(err)?;
            let (mut major, mut minor) = (0, 0);
            let v = get_version(&mut major, &mut minor);
            let version = if v.is_null() {
                String::new()
            } else {
                CStr::from_ptr(v).to_string_lossy().into_owned()
            };
            if (major, minor) != (2, 1) {
                return Err(format!(
                    "{}: vkd3d-shader {major}.{minor} ({version:?}), need 2.1",
                    path.display()
                ));
            }
            Ok(Vkd3d {
                compile: *lib.get(b"vkd3d_shader_compile\0").map_err(err)?,
                scan: *lib.get(b"vkd3d_shader_scan\0").map_err(err)?,
                free_signature: *lib
                    .get(b"vkd3d_shader_free_scan_signature_info\0")
                    .map_err(err)?,
                free_descriptors: *lib
                    .get(b"vkd3d_shader_free_scan_descriptor_info\0")
                    .map_err(err)?,
                free_code: *lib.get(b"vkd3d_shader_free_shader_code\0").map_err(err)?,
                free_messages: *lib.get(b"vkd3d_shader_free_messages\0").map_err(err)?,
                path: path.to_path_buf(),
                version,
                _lib: lib,
            })
        }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn version(&self) -> &str {
        &self.version
    }

    /// Compiles HLSL `source` with `profile` (such as `ps_3_0`) and `entry`, as
    /// `vkd3d-compiler -x hlsl -p <profile> -e <entry> -b <target>` does.
    pub fn compile_hlsl(
        &self,
        source: &str,
        source_name: &str,
        profile: &str,
        entry: &str,
        target: Target,
    ) -> Result<Vec<u8>, CompileError> {
        let cstr = |s: &str| {
            CString::new(s).map_err(|_| CompileError {
                code: -1,
                messages: format!("{s:?} contains a NUL byte"),
            })
        };
        let (name, profile, entry) = (cstr(source_name)?, cstr(profile)?, cstr(entry)?);
        let mut options = vec![
            CompileOption {
                name: OPTION_FORMATTING,
                value: FORMATTING_INDENT_HEADER,
            },
            CompileOption {
                name: OPTION_API_VERSION,
                value: API_VERSION_2_1,
            },
        ];
        if target == Target::SpirvBinary {
            options.push(CompileOption {
                name: OPTION_FEATURE,
                value: FEATURE_INT64_FLOAT64,
            });
        }
        for name in [
            OPTION_DENORMAL_MODE_F16,
            OPTION_DENORMAL_MODE_F32,
            OPTION_DENORMAL_MODE_F64,
        ] {
            options.push(CompileOption {
                name,
                value: DENORMAL_MODE_ANY,
            });
        }
        let spirv = SpirvTargetInfo {
            ty: STRUCTURE_TYPE_SPIRV_TARGET_INFO,
            next: std::ptr::null(),
            entry_point: entry.as_ptr(),
            environment: SPIRV_ENVIRONMENT_VULKAN_1_0,
            extensions: std::ptr::null(),
            extension_count: 0,
            parameters: std::ptr::null(),
            parameter_count: 0,
            dual_source_blending: false,
            output_swizzles: std::ptr::null(),
            output_swizzle_count: 0,
        };
        let hlsl = HlslSourceInfo {
            ty: STRUCTURE_TYPE_HLSL_SOURCE_INFO,
            next: (&spirv as *const SpirvTargetInfo).cast(),
            entry_point: entry.as_ptr(),
            secondary_code: Code {
                code: std::ptr::null(),
                size: 0,
            },
            profile: profile.as_ptr(),
        };
        let info = CompileInfo {
            ty: STRUCTURE_TYPE_COMPILE_INFO,
            next: (&hlsl as *const HlslSourceInfo).cast(),
            source: Code {
                code: source.as_ptr().cast(),
                size: source.len(),
            },
            source_type: SOURCE_HLSL,
            target_type: target as c_uint,
            options: options.as_ptr(),
            option_count: options.len() as c_uint,
            log_level: LOG_ERROR,
            source_name: name.as_ptr(),
        };
        let mut out = Code {
            code: std::ptr::null(),
            size: 0,
        };
        let mut messages: *mut c_char = std::ptr::null_mut();
        // SAFETY: every pointer in `info` points into locals that outlive the call. vkd3d
        // allocates `out` and `messages`; both are copied and freed with vkd3d's own functions.
        unsafe {
            let ret = (self.compile)(&info, &mut out, &mut messages);
            let text = if messages.is_null() {
                String::new()
            } else {
                let s = CStr::from_ptr(messages).to_string_lossy().into_owned();
                (self.free_messages)(messages);
                s
            };
            if ret < 0 {
                (self.free_code)(&mut out);
                return Err(CompileError {
                    code: ret,
                    messages: text,
                });
            }
            let bytes = if out.code.is_null() {
                Vec::new()
            } else {
                std::slice::from_raw_parts(out.code.cast::<u8>(), out.size).to_vec()
            };
            (self.free_code)(&mut out);
            Ok(bytes)
        }
    }

    /// The input and output signatures and the descriptors of HLSL `source`, from
    /// `vkd3d_shader_scan`.
    pub fn scan_hlsl(
        &self,
        source: &str,
        source_name: &str,
        profile: &str,
        entry: &str,
    ) -> Result<Scan, CompileError> {
        let cstr = |s: &str| {
            CString::new(s).map_err(|_| CompileError {
                code: -1,
                messages: format!("{s:?} contains a NUL byte"),
            })
        };
        let (name, profile, entry) = (cstr(source_name)?, cstr(profile)?, cstr(entry)?);
        let empty = || Signature {
            elements: std::ptr::null_mut(),
            element_count: 0,
        };
        let mut descriptors = ScanDescriptorInfo {
            ty: STRUCTURE_TYPE_SCAN_DESCRIPTOR_INFO,
            next: std::ptr::null(),
            descriptors: std::ptr::null_mut(),
            descriptor_count: 0,
        };
        let mut signatures = ScanSignatureInfo {
            ty: STRUCTURE_TYPE_SCAN_SIGNATURE_INFO,
            next: std::ptr::addr_of_mut!(descriptors).cast_const().cast(),
            input: empty(),
            output: empty(),
            patch_constant: empty(),
        };
        let hlsl = HlslSourceInfo {
            ty: STRUCTURE_TYPE_HLSL_SOURCE_INFO,
            next: std::ptr::addr_of_mut!(signatures).cast_const().cast(),
            entry_point: entry.as_ptr(),
            secondary_code: Code {
                code: std::ptr::null(),
                size: 0,
            },
            profile: profile.as_ptr(),
        };
        let options = [CompileOption {
            name: OPTION_API_VERSION,
            value: API_VERSION_2_1,
        }];
        let info = CompileInfo {
            ty: STRUCTURE_TYPE_COMPILE_INFO,
            next: (&hlsl as *const HlslSourceInfo).cast(),
            source: Code {
                code: source.as_ptr().cast(),
                size: source.len(),
            },
            source_type: SOURCE_HLSL,
            target_type: Target::SpirvBinary as c_uint,
            options: options.as_ptr(),
            option_count: options.len() as c_uint,
            log_level: LOG_ERROR,
            source_name: name.as_ptr(),
        };
        let mut messages: *mut c_char = std::ptr::null_mut();
        // SAFETY: as in `compile_hlsl`. vkd3d fills `signatures` and `descriptors` through the
        // `next` chain; both are copied, then freed with vkd3d's own functions.
        unsafe {
            let ret = (self.scan)(&info, &mut messages);
            let text = if messages.is_null() {
                String::new()
            } else {
                let s = CStr::from_ptr(messages).to_string_lossy().into_owned();
                (self.free_messages)(messages);
                s
            };
            let elements = |s: &Signature| -> Vec<Element> {
                if s.elements.is_null() {
                    return Vec::new();
                }
                std::slice::from_raw_parts(s.elements, s.element_count as usize)
                    .iter()
                    .map(|e| Element {
                        semantic: if e.semantic_name.is_null() {
                            String::new()
                        } else {
                            CStr::from_ptr(e.semantic_name)
                                .to_string_lossy()
                                .into_owned()
                        },
                        index: e.semantic_index,
                        register: e.register_index,
                        sysval: e.sysval_semantic,
                        mask: e.mask,
                    })
                    .collect()
            };
            let scan = Scan {
                inputs: elements(&signatures.input),
                outputs: elements(&signatures.output),
                descriptors: if descriptors.descriptors.is_null() {
                    Vec::new()
                } else {
                    std::slice::from_raw_parts(
                        descriptors.descriptors,
                        descriptors.descriptor_count as usize,
                    )
                    .iter()
                    .map(|d| Descriptor {
                        kind: d.ty,
                        register: d.register_index,
                        resource: d.resource_type,
                    })
                    .collect()
                },
            };
            (self.free_signature)(&mut signatures);
            (self.free_descriptors)(&mut descriptors);
            if ret < 0 {
                return Err(CompileError {
                    code: ret,
                    messages: text,
                });
            }
            Ok(scan)
        }
    }
}

/// On Windows the mingw build imports `libgcc_s_seh-1.dll`, which ships beside it. The default
/// `LoadLibraryExW` search skips the library's own directory, so ask for it explicitly.
#[cfg(windows)]
unsafe fn load(path: &Path) -> Result<Library, libloading::Error> {
    use libloading::os::windows::{
        Library as WindowsLibrary, LOAD_LIBRARY_SEARCH_DEFAULT_DIRS,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR,
    };
    let path = std::path::absolute(path).unwrap_or_else(|_| path.to_path_buf());
    WindowsLibrary::load_with_flags(
        &path,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS,
    )
    .map(Library::from)
}

#[cfg(not(windows))]
unsafe fn load(path: &Path) -> Result<Library, libloading::Error> {
    Library::new(path)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn summary_strips_the_location() {
        let e = CompileError {
            code: -4,
            messages: "a.hlsl:3:5: W5300: Implicit truncation.\na.hlsl:9:1: E5027: Infinities are not allowed.\n".into(),
        };
        assert_eq!(e.summary(), "E5027: Infinities are not allowed.");
        let e = CompileError {
            code: -4,
            messages: String::new(),
        };
        assert_eq!(e.summary(), "vkd3d-shader returned -4");
    }

    #[test]
    fn open_rejects_a_missing_file() {
        let err = Vkd3d::open(Path::new("/nonexistent/libvkd3d-shader.so"))
            .err()
            .unwrap();
        assert!(err.contains("not a file"), "{err}");
    }
}
