//! The background movie: an AVI read the way `LoadAviFile` opens it, with
//! the frame chosen the way `AviBgOverlayRefresh` chooses it.
//!
//! Ports `src/media/media_load.cpp:LoadAviFile` (VA 0x433250) and the frame
//! selection of `src/render/bg_overlay.cpp:AviBgOverlayRefresh` (VA
//! 0x4168D0). The C++ goes through the VFW calls `AVIFileOpenW`,
//! `AVIFileInfoA`, `AVIFileGetStream`, `AVIStreamInfoA`,
//! `AVIStreamGetFrameOpen` and `AVIStreamGetFrame`; this module reads the RIFF
//! itself and decodes the two codecs the operator decided to keep (2026-10-25):
//! uncompressed `BI_RGB` (24 and 32 bit, bottom-up and top-down) and Motion
//! JPEG (`zune-jpeg`). Any other codec is [`MovieError::Unsupported`].
//!
//! Frames are RGBA8 of the stream size, top-down, alpha 255.
//!
//! Only AVI 1.0 chunk layout is read: the `LIST movi` chunks (and `rec `
//! lists and `AVIX` extensions, which are walked the same way) are indexed by
//! scanning, not through `idx1`.

use crate::dib::rgba_from_dib;
use crate::picture::jpeg_rgba;
use std::fs::File;
use std::io::{self, BufReader, Read, Seek, SeekFrom};
use std::path::Path;

/// `g_FrameScale` (`src/app/globals.cpp`): the scene frame rate.
pub const FRAME_SCALE: f32 = 30.0;

/// The failure sites of `LoadAviFile`, plus the codec gate. The UI shows
/// [`message`](Self::message) under [`caption`](Self::caption); after any of
/// them the caller clears the AVI path slot and the enabled flag
/// (`AviFailTail`), as [`crate::background::MovieBackground::load`] does.
#[derive(Debug, PartialEq, Eq)]
pub enum MovieError {
    /// `AVIFileOpenW` failed: unreadable, or not an AVI.
    Open,
    /// `AVIFileInfoA` failed: no main header.
    Info,
    /// `AVIFileGetStream` failed: fewer streams than the main header says.
    GetStream,
    /// `AVIStreamInfoA` failed: no usable stream header.
    StreamInfo,
    /// No `vids` stream.
    NoVideoStream,
    /// `AVIStreamGetFrameOpen` has no decoder for the video format. The text
    /// names the format. The C++ shows "Cannot open AVI file" here.
    Unsupported(String),
    /// `AVIStreamGetFrame` gave no frame (frame 0 at load, any frame while
    /// playing): the sample is out of range or the data does not decode.
    Frame,
}

impl MovieError {
    /// `kMsgAvi*` texts of `media_load.cpp` (Shift-JIS there, Unicode here);
    /// `english` is `EnglishUI() != 0`.
    pub fn message(&self, english: bool) -> String {
        let (en, jp) = match self {
            MovieError::Open => ("Cannot open AVI file!!", "AVIファイルが読み込めません"),
            MovieError::Info => ("Cannot read AVIFILEINFO!!", "AVIFILEINFOを読み込めません"),
            MovieError::GetStream => ("Failed AVIFileGetStream", "AVIFileGetStream失敗"),
            MovieError::StreamInfo => ("Failed AVIStreamInfo", "AVIStreamInfo失敗"),
            MovieError::NoVideoStream | MovieError::Frame => {
                ("Cannot open AVI file", "AVIファイルを読み込めません")
            }
            MovieError::Unsupported(what) => {
                return if english {
                    format!(
                        "Unsupported AVI video format ({what}). \
                         Only uncompressed and Motion JPEG AVI can be used."
                    )
                } else {
                    format!(
                        "未対応のAVI形式です({what})。\
                         非圧縮とMotion JPEGのAVIのみ使用できます。"
                    )
                };
            }
        };
        (if english { en } else { jp }).to_owned()
    }

    /// The `MessageBoxA` caption of the same sites.
    pub fn caption(&self, english: bool) -> &'static str {
        if english {
            "open AVI file"
        } else {
            "AVIデータ読込"
        }
    }
}

impl std::fmt::Display for MovieError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message(true))
    }
}

impl std::error::Error for MovieError {}

/// One decoded frame: `width * height * 4` bytes, top-down RGBA8.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Frame {
    pub width: u32,
    pub height: u32,
    pub rgba: Vec<u8>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Codec {
    Raw { bpp: u16, bottom_up: bool },
    Mjpeg,
}

