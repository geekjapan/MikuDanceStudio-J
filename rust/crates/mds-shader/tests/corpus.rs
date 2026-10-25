//! Every unique shader entry of the ray-mmd corpus (`tools/fixtures/fetch_corpus.sh`) through
//! `mds_shader::compile`, counted per vkd3d error class before and after the workarounds of
//! this crate:
//!
//! - E5027: the first vkd3d try (before) and the try on the [`mds_shader::guard_pow`] source
//!   (after).
//! - E9015: the D3D assembly listing of each compiled entry (before; `mds-mmert` reads its
//!   `dcl` lines) and [`Vkd3d::scan_hlsl`] (after). Where the listing exists, the scan gives the
//!   same declarations.
//! - E9022 and the rest: no workaround here; `vkd3d-patches/` fixes E9022 in the library.
//!
//! It also checks that the WGSL entry point of every compiled entry is `entry_point`.
//! It prints SKIP when the corpus is missing: a skip is not a pass.

mod common;

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

use mds_fx::{Effect, Entry};
use mds_shader::vkd3d::{self, Scan, Target, Vkd3d};
use mds_shader::Status;

const CORPUS_COMMIT: &str = "218a91cd1c53f49850b2772ebbcb98bf258e75b1";

fn report(text: &str) {
    let _ = writeln!(std::io::stderr(), "{text}");
}

fn fx_files(dir: &Path, out: &mut Vec<PathBuf>) {
    for e in std::fs::read_dir(dir).unwrap().flatten() {
        let p = e.path();
        if p.file_name().is_some_and(|n| n == ".git") {
            continue;
        }
        if p.is_dir() {
            fx_files(&p, out);
        } else if p.extension().is_some_and(|x| x.eq_ignore_ascii_case("fx")) {
            out.push(p);
        }
    }
}

fn par_map<T: Sync, R: Send>(items: &[T], f: impl Fn(&T) -> R + Sync) -> Vec<R> {
    let next = AtomicUsize::new(0);
    let out: Mutex<Vec<Option<R>>> = Mutex::new((0..items.len()).map(|_| None).collect());
    let n = std::thread::available_parallelism()
        .map_or(2, |n| n.get())
        .min(8);
    std::thread::scope(|s| {
        for _ in 0..n {
            std::thread::Builder::new()
                .stack_size(64 << 20)
                .spawn_scoped(s, || loop {
                    let i = next.fetch_add(1, Ordering::Relaxed);
                    let Some(item) = items.get(i) else { break };
                    let r = f(item);
                    out.lock().unwrap()[i] = Some(r);
                })
                .unwrap();
        }
    });
    out.into_inner()
        .unwrap()
        .into_iter()
        .map(|r| r.unwrap())
        .collect()
}

/// `E5027` of `E5027: ...`, or the first words of a message without a code.
fn class(error: &str) -> String {
    match error.get(..5) {
        Some(c) if c.starts_with('E') && c[1..].bytes().all(|b| b.is_ascii_digit()) => c.into(),
        _ => error.chars().take(40).collect(),
    }
}

/// The `fn` name after the `@vertex` or `@fragment` attribute.
fn wgsl_entry(wgsl: &str) -> Option<&str> {
    let (_, rest) = wgsl
        .split_once("@vertex")
        .or_else(|| wgsl.split_once("@fragment"))?;
    Some(rest.split_once("fn ")?.1.split_once('(')?.0.trim())
}

/// Declarations as `mds-mmert` reads them: `(register letter, number) -> (usage, index)` for
/// the vertex inputs, and for sm3 the pixel inputs and vertex outputs; `s# -> dimension`.
#[derive(Debug, Default, PartialEq, Eq)]
struct Decls {
    semantics: BTreeMap<(char, u32), (String, u32)>,
    samplers: BTreeMap<u32, String>,
}

fn kept(profile: &str, letter: char) -> bool {
    let vs = profile.starts_with("vs_");
    let sm3 = profile.get(3..4) == Some("3");
    (vs && letter == 'v') || (sm3 && ((vs && letter == 'o') || (!vs && letter == 'v')))
}

