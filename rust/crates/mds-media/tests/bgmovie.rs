//! The background movie and picture against committed ffmpeg decodes.
//!
//! Fixtures are under `tests/fixtures/bgmovie`, made by
//! `tests/gen/make_bgmovie_fixtures.sh <output-dir>` (ffmpeg 8.1). The
//! expected values are `ffmpeg -f framemd5` of the same files (exact
//! comparison) and, for JPEG, the raw RGB24 ffmpeg decodes (tolerance). No
//! ffmpeg is needed to run the tests.

use mds_media::avi::{AviWriter, Config};
use mds_media::background::{
    media_aspect, MovieBackground, PictureBackground, Viewport, DIR_SLOT_CHARS, PATH_SLOT_CHARS,
};
use mds_media::movie::{Frame, Movie, MovieError, PlaybackState};
use mds_media::picture::{self, PictureError};
use std::io::Cursor;
use std::path::{Path, PathBuf};

mod common;
use common::md5;

fn fixture(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures/bgmovie")
        .join(name)
}

fn read(name: &str) -> Vec<u8> {
    std::fs::read(fixture(name)).unwrap_or_else(|e| panic!("{name}: {e}"))
}

/// The hash column of a `framemd5` file.
fn framemd5(name: &str) -> Vec<String> {
    String::from_utf8(read(name))
        .unwrap()
        .lines()
        .filter(|l| !l.starts_with('#'))
        .map(|l| l.rsplit(',').next().unwrap().trim().to_owned())
        .collect()
}

fn rgb(rgba: &[u8]) -> Vec<u8> {
    rgba.chunks_exact(4)
        .flat_map(|p| [p[0], p[1], p[2]])
        .collect()
}

fn all_frames(name: &str) -> (Movie<Cursor<Vec<u8>>>, Vec<Frame>) {
    let mut movie = Movie::open(Cursor::new(read(name))).unwrap();
    let (start, end) = (movie.info().start, movie.info().end);
    let frames = (start..end).map(|s| movie.frame(s).unwrap()).collect();
    (movie, frames)
}

fn assert_matches_framemd5(avi: &str, md5s: &str) {
    let (movie, frames) = all_frames(avi);
    assert_eq!((movie.info().width, movie.info().height), (32, 24));
    let want = framemd5(md5s);
    assert_eq!(frames.len(), want.len());
    for (i, (f, w)) in frames.iter().zip(&want).enumerate() {
        assert!(
            f.rgba.chunks_exact(4).all(|p| p[3] == 255),
            "frame {i} alpha"
        );
        assert_eq!(&md5(&rgb(&f.rgba)), w, "{avi} frame {i}");
    }
}

/// The largest channel difference between two RGB24 buffers.
fn max_diff(a: &[u8], b: &[u8]) -> u8 {
    assert_eq!(a.len(), b.len());
    a.iter().zip(b).map(|(x, y)| x.abs_diff(*y)).max().unwrap()
}

/// zune-jpeg and ffmpeg's mjpeg decoder both read the same bits; they differ
/// in the IDCT rounding and the chroma upsampling, which the JPEG standard
/// leaves open (zune-jpeg's README states bit-identity with other decoders is
/// a non-goal). The worst channel difference on the fixtures is 3 on aarch64;
/// the bound leaves room for the x86 SIMD colour conversion.
const JPEG_MAX_DIFF: u8 = 6;

#[test]
fn uncompressed_24_bit_top_down_equals_ffmpeg() {
    assert_matches_framemd5("raw24_topdown.avi", "raw24_topdown.framemd5");
}

#[test]
fn uncompressed_24_bit_bottom_up_equals_ffmpeg() {
    assert_matches_framemd5("raw24_bottomup.avi", "raw24_bottomup.framemd5");
}

#[test]
fn uncompressed_32_bit_equals_ffmpeg_and_is_opaque() {
    assert_matches_framemd5("raw32_topdown.avi", "raw32_topdown.framemd5");
}

#[test]
fn motion_jpeg_is_within_the_decoder_difference() {
    let (movie, frames) = all_frames("mjpeg.avi");
    assert_eq!((movie.info().width, movie.info().height), (32, 24));
    let want = read("mjpeg.rgb24");
    assert_eq!(want.len(), frames.len() * 32 * 24 * 3);
    let worst = frames
        .iter()
        .zip(want.chunks_exact(32 * 24 * 3))
        .map(|(f, w)| max_diff(&rgb(&f.rgba), w))
        .max()
        .unwrap();
    println!("MJPEG max channel difference to ffmpeg: {worst}");
    assert!(worst <= JPEG_MAX_DIFF, "worst channel difference {worst}");
}

