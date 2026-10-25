//! The wgpu objects of an effect's resources: what `SasEnsureResourceTexture`
//! (`sas_interpreter.cpp`) creates, with the sizes, mip counts, and D3D formats that `mds-mme`
//! resolved, and the texels of texture files.
//!
//! Formats map to the nearest wgpu format ([`wgpu_format`]); the D3D format is kept beside the
//! texture. Luminance formats (`L8`, `A8L8`) sample as red (and green) where D3D replicates
//! luminance, and `A8` samples as red where D3D gives alpha. Texture files: PNG, BMP (24 and
//! 32 bit), TGA (uncompressed), and DDS (uncompressed, DXT1 to DXT5 when the adapter has BC,
//! and float formats) are decoded; JPEG and Radiance HDR are created at their size and format
//! but stay black. Only level 0 is filled for compressed and float files; 8-bit RGBA files get a
//! box-filtered chain.

use mds_mme::sas::{fmt, Resource, TexKind, SEM_OFFSCREEN, SEM_RENDER_COLOR, SEM_RENDER_DEPTH};

use crate::gpu::Gpu;

const fn fourcc(s: &[u8; 4]) -> u32 {
    u32::from_le_bytes(*s)
}

/// The wgpu format a D3D format is stored in, or `None` when there is none.
pub fn wgpu_format(d3d: u32, features: wgpu::Features) -> Option<wgpu::TextureFormat> {
    use wgpu::TextureFormat as T;
    let bc = features.contains(wgpu::Features::TEXTURE_COMPRESSION_BC);
    let norm16 = features.contains(wgpu::Features::TEXTURE_FORMAT_16BIT_NORM);
    Some(match d3d {
        fmt::A8R8G8B8 | fmt::X8R8G8B8 | 20 => T::Bgra8Unorm,
        32 | 33 => T::Rgba8Unorm,   // A8B8G8R8, X8B8G8R8
        31 | 35 => T::Rgb10a2Unorm, // A2B10G10R10, A2R10G10B10
        28 | fmt::L8 => T::R8Unorm, // A8, L8
        fmt::A8L8 => T::Rg8Unorm,
        34 if norm16 => T::Rg16Unorm,   // G16R16
        36 if norm16 => T::Rgba16Unorm, // A16B16G16R16
        81 if norm16 => T::R16Unorm,    // L16
        111 => T::R16Float,
        112 => T::Rg16Float,
        113 => T::Rgba16Float,
        114 => T::R32Float,
        115 => T::Rg32Float,
        fmt::A32B32G32R32F => T::Rgba32Float,
        60 => T::Rg8Snorm,   // V8U8
        63 => T::Rgba8Snorm, // Q8W8V8U8
        70 | 80 => T::Depth16Unorm,
        fmt::D24S8 | 79 => T::Depth24PlusStencil8,
        77 => T::Depth24Plus,
        71 | 82 | 83 => T::Depth32Float,
        f if bc && f == fourcc(b"DXT1") => T::Bc1RgbaUnorm,
        f if bc && (f == fourcc(b"DXT2") || f == fourcc(b"DXT3")) => T::Bc2RgbaUnorm,
        f if bc && (f == fourcc(b"DXT4") || f == fourcc(b"DXT5")) => T::Bc3RgbaUnorm,
        _ => return None,
    })
}

/// The D3D format name of the `Format` annotation table.
pub fn format_name(d3d: u32) -> String {
    mds_mme::sas::FORMATS
        .iter()
        .find(|(_, v)| *v == d3d)
        .map_or_else(|| d3d.to_string(), |(n, _)| n.to_string())
}

/// What the runtime created for one resource.
pub struct Created {
    pub kind: TexKind,
    /// The color texture (for a depth target its 1x1 placeholder).
    pub texture: Option<wgpu::Texture>,
    pub format: u32,
    /// The depth surface of a depth target, or of an offscreen target.
    pub depth: Option<wgpu::Texture>,
    pub depth_format: u32,
}

