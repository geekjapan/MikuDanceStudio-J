//! `mds-shader corpus <path>...`: compile every shader entry of the `.fx` files below the paths.

use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use mds_fx::{Effect, Entry, FxError, Options};
use mds_shader::vkd3d::Vkd3d;
use mds_shader::{backend, gpu, reflect, Compiled, Stage, Status};

const USAGE: &str = "\
usage: mds-shader corpus [options] <path>...

Compiles every unique shader entry of the .fx files below each path (or the file itself)
through vkd3d-shader to SPIR-V, then through naga to WGSL, MSL, and HLSL, and prints
`shaders N spirv N wgsl N msl N hlsl N` and the compile time per shader.

options:
  --list          print one line per shader: path, profile, function, args, OK/FAIL/NAGA_FAIL
  --errors        print the first error of each shader that is not OK
  --reflect       print the parameter registers of each compiled shader and their source
  --reparse-wgsl  parse and validate each WGSL output again with naga
  --wgpu-check    create a wgpu device, then a shader module and a render pipeline per WGSL
  --emit <dir>    write the vkd3d input, WGSL, MSL, and HLSL of each shader to <dir>
  -j <n>          worker threads (default: all CPUs, at most 8)

The vkd3d-shader 2.1 library is loaded from $MDS_VKD3D_LIB, or else from the directory of
the executable (tools/vkd3d/build.sh builds it).
";

struct Opts {
    list: bool,
    errors: bool,
    reflect: bool,
    reparse: bool,
    wgpu: bool,
    emit: Option<PathBuf>,
    jobs: usize,
    paths: Vec<PathBuf>,
}

fn parse_args(args: &[String]) -> Result<Opts, String> {
    let mut o = Opts {
        list: false,
        errors: false,
        reflect: false,
        reparse: false,
        wgpu: false,
        emit: None,
        jobs: std::thread::available_parallelism()
            .map_or(1, |n| n.get())
            .min(8),
        paths: Vec::new(),
    };
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--list" => o.list = true,
            "--errors" => o.errors = true,
            "--reflect" => o.reflect = true,
            "--reparse-wgsl" => o.reparse = true,
            "--wgpu-check" => o.wgpu = true,
            "--emit" => o.emit = Some(PathBuf::from(it.next().ok_or("--emit needs a directory")?)),
            "-j" => {
                let n = it.next().ok_or("-j needs a number")?;
                o.jobs = n
                    .parse::<usize>()
                    .ok()
                    .filter(|n| *n > 0)
                    .ok_or("-j needs a positive number")?;
            }
            s if s.starts_with('-') && s.len() > 1 => return Err(format!("unknown option {s}")),
            s => o.paths.push(PathBuf::from(s)),
        }
    }
    if o.paths.is_empty() {
        return Err("no path given".into());
    }
    Ok(o)
}

// File discovery and labels follow `mds-fx scan`, so paths print as in shaders-direct.tsv.

struct Found {
    path: PathBuf,
    label: String,
}

fn slashed(p: &Path) -> String {
    p.components()
        .map(|c| c.as_os_str().to_string_lossy().into_owned())
        .collect::<Vec<_>>()
        .join("/")
}

fn root_label(root: &Path) -> String {
    if root.is_absolute() {
        if let Some(rel) = std::env::current_dir()
            .ok()
            .and_then(|cwd| root.strip_prefix(cwd).ok().map(Path::to_path_buf))
        {
            if !rel.as_os_str().is_empty() {
                return slashed(&rel);
            }
        }
        return root
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_default();
    }
    slashed(root)
}

fn walk(dir: &Path, out: &mut Vec<PathBuf>, errors: &mut Vec<String>) {
    let rd = match fs::read_dir(dir) {
        Ok(rd) => rd,
        Err(e) => {
            errors.push(format!("{}: cannot read directory: {e}", dir.display()));
            return;
        }
    };
    for entry in rd.flatten() {
        let path = entry.path();
        match entry.file_type() {
            Ok(t) if t.is_dir() => walk(&path, out, errors),
            Ok(t)
                if t.is_file()
                    && path
                        .extension()
                        .is_some_and(|e| e.eq_ignore_ascii_case("fx")) =>
            {
                out.push(path)
            }
            _ => {}
        }
    }
}

fn collect(paths: &[PathBuf], errors: &mut Vec<String>) -> Vec<Found> {
    let mut found = Vec::new();
    for root in paths {
        if root.is_dir() {
            let mut files = Vec::new();
            walk(root, &mut files, errors);
            let base = root_label(root);
            for f in files {
                let rel = f.strip_prefix(root).map(slashed).unwrap_or_default();
                let label = if base.is_empty() {
                    rel
                } else {
                    format!("{base}/{rel}")
                };
                found.push(Found { path: f, label });
            }
        } else if root.is_file() {
            found.push(Found {
                path: root.clone(),
                label: slashed(root),
            });
        } else {
            errors.push(format!("{}: no such file or directory", root.display()));
        }
    }
    found.sort_by(|a, b| a.label.cmp(&b.label));
    found.dedup_by(|a, b| a.label == b.label);
    found
}