fn asm_decls(asm: &str, profile: &str) -> Decls {
    let mut d = Decls::default();
    for line in asm.lines() {
        let mut w = line.split_whitespace();
        let (Some(op), Some(reg)) = (w.next(), w.next()) else {
            continue;
        };
        let Some(usage) = op.strip_prefix("dcl_") else {
            continue;
        };
        let reg = reg.split('.').next().unwrap();
        let (letter, num) = reg.split_at(1);
        let Ok(num) = num.parse::<u32>() else {
            continue;
        };
        let letter = letter.chars().next().unwrap();
        if letter == 's' {
            d.samplers.insert(num, usage.to_string());
            continue;
        }
        if !kept(profile, letter) {
            continue;
        }
        let digits = usage.len() - usage.trim_end_matches(|c: char| c.is_ascii_digit()).len();
        let (name, index) = usage.split_at(usage.len() - digits);
        d.semantics.insert(
            (letter, num),
            (name.to_string(), index.parse().unwrap_or(0)),
        );
    }
    d
}

fn scan_decls(scan: &Scan, profile: &str) -> Decls {
    let mut d = Decls::default();
    for (letter, list) in [('v', &scan.inputs), ('o', &scan.outputs)] {
        if !kept(profile, letter) {
            continue;
        }
        for e in list {
            if letter == 'v'
                && [vkd3d::SV_POSITION, vkd3d::SV_IS_FRONT_FACE].contains(&e.sysval)
                && profile.starts_with("ps_")
            {
                continue;
            }
            let name = e.semantic.to_ascii_lowercase();
            let name = name.strip_prefix("sv_").unwrap_or(&name).to_string();
            d.semantics.insert((letter, e.register), (name, e.index));
        }
    }
    for x in &scan.descriptors {
        if x.kind != vkd3d::DESCRIPTOR_SRV {
            continue;
        }
        let dim = match x.resource {
            vkd3d::RESOURCE_TEXTURE_1D => "1d",
            vkd3d::RESOURCE_TEXTURE_2D => "2d",
            vkd3d::RESOURCE_TEXTURE_3D => "volume",
            vkd3d::RESOURCE_TEXTURE_CUBE => "cube",
            _ => "other",
        };
        d.samplers.insert(x.register, dim.to_string());
    }
    d
}

#[derive(Default)]
struct Outcome {
    /// Error classes of the SPIR-V compile: first try, final result.
    spirv_before: Option<String>,
    spirv_after: Option<String>,
    /// Error classes of the declarations: assembly listing, scan.
    decls_before: Option<String>,
    decls_after: Option<String>,
    /// Problems that fail the test.
    wrong: Vec<String>,
}

fn run(vk: &Vkd3d, label: &str, fx: &Effect, entry: &Entry) -> Outcome {
    let c = mds_shader::compile(vk, fx, entry, label);
    let mut o = Outcome {
        spirv_after: c
            .error
            .as_deref()
            .filter(|_| c.status != Status::Ok)
            .map(class),
        ..Outcome::default()
    };
    o.spirv_before = c
        .first_error
        .as_deref()
        .map(class)
        .or(o.spirv_after.clone());
    if c.status != Status::Ok {
        return o;
    }
    match c.outputs.as_ref().map(|out| &out.wgsl) {
        Some(Ok(wgsl)) if wgsl_entry(wgsl) == Some(c.entry_point.as_str()) => {}
        Some(Ok(wgsl)) => o.wrong.push(format!(
            "WGSL entry point {:?}, entry_point {:?}",
            wgsl_entry(wgsl),
            c.entry_point
        )),
        _ => o.wrong.push("no WGSL".into()),
    }
    let asm = vk.compile_hlsl(
        &c.source,
        label,
        &entry.profile,
        &c.entry_point,
        Target::D3dAsm,
    );
    let scan = vk.scan_hlsl(&c.source, label, &entry.profile, &c.entry_point);
    o.decls_before = asm.as_ref().err().map(|e| class(&e.summary()));
    o.decls_after = scan.as_ref().err().map(|e| class(&e.summary()));
    if let (Ok(asm), Ok(scan)) = (&asm, &scan) {
        let want = asm_decls(&String::from_utf8_lossy(asm), &entry.profile);
        let got = scan_decls(scan, &entry.profile);
        if want != got {
            o.wrong
                .push(format!("scan declarations {got:?}, listing {want:?}"));
        }
    }
    o
}

fn tally(
    rows: &[(String, &Outcome)],
    pick: impl Fn(&Outcome) -> &Option<String>,
) -> BTreeMap<String, usize> {
    let mut m = BTreeMap::new();
    for (_, o) in rows {
        if let Some(c) = pick(o) {
            *m.entry(c.clone()).or_default() += 1;
        }
    }
    m
}

