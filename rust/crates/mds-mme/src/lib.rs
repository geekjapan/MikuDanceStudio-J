//! The planning layer of the MME runtime (`third_party/mmeffect`) in Rust, on top of the
//! mds-fx parser: what `MmeEngineLoadEffectFile` decides for an effect file, the draw
//! technique table, and an interpreted run of every technique script.
//!
//! [`plan`] writes the same text as `tools/oracle/mme_passplan.cpp`, so the two compare line
//! by line (`tests/fixtures/rust/mme/`).

pub mod fx;
pub mod plan;
pub mod run;
pub mod sas;
mod texfile;

use std::path::Path;

/// The plan of `effect`, with paths below `root` written as `<root>/...`.
pub fn plan(effect: &Path, root: &Path) -> String {
    let rel = effect
        .strip_prefix(root)
        .unwrap_or(effect)
        .to_string_lossy()
        .replace('\\', "/");
    let path = format!("<root>/{rel}");
    let dir = rel.rsplit_once('/').map_or("", |(d, _)| d).to_string();
    let loc = sas::Location { root, dir };
    let loaded = match mds_fx::Effect::parse_file(effect) {
        Ok(e) => sas::parse(fx::Fx::new(&e), &path, &loc),
        // ponytail: D3DX compiler messages are not reproduced; no plan has one.
        Err(e) => Err(format!("{e}\n")),
    };
    plan::write(&path, loaded)
}
