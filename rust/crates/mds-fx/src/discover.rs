//! Finding `.fx` files below command-line paths, and the labels they print under.

use std::fs;
use std::path::{Path, PathBuf};

use crate::FxError;

/// An effect file and the name it prints under.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Found {
    pub path: PathBuf,
    pub label: String,
}

/// Every `.fx` file below the directories in `paths`, and the files named in `paths`
/// themselves, sorted by label with equal labels dropped. A path that is neither a directory
/// nor readable as one comes back as a file, so that parsing it reports the error. Unreadable
/// directories go to the second list.
pub fn discover(paths: &[PathBuf]) -> (Vec<Found>, Vec<FxError>) {
    let mut found = Vec::new();
    let mut errors = Vec::new();
    for root in paths {
        if root.is_dir() {
            let mut files = Vec::new();
            walk(root, &mut files, &mut errors);
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
    (found, errors)
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::TempTree;

    #[test]
    fn a_directory_prints_under_its_own_name_and_finds_fx_files_at_any_depth() {
        let t = TempTree::new();
        t.write("a/Main.FX", b"");
        t.write("a/sub/b.fx", b"");
        t.write("a/skip.fxsub", b"");
        let (found, errors) = discover(&[t.path("a")]);
        assert!(errors.is_empty());
        let got: Vec<_> = found.iter().map(|f| f.label.as_str()).collect();
        assert_eq!(got, ["a/Main.FX", "a/sub/b.fx"]);
        assert_eq!(found[1].path, t.path("a/sub/b.fx"));
    }

    #[test]
    fn named_files_print_by_their_path_and_repeats_collapse() {
        let t = TempTree::new();
        t.write("c.fx", b"");
        let missing = t.path("missing.fx");
        let (found, errors) = discover(&[t.path("c.fx"), missing.clone(), t.path("c.fx")]);
        assert!(errors.is_empty());
        let paths: Vec<_> = found.iter().map(|f| f.path.clone()).collect();
        assert_eq!(paths, [t.path("c.fx"), missing]);
        assert_eq!(found[0].label, slashed(&t.path("c.fx")));
    }

    #[test]
    fn relative_roots_print_as_given() {
        assert_eq!(root_label(Path::new("res/assets")), "res/assets");
    }
}
