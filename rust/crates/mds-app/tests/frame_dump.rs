//! `mds-app --frame-dump tests/fixtures/rust/swing600-golden.pmm <dir> 0 150 300 599` against the
//! golden images of the C++ app, with the per-pixel rule of `mds-render/tests/golden.rs`
//! ([`LIMITS`], [`overlay`] and [`score`] are copied from there unchanged, because a test file of
//! another crate cannot be imported).
//!
//! `MDS_APP_DUMP_DIR=<dir>` keeps the dumped PNGs there instead of a temporary folder.

use mds_render::Gpu;
use std::path::{Path, PathBuf};
use std::process::Command;

const W: usize = 640;
const H: usize = 360;
const FRAMES: [u32; 4] = [0, 150, 300, 599];

struct Limits {
    tolerance: u8,
    min_close: f64,
    max_diff: u8,
}

const LIMITS: Limits = Limits {
    tolerance: 4,
    min_close: 0.9999,
    max_diff: 48,
};

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

fn read_png(path: &Path) -> Vec<u8> {
    let data = std::fs::read(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let mut reader = png::Decoder::new(std::io::Cursor::new(data))
        .read_info()
        .unwrap();
    let mut buf = vec![0; reader.output_buffer_size().unwrap()];
    let info = reader.next_frame(&mut buf).unwrap();
    assert_eq!((info.width as usize, info.height as usize), (W, H));
    assert_eq!(info.color_type, png::ColorType::Rgba);
    buf
}

/// The ground line and the bone axis the C++ app draws besides the models.
fn overlay(x: usize, y: usize) -> bool {
    (320..=321).contains(&y) || (x == 320 && y <= 273)
}

#[derive(Debug)]
struct Score {
    pixels: usize,
    close: f64,
    max: u8,
    mean: f64,
}

fn score(px: &[u8], gold: &[u8]) -> Score {
    let (mut n, mut close, mut max, mut sum) = (0, 0, 0u8, 0u64);
    for i in (0..W * H).filter(|&i| !overlay(i % W, i / W)) {
        let d = (0..3)
            .map(|c| px[i * 4 + c].abs_diff(gold[i * 4 + c]))
            .max()
            .unwrap();
        n += 1;
        close += usize::from(d <= LIMITS.tolerance);
        max = max.max(d);
        sum += u64::from(d);
    }
    Score {
        pixels: n,
        close: close as f64 / n as f64,
        max,
        mean: sum as f64 / n as f64,
    }
}

#[test]
fn frame_dump_meets_the_golden_rule() {
    if Gpu::new().expect("device").is_none() {
        eprintln!("SKIP: no wgpu adapter on this host (not a pass)");
        return;
    }
    let out = std::env::var_os("MDS_APP_DUMP_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            std::env::temp_dir().join(format!("mds-app-dump-{}", std::process::id()))
        });
    let status = Command::new(env!("CARGO_BIN_EXE_mds-app"))
        .arg("--frame-dump")
        .arg(fixtures().join("swing600-golden.pmm"))
        .arg(&out)
        .args(FRAMES.map(|f| f.to_string()))
        .status()
        .unwrap();
    assert!(status.success(), "mds-app --frame-dump: {status}");
    for frame in FRAMES {
        let px = read_png(&out.join(format!("swing600-golden-{frame}.png")));
        let gold = read_png(&fixtures().join(format!("golden/swing600-golden-{frame}.png")));
        let s = score(&px, &gold);
        eprintln!(
            "frame {frame}: {} px, within {} {:.5}, max {}, mean {:.4}",
            s.pixels, LIMITS.tolerance, s.close, s.max, s.mean
        );
        assert!(s.close >= LIMITS.min_close, "frame {frame}: {s:?}");
        assert!(s.max <= LIMITS.max_diff, "frame {frame}: {s:?}");
    }
    if std::env::var_os("MDS_APP_DUMP_DIR").is_none() {
        std::fs::remove_dir_all(&out).unwrap();
    }
}
