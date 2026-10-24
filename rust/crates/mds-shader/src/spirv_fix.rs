//! SPIR-V fixes applied between vkd3d-shader and naga.

use rspirv::binary::Assemble;
use rspirv::dr::{self, Operand};
use rspirv::spirv::{BuiltIn, Decoration, Op};

/// Turns SPIR-V bytes into words. Fails when the length is not a multiple of four.
pub fn words(bytes: &[u8]) -> Result<Vec<u32>, String> {
    if !bytes.len().is_multiple_of(4) {
        return Err(format!(
            "SPIR-V of {} bytes is not whole words",
            bytes.len()
        ));
    }
    Ok(bytes
        .chunks_exact(4)
        .map(|c| u32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect())
}

fn is_id(op: Option<&Operand>, id: u32) -> bool {
    matches!(op, Some(Operand::IdRef(x)) if *x == id)
}

/// Removes the `PointSize` output that vkd3d-shader adds to every vertex shader: its
/// `OpDecorate ... BuiltIn PointSize`, `OpName`, `OpVariable`, every `OpStore` to it, and its
/// entry in the `OpEntryPoint` interface. naga's WGSL and HLSL writers reject the output.
///
/// Returns the module and whether it held a `PointSize` output.
pub fn strip_point_size(words: &[u32]) -> Result<(Vec<u32>, bool), String> {
    let mut m = dr::load_words(words).map_err(|e| format!("cannot read SPIR-V: {e}"))?;
    let ids: Vec<u32> = m
        .annotations
        .iter()
        .filter(|i| {
            i.class.opcode == Op::Decorate
                && matches!(
                    i.operands.get(1),
                    Some(Operand::Decoration(Decoration::BuiltIn))
                )
                && matches!(
                    i.operands.get(2),
                    Some(Operand::BuiltIn(BuiltIn::PointSize))
                )
        })
        .filter_map(|i| match i.operands.first() {
            Some(Operand::IdRef(id)) => Some(*id),
            _ => None,
        })
        .collect();
    if ids.is_empty() {
        return Ok((words.to_vec(), false));
    }
    for &id in &ids {
        // A PointSize decoration on a struct member (OpMemberDecorate) is not this case.
        let is_var = m
            .types_global_values
            .iter()
            .any(|i| i.class.opcode == Op::Variable && i.result_id == Some(id));
        if !is_var {
            return Err(format!("PointSize id %{id} is not a global variable"));
        }
        // Only stores may use the variable; anything else would be left dangling.
        for f in &m.functions {
            for b in &f.blocks {
                for i in &b.instructions {
                    let uses = i
                        .operands
                        .iter()
                        .any(|o| matches!(o, Operand::IdRef(x) if *x == id));
                    if uses && !(i.class.opcode == Op::Store && is_id(i.operands.first(), id)) {
                        return Err(format!(
                            "PointSize variable %{id} is used by {:?}",
                            i.class.opcode
                        ));
                    }
                }
            }
        }
        m.annotations.retain(|i| !is_id(i.operands.first(), id));
        m.debug_names.retain(|i| !is_id(i.operands.first(), id));
        m.types_global_values.retain(|i| i.result_id != Some(id));
        for ep in &mut m.entry_points {
            ep.operands
                .retain(|o| !matches!(o, Operand::IdRef(x) if *x == id));
        }
        for f in &mut m.functions {
            for b in &mut f.blocks {
                b.instructions
                    .retain(|i| !(i.class.opcode == Op::Store && is_id(i.operands.first(), id)));
            }
        }
    }
    // rspirv moves an OpLine that sits between OpFunction and the first OpLabel into the
    // global section, where naga rejects it. Line info is debug only, so drop those.
    m.types_global_values
        .retain(|i| !matches!(i.class.opcode, Op::Line | Op::NoLine));
    Ok((m.assemble(), true))
}

/// Disassembles a module, for debugging.
pub fn disassemble(words: &[u32]) -> String {
    use rspirv::binary::Disassemble;
    match dr::load_words(words) {
        Ok(m) => m.disassemble(),
        Err(e) => format!("cannot read SPIR-V: {e}"),
    }
}
