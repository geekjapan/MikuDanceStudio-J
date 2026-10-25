//! Block digests against the UCRT oracle `crt-digests-fma3.txt`.

use mds_crtmath::digest::{block_digest, Func, BLOCK_COUNT};
use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

const FUNCS: [(&str, Func); 10] = [
    ("sinf", Func::One(mds_crtmath::sinf)),
    ("cosf", Func::One(mds_crtmath::cosf)),
    ("tanf", Func::One(mds_crtmath::tanf)),
    ("asinf", Func::One(mds_crtmath::asinf)),
    ("acosf", Func::One(mds_crtmath::acosf)),
    ("atanf", Func::One(mds_crtmath::atanf)),
    ("atan2f", Func::Atan2(mds_crtmath::atan2f)),
    ("expf", Func::One(mds_crtmath::expf)),
    ("logf", Func::One(mds_crtmath::logf)),
    ("powf", Func::Pow(mds_crtmath::powf)),
];

/// Blocks that cross every code path the full sweep needed to get right:
/// subnormals, the small-argument cuts, near one, e, the Cody-Waite range,
/// the Payne-Hanek range, inf/NaN, negative zero, and expf's underflow edge.
const SAMPLE: [u32; 16] = [
    0x000, 0x39E, 0x3B0, 0x3C8, 0x3F4, 0x3F8, 0x402, 0x413, 0x4B0, 0x4E0, 0x73D, 0x7F8, 0x800,
    0xBF4, 0xC2C, 0xF3D,
];

fn oracle() -> HashMap<String, Vec<u64>> {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../../tests/fixtures/rust/math/crt-digests-fma3.txt"
    );
    let text = std::fs::read_to_string(path).expect("read crt-digests-fma3.txt");
    let mut map: HashMap<String, Vec<u64>> = HashMap::new();
    for line in text.lines().filter(|l| l.starts_with("digest ")) {
        let f: Vec<&str> = line.split(' ').collect();
        let block: usize = f[2].parse().unwrap();
        let digests = map
            .entry(f[1].to_owned())
            .or_insert_with(|| vec![0; BLOCK_COUNT as usize]);
        digests[block] = u64::from_str_radix(f[3], 16).unwrap();
    }
    map
}

/// Matching block count per function over `blocks`, computed on all cores.
fn matches(blocks: &[u32]) -> Vec<(&'static str, usize)> {
    let oracle = oracle();
    let jobs: Vec<(usize, u32)> = (0..FUNCS.len())
        .flat_map(|f| blocks.iter().map(move |&b| (f, b)))
        .collect();
    let ok = Mutex::new(vec![0usize; FUNCS.len()]);
    let next = AtomicUsize::new(0);
    std::thread::scope(|s| {
        for _ in 0..std::thread::available_parallelism().map_or(4, |n| n.get()) {
            s.spawn(|| {
                while let Some(&(f, b)) = jobs.get(next.fetch_add(1, Ordering::Relaxed)) {
                    let (name, func) = FUNCS[f];
                    if block_digest(func, b) == oracle[name][b as usize] {
                        ok.lock().unwrap()[f] += 1;
                    } else {
                        eprintln!("mismatch {name} block {b:#x}");
                    }
                }
            });
        }
    });
    let ok = ok.into_inner().unwrap();
    FUNCS
        .iter()
        .zip(ok)
        .map(|(&(name, _), n)| (name, n))
        .collect()
}

#[test]
fn sample_blocks_match_ucrt() {
    for (name, n) in matches(&SAMPLE) {
        assert_eq!(
            n,
            SAMPLE.len(),
            "{name}: {n} of {} sample blocks match",
            SAMPLE.len()
        );
    }
}

/// `cargo test -p mds-crtmath --release -- --ignored --nocapture`
#[test]
#[ignore = "full sweep of 2^32 inputs per function; run in release"]
fn full_sweep() {
    let all: Vec<u32> = (0..BLOCK_COUNT).collect();
    let counts = matches(&all);
    for (name, n) in &counts {
        println!("{name} {n}/{BLOCK_COUNT}");
    }
    assert!(counts.iter().all(|&(_, n)| n == BLOCK_COUNT as usize));
}
