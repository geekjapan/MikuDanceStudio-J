//! Writes AVI files with known frames and audio, then decodes them with
//! `ffprobe` and `ffmpeg` and compares with what was written. A host without
//! `ffprobe` and `ffmpeg` prints SKIP, which is not a pass. The OpenDML
//! layout (RIFFs, standard and super indexes) is also checked in memory,
//! without either tool, by walking the bytes.

use mds_media::avi::{AudioFormat, AviWriter, Config, Error, SUPER_ENTRIES};
use mds_media::movie::Movie;
use std::io::{self, Cursor, Seek, SeekFrom, Write};
use std::path::PathBuf;
use std::process::Command;

mod common;
use common::md5;

struct Lcg(u32);
impl Lcg {
    fn bytes(&mut self, n: usize) -> Vec<u8> {
        (0..n)
            .map(|_| {
                self.0 = self.0.wrapping_mul(1103515245).wrapping_add(12345);
                (self.0 >> 16) as u8
            })
            .collect()
    }
}

fn have(tool: &str) -> bool {
    Command::new(tool)
        .arg("-version")
        .output()
        .is_ok_and(|o| o.status.success())
}

fn temp(name: &str) -> PathBuf {
    std::env::temp_dir().join(format!("mds-media-{}-{name}", std::process::id()))
}

/// `key=value` lines of `ffprobe -of flat`, quotes removed.
fn probe(path: &PathBuf) -> Vec<(String, String)> {
    let out = Command::new("ffprobe")
        .args([
            "-v",
            "error",
            "-count_frames",
            "-of",
            "flat",
            "-show_streams",
            "-show_format",
        ])
        .arg(path)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "ffprobe: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout)
        .unwrap()
        .lines()
        .filter_map(|l| l.split_once('='))
        .map(|(k, v)| (k.to_string(), v.trim_matches('"').to_string()))
        .collect()
}

fn get<'a>(p: &'a [(String, String)], key: &str) -> &'a str {
    p.iter()
        .find(|(k, _)| k == key)
        .unwrap_or_else(|| panic!("ffprobe has no {key}: {p:?}"))
        .1
        .as_str()
}

/// md5 of every decoded frame, as `ffmpeg -f framemd5` prints them.
fn frame_md5s(path: &PathBuf) -> Vec<String> {
    let out = Command::new("ffmpeg")
        .args(["-v", "error", "-i"])
        .arg(path)
        .args(["-map", "0:v:0", "-pix_fmt", "bgr24", "-f", "framemd5", "-"])
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "ffmpeg: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout)
        .unwrap()
        .lines()
        .filter(|l| !l.starts_with('#'))
        .map(|l| l.rsplit(',').next().unwrap().trim().to_string())
        .collect()
}

fn decoded_audio(path: &PathBuf) -> Vec<u8> {
    let out = Command::new("ffmpeg")
        .args(["-v", "error", "-i"])
        .arg(path)
        .args(["-map", "0:a:0", "-f", "s16le", "-"])
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "ffmpeg: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    out.stdout
}

