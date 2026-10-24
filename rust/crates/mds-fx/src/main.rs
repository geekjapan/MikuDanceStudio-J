//! `mds-fx scan <path>...`: parse every `.fx` file below the paths and print counts.

use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

use mds_fx::{Effect, Entry, FxError, Include, Options, Via};

const USAGE: &str = "\
usage: mds-fx scan [options] <path>...
       mds-fx pp <file>        print the preprocessed text of one file (debugging)

Parses every .fx file below each directory (or the file itself), and prints the number of
files, techniques, and unique entries. Files with the same preprocessed content count once.

options:
  --entries     print one tab-separated line per unique entry (path, profile, function, args)
  --files       print one line per file with its technique, pass, and entry counts
  --includes    print one line per resolved #include
  --no-mipmap   do not define MME_MIPMAP
  --lazy-includes   skip #include lines in disabled #if branches, as D3DX does
                (default: resolve them too, so the scan reports dangling includes)
  -j <n>        worker threads (default: all CPUs, at most 8)

exit status: 0 when every file parses, 1 when some file fails, 2 on a usage error.
";

struct Opts {
    entries: bool,
    files: bool,
    includes: bool,
    mip: bool,
    strict: bool,
    jobs: usize,
    paths: Vec<PathBuf>,
}

fn parse_args(args: &[String]) -> Result<Opts, String> {
    let mut o = Opts {
        entries: false,
        files: false,
        includes: false,
        mip: true,
        strict: true,
        jobs: std::thread::available_parallelism()
            .map_or(1, |n| n.get())
            .min(8),
        paths: Vec::new(),
    };
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--entries" => o.entries = true,
            "--files" => o.files = true,
            "--includes" => o.includes = true,
            "--no-mipmap" => o.mip = false,
            "--lazy-includes" => o.strict = false,
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

/// The name a file prints under: relative arguments print as given, absolute ones by the
/// directory's own name, so `.../mds-corpus/ray-mmd` prints as `ray-mmd/...`.
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

fn is_fx(p: &Path) -> bool {
    p.extension().is_some_and(|e| e.eq_ignore_ascii_case("fx"))
}

fn walk(dir: &Path, out: &mut Vec<PathBuf>, errors: &mut Vec<FxError>) {
    let rd = match fs::read_dir(dir) {
        Ok(rd) => rd,
        Err(e) => {
            errors.push(FxError::new(dir, 0, format!("cannot read directory: {e}")));
            return;
        }
    };
    for entry in rd.flatten() {
        let path = entry.path();
        match entry.file_type() {
            Ok(t) if t.is_dir() => walk(&path, out, errors),
            Ok(t) if t.is_file() && is_fx(&path) => out.push(path),
            _ => {}
        }
    }
}

fn collect(paths: &[PathBuf], errors: &mut Vec<FxError>) -> Vec<Found> {
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
        } else {
            found.push(Found {
                path: root.clone(),
                label: slashed(root),
            });
        }
    }
    found.sort_by(|a, b| a.label.cmp(&b.label));
    found.dedup_by(|a, b| a.label == b.label);
    found
}

struct Parsed {
    key: u64,
    techniques: usize,
    passes: usize,
    entries: Vec<Entry>,
    wrapper_errors: Vec<String>,
}

/// What one file gave: the parse result, and the includes resolved on the way. On a failure
/// the includes are the ones resolved before it.
struct Outcome {
    result: Result<Parsed, FxError>,
    includes: Vec<Include>,
}

fn scan_one(path: &Path, opts: &Options) -> Outcome {
    match Effect::parse_file_with(path, opts) {
        Ok(fx) => {
            let entries = fx.entries();
            let wrapper_errors = entries
                .iter()
                .filter_map(|e| fx.wrapper(e).err())
                .map(|e| e.to_string())
                .collect();
            Outcome {
                includes: fx.includes().to_vec(),
                result: Ok(Parsed {
                    key: fx.content_key(),
                    techniques: fx.ast.techniques.len(),
                    passes: fx.ast.pass_count(),
                    entries,
                    wrapper_errors,
                }),
            }
        }
        Err(e) => {
            let includes = fs::read(path)
                .map(|b| mds_fx::preprocess::resolved_includes(path, &b, opts))
                .unwrap_or_default();
            Outcome {
                result: Err(e),
                includes,
            }
        }
    }
}

