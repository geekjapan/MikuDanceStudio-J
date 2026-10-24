//! `mds-formats roundtrip <file> [--out <file>]`: read and write a file and
//! compare the bytes. Exit 0 identical, 1 different, 2 error.
//!
//! `mds-formats flipfuzz --seed <n> --iters <n> [files...]`: flip random
//! bytes of each file (the 7 RM-1 fixtures by default) `iters` times. Every
//! mutant that reads must write back to the same bytes (VPD: write, read,
//! write to the same bytes). Exit 0 when all hold, 1 otherwise.
//!
//! `mds-formats inspect <file>`: print bone names (PMD, PMX) or the key
//! pools and their track check (PMM).

use mds_formats::key_pool::{Key, KeyPool};
use mds_formats::{Document, Kind};
use std::process::ExitCode;

const FIXTURES: [(&str, &[u8]); 7] = [
    (
        "chain8.pmd",
        include_bytes!("../../../../tests/fixtures/rust/chain8.pmd"),
    ),
    (
        "chain8.pmx",
        include_bytes!("../../../../tests/fixtures/rust/chain8.pmx"),
    ),
    (
        "chain8_ik.pmx",
        include_bytes!("../../../../tests/fixtures/rust/chain8_ik.pmx"),
    ),
    (
        "morph4.pmx",
        include_bytes!("../../../../tests/fixtures/rust/morph4.pmx"),
    ),
    (
        "swing600.vmd",
        include_bytes!("../../../../tests/fixtures/rust/swing600.vmd"),
    ),
    (
        "pose.vpd",
        include_bytes!("../../../../tests/fixtures/rust/pose.vpd"),
    ),
    (
        "swing600.pmm",
        include_bytes!("../../../../tests/fixtures/rust/swing600.pmm"),
    ),
];

const USAGE: &str = "usage: mds-formats roundtrip <file> [--out <file>]\n       \
                     mds-formats flipfuzz --seed <n> --iters <n> [files...]\n       \
                     mds-formats inspect <file>";

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let args: Vec<&str> = args.iter().map(String::as_str).collect();
    let result = match args.as_slice() {
        // An option where a file belongs, such as `--help`, gets the usage.
        ["roundtrip" | "inspect", file, ..] if file.starts_with('-') => Err(USAGE.into()),
        ["roundtrip", file] => roundtrip(file, None),
        ["roundtrip", file, "--out", out] => roundtrip(file, Some(out)),
        ["flipfuzz", "--seed", seed, "--iters", iters, files @ ..] => {
            match (seed.parse(), iters.parse()) {
                (Ok(seed), Ok(iters)) => flipfuzz(seed, iters, files),
                _ => Err("seed and iters must be numbers".into()),
            }
        }
        ["inspect", file] => inspect(file),
        _ => Err(USAGE.into()),
    };
    match result {
        Ok(code) => code,
        Err(e) => {
            eprintln!("mds-formats: {e}");
            ExitCode::from(2)
        }
    }
}

type Outcome = Result<ExitCode, String>;

fn load(path: &str) -> Result<(Vec<u8>, Document), String> {
    let data = std::fs::read(path).map_err(|e| format!("{path}: {}", e.kind()))?;
    let doc = Document::read(&data).map_err(|e| format!("{path}: {e}"))?;
    Ok((data, doc))
}

fn roundtrip(path: &str, out: Option<&str>) -> Outcome {
    let (data, doc) = load(path)?;
    let bytes = doc.write().map_err(|e| format!("{path}: write: {e}"))?;
    if let Some(out) = out {
        std::fs::write(out, &bytes).map_err(|e| format!("{out}: {}", e.kind()))?;
    }
    if bytes == data {
        println!("identical 1 file");
        return Ok(ExitCode::SUCCESS);
    }
    let at = data
        .iter()
        .zip(&bytes)
        .position(|(a, b)| a != b)
        .unwrap_or(data.len().min(bytes.len()));
    println!(
        "differs 1 file: {path} first difference at byte {at} (in {} bytes, out {} bytes)",
        data.len(),
        bytes.len()
    );
    Ok(ExitCode::from(1))
}

/// xorshift64*: deterministic, no dependency.
struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_f491_4f6c_dd1d)
    }
    fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }
}