/// What `LoadAviFile` keeps of the chosen stream.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MovieInfo {
    /// `header->biWidth` of the decoded frame.
    pub width: i32,
    /// `abs(header->biHeight)`. The C++ keeps the signed value; a top-down
    /// raw AVI would give it a negative height there.
    pub height: i32,
    /// `AVIStreamStart` (`AviStreamStartFrame`).
    pub start: i32,
    /// `AVIStreamStart + AVIStreamLength` (`AviStreamEndFrame`). The length
    /// is the number of frame chunks found, which is `dwLength` for a
    /// well-formed file.
    pub end: i32,
    /// `AviUsesThirtyFpsTiming`: `AVIStreamSampleToTime(stream, 1)` is 33 ms.
    pub uses_thirty_fps_timing: bool,
    rate: u32,
    scale: u32,
}

#[derive(Clone, Copy)]
struct FrameLoc {
    offset: u64,
    len: u32,
}

/// An opened background movie.
pub struct Movie<R: Read + Seek> {
    src: R,
    info: MovieInfo,
    codec: Codec,
    frames: Vec<FrameLoc>,
}

impl Movie<BufReader<File>> {
    pub fn open_path(path: &Path) -> Result<Self, MovieError> {
        Self::open(BufReader::new(
            File::open(path).map_err(|_| MovieError::Open)?,
        ))
    }
}

struct VideoStream {
    index: usize,
    rate: u32,
    scale: u32,
    start: u32,
    width: i32,
    height: i32,
    codec: Codec,
}

fn u32_at(b: &[u8], at: usize) -> Option<u32> {
    Some(u32::from_le_bytes(b.get(at..at + 4)?.try_into().ok()?))
}

/// The chunks of an in-memory list body, cut short at the first bad size.
fn sub_chunks(mut b: &[u8]) -> Vec<([u8; 4], &[u8])> {
    let mut out = Vec::new();
    while b.len() >= 8 {
        let size = u32_at(b, 4).unwrap_or(0) as usize;
        let Some(body) = b.get(8..8usize.saturating_add(size)) else {
            break;
        };
        out.push((b[..4].try_into().unwrap(), body));
        b = b.get(8 + ((size + 1) & !1)..).unwrap_or(&[]);
    }
    out
}

fn describe_compression(bpp: u16, comp: u32) -> String {
    match comp {
        0 => format!("{bpp}-bit uncompressed"),
        1 => "RLE8".into(),
        2 => "RLE4".into(),
        3 => "BI_BITFIELDS".into(),
        _ => comp
            .to_le_bytes()
            .iter()
            .map(|&c| {
                if c.is_ascii_graphic() || c == b' ' {
                    c as char
                } else {
                    '?'
                }
            })
            .collect::<String>()
            .trim_end()
            .to_owned(),
    }
}

/// The stream scan of `LoadAviFile` (0x4333CC..0x43346E) over the `hdrl`
/// body: the `vids` stream with the lowest `wPriority`, the first on a tie.
fn select_video(hdrl: &[u8]) -> Result<VideoStream, MovieError> {
    let chunks = sub_chunks(hdrl.get(4..).unwrap_or(&[]));
    let streams = chunks
        .iter()
        .find(|(id, _)| id == b"avih")
        .and_then(|(_, b)| u32_at(b, 24))
        .ok_or(MovieError::Info)?;
    let strls: Vec<_> = chunks
        .iter()
        .filter(|(id, b)| id == b"LIST" && b.starts_with(b"strl"))
        .map(|(_, b)| sub_chunks(&b[4..]))
        .collect();

    let mut best: Option<(u16, VideoStream)> = None;
    for i in 0..streams as usize {
        let strl = strls.get(i).ok_or(MovieError::GetStream)?;
        let strh = strl
            .iter()
            .find(|(id, _)| id == b"strh")
            .map(|(_, b)| *b)
            .filter(|b| b.len() >= 36)
            .ok_or(MovieError::StreamInfo)?;
        let (scale, rate) = (u32_at(strh, 20).unwrap(), u32_at(strh, 24).unwrap());
        if scale == 0 || rate == 0 {
            return Err(MovieError::StreamInfo);
        }
        if &strh[..4] != b"vids" {
            continue;
        }
        let priority = u16::from_le_bytes([strh[12], strh[13]]);
        if best.as_ref().is_some_and(|(p, _)| priority >= *p) {
            continue;
        }
        let strf = strl
            .iter()
            .find(|(id, _)| id == b"strf")
            .map(|(_, b)| *b)
            .unwrap_or(&[]);
        best = Some((
            priority,
            video_stream(i, strf, scale, rate, u32_at(strh, 28).unwrap())?,
        ));
    }
    best.map(|(_, v)| v).ok_or(MovieError::NoVideoStream)
}

