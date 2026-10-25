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

/// The plan of `effect`, with paths below `root` written as `<root>/...`, on the oracle's
/// 1000x600 back buffer.
pub fn plan(effect: &Path, root: &Path) -> String {
    plan_at(effect, root, sas::BACKBUFFER)
}

/// [`plan`] on a device whose back buffer is `backbuffer` (width, height).
pub fn plan_at(effect: &Path, root: &Path, backbuffer: (i32, i32)) -> String {
    let rel = effect
        .strip_prefix(root)
        .unwrap_or(effect)
        .to_string_lossy()
        .replace('\\', "/");
    let path = format!("<root>/{rel}");
    let dir = rel.rsplit_once('/').map_or("", |(d, _)| d).to_string();
    let loc = sas::Location {
        root,
        dir,
        backbuffer,
    };
    let loaded = match mds_fx::Effect::parse_file(effect) {
        Ok(e) => sas::parse(fx::Fx::new(&e), &path, &loc),
        // ponytail: D3DX compiler messages are not reproduced; no plan has one.
        Err(e) => Err(format!("{e}\n")),
    };
    plan::write(&path, loaded)
}
