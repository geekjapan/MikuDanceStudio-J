//! An AVI 1.0 writer for uncompressed BGR24 video with an optional PCM audio
//! stream.
//!
//! There is no C++ twin: the C++ records through DirectShow. The layout is the
//! one of the Microsoft AVI RIFF reference: `RIFF 'AVI '` holding `LIST hdrl`
//! (`avih`, then one `LIST strl` per stream), `LIST movi` with the data
//! chunks in the order written, and a closing `idx1` index.
//!
//! The format names 32-bit sizes and offsets, and old readers fail past 2 GB,
//! so the writer stops at 1 GiB ([`MAX_FILE_BYTES`]) and returns
//! [`Error::TooLarge`]. A longer recording needs OpenDML (`AVIX` extension
//! RIFFs and a super index), which this writer does not have.
//!
//! The caller passes frames top-down and tightly packed (`width * 3` bytes per
//! row); the writer stores them bottom-up with 4-byte row padding, as a
//! `BI_RGB` DIB.

use std::io::{self, Seek, SeekFrom, Write};

/// The largest file the writer produces.
pub const MAX_FILE_BYTES: u64 = 1 << 30;

#[derive(Debug)]
pub enum Error {
    Io(io::Error),
    /// A parameter the format cannot hold (the text names it).
    Param(&'static str),
    /// The next chunk would take the file past [`MAX_FILE_BYTES`].
    TooLarge,
}

impl From<io::Error> for Error {
    fn from(e: io::Error) -> Self {
        Error::Io(e)
    }
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::Io(e) => write!(f, "{e}"),
            Error::Param(p) => write!(f, "bad AVI parameter: {p}"),
            Error::TooLarge => write!(f, "AVI 1.0 file would pass 1 GiB"),
        }
    }
}

impl std::error::Error for Error {}

/// PCM audio; `bits` is 8 or 16.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AudioFormat {
    pub channels: u16,
    pub sample_rate: u32,
    pub bits: u16,
}

impl AudioFormat {
    pub fn block_align(&self) -> u32 {
        u32::from(self.channels) * u32::from(self.bits) / 8
    }
}

/// The frame rate is `fps_num / fps_den` (30/1, 30000/1001).
#[derive(Debug, Clone, Copy)]
pub struct Config {
    pub width: u32,
    pub height: u32,
    pub fps_num: u32,
    pub fps_den: u32,
    pub audio: Option<AudioFormat>,
}

struct IndexEntry {
    id: [u8; 4],
    offset: u32,
    size: u32,
}

pub struct AviWriter<W: Write + Seek> {
    out: W,
    cfg: Config,
    /// Bytes of one stored frame (padded rows).
    frame_bytes: u32,
    header_len: u64,
    /// File position of the next chunk.
    pos: u64,
    frames: u32,
    audio_bytes: u32,
    index: Vec<IndexEntry>,
}

/// A chunk: tag, size, body, and a pad byte after an odd body.
fn put(buf: &mut Vec<u8>, tag: &[u8; 4], body: &[u8]) {
    buf.extend_from_slice(tag);
    buf.extend_from_slice(&(body.len() as u32).to_le_bytes());
    buf.extend_from_slice(body);
    if body.len() % 2 == 1 {
        buf.push(0);
    }
}

fn list(buf: &mut Vec<u8>, kind: &[u8; 4], body: &[u8]) {
    let mut inner = kind.to_vec();
    inner.extend_from_slice(body);
    put(buf, b"LIST", &inner);
}

fn le(words: &[u32]) -> Vec<u8> {
    words.iter().flat_map(|w| w.to_le_bytes()).collect()
}