fn flipfuzz(seed: u64, iters: u64, files: &[&str]) -> Outcome {
    let inputs: Vec<(String, Vec<u8>)> = if files.is_empty() {
        FIXTURES
            .iter()
            .map(|(n, b)| (n.to_string(), b.to_vec()))
            .collect()
    } else {
        files
            .iter()
            .map(|p| {
                std::fs::read(p)
                    .map(|b| (p.to_string(), b))
                    .map_err(|e| format!("{p}: {}", e.kind()))
            })
            .collect::<Result<_, _>>()?
    };
    let mut failed = false;
    for (name, original) in &inputs {
        if original.is_empty() {
            return Err(format!("{name}: empty file"));
        }
        let mut rng = Rng(seed.wrapping_mul(0x9e37_79b9_7f4a_7c15) | 1);
        let (mut accepted, mut mismatches) = (0u64, 0u64);
        let mut data = original.clone();
        for iter in 0..iters {
            data.copy_from_slice(original);
            let mut flips = Vec::new();
            for _ in 0..1 + rng.below(4) {
                let at = rng.below(data.len());
                data[at] = if rng.below(2) == 0 {
                    data[at] ^ (1 << rng.below(8))
                } else {
                    rng.next() as u8
                };
                flips.push((at, data[at]));
            }
            let Ok(doc) = Document::read(&data) else {
                continue;
            };
            accepted += 1;
            let holds = match doc.write() {
                Ok(out) if matches!(doc, Document::Vpd(_)) => Document::read(&out)
                    .and_then(|d| d.write())
                    .is_ok_and(|again| again == out),
                Ok(out) => out == data,
                Err(_) => false,
            };
            if !holds {
                if mismatches == 0 {
                    println!("  {name}: first mismatch at iteration {iter}, bytes (offset, value) {flips:?}");
                }
                mismatches += 1;
            }
        }
        println!(
            "flipfuzz {name}: {iters} iterations, {accepted} read, {mismatches} did not write back"
        );
        failed |= mismatches != 0;
    }
    Ok(if failed {
        ExitCode::from(1)
    } else {
        ExitCode::SUCCESS
    })
}

fn print_pool<K: Key>(label: &str, pool: &KeyPool<K>) {
    let links = |i: u32, k: &K| format!("{i}:{}/{}/{}", k.frame(), k.previous(), k.next());
    let heads: Vec<String> = pool
        .heads()
        .iter()
        .enumerate()
        .map(|(i, k)| links(i as u32, k))
        .collect();
    let records: Vec<String> = pool.records().iter().map(|(i, k)| links(*i, k)).collect();
    let check = pool.validate_tracks().err().unwrap_or_else(|| "ok".into());
    println!("  {label}: capacity {}, tracks {check}", pool.capacity());
    println!("    heads (index:frame/previous/next) {}", heads.join(" "));
    println!("    records {}", records.join(" "));
}

fn inspect(path: &str) -> Outcome {
    let (data, doc) = load(path)?;
    let kind = mds_formats::detect(&data).map_or("?", |k| match k {
        Kind::Pmd => "PMD",
        Kind::Pmx => "PMX",
        Kind::Vmd => "VMD",
        Kind::Vpd => "VPD",
        Kind::Pmm => "PMM",
    });
    println!("{path}: {kind}, {} bytes", data.len());
    match &doc {
        Document::Pmd(m) => {
            for (i, b) in m.bones.iter().enumerate() {
                println!("  bone {i}: {}", b.name.text);
            }
        }
        Document::Pmx(m) => {
            for (i, b) in m.bones.iter().enumerate() {
                println!("  bone {i}: {} / {}", b.name.text, b.name_en.text);
            }
        }
        Document::Vmd(m) => println!(
            "  {} bone keys, {} morph keys",
            m.bones.len(),
            m.morphs.len()
        ),
        Document::Vpd(m) => {
            for b in &m.bones {
                println!(
                    "  bone {}: {:?} {:?}",
                    b.name.text, b.translation, b.rotation
                );
            }
        }
        Document::Pmm(s) => {
            for m in &s.models {
                println!(" model slot {}: {}", m.slot, m.name.text);
                print_pool("bone keys", &m.bone_keys);
                print_pool("morph keys", &m.morph_keys);
                print_pool("display keys", &m.display_keys);
            }
            print_pool("camera keys", &s.camera);
            print_pool("light keys", &s.light);
            print_pool("gravity keys", &s.gravity);
            print_pool("self-shadow keys", &s.self_shadow);
        }
    }
    Ok(ExitCode::SUCCESS)
}
