//! Compares `mds_vsq::lip_sync` with the dump of `tools/vsq_check`, which
//! runs the real `LoadVsqFile`, for every case of `cases.tsv` in
//! `tests/fixtures/rust/vsq`: the outcome, the message boxes, the morph
//! keys to the bit, the frame, and the `.txt` bytes.
//!
//! Regenerate the files with
//!
//!     python3 -I tests/fixtures/rust/vsq/generate.py
//!     tools/vsq_check/run.sh --update

use mds_vsq::{lip_sync, Run, Stop};
use std::fmt::Write;
use std::path::PathBuf;

/// `kUnset` of the harness: the frame it starts with.
const UNSET: i32 = -0x4000_0000;

// Shift-JIS: まばたき, あ, い, う, え, お and the doubled forms.
const BLINK: &[u8] = b"\x82\xdc\x82\xce\x82\xbd\x82\xab";
const A: &[u8] = b"\x82\xa0";
const I: &[u8] = b"\x82\xa2";
const U: &[u8] = b"\x82\xa4";
const E: &[u8] = b"\x82\xa6";
const O: &[u8] = b"\x82\xa8";

/// The morph tables of the harness's `kModels`.
fn model(name: &str) -> Vec<&'static [u8]> {
    match name {
        "full" => vec![BLINK, O, U, I, A, E, A],
        "no-a" => vec![BLINK, O, U, I, E],
        "no-i" => vec![BLINK, O, U, A, E],
        "no-u" => vec![BLINK, O, I, A, E],
        "no-o" => vec![BLINK, U, I, A, E],
        "no-a-no-o" => vec![BLINK, U, I, E],
        "lookalike" => vec![
            b"\x82\xa0\x82\xa0",
            b"\x82\xa2\x82\xa2",
            b"\x82\xa4\x82\xa4",
            b"\x82\xa8\x82\xa8",
        ],
        "empty" => vec![],
        other => panic!("model {other} is not in the harness"),
    }
}

fn hex(b: &[u8]) -> String {
    if b.is_empty() {
        return "-".into();
    }
    b.iter().fold(String::new(), |mut s, x| {
        write!(s, "{x:02x}").unwrap();
        s
    })
}

/// The harness's dump, rendered from the Rust outcome. The decimal weight
/// column is left out; the bits say the same.
fn render(run: &Run, english: bool) -> String {
    let mut s = String::new();
    let status = match &run.outcome {
        Ok(_) => "ok",
        Err(Stop::Rejected(_)) => "rejected",
        Err(Stop::Hang) => "hang",
        Err(Stop::Fault(_)) => "fault",
    };
    writeln!(s, "status: {status}").unwrap();
    if let Err(Stop::Rejected(r)) = &run.outcome {
        let (text, caption) = r.message(english);
        writeln!(s, "box: {} {}", hex(caption), hex(text)).unwrap();
    }
    if let Err(Stop::Fault(why)) = &run.outcome {
        let why = if *why == "sprintf_s overflow" {
            why
        } else {
            &"signal"
        };
        writeln!(s, "fault: {why}").unwrap();
    }
    let keys = run
        .outcome
        .as_ref()
        .map(|l| l.keys.as_slice())
        .unwrap_or(&[]);
    writeln!(s, "keys: {}", keys.len()).unwrap();
    for k in keys {
        writeln!(s, "{} {} {:08x}", k.frame, k.morph, k.weight.to_bits()).unwrap();
    }
    match &run.outcome {
        Ok(l) => {
            let cur = l.final_frame.unwrap_or(UNSET);
            match l.final_frame {
                Some(f) => writeln!(s, "current_frame: {f}"),
                None => writeln!(s, "current_frame: unchanged"),
            }
            .unwrap();
            writeln!(s, "timeline_start: {}", if cur > 6 { cur - 6 } else { 0 }).unwrap();
            writeln!(s, "last_registered: 0\nseek: {cur} 0").unwrap();
        }
        Err(_) => {
            writeln!(s, "current_frame: unchanged\ntimeline_start: unchanged").unwrap();
            writeln!(s, "last_registered: 0\nseek: none").unwrap();
        }
    }
    s
}

/// The harness line without the decimal weight.
fn without_decimal(dump: &str) -> String {
    dump.lines()
        .map(|l| {
            let f: Vec<&str> = l.split(' ').collect();
            if f.len() == 4 && f[0].parse::<i32>().is_ok() {
                format!("{} {} {}\n", f[0], f[1], f[2])
            } else {
                format!("{l}\n")
            }
        })
        .collect()
}

#[test]
fn every_case_matches_the_cpp_dump() {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust/vsq");
    let cases = std::fs::read_to_string(dir.join("cases.tsv")).expect("cases.tsv");
    let mut n = 0;
    let mut by_status = std::collections::BTreeMap::new();
    for row in cases
        .lines()
        .filter(|l| !l.is_empty() && !l.starts_with('#'))
    {
        let (file, model_name) = row.split_once('\t').expect("file<TAB>model");
        let stem = file.strip_suffix(".vsq").unwrap();
        let vsq = std::fs::read(dir.join(file)).unwrap();
        let morphs = model(model_name);
        let run = lip_sync(&vsq, &morphs);

        let want_txt =
            std::fs::read(dir.join(format!("expected/{stem}@{model_name}.txt"))).unwrap();
        assert_eq!(run.txt, want_txt, "{row}: .txt bytes");
        for (lang, english) in [("jp", false), ("en", true)] {
            let path = dir.join(format!("expected/{stem}@{model_name}.{lang}.dump"));
            let want = without_decimal(&std::fs::read_to_string(path).unwrap());
            assert_eq!(render(&run, english), want, "{row} ({lang})");
        }
        *by_status
            .entry(render(&run, false).lines().next().unwrap().to_string())
            .or_insert(0) += 1;
        n += 1;
    }
    eprintln!("{n} cases match: {by_status:?}");
    assert!(n >= 50, "cases.tsv lists {n} cases");
}

#[test]
fn txt_path_replaces_the_first_vsq() {
    assert_eq!(
        mds_vsq::txt_path("C:\\a.vsq.bak\\b.vsq").as_deref(),
        Some("C:\\a.txt.bak\\b.vsq")
    );
    assert_eq!(mds_vsq::txt_path("song.VSQ"), None);
}
