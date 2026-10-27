//! The per-pixel rule the golden-image tests share, and their helpers.

#![allow(dead_code)]

use mds_render::Gpu;
use std::path::{Path, PathBuf};

/// What the whole picture of every frame must reach. A pixel is close when no channel is further
/// than `tolerance` from the golden image.
pub struct Limits {
    pub tolerance: u8,
    pub min_close: f64,
    pub max_diff: u8,
}

/// 4 levels, 99.99% of the pixels (at most 22 may be further), none beyond 48. Measured on the
/// swing600 golden scene (`golden.rs`, before the golden2 edge rule): frame 0 differs by at most 1 level everywhere; frames 150, 300 and 599 have 1, 5 and
/// 10 pixels beyond 4 and a largest difference of 12, 46 and 25. Those pixels are hairline
/// slivers of the swinging strand of slot 3, where one of the
/// eight samples falls on the other side of the edge: a single sample of a dark sliver on white is
/// worth up to about 45 levels.
pub const LIMITS: Limits = Limits {
    tolerance: 4,
    min_close: 0.9999,
    max_diff: 48,
};

pub fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

/// Width, height and RGBA8 pixels of an 8-bit RGBA PNG.
pub fn read_png(path: &Path) -> (usize, usize, Vec<u8>) {
    let data = std::fs::read(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let mut reader = png::Decoder::new(std::io::Cursor::new(data))
        .read_info()
        .unwrap();
    let mut buf = vec![0; reader.output_buffer_size().unwrap()];
    let info = reader.next_frame(&mut buf).unwrap();
    assert_eq!(info.color_type, png::ColorType::Rgba);
    (info.width as usize, info.height as usize, buf)
}

#[derive(Debug)]
pub struct Score {
    pub pixels: usize,
    /// Fraction of the pixels within the tolerance.
    pub close: f64,
    pub max: u8,
    pub mean: f64,
}

impl Score {
    pub fn passes(&self) -> bool {
        self.close >= LIMITS.min_close && self.max <= LIMITS.max_diff
    }
}

pub fn pixel_diff(a: &[u8], b: &[u8], i: usize) -> u8 {
    (0..3)
        .map(|c| a[i * 4 + c].abs_diff(b[i * 4 + c]))
        .max()
        .unwrap()
}

pub fn gpu_or_skip() -> Option<Gpu> {
    let gpu = Gpu::new().expect("device");
    if let Some(ref gpu) = gpu {
        eprintln!("CENTER_ADAPTER {}", gpu.adapter);
    }
    if gpu.is_none() {
        eprintln!("SKIP: no wgpu adapter on this host (not a pass)");
    }
    gpu
}
