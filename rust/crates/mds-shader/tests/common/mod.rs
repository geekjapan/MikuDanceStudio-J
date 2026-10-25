use std::path::PathBuf;

use mds_shader::vkd3d::Vkd3d;

/// `$MDS_VKD3D_LIB`, or the library that `tools/vkd3d/build.sh` builds for this host.
pub fn vkd3d() -> Vkd3d {
    let path = match std::env::var_os("MDS_VKD3D_LIB") {
        Some(p) => PathBuf::from(p),
        None => {
            let (target, file) = if cfg!(target_os = "macos") {
                ("macos".to_string(), "libvkd3d-shader.1.dylib")
            } else {
                let arch = if cfg!(target_arch = "x86_64") {
                    "amd64"
                } else {
                    "arm64"
                };
                (format!("linux-{arch}"), "libvkd3d-shader.so.1")
            };
            std::env::temp_dir()
                .join("mds-vkd3d")
                .join(target)
                .join("lib")
                .join(file)
        }
    };
    Vkd3d::open(&path).unwrap_or_else(|e| {
        panic!("vkd3d-shader 2.1 not loaded: {e}\nBuild it with tools/vkd3d/build.sh, or set MDS_VKD3D_LIB to the library file.")
    })
}
