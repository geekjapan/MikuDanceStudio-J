//! Where the background picture of a PMM goes.
//!
//! The C++ app places the picture quad in the pixels of its main window's viewport, from the PMM
//! render width, at PMM load (golden2 README, "Notes for render2"); its frame dump then draws that
//! quad into the 640x360 output unchanged, so the golden image depends on the host's window.
//! [`PictureQuad::in_viewport`] is that placement, checked against the `picture` line of
//! `tests/fixtures/rust/golden2/background.edge.txt`; [`PictureQuad::to_output`] maps it from the
//! viewport onto an output picture of any size, which is where `mds-render` draws it.

/// A picture quad: left, top, right, bottom in pixels.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PictureQuad {
    pub rect: [f32; 4],
}

impl PictureQuad {
    /// The quad of a `width` x `height` picture at PMM `scale` and `offset` (pixels), in a
    /// viewport `[left, top, right, bottom]` that shows a render `render_width` pixels wide. The
    /// width keeps the picture's pixels at `scale` render pixels each and the height keeps its
    /// aspect; the quad starts one pixel above and left of the viewport, as the C++ quad does.
    pub fn in_viewport(
        width: u32,
        height: u32,
        scale: f32,
        offset: [i32; 2],
        viewport: [f32; 4],
        render_width: u32,
    ) -> PictureQuad {
        let [left, top, right, _] = viewport;
        let w = width as f32 * scale * (right - left) / render_width as f32;
        let h = w * height as f32 / width as f32;
        let (x, y) = (left + offset[0] as f32, top + offset[1] as f32);
        PictureQuad {
            rect: [x - 1.0, y - 1.0, x + w, y + h],
        }
    }

    /// The quad moved from `viewport` onto an output of `width` x `height` pixels that shows the
    /// same view.
    pub fn to_output(&self, viewport: [f32; 4], width: u32, height: u32) -> PictureQuad {
        let [l, t, r, b] = viewport;
        let sx = width as f32 / (r - l);
        let sy = height as f32 / (b - t);
        let [x0, y0, x1, y1] = self.rect;
        PictureQuad {
            rect: [(x0 - l) * sx, (y0 - t) * sy, (x1 - l) * sx, (y1 - t) * sy],
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The probe line: offset x, y, scale, picture width, height, an unused value, the viewport
    /// (left, top, right, bottom), the output size, the quad, and six rhw values.
    #[test]
    fn placement_matches_the_probe() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../tests/fixtures/rust/golden2/background.edge.txt");
        let text = std::fs::read_to_string(path).unwrap();
        let line = text
            .lines()
            .find(|l| l.split(' ').nth(1) == Some("picture"))
            .expect("a picture line");
        let v: Vec<f32> = line
            .split(' ')
            .skip(2)
            .map(|w| w.parse().unwrap())
            .collect();
        let viewport = [v[6], v[7], v[8], v[9]];
        // The PMM of the scene stores a 1280-wide render.
        let quad = PictureQuad::in_viewport(
            v[3] as u32,
            v[4] as u32,
            v[2],
            [v[0] as i32, v[1] as i32],
            viewport,
            1280,
        );
        assert_eq!(quad.rect, [v[12], v[13], v[14], v[15]]);
        let out = quad.to_output(viewport, v[10] as u32, v[11] as u32);
        let want = [-0.28, -0.28, 80.0, 45.046];
        for (got, want) in out.rect.iter().zip(want) {
            assert!((got - want).abs() < 0.01, "{:?}", out.rect);
        }
    }
}