/// Runs `f` over `0..n` on `jobs` threads with large stacks (macro expansion and vkd3d's
/// parser recurse) and returns the results in index order.
fn par_map<T: Send>(n: usize, jobs: usize, f: impl Fn(usize) -> T + Sync) -> Vec<Option<T>> {
    let next = AtomicUsize::new(0);
    let out: Mutex<Vec<Option<T>>> = Mutex::new((0..n).map(|_| None).collect());
    std::thread::scope(|s| {
        for _ in 0..jobs.min(n.max(1)) {
            let r = std::thread::Builder::new()
                .stack_size(64 << 20)
                .spawn_scoped(s, || loop {
                    let i = next.fetch_add(1, Ordering::Relaxed);
                    if i >= n {
                        break;
                    }
                    let v = f(i);
                    if let Ok(mut g) = out.lock() {
                        g[i] = Some(v);
                    }
                });
            if r.is_err() {
                eprintln!("error: cannot start a worker thread");
            }
        }
    });
    out.into_inner().unwrap_or_default()
}

struct Job<'a> {
    label: &'a str,
    fx: &'a Effect,
    entry: Entry,
}

struct Done {
    compiled: Compiled,
    time: Duration,
    reflection: Option<Result<reflect::Reflection, String>>,
    reparsed: Option<Result<naga::Module, String>>,
}

fn percentile(sorted: &[Duration], p: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    // nearest rank
    let rank = ((p / 100.0) * sorted.len() as f64).ceil().max(1.0) as usize;
    sorted[rank.min(sorted.len()) - 1].as_secs_f64() * 1000.0
}

