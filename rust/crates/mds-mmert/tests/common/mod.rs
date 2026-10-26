//! What the GPU tests need from the host: a wgpu adapter, the vkd3d-shader library, and the
//! ray-mmd corpus. Each one that is missing prints SKIP and returns `None`; a skip is not a pass.

#![allow(dead_code)]

use std::path::{Path, PathBuf};

use mds_mmert::Gpu;
use mds_shader::vkd3d::Vkd3d;

pub fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

pub fn gpu() -> Option<Gpu> {
    let gpu = Gpu::new().expect("wgpu instance");
    if gpu.is_none() {
        eprintln!("SKIP: no wgpu adapter (a skip is not a pass)");
    }
    gpu
}

/// `MDS_VKD3D_LIB`, else the library `tools/vkd3d/build.sh` leaves in the temp directory.
pub fn vkd3d_path() -> PathBuf {
    match std::env::var_os("MDS_VKD3D_LIB") {
        Some(p) => PathBuf::from(p),
        None if cfg!(target_os = "macos") => {
            std::env::temp_dir().join("mds-vkd3d/macos/lib/libvkd3d-shader.1.dylib")
        }
        None => {
            let arch = if cfg!(target_arch = "x86_64") {
                "amd64"
            } else {
                "arm64"
            };
            std::env::temp_dir().join(format!("mds-vkd3d/linux-{arch}/lib/libvkd3d-shader.so.1"))
        }
    }
}

pub fn vkd3d_at(lib: &Path) -> Option<Vkd3d> {
    Vkd3d::open(lib)
        .map_err(|e| eprintln!("SKIP: vkd3d-shader not loaded: {e} (a skip is not a pass)"))
        .ok()
}

pub fn vkd3d() -> Option<Vkd3d> {
    vkd3d_at(&vkd3d_path())
}

/// The ray-mmd checkout of `tools/fixtures/fetch_corpus.sh`: `$MDS_CORPUS/ray-mmd`, else the
/// temp directory's `mds-corpus/ray-mmd`.
pub fn corpus_path() -> PathBuf {
    match std::env::var_os("MDS_CORPUS") {
        Some(p) => PathBuf::from(p),
        None => std::env::temp_dir().join("mds-corpus"),
    }
    .join("ray-mmd")
}

pub fn corpus_at(dir: &Path) -> Option<PathBuf> {
    if dir.is_dir() {
        Some(dir.to_path_buf())
    } else {
        eprintln!(
            "SKIP: no corpus at {} (a skip is not a pass)",
            dir.display()
        );
        None
    }
}

pub fn corpus() -> Option<PathBuf> {
    corpus_at(&corpus_path())
}