#[test]
fn ray_mmd_entries_compile_per_error_class() {
    let corpus = match std::env::var_os("MDS_CORPUS") {
        Some(p) => PathBuf::from(p),
        None => std::env::temp_dir().join("mds-corpus"),
    }
    .join("ray-mmd");
    if !corpus.is_dir() {
        report(&format!(
            "SKIP: corpus not found at {}; run tools/fixtures/fetch_corpus.sh (a skip is not a pass)",
            corpus.display()
        ));
        return;
    }
    if let Ok(head) = std::fs::read_to_string(corpus.join(".git/HEAD")) {
        assert_eq!(
            head.trim(),
            CORPUS_COMMIT,
            "the corpus is not at the pinned commit"
        );
    }
    let vk = common::vkd3d();
    report(&format!(
        "vkd3d-shader {} from {}",
        vk.version(),
        vk.path().display()
    ));

    let mut files = Vec::new();
    fx_files(&corpus, &mut files);
    files.sort();
    assert_eq!(files.len(), 515, "the pinned corpus holds 515 .fx files");
    let effects = par_map(&files, |f| Effect::parse_file(f).unwrap());
    // One job per unique (preprocessed content, entry), as `mds-shader corpus` counts them.
    let mut seen = HashSet::new();
    let mut jobs = Vec::new();
    for (f, fx) in files.iter().zip(&effects) {
        for e in fx.entries() {
            if seen.insert((fx.content_key(), e.clone())) {
                let rel = f
                    .strip_prefix(&corpus)
                    .unwrap()
                    .to_string_lossy()
                    .into_owned();
                jobs.push((rel, fx, e));
            }
        }
    }
    let outcomes = par_map(&jobs, |(rel, fx, e)| {
        run(&vk, &format!("{rel}:{}", e.function), fx, e)
    });
    let rows: Vec<(String, &Outcome)> = jobs
        .iter()
        .zip(&outcomes)
        .map(|((rel, _, e), o)| (format!("{rel} {} {}", e.profile, e.function), o))
        .collect();

    let spirv = (
        tally(&rows, |o| &o.spirv_before),
        tally(&rows, |o| &o.spirv_after),
    );
    let decls = (
        tally(&rows, |o| &o.decls_before),
        tally(&rows, |o| &o.decls_after),
    );
    let failing = |o: &Outcome, before: bool| {
        if before {
            o.spirv_before.is_some() || o.decls_before.is_some()
        } else {
            o.spirv_after.is_some() || o.decls_after.is_some()
        }
    };
    let before = rows.iter().filter(|(_, o)| failing(o, true)).count();
    let after = rows.iter().filter(|(_, o)| failing(o, false)).count();
    report(&format!(
        "{} unique entries of {} effects: {before} failing before, {after} after",
        rows.len(),
        files.len()
    ));
    let classes: BTreeSet<&String> = spirv.0.keys().chain(spirv.1.keys()).collect();
    for c in classes {
        report(&format!(
            "  SPIR-V {c}: {} before, {} after",
            spirv.0.get(c).unwrap_or(&0),
            spirv.1.get(c).unwrap_or(&0)
        ));
    }
    let classes: BTreeSet<&String> = decls.0.keys().chain(decls.1.keys()).collect();
    for c in classes {
        report(&format!(
            "  declarations {c}: {} before (assembly), {} after (scan)",
            decls.0.get(c).unwrap_or(&0),
            decls.1.get(c).unwrap_or(&0)
        ));
    }
    for (name, o) in &rows {
        if let Some(c) = o.spirv_after.as_ref().or(o.decls_after.as_ref()) {
            report(&format!("  remaining {c}: {name}"));
        }
    }
    let wrong: Vec<String> = rows
        .iter()
        .flat_map(|(name, o)| o.wrong.iter().map(move |w| format!("{name}: {w}")))
        .collect();
    for w in wrong.iter().take(20) {
        report(&format!("  WRONG {w}"));
    }

    assert!(wrong.is_empty(), "{} entries are wrong", wrong.len());
    assert_eq!(spirv.1.get("E5027"), None, "E5027 remains");
    assert!(decls.1.is_empty(), "scan failures: {:?}", decls.1);
    assert!(after < before, "{after} failing after, {before} before");
}
