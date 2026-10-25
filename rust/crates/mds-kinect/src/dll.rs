//! `Data\DxOpenNI.dll`, loaded at run time like `OpenNiInit` and
//! `DisableKinect` of `src/app/oni_kinect.cpp`. The DLL is the third-party
//! OpenNI wrapper of the original application; nothing links against it.
//!
//! Not run against a device or the DLL: no Kinect was available. The seven
//! exports and their signatures are those of the C++, whose names carry the
//! MSVC `__stdcall` decoration of the 32-bit build (`YG`). A 64-bit process
//! needs a DLL that exports the same names.

use std::ffi::{c_char, c_void, CStr};
use std::os::windows::ffi::OsStrExt;
use std::path::Path;

use libloading::Library;

use crate::error::Error;
use crate::session::Version;

type InitFn =
    unsafe extern "system" fn(*mut c_void, u8, *mut c_void, *const u16, *const c_char) -> u8;
type CleanFn = unsafe extern "system" fn();
type DrawDepthMapFn = unsafe extern "system" fn(u8);
type DepthTextureFn = unsafe extern "system" fn(*mut *mut c_void);
type JointFn = unsafe extern "system" fn(i32, *mut f32);
type IsTrackingFn = unsafe extern "system" fn(*mut u8);
type VersionFn = unsafe extern "system" fn(*mut f32);

/// The seven exports in the order the C++ resolves them.
const EXPORTS: [&[u8]; 7] = [
    b"?OpenNIInit@@YG_NPAUHWND__@@_NPAUIDirect3DDevice9@@PA_WPAD@Z\0",
    b"?OpenNIClean@@YGXXZ\0",
    b"?OpenNIDrawDepthMap@@YGX_N@Z\0",
    b"?OpenNIDepthTexture@@YGXPAPAUIDirect3DTexture9@@@Z\0",
    b"?OpenNIGetSkeltonJointPosition@@YGXHPAUD3DXVECTOR3@@@Z\0",
    b"?OpenNIIsTracking@@YGXPA_N@Z\0",
    b"?OpenNIGetVersion@@YGXPAM@Z\0",
];

/// A loaded and initialized DxOpenNI.dll.
pub struct OpenNi {
    lib: Library,
    clean: CleanFn,
    draw_depth_map: DrawDepthMapFn,
    depth_texture: DepthTextureFn,
    joint: JointFn,
    is_tracking: IsTrackingFn,
    pub version: Version,
}

impl OpenNi {
    /// Loads `Data\DxOpenNI.dll` beside the executable, checks its exports
    /// and version, and runs `OpenNIInit`. `path` is the `.oni` file in the
    /// system code page, or `None` for the live sensor.
    ///
    /// Like the C++, this makes `exe_dir` the current directory first (the
    /// DLL reads its data files from there).
    ///
    /// # Safety
    /// `hwnd` is the main window and `device` the `IDirect3DDevice9` the DLL
    /// may draw its depth map with; both must stay valid until [`stop`].
    ///
    /// [`stop`]: OpenNi::stop
    pub unsafe fn start(
        exe_dir: &Path,
        hwnd: *mut c_void,
        english: bool,
        device: *mut c_void,
        path: Option<&CStr>,
    ) -> Result<OpenNi, Error> {
        let _ = std::env::set_current_dir(exe_dir);
        let dll = exe_dir.join("Data").join("DxOpenNI.dll");
        if std::fs::File::open(&dll).is_err() {
            return Err(Error::NotFound);
        }
        let lib = Library::new(&dll).map_err(|e| {
            // `WindowsError` hides its number; its Debug output is the bare i32.
            let code = match &e {
                libloading::Error::LoadLibraryExW { source } => {
                    format!("{source:?}").parse::<i32>().unwrap_or(0)
                }
                _ => 0,
            };
            Error::CannotLoad {
                code: code as u32,
                detail: std::io::Error::from_raw_os_error(code).to_string(),
            }
        })?;
        // All seven are resolved before any is checked, as in the C++.
        let found: Vec<Option<unsafe extern "system" fn()>> = EXPORTS
            .iter()
            .map(|name| lib.get(*name).ok().map(|s| *s))
            .collect();
        let [Some(init), Some(clean), Some(draw), Some(texture), Some(joint), Some(tracking), Some(version)] =
            found[..]
        else {
            return Err(Error::ExportMissing);
        };
        // SAFETY: each export has the signature declared above (the
        // function-pointer casts of oni_kinect.cpp).
        let get_version: VersionFn = std::mem::transmute(version);
        let mut sensor_version = 0.0f32;
        get_version(&mut sensor_version);
        let version = Version::from_sensor(sensor_version).ok_or(Error::UnsupportedVersion)?;
        let init: InitFn = std::mem::transmute(init);
        let exe_dir_wide: Vec<u16> = exe_dir.as_os_str().encode_wide().chain([0]).collect();
        let ok = init(
            hwnd,
            u8::from(english),
            device,
            exe_dir_wide.as_ptr(),
            path.map_or(std::ptr::null(), CStr::as_ptr),
        );
        if ok == 0 {
            return Err(Error::InitFailed);
        }
        Ok(OpenNi {
            clean,
            draw_depth_map: std::mem::transmute::<unsafe extern "system" fn(), DrawDepthMapFn>(
                draw,
            ),
            depth_texture: std::mem::transmute::<unsafe extern "system" fn(), DepthTextureFn>(
                texture,
            ),
            joint: std::mem::transmute::<unsafe extern "system" fn(), JointFn>(joint),
            is_tracking: std::mem::transmute::<unsafe extern "system" fn(), IsTrackingFn>(tracking),
            lib,
            version,
        })
    }

    /// `OpenNIIsTracking`: a performer is tracked.
    pub fn is_tracking(&self) -> bool {
        let mut tracking = 0u8;
        // SAFETY: `start` resolved the export; the argument is a valid byte.
        unsafe { (self.is_tracking)(&mut tracking) };
        tracking != 0
    }

    /// `OpenNIGetSkeltonJointPosition(id, slot)`, the callback of
    /// [`crate::Capture::pump`].
    pub fn joint(&self, id: i32, slot: &mut [f32; 3]) {
        // SAFETY: as above; the DLL writes three floats.
        unsafe { (self.joint)(id, slot.as_mut_ptr()) };
    }

    /// `OpenNIDrawDepthMap`.
    pub fn draw_depth_map(&self, draw: bool) {
        // SAFETY: as above.
        unsafe { (self.draw_depth_map)(u8::from(draw)) };
    }

    /// `OpenNIDepthTexture`: the `IDirect3DTexture9` of the depth map.
    pub fn depth_texture(&self) -> *mut c_void {
        let mut texture = std::ptr::null_mut();
        // SAFETY: as above.
        unsafe { (self.depth_texture)(&mut texture) };
        texture
    }

    /// `OpenNIClean`. The library stays loaded, like the C++, which never
    /// calls `FreeLibrary` here.
    pub fn stop(self) {
        // SAFETY: as above.
        unsafe { (self.clean)() };
        std::mem::forget(self.lib);
    }
}
