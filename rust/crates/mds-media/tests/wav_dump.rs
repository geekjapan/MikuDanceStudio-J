//! Compares `mds_media::wav` with the dump of `tools/wave_check`, which runs
//! the real `src/media/wave_audio.cpp` and `wave_data_chunk.cpp` on the WAV
//! files next to it. Regenerate the inputs and the dump with the commands in
//! `tests/fixtures/rust/media/README.md`.

use mds_media::wav::{scan_data_chunk, Reject, Wave, CB_SIZE};
use std::collections::BTreeMap;
use std::path::PathBuf;

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust/media")
}

/// `file name -> key -> numbers` of the dump (`message` keeps its text).
type Dump = BTreeMap<String, BTreeMap<String, Vec<String>>>;

fn parse_dump(text: &str) -> Dump {
    let mut dump = Dump::new();
    let mut current = String::new();
    for line in text.lines() {
        let (key, rest) = line.split_once(' ').unwrap_or((line, ""));
        if key == "file" {
            current = rest.to_string();
            dump.insert(current.clone(), BTreeMap::new());
        } else {
            let words = rest.split(' ').filter(|w| !w.is_empty()).map(String::from);
            dump.get_mut(&current)
                .expect("a field before the first file line")
                .insert(key.to_string(), words.collect());
        }
    }
    dump
}

fn nums<T: ToString>(v: impl IntoIterator<Item = T>) -> Vec<String> {
    v.into_iter().map(|x| x.to_string()).collect()
}

/// `(frame, offset)` of the `seek` lines in the block of one file.
fn frame_seeks(text: &str, name: &str) -> Vec<(i32, i32)> {
    let block = text.split("file ").find(|b| b.starts_with(name)).unwrap();
    block
        .lines()
        .filter_map(|l| l.strip_prefix("seek "))
        .map(|l| {
            let (f, o) = l.split_once(' ').unwrap();
            (f.parse().unwrap(), o.parse().unwrap())
        })
        .collect()
}

#[test]
fn wav_matches_cpp_dump() {
    let dir = fixtures();
    let Ok(text) = std::fs::read_to_string(dir.join("wave-dump.txt")) else {
        eprintln!("SKIP: tests/fixtures/rust/media/wave-dump.txt is missing (not a pass)");
        return;
    };
    let dump = parse_dump(&text);
    let mut on_disk: Vec<String> = std::fs::read_dir(dir.join("wav"))
        .expect("tests/fixtures/rust/media/wav")
        .map(|e| e.unwrap().file_name().into_string().unwrap())
        .filter(|n| n.ends_with(".wav"))
        .collect();
    on_disk.sort();
    assert_eq!(on_disk, dump.keys().cloned().collect::<Vec<_>>());

    let (mut accepted, mut rejected) = (0, 0);
    for (name, want) in &dump {
        let bytes = std::fs::read(dir.join("wav").join(name)).unwrap();
        let scan = scan_data_chunk(&bytes, 36);
        let got_scan = scan.map_or(vec!["fail".into()], |c| {
            nums(["ok".to_string(), c.size.to_string(), c.offset.to_string()])
        });
        assert_eq!(want["scan"], got_scan, "{name}: scan");

        let loaded = Wave::from_bytes(bytes);
        let got_message = match &loaded {
            Err(Reject::NotPcm) => "This is not WAVE(PCM) file",
            _ => "none",
        };
        assert_eq!(want["message"].join(" "), got_message, "{name}: message");
        assert_eq!(
            want["loaded"],
            nums([u8::from(loaded.is_ok())]),
            "{name}: loaded"
        );
        let Ok(wave) = loaded else {
            rejected += 1;
            continue;
        };
        accepted += 1;

        let f = wave.format;
        let format = [
            1,
            f.channels.into(),
            f.samples_per_sec,
            f.avg_bytes_per_sec,
            f.block_align.into(),
            f.bits_per_sample.into(),
            CB_SIZE.into(),
        ];
        assert_eq!(want["format"], nums(format), "{name}: format");
        assert_eq!(
            want["data"],
            nums([wave.data.size, wave.data.offset]),
            "{name}: data"
        );
        assert_eq!(
            want["buffer_bytes"],
            nums([wave.buffer_bytes(); 2]),
            "{name}: buffer_bytes"
        );
        assert_eq!(
            want["failures"],
            nums([wave.read_failures]),
            "{name}: failures"
        );
        assert_eq!(
            want["columns"],
            nums([wave.waveform_max.len()]),
            "{name}: columns"
        );
        assert_eq!(want["max"], nums(wave.waveform_max.iter()), "{name}: max");
        assert_eq!(want["min"], nums(wave.waveform_min.iter()), "{name}: min");
        // The dump holds `seek <frame> <offset>` per frame; the map keeps the last
        // line only, so read them from the raw text.
        let seeks = frame_seeks(&text, name);
        assert!(!seeks.is_empty(), "{name}: no seek lines");
        for (frame, offset) in seeks {
            assert_eq!(
                wave.seek_offset(frame as f64 / 30.0),
                offset,
                "{name}: seek frame {frame}"
            );
        }
        let pcm = wave.pcm();
        assert!(
            pcm.len() <= wave.data.size as usize,
            "{name}: pcm longer than its chunk"
        );
    }
    eprintln!("{accepted} accepted, {rejected} rejected, all equal to the C++ dump");
    assert!(accepted >= 10 && rejected >= 10, "the fixture set shrank");
}