impl Created {
    /// The `created`/`offscreendepth` lines of the plan, from the wgpu objects.
    pub fn plan_lines(&self, r: &Resource) -> Vec<String> {
        let mut out = Vec::new();
        if let Some(t) = &self.texture {
            let kind = if self.kind == TexKind::Cube {
                "cube"
            } else {
                "texture"
            };
            out.push(format!(
                "created {kind} {}x{} levels={} format={}",
                t.width(),
                t.height(),
                t.mip_level_count(),
                format_name(self.format)
            ));
        }
        let depth = |t: &wgpu::Texture| {
            format!(
                "{}x{} format={}",
                t.width(),
                t.height(),
                format_name(self.depth_format)
            )
        };
        if r.semantic == SEM_RENDER_DEPTH {
            if let Some(d) = &self.depth {
                out.push(format!("created depthsurface {}", depth(d)));
            }
        }
        if r.semantic == SEM_OFFSCREEN {
            out.push(match &self.depth {
                Some(d) => format!("offscreendepth {}", depth(d)),
                None => "offscreendepth none".into(),
            });
        }
        out
    }
}

pub const COLOR_USAGE: wgpu::TextureUsages = wgpu::TextureUsages::RENDER_ATTACHMENT
    .union(wgpu::TextureUsages::TEXTURE_BINDING)
    .union(wgpu::TextureUsages::COPY_SRC)
    .union(wgpu::TextureUsages::COPY_DST);

fn texture(
    gpu: &Gpu,
    label: &str,
    (w, h, layers): (u32, u32, u32),
    levels: u32,
    dim: wgpu::TextureDimension,
    format: wgpu::TextureFormat,
    usage: wgpu::TextureUsages,
) -> wgpu::Texture {
    gpu.device.create_texture(&wgpu::TextureDescriptor {
        label: Some(label),
        size: wgpu::Extent3d {
            width: w,
            height: h,
            depth_or_array_layers: layers,
        },
        mip_level_count: levels,
        sample_count: 1,
        dimension: dim,
        format,
        usage,
        view_formats: &[],
    })
}

/// Creates the objects of `r` as `mds-mme` modelled them. `Ok(None)` for a resource that
/// creates no texture (animated, value, and shader textures).
pub fn create(gpu: &Gpu, r: &Resource) -> Result<Option<Created>, String> {
    let Some(t) = r.texture else {
        return Ok(None);
    };
    let fmt_of = |d3d| {
        wgpu_format(d3d, gpu.features)
            .ok_or_else(|| format!("{}: format {} has no wgpu format", r.name, format_name(d3d)))
    };
    let render = matches!(r.semantic, SEM_RENDER_COLOR | SEM_OFFSCREEN);
    let usage = if render {
        COLOR_USAGE
    } else {
        wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST
    };
    let format = fmt_of(t.format)?;
    if render && format.is_compressed() {
        return Err(format!("{}: a compressed render target", r.name));
    }
    let (size, dim) = match t.kind {
        TexKind::Plain => ((t.width, t.height, 1), wgpu::TextureDimension::D2),
        TexKind::Cube => ((t.width, t.width, 6), wgpu::TextureDimension::D2),
        TexKind::Volume => {
            let d = u32::try_from(r.req_depth).unwrap_or(1).max(1);
            ((t.width, t.height, d), wgpu::TextureDimension::D3)
        }
    };
    let tex = texture(gpu, &r.name, size, t.levels, dim, format, usage);
    if let Some(file) = &r.resource_file {
        if !render && r.semantic != SEM_RENDER_DEPTH {
            upload_file(gpu, &tex, file, t.format, format);
        }
    }
    let surface = r.surface.or(r.offscreen_depth);
    let depth = match surface {
        Some((w, h, f)) => Some((
            texture(
                gpu,
                &format!("{}.depth", r.name),
                (w, h, 1),
                1,
                wgpu::TextureDimension::D2,
                fmt_of(f)?,
                wgpu::TextureUsages::RENDER_ATTACHMENT,
            ),
            f,
        )),
        None => None,
    };
    Ok(Some(Created {
        kind: t.kind,
        texture: Some(tex),
        format: t.format,
        depth_format: depth.as_ref().map_or(0, |d| d.1),
        depth: depth.map(|d| d.0),
    }))
}