/// The decoder gate: `AVIStreamGetFrameOpen` returns NULL for a format it
/// cannot decompress.
fn video_stream(
    index: usize,
    strf: &[u8],
    scale: u32,
    rate: u32,
    start: u32,
) -> Result<VideoStream, MovieError> {
    let unsupported = |what: String| MovieError::Unsupported(what);
    let (Some(width), Some(height), Some(comp)) =
        (u32_at(strf, 4), u32_at(strf, 8), u32_at(strf, 16))
    else {
        return Err(unsupported("no video format header".into()));
    };
    let (width, height) = (width as i32, height as i32);
    let bpp = u16::from_le_bytes([strf[14], strf[15]]);
    let codec = match (comp, bpp) {
        (0, 24 | 32) => Codec::Raw {
            bpp,
            bottom_up: height > 0,
        },
        (c, _) if c.to_le_bytes().eq_ignore_ascii_case(b"MJPG") => Codec::Mjpeg,
        _ => return Err(unsupported(describe_compression(bpp, comp))),
    };
    if width <= 0 || height == 0 {
        return Err(unsupported("empty frame size".into()));
    }
    Ok(VideoStream {
        index,
        rate,
        scale,
        start,
        width,
        height: height
            .checked_abs()
            .ok_or_else(|| unsupported("frame size".into()))?,
        codec,
    })
}

/// Walks the RIFF flat: `RIFF` and `LIST` are entered, `hdrl` is read whole,
/// every other chunk is skipped by its size. Returns the video stream and
/// the position of each of its frame chunks.
fn scan<R: Read + Seek>(r: &mut R) -> Result<(VideoStream, Vec<FrameLoc>), MovieError> {
    let io = |_: io::Error| MovieError::Open;
    let len = r.seek(SeekFrom::End(0)).map_err(io)?;
    let mut pos = 0u64;
    let mut video: Option<VideoStream> = None;
    let mut frames = Vec::new();
    while pos + 8 <= len {
        r.seek(SeekFrom::Start(pos)).map_err(io)?;
        let mut h = [0u8; 8];
        r.read_exact(&mut h).map_err(io)?;
        let id: [u8; 4] = h[..4].try_into().unwrap();
        let size = u64::from(u32::from_le_bytes(h[4..].try_into().unwrap()));
        let body = pos + 8;
        if pos == 0 && &id != b"RIFF" {
            return Err(MovieError::Open);
        }
        if &id == b"RIFF" || &id == b"LIST" {
            let mut form = [0u8; 4];
            r.read_exact(&mut form).map_err(io)?;
            if pos == 0 && &form != b"AVI " {
                return Err(MovieError::Open);
            }
            if &form == b"hdrl" && video.is_none() {
                let end = (body + size).min(len);
                let mut hdrl = vec![0u8; (end.saturating_sub(body)) as usize];
                r.seek(SeekFrom::Start(body)).map_err(io)?;
                r.read_exact(&mut hdrl).map_err(io)?;
                video = Some(select_video(&hdrl)?);
                pos = body + size + (size & 1);
            } else {
                pos = body + 4;
            }
            continue;
        }
        if let Some(v) = &video {
            let stream_no = id[..2].iter().all(u8::is_ascii_digit)
                && usize::from(id[0] - b'0') * 10 + usize::from(id[1] - b'0') == v.index;
            if stream_no && matches!(&id[2..], b"db" | b"dc") && body + size <= len {
                frames.push(FrameLoc {
                    offset: body,
                    len: size as u32,
                });
            }
        }
        pos = body + size + (size & 1);
    }
    video.map(|v| (v, frames)).ok_or(MovieError::Open)
}

/// `MulDiv`: `a * b / c` rounded to nearest, halves away from zero; `i32`
/// saturated.
fn mul_div(a: i32, b: u64, c: u64) -> i32 {
    let n = u128::from(a.unsigned_abs()) * u128::from(b) + u128::from(c / 2);
    let q = (n / u128::from(c)).min(i32::MAX as u128) as i32;
    if a < 0 {
        -q
    } else {
        q
    }
}

/// How the frame is chosen: the state `AviBgOverlayRefresh` reads.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PlaybackState {
    /// `PlaybackActive() != 0`.
    pub playback_active: bool,
    /// `FrameStepPlayback() != 0`.
    pub frame_step: bool,
    /// `state.currentFrame`.
    pub current_frame: i32,
    /// `state.aviRecordFps`; the sequential branch needs [`FRAME_SCALE`].
    pub record_fps: f32,
    /// `state.playbackCursorSeconds`.
    pub cursor_seconds: f32,
    /// `state.a0B10`: added to the wall-clock sample. The C++ never writes
    /// it (zero in both originals) and the PMM format has no field for it.
    pub bias: i32,
    /// `state.aviBackgroundSample`: the sequential branch reads it and adds 1.
    pub sequential_sample: i32,
}