#[test]
fn video_and_audio_decode_to_what_was_written() {
    if !have("ffprobe") || !have("ffmpeg") {
        eprintln!("SKIP: ffprobe or ffmpeg is not installed (not a pass)");
        return;
    }
    // Width 5 makes a 15-byte row, padded to 16 in the file.
    let (w, h, frames) = (5usize, 3usize, 4usize);
    let audio = AudioFormat {
        channels: 2,
        sample_rate: 24000,
        bits: 16,
    };
    let mut rng = Lcg(7);
    let video: Vec<Vec<u8>> = (0..frames).map(|_| rng.bytes(w * h * 3)).collect();
    // 24000 Hz at 30 fps: 800 blocks of 4 bytes per frame.
    let pcm: Vec<Vec<u8>> = (0..frames).map(|_| rng.bytes(800 * 4)).collect();

    let path = temp("av.avi");
    let mut avi = AviWriter::new(
        Cursor::new(Vec::new()),
        Config {
            width: w as u32,
            height: h as u32,
            fps_num: 30,
            fps_den: 1,
            audio: Some(audio),
        },
    )
    .unwrap();
    for (v, a) in video.iter().zip(&pcm) {
        avi.write_frame(v).unwrap();
        avi.write_audio(a).unwrap();
    }
    std::fs::write(&path, avi.finish().unwrap().into_inner()).unwrap();

    let p = probe(&path);
    assert_eq!(get(&p, "format.nb_streams"), "2");
    assert_eq!(get(&p, "streams.stream.0.codec_type"), "video");
    assert_eq!(get(&p, "streams.stream.0.codec_name"), "rawvideo");
    assert_eq!(get(&p, "streams.stream.0.pix_fmt"), "bgr24");
    assert_eq!(get(&p, "streams.stream.0.width"), "5");
    assert_eq!(get(&p, "streams.stream.0.height"), "3");
    assert_eq!(get(&p, "streams.stream.0.r_frame_rate"), "30/1");
    assert_eq!(get(&p, "streams.stream.0.nb_frames"), "4");
    assert_eq!(get(&p, "streams.stream.0.nb_read_frames"), "4");
    assert_eq!(get(&p, "streams.stream.1.codec_type"), "audio");
    assert_eq!(get(&p, "streams.stream.1.codec_name"), "pcm_s16le");
    assert_eq!(get(&p, "streams.stream.1.channels"), "2");
    assert_eq!(get(&p, "streams.stream.1.sample_rate"), "24000");

    let want: Vec<String> = video.iter().map(|f| md5(f)).collect();
    assert_eq!(frame_md5s(&path), want);
    assert_eq!(decoded_audio(&path), pcm.concat());
    std::fs::remove_file(&path).unwrap();
}

#[test]
fn video_only_ntsc_rate() {
    if !have("ffprobe") || !have("ffmpeg") {
        eprintln!("SKIP: ffprobe or ffmpeg is not installed (not a pass)");
        return;
    }
    let (w, h) = (16usize, 8usize);
    let mut rng = Lcg(99);
    let video: Vec<Vec<u8>> = (0..3).map(|_| rng.bytes(w * h * 3)).collect();
    let path = temp("v.avi");
    let mut avi = AviWriter::new(
        Cursor::new(Vec::new()),
        Config {
            width: w as u32,
            height: h as u32,
            fps_num: 30000,
            fps_den: 1001,
            audio: None,
        },
    )
    .unwrap();
    for v in &video {
        avi.write_frame(v).unwrap();
    }
    std::fs::write(&path, avi.finish().unwrap().into_inner()).unwrap();

    let p = probe(&path);
    assert_eq!(get(&p, "format.nb_streams"), "1");
    assert_eq!(get(&p, "streams.stream.0.r_frame_rate"), "30000/1001");
    assert_eq!(get(&p, "streams.stream.0.nb_read_frames"), "3");
    let want: Vec<String> = video.iter().map(|f| md5(f)).collect();
    assert_eq!(frame_md5s(&path), want);
    std::fs::remove_file(&path).unwrap();
}

