//! WAV loading and the timeline waveform, as the C++ computes them.
//!
//! The C++ does not walk the RIFF chunks. It reads the format fields at fixed
//! offsets (tag at 20, channels at 22, rate at 24, average bytes at 28, block
//! align at 32, bits at 34) and then scans the rest of the file byte by byte
//! for the letters `data`. A `fmt ` chunk that is not first, or the letters
//! `data` inside a `LIST` text, therefore give the answer the C++ gives, not
//! the one a chunk parser would.
//!
//! One intended difference: the C++ `malloc`s the two waveform arrays with
//! `dataSize / colBytes + 1` bytes each, taking `dataSize` from the file
//! header, so a 50-byte file declaring a data size of `0x7FFFFFF0` allocates
//! gigabytes. [`Waveform`] keeps the same logical length but stores only the
//! columns the loop reaches, which the bytes present in the input bound (the
//! loop stops at the first short read); every other column reads as 0, the
//! C++ initial fill. The per-column scratch buffer stays at `colBytes`, at
//! most about `u32::MAX / 390` bytes.

use std::io;
use std::path::Path;

/// Offset of the first byte after the format fields; where the C++ starts
/// looking for the `data` chunk.
const SCAN_START: usize = 36;

/// `cbSize` the C++ stores in the format it hands to DirectSound.
pub const CB_SIZE: u16 = 0x12;

/// The `WAVEFORMATEX` fields the C++ reads. The tag is always PCM (1).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Format {
    pub channels: u16,
    pub samples_per_sec: u32,
    pub avg_bytes_per_sec: u32,
    pub block_align: u16,
    pub bits_per_sample: u16,
}

/// Where `ScanWaveDataChunk` found the data: the declared size and the file
/// offset of its first byte.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DataChunk {
    pub size: i32,
    pub offset: i32,
}

/// Why `WaveLoadFile` returns false.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Reject {
    /// Not `RIFF`, or the format tag is not 1. The C++ shows a message box.
    NotPcm,
    /// No `data` tag after the format fields, or its size field is cut off or negative.
    NoDataChunk,
    /// Block align 0, or a timeline column smaller than one block.
    Unusable,
}

#[derive(Debug)]
pub enum Error {
    Io(io::Error),
    Reject(Reject),
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
            Error::Reject(r) => write!(f, "not a usable WAVE(PCM) file: {r:?}"),
        }
    }
}

impl std::error::Error for Error {}

/// `ScanWaveDataChunk` on a stream positioned at `from`.
///
/// A byte that breaks a partial match is consumed, not re-examined: `ddata`
/// is not found at its second letter. A size field that is cut off or has the
/// top bit set is a miss, like an offset beyond `i32::MAX`.
pub fn scan_data_chunk(bytes: &[u8], from: usize) -> Option<DataChunk> {
    let mut pos = from;
    let mut next = || {
        let b = bytes.get(pos).copied();
        pos += usize::from(b.is_some());
        b
    };
    'scan: loop {
        for want in *b"data" {
            if next()? != want {
                continue 'scan;
            }
        }
        break;
    }
    let size = i32::from_le_bytes(bytes.get(pos..pos + 4)?.try_into().ok()?);
    if size < 0 {
        return None;
    }
    let offset = i32::try_from(pos + 4).ok()?;
    Some(DataChunk { size, offset })
}

fn u16_at(bytes: &[u8], at: usize) -> u16 {
    bytes
        .get(at..at + 2)
        .map_or(0, |b| u16::from_le_bytes([b[0], b[1]]))
}

fn u32_at(bytes: &[u8], at: usize) -> u32 {
    bytes
        .get(at..at + 4)
        .map_or(0, |b| u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
}

/// One timeline waveform array. `len()` is the C++ column count; only the
/// columns that were computed are stored, and the rest read as 0.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Waveform {
    len: usize,
    stored: Vec<u8>,
}

impl Waveform {
    pub fn len(&self) -> usize {
        self.len
    }

    pub fn is_empty(&self) -> bool {
        self.len == 0
    }

