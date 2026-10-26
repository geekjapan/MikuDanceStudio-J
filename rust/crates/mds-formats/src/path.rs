//! Filesystem lookup for Windows asset names without changing stored paths.

use std::fs;
use std::path::{Path, PathBuf};

/// Resolves `rel` below `base`. Parts match without case, `\` counts as `/`. An exact-case
/// entry wins over a case-folded one, so the result does not depend on the file system.
pub fn resolve_ci(base: &Path, rel: &str) -> Option<PathBuf> {
    let mut cur = if base.as_os_str().is_empty() {
        PathBuf::from(".")
    } else {
        base.to_path_buf()
    };
    for part in rel.replace('\\', "/").split('/') {
        match part {
            "" | "." => {}
            ".." => {
                // step out of a real directory name, so paths read `Shader/x` and not `Shadow/../Shader/x`
                if matches!(
                    cur.components().next_back(),
                    Some(std::path::Component::Normal(_))
                ) {
                    cur.pop();
                } else {
                    cur.push("..");
                }
            }
            p => {
                let want = p.to_lowercase();
                let mut folded: Option<std::ffi::OsString> = None;
                let mut exact = None;
                for e in fs::read_dir(&cur).ok()? {
                    let name = e.ok()?.file_name();
                    let s = name.to_string_lossy();
                    if s == p {
                        exact = Some(name.clone());
                        break;
                    }
                    if s.to_lowercase() == want && folded.as_ref().is_none_or(|f| name < *f) {
                        folded = Some(name.clone());
                    }
                }
                cur.push(exact.or(folded)?);
            }
        }
    }
    cur.is_file().then_some(cur)
}

/// Resolves a complete host path through [`resolve_ci`], retaining its root or drive prefix.
pub fn resolve_path_ci(path: &Path) -> Option<PathBuf> {
    let root = path.ancestors().last().unwrap_or(Path::new("."));
    let relative = path.strip_prefix(root).ok()?.to_string_lossy();
    resolve_ci(root, &relative)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn windows_components_and_parent_lookup() {
        let dir = std::env::temp_dir().join(format!("mds-formats-path-{}", std::process::id()));
        fs::create_dir_all(dir.join("Sub/Deep")).unwrap();
        fs::write(dir.join("Sub/Mesh.X"), b"mesh").unwrap();
        assert_eq!(
            resolve_ci(&dir, "sub\\mesh.x"),
            Some(dir.join("Sub/Mesh.X"))
        );
        assert_eq!(
            resolve_ci(&dir.join("Sub/Deep"), "..\\MESH.x"),
            Some(dir.join("Sub/Mesh.X"))
        );
        assert_eq!(
            resolve_path_ci(&dir.join("sub/mesh.x")),
            Some(dir.join("Sub/Mesh.X"))
        );
        assert_eq!(resolve_ci(&dir, "sub"), None);
        assert_eq!(resolve_ci(&dir, "missing.x"), None);
        fs::remove_dir_all(dir).unwrap();
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn exact_case_wins_then_lexical_fallback() {
        let dir = std::env::temp_dir().join(format!("mds-formats-case-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        for name in ["Mesh.X", "mesh.x"] {
            fs::write(dir.join(name), name).unwrap();
        }
        assert_eq!(resolve_ci(&dir, "mesh.x"), Some(dir.join("mesh.x")));
        assert_eq!(resolve_ci(&dir, "MESH.X"), Some(dir.join("Mesh.X")));
        fs::remove_dir_all(dir).unwrap();
    }
}
