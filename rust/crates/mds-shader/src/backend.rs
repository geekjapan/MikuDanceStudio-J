//! SPIR-V to WGSL, MSL, and HLSL through naga, with the options `naga` (naga-cli 30.0.1) uses
//! for `naga in.spv out.<ext>`, which produced the P2 prototype counts.

use naga::back::{hlsl, msl, pipeline_constants, wgsl, PipelineConstants};
use naga::valid::{
    Capabilities, ModuleInfo, ShaderStages, SubgroupOperationSet, ValidationFlags, Validator,
};

/// The three outputs of one module. Each backend fails on its own.
pub struct Outputs {
    pub module: naga::Module,
    pub wgsl: Result<String, String>,
    pub msl: Result<String, String>,
    pub hlsl: Result<String, String>,
}

fn validate(module: &naga::Module, caps: Capabilities) -> Result<ModuleInfo, String> {
    Validator::new(ValidationFlags::all(), caps)
        .subgroup_stages(ShaderStages::all())
        .subgroup_operations(SubgroupOperationSet::all())
        .validate(module)
        .map_err(|e| format!("naga validation: {}", e.emit_to_string("")))
}

/// Reads SPIR-V with naga. naga-cli flips the Y of `Position` by default, and so does this.
pub fn parse_spirv(words: &[u32]) -> Result<naga::Module, String> {
    let opts = naga::front::spv::Options {
        adjust_coordinate_space: true,
        strict_capabilities: false,
        block_ctx_dump_prefix: None,
    };
    naga::front::spv::Frontend::new(words.iter().copied(), &opts)
        .parse()
        .map_err(|e| format!("naga spv-in: {e}"))
}

pub fn translate(module: naga::Module) -> Outputs {
    let all = Capabilities::all();
    let wgsl = validate(&module, all & wgsl::supported_capabilities()).and_then(|info| {
        wgsl::write_string(&module, &info, wgsl::WriterFlags::empty())
            .map_err(|e| format!("naga wgsl-out: {e}"))
    });
    let msl = validate(&module, all & msl::supported_capabilities()).and_then(|info| {
        let (m, i) = pipeline_constants::process_overrides(
            &module,
            &info,
            None,
            &PipelineConstants::default(),
        )
        .map_err(|e| format!("naga overrides: {e}"))?;
        msl::write_string(
            &m,
            &i,
            &msl::Options::default(),
            &msl::PipelineOptions::default(),
        )
        .map(|(s, _)| s)
        .map_err(|e| format!("naga msl-out: {e}"))
    });
    let hlsl = validate(&module, all & hlsl::supported_capabilities()).and_then(|info| {
        let (m, i) = pipeline_constants::process_overrides(
            &module,
            &info,
            None,
            &PipelineConstants::default(),
        )
        .map_err(|e| format!("naga overrides: {e}"))?;
        let mut out = String::new();
        let opts = hlsl::Options::default();
        let pipe = hlsl::PipelineOptions::default();
        hlsl::Writer::new(&mut out, &opts, &pipe)
            .write(&m, &i, None)
            .map_err(|e| format!("naga hlsl-out: {e}"))?;
        Ok(out)
    });
    Outputs {
        module,
        wgsl,
        msl,
        hlsl,
    }
}

/// Parses WGSL with naga and validates it, as a check of a WGSL output.
pub fn reparse_wgsl(src: &str) -> Result<naga::Module, String> {
    let m = naga::front::wgsl::parse_str(src)
        .map_err(|e| format!("naga wgsl-in: {}", e.emit_to_string(src)))?;
    validate(&m, Capabilities::all())?;
    Ok(m)
}