/// `AVIStreamHeader` (56 bytes) with no handler, priority or start.
fn strh(
    kind: &[u8; 4],
    scale: u32,
    rate: u32,
    length: u32,
    buf: u32,
    sample_size: u32,
    frame: (u16, u16),
) -> Vec<u8> {
    let mut b = kind.to_vec();
    b.extend(le(&[
        0,
        0,
        0,
        0,
        scale,
        rate,
        0,
        length,
        buf,
        u32::MAX,
        sample_size,
    ]));
    for v in [0, 0, frame.0, frame.1] {
        b.extend(v.to_le_bytes());
    }
    b
}

impl<W: Write + Seek> AviWriter<W> {
    /// Writes the header (patched in [`finish`](Self::finish)) and opens `movi`.
    pub fn new(out: W, cfg: Config) -> Result<Self, Error> {
        if cfg.width == 0 || cfg.height == 0 || cfg.width > 0xFFFF || cfg.height > 0xFFFF {
            return Err(Error::Param("size must be 1 to 65535"));
        }
        if cfg.fps_num == 0 || cfg.fps_den == 0 {
            return Err(Error::Param("frame rate is zero"));
        }
        if let Some(a) = cfg.audio {
            if a.channels == 0 || a.sample_rate == 0 || !matches!(a.bits, 8 | 16) {
                return Err(Error::Param("audio must be 8 or 16 bit PCM with a rate"));
            }
        }
        let frame_bytes = u64::from((cfg.width * 3).div_ceil(4) * 4) * u64::from(cfg.height);
        if frame_bytes > MAX_FILE_BYTES / 2 {
            return Err(Error::Param("frame is too large for AVI 1.0"));
        }
        let frame_bytes = frame_bytes as u32;
        let mut w = AviWriter {
            out,
            cfg,
            frame_bytes,
            header_len: 0,
            pos: 0,
            frames: 0,
            audio_bytes: 0,
            index: Vec::new(),
        };
        let header = w.header(0);
        w.out.write_all(&header)?;
        w.header_len = header.len() as u64;
        w.pos = w.header_len;
        Ok(w)
    }

    /// Appends one frame: `width * height * 3` bytes, top-down BGR.
    pub fn write_frame(&mut self, bgr: &[u8]) -> Result<(), Error> {
        let (w, h) = (self.cfg.width as usize, self.cfg.height as usize);
        if bgr.len() != w * h * 3 {
            return Err(Error::Param("frame length is not width * height * 3"));
        }
        let stride = (w * 3).div_ceil(4) * 4;
        let mut dib = vec![0u8; stride * h];
        for (y, src) in bgr.chunks_exact(w * 3).enumerate() {
            let at = (h - 1 - y) * stride;
            dib[at..at + src.len()].copy_from_slice(src);
        }
        self.write_chunk(*b"00db", &dib)?;
        self.frames += 1;
        Ok(())
    }

    /// Appends PCM bytes (a whole number of blocks) to the audio stream.
    pub fn write_audio(&mut self, pcm: &[u8]) -> Result<(), Error> {
        let Some(a) = self.cfg.audio else {
            return Err(Error::Param("the file has no audio stream"));
        };
        if !pcm.len().is_multiple_of(a.block_align() as usize) {
            return Err(Error::Param("audio is not a whole number of blocks"));
        }
        self.write_chunk(*b"01wb", pcm)?;
        self.audio_bytes += pcm.len() as u32;
        Ok(())
    }

    /// Writes the index, patches the header, and returns the output.
    pub fn finish(mut self) -> Result<W, Error> {
        let mut idx = Vec::with_capacity(self.index.len() * 16);
        for e in &self.index {
            idx.extend_from_slice(&e.id);
            idx.extend(le(&[0x10, e.offset, e.size])); // AVIIF_KEYFRAME
        }
        let mut tail = Vec::new();
        put(&mut tail, b"idx1", &idx);
        self.out.write_all(&tail)?;
        let end = self.pos + tail.len() as u64;
        let header = self.header(end);
        self.out.seek(SeekFrom::Start(0))?;
        self.out.write_all(&header)?;
        self.out.seek(SeekFrom::Start(end))?;
        self.out.flush()?;
        Ok(self.out)
    }