/// Decoded texels: width, height, and RGBA8 (top row first), or raw level-0 bytes in the
/// texture's own format.
enum Texels {
    Rgba8(u32, u32, Vec<u8>),
    Raw(u32, u32, Vec<u8>),
}

fn u16le(b: &[u8], i: usize) -> Option<u32> {
    Some(u32::from(u16::from_le_bytes(
        b.get(i..i + 2)?.try_into().ok()?,
    )))
}

fn u32le(b: &[u8], i: usize) -> Option<u32> {
    Some(u32::from_le_bytes(b.get(i..i + 4)?.try_into().ok()?))
}

fn decode_png(b: &[u8]) -> Option<Texels> {
    let (w, h, rgba) = decode_png_rgba(b, false)?;
    Some(Texels::Rgba8(w, h, rgba))
}

/// A PNG as width, height, and RGBA8; `ignore_crc` skips the chunk checksums.
pub(crate) fn decode_png_rgba(b: &[u8], ignore_crc: bool) -> Option<(u32, u32, Vec<u8>)> {
    let mut dec = png::Decoder::new(std::io::Cursor::new(b));
    dec.ignore_checksums(ignore_crc);
    dec.set_transformations(png::Transformations::EXPAND | png::Transformations::STRIP_16);
    let mut reader = dec.read_info().ok()?;
    let mut buf = vec![0; reader.output_buffer_size()?];
    let info = reader.next_frame(&mut buf).ok()?;
    let px = &buf[..info.buffer_size()];
    let rgba: Vec<u8> = match info.color_type {
        png::ColorType::Rgba => px.to_vec(),
        png::ColorType::Rgb => px.chunks(3).flat_map(|c| [c[0], c[1], c[2], 255]).collect(),
        png::ColorType::GrayscaleAlpha => px
            .chunks(2)
            .flat_map(|c| [c[0], c[0], c[0], c[1]])
            .collect(),
        png::ColorType::Grayscale => px.iter().flat_map(|&g| [g, g, g, 255]).collect(),
        png::ColorType::Indexed => return None,
    };
    Some((info.width, info.height, rgba))
}

/// Bottom-up rows of `bpp`-byte BGR(A) pixels to top-down RGBA.
fn bgr_rows(px: &[u8], w: u32, h: u32, bpp: usize, row: usize, bottom_up: bool) -> Option<Vec<u8>> {
    let mut out = Vec::with_capacity((w * h * 4) as usize);
    for y in 0..h as usize {
        let src = if bottom_up { h as usize - 1 - y } else { y };
        let line = px.get(src * row..src * row + w as usize * bpp)?;
        for c in line.chunks(bpp) {
            out.extend([c[2], c[1], c[0], if bpp == 4 { c[3] } else { 255 }]);
        }
    }
    Some(out)
}

