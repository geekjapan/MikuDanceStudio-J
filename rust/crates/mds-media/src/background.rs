//! The background menu state: the movie and picture slots with the
//! placement `MediaAspect` computes, as `LoadAviFile` and
//! `LoadBackgroundPicture` fill them.
//!
//! Ports `src/media/media_load.cpp` (`MediaAspect`, `AviFailTail`, the
//! success and failure tails of both loaders).

use crate::movie::{Movie, MovieError};
use crate::picture::{self, Picture, PictureError};
use std::fs::File;
use std::io::BufReader;
use std::path::Path;

/// `kOverlaySpan`: the .rdata float 1.2f of `MediaAspect`.
pub const OVERLAY_SPAN: f32 = 1.2;
/// `kOverlayHalf`: the .rdata float 0.5f of `MediaAspect`.
pub const OVERLAY_HALF: f32 = 0.5;
/// Characters of the media path slots (`CopyPathW`: `wcscpy_s(.., 0x100, ..)`).
pub const PATH_SLOT_CHARS: usize = 0x100;
/// Characters of the UserFile directory slots (`CopyDirPathW`: 0x3E8).
pub const DIR_SLOT_CHARS: usize = 0x3E8;

/// The viewport fields `MediaAspect` reads: `state.hideLeft` (the right edge
/// in fact), `hideRight` (the left edge), `hideTop`, `hideBottom`, and the
/// renderer's `viewScale`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Viewport {
    pub hide_left: i32,
    pub hide_right: i32,
    pub hide_top: i32,
    pub hide_bottom: i32,
    pub view_scale: f32,
}

/// What the loaders store next to the media: `AviScale`/`PictureScale`,
/// `AviOffsetX`/`PictureOffsetX` (0 on load) and `AviOffsetY`/`PictureOffsetY`.
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct Placement {
    pub offset_x: i32,
    pub offset_y: i32,
    pub scale: f32,
}

/// x86 `cvttss2si`: truncation, with 0x80000000 for NaN and out of range
/// (NaN fails `contains`).
fn cvttss2si(v: f32) -> i32 {
    if !(-2_147_483_648.0..2_147_483_648.0).contains(&v) {
        i32::MIN
    } else {
        v as i32
    }
}

/// `MediaAspect` (media_load.cpp): the zoom that fits the media to the
/// viewport width and the Y offset that centres it, returned as
/// `(scale, offset_y)`. All steps are single-precision in the written order.
pub fn media_aspect(vp: &Viewport, width: i32, height: i32) -> (f32, i32) {
    let w = vp.hide_left.wrapping_sub(vp.hide_right); // 0x4336B7
    let h2 = vp.hide_bottom.wrapping_sub(vp.hide_top) / 2; // 0x4336E9
    let ratio = vp.view_scale;
    let span_w = w as f32 / ratio;
    let zoom = (span_w * OVERLAY_SPAN) / width as f32;
    let drawn_h = (height as f32 * zoom * ratio) / OVERLAY_SPAN;
    (zoom, cvttss2si(h2 as f32 - drawn_h * OVERLAY_HALF))
}

fn placement(vp: &Viewport, width: i32, height: i32) -> Placement {
    let (scale, offset_y) = media_aspect(vp, width, height);
    Placement {
        offset_x: 0,
        offset_y,
        scale,
    }
}

/// The AVI background: `AviBackgroundPath`, `AviBackgroundEnabled`, the open
/// movie and the placement.
#[derive(Default)]
pub struct MovieBackground {
    pub path: String,
    pub enabled: bool,
    pub movie: Option<Movie<BufReader<File>>>,
    pub placement: Placement,
}

impl MovieBackground {
    /// `LoadAviFile` with the path already resolved under the UserFile tree.
    /// The previous movie is dropped first. On success the slot keeps the
    /// resolved path and is enabled. On any failure the caller shows
    /// `err.message(..)` and the slot is cleared (`AviFailTail`): empty path,
    /// disabled, no movie.
    pub fn load(&mut self, resolved: &Path, vp: &Viewport) -> Result<(), MovieError> {
        self.movie = None;
        match Movie::open_path(resolved) {
            Ok(movie) => {
                let i = movie.info();
                self.placement = placement(vp, i.width, i.height);
                self.movie = Some(movie);
                self.path = resolved.to_string_lossy().into_owned();
                self.enabled = true;
                Ok(())
            }
            Err(e) => {
                self.fail();
                Err(e)
            }
        }
    }

    /// The runtime failure tail of `AviBgOverlayRefresh` (frame missing):
    /// handles released, flag off, path cleared. The same state as after a
    /// failed load.
    pub fn fail(&mut self) {
        self.movie = None;
        self.enabled = false;
        self.path.clear();
    }
}

/// The picture background: `PictureBackgroundPath`,
/// `PictureBackgroundEnabled`, the decoded image (the C++ keeps a D3D
/// texture) and the placement.
#[derive(Default)]
pub struct PictureBackground {
    pub path: String,
    pub enabled: bool,
    pub picture: Option<Picture>,
    pub placement: Placement,
}

impl PictureBackground {
    /// `LoadBackgroundPicture` with the path already resolved. A missing file
    /// clears the path and changes nothing else. After that probe the old
    /// picture is dropped, and a decode failure clears the path while the
    /// enabled flag stays as it was, as in the C++ (0x43394A).
    pub fn load(&mut self, resolved: &Path, vp: &Viewport) -> Result<(), PictureError> {
        let Ok(file) = std::fs::read(resolved) else {
            self.path.clear();
            return Err(PictureError::Open);
        };
        self.picture = None;
        match picture::decode(&file) {
            Ok(pic) => {
                self.placement = placement(vp, pic.width as i32, pic.height as i32);
                self.picture = Some(pic);
                self.path = resolved.to_string_lossy().into_owned();
                self.enabled = true;
                Ok(())
            }
            Err(e) => {
                self.path.clear();
                Err(e)
            }
        }
    }
}
