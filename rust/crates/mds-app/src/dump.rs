//! `--frame-dump <pmm> <out-dir> <frame>...`: the Rust twin of the C++ `--mds-frame-dump`
//! (`src/tools/trace_mode.cpp`, `RunFrameDump`; arguments as `ParseTraceArgs` in
//! `src/tools/trace_args.hpp`). Loads the PMM as a document, moves the physics the way the C++
//! `RunFrameDump` moves it (the PMM load, then one frame-step pass, `PlaybackCatchup` +
//! `PhysicsFrame` at 30 fps, per frame: [`PhysicsScene::new`] and [`PhysicsScene::step`]), and
//! writes `<out-dir>/<pmm stem>-<frame>.png` at the C++ output size, 640x360, with the 8x sample
//! pattern.

use crate::{file, scene};
use mds_physics::PhysicsScene;
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
    let doc = file::read(&request.pmm)?;
    let dir = request.pmm.parent().unwrap_or(Path::new("."));
    let meshes = scene::meshes(&doc)?;
    let mut physics = PhysicsScene::new(&doc.pmm, |p| scene::read_model(dir, p))?;
    let stem = request
        .pmm
        .file_stem()
        .and_then(|s| s.to_str())
        .ok_or("PMM file name")?;
    std::fs::create_dir_all(&request.out).map_err(|e| format!("{}: {e}", request.out.display()))?;
    let mut at = 0;
    for &frame in &request.frames {
        while at < frame {
            physics
                .step()
                .map_err(|e| format!("frame {}: {e}", at + 1))?;
            at += 1;
        }
        let camera = scene::track_camera(&doc, frame)?;
        let size = [WIDTH, HEIGHT];
        let px = scene::with_frame(
            &doc,
            &meshes,
            &physics,
            frame,
            &camera,
            size,
            &SAMPLES_8X,
            |f| mds_render::render_frame(gpu, f),
        )??;
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
