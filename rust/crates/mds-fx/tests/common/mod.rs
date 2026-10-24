#![allow(dead_code)]

use std::path::{Path, PathBuf};

pub const CORPUS_COMMIT: &str = "218a91cd1c53f49850b2772ebbcb98bf258e75b1";

/// `res/assets` of this repository, which holds the two standard effects.
pub fn repo_assets() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../res/assets")
}

/// The directory that holds the `ray-mmd` checkout: `$MDS_CORPUS`, or
/// `${TMPDIR:-/tmp}/mds-corpus`.
pub fn corpus_dir() -> PathBuf {
    match std::env::var_os("MDS_CORPUS") {
        Some(p) => PathBuf::from(p),
        None => std::env::temp_dir().join("mds-corpus"),
    }
}

/// Returns the corpus directory, or fails the test. A test that needs the corpus does not
/// skip when it is missing: a skipped check is not a pass.
pub fn require_corpus() -> PathBuf {
    let dir = corpus_dir();
    let ray = dir.join("ray-mmd");
    assert!(
        ray.is_dir(),
        "corpus not found at {}.\nFetch it with:\n  git clone https://github.com/ray-cast/ray-mmd {} && git -C {} checkout {CORPUS_COMMIT}\nor set MDS_CORPUS to the directory that holds ray-mmd.",
        ray.display(),
        ray.display(),
        ray.display(),
    );
    if let Ok(head) = std::fs::read_to_string(ray.join(".git/HEAD")) {
        assert_eq!(
            head.trim(),
            CORPUS_COMMIT,
            "the corpus at {} is not at the pinned commit",
            ray.display()
        );
    }
    dir
}

/// Every `.fx` file below `root`, sorted.
pub fn fx_files(root: &Path) -> Vec<PathBuf> {
    fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
        for e in std::fs::read_dir(dir).unwrap().flatten() {
            let p = e.path();
            let t = e.file_type().unwrap();
            if t.is_dir() {
                walk(&p, out);
            } else if t.is_file() && p.extension().is_some_and(|x| x.eq_ignore_ascii_case("fx")) {
                out.push(p);
            }
        }
    }
    let mut out = Vec::new();
    walk(root, &mut out);
    out.sort();
    out
}

/// Runs `f` on every item with `n` worker threads and returns the results in item order.
pub fn par_map<T: Sync, R: Send>(items: &[T], f: impl Fn(&T) -> R + Sync) -> Vec<R> {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Mutex;
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