fn scan(o: &Opts) -> ExitCode {
    let mut walk_errors = Vec::new();
    let found = collect(&o.paths, &mut walk_errors);
    let opts = Options {
        mip_filter: o.mip,
        strict_includes: o.strict,
        ..Options::default()
    };

    // Parse on worker threads; keep results in file order so output is deterministic.
    let next = AtomicUsize::new(0);
    let results: Mutex<Vec<Option<Outcome>>> = Mutex::new((0..found.len()).map(|_| None).collect());
    std::thread::scope(|s| {
        for _ in 0..o.jobs.min(found.len().max(1)) {
            // Macro expansion recurses, so give workers a large stack.
            let worker = std::thread::Builder::new()
                .stack_size(64 << 20)
                .spawn_scoped(s, || loop {
                    let i = next.fetch_add(1, Ordering::Relaxed);
                    let Some(f) = found.get(i) else { break };
                    let r = scan_one(&f.path, &opts);
                    if let Ok(mut g) = results.lock() {
                        g[i] = Some(r);
                    }
                });
            if worker.is_err() {
                eprintln!("error: cannot start a worker thread");
            }
        }
    });
    let results = results.into_inner().unwrap_or_default();

    let mut failed = walk_errors.len();
    for e in &walk_errors {
        eprintln!("error: {e}");
    }
    let mut seen: HashSet<u64> = HashSet::new();
    let (mut unique, mut techniques, mut passes, mut wrapper_failed) =
        (0usize, 0usize, 0usize, 0usize);
    let (mut inc_top, mut inc_nested) = (0usize, 0usize);
    let mut rows: Vec<(String, Entry)> = Vec::new();
    for (f, r) in found.iter().zip(results) {
        let Some(out) = r else {
            failed += 1;
            eprintln!("error: {}: file was not scanned", f.label);
            continue;
        };
        for i in &out.includes {
            match i.via {
                Via::TopLevelDir => inc_top += 1,
                Via::IncludingDir => inc_nested += 1,
            }
            if o.includes {
                println!(
                    "include\t{}\t{}:{}\t{}\t{:?}\t{}",
                    f.label,
                    i.from_path.display(),
                    i.from.line,
                    i.name,
                    i.via,
                    i.resolved.display()
                );
            }
        }
        match out.result {
            Ok(p) => {
                if o.files {
                    println!(
                        "ok\t{}\t{}\t{}\t{}\t{:016x}",
                        f.label,
                        p.techniques,
                        p.passes,
                        p.entries.len(),
                        p.key
                    );
                }
                for w in &p.wrapper_errors {
                    eprintln!("wrapper error: {w}");
                    wrapper_failed += 1;
                }
                if seen.insert(p.key) {
                    unique += 1;
                    techniques += p.techniques;
                    passes += p.passes;
                    rows.extend(p.entries.into_iter().map(|e| (f.label.clone(), e)));
                }
            }
            Err(e) => {
                failed += 1;
                if o.files {
                    println!("err\t{}\t{}", f.label, e.message);
                }
                eprintln!("error: {e}");
            }
        }
    }
    rows.sort_by(|a, b| {
        (&a.0, &a.1.profile, &a.1.function, &a.1.args_text).cmp(&(
            &b.0,
            &b.1.profile,
            &b.1.function,
            &b.1.args_text,
        ))
    });
    if o.entries {
        for (label, e) in &rows {
            println!("{label}\t{}\t{}\t{}", e.profile, e.function, e.args_text);
        }
    }
    let summary = format!(
        "files: {}\nparsed: {}\nfailed: {failed}\nunique files: {unique}\ntechniques: {techniques}\npasses: {passes}\nunique entries: {}\n\
         includes: {} (top-level dir {inc_top}, including dir {inc_nested})\nwrapper errors: {wrapper_failed}\n",
        found.len(),
        found.len() + walk_errors.len() - failed,
        rows.len(),
        inc_top + inc_nested,
    );
    if o.entries {
        eprint!("{summary}");
    } else {
        print!("{summary}");
    }
    if failed > 0 || wrapper_failed > 0 {
        ExitCode::from(1)
    } else {
        ExitCode::SUCCESS
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("scan") => match parse_args(&args[1..]) {
            Ok(o) => scan(&o),
            Err(m) => {
                eprintln!("error: {m}\n\n{USAGE}");
                ExitCode::from(2)
            }
        },
        Some("pp") => match args.get(1) {
            // debugging aid: print the preprocessed text of one file
            Some(f) => match mds_fx::preprocess::preprocess_file(
                Path::new(f),
                &Options {
                    strict_includes: true,
                    ..Options::default()
                },
            ) {
                Ok(p) => {
                    print!("{}", p.text);
                    ExitCode::SUCCESS
                }
                Err(e) => {
                    eprintln!("error: {e}");
                    ExitCode::from(1)
                }
            },
            None => {
                eprint!("{USAGE}");
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