    fn write_chunk(&mut self, id: [u8; 4], payload: &[u8]) -> Result<(), Error> {
        let total = 8 + payload.len() as u64 + (payload.len() as u64 & 1);
        let index_after = 8 + 16 * (self.index.len() as u64 + 1);
        if self.pos + total + index_after > MAX_FILE_BYTES {
            return Err(Error::TooLarge);
        }
        let mut chunk = Vec::with_capacity(total as usize);
        put(&mut chunk, &id, payload);
        self.out.write_all(&chunk)?;
        self.index.push(IndexEntry {
            id,
            // Relative to the `movi` tag, the last four bytes of the header.
            offset: (self.pos - (self.header_len - 4)) as u32,
            size: payload.len() as u32,
        });
        self.pos += total;
        Ok(())
    }

    /// The header up to and including `LIST movi`, for a file `end` bytes
    /// long (0 while the sizes are still unknown).
    fn header(&self, end: u64) -> Vec<u8> {
        let Config {
            width,
            height,
            fps_num,
            fps_den,
            audio,
        } = self.cfg;
        let audio_rate = audio.map_or(0, |a| a.sample_rate * a.block_align());
        let micro = (1_000_000 * u64::from(fps_den) + u64::from(fps_num) / 2) / u64::from(fps_num);
        let video_rate = u64::from(self.frame_bytes) * u64::from(fps_num) / u64::from(fps_den);

        let avih = le(&[
            micro as u32,
            (video_rate as u32).saturating_add(audio_rate),
            0,
            0x10 | if audio.is_some() { 0x100 } else { 0 }, // HASINDEX, ISINTERLEAVED
            self.frames,
            0,
            1 + u32::from(audio.is_some()),
            self.frame_bytes,
            width,
            height,
            0,
            0,
            0,
            0,
        ]);
        let mut hdrl = Vec::new();
        put(&mut hdrl, b"avih", &avih);

        let mut video = Vec::new();
        put(
            &mut video,
            b"strh",
            &strh(
                b"vids",
                fps_den,
                fps_num,
                self.frames,
                self.frame_bytes,
                0,
                (width as u16, height as u16),
            ),
        );
        // BITMAPINFOHEADER: positive height means bottom-up rows.
        let mut bih = le(&[40, width, height]);
        bih.extend(1u16.to_le_bytes());
        bih.extend(24u16.to_le_bytes());
        bih.extend(le(&[0, self.frame_bytes, 0, 0, 0, 0]));
        put(&mut video, b"strf", &bih);
        list(&mut hdrl, b"strl", &video);

        if let Some(a) = audio {
            let block = a.block_align();
            let mut stream = Vec::new();
            put(
                &mut stream,
                b"strh",
                &strh(
                    b"auds",
                    1,
                    a.sample_rate,
                    self.audio_bytes / block,
                    a.sample_rate * block,
                    block,
                    (0, 0),
                ),
            );
            let mut wfx = Vec::new();
            wfx.extend(1u16.to_le_bytes()); // WAVE_FORMAT_PCM
            wfx.extend(a.channels.to_le_bytes());
            wfx.extend(a.sample_rate.to_le_bytes());
            wfx.extend((a.sample_rate * block).to_le_bytes());
            wfx.extend((block as u16).to_le_bytes());
            wfx.extend(a.bits.to_le_bytes());
            put(&mut stream, b"strf", &wfx);
            list(&mut hdrl, b"strl", &stream);
        }

        let mut out = Vec::new();
        list(&mut out, b"hdrl", &hdrl);
        let movi_data = self.pos.saturating_sub(self.header_len);
        let mut head = b"RIFF".to_vec();
        head.extend(le(&[end.saturating_sub(8) as u32]));
        head.extend(b"AVI ");
        head.extend(out);
        head.extend(b"LIST");
        head.extend(le(&[4 + movi_data as u32]));
        head.extend(b"movi");
        head
    }
}
