//! Writes AVI files with known frames and audio, then decodes them with
//! `ffprobe` and `ffmpeg` and compares with what was written. A host without
//! `ffprobe` and `ffmpeg` prints SKIP, which is not a pass.

use mds_media::avi::{AudioFormat, AviWriter, Config, Error, MAX_FILE_BYTES};
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

/// Counts bytes written and keeps none, to reach the size limit cheaply.
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
fn stops_at_one_gibibyte() {
    let (w, h) = (3000usize, 3000usize);
    let frame = vec![0u8; w * h * 3];
    let mut avi = AviWriter::new(
        Counter { pos: 0 },
        Config {
            width: w as u32,
            height: h as u32,
            fps_num: 30,
            fps_den: 1,
            audio: None,
        },
    )
    .unwrap();
    let mut written = 0u64;
    let err = loop {
        match avi.write_frame(&frame) {
            Ok(()) => written += 1,
            Err(e) => break e,
        }
    };
    assert!(matches!(err, Error::TooLarge));
    assert!(written * frame.len() as u64 <= MAX_FILE_BYTES);
    assert!((written + 1) * frame.len() as u64 > MAX_FILE_BYTES - 4096);
}
