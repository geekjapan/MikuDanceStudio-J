//! The gate: every effect with a plan under `tests/fixtures/rust/mme/` loads, its resources
//! are what the plan's `created` lines say (read back from the wgpu objects), and one frame
//! that runs every technique on `chain8.pmx` walks the scripts exactly as the plan's `runs`
//! section records, with no wgpu validation error.
//!
//! An effect is skipped (with the reason) when the plan rejects it or a pass cannot compile
//! (a known `mds-shader` gap); its other passes still run. `extra/` always runs; `ray-mmd/`
//! needs the corpus of `tools/fixtures/fetch_corpus.sh` and prints SKIP without it.
//! `MDS_MMERT_ONLY=<substring>` runs only the plans whose path contains it.

use std::collections::BTreeMap;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

use mds_mmert::{DrawInput, Effect, Gpu, LoadError, Model, Scene, Target, BACKBUFFER};

const CORPUS_COMMIT: &str = "218a91cd1c53f49850b2772ebbcb98bf258e75b1";

fn report(text: &str) {
    let _ = writeln!(std::io::stderr(), "{text}");
}

fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

fn corpus_dir() -> PathBuf {
    match std::env::var_os("MDS_CORPUS") {
        Some(p) => PathBuf::from(p),
        None => std::env::temp_dir().join("mds-corpus"),
    }
    .join("ray-mmd")
}

fn vkd3d() -> mds_shader::vkd3d::Vkd3d {
    let path = match std::env::var_os("MDS_VKD3D_LIB") {
        Some(p) => PathBuf::from(p),
        None => {
            let (target, file) = if cfg!(target_os = "macos") {
                ("macos".to_string(), "libvkd3d-shader.1.dylib")
            } else {
                let arch = if cfg!(target_arch = "x86_64") {
                    "amd64"
                } else {
                    "arm64"
                };
                (format!("linux-{arch}"), "libvkd3d-shader.so.1")
            };
            std::env::temp_dir()
                .join("mds-vkd3d")
                .join(target)
                .join("lib")
                .join(file)
        }
    };
    mds_shader::vkd3d::Vkd3d::open(&path).unwrap_or_else(|e| {
        panic!("vkd3d-shader 2.1 not loaded: {e}\nBuild it with tools/vkd3d/build.sh, or set MDS_VKD3D_LIB.")
    })
}

