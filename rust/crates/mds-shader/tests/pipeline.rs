//! Tests through the real vkd3d-shader 2.1 library and the two standard effects. They fail
//! when the library is missing: a skipped check is not a pass.

mod common;

use std::path::Path;

use common::vkd3d;
use mds_fx::Effect;
use mds_shader::vkd3d::Target;
use mds_shader::{backend, ctab, entry_source, reflect, spirv_fix};

fn effect(name: &str) -> Effect {
    let p = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../../res/assets")
        .join(name);
    Effect::parse_file(&p).unwrap()
}

/// The vkd3d input and entry point of `function` in `fx`.
fn source(fx: &Effect, function: &str) -> (String, String, String) {
    let e = fx
        .entries()
        .into_iter()
        .find(|e| e.function == function)
        .unwrap_or_else(|| panic!("no entry {function}"));
    let (src, ep) = entry_source(fx, &e).unwrap();
    (src, ep, e.profile)
}

fn has_point_size(words: &[u32]) -> bool {
    spirv_fix::disassemble(words).contains("BuiltIn PointSize")
}

#[test]
fn point_size_removal_leaves_a_module_naga_validates() {
    let vk = vkd3d();
    let fx = effect("skin_effect_sm3.fx");
    let (src, ep, profile) = source(&fx, "BufferShadow_VS");
    assert_eq!(profile, "vs_3_0");
    let bytes = vk
        .compile_hlsl(&src, "sm3", &profile, &ep, Target::SpirvBinary)
        .unwrap();
    let raw = spirv_fix::words(&bytes).unwrap();
    assert!(has_point_size(&raw), "vkd3d no longer adds PointSize");
    // Without the fix naga's WGSL and HLSL writers reject the module.
    let out = backend::translate(backend::parse_spirv(&raw, true).unwrap());
    assert!(out.wgsl.is_err() && out.hlsl.is_err());

    let (fixed, removed) = spirv_fix::strip_point_size(&raw).unwrap();
    assert!(removed && !has_point_size(&fixed));
    let out = backend::translate(backend::parse_spirv(&fixed, true).unwrap());
    let wgsl = out.wgsl.unwrap();
    out.msl.unwrap();
    out.hlsl.unwrap();
    backend::reparse_wgsl(&wgsl).unwrap();

    // A module without PointSize is returned as it was.
    let (same, removed) = spirv_fix::strip_point_size(&fixed).unwrap();
    assert!(!removed && same == fixed);
}

#[test]
fn ctab_names_of_buffer_shadow_ps() {
    let vk = vkd3d();
    let fx = effect("skin_effect_sm3.fx");
    let (src, ep, profile) = source(&fx, "BufferShadow_PS");
    let d3dbc = vk
        .compile_hlsl(&src, "sm3", &profile, &ep, Target::D3dBytecode)
        .unwrap();
    let c = ctab::parse(&d3dbc).unwrap();
    let names: Vec<&str> = c.iter().map(|c| c.name.as_str()).collect();
    for n in ["EgColor", "LightDir", "SpcColor", "ToonColor"] {
        assert!(names.contains(&n), "{n} missing from {names:?}");
    }
    let mut regs: Vec<String> = c.iter().map(|c| c.to_string()).collect();
    regs.sort();
    assert_eq!(
        regs,
        [
            "DefSampler=s0",
            "EgColor=c0",
            "LightDir=c2",
            "SpcColor=c3",
            "ToonColor=c1",
            "parthf=c4",
            "transp=c5"
        ]
    );

    // The table covers exactly the registers the SPIR-V of the same entry reads.
    let spv = vk
        .compile_hlsl(&src, "sm3", &profile, &ep, Target::SpirvBinary)
        .unwrap();
    let words = spirv_fix::words(&spv).unwrap();
    reflect::check_coverage(&words, &c).unwrap();
    let without_light: Vec<_> = c.iter().filter(|c| c.name != "LightDir").cloned().collect();
    let err = reflect::check_coverage(&words, &without_light).unwrap_err();
    assert!(err.contains("c2 is read and lies in 0 parameters"), "{err}");
}

#[test]
fn probe_matches_ctab_on_the_standard_effects() {
    let vk = vkd3d();
    let mut checked = 0;
    for file in ["skin_effect_sm2.fx", "skin_effect_sm3.fx"] {
        let fx = effect(file);
        for e in fx.entries() {
            let (src, ep) = entry_source(&fx, &e).unwrap();
            let r = reflect::reflect(&vk, &fx.ast, &src, file, &e.profile, &ep).unwrap();
            assert_eq!(r.source, reflect::Source::Ctab);
            let p = reflect::verify_probe(&vk, &fx.ast, &src, file, &e.profile, &ep).unwrap();
            assert_eq!(p, r.constants, "{file} {}", e.function);
            checked += 1;
        }
    }
    assert!(checked > 20);
}

#[test]
fn compile_reports_vkd3d_errors() {
    let vk = vkd3d();
    let e = vk
        .compile_hlsl(
            "float4 main() : COLOR { return nope; }",
            "bad",
            "ps_3_0",
            "main",
            Target::SpirvBinary,
        )
        .unwrap_err();
    assert!(e.code < 0);
    assert!(e.summary().starts_with('E'), "{}", e.summary());
}

#[test]
fn disassemble_lists_every_pass_in_d3d_assembly() {
    let vk = vkd3d();
    let fx = effect("skin_effect_sm3.fx");
    let text = mds_shader::disassemble(&vk, &fx, "sm3");
    let passes: usize = fx.ast.techniques.iter().map(|t| t.passes.len()).sum();
    let count = |prefix: &str| text.lines().filter(|l| l.starts_with(prefix)).count();
    assert_eq!(count("  pass "), passes);
    assert_eq!(count("technique "), fx.ast.techniques.len());
    // Each shader state is followed by its program: the version token, then instructions.
    let states = text.lines().filter(|l| l.contains(" = compile ")).count();
    assert!(states >= 2 * passes, "{states} shader states");
    let versions = text
        .lines()
        .filter(|l| matches!(l.trim(), "vs_3_0" | "ps_3_0"))
        .count();
    assert_eq!(versions, states, "{text}");
    assert!(!text.contains("// error"), "{text}");
    assert!(text.contains("mov "), "{text}");
}