fn run(o: &Opts) -> Result<bool, String> {
    let vk = Vkd3d::load()?;
    eprintln!("vkd3d-shader {} from {}", vk.version(), vk.path().display());

    let mut walk_errors = Vec::new();
    let found = collect(&o.paths, &mut walk_errors);
    for e in &walk_errors {
        eprintln!("error: {e}");
    }
    // Resolve every #include, as `mds-fx scan` does by default and as the P2 prototype did.
    let opts = Options {
        strict_includes: true,
        ..Options::default()
    };
    let parsed: Vec<Option<Result<Effect, FxError>>> = par_map(found.len(), o.jobs, |i| {
        Effect::parse_file_with(&found[i].path, &opts)
    });
    let mut seen = HashSet::new();
    let mut jobs: Vec<Job> = Vec::new();
    let mut parse_failed = 0;
    for (f, r) in found.iter().zip(&parsed) {
        match r {
            Some(Ok(fx)) => {
                if seen.insert(fx.content_key()) {
                    jobs.extend(fx.entries().into_iter().map(|entry| Job {
                        label: &f.label,
                        fx,
                        entry,
                    }));
                }
            }
            Some(Err(e)) => {
                parse_failed += 1;
                eprintln!("error: {e}");
            }
            None => parse_failed += 1,
        }
    }
    jobs.sort_by(|a, b| {
        (
            a.label,
            &a.entry.profile,
            &a.entry.function,
            &a.entry.args_text,
        )
            .cmp(&(
                b.label,
                &b.entry.profile,
                &b.entry.function,
                &b.entry.args_text,
            ))
    });

    let done: Vec<Option<Done>> = par_map(jobs.len(), o.jobs, |i| {
        let j = &jobs[i];
        let t = Instant::now();
        let compiled = mds_shader::compile(&vk, j.fx, &j.entry, j.label);
        let time = t.elapsed();
        let reflection = (o.reflect && compiled.spirv.is_some()).then(|| {
            reflect::reflect(
                &vk,
                &compiled.source,
                j.label,
                &j.entry.profile,
                &compiled.entry_point,
            )
        });
        let reparsed = (o.reparse || o.wgpu)
            .then(|| compiled.outputs.as_ref().and_then(|x| x.wgsl.as_ref().ok()))
            .flatten()
            .map(|w| backend::reparse_wgsl(w));
        Done {
            compiled,
            time,
            reflection,
            reparsed,
        }
    });

    if let Some(dir) = &o.emit {
        fs::create_dir_all(dir).map_err(|e| format!("{}: {e}", dir.display()))?;
        let mut index = String::new();
        for (i, (j, d)) in jobs.iter().zip(&done).enumerate() {
            let Some(d) = d else { continue };
            let c = &d.compiled;
            let e = &j.entry;
            index.push_str(&format!(
                "{i:04}\t{}\t{}\t{}\t{}\t{}\t{}\n",
                j.label,
                e.profile,
                e.function,
                e.args_text,
                c.entry_point,
                c.status.as_str()
            ));
            let w = |ext: &str, s: &str| fs::write(dir.join(format!("{i:04}.{ext}")), s);
            let mut r = w("in.hlsl", &c.source);
            if let Some(out) = &c.outputs {
                for (ext, s) in [
                    ("wgsl", &out.wgsl),
                    ("metal", &out.msl),
                    ("hlsl", &out.hlsl),
                ] {
                    if let Ok(s) = s {
                        r = r.and(w(ext, s));
                    }
                }
            }
            r.map_err(|e| format!("{}: {e}", dir.display()))?;
        }
        fs::write(dir.join("index.tsv"), index).map_err(|e| format!("{}: {e}", dir.display()))?;
    }

    let (mut spirv, mut wgsl, mut msl, mut hlsl, mut ok, mut stripped) = (0, 0, 0, 0, 0, 0);
    let (mut reparse_ok, mut reparse_fail) = (0, 0);
    let mut times = Vec::new();
    for (j, d) in jobs.iter().zip(&done) {
        let Some(d) = d else {
            eprintln!(
                "error: {} {}: shader was not compiled",
                j.label, j.entry.function
            );
            continue;
        };
        let c = &d.compiled;
        times.push(d.time);
        spirv += c.spirv.is_some() as usize;
        stripped += c.point_size_removed as usize;
        ok += (c.status == Status::Ok) as usize;
        if let Some(out) = &c.outputs {
            wgsl += out.wgsl.is_ok() as usize;
            msl += out.msl.is_ok() as usize;
            hlsl += out.hlsl.is_ok() as usize;
        }
        let e = &j.entry;
        let row = format!(
            "{}\t{}\t{}\t{}",
            j.label, e.profile, e.function, e.args_text
        );
        if o.list {
            println!("{row}\t{}", c.status.as_str());
        }
        if o.errors {
            if let Some(err) = &c.error {
                println!("error\t{row}\t{}", err.lines().next().unwrap_or(""));
            }
        }
        if let Some(r) = &d.reflection {
            match r {
                Ok(r) => {
                    let regs: Vec<String> = r.constants.iter().map(|c| c.to_string()).collect();
                    println!("reflect\t{row}\t{}\t{}", r.source.as_str(), regs.join(" "));
                }
                Err(err) => println!("reflect\t{row}\tnone\t{err}"),
            }
        }
        if o.reparse {
            match &d.reparsed {
                Some(Ok(_)) => reparse_ok += 1,
                Some(Err(err)) => {
                    reparse_fail += 1;
                    println!("reparse-fail\t{row}\t{}", err.lines().next().unwrap_or(""));
                }
                None => {}
            }
        }
    }
    times.sort();
    println!(
        "shaders {} spirv {spirv} wgsl {wgsl} msl {msl} hlsl {hlsl}",
        jobs.len()
    );
    println!(
        "ok {ok} point-size-removed {stripped} files {} parse-failed {parse_failed} unique-files {}",
        found.len(),
        seen.len()
    );
    println!(
        "time per shader: median {:.2} ms p95 {:.2} ms max {:.2} ms (n {}, -j {})",
        percentile(&times, 50.0),
        percentile(&times, 95.0),
        percentile(&times, 100.0),
        times.len(),
        o.jobs
    );
    if o.reparse {
        println!("wgsl reparse ok {reparse_ok} fail {reparse_fail}");
    }
    let mut good = reparse_fail == 0;

    if o.wgpu {
        let g = gpu::Gpu::new()?;
        println!("wgpu adapter: {}", g.adapter);
        let (mut modules, mut fails) = (0, 0);
        for (j, d) in jobs.iter().zip(&done) {
            let Some(d) = d else { continue };
            let (Some(out), Some(Ok(parsed))) = (&d.compiled.outputs, &d.reparsed) else {
                continue;
            };
            let Ok(w) = &out.wgsl else { continue };
            let Some(stage) = Stage::of_profile(&j.entry.profile) else {
                continue;
            };
            modules += 1;
            let label = format!("{} {} {}", j.label, j.entry.profile, j.entry.function);
            if let Err(e) = g.check(&label, w, parsed, stage) {
                fails += 1;
                println!(
                    "wgpu-fail\t{}\t{}\t{}\t{}\t{}",
                    j.label,
                    j.entry.profile,
                    j.entry.function,
                    j.entry.args_text,
                    e.lines().next().unwrap_or("")
                );
                for l in e.lines().skip(1).take(6) {
                    println!("wgpu-fail\t  {l}");
                }
            }
        }
        println!(
            "wgpu modules {modules} pipelines {} failed {fails}",
            modules - fails
        );
        good &= fails == 0;
    }
    Ok(good)
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("corpus") => match parse_args(&args[1..]) {
            Ok(o) => match run(&o) {
                Ok(true) => ExitCode::SUCCESS,
                Ok(false) => ExitCode::from(1),
                Err(e) => {
                    eprintln!("error: {e}");
                    ExitCode::from(1)
                }
            },
            Err(m) => {
                eprintln!("error: {m}\n\n{USAGE}");
                ExitCode::from(2)
            }
        },
        Some("-h" | "--help") => {
            print!("{USAGE}");
            ExitCode::SUCCESS
        }
        _ => {
            eprint!("{USAGE}");
            ExitCode::from(2)
        }
    }
}