#[test]
fn other_codecs_are_unsupported() {
    for (file, fourcc) in [("mpeg4.avi", "FMP4"), ("h264.avi", "H264")] {
        let err = Movie::open(Cursor::new(read(file))).err().unwrap();
        assert_eq!(err, MovieError::Unsupported(fourcc.into()), "{file}");
        let text = err.message(true);
        assert!(
            text.contains(fourcc) && text.contains("Motion JPEG"),
            "{text}"
        );
        assert!(err.message(false).contains(fourcc));
    }
}

/// An AVI 1.0 file built by hand, to reach what ffmpeg will not write.
#[derive(Clone)]
struct Stream {
    kind: &'static [u8; 4],
    priority: u16,
    scale: u32,
    rate: u32,
    start: u32,
    /// `strf` body.
    format: Vec<u8>,
    /// Data chunks as `(two-letter suffix, body)`.
    chunks: Vec<(&'static str, Vec<u8>)>,
}

fn chunk(id: &[u8], body: &[u8]) -> Vec<u8> {
    let mut v = id.to_vec();
    v.extend((body.len() as u32).to_le_bytes());
    v.extend(body);
    if body.len() % 2 == 1 {
        v.push(0);
    }
    v
}

fn list(kind: &[u8; 4], body: &[u8]) -> Vec<u8> {
    chunk(b"LIST", &[kind.as_slice(), body].concat())
}

fn bih(width: i32, height: i32, bpp: u16, comp: u32) -> Vec<u8> {
    let mut v = 40u32.to_le_bytes().to_vec();
    v.extend(width.to_le_bytes());
    v.extend(height.to_le_bytes());
    v.extend(1u16.to_le_bytes());
    v.extend(bpp.to_le_bytes());
    v.extend(comp.to_le_bytes());
    v.extend([0u8; 20]);
    v
}

fn video(priority: u16, rate: u32, start: u32, format: Vec<u8>, frames: Vec<Vec<u8>>) -> Stream {
    Stream {
        kind: b"vids",
        priority,
        scale: 1,
        rate,
        start,
        format,
        chunks: frames.into_iter().map(|f| ("db", f)).collect(),
    }
}

fn avi(streams: &[Stream], declared: u32) -> Vec<u8> {
    let mut avih = vec![0u8; 56];
    avih[24..28].copy_from_slice(&declared.to_le_bytes());
    let mut hdrl = chunk(b"avih", &avih);
    for s in streams {
        let mut strh = s.kind.to_vec();
        strh.extend([0u8; 4]);
        strh.extend([0u8; 4]);
        strh.extend(s.priority.to_le_bytes());
        strh.extend([0u8; 2 + 4]);
        for v in [s.scale, s.rate, s.start, s.chunks.len() as u32] {
            strh.extend(v.to_le_bytes());
        }
        strh.resize(56, 0);
        let strl = [chunk(b"strh", &strh), chunk(b"strf", &s.format)].concat();
        hdrl.extend(list(b"strl", &strl));
    }
    let mut movi = Vec::new();
    for (i, s) in streams.iter().enumerate() {
        for (suffix, body) in &s.chunks {
            movi.extend(chunk(format!("{i:02}{suffix}").as_bytes(), body));
        }
    }
    let body = [
        b"AVI ".as_slice(),
        &list(b"hdrl", &hdrl),
        &chunk(b"JUNK", b"pad"),
        &list(b"movi", &movi),
    ]
    .concat();
    chunk(b"RIFF", &body)
}

/// `w x h` 24-bit pixels with a distinct colour per pixel, as stored rows.
fn solid(w: usize, h: usize, bpp: usize, seed: u8, bottom_up: bool) -> (Vec<u8>, Vec<u8>) {
    let stride = (w * bpp / 8 + 3) & !3;
    let mut stored = vec![0xEEu8; stride * h];
    let mut rgba = Vec::new();
    for y in 0..h {
        for x in 0..w {
            let (r, g, b) = (seed.wrapping_add(x as u8), (y * 7) as u8, (x * 3 + y) as u8);
            let row = if bottom_up { h - 1 - y } else { y };
            let at = row * stride + x * bpp / 8;
            stored[at..at + 3].copy_from_slice(&[b, g, r]);
            if bpp == 32 {
                stored[at + 3] = 0x40; // never read
            }
            rgba.extend([r, g, b, 255]);
        }
    }
    (stored, rgba)
}

fn open(file: Vec<u8>) -> Result<Movie<Cursor<Vec<u8>>>, MovieError> {
    Movie::open(Cursor::new(file))
}

#[test]
fn padded_rows_both_depths_and_both_directions() {
    for (bpp, bottom_up) in [(24, true), (24, false), (32, true), (32, false)] {
        let (stored, want) = solid(5, 3, bpp, 10, bottom_up);
        let h = if bottom_up { 3 } else { -3 };
        let s = video(0, 30, 0, bih(5, h, bpp as u16, 0), vec![stored]);
        let mut m = open(avi(&[s], 1)).unwrap();
        let f = m.frame(0).unwrap();
        assert_eq!((f.width, f.height), (5, 3));
        assert_eq!(f.rgba, want, "{bpp} bit bottom_up={bottom_up}");
        assert_eq!(m.info().height, 3);
    }
}

#[test]
fn avi_writer_output_reads_back_exactly() {
    let (w, h) = (7usize, 4usize);
    let frames: Vec<Vec<u8>> = (0..3u8)
        .map(|n| {
            (0..w * h * 3)
                .map(|i| (i as u8).wrapping_mul(5).wrapping_add(n))
                .collect()
        })
        .collect();
    let mut out = Cursor::new(Vec::new());
    let mut writer = AviWriter::new(
        &mut out,
        Config {
            width: w as u32,
            height: h as u32,
            fps_num: 30,
            fps_den: 1,
            audio: None,
        },
    )
    .unwrap();
    for f in &frames {
        writer.write_frame(f).unwrap();
    }
    writer.finish().unwrap();
    let mut m = Movie::open(out).unwrap();
    assert_eq!((m.info().start, m.info().end), (0, 3));
    for (i, bgr) in frames.iter().enumerate() {
        let want: Vec<u8> = bgr
            .chunks_exact(3)
            .flat_map(|p| [p[2], p[1], p[0], 255])
            .collect();
        assert_eq!(m.frame(i as i32).unwrap().rgba, want);
    }
}

#[test]
fn lowest_priority_video_stream_wins_and_ties_keep_the_first() {
    let (a, ra) = solid(4, 2, 24, 1, true);
    let (b, rb) = solid(4, 2, 24, 50, true);
    let (c, _) = solid(4, 2, 24, 90, true);
    let audio = Stream {
        kind: b"auds",
        priority: 0,
        scale: 1,
        rate: 8000,
        start: 0,
        format: vec![0; 16],
        chunks: vec![("wb", vec![0; 8])],
    };
    let mk = |streams: Vec<Stream>| {
        let n = streams.len() as u32;
        open(avi(&streams, n)).unwrap().frame(0).unwrap().rgba
    };
    let fmt = || bih(4, 2, 24, 0);
    let first = video(5, 30, 0, fmt(), vec![a.clone()]);
    let lower = video(2, 30, 0, fmt(), vec![b]);
    assert_eq!(mk(vec![audio.clone(), first, lower]), rb);
    let first = video(3, 30, 0, fmt(), vec![a]);
    let tie = video(3, 30, 0, fmt(), vec![c]);
    assert_eq!(mk(vec![first, tie]), ra);
}

#[test]
fn a_dropped_frame_shows_the_previous_one() {
    let (f0, r0) = solid(4, 2, 24, 3, true);
    let s = video(0, 30, 0, bih(4, 2, 24, 0), vec![f0, vec![]]);
    let mut m = open(avi(&[s], 1)).unwrap();
    assert_eq!(m.frame(1).unwrap().rgba, r0);
    let s = video(0, 30, 0, bih(4, 2, 24, 0), vec![vec![]]);
    assert_eq!(open(avi(&[s], 1)).err(), Some(MovieError::Frame));
}

#[test]
fn load_failures_map_to_the_c_plus_plus_sites() {
    let (f, _) = solid(4, 2, 24, 1, true);
    let good = || video(0, 30, 0, bih(4, 2, 24, 0), vec![f.clone()]);
    let err = |streams: &[Stream], declared| open(avi(streams, declared)).err();

    assert_eq!(
        open(b"RIFF\0\0\0\0WAVEfmt ".to_vec()).err(),
        Some(MovieError::Open)
    );
    assert_eq!(open(Vec::new()).err(), Some(MovieError::Open));
    assert_eq!(err(&[good()], 2), Some(MovieError::GetStream));
    let mut zero_rate = good();
    zero_rate.rate = 0;
    assert_eq!(err(&[zero_rate], 1), Some(MovieError::StreamInfo));
    let audio_only = Stream {
        kind: b"auds",
        priority: 0,
        scale: 1,
        rate: 8000,
        start: 0,
        format: vec![0; 16],
        chunks: vec![],
    };
    assert_eq!(err(&[audio_only], 1), Some(MovieError::NoVideoStream));
    assert_eq!(err(&[], 0), Some(MovieError::NoVideoStream));
    // 8-bit and BI_BITFIELDS BI_RGB cannot be decoded here.
    for (bpp, comp, what) in [(8, 0, "8-bit uncompressed"), (32, 3, "BI_BITFIELDS")] {
        let s = video(0, 30, 0, bih(4, 2, bpp, comp), vec![f.clone()]);
        assert_eq!(err(&[s], 1), Some(MovieError::Unsupported(what.into())));
    }
    // A file with no avih has no AVIFILEINFO.
    let mut no_avih = avi(&[good()], 1);
    no_avih[24..28].copy_from_slice(b"JUNK");
    assert_eq!(open(no_avih).err(), Some(MovieError::Info));
}

#[test]
fn error_texts_are_the_c_plus_plus_ones() {
    let texts = [
        (
            MovieError::Open,
            "Cannot open AVI file!!",
            "AVIファイルが読み込めません",
        ),
        (
            MovieError::Info,
            "Cannot read AVIFILEINFO!!",
            "AVIFILEINFOを読み込めません",
        ),
        (
            MovieError::GetStream,
            "Failed AVIFileGetStream",
            "AVIFileGetStream失敗",
        ),
        (
            MovieError::StreamInfo,
            "Failed AVIStreamInfo",
            "AVIStreamInfo失敗",
        ),
        (
            MovieError::NoVideoStream,
            "Cannot open AVI file",
            "AVIファイルを読み込めません",
        ),
        (
            MovieError::Frame,
            "Cannot open AVI file",
            "AVIファイルを読み込めません",
        ),
    ];
    for (e, en, jp) in texts {
        assert_eq!(
            (e.message(true), e.message(false)),
            (en.to_owned(), jp.to_owned())
        );
        assert_eq!(
            (e.caption(true), e.caption(false)),
            ("open AVI file", "AVIデータ読込")
        );
    }
    assert_eq!(PictureError::Open.message(true), "Cannot open BMP file");
    assert_eq!(
        PictureError::Open.message(false),
        "BMPファイルを読み込めませんでした"
    );
    assert_eq!(PictureError::Open.caption(true), "open BMP file");
    assert_eq!(PictureError::Open.caption(false), "BMPファイル読込");
}

/// A movie of `frames` empty-ish frames at `scale/rate` starting at `start`,
/// for the time rule only.
fn timed(rate: u32, scale: u32, start: u32, frames: usize) -> Movie<Cursor<Vec<u8>>> {
    let (f, _) = solid(2, 2, 24, 0, true);
    let mut s = video(0, rate, start, bih(2, 2, 24, 0), vec![f; frames]);
    s.scale = scale;
    open(avi(&[s], 1)).unwrap()
}

#[test]
fn thirty_fps_timing_flag_is_a_33_ms_frame() {
    for (rate, scale, want) in [
        (30, 1, true),
        (30000, 1001, true),
        (25, 1, false),
        (60, 1, false),
        (24, 1, false),
    ] {
        assert_eq!(
            timed(rate, scale, 0, 2).info().uses_thirty_fps_timing,
            want,
            "{rate}/{scale}"
        );
    }
    let m = timed(25, 1, 0, 2);
    assert_eq!(
        (m.info().sample_to_time(1), m.info().sample_to_time(25)),
        (40, 1000)
    );
}

fn state() -> PlaybackState {
    PlaybackState {
        playback_active: false,
        frame_step: false,
        current_frame: 0,
        record_fps: 30.0,
        cursor_seconds: 0.0,
        bias: 0,
        sequential_sample: 0,
    }
}

#[test]
fn stopped_movie_picks_the_sample_from_the_scene_frame() {
    // 0x416B27: 30 fps movie takes the frame number, others convert
    // `frame * 1000 / 30` milliseconds.
    let thirty = timed(30, 1, 0, 100);
    let mut st = PlaybackState {
        current_frame: 42,
        ..state()
    };
    assert_eq!(thirty.info().select_sample(&mut st), 42);
    let slow = timed(24, 1, 0, 100); // frame 30 is 1000 ms is sample 24
    let mut st = PlaybackState {
        current_frame: 30,
        ..state()
    };
    assert_eq!(slow.info().select_sample(&mut st), 24);
    let mut st = PlaybackState {
        current_frame: 15,
        ..state()
    }; // 500 ms
    assert_eq!(slow.info().select_sample(&mut st), 12);
}

#[test]
fn playing_movie_follows_the_clock_or_counts_frames() {
    let m = timed(30, 1, 0, 100);
    // 0x416ADE: seconds * 1000 as LONG, to a sample, plus the bias.
    let mut st = PlaybackState {
        playback_active: true,
        cursor_seconds: 0.5,
        bias: 2,
        ..state()
    };
    assert_eq!(m.info().select_sample(&mut st), 15 + 2);
    // frame step at 30 fps records frame by frame: the counter, then +1.
    let mut st = PlaybackState {
        playback_active: true,
        frame_step: true,
        sequential_sample: 9,
        cursor_seconds: 3.0,
        bias: 5,
        ..state()
    };
    assert_eq!(m.info().select_sample(&mut st), 9);
    assert_eq!(st.sequential_sample, 10);
    // another record rate, or a non-30 fps movie, falls back to the clock.
    let mut st = PlaybackState {
        record_fps: 24.0,
        ..st
    };
    assert_eq!(m.info().select_sample(&mut st), 90 + 5);
    assert_eq!(st.sequential_sample, 10);
    let slow = timed(24, 1, 0, 100);
    let mut st = PlaybackState {
        playback_active: true,
        frame_step: true,
        cursor_seconds: 1.0,
        ..state()
    };
    assert_eq!(slow.info().select_sample(&mut st), 24);
}

#[test]
fn selected_sample_stays_inside_the_stream() {
    let m = timed(30, 1, 10, 5); // samples 10..=14
    assert_eq!((m.info().start, m.info().end), (10, 15));
    for (frame, want) in [(-4, 10), (3, 10), (12, 12), (14, 14), (99, 14)] {
        let mut st = PlaybackState {
            current_frame: frame,
            ..state()
        };
        assert_eq!(m.info().select_sample(&mut st), want, "frame {frame}");
    }
    let mut m = m;
    assert!(m.frame(9).is_err() && m.frame(15).is_err());
    assert!(m.frame(10).is_ok() && m.frame(14).is_ok());
}

fn vp(l: i32, r: i32, t: i32, b: i32, scale: f32) -> Viewport {
    Viewport {
        hide_left: l,
        hide_right: r,
        hide_top: t,
        hide_bottom: b,
        view_scale: scale,
    }
}

#[test]
fn media_aspect_follows_the_c_plus_plus_float_steps() {
    // Expected values come from running the written steps of MediaAspect in
    // numpy float32: zoom = ((w / ratio) * 1.2f) / mediaW,
    // pos = (int)(h2 - ((mediaH * zoom * ratio) / 1.2f) * 0.5f).
    for (v, w, h, scale, pos) in [
        (vp(800, 0, 0, 600, 1.0), 640, 480, 1.5000001_f32, 0),
        (vp(800, 0, 0, 600, 1.0), 640, 960, 1.5000001, -300),
        (vp(800, 0, 0, 600, 1.0), 1000, 100, 0.96000004, 260),
        (vp(1280, 0, 0, 720, 2.0), 640, 360, 1.2, 0),
        (vp(1000, 200, 50, 651, 1.5), 320, 240, 2.0, 0),
    ] {
        assert_eq!(media_aspect(&v, w, h), (scale, pos), "{v:?} {w}x{h}");
    }
}

#[test]
fn slot_sizes_are_the_wcscpy_s_counts() {
    assert_eq!((PATH_SLOT_CHARS, DIR_SLOT_CHARS), (0x100, 0x3E8));
}

#[test]
fn movie_slot_follows_the_load_and_fail_tails() {
    let view = vp(800, 0, 0, 600, 1.0);
    let mut slot = MovieBackground::default();
    let path = fixture("raw24_topdown.avi");
    slot.load(&path, &view).unwrap();
    assert!(slot.enabled && slot.movie.is_some());
    assert_eq!(slot.path, path.to_string_lossy());
    assert_eq!(
        (slot.placement.offset_x, slot.placement.scale),
        (0, media_aspect(&view, 32, 24).0)
    );
    assert_eq!(slot.placement.offset_y, media_aspect(&view, 32, 24).1);

    let err = slot.load(&fixture("h264.avi"), &view).unwrap_err();
    assert!(matches!(err, MovieError::Unsupported(_)));
    assert!(!slot.enabled && slot.movie.is_none() && slot.path.is_empty());

    slot.load(&path, &view).unwrap();
    assert_eq!(
        slot.load(&fixture("missing.avi"), &view).unwrap_err(),
        MovieError::Open
    );
    assert!(!slot.enabled && slot.path.is_empty());

    slot.load(&path, &view).unwrap();
    slot.fail();
    assert!(!slot.enabled && slot.movie.is_none() && slot.path.is_empty());
}

fn solid_dib_file(bpp: usize) -> (Vec<u8>, Vec<u8>) {
    let (stored, want) = solid(5, 3, bpp, 20, true);
    let mut v = b"BM".to_vec();
    v.extend(((54 + stored.len()) as u32).to_le_bytes());
    v.extend([0u8; 4]);
    v.extend(54u32.to_le_bytes());
    v.extend(bih(5, 3, bpp as u16, 0));
    v.extend(stored);
    (v, want)
}

#[test]
fn bmp_decodes_both_depths() {
    for bpp in [24, 32] {
        let (file, want) = solid_dib_file(bpp);
        let pic = picture::decode(&file).unwrap();
        assert_eq!((pic.width, pic.height), (5, 3));
        assert_eq!(pic.rgba, want, "{bpp} bit");
    }
}

#[test]
fn bmp_png_and_jpeg_equal_ffmpeg() {
    let bmp = picture::decode(&read("picture.bmp")).unwrap();
    assert_eq!((bmp.width, bmp.height), (32, 24));
    assert_eq!(md5(&rgb(&bmp.rgba)), framemd5("picture.bmp.framemd5")[0]);
    let png = picture::decode(&read("picture.png")).unwrap();
    assert_eq!(md5(&rgb(&png.rgba)), framemd5("picture.png.framemd5")[0]);
    let alpha = picture::decode(&read("picture_alpha.png")).unwrap();
    assert_eq!(md5(&alpha.rgba), framemd5("picture_alpha.png.framemd5")[0]);
    assert!(alpha.rgba.chunks_exact(4).all(|p| p[3] == 128));
    let jpg = picture::decode(&read("picture.jpg")).unwrap();
    assert_eq!((jpg.width, jpg.height), (32, 24));
    let worst = max_diff(&rgb(&jpg.rgba), &read("picture.jpg.rgb24"));
    println!("JPEG max channel difference to ffmpeg: {worst}");
    assert!(worst <= JPEG_MAX_DIFF);
}

#[test]
fn picture_formats_d3dx_reads_but_this_port_does_not_are_unsupported() {
    let tga = picture::decode(&read("picture.tga")).unwrap_err();
    assert!(matches!(tga, PictureError::Unsupported(_)), "{tga:?}");
    assert_eq!(
        picture::decode(b"DDS \0\0\0\0").unwrap_err(),
        PictureError::Unsupported("DDS".into())
    );
    assert!(picture::decode(&read("picture.png")[..40]).unwrap_err() == PictureError::Open);
    assert!(picture::decode(&[]).unwrap_err() != PictureError::Open);
    assert!(PictureError::Unsupported("DDS".into())
        .message(true)
        .contains("DDS"));
}

#[test]
fn picture_slot_follows_the_c_plus_plus_tails() {
    let view = vp(800, 0, 0, 600, 1.0);
    let mut slot = PictureBackground::default();
    let path = fixture("picture.png");
    slot.load(&path, &view).unwrap();
    assert!(slot.enabled && slot.picture.is_some());
    assert_eq!(slot.path, path.to_string_lossy());
    assert_eq!(
        (slot.placement.scale, slot.placement.offset_y),
        media_aspect(&view, 32, 24)
    );

    // A missing file only clears the path (0x433842); the picture stays.
    assert_eq!(
        slot.load(&fixture("none.png"), &view).unwrap_err(),
        PictureError::Open
    );
    assert!(slot.path.is_empty() && slot.picture.is_some() && slot.enabled);

    // A decode failure drops the picture and clears the path; the flag stays.
    let bad = fixture("mjpeg.rgb24");
    assert!(slot.load(&bad, &view).is_err());
    assert!(slot.path.is_empty() && slot.picture.is_none() && slot.enabled);
}