#[test]
fn seek_offset_is_the_block_aligned_byte_of_the_time() {
    let dir = fixtures().join("wav");
    let Ok(bytes) = std::fs::read(dir.join("pcm16_stereo_22050.wav")) else {
        eprintln!("SKIP: pcm16_stereo_22050.wav is missing (not a pass)");
        return;
    };
    let wave = Wave::from_bytes(bytes).unwrap();
    assert_eq!(wave.seek_offset(0.0), 44);
    // 88200 bytes a second: frame 7 of 30 is byte 20580, frame 15 is 44100.
    assert_eq!(wave.seek_offset(7.0 / 30.0), 44 + 20580);
    assert_eq!(wave.seek_offset(15.0 / 30.0), 44 + 44100);

    let Ok(bytes) = std::fs::read(dir.join("pcm16_mono_11025.wav")) else {
        eprintln!("SKIP: pcm16_mono_11025.wav is missing (not a pass)");
        return;
    };
    // 22050 bytes a second, 2 per block: frame 1 is byte 735, rounded down to 734.
    assert_eq!(
        Wave::from_bytes(bytes).unwrap().seek_offset(1.0 / 30.0),
        44 + 734
    );
}

#[test]
fn pcm_is_cut_to_the_file() {
    let dir = fixtures().join("wav");
    let Ok(bytes) = std::fs::read(dir.join("truncated_data.wav")) else {
        eprintln!("SKIP: truncated_data.wav is missing (not a pass)");
        return;
    };
    let wave = Wave::from_bytes(bytes).unwrap();
    assert_eq!((wave.data.size, wave.pcm().len()), (4000, 2000));
}

/// 44-byte PCM header, then `data` with the declared size and no bytes.
fn header_only(avg: u32, block: u16, declared: u32) -> Vec<u8> {
    let mut b = b"RIFF".to_vec();
    b.extend([0; 16]);
    b.extend(1u16.to_le_bytes());
    b.extend(1u16.to_le_bytes());
    b.extend(8000u32.to_le_bytes());
    b.extend(avg.to_le_bytes());
    b.extend(block.to_le_bytes());
    b.extend(8u16.to_le_bytes());
    b.extend(b"data");
    b.extend(declared.to_le_bytes());
    b
}

#[test]
fn declared_size_does_not_size_the_allocation() {
    // C++: dataSize 0x7FFFFFF0 is positive, so it accepts and mallocs
    // dataSize / 1 + 1 bytes per array; here only the present bytes are stored.
    let mut bytes = header_only(400, 1, 0x7FFF_FFF0);
    bytes.extend([0x90; 8]);
    assert!(bytes.len() < 100);
    let wave = Wave::from_bytes(bytes).unwrap();
    assert_eq!(wave.waveform_max.len(), 0x7FFF_FFF0 + 1);
    assert_eq!(wave.waveform_min.len(), 0x7FFF_FFF0 + 1);
    assert!(wave.waveform_max.stored().len() <= 9);
    assert!(wave.waveform_min.stored().len() <= 9);
    assert_eq!(wave.waveform_max.get(0x7FFF_FFF0), 0);
    assert_eq!(wave.pcm().len(), 8);
}

#[test]
fn negative_declared_size_is_rejected() {
    let r = Wave::from_bytes(header_only(400, 1, 0xFFFF_FFF0));
    assert!(matches!(r, Err(Reject::NoDataChunk)));
}
