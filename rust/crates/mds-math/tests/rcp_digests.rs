//! The `rcpss` and `rsqrtss` estimates against `tests/fixtures/rust/math/rcp/`.

use mds_crtmath::digest::{block_digest, Func, BLOCK_COUNT};
use mds_math::{rcp_estimate, rsqrt_estimate};
use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

const DIR: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../tests/fixtures/rust/math/rcp/"
);
type Estimate = fn(f32) -> f32;
const FUNCS: [(&str, Estimate); 2] = [("rcpss", rcp_estimate), ("rsqrtss", rsqrt_estimate)];

/// Zeros and denormals of both signs, exponents 126 and 127 of both signs,
/// the exponents where `rcpss` flushes to zero, infinities and NaNs, and a
/// few others.
const SAMPLE: [u32; 16] = [
    0x000, 0x007, 0x008, 0x200, 0x3F0, 0x3F8, 0x5A0, 0x7E8, 0x7F0, 0x7F8, 0x800, 0x807, 0xBF0,
    0xBF8, 0xFE8, 0xFF8,
];

/// `(name, index, bits)` for each non-comment line of a fixture.
fn lines(file: &str) -> Vec<(String, u32, u64)> {
    let text = std::fs::read_to_string(format!("{DIR}{file}")).expect(file);
    text.lines()
        .filter(|l| !l.starts_with('#'))
        .map(|l| {
            let f: Vec<&str> = l.split(' ').collect();
            let word = if f[0] == "digest" { &f[1..] } else { &f[..] };
            (
                word[0].to_owned(),
                word[1].parse().unwrap(),
                u64::from_str_radix(word[2], 16).unwrap(),
            )
        })
        .collect()
}

/// Matching block count per function over `blocks`, computed on all cores.
fn matches(blocks: &[u32]) -> Vec<(&'static str, usize)> {
    let oracle: HashMap<(String, u32), u64> = lines("rcp-digests.txt")
        .into_iter()
        .map(|(n, b, d)| ((n, b), d))
        .collect();
    let want = |name: &str, block: u32| oracle[&(name.to_owned(), block)];
    let jobs: Vec<(usize, u32, u64)> = (0..FUNCS.len())
        .flat_map(|f| blocks.iter().map(move |&b| (f, b)))
        .map(|(f, b)| (f, b, want(FUNCS[f].0, b)))
        .collect();
    let ok = Mutex::new(vec![0usize; FUNCS.len()]);
    let next = AtomicUsize::new(0);
    std::thread::scope(|s| {
        for _ in 0..std::thread::available_parallelism().map_or(4, |n| n.get()) {
            s.spawn(|| {
                while let Some(&(f, b, digest)) = jobs.get(next.fetch_add(1, Ordering::Relaxed)) {
                    let (name, func) = FUNCS[f];
                    if block_digest(Func::One(func), b) == digest {
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
fn table_matches_fixture() {
    let table = lines("rcp-table.txt");
    assert_eq!(table.len(), 4096);
    for (name, i, bits) in table {
        let got = match name.as_str() {
            "rcpss" => rcp_estimate(f32::from_bits(0x3F80_0000 | i << 12)),
            "rsqrtss" => rsqrt_estimate(f32::from_bits(0x3F00_0000 + (i << 13))),
            _ => panic!("{name}"),
        };
        assert_eq!(u64::from(got.to_bits()), bits, "{name} {i}");
    }
}

/// NaN signs and payloads, which the digests do not see.
#[test]
fn nan_and_negative_outputs() {
    let cases = [
        (rcp_estimate as Estimate, 0x7F80_0001u32, 0x7FC0_0001u32),
        (rcp_estimate, 0xFFA0_0000, 0xFFE0_0000),
        (rsqrt_estimate, 0x7F80_0001, 0x7FC0_0001),
        (rsqrt_estimate, 0xFFC0_1234, 0xFFC0_1234),
        (rsqrt_estimate, 0xBF80_0000, 0xFFC0_0000),
        (rsqrt_estimate, 0xFF80_0000, 0xFFC0_0000),
        (rsqrt_estimate, 0x8000_0000, 0xFF80_0000),
    ];
    for (f, x, want) in cases {
        assert_eq!(f(f32::from_bits(x)).to_bits(), want, "{x:#010x}");
    }
}

#[test]
fn sample_blocks_match() {
    for (name, n) in matches(&SAMPLE) {
        assert_eq!(
            n,
            SAMPLE.len(),
            "{name}: {n} of {} sample blocks match",
            SAMPLE.len()
        );
    }
}

/// `cargo test -p mds-math --release -- --ignored --nocapture`
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
