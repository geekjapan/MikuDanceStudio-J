//! Texture files: decoding, and which files a material names.
//!
//! PMX materials name their texture, sphere map and toon by index into the model's texture list,
//! or a shared toon `toon01.bmp` to `toon10.bmp` (PMX 2.0 specification). A PMD material names its
//! texture and sphere map in one field, `texture*sphere`, where the sphere ends in `.sph`
//! (multiply) or `.spa` (add), and its toon by index into the toon names after the bone frames
//! (`toon0.bmp`, the built-in toon, for 255). A name that does not load leaves the slot at its
//! default: white for the texture, none for the sphere, the built-in toon.

/// Decoded RGBA8 pixels, top row first.
#[derive(Clone, Debug, PartialEq)]
pub struct Image {
    pub width: u32,
    pub height: u32,
    pub rgba: Vec<u8>,
}

impl Image {
    pub fn new(width: u32, height: u32, rgba: Vec<u8>) -> Image {
        Image {
            width,
            height,
            rgba,
        }
    }

    /// The image and its mip levels down to 1 x 1, each a 2 x 2 box average of the last (D3DX
    /// makes a full chain for a texture it loads).
    pub(crate) fn mip_chain(&self) -> Vec<Image> {
        let mut chain = vec![self.clone()];
        while let Some(l) = chain.last().filter(|l| l.width > 1 || l.height > 1) {
            let (w, h) = ((l.width / 2).max(1), (l.height / 2).max(1));
            let px = |x: u32, y: u32, c: usize| {
                let (x, y) = (x.min(l.width - 1), y.min(l.height - 1));
                u32::from(l.rgba[((y * l.width + x) * 4) as usize + c])
            };
            let mut rgba = Vec::with_capacity((w * h * 4) as usize);
            for y in 0..h {
                for x in 0..w {
                    for c in 0..4 {
                        let sum = px(2 * x, 2 * y, c)
                            + px(2 * x + 1, 2 * y, c)
                            + px(2 * x, 2 * y + 1, c)
                            + px(2 * x + 1, 2 * y + 1, c);
                        rgba.push(((sum + 2) / 4) as u8);
                    }
                }
            }
            chain.push(Image::new(w, h, rgba));
        }
        chain
    }

    /// The image stretched to `width` x `height`, each output texel a linear blend of the two
    /// nearest source texels along each axis (texel centers aligned, the edges clamped).
    pub(crate) fn resized(&self, width: u32, height: u32) -> Image {
        // Per output index: the two source indices and the weight of the second.
        let taps = |n: u32, m: u32| -> Vec<(usize, usize, f32)> {
            (0..n)
                .map(|i| {
                    let x =
                        ((i as f32 + 0.5) * m as f32 / n as f32 - 0.5).clamp(0.0, (m - 1) as f32);
                    let j = x.floor() as usize;
                    (j, (j + 1).min(m as usize - 1), x - j as f32)
                })
                .collect()
        };
        let (xs, ys) = (taps(width, self.width), taps(height, self.height));
        let px = |x: usize, y: usize, c: usize| {
            f32::from(self.rgba[(y * self.width as usize + x) * 4 + c])
        };
        let mut rgba = Vec::with_capacity((width * height * 4) as usize);
        for &(y0, y1, fy) in &ys {
            for &(x0, x1, fx) in &xs {
                for c in 0..4 {
                    let top = px(x0, y0, c) * (1.0 - fx) + px(x1, y0, c) * fx;
                    let bottom = px(x0, y1, c) * (1.0 - fx) + px(x1, y1, c) * fx;
                    rgba.push((top * (1.0 - fy) + bottom * fy).round() as u8);
                }
            }
        }
        Image::new(width, height, rgba)
    }

    /// BMP, PNG, TGA, JPEG and DDS (DXT1, 3 and 5), as far as the `image` crate decodes them.
    pub fn decode(data: &[u8]) -> Result<Image, String> {
        let img = image::load_from_memory(data).map_err(|e| e.to_string())?;
        let rgba = img.to_rgba8();
        Ok(Image {
            width: rgba.width(),
            height: rgba.height(),
            rgba: rgba.into_raw(),
        })
    }
}

/// How a sphere map combines with the color.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum SphereMode {
    Multiply = 1,
    Add = 2,
}

/// The files one material names; `None` where it names none.
#[derive(Clone, Debug, Default, PartialEq)]
pub(crate) struct Names {
    pub texture: Option<String>,
    pub sphere: Option<(String, SphereMode)>,
    pub toon: Option<String>,
}

fn nonempty(s: &str) -> Option<String> {
    let s = s.trim_end_matches('\0');
    (!s.is_empty()).then(|| s.to_string())
}

/// The shared toon file of PMX toon number `n` (0 is `toon01.bmp`).
fn shared_toon(n: i32) -> Option<String> {
    (0..10)
        .contains(&n)
        .then(|| format!("toon{:02}.bmp", n + 1))
}

pub(crate) fn pmx_names(pmx: &mds_formats::pmx::Pmx) -> Vec<Names> {
    let tex = |i: i32| {
        usize::try_from(i)
            .ok()
            .and_then(|i| pmx.textures.get(i))
            .and_then(|t| nonempty(&t.text))
    };
    pmx.materials
        .iter()
        .map(|m| Names {
            texture: tex(m.texture),
            sphere: match m.sphere_mode {
                1 => tex(m.sphere).map(|s| (s, SphereMode::Multiply)),
                2 => tex(m.sphere).map(|s| (s, SphereMode::Add)),
                _ => None,
            },
            toon: if m.shared_toon != 0 {
                shared_toon(m.toon)
            } else {
                tex(m.toon)
            },
        })
        .collect()
}

pub(crate) fn pmd_names(pmd: &mds_formats::pmd::Pmd) -> Vec<Names> {
    let toons = pmd.extension.as_ref().map(|e| &e.toon_textures);
    pmd.materials
        .iter()
        .map(|m| {
            let field = &m.texture.text;
            let mut names = Names::default();
            for part in field.split('*') {
                let lower = part.to_ascii_lowercase();
                if lower.ends_with(".sph") {
                    names.sphere = nonempty(part).map(|s| (s, SphereMode::Multiply));
                } else if lower.ends_with(".spa") {
                    names.sphere = nonempty(part).map(|s| (s, SphereMode::Add));
                } else if names.texture.is_none() {
                    names.texture = nonempty(part);
                }
            }
            names.toon = match (m.toon, toons) {
                (255, _) => None,
                (i, Some(t)) => t.get(usize::from(i)).and_then(|n| nonempty(&n.text)),
                (i, None) => shared_toon(i32::from(i)),
            };
            names
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decodes_the_skin_texture() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../tests/fixtures/rust/golden2/skin_tex.bmp");
        let img = Image::decode(&std::fs::read(path).unwrap()).unwrap();
        assert_eq!((img.width, img.height), (16, 16));
        // Top-left quadrant (224, 64, 64), bottom-right (240, 208, 64): gen_golden2.py.
        assert_eq!(img.rgba[..4], [224, 64, 64, 255]);
        assert_eq!(img.rgba[img.rgba.len() - 4..], [240, 208, 64, 255]);
    }
}
