//! Device-independent bitmap rows to RGBA8, shared by the AVI frames and the
//! BMP background picture.

/// Converts BI_RGB rows of 24 or 32 bits to top-down RGBA8 with opaque alpha.
///
/// `height` is the signed `biHeight`: positive means the rows are stored
/// bottom-up, negative top-down. Rows are padded to 4 bytes. Alpha is forced
/// to 255 because the C++ draws the frame into an `X8R8G8B8` surface
/// (`src/render/bg_overlay.cpp:AviBgOverlayRefresh`), which never reads the
/// fourth byte. Returns `None` for other depths, a zero size, or short data.
pub(crate) fn rgba_from_dib(width: u32, height: i32, bpp: u16, bits: &[u8]) -> Option<Vec<u8>> {
    if !matches!(bpp, 24 | 32) || width == 0 || height == 0 {
        return None;
    }
    let (w, h) = (width as usize, height.unsigned_abs() as usize);
    let px = usize::from(bpp / 8);
    let row = w.checked_mul(px)?;
    let stride = row.checked_add(3)? & !3;
    if bits.len() < stride.checked_mul(h)? {
        return None;
    }
    let mut out = Vec::with_capacity(w.checked_mul(h)?.checked_mul(4)?);
    for y in 0..h {
        let src_row = if height > 0 { h - 1 - y } else { y };
        let src = &bits[src_row * stride..][..row];
        for p in src.chunks_exact(px) {
            out.extend_from_slice(&[p[2], p[1], p[0], 255]);
        }
    }
    Some(out)
}
