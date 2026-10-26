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
//!
//! A PMM whose objects have effects ([`Mme::autoload`]: the `.emm` beside it, or an effect file
//! beside an object) dumps through MME instead, as the C++ `--mds-mme-dump` does (README of
//! `tests/fixtures/rust/mmegold`): every frame from 0 is drawn, frame 0 once more before them
//! (the draw while the application loads, which makes `ELAPSEDTIME` 0 at frame 0 and 1/30 after
//! it), with the camera and light tracks in playback mode and `TIME` the frame's time.

use crate::file;
use crate::mme::{Mme, View};
use crate::scene::{self, Assets, Shot};
use mds_physics::PhysicsScene;
use mds_render::Camera;
use mds_render::{encode_png, Gpu, SAMPLES_8X};
use mds_scene::track::{evaluate_camera, evaluate_light, CameraMode, LightMode};
use std::path::{Path, PathBuf};

pub const WIDTH: u32 = 640;
pub const HEIGHT: u32 = 360;
/// `kMaxTraceFrames`.
const MAX_FRAMES: u32 = 100_000;
/// The back buffer of the C++ MME dump that `ViewportRatio` targets are sized against: the
/// device of the oracle host's window (README of `tests/fixtures/rust/mmegold`). The picture is
/// its 640x360 corner.
pub const MME_BACKBUFFER: (u32, u32) = (3072, 1728);

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
    let mut doc = file::read(&request.pmm)?;
    let [l, t, r, b] = request
        .picture_viewport
        .unwrap_or([0.0, 0.0, WIDTH as f32, HEIGHT as f32]);
    doc.edit.viewport = Some(crate::viewport::media_viewport(
        [l, t, r, b].map(|v| v as i32),
    ));
    let dir = request.pmm.parent().unwrap_or(Path::new("."));
    let assets = Assets::load(&doc, dir)?;
    let mut physics = PhysicsScene::new(&doc.pmm, |p| scene::read_model(dir, p))?;
    let stem = request
        .pmm
        .file_stem()
        .and_then(|s| s.to_str())
        .ok_or("PMM file name")?;
    std::fs::create_dir_all(&request.out).map_err(|e| format!("{}: {e}", request.out.display()))?;
    let write = |frame: u32, px: &[u8]| {
        let path = Path::new(&request.out).join(format!("{stem}-{frame}.png"));
        std::fs::write(&path, encode_png(WIDTH, HEIGHT, px))
            .map_err(|e| format!("{}: {e}", path.display()))
    };
    let mut mme = Mme::autoload(&doc, Some(&request.pmm));
    if mme.active() {
        mme.backbuffer = Some(MME_BACKBUFFER);
        return run_mme(&doc, &mme, &mut physics, &request.frames, write);
    }
    let mut at = 0;
    for &frame in &request.frames {
        while at < frame {
            physics
                .step()
                .map_err(|e| format!("frame {}: {e}", at + 1))?;
            at += 1;
        }
        let camera = scene::track_camera(&doc, frame)?.into();
        let shot = Shot {
            physics: &physics,
            frame,
            camera: &camera,
            view_offset: [0.0; 2],
            size: [WIDTH, HEIGHT],
            samples: &SAMPLES_8X,
            picture_viewport: request.picture_viewport,
        };
        let px = scene::with_stage(&doc, &assets, &shot, |f, s| {
            mds_render::render_frame_with(gpu, f, s)
        })??;
        write(frame, &px)?;
    }
    Ok(())
}

/// The MME dump (see the module doc).
fn run_mme(
    doc: &mds_doc::Document,
    mme: &Mme,
    physics: &mut PhysicsScene,
    frames: &[u32],
    write: impl Fn(u32, &[u8]) -> Result<(), String>,
) -> Result<(), String> {
    let last = *frames.last().ok_or("no frames")?;
    let draw = |physics: &PhysicsScene, frame: u32, elapsed: f32| {
        let pmm = &doc.pmm;
        let at = f64::from(frame);
        let c = evaluate_camera(&pmm.camera, at, CameraMode::Playback)
            .ok_or_else(|| format!("camera track at frame {frame}"))?;
        let camera = mds_render::CameraFrame::from(Camera {
            target: c.position,
            rotation: c.rotation,
            distance: c.distance,
            fov_deg: c.fov,
            orthographic: c.perspective == 1,
        });
        let light = evaluate_light(&pmm.light, at, LightMode::Playback)
            .ok_or_else(|| format!("light track at frame {frame}"))?;
        let view = View {
            camera: &camera,
            view_offset: [0.0; 2],
            shadow_map: Default::default(),
            shadow_map_display: false,
            light,
            frame,
            elapsed,
            size: [WIDTH, HEIGHT],
        };
        mme.render(doc, physics, &view)
    };
    draw(physics, 0, 0.0)?;
    for frame in 0..=last {
        if frame > 0 {
            physics.step().map_err(|e| format!("frame {frame}: {e}"))?;
        }
        let px = draw(physics, frame, if frame == 0 { 0.0 } else { 1.0 / 30.0 })?;
        if frames.contains(&frame) {
            write(frame, &px)?;
        }
    }
    for line in mme.log.borrow().iter() {
        eprintln!("mme: {line}");
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