impl MovieInfo {
    /// `AVIStreamSampleToTime`: milliseconds of a sample (not offset by
    /// `start`). avifil32's rounding is not in any C++ line; this is
    /// `MulDiv` rounding, unverified against Windows. The thirty-fps flag
    /// holds for truncation as well.
    pub fn sample_to_time(&self, sample: i32) -> i32 {
        mul_div(sample, 1000 * u64::from(self.scale), u64::from(self.rate))
    }

    /// `AVIStreamTimeToSample`: the sample at a time in milliseconds (same
    /// rounding caveat as [`sample_to_time`](Self::sample_to_time)).
    pub fn time_to_sample(&self, ms: i32) -> i32 {
        mul_div(ms, u64::from(self.rate), 1000 * u64::from(self.scale))
    }

    /// The sample `AviBgOverlayRefresh` asks for (0x416A83..0x416B27),
    /// clamped to `start..=end - 1`. Updates `sequential_sample` in the
    /// branch that advances it.
    pub fn select_sample(&self, st: &mut PlaybackState) -> i32 {
        let thirty = self.uses_thirty_fps_timing;
        let mut sample = if !st.playback_active {
            if !thirty {
                self.time_to_sample(st.current_frame.wrapping_mul(1000) / 30)
            } else {
                st.current_frame
            }
        } else if !st.frame_step || !thirty || st.record_fps != FRAME_SCALE {
            let t = (f64::from(st.cursor_seconds) * 1000.0) as i32;
            self.time_to_sample(t).wrapping_add(st.bias)
        } else {
            let s = st.sequential_sample;
            st.sequential_sample = s.wrapping_add(1);
            s
        };
        if sample < self.start {
            sample = self.start;
        }
        sample.min(self.end.wrapping_sub(1))
    }
}

impl<R: Read + Seek> Movie<R> {
    /// `LoadAviFile` after the path is resolved: opens, checks, selects the
    /// stream and decodes frame 0 as the C++ does for the header.
    pub fn open(mut src: R) -> Result<Self, MovieError> {
        let (v, frames) = scan(&mut src)?;
        let start = v.start as i32;
        let length = i32::try_from(frames.len()).map_err(|_| MovieError::Frame)?;
        let frame_ms = mul_div(1, 1000 * u64::from(v.scale), u64::from(v.rate));
        let mut movie = Movie {
            src,
            info: MovieInfo {
                width: v.width,
                height: v.height,
                start,
                end: start.wrapping_add(length),
                uses_thirty_fps_timing: frame_ms > 0x20 && frame_ms < 0x22,
                rate: v.rate,
                scale: v.scale,
            },
            codec: v.codec,
            frames,
        };
        movie.frame(start)?;
        Ok(movie)
    }

    pub fn info(&self) -> &MovieInfo {
        &self.info
    }

    /// `AVIStreamGetFrame(reader, sample)`. A zero-length chunk is a dropped
    /// frame: the previous frame shows again.
    pub fn frame(&mut self, sample: i32) -> Result<Frame, MovieError> {
        if sample < self.info.start || sample >= self.info.end {
            return Err(MovieError::Frame);
        }
        let at = (sample - self.info.start) as usize;
        let loc = self.frames[..=at]
            .iter()
            .rev()
            .find(|l| l.len > 0)
            .ok_or(MovieError::Frame)?;
        let mut data = vec![0u8; loc.len as usize];
        self.src
            .seek(SeekFrom::Start(loc.offset))
            .and_then(|_| self.src.read_exact(&mut data))
            .map_err(|_| MovieError::Frame)?;
        let (w, h) = (self.info.width as u32, self.info.height as u32);
        let rgba = match self.codec {
            Codec::Raw { bpp, bottom_up } => {
                let h = self.info.height * if bottom_up { 1 } else { -1 };
                rgba_from_dib(w, h, bpp, &data)
            }
            Codec::Mjpeg => decode_jpeg(&data, w, h),
        };
        Ok(Frame {
            width: w,
            height: h,
            rgba: rgba.ok_or(MovieError::Frame)?,
        })
    }
}

/// One Motion JPEG frame. The size must be the stream's, as it is for the
/// DIB the C++ gets from the decompressor.
fn decode_jpeg(data: &[u8], width: u32, height: u32) -> Option<Vec<u8>> {
    let pic = jpeg_rgba(data)?;
    (pic.width == width && pic.height == height).then_some(pic.rgba)
}