fn decode(b: &[u8], d3d: u32) -> Option<Texels> {
    if b.starts_with(b"\x89PNG") {
        return decode_png(b);
    }
    if b.starts_with(b"BM") {
        let (off, w) = (u32le(b, 10)? as usize, u32le(b, 18)?);
        let h_raw = u32le(b, 22)? as i32;
        let bpp = usize::from(u16::try_from(u16le(b, 28)?).ok()? / 8);
        if bpp != 3 && bpp != 4 {
            return None;
        }
        let h = h_raw.unsigned_abs();
        let row = (w as usize * bpp).next_multiple_of(4);
        return bgr_rows(b.get(off..)?, w, h, bpp, row, h_raw > 0).map(|p| Texels::Rgba8(w, h, p));
    }
    if b.starts_with(b"DDS ") {
        let (h, w) = (u32le(b, 12)?, u32le(b, 16)?);
        let data = b.get(128..)?;
        let flags = u32le(b, 80)?;
        if flags & 4 == 0 {
            let bits = u32le(b, 88)?;
            if bits != 32 {
                return None;
            }
            // A8R8G8B8 in memory is B, G, R, A: the Bgra8Unorm layout.
            let n = (w * h * 4) as usize;
            return Some(Texels::Raw(w, h, data.get(..n)?.to_vec()));
        }
        let block = |bytes: u32| ((w.div_ceil(4)) * (h.div_ceil(4)) * bytes) as usize;
        let n = match d3d {
            f if f == fourcc(b"DXT1") => block(8),
            f if f == fourcc(b"DXT2")
                || f == fourcc(b"DXT3")
                || f == fourcc(b"DXT4")
                || f == fourcc(b"DXT5") =>
            {
                block(16)
            }
            113 => (w * h * 8) as usize,
            116 => (w * h * 16) as usize,
            111 => (w * h * 2) as usize,
            114 | 112 => (w * h * 4) as usize,
            115 => (w * h * 8) as usize,
            _ => return None,
        };
        return Some(Texels::Raw(w, h, data.get(..n)?.to_vec()));
    }
    if b.starts_with(b"\xff\xd8") || b.starts_with(b"#?") {
        return None;
    }
    // TGA: uncompressed true color (2) or gray (3), origin bit 5 of the descriptor.
    let (kind, depth, desc) = (*b.get(2)?, *b.get(16)?, *b.get(17)?);
    let (w, h) = (u16le(b, 12)?, u16le(b, 14)?);
    let px = b.get(18 + usize::from(*b.first()?)..)?;
    let bottom_up = desc & 0x20 == 0;
    match (kind, depth) {
        (2, 24 | 32) => {
            let bpp = usize::from(depth / 8);
            bgr_rows(px, w, h, bpp, w as usize * bpp, bottom_up).map(|p| Texels::Rgba8(w, h, p))
        }
        (3, 8) => {
            let rgb: Vec<u8> = px
                .get(..(w * h) as usize)?
                .iter()
                .flat_map(|&g| [g, g, g])
                .collect();
            bgr_rows(&rgb, w, h, 3, w as usize * 3, bottom_up).map(|p| Texels::Rgba8(w, h, p))
        }
        _ => None,
    }
}

/// Nearest-texel resample of RGBA8 to `w` x `h` (D3DX filters; the file sizes the corpus uses
/// are mostly powers of two already).
fn resample(src: &[u8], sw: u32, sh: u32, w: u32, h: u32) -> Vec<u8> {
    let mut out = Vec::with_capacity((w * h * 4) as usize);
    for y in 0..h {
        let sy = (u64::from(y) * u64::from(sh) / u64::from(h)) as usize;
        for x in 0..w {
            let sx = (u64::from(x) * u64::from(sw) / u64::from(w)) as usize;
            let i = (sy * sw as usize + sx) * 4;
            out.extend_from_slice(&src[i..i + 4]);
        }
    }
    out
}

/// RGBA8 to the texel bytes of `format` (BGRA swaps, one- and two-channel formats keep the
/// luminance and alpha D3D would).
fn pack(rgba: &[u8], format: wgpu::TextureFormat) -> Option<Vec<u8>> {
    use wgpu::TextureFormat as T;
    Some(match format {
        T::Rgba8Unorm => rgba.to_vec(),
        T::Bgra8Unorm => rgba
            .chunks(4)
            .flat_map(|c| [c[2], c[1], c[0], c[3]])
            .collect(),
        T::R8Unorm => rgba.chunks(4).map(|c| c[0]).collect(),
        T::Rg8Unorm => rgba.chunks(4).flat_map(|c| [c[0], c[3]]).collect(),
        _ => return None,
    })
}

