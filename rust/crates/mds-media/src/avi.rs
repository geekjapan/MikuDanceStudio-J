//! An OpenDML (AVI 2.0) writer for uncompressed BGR24 video with an optional
//! PCM audio stream.
//!
//! There is no C++ twin: the C++ records through DirectShow, whose AVI mux
//! writes OpenDML. The layout is the one of the Microsoft AVI RIFF reference
//! and the OpenDML extension, as DirectShow's mux and libavformat write it:
//!
//! ```text
//! RIFF 'AVI '                      first RIFF, under MAX_RIFF_BYTES
//!   LIST hdrl  avih, LIST strl (strh strf indx)..., LIST odml (dmlh)
//!   LIST movi  data chunks in the order written, then ix00 [ix01]
//!   idx1                           legacy index of the first RIFF only
//! RIFF 'AVIX'                      one per further MAX_RIFF_BYTES
//!   LIST movi  data chunks, then ix00 [ix01]
//! ```
//!
//! Every RIFF stays under [`MAX_RIFF_BYTES`] (the 32-bit sizes, and readers
//! that treat them as signed). A chunk that would pass the limit closes the
//! RIFF (standard indexes `ix00`/`ix01`, one per stream with chunks in it) and
//! opens the next `AVIX`. The super index (`indx`) in each `strl` has room for
//! [`SUPER_ENTRIES`] standard indexes, so a file holds up to that many RIFFs;
//! past it [`Error::TooLarge`]. The `idx1` of the first RIFF lets AVI 1.0
//! readers play the first gibibyte. The frame counts in `avih`, `strh` and
//! `dmlh` are the totals of the file.
//!
//! The super index is reserved in the header from the start (the header is
//! rewritten in place at the end, so its size cannot grow), so even a short
//! file differs from the AVI 1.0 output this writer had before: the `indx`
//! space, the `odml` list and the `ix` chunks.
//!
//! The caller passes frames top-down and tightly packed (`width * 3` bytes per
//! row); the writer stores them bottom-up with 4-byte row padding, as a
//! `BI_RGB` DIB.

use std::io::{self, Seek, SeekFrom, Write};

/// The largest RIFF (the first one holds the header) the writer produces.
pub const MAX_RIFF_BYTES: u64 = 1 << 30;

/// Standard indexes a super index can name: the number of RIFFs a file holds
/// (1 TiB with [`MAX_RIFF_BYTES`]).
pub const SUPER_ENTRIES: usize = 1024;