fn plans(dir: &Path, out: &mut Vec<PathBuf>) {
    let mut entries: Vec<_> = std::fs::read_dir(dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .collect();
    entries.sort();
    for p in entries {
        if p.is_dir() {
            plans(&p, out);
        } else if p.to_string_lossy().ends_with(".plan.txt") {
            out.push(p);
        }
    }
}

/// The `created` and `offscreendepth` lines of a plan, by resource, without the D3D pool and
/// usage fields.
fn planned_resources(plan: &str) -> Vec<(String, String)> {
    let mut out = Vec::new();
    let mut name = String::new();
    for line in plan.lines() {
        if let Some(rest) = line.strip_prefix("resource ") {
            name = rest.split(" semantic=").next().unwrap_or("").to_string();
        } else if let Some(rest) = line
            .strip_prefix("  ")
            .filter(|l| l.starts_with("created ") || l.starts_with("offscreendepth "))
        {
            out.push((
                name.clone(),
                rest.split(" pool=").next().unwrap_or(rest).to_string(),
            ));
        }
    }
    out
}

/// The plan's `runs` section without its `log` lines.
fn planned_runs(plan: &str) -> String {
    let mut out = String::new();
    let mut inside = false;
    for line in plan.lines() {
        if line == "runs" {
            inside = true;
        } else if inside && !line.starts_with(' ') {
            break;
        }
        if inside && !line.trim_start().starts_with("log ") {
            out.push_str(line);
            out.push('\n');
        }
    }
    out
}

fn first_diff(expected: &str, got: &str) -> Option<String> {
    let (e, g): (Vec<_>, Vec<_>) = (expected.lines().collect(), got.lines().collect());
    (0..e.len().max(g.len()))
        .find(|&i| e.get(i) != g.get(i))
        .map(|i| {
            format!(
                "line {}: expected {:?}, got {:?}",
                i + 1,
                e.get(i).unwrap_or(&"<eof>"),
                g.get(i).unwrap_or(&"<eof>")
            )
        })
}

enum Outcome {
    Passed,
    Skipped(String),
    Failed(String),
}

fn check(
    gpu: &Gpu,
    vk: &mds_shader::vkd3d::Vkd3d,
    model: &Model,
    effect: &Path,
    root: &Path,
    plan: &str,
) -> Outcome {
    let rejected = plan.lines().any(|l| l == "load rejected");
    let ((result, report), errors) = gpu.scoped(|| {
        let mut e = match Effect::load(gpu, vk, effect, root, BACKBUFFER) {
            Ok(e) => e,
            Err(err) => return (Err(err), None),
        };
        let target = Target::new(gpu, BACKBUFFER);
        let mut scene = Scene::default_view(BACKBUFFER.0, BACKBUFFER.1);
        // chain8 faces +Z.
        scene.view =
            mds_mmert::bind::look_at_lh([0.0, 4.0, 20.0], [0.0, 4.0, 0.0], [0.0, 1.0, 0.0]);
        let input = DrawInput {
            scene: &scene,
            geometry: Some((model, 0)),
            draw_type: mds_mmert::bind::DRAW_OBJECT,
            controls: None,
            owner: None,
            offscreen_owner: None,
        };
        let report = e.frame(gpu, &target, &input);
        let _ = gpu.wait();
        (Ok(e), Some(report))
    });
    let e = match (result, rejected) {
        (Err(LoadError::Rejected(_)), true) => {
            return Outcome::Skipped("rejected, as the plan says".into())
        }
        (Err(err), _) => return Outcome::Failed(format!("load: {err}")),
        (Ok(_), true) => return Outcome::Failed("loads, but the plan rejects it".into()),
        (Ok(e), false) => e,
    };
    if let Some(err) = errors.first() {
        return Outcome::Failed(format!(
            "wgpu: {}",
            err.split_whitespace().collect::<Vec<_>>().join(" ")
        ));
    }
    let got: Vec<(String, String)> = e
        .sas
        .resources
        .iter()
        .zip(&e.created)
        .flat_map(|(r, c)| {
            let q = mds_mme::plan::q(&r.name);
            c.as_ref()
                .map_or_else(|| vec!["created none".to_string()], |c| c.plan_lines(r))
                .into_iter()
                .map(move |l| (q.clone(), l))
        })
        .collect();
    let want = planned_resources(plan);
    if got != want {
        let at = got
            .iter()
            .zip(&want)
            .position(|(a, b)| a != b)
            .unwrap_or(got.len().min(want.len()));
        return Outcome::Failed(format!(
            "resources: expected {:?}, got {:?}",
            want.get(at),
            got.get(at)
        ));
    }
    let report = report.unwrap();
    if let Some(d) = first_diff(&planned_runs(plan), &report.runs) {
        return Outcome::Failed(format!("runs {d}"));
    }
    let failed_pass = e.programs.iter().flatten().find_map(|p| p.as_ref().err());
    match failed_pass {
        Some(why) => Outcome::Skipped(format!("pass not compiled: {}", reason(why))),
        None => Outcome::Passed,
    }
}

/// The class of a failure: the error code or the first words.
fn reason(why: &str) -> String {
    match why
        .split_whitespace()
        .find(|w| w.len() == 6 && w.starts_with('E') && w.ends_with(':'))
    {
        Some(code) => format!("vkd3d {}", code.trim_end_matches(':')),
        None => why
            .split(':')
            .nth(1)
            .unwrap_or(why)
            .trim()
            .chars()
            .take(70)
            .collect(),
    }
}

fn run_group(
    gpu: &Gpu,
    vk: &mds_shader::vkd3d::Vkd3d,
    model: &Model,
    group: &str,
    effects: &Path,
) -> usize {
    let mut list = Vec::new();
    plans(&fixtures().join("mme").join(group), &mut list);
    if let Ok(only) = std::env::var("MDS_MMERT_ONLY") {
        list.retain(|p| p.to_string_lossy().contains(&only));
    }
    let rel_of = |plan: &Path| {
        plan.strip_prefix(fixtures().join("mme").join(group))
            .unwrap()
            .to_string_lossy()
            .replace('\\', "/")
    };
    // Error scopes are per thread in wgpu, so effects run in parallel on one device.
    let next = AtomicUsize::new(0);
    let outcomes = Mutex::new(Vec::new());
    let workers = std::thread::available_parallelism()
        .map_or(1, |n| n.get())
        .min(8);
    std::thread::scope(|s| {
        for _ in 0..workers {
            s.spawn(|| loop {
                let i = next.fetch_add(1, Ordering::Relaxed);
                let Some(plan) = list.get(i) else {
                    break;
                };
                let rel = rel_of(plan);
                let effect = effects.join(rel.trim_end_matches(".plan.txt"));
                let text = std::fs::read_to_string(plan).unwrap();
                let o = check(gpu, vk, model, &effect, effects, &text);
                outcomes.lock().unwrap().push((i, o));
            });
        }
    });
    let mut outcomes = outcomes.into_inner().unwrap();
    outcomes.sort_by_key(|o| o.0);
    let (mut passed, mut skipped, mut failed) = (0, BTreeMap::<String, usize>::new(), Vec::new());
    for (i, o) in outcomes {
        match o {
            Outcome::Passed => passed += 1,
            Outcome::Skipped(why) => *skipped.entry(why).or_default() += 1,
            Outcome::Failed(why) => failed.push(format!("{group}/{}: {why}", rel_of(&list[i]))),
        }
    }
    let skips: usize = skipped.values().sum();
    report(&format!(
        "{group}: {} effects, {passed} passed, {skips} skipped, {} failed (adapter {})",
        list.len(),
        failed.len(),
        gpu.adapter
    ));
    for (why, n) in &skipped {
        report(&format!("  skipped {n}: {why}"));
    }
    for f in failed.iter().take(40) {
        report(&format!("  FAILED {f}"));
    }
    failed.len()
}

fn setup() -> Option<(Gpu, mds_shader::vkd3d::Vkd3d, Model)> {
    let Some(gpu) = Gpu::new().unwrap() else {
        report("SKIP: no wgpu adapter on this host (a skip is not a pass)");
        return None;
    };
    let vk = vkd3d();
    let pmx = mds_formats::pmx::Pmx::read(&std::fs::read(fixtures().join("chain8.pmx")).unwrap())
        .unwrap();
    let model = Model::from_pmx(&gpu.device, &pmx).unwrap();
    Some((gpu, vk, model))
}

#[test]
fn extra_effects_run_their_plans() {
    let Some((gpu, vk, model)) = setup() else {
        return;
    };
    let failed = run_group(&gpu, &vk, &model, "extra", &fixtures().join("mme/effects"));
    assert_eq!(failed, 0);
}

#[test]
fn ray_mmd_effects_run_their_plans() {
    let corpus = corpus_dir();
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
            "the corpus at {} is not at the pinned commit",
            corpus.display()
        );
    }
    let Some((gpu, vk, model)) = setup() else {
        return;
    };
    let failed = run_group(&gpu, &vk, &model, "ray-mmd", &corpus);
    assert_eq!(failed, 0);
}