    /// Column `i`; 0 past the stored columns. Panics when `i >= len()`.
    pub fn get(&self, i: usize) -> u8 {
        assert!(i < self.len, "column {i} of {}", self.len);
        self.stored.get(i).copied().unwrap_or(0)
    }

    pub fn iter(&self) -> impl Iterator<Item = u8> + '_ {
        (0..self.len).map(|i| self.get(i))
    }

    /// The columns that hold storage; the rest are 0.
    pub fn stored(&self) -> &[u8] {
        &self.stored
    }
}

/// A loaded WAV file: the format, the data chunk, the timeline waveform, and
/// the file bytes behind them.
#[derive(Debug, Clone)]
pub struct Wave {
    pub format: Format,
    pub data: DataChunk,
    /// Per timeline column (390 per second of audio), `(max * 25 >> shift) + 25`
    /// of the loudest sample, as the timeline strip draws it. Columns after a
    /// short read stay 0.
    pub waveform_max: Waveform,
    /// The same for the lowest sample.
    pub waveform_min: Waveform,
    /// Short reads while building the waveform (the last column nearly always
    /// reads past the end, so 1 is normal).
    pub read_failures: i32,
    file: Vec<u8>,
}

impl Wave {
    pub fn load(path: impl AsRef<Path>) -> Result<Wave, Error> {
        Wave::from_bytes(std::fs::read(path)?).map_err(Error::Reject)
    }

    /// `WaveLoadFile` on the bytes of a file.
    pub fn from_bytes(file: Vec<u8>) -> Result<Wave, Reject> {
        if file.get(..4) != Some(&b"RIFF"[..]) || u16_at(&file, 20) != 1 {
            return Err(Reject::NotPcm);
        }
        let format = Format {
            channels: u16_at(&file, 22),
            samples_per_sec: u32_at(&file, 24),
            avg_bytes_per_sec: u32_at(&file, 28),
            block_align: u16_at(&file, 32),
            bits_per_sample: u16_at(&file, 34),
        };
        let data = scan_data_chunk(&file, SCAN_START).ok_or(Reject::NoDataChunk)?;
        let avg = format.avg_bytes_per_sec as f32;
        let block = i32::from(format.block_align);
        if block == 0 {
            return Err(Reject::Unusable);
        }
        // Single precision, in this order, as the x64 build computes it.
        let col_bytes = (avg * (1.0f32 / 30.0f32) / 13.0f32 / block as f32) as i32 * block;
        if col_bytes <= 0 {
            return Err(Reject::Unusable);
        }
        // The C++ overflows here for size 0x7FFFFFFF with one byte per column.
        let columns = (data.size / col_bytes)
            .checked_add(1)
            .ok_or(Reject::Unusable)? as usize;
        let empty = || Waveform {
            len: columns,
            stored: Vec::new(),
        };
        let mut wave = Wave {
            format,
            data,
            waveform_max: empty(),
            waveform_min: empty(),
            read_failures: 0,
            file,
        };
        wave.build_waveform(col_bytes);
        Ok(wave)
    }

    /// The data chunk bytes the file holds: `data.size`, or fewer when the
    /// file is cut short.
    pub fn pcm(&self) -> &[u8] {
        let start = (self.data.offset as usize).min(self.file.len());
        let end = (start + self.data.size as usize).min(self.file.len());
        &self.file[start..end]
    }

    /// `nAvgBytesPerSec * 2`: the size of the DirectSound streaming buffer.
    pub fn buffer_bytes(&self) -> i32 {
        self.format.avg_bytes_per_sec.wrapping_mul(2) as i32
    }

    /// The file offset `WaveSeekAndFeed` seeks to for a playback time: the
    /// byte of that time in the data chunk, rounded down to a whole block.
    /// Frame `n` at 30 fps is `seek_offset(n as f64 / 30.0)`.
    pub fn seek_offset(&self, seconds: f64) -> i32 {
        let block = f64::from(self.format.block_align);
        let t = block * ((f64::from(self.format.avg_bytes_per_sec) * seconds) / block);
        let whole = t as i32;
        let rem = whole
            .checked_rem(i32::from(self.format.block_align))
            .unwrap_or(0);
        self.data.offset.wrapping_sub(rem).wrapping_add(whole)
    }