#[derive(Debug)]
pub enum Error {
    Io(io::Error),
    /// A parameter the format cannot hold (the text names it).
    Param(&'static str),
    /// The file would need more than [`SUPER_ENTRIES`] RIFFs.
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
            Error::TooLarge => write!(f, "AVI file would pass the super index capacity"),
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

const VIDEO: usize = 0;
const AUDIO: usize = 1;
const DATA_IDS: [[u8; 4]; 2] = [*b"00db", *b"01wb"];
const IX_IDS: [[u8; 4]; 2] = [*b"ix00", *b"ix01"];

/// One data chunk of the open RIFF.
struct Entry {
    stream: usize,
    /// File position of the chunk header.
    pos: u64,
    size: u32,
}

/// The RIFF being written.
struct Riff {
    start: u64,
    /// File position of the `LIST` tag of its `movi`.
    movi: u64,
    entries: Vec<Entry>,
    /// Chunks per stream in `entries`.
    counts: [u64; 2],
}

/// A super index entry: one standard index.
struct Named {
    offset: u64,
    size: u32,
    duration: u32,
}

pub struct AviWriter<W: Write + Seek> {
    out: W,
    cfg: Config,
    /// Bytes of one stored frame (padded rows).
    frame_bytes: u32,
    riff_limit: u64,
    /// File position of the next chunk.
    pos: u64,
    frames: u32,
    audio_bytes: u64,
    riff: Riff,
    /// RIFFs started, the open one included.
    riffs: usize,
    supers: [Vec<Named>; 2],
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

/// The tail of a RIFF holding `counts` chunks: its standard indexes and, in
/// the first RIFF, the `idx1`.
fn tail_len(counts: [u64; 2], first: bool) -> u64 {
    let ix: u64 = counts
        .iter()
        .filter(|&&c| c > 0)
        .map(|c| 8 + 24 + 8 * c)
        .sum();
    ix + if first {
        8 + 16 * (counts[0] + counts[1])
    } else {
        0
    }
}

/// `LIST movi` opened with sizes still unknown.
fn movi_open(buf: &mut Vec<u8>) {
    buf.extend(b"LIST");
    buf.extend(le(&[0]));
    buf.extend(b"movi");
}

impl<W: Write + Seek> AviWriter<W> {
    /// Writes the header (patched in [`finish`](Self::finish)) and opens `movi`.
    pub fn new(out: W, cfg: Config) -> Result<Self, Error> {
        Self::with_riff_limit(out, cfg, MAX_RIFF_BYTES)
    }

    /// [`new`](Self::new) with RIFFs of at most `riff_limit` bytes (at most
    /// [`MAX_RIFF_BYTES`]); a small limit makes a short recording cross RIFFs.
    pub fn with_riff_limit(out: W, cfg: Config, riff_limit: u64) -> Result<Self, Error> {
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
        if riff_limit > MAX_RIFF_BYTES {
            return Err(Error::Param("RIFF limit is over 1 GiB"));
        }
        let frame_bytes = u64::from((cfg.width * 3).div_ceil(4) * 4) * u64::from(cfg.height);
        if frame_bytes > riff_limit / 2 {
            return Err(Error::Param("frame is too large for a RIFF"));
        }
        let mut w = AviWriter {
            out,
            cfg,
            frame_bytes: frame_bytes as u32,
            riff_limit,
            pos: 0,
            frames: 0,
            audio_bytes: 0,
            riff: Riff {
                start: 0,
                movi: 0,
                entries: Vec::new(),
                counts: [0; 2],
            },
            riffs: 1,
            supers: [Vec::new(), Vec::new()],
        };
        let mut head = b"RIFF".to_vec();
        head.extend(le(&[0]));
        head.extend(b"AVI ");
        head.extend(w.hdrl());
        w.riff.movi = head.len() as u64;
        movi_open(&mut head);
        w.out.write_all(&head)?;
        w.pos = head.len() as u64;
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
        self.write_chunk(VIDEO, &dib)?;
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
        self.write_chunk(AUDIO, pcm)?;
        self.audio_bytes += pcm.len() as u64;
        Ok(())
    }

    /// Closes the last RIFF, patches the header, and returns the output.
    pub fn finish(mut self) -> Result<W, Error> {
        self.close_riff()?;
        let hdrl = self.hdrl();
        self.out.seek(SeekFrom::Start(12))?;
        self.out.write_all(&hdrl)?;
        self.out.seek(SeekFrom::Start(self.pos))?;
        self.out.flush()?;
        Ok(self.out)
    }

    fn write_chunk(&mut self, stream: usize, payload: &[u8]) -> Result<(), Error> {
        let len = payload.len() as u64;
        let total = 8 + len + (len & 1);
        if !self.fits(stream, total) {
            // A chunk that would not fit an empty RIFF either is refused.
            if self.riff.entries.is_empty() {
                return Err(Error::Param("chunk is too large for a RIFF"));
            }
            self.next_riff()?;
            if !self.fits(stream, total) {
                return Err(Error::Param("chunk is too large for a RIFF"));
            }
        }
        let mut head = DATA_IDS[stream].to_vec();
        head.extend(le(&[len as u32]));
        self.out.write_all(&head)?;
        self.out.write_all(payload)?;
        if len & 1 == 1 {
            self.out.write_all(&[0])?;
        }
        self.riff.entries.push(Entry {
            stream,
            pos: self.pos,
            size: len as u32,
        });
        self.riff.counts[stream] += 1;
        self.pos += total;
        Ok(())
    }

    /// Whether a chunk of `total` bytes and the tail of the RIFF behind it
    /// stay under the limit.
    fn fits(&self, stream: usize, total: u64) -> bool {
        let mut counts = self.riff.counts;
        counts[stream] += 1;
        let tail = tail_len(counts, self.riff.start == 0);
        self.pos + total + tail <= self.riff.start + self.riff_limit
    }

    /// Ends the open RIFF and starts an `AVIX`.
    fn next_riff(&mut self) -> Result<(), Error> {
        if self.riffs >= SUPER_ENTRIES {
            return Err(Error::TooLarge);
        }
        self.close_riff()?;
        let mut head = b"RIFF".to_vec();
        head.extend(le(&[0]));
        head.extend(b"AVIX");
        let movi = self.pos + head.len() as u64;
        movi_open(&mut head);
        self.out.write_all(&head)?;
        self.riff = Riff {
            start: self.pos,
            movi,
            entries: Vec::new(),
            counts: [0; 2],
        };
        self.pos += head.len() as u64;
        self.riffs += 1;
        Ok(())
    }

    /// Writes the standard indexes (and, in the first RIFF, `idx1`) behind the
    /// chunks of the open RIFF and patches its sizes.
    fn close_riff(&mut self) -> Result<(), Error> {
        let base = self.riff.movi;
        let mut tail = Vec::new();
        for stream in [VIDEO, AUDIO] {
            let mine = || self.riff.entries.iter().filter(|e| e.stream == stream);
            let n = mine().count();
            if n == 0 {
                continue;
            }
            let mut ix = 2u16.to_le_bytes().to_vec();
            ix.extend([0, 1]); // sub type 0, AVI_INDEX_OF_CHUNKS
            ix.extend(le(&[n as u32]));
            ix.extend(DATA_IDS[stream]);
            ix.extend(base.to_le_bytes());
            ix.extend(le(&[0]));
            for e in mine() {
                // The offset names the data, behind the 8-byte chunk header.
                ix.extend(le(&[(e.pos + 8 - base) as u32, e.size]));
            }
            let duration = match (stream, self.cfg.audio) {
                (AUDIO, Some(a)) => mine().map(|e| e.size / a.block_align()).sum(),
                _ => n as u32,
            };
            self.supers[stream].push(Named {
                offset: self.pos + tail.len() as u64,
                size: 8 + ix.len() as u32,
                duration,
            });
            put(&mut tail, &IX_IDS[stream], &ix);
        }
        self.out.write_all(&tail)?;
        self.pos += tail.len() as u64;
        let movi_size = (self.pos - base - 8) as u32;

        if self.riff.start == 0 {
            // Offsets are relative to the `movi` tag, behind its `LIST` header.
            let mut idx = Vec::with_capacity(self.riff.entries.len() * 16);
            for e in &self.riff.entries {
                idx.extend(DATA_IDS[e.stream]);
                idx.extend(le(&[0x10, (e.pos - (base + 8)) as u32, e.size])); // AVIIF_KEYFRAME
            }
            let mut idx1 = Vec::new();
            put(&mut idx1, b"idx1", &idx);
            self.out.write_all(&idx1)?;
            self.pos += idx1.len() as u64;
        }
        let riff_size = (self.pos - self.riff.start - 8) as u32;
        for (at, v) in [(base + 4, movi_size), (self.riff.start + 4, riff_size)] {
            self.out.seek(SeekFrom::Start(at))?;
            self.out.write_all(&v.to_le_bytes())?;
        }
        self.out.seek(SeekFrom::Start(self.pos))?;
        Ok(())
    }

    /// `LIST hdrl`. Its size does not depend on the counts, so the final
    /// header replaces the first one in place.
    fn hdrl(&self) -> Vec<u8> {
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
        put(&mut video, b"indx", &self.indx(VIDEO));
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
                    (self.audio_bytes / u64::from(block)) as u32,
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
            put(&mut stream, b"indx", &self.indx(AUDIO));
            list(&mut hdrl, b"strl", &stream);
        }

        // `dmlh`: dwGrandFrames, then 244 reserved bytes.
        let mut dmlh = le(&[self.frames]);
        dmlh.resize(248, 0);
        let mut odml = Vec::new();
        put(&mut odml, b"dmlh", &dmlh);
        list(&mut hdrl, b"odml", &odml);

        let mut out = Vec::new();
        list(&mut out, b"hdrl", &hdrl);
        out
    }

    /// The super index of `stream`: `AVI_INDEX_OF_INDEXES`, with room for
    /// [`SUPER_ENTRIES`] entries.
    fn indx(&self, stream: usize) -> Vec<u8> {
        let named = &self.supers[stream];
        let mut b = 4u16.to_le_bytes().to_vec();
        b.extend([0, 0]); // sub type 0, AVI_INDEX_OF_INDEXES
        b.extend(le(&[named.len() as u32]));
        b.extend(DATA_IDS[stream]);
        b.extend(le(&[0, 0, 0]));
        for n in named {
            b.extend(n.offset.to_le_bytes());
            b.extend(le(&[n.size, n.duration]));
        }
        b.resize(24 + 16 * SUPER_ENTRIES, 0);
        b
    }
}
