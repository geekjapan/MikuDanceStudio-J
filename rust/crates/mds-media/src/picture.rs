//! The background picture file.
//!
//! The C++ (`src/media/media_load.cpp:LoadBackgroundPicture`, VA 0x4337A0)
//! hands the file to `D3DXCreateTextureFromFileExW`, which picks the decoder
//! by content: bmp, dib, jpg, png, tga, dds, pfm. This port decodes BMP/DIB
//! (24 and 32 bit `BI_RGB`), JPEG and PNG, chosen by magic bytes, and
//! reports the rest as [`PictureError::Unsupported`].
//!
//! The C++ asks D3DX for a 1024x1024 texture (then 512x512 with one mip
//! level) and keeps the image's own size from `D3DXIMAGE_INFO` for the
//! placement. [`Picture`] is the decoded image at its own size; the resize to
//! the texture is the renderer's.

use crate::dib::rgba_from_dib;
use zune_jpeg::zune_core::{bytestream::ZCursor, colorspace::ColorSpace, options::DecoderOptions};
use zune_jpeg::JpegDecoder;

/// A decoded picture: `width * height * 4` bytes, top-down RGBA8. BMP and
/// JPEG are opaque; PNG keeps its alpha.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Picture {
    pub width: u32,
    pub height: u32,
    pub rgba: Vec<u8>,
}

#[derive(Debug, PartialEq, Eq)]
pub enum PictureError {
    /// The file is missing (`WsOpenOk` fails) or its decoder fails (both
    /// `D3DXCreateTextureFromFileExW` tries fail): the C++ shows one message.
    Open,
    /// A format D3DX reads and this port does not; the text names it.
    Unsupported(String),
}

impl PictureError {
    pub fn message(&self, english: bool) -> String {
        match self {
            PictureError::Open if english => "Cannot open BMP file".into(),
            PictureError::Open => "BMPファイルを読み込めませんでした".into(),
            PictureError::Unsupported(what) if english => {
                format!("Unsupported picture format ({what}). Use BMP, JPEG or PNG.")
            }
            PictureError::Unsupported(what) => {
                format!("未対応の画像形式です({what})。BMP、JPEG、PNGを使用してください。")
            }
        }
    }

    /// Caption of the C++ `MessageBoxA`.
    pub fn caption(&self, english: bool) -> &'static str {
        if english {
            "open BMP file"
        } else {
            "BMPファイル読込"
        }
    }
}

impl std::fmt::Display for PictureError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message(true))
    }
}

impl std::error::Error for PictureError {}

const PNG_SIGNATURE: &[u8] = b"\x89PNG\r\n\x1a\n";

/// Decodes a picture file.
pub fn decode(file: &[u8]) -> Result<Picture, PictureError> {
    if file.starts_with(b"BM") {
        decode_bmp(file)
    } else if file.starts_with(&[0xFF, 0xD8]) {
        decode_jpeg(file)
    } else if file.starts_with(PNG_SIGNATURE) {
        decode_png(file)
    } else if file.starts_with(b"DDS ") {
        Err(PictureError::Unsupported("DDS".into()))
    } else {
        Err(PictureError::Unsupported(
            "not BMP, JPEG or PNG; TGA and DDS are not supported".into(),
        ))
    }
}

fn le32(b: &[u8], at: usize) -> Option<u32> {
    Some(u32::from_le_bytes(b.get(at..at + 4)?.try_into().ok()?))
}

/// A BMP file: 14-byte file header, then a `BITMAPINFOHEADER` or later one
/// (only its first 40 bytes are read), then the pixel array at `bfOffBits`.
fn decode_bmp(file: &[u8]) -> Result<Picture, PictureError> {
    let bad = || PictureError::Open;
    let off_bits = le32(file, 10).ok_or_else(bad)? as usize;
    let (size, w, h) = (
        le32(file, 14).ok_or_else(bad)?,
        le32(file, 18).ok_or_else(bad)?,
        le32(file, 22).ok_or_else(bad)? as i32,
    );
    if size < 40 {
        return Err(PictureError::Unsupported("OS/2 bitmap".into()));
    }
    let bpp = u16::from_le_bytes(file.get(28..30).ok_or_else(bad)?.try_into().unwrap());
    let comp = le32(file, 30).ok_or_else(bad)?;
    if comp != 0 || !matches!(bpp, 24 | 32) {
        return Err(PictureError::Unsupported(format!(
            "{bpp}-bit BMP, compression {comp}"
        )));
    }
    let bits = file.get(off_bits..).ok_or_else(bad)?;
    let rgba = rgba_from_dib(w, h, bpp, bits).ok_or_else(bad)?;
    Ok(Picture {
        width: w,
        height: h.unsigned_abs(),
        rgba,
    })
}

/// JPEG to RGBA8 (opaque), with the size from the header.
pub(crate) fn jpeg_rgba(data: &[u8]) -> Option<Picture> {
    let opts = DecoderOptions::default().jpeg_set_out_colorspace(ColorSpace::RGBA);
    let mut dec = JpegDecoder::new_with_options(ZCursor::new(data), opts);
    let rgba = dec.decode().ok()?;
    let info = dec.info()?;
    Some(Picture {
        width: info.width.into(),
        height: info.height.into(),
        rgba,
    })
}

fn decode_jpeg(file: &[u8]) -> Result<Picture, PictureError> {
    jpeg_rgba(file).ok_or(PictureError::Open)
}

fn decode_png(file: &[u8]) -> Result<Picture, PictureError> {
    let bad = |_| PictureError::Open;
    let mut dec = png::Decoder::new(std::io::Cursor::new(file));
    dec.set_transformations(png::Transformations::normalize_to_color8());
    let mut reader = dec.read_info().map_err(bad)?;
    let mut buf = vec![0; reader.output_buffer_size().ok_or(PictureError::Open)?];
    let info = reader.next_frame(&mut buf).map_err(bad)?;
    let px = &buf[..info.buffer_size()];
    let rgba = match info.color_type {
        png::ColorType::Rgba => px.to_vec(),
        png::ColorType::Rgb => px
            .chunks_exact(3)
            .flat_map(|p| [p[0], p[1], p[2], 255])
            .collect(),
        png::ColorType::GrayscaleAlpha => px
            .chunks_exact(2)
            .flat_map(|p| [p[0], p[0], p[0], p[1]])
            .collect(),
        png::ColorType::Grayscale => px.iter().flat_map(|&g| [g, g, g, 255]).collect(),
        png::ColorType::Indexed => return Err(PictureError::Open),
    };
    Ok(Picture {
        width: info.width,
        height: info.height,
        rgba,
    })
}
