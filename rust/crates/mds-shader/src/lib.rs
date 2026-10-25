//! Compiles the shader entries of MikuMikuEffect files to WGSL, MSL, and HLSL.
//!
//! The pipeline per entry follows the P2 prototype (`docs/prototypes/p2-mme`):
//!
//! 1. [`mds_fx::Effect::wrapper`] gives the technique-free source and the entry point.
//! 2. [`fix_sampler2d`] rewrites `sampler2D` parameters to `sampler`.
//! 3. vkd3d-shader compiles the HLSL straight to SPIR-V ([`vkd3d`]). On E5027 the compile runs
//!    once more on the source with [`guard_pow`].
//! 4. [`spirv_fix::strip_point_size`] removes the `PointSize` output.
//! 5. naga validates the module and writes WGSL, MSL, and HLSL ([`backend`]).
//!
//! [`reflect`] maps each parameter to its constant register.
//!
//! Known vkd3d-shader 2.1 limits, measured over the ray-mmd corpus by `tests/corpus.rs`:
//!
//! - E9022: an sm3 pixel shader that reads `VPOS` (or `SV_Position`) and other inputs fails, or,
//!   when `VPOS` is its first input, reads `VPOS` where it reads `v0`. The I/O normaliser looks
//!   up its own `vPos` read by element index as a register, and `v#` reads match the `MISCTYPE`
//!   elements. `tools/vkd3d/patches/0001-vpos-vface-io.patch` (LGPL-2.1, like vkd3d) fixes both;
//!   `tools/vkd3d/build.sh` applies it to every target.
//! - E9015: the D3D bytecode writer, which the D3D bytecode and assembly targets go through,
//!   rejects more than 32 temps, and vkd3d's allocator uses more than fxc's for some shaders.
//!   SPIR-V is unaffected; [`vkd3d::Vkd3d::scan_hlsl`] gives the I/O declarations that the
//!   assembly listing would.

pub mod backend;
pub mod ctab;
pub mod gpu;
pub mod reflect;
pub mod spirv_fix;
pub mod vkd3d;

use std::time::{Duration, Instant};

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

/// Choices of [`compile_with`].
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Options {
    /// Flip the Y of the vertex `Position` output, as naga-cli does by default
    /// (`adjust_coordinate_space` of naga's SPIR-V reader). vkd3d writes D3D clip space, which
    /// wgpu shares, so a wgpu runtime turns this off.
    pub flip_y: bool,
}

impl Default for Options {
    fn default() -> Options {
        Options { flip_y: true }
    }
}

