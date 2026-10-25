//! `--frame-dump <pmm> <out-dir> <frame>...`: the Rust twin of the C++ `--mds-frame-dump`
//! (`src/tools/trace_mode.cpp`, `RunFrameDump`; arguments as `ParseTraceArgs` in
//! `src/tools/trace_args.hpp`). Steps the frames as the window does and writes
//! `<out-dir>/<pmm stem>-<frame>.png` at the C++ output size, 640x360, with the 8x sample pattern.

use crate::viewer::Viewer;
use mds_render::{encode_png, Gpu, SAMPLES_8X};
use std::path::{Path, PathBuf};

pub const WIDTH: u32 = 640;
pub const HEIGHT: u32 = 360;
/// `kMaxTraceFrames`.
const MAX_FRAMES: u32 = 100_000;

pub struct Request {
    pub pmm: PathBuf,
    pub out: PathBuf,
    /// Strictly ascending.
    pub frames: Vec<u32>,
}

/// `ParseDecimal`: up to six decimal digits.
fn decimal(text: &str) -> Option<u32> {
    if text.is_empty() || text.len() > 6 || !text.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    text.parse().ok()
}

/// The arguments after `--frame-dump`.
pub fn parse(args: &[String]) -> Result<Request, String> {
    let usage = "usage: mds-app --frame-dump <pmm> <out-dir> <frame>...";
    let [pmm, out, frames @ ..] = args else {
        return Err(usage.into());
    };
    if frames.is_empty() || !pmm.to_ascii_lowercase().ends_with(".pmm") {
        return Err(usage.into());
    }
    let frames = frames
        .iter()
        .map(|f| decimal(f).filter(|&f| f < MAX_FRAMES))
        .collect::<Option<Vec<_>>>()
        .ok_or("frames are decimal numbers below 100000")?;
    if frames.windows(2).any(|w| w[0] >= w[1]) {
        return Err("frames must be strictly ascending".into());
    }
    Ok(Request {
        pmm: pmm.into(),
        out: out.into(),
        frames,
    })
}

pub fn run(gpu: &Gpu, request: &Request) -> Result<(), String> {
    let mut viewer = Viewer::open(&request.pmm)?;
    let stem = request
        .pmm
        .file_stem()
        .and_then(|s| s.to_str())
        .ok_or("PMM file name")?;
    std::fs::create_dir_all(&request.out).map_err(|e| format!("{}: {e}", request.out.display()))?;
    for &frame in &request.frames {
        viewer.seek(frame)?;
        let camera = viewer.track_camera()?;
        let px = viewer.render(gpu, WIDTH, HEIGHT, &camera, &SAMPLES_8X)?;
        let path = Path::new(&request.out).join(format!("{stem}-{frame}.png"));
        std::fs::write(&path, encode_png(WIDTH, HEIGHT, &px))
            .map_err(|e| format!("{}: {e}", path.display()))?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::parse;

    fn args(a: &[&str]) -> Vec<String> {
        a.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn arguments_follow_the_cpp_parser() {
        let r = parse(&args(&["a.PMM", "out", "0", "150", "599"])).unwrap();
        assert_eq!(r.frames, [0, 150, 599]);
        for bad in [
            &["a.pmm", "out"][..],
            &["a.pmx", "out", "0"],
            &["a.pmm", "out", "5", "5"],
            &["a.pmm", "out", "100000"],
            &["a.pmm", "out", "-1"],
            &["a.pmm", "out", "1234567"],
        ] {
            assert!(parse(&args(bad)).is_err(), "{bad:?}");
        }
    }
}
