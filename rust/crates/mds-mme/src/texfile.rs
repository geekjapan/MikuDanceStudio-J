//! What `D3DXCreate{,Cube,Volume}TextureFromFileExA` creates for a texture file, from the
//! file header alone: size, mip count, and format (Format and Pool are D3DFMT_UNKNOWN and
//! MANAGED in the runtime's call, so they come from the file).
//!
//! Readers: PNG, JPEG, BMP, TGA, DDS, and Radiance HDR. The format rules are those D3DX9
//! applies when the device takes the file format, with 24-bit RGB promoted to X8R8G8B8.

use std::path::Path;

use crate::sas::{fmt, levels, TexKind, Texture};

const D3DXERR_INVALIDDATA: &str = "Invalid data [88760B6E]";

/// Size and format of the top image of a file.
struct Header {
    width: u32,
    height: u32,
    format: u32,
}

/// The texture D3DX loads from `path`. `width`, `height`, and `mips` are the raw request
/// (-1 = `D3DX_DEFAULT`). The error is the dxerr text and code the log line carries.
pub fn load(
    path: &Path,
    texture_type: i32,
    width: i32,
    height: i32,
    mips: i32,
) -> Result<Texture, String> {
    let bytes = std::fs::read(path).map_err(|_| D3DXERR_INVALIDDATA.to_string())?;
    let h = header(&bytes).ok_or_else(|| D3DXERR_INVALIDDATA.to_string())?;
    // 0 and D3DX_DEFAULT take the file size rounded up to a power of two.
    let size = |req: i32, file: u32| {
        if req > 0 {
            req as u32
        } else {
            file.max(1).next_power_of_two()
        }
    };
    let kind = match texture_type {
        8 => TexKind::Volume,
        9 => TexKind::Cube,
        _ => TexKind::Plain,
    };
    let w = size(width, h.width);
    let ht = if kind == TexKind::Cube {
        w
    } else {
        size(height, h.height)
    };
    Ok(Texture {
        kind,
        width: w,
        height: ht,
        levels: levels(mips as u32, w, ht),
        format: h.format,
        pool: 1,
        usage: 0,
    })
}

fn u16le(b: &[u8], i: usize) -> Option<u32> {
    Some(u32::from(u16::from_le_bytes(
        b.get(i..i + 2)?.try_into().ok()?,
    )))
}

fn u32le(b: &[u8], i: usize) -> Option<u32> {
    Some(u32::from_le_bytes(b.get(i..i + 4)?.try_into().ok()?))
}

fn u32be(b: &[u8], i: usize) -> Option<u32> {
    Some(u32::from_be_bytes(b.get(i..i + 4)?.try_into().ok()?))
}

// ponytail: the formats below are the ones the corpus files use (checked against the
// oracle) plus their obvious neighbours; anything else is `Invalid data`, which shows up as a
// plan mismatch rather than a silent guess.
fn header(b: &[u8]) -> Option<Header> {
    let h = |width, height, format| {
        Some(Header {
            width,
            height,
            format,
        })
    };
    if b.starts_with(b"\x89PNG\r\n\x1a\n") {
        let (w, ht) = (u32be(b, 16)?, u32be(b, 20)?);
        let (depth, color) = (*b.get(24)?, *b.get(25)?);
        let alpha = color == 4 || color == 6 || png_has_chunk(b, b"tRNS");
        let format = match (color, depth, alpha) {
            (_, 16, _) => return None,
            (0, _, false) => fmt::L8,
            (0 | 4, _, _) => fmt::A8L8,
            (_, _, false) => fmt::X8R8G8B8,
            _ => fmt::A8R8G8B8,
        };
        return h(w, ht, format);
    }
    if b.starts_with(b"\xff\xd8") {
        let mut i = 2;
        while i + 9 < b.len() {
            if b[i] != 0xff {
                i += 1;
                continue;
            }
            let marker = b[i + 1];
            if (0xc0..=0xcf).contains(&marker) && !matches!(marker, 0xc4 | 0xc8 | 0xcc) {
                let ht = u32::from(u16::from_be_bytes([b[i + 5], b[i + 6]]));
                let w = u32::from(u16::from_be_bytes([b[i + 7], b[i + 8]]));
                let gray = b[i + 9] == 1;
                return h(w, ht, if gray { fmt::L8 } else { fmt::X8R8G8B8 });
            }
            i += 2 + usize::from(u16::from_be_bytes([b[i + 2], b[i + 3]]));
        }
        return None;
    }
    if b.starts_with(b"BM") {
        let w = u32le(b, 18)?;
        let ht = (u32le(b, 22)? as i32).unsigned_abs();
        let format = match u16le(b, 28)? {
            32 => fmt::A8R8G8B8,
            24 => fmt::X8R8G8B8,
            _ => return None,
        };
        return h(w, ht, format);
    }
    if b.starts_with(b"DDS ") {
        let (ht, w) = (u32le(b, 12)?, u32le(b, 16)?);
        let flags = u32le(b, 80)?;
        let format = if flags & 4 != 0 {
            u32le(b, 84)? // a FourCC or a D3DFORMAT number
        } else {
            match (u32le(b, 88)?, u32le(b, 104)?) {
                (32, 0) => fmt::X8R8G8B8,
                (32, _) => fmt::A8R8G8B8,
                _ => return None,
            }
        };
        return h(w, ht, format);
    }
    if b.starts_with(b"#?") {
        // Radiance HDR: a header, a blank line, then `-Y <height> +X <width>`.
        let text = String::from_utf8_lossy(&b[..b.len().min(4096)]);
        let line = text.lines().find(|l| l.starts_with("-Y"))?;
        let mut it = line.split_whitespace().skip(1).step_by(2);
        let (ht, w) = (it.next()?.parse().ok()?, it.next()?.parse().ok()?);
        return h(w, ht, fmt::A32B32G32R32F);
    }
    // TGA has no signature: the image type and the pixel depth.
    let (w, ht) = (u16le(b, 12)?, u16le(b, 14)?);
    let format = match (*b.get(2)? & !8, *b.get(16)?) {
        (2, 32) => fmt::A8R8G8B8,
        (2, 24) => fmt::X8R8G8B8,
        (3, 8) => fmt::L8,
        _ => return None,
    };
    h(w, ht, format)
}

fn png_has_chunk(b: &[u8], name: &[u8; 4]) -> bool {
    let mut i = 8;
    while let (Some(len), Some(tag)) = (u32be(b, i), b.get(i + 4..i + 8)) {
        if tag == name {
            return true;
        }
        if tag == b"IDAT" {
            return false;
        }
        i += 12 + len as usize;
    }
    false
}