/// What one entry produced.
pub struct Compiled {
    pub status: Status,
    /// The HLSL that went to vkd3d-shader, with [`guard_pow`] when the first try failed with
    /// E5027. Compile it again for the D3D targets.
    pub source: String,
    pub entry_point: String,
    /// SPIR-V after the `PointSize` removal.
    pub spirv: Option<Vec<u32>>,
    pub point_size_removed: bool,
    pub outputs: Option<Outputs>,
    /// Time spent in `vkd3d_shader_compile`.
    pub vkd3d_time: Duration,
    /// The first error, when the status is not [`Status::Ok`].
    pub error: Option<String>,
    /// The error of the first vkd3d try, when a second try ran on a rewritten source.
    pub first_error: Option<String>,
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
            vkd3d_time: Duration::ZERO,
            error: Some(error),
            first_error: None,
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

/// Clamps the base of every `pow(x, y)` call: `pow(max(x, FLT_MIN), y)`.
///
/// vkd3d-shader lowers `pow` to `exp2(y * log2(x))` and, below shader model 4, rejects the
/// infinite `log2` of a constant 0 base when it folds constants (E5027), although the folded
/// result is 0. With the clamp a 0 base folds to 0 for a positive exponent. Other bases below
/// `FLT_MIN`, negative ones included, change too, so [`compile`] uses this only when the source
/// failed with E5027.
pub fn guard_pow(src: &str) -> String {
    const CLAMP: &str = ", 1.175494351e-38)";
    let b = src.as_bytes();
    let mut out = String::with_capacity(src.len());
    let mut pos = 0;
    let mut i = 0;
    let mut in_string = false;
    while i < b.len() {
        if b[i] == b'"' {
            in_string = !in_string;
        }
        let call = !in_string
            && b[i..].starts_with(b"pow")
            && (i == 0 || !is_word(b[i - 1]))
            && b.get(i + 3).is_some_and(|&c| !is_word(c));
        if !call {
            i += 1;
            continue;
        }
        let mut j = i + 3;
        while j < b.len() && b[j].is_ascii_whitespace() {
            j += 1;
        }
        if b.get(j) != Some(&b'(') {
            i += 3;
            continue;
        }
        let arg = j + 1;
        let (mut depth, mut k) = (0i32, arg);
        while k < b.len() {
            match b[k] {
                b'(' | b'[' => depth += 1,
                b')' | b']' => depth -= 1,
                b',' if depth == 0 => break,
                _ => {}
            }
            if depth < 0 {
                break;
            }
            k += 1;
        }
        if k < b.len() && b[k] == b',' {
            out.push_str(&src[pos..arg]);
            out.push_str("max(");
            out.push_str(&src[arg..k]);
            out.push_str(CLAMP);
            pos = k;
        }
        i = arg;
    }
    out.push_str(&src[pos..]);
    out
}

fn is_e5027(e: &vkd3d::CompileError) -> bool {
    e.summary().starts_with("E5027")
}

/// The source to compile for `entry`: the wrapper source with the `sampler2D` fix.
pub fn entry_source(fx: &Effect, entry: &Entry) -> Result<(String, String), String> {
    let w = fx.wrapper(entry).map_err(|e| e.to_string())?;
    Ok((fix_sampler2d(&w.source), w.entry_point))
}

/// Compiles one entry of `fx` through the whole pipeline with the default [`Options`]. `name`
/// labels the source in vkd3d messages.
pub fn compile(vk: &Vkd3d, fx: &Effect, entry: &Entry, name: &str) -> Compiled {
    compile_with(vk, fx, entry, name, &Options::default())
}

pub fn compile_with(
    vk: &Vkd3d,
    fx: &Effect,
    entry: &Entry,
    name: &str,
    opts: &Options,
) -> Compiled {
    let (mut source, ep) = match entry_source(fx, entry) {
        Ok(s) => s,
        Err(e) => return Compiled::fail(Status::Fail, String::new(), String::new(), e),
    };
    let t = Instant::now();
    let mut compiled = vk.compile_hlsl(&source, name, &entry.profile, &ep, Target::SpirvBinary);
    let mut first_error = None;
    if let Err(e) = compiled.as_ref() {
        if is_e5027(e) {
            first_error = Some(e.summary());
            source = guard_pow(&source);
            compiled = vk.compile_hlsl(&source, name, &entry.profile, &ep, Target::SpirvBinary);
        }
    }
    let vkd3d_time = t.elapsed();
    let bytes = match compiled {
        Ok(b) => b,
        Err(e) => {
            let mut c = Compiled::fail(Status::Fail, source, ep, e.summary());
            c.vkd3d_time = vkd3d_time;
            c.first_error = first_error;
            return c;
        }
    };
    let fixed = spirv_fix::words(&bytes).and_then(|w| spirv_fix::strip_point_size(&w));
    let (words, removed) = match fixed {
        Ok(x) => x,
        Err(e) => {
            let mut c = Compiled::fail(Status::Fail, source, ep, e);
            c.first_error = first_error;
            return c;
        }
    };
    let module = match backend::parse_spirv(&words, opts.flip_y) {
        Ok(m) => m,
        Err(e) => {
            let mut c = Compiled::fail(Status::NagaFail, source, ep, e);
            c.spirv = Some(words);
            c.point_size_removed = removed;
            c.vkd3d_time = vkd3d_time;
            c.first_error = first_error;
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
        vkd3d_time,
        error,
        first_error,
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
    fn guard_pow_clamps_the_base() {
        assert_eq!(
            guard_pow("float4(pow(c, 2.2), 0) + pow (f(a, b)[i], y) + mypow(x, 2) + pow(x)"),
            "float4(pow(max(c, 1.175494351e-38), 2.2), 0) + pow (max(f(a, b)[i], 1.175494351e-38), y) + mypow(x, 2) + pow(x)"
        );
        assert_eq!(
            guard_pow("string s = \"pow(a, b)\"; pow"),
            "string s = \"pow(a, b)\"; pow"
        );
    }

    #[test]
    fn stage_of_profile() {
        assert_eq!(Stage::of_profile("vs_3_0"), Some(Stage::Vertex));
        assert_eq!(Stage::of_profile("ps_2_0"), Some(Stage::Fragment));
        assert_eq!(Stage::of_profile("fx_2_0"), None);
    }
}
