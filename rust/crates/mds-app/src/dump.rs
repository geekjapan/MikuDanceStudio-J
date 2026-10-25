//! `--frame-dump <pmm> <out-dir> <frame>...`: the Rust twin of the C++ `--mds-frame-dump`
//! (`src/tools/trace_mode.cpp`, `RunFrameDump`; arguments as `ParseTraceArgs` in
//! `src/tools/trace_args.hpp`). Loads the PMM as a document, moves the physics the way the C++
//! `RunFrameDump` moves it (the PMM load, then one frame-step pass, `PlaybackCatchup` +
//! `PhysicsFrame` at 30 fps, per frame: [`PhysicsScene::new`] and [`PhysicsScene::step`]), and
//! writes `<out-dir>/<pmm stem>-<frame>.png` at the C++ output size, 640x360, with the 8x sample
//! pattern: the models with their textures, the accessories, the self-shadow and ground shadow
//! of the PMM and its background picture ([`scene::with_stage`]).
//!
//! The C++ places the background picture in its main window's viewport and draws that quad into
//! the output unchanged (README of `tests/fixtures/rust/golden2`), so its picture depends on the
//! host's window. With no window, the dump places it in the output; `MDS_FRAME_DUMP_PICTURE_VIEWPORT
//! =<left>,<top>,<right>,<bottom>` names the viewport instead ([`Request::picture_viewport`]).

use crate::file;
use crate::scene::{self, Assets, Shot};
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
    /// Where the background picture is placed (see the module doc); `None` is the output.
    pub picture_viewport: Option<[f32; 4]>,
}

/// `<left>,<top>,<right>,<bottom>`.
pub fn parse_viewport(text: &str) -> Result<[f32; 4], String> {
    let v: Vec<f32> = text
        .split(',')
        .map(|n| n.trim().parse::<f32>())
        .collect::<Result<_, _>>()
        .map_err(|e| format!("picture viewport {text:?}: {e}"))?;
    v.try_into()
        .map_err(|_| format!("picture viewport {text:?}: four numbers"))
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
        picture_viewport: None,
    })
}

pub fn run(gpu: &Gpu, request: &Request) -> Result<(), String> {
    let doc = file::read(&request.pmm)?;
    let dir = request.pmm.parent().unwrap_or(Path::new("."));
    let assets = Assets::load(&doc, dir)?;
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
        let shot = Shot {
            physics: &physics,
            frame,
            camera: &camera,
            size: [WIDTH, HEIGHT],
            samples: &SAMPLES_8X,
            picture_viewport: request.picture_viewport,
        };
        let px = scene::with_stage(&doc, &assets, &shot, |f, s| {
            mds_render::render_frame_with(gpu, f, s)
        })??;
        let path = Path::new(&request.out).join(format!("{stem}-{frame}.png"));
        std::fs::write(&path, encode_png(WIDTH, HEIGHT, &px))
            .map_err(|e| format!("{}: {e}", path.display()))?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{parse, parse_viewport};

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
        assert_eq!(
            parse_viewport("259, 94,2544,1378"),
            Ok([259.0, 94.0, 2544.0, 1378.0])
        );
        assert!(parse_viewport("1,2,3").is_err() && parse_viewport("1,2,3,x").is_err());
    }
}
