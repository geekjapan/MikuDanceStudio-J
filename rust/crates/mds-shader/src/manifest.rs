//! Versioned TSV contracts. Each cell percent-escapes %, tab, CR, and LF.
use std::fmt::Write;
use std::path::Path;

use super::{Done, Job};

fn cell(s: &str) -> String {
    s.replace('%', "%25")
        .replace('\t', "%09")
        .replace('\r', "%0D")
        .replace('\n', "%0A")
}

// FNV-1a is fixed here rather than using Rust's unspecified DefaultHasher algorithm.
fn fingerprint(source: &str) -> String {
    let hash = source.bytes().fold(0xcbf29ce484222325u64, |h, b| {
        (h ^ u64::from(b)).wrapping_mul(0x100000001b3)
    });
    format!("fnv1a64:{hash:016x}")
}

fn result<T>(r: Option<&Result<T, String>>, ok: impl FnOnce(&T) -> String) -> String {
    match r {
        Some(Ok(v)) => format!("OK {}", ok(v)),
        Some(Err(e)) => format!("ERR {e}"),
        None => "UNAVAILABLE".into(),
    }
}

pub(super) fn write(
    path: &Path,
    version: &str,
    jobs: &[Job<'_>],
    done: &[Option<Done>],
) -> Result<(), String> {
    let mut text = String::from("mds-shader-contracts-v1\n");
    writeln!(text, "compiler\t{}", cell(version)).unwrap();
    text.push_str("file\tprofile\tentry\targs\tsource_hash\tspirv\twgsl\tmsl\thlsl\tscan\treflection\tcoverage\tprobe\treparse\treflection_origin\terror\n");
    for (j, d) in jobs.iter().zip(done) {
        let d = d.as_ref().ok_or("missing shader result")?;
        let c = &d.compiled;
        let source = j.fx.shader_source();
        let output = |pick: fn(&mds_shader::Outputs) -> &Result<String, String>| {
            result(c.outputs.as_ref().map(pick), |_| String::new())
        };
        let scan = result(d.scan.as_ref(), |s| {
            let mut rows = Vec::new();
            for (direction, list) in [("in", &s.inputs), ("out", &s.outputs)] {
                for e in list {
                    rows.push(format!(
                        "{direction}:{}:{}:{}:{}:{}",
                        e.semantic, e.index, e.register, e.sysval, e.mask
                    ));
                }
            }
            for e in &s.descriptors {
                rows.push(format!(
                    "descriptor:{}:{}:{}",
                    e.kind, e.register, e.resource
                ));
            }
            rows.sort();
            rows.join(";")
        });
        let constants = |cs: &[mds_shader::ctab::Constant]| {
            let mut rows: Vec<_> = cs.iter().map(ToString::to_string).collect();
            rows.sort();
            rows.join(";")
        };
        let reflection = result(d.reflection.as_ref(), |r| constants(&r.constants));
        let probe = result(d.probe.as_ref(), |p| constants(p));
        let row = [
            j.label.to_string(),
            j.entry.profile.clone(),
            j.entry.function.clone(),
            j.entry.args_text.clone(),
            fingerprint(source),
            if c.spirv.is_some() {
                "OK ".into()
            } else {
                "UNAVAILABLE".into()
            },
            output(|o| &o.wgsl),
            output(|o| &o.msl),
            output(|o| &o.hlsl),
            scan,
            reflection,
            result(d.coverage.as_ref(), |_| String::new()),
            probe,
            result(d.reparsed.as_ref(), |_| String::new()),
            match &d.reflection {
                Some(Ok(r)) => r.source.as_str().into(),
                _ => "none".into(),
            },
            c.error.clone().unwrap_or_default(),
        ];
        writeln!(
            text,
            "{}",
            row.iter().map(|s| cell(s)).collect::<Vec<_>>().join("\t")
        )
        .unwrap();
    }
    std::fs::write(path, text).map_err(|e| format!("{}: {e}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_identity_is_fixed_and_sensitive_to_content() {
        assert_eq!(fingerprint("hello"), "fnv1a64:a430d84680aabd0b");
        assert_ne!(fingerprint("hello"), fingerprint("hello\n"));
        assert_eq!(cell("a\t%\n"), "a%09%25%0A");
    }
}