/// Counts bytes written and keeps none, to reach the size limits cheaply.
struct Counter {
    pos: u64,
}
impl Write for Counter {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        self.pos += buf.len() as u64;
        Ok(buf.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
impl Seek for Counter {
    fn seek(&mut self, to: SeekFrom) -> io::Result<u64> {
        if let SeekFrom::Start(p) = to {
            self.pos = p;
        }
        Ok(self.pos)
    }
}

#[test]
fn the_super_index_capacity_ends_the_file() {
    let (w, h) = (100usize, 100usize);
    let frame = vec![0u8; w * h * 3];
    let mut avi = AviWriter::with_riff_limit(
        Counter { pos: 0 },
        Config {
            width: w as u32,
            height: h as u32,
            fps_num: 30,
            fps_den: 1,
            audio: None,
        },
        64 * 1024,
    )
    .unwrap();
    let mut written = 0usize;
    let err = loop {
        match avi.write_frame(&frame) {
            Ok(()) => written += 1,
            Err(e) => break e,
        }
    };
    assert!(matches!(err, Error::TooLarge));
    assert!(written >= SUPER_ENTRIES, "{written} frames");
}

#[test]
fn a_frame_larger_than_half_a_riff_is_refused() {
    let cfg = Config {
        width: 100,
        height: 100,
        fps_num: 30,
        fps_den: 1,
        audio: None,
    };
    assert!(matches!(
        AviWriter::with_riff_limit(Counter { pos: 0 }, cfg, 40_000),
        Err(Error::Param(_))
    ));
    assert!(matches!(
        AviWriter::with_riff_limit(Counter { pos: 0 }, cfg, (1 << 30) + 1),
        Err(Error::Param(_))
    ));
}

const SMALL_LIMIT: u64 = 96 * 1024;

struct Written {
    file: Vec<u8>,
    video: Vec<Vec<u8>>,
    pcm: Vec<Vec<u8>>,
}

/// `frames` frames of `w` x `h` with `pcm_len`-byte audio chunks, in RIFFs of
/// at most `limit` bytes.
fn write_av(
    limit: u64,
    (w, h): (usize, usize),
    frames: usize,
    audio: Option<(AudioFormat, usize)>,
) -> Written {
    let mut rng = Lcg(31);
    let mut avi = AviWriter::with_riff_limit(
        Cursor::new(Vec::new()),
        Config {
            width: w as u32,
            height: h as u32,
            fps_num: 30,
            fps_den: 1,
            audio: audio.map(|a| a.0),
        },
        limit,
    )
    .unwrap();
    let (mut video, mut pcm) = (Vec::new(), Vec::new());
    for n in 0..frames {
        let f = rng.bytes(w * h * 3);
        avi.write_frame(&f).unwrap();
        video.push(f);
        if let Some((fmt, len)) = audio {
            // Lengths vary so chunks end on odd and even offsets.
            let a = rng.bytes(len + n % 3 * fmt.block_align() as usize);
            avi.write_audio(&a).unwrap();
            pcm.push(a);
        }
    }
    Written {
        file: avi.finish().unwrap().into_inner(),
        video,
        pcm,
    }
}

type Chunk = ([u8; 4], usize, usize);

/// The chunks of `b[pos..end]`: id, position of the header, body size.
fn kids(b: &[u8], mut pos: usize, end: usize) -> Vec<Chunk> {
    let mut out = Vec::new();
    while pos + 8 <= end {
        let size = u32::from_le_bytes(b[pos + 4..pos + 8].try_into().unwrap()) as usize;
        out.push((b[pos..pos + 4].try_into().unwrap(), pos, size));
        pos += 8 + size + (size & 1);
    }
    assert_eq!(pos, end, "chunks do not end at the end of their list");
    out
}

fn u32_at(b: &[u8], at: usize) -> u32 {
    u32::from_le_bytes(b[at..at + 4].try_into().unwrap())
}

fn u64_at(b: &[u8], at: usize) -> u64 {
    u64::from_le_bytes(b[at..at + 8].try_into().unwrap())
}

struct Layout {
    riffs: usize,
    /// Payload bytes of the data chunks of each stream, in file order.
    data: [Vec<Vec<u8>>; 2],
    /// File position of the `idx1` chunk.
    idx1: usize,
}

/// Checks the OpenDML structure of `b` against its own chunks: RIFF forms and
/// sizes, every `ix` entry, the `idx1` of the first RIFF, the super index
/// and the frame counts.
fn check_layout(b: &[u8], limit: u64, block: Option<u32>) -> Layout {
    let riffs = kids(b, 0, b.len());
    let mut data: [Vec<Vec<u8>>; 2] = [Vec::new(), Vec::new()];
    // Per stream, per RIFF with chunks of it: (ix position, ix body size,
    // chunks, ticks).
    let mut ixs: [Vec<(usize, usize, usize, u32)>; 2] = [Vec::new(), Vec::new()];
    let mut hdrl = None;
    let mut idx1 = None;
    for (k, &(id, pos, size)) in riffs.iter().enumerate() {
        assert_eq!(&id, b"RIFF");
        assert_eq!(
            &b[pos + 8..pos + 12],
            if k == 0 { b"AVI " } else { b"AVIX" }
        );
        assert!(8 + size as u64 <= limit, "RIFF {k} is {} bytes", 8 + size);
        let top = kids(b, pos + 12, pos + 8 + size);
        let movi = top
            .iter()
            .find(|c| &c.0 == b"LIST" && &b[c.1 + 8..c.1 + 12] == b"movi")
            .unwrap_or_else(|| panic!("RIFF {k} has no movi"));
        if k == 0 {
            hdrl = top
                .iter()
                .find(|c| &c.0 == b"LIST" && &b[c.1 + 8..c.1 + 12] == b"hdrl")
                .copied();
            idx1 = top.iter().find(|c| &c.0 == b"idx1").copied();
            assert_eq!(top.last().unwrap().0, *b"idx1");
        } else {
            assert_eq!(top.len(), 1, "an AVIX holds only its movi");
        }
        let in_movi = kids(b, movi.1 + 12, movi.1 + 8 + movi.2);
        for s in 0..2 {
            let id = [b"00db", b"01wb"][s];
            let mine: Vec<_> = in_movi.iter().filter(|c| &c.0 == id).collect();
            let ix: Vec<_> = in_movi
                .iter()
                .filter(|c| c.0 == [b'i', b'x', b'0', b'0' + s as u8][..])
                .collect();
            if mine.is_empty() {
                assert!(ix.is_empty());
                continue;
            }
            assert_eq!(ix.len(), 1);
            let ix = ix[0];
            assert_eq!(in_movi.last().unwrap().0[..2], *b"ix", "ix closes the movi");
            let body = ix.1 + 8;
            assert_eq!(&b[body..body + 4], &[2, 0, 0, 1], "longs, sub type, type");
            assert_eq!(u32_at(b, body + 4) as usize, mine.len());
            assert_eq!(&b[body + 8..body + 12], id);
            assert_eq!(u64_at(b, body + 12), movi.1 as u64, "base is the movi LIST");
            let mut ticks = 0;
            for (i, c) in mine.iter().enumerate() {
                let (off, sz) = (u32_at(b, body + 24 + 8 * i), u32_at(b, body + 28 + 8 * i));
                assert_eq!(movi.1 as u64 + u64::from(off) - 8, c.1 as u64);
                assert_eq!(sz as usize, c.2);
                ticks += if s == 0 { 1 } else { sz / block.unwrap() };
                data[s].push(b[c.1 + 8..c.1 + 8 + c.2].to_vec());
            }
            ixs[s].push((ix.1, ix.2, mine.len(), ticks));
        }
    }

    let idx1 = idx1.expect("no idx1");
    let first_movi = kids(b, riffs[0].1 + 12, riffs[0].1 + 8 + riffs[0].2)
        .into_iter()
        .find(|c| &c.0 == b"LIST" && &b[c.1 + 8..c.1 + 12] == b"movi")
        .unwrap();
    let in_first: Vec<_> = kids(b, first_movi.1 + 12, first_movi.1 + 8 + first_movi.2)
        .into_iter()
        .filter(|c| c.0[..2] != *b"ix")
        .collect();
    assert_eq!(idx1.2, 16 * in_first.len());
    for (i, c) in in_first.iter().enumerate() {
        let e = idx1.1 + 8 + 16 * i;
        assert_eq!(&b[e..e + 4], &c.0);
        assert_eq!(u32_at(b, e + 4), 0x10);
        assert_eq!(
            u64::from(u32_at(b, e + 8)),
            (c.1 - (first_movi.1 + 8)) as u64
        );
        assert_eq!(u32_at(b, e + 12) as usize, c.2);
    }

    let hdrl = hdrl.expect("no hdrl");
    let parts = kids(b, hdrl.1 + 12, hdrl.1 + 8 + hdrl.2);
    let total = data[0].len() as u32;
    let avih = parts.iter().find(|c| &c.0 == b"avih").unwrap();
    assert_eq!(u32_at(b, avih.1 + 8 + 16), total);
    let odml = parts
        .iter()
        .find(|c| &c.0 == b"LIST" && &b[c.1 + 8..c.1 + 12] == b"odml")
        .unwrap();
    let dmlh = kids(b, odml.1 + 12, odml.1 + 8 + odml.2);
    assert_eq!((&dmlh[0].0, dmlh[0].2), (b"dmlh", 248));
    assert_eq!(u32_at(b, dmlh[0].1 + 8), total);
    let strls: Vec<_> = parts
        .iter()
        .filter(|c| &c.0 == b"LIST" && &b[c.1 + 8..c.1 + 12] == b"strl")
        .collect();
    assert_eq!(strls.len(), 1 + usize::from(block.is_some()));
    for (s, strl) in strls.iter().enumerate() {
        let kids = kids(b, strl.1 + 12, strl.1 + 8 + strl.2);
        let strh = kids.iter().find(|c| &c.0 == b"strh").unwrap();
        assert_eq!(
            u32_at(b, strh.1 + 8 + 32) as usize,
            if s == 0 {
                data[0].len()
            } else {
                data[1].iter().map(|d| d.len()).sum::<usize>() / block.unwrap() as usize
            }
        );
        let indx = kids.iter().find(|c| &c.0 == b"indx").unwrap();
        assert_eq!(indx.2, 24 + 16 * SUPER_ENTRIES);
        let body = indx.1 + 8;
        assert_eq!(&b[body..body + 4], &[4, 0, 0, 0], "longs, sub type, type");
        assert_eq!(u32_at(b, body + 4) as usize, ixs[s].len());
        assert_eq!(&b[body + 8..body + 12], [b"00db", b"01wb"][s]);
        for (i, &(pos, size, _, ticks)) in ixs[s].iter().enumerate() {
            let e = body + 24 + 16 * i;
            assert_eq!(u64_at(b, e), pos as u64);
            assert_eq!(u32_at(b, e + 8) as usize, 8 + size);
            assert_eq!(u32_at(b, e + 12), ticks);
        }
    }
    Layout {
        riffs: riffs.len(),
        data,
        idx1: idx1.1,
    }
}

const STEREO16: AudioFormat = AudioFormat {
    channels: 2,
    sample_rate: 24000,
    bits: 16,
};

#[test]
fn one_riff_holds_a_short_recording() {
    let w = write_av(1 << 30, (5, 3), 4, Some((STEREO16, 3200)));
    let l = check_layout(&w.file, 1 << 30, Some(4));
    assert_eq!(l.riffs, 1);
    assert_eq!(l.data[0].len(), 4);
    assert_eq!(l.data[1], w.pcm);
}

#[test]
fn chunks_cross_riffs_with_their_indexes() {
    let w = write_av(SMALL_LIMIT, (32, 24), 150, Some((STEREO16, 1200)));
    let l = check_layout(&w.file, SMALL_LIMIT, Some(4));
    assert!(l.riffs >= 4, "{} RIFFs", l.riffs);
    assert_eq!(l.data[0].len(), 150);
    assert_eq!(l.data[1], w.pcm);
}

#[test]
fn odd_audio_chunks_are_padded_across_riffs() {
    let mono8 = AudioFormat {
        channels: 1,
        sample_rate: 8000,
        bits: 8,
    };
    let w = write_av(SMALL_LIMIT, (20, 20), 250, Some((mono8, 267)));
    let l = check_layout(&w.file, SMALL_LIMIT, Some(1));
    assert!(l.riffs >= 3, "{} RIFFs", l.riffs);
    assert_eq!(l.data[1], w.pcm);
}

#[test]
fn the_background_movie_reads_every_frame_across_riffs() {
    let (w, h) = (32usize, 24usize);
    let wr = write_av(SMALL_LIMIT, (w, h), 150, Some((STEREO16, 1200)));
    let mut m = Movie::open(Cursor::new(wr.file)).unwrap();
    assert_eq!((m.info().start, m.info().end), (0, 150));
    for i in [0usize, 40, 99, 149] {
        let want: Vec<u8> = wr.video[i]
            .chunks_exact(3)
            .flat_map(|p| [p[2], p[1], p[0], 255])
            .collect();
        assert_eq!(m.frame(i as i32).unwrap().rgba, want, "frame {i}");
    }
}

/// `ffprobe` and `ffmpeg` read `file` and find what `w` wrote.
fn assert_ffmpeg_reads(file: &PathBuf, w: &Written, block: u32) {
    let frames = w.video.len();
    let p = probe(file);
    assert_eq!(get(&p, "streams.stream.0.nb_frames"), frames.to_string());
    assert_eq!(
        get(&p, "streams.stream.0.nb_read_frames"),
        frames.to_string()
    );
    let samples = w.pcm.iter().map(Vec::len).sum::<usize>() / block as usize;
    // ffprobe gives no audio stream duration for AVI; the stream length in
    // samples is the duration at the sample rate.
    assert_eq!(get(&p, "streams.stream.1.nb_frames"), samples.to_string());
    let want: Vec<String> = w.video.iter().map(|f| md5(f)).collect();
    assert_eq!(frame_md5s(file), want);
    assert_eq!(decoded_audio(file), w.pcm.concat());
}

#[test]
fn ffmpeg_reads_every_frame_and_the_audio_across_riffs() {
    if !have("ffprobe") || !have("ffmpeg") {
        eprintln!("SKIP: ffprobe or ffmpeg is not installed (not a pass)");
        return;
    }
    let w = write_av(SMALL_LIMIT, (32, 24), 150, Some((STEREO16, 1200)));
    let path = temp("riffs.avi");
    std::fs::write(&path, &w.file).unwrap();
    assert_ffmpeg_reads(&path, &w, 4);

    // Without idx1 ffmpeg has only the OpenDML indexes to go by.
    let mut odml_only = w.file.clone();
    let idx1 = check_layout(&w.file, SMALL_LIMIT, Some(4)).idx1;
    odml_only[idx1..idx1 + 4].copy_from_slice(b"JUNK");
    std::fs::write(&path, &odml_only).unwrap();
    assert_ffmpeg_reads(&path, &w, 4);
    std::fs::remove_file(&path).unwrap();
}

/// Writes more than 1 GiB of 1920x1080 video with audio and has `ffmpeg`
/// read it back. Slow and big, so `cargo test --release -- --ignored`.
#[test]
#[ignore]
fn a_file_over_one_gibibyte_reads_back() {
    if !have("ffprobe") || !have("ffmpeg") {
        eprintln!("SKIP: ffprobe or ffmpeg is not installed (not a pass)");
        return;
    }
    let (w, h, frames) = (1920usize, 1080usize, 200usize);
    let mut rng = Lcg(5);
    let distinct: Vec<Vec<u8>> = (0..8).map(|_| rng.bytes(w * h * 3)).collect();
    let pcm: Vec<Vec<u8>> = (0..frames).map(|_| rng.bytes(800 * 4)).collect();
    let path = temp("big.avi");
    let file = std::io::BufWriter::new(std::fs::File::create(&path).unwrap());
    let mut avi = AviWriter::new(
        file,
        Config {
            width: w as u32,
            height: h as u32,
            fps_num: 30,
            fps_den: 1,
            audio: Some(STEREO16),
        },
    )
    .unwrap();
    for (n, a) in pcm.iter().enumerate() {
        avi.write_audio(a).unwrap();
        avi.write_frame(&distinct[n % 8]).unwrap();
    }
    avi.finish().unwrap();
    let size = std::fs::metadata(&path).unwrap().len();
    assert!(size > 1 << 30, "{size} bytes");
    let video: Vec<Vec<u8>> = Vec::new();
    let written = Written {
        file: Vec::new(),
        video,
        pcm,
    };
    let p = probe(&path);
    assert_eq!(
        get(&p, "streams.stream.0.nb_read_frames"),
        frames.to_string()
    );
    let samples = frames * 800;
    assert_eq!(get(&p, "streams.stream.1.nb_frames"), samples.to_string());
    let digests: Vec<String> = distinct.iter().map(|f| md5(f)).collect();
    let want: Vec<String> = (0..frames).map(|n| digests[n % 8].clone()).collect();
    assert_eq!(frame_md5s(&path), want);
    assert_eq!(decoded_audio(&path), written.pcm.concat());
    eprintln!(
        "{size} bytes, {frames} frames, {} s of audio",
        samples as f64 / 24000.0
    );
    for (k, v) in &p {
        if k.contains("nb_") || k.contains("duration") || k.contains("size") {
            eprintln!("{k}={v}");
        }
    }
    std::fs::remove_file(&path).unwrap();
}