    fn build_waveform(&mut self, col_bytes: i32) {
        let Format {
            channels,
            avg_bytes_per_sec,
            block_align,
            bits_per_sample,
            ..
        } = self.format;
        let block = i32::from(block_align);
        let avg = avg_bytes_per_sec as f32;
        let columns = self.waveform_max.len() as i32;
        let (mut maxes, mut mins) = (Vec::new(), Vec::new());
        let mut reader = StreamReader {
            file: &self.file,
            start: self.data.offset as usize,
            cursor: 0,
            size: self.data.size,
            bits: bits_per_sample,
        };
        let mut scratch = vec![0u8; col_bytes as usize];
        // 0 and 1: 8 and 16 bit mono; 2 and 3: 8 and 16 bit stereo. The C++
        // takes it from the block align, not from the bit depth.
        let k = if channels == 1 {
            i32::from(block != 1)
        } else if block != 2 {
            3
        } else {
            2
        };
        let shift = if k == 0 || k == 2 { 7 } else { 15 };
        let sample = |s: &[u8], i: usize| i32::from(s.get(i).copied().unwrap_or(0) as i8);
        let mut so_far = 0i32;
        for i in 0..columns {
            let t = ((i as f32 / 390.0f32) * avg) as i32;
            let skip_blocks = (t.wrapping_sub(so_far) as u32) / block as u32;
            if skip_blocks as i32 > 0 {
                let skip = block.wrapping_mul(skip_blocks as i32);
                if !reader.read(&mut scratch, skip) {
                    self.read_failures += 1;
                }
                so_far = so_far.wrapping_add(skip);
            }
            let ok = reader.read(&mut scratch, col_bytes);
            if !ok {
                self.read_failures += 1;
            }
            so_far = so_far.wrapping_add(col_bytes);

            let (mut max, mut min) = (0i32, 0i32);
            for off in (0..col_bytes as usize).step_by(block as usize) {
                let (l, r) = match k {
                    3 => (
                        (sample(&scratch, off + 1) << 8) + sample(&scratch, off),
                        (sample(&scratch, off + 3) << 8) + sample(&scratch, off + 2),
                    ),
                    2 => (sample(&scratch, off), sample(&scratch, off + 1)),
                    1 => {
                        let l = (sample(&scratch, off + 1) << 8) + sample(&scratch, off);
                        (l, l)
                    }
                    _ => (sample(&scratch, off), sample(&scratch, off)),
                };
                max = max.max(l).max(r);
                min = min.min(l).min(r);
            }
            maxes.push((((max * 25) >> shift) + 25) as u8);
            mins.push((((min * 25) >> shift) + 25) as u8);
            if !ok {
                break;
            }
        }
        self.waveform_max.stored = maxes;
        self.waveform_min.stored = mins;
    }
}

/// `WaveStreamRead`: reads at most the rest of the data chunk, and pads a
/// short read with silence (0 for 16 bit, 0x80 for 8 bit; other depths keep
/// what the buffer held).
struct StreamReader<'a> {
    file: &'a [u8],
    start: usize,
    cursor: i32,
    size: i32,
    bits: u16,
}

impl StreamReader<'_> {
    fn read(&mut self, buf: &mut [u8], bytes: i32) -> bool {
        let want = if self.cursor.wrapping_add(bytes) < self.size {
            bytes
        } else {
            self.size - self.cursor
        } as usize;
        let from = (self.start + self.cursor as usize).min(self.file.len());
        let got = want.min(self.file.len() - from).min(buf.len());
        buf[..got].copy_from_slice(&self.file[from..from + got]);
        self.cursor += got as i32;
        let bytes = bytes as usize;
        if got >= bytes {
            return true;
        }
        let end = bytes.min(buf.len());
        match self.bits {
            16 => buf[got..end].fill(0),
            8 => buf[got..end].fill(0x80),
            _ => {}
        }
        false
    }
}
