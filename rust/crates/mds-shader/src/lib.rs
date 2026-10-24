//! Compiles the shader entries of MikuMikuEffect files to WGSL, MSL, and HLSL.
//!
//! The pipeline per entry follows the P2 prototype (`docs/prototypes/p2-mme`):
//!
//! 1. [`mds_fx::Effect::wrapper`] gives the technique-free source and the entry point.
//! 2. [`fix_sampler2d`] rewrites `sampler2D` parameters to `sampler`.
//! 3. vkd3d-shader compiles the HLSL straight to SPIR-V ([`vkd3d`]).
//! 4. [`spirv_fix::strip_point_size`] removes the `PointSize` output.
//! 5. naga validates the module and writes WGSL, MSL, and HLSL ([`backend`]).
//!
//! [`reflect`] maps each parameter to its constant register.

pub mod backend;
pub mod ctab;
pub mod gpu;
pub mod reflect;
pub mod spirv_fix;
pub mod vkd3d;

use mds_fx::{Effect, Entry};

pub use backend::Outputs;
use vkd3d::{Target, Vkd3d};

/// Shader stage of a profile such as `vs_3_0`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Stage {
    Vertex,
    Fragment,
}

impl Stage {
    pub fn of_profile(profile: &str) -> Option<Stage> {
        match profile.get(..3) {
            Some("vs_") => Some(Stage::Vertex),
            Some("ps_") => Some(Stage::Fragment),
            _ => None,
        }
    }
}

/// Result word in `shaders-direct.tsv`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Status {
    /// SPIR-V and all three naga outputs exist.
    Ok,
    /// No SPIR-V: the wrapper or vkd3d-shader failed.
    Fail,
    /// SPIR-V exists but a naga step failed.
    NagaFail,
}

impl Status {
    pub fn as_str(self) -> &'static str {
        match self {
            Status::Ok => "OK",
            Status::Fail => "FAIL",
            Status::NagaFail => "NAGA_FAIL",
        }
    }
}

/// What one entry produced.
pub struct Compiled {
    pub status: Status,
    /// The HLSL that went to vkd3d-shader.
    pub source: String,
    pub entry_point: String,
    /// SPIR-V after the `PointSize` removal.
    pub spirv: Option<Vec<u32>>,
    pub point_size_removed: bool,
    pub outputs: Option<Outputs>,
    /// The first error, when the status is not [`Status::Ok`].
    pub error: Option<String>,
}

impl Compiled {
    fn fail(status: Status, source: String, entry_point: String, error: String) -> Compiled {
        Compiled {
            status,
            source,
            entry_point,
            spirv: None,
            point_size_removed: false,
            outputs: None,
            error: Some(error),
        }
    }
}

fn is_word(b: u8) -> bool {
    b.is_ascii_alphanumeric() || b == b'_'
}

/// Rewrites each `sampler2D` parameter (`sampler2D <name>` followed by `,` or `)`) to
/// `sampler`, which vkd3d-shader accepts where it rejects `sampler2D` arguments.
pub fn fix_sampler2d(src: &str) -> String {
    const KW: &str = "sampler2D";
    let b = src.as_bytes();
    let mut out = String::with_capacity(src.len());
    let mut pos = 0;
    let mut search = 0;
    while let Some(off) = src[search..].find(KW) {
        let at = search + off;
        search = at + KW.len();
        if at > 0 && is_word(b[at - 1]) {
            continue;
        }
        let mut i = at + KW.len();
        let ws = i;
        while i < b.len() && b[i].is_ascii_whitespace() {
            i += 1;
        }
        if i == ws {
            continue;
        }
        let name = i;
        while i < b.len() && is_word(b[i]) {
            i += 1;
        }
        if i == name {
            continue;
        }
        while i < b.len() && b[i].is_ascii_whitespace() {
            i += 1;
        }
        if i < b.len() && (b[i] == b',' || b[i] == b')') {
            out.push_str(&src[pos..at]);
            out.push_str("sampler");
            pos = at + KW.len();
        }
    }
    out.push_str(&src[pos..]);
    out
}

/// The source to compile for `entry`: the wrapper source with the `sampler2D` fix.
pub fn entry_source(fx: &Effect, entry: &Entry) -> Result<(String, String), String> {
    let w = fx.wrapper(entry).map_err(|e| e.to_string())?;
    Ok((fix_sampler2d(&w.source), w.entry_point))
}

/// Compiles one entry of `fx` through the whole pipeline. `name` labels the source in vkd3d
/// messages.
pub fn compile(vk: &Vkd3d, fx: &Effect, entry: &Entry, name: &str) -> Compiled {
    let (source, ep) = match entry_source(fx, entry) {
        Ok(s) => s,
        Err(e) => return Compiled::fail(Status::Fail, String::new(), String::new(), e),
    };
    let bytes = match vk.compile_hlsl(&source, name, &entry.profile, &ep, Target::SpirvBinary) {
        Ok(b) => b,
        Err(e) => return Compiled::fail(Status::Fail, source, ep, e.summary()),
    };
    let fixed = spirv_fix::words(&bytes).and_then(|w| spirv_fix::strip_point_size(&w));
    let (words, removed) = match fixed {
        Ok(x) => x,
        Err(e) => return Compiled::fail(Status::Fail, source, ep, e),
    };
    let module = match backend::parse_spirv(&words) {
        Ok(m) => m,
        Err(e) => {
            let mut c = Compiled::fail(Status::NagaFail, source, ep, e);
            c.spirv = Some(words);
            c.point_size_removed = removed;
            return c;
        }
    };
    let outputs = backend::translate(module);
    let error = [&outputs.wgsl, &outputs.msl, &outputs.hlsl]
        .into_iter()
        .find_map(|r| r.as_ref().err().cloned());
    Compiled {
        status: if error.is_none() {
            Status::Ok
        } else {
            Status::NagaFail
        },
        source,
        entry_point: ep,
        spirv: Some(words),
        point_size_removed: removed,
        outputs: Some(outputs),
        error,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sampler2d_parameters_become_sampler() {
        let src = "float4 F(sampler2D s, float2 uv, sampler2D t) : COLOR;\n\
                   sampler2D g = sampler_state { };\nfloat4 G(in sampler2D  s2 ) {}\nmysampler2D x, y;";
        assert_eq!(
            fix_sampler2d(src),
            "float4 F(sampler s, float2 uv, sampler t) : COLOR;\n\
             sampler2D g = sampler_state { };\nfloat4 G(in sampler  s2 ) {}\nmysampler2D x, y;"
        );
        assert_eq!(fix_sampler2d("sampler2D"), "sampler2D");
        assert_eq!(fix_sampler2d("(sampler2D a)"), "(sampler a)");
    }

    #[test]
    fn stage_of_profile() {
        assert_eq!(Stage::of_profile("vs_3_0"), Some(Stage::Vertex));
        assert_eq!(Stage::of_profile("ps_2_0"), Some(Stage::Fragment));
        assert_eq!(Stage::of_profile("fx_2_0"), None);
    }
}