fn write_level(gpu: &Gpu, tex: &wgpu::Texture, level: u32, w: u32, h: u32, data: &[u8]) {
    let format = tex.format();
    let (bw, bh) = format.block_dimensions();
    let block_bytes = format.block_copy_size(None).unwrap_or(4);
    let layers = tex.depth_or_array_layers();
    let per_layer = (w.div_ceil(bw) * h.div_ceil(bh) * block_bytes) as usize;
    for layer in 0..layers.min(if tex.dimension() == wgpu::TextureDimension::D3 {
        1
    } else {
        layers
    }) {
        if data.len() < per_layer {
            return;
        }
        gpu.queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: tex,
                mip_level: level,
                origin: wgpu::Origin3d {
                    x: 0,
                    y: 0,
                    z: layer,
                },
                aspect: wgpu::TextureAspect::All,
            },
            &data[..per_layer],
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(w.div_ceil(bw) * block_bytes),
                rows_per_image: Some(h.div_ceil(bh)),
            },
            wgpu::Extent3d {
                width: w.div_ceil(bw) * bw,
                height: h.div_ceil(bh) * bh,
                depth_or_array_layers: 1,
            },
        );
    }
}

/// Fills `tex` from `file` when the decoder knows the file; otherwise the texture stays black.
fn upload_file(
    gpu: &Gpu,
    tex: &wgpu::Texture,
    file: &std::path::Path,
    d3d: u32,
    format: wgpu::TextureFormat,
) {
    let Ok(bytes) = std::fs::read(file) else {
        return;
    };
    let (w, h) = (tex.width(), tex.height());
    match decode(&bytes, d3d) {
        Some(Texels::Rgba8(sw, sh, px)) => {
            let mut level = resample(&px, sw, sh, w, h);
            let (mut lw, mut lh) = (w, h);
            for l in 0..tex.mip_level_count() {
                let Some(packed) = pack(&level, format) else {
                    return;
                };
                write_level(gpu, tex, l, lw, lh, &packed);
                let (nw, nh) = ((lw / 2).max(1), (lh / 2).max(1));
                level = box_down(&level, lw, lh, nw, nh);
                (lw, lh) = (nw, nh);
            }
        }
        Some(Texels::Raw(sw, sh, data)) if (sw, sh) == (w, h) => {
            write_level(gpu, tex, 0, w, h, &data)
        }
        _ => {}
    }
}

fn box_down(src: &[u8], sw: u32, sh: u32, w: u32, h: u32) -> Vec<u8> {
    let mut out = Vec::with_capacity((w * h * 4) as usize);
    for y in 0..h {
        for x in 0..w {
            let mut acc = [0u32; 4];
            let mut n = 0;
            for (dx, dy) in [(0, 0), (1, 0), (0, 1), (1, 1)] {
                let (sx, sy) = ((x * 2 + dx).min(sw - 1), (y * 2 + dy).min(sh - 1));
                let i = ((sy * sw + sx) * 4) as usize;
                for c in 0..4 {
                    acc[c] += u32::from(src[i + c]);
                }
                n += 1;
            }
            out.extend(acc.map(|a| ((a + n / 2) / n) as u8));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tga_and_bmp_decode_to_top_down_rgba() {
        // 2x1 TGA, bottom-up, BGR.
        let mut tga = vec![0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 1, 0, 24, 0];
        tga.extend([1, 2, 3, 4, 5, 6]);
        let Some(Texels::Rgba8(2, 1, px)) = decode(&tga, fmt::X8R8G8B8) else {
            panic!("tga")
        };
        assert_eq!(px, [3, 2, 1, 255, 6, 5, 4, 255]);
        assert_eq!(resample(&px, 2, 1, 4, 1)[4..8], [3, 2, 1, 255]);
        assert_eq!(box_down(&px, 2, 1, 1, 1), [5, 4, 3, 255]);
        assert_eq!(
            pack(&px, wgpu::TextureFormat::Bgra8Unorm).unwrap()[..4],
            [1, 2, 3, 255]
        );
        assert_eq!(format_name(fmt::A32B32G32R32F), "A32B32G32R32F");
        assert_eq!(
            wgpu_format(fmt::D24S8, wgpu::Features::empty()),
            Some(wgpu::TextureFormat::Depth24PlusStencil8)
        );
    }
}
