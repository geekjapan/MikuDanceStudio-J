//! Test helper: a temporary directory tree that deletes itself.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};

static COUNTER: AtomicU32 = AtomicU32::new(0);

pub struct TempTree {
    root: PathBuf,
}

impl TempTree {
    pub fn new() -> Self {
        let n = COUNTER.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!("mds-fx-test-{}-{n}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        TempTree { root }
    }

    pub fn write(&self, rel: &str, bytes: &[u8]) {
        let p = self.root.join(rel);
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        fs::write(p, bytes).unwrap();
    }

    pub fn path(&self, rel: &str) -> PathBuf {
        self.root.join(rel)
    }

    pub fn root(&self) -> &Path {
        &self.root
    }
}

impl Drop for TempTree {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}
