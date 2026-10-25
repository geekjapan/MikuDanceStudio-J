//! Shader entry points (`compile <profile> <function>(<args>)`) and their wrapper sources.

use std::collections::HashSet;

use crate::ast::{EffectAst, Function};

/// Name of the generated wrapper function. WGSL reserves names that start with `__`, so naga's
/// WGSL writer would rename such an entry point.
pub const WRAPPER_ENTRY: &str = "mme_entry";

/// One shader entry, unique by profile, function, and argument text.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Entry {
    pub profile: String,
    pub function: String,
    pub args: Vec<String>,
    /// Argument tokens joined by single spaces, the form `shaders-direct.tsv` uses.
    pub args_text: String,
}

/// Shader source plus the function to compile.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Wrapper {
    pub source: String,
    pub entry_point: String,
}

/// The unique entries of an effect, in order of first appearance.
pub fn entries(ast: &EffectAst) -> Vec<Entry> {
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for c in ast.compiles() {
        let e = Entry {
            profile: c.profile.clone(),
            function: c.function.clone(),
            args: c.args.clone(),
            args_text: c.args_text.clone(),
        };
        if seen.insert(e.clone()) {
            out.push(e);
        }
    }
    out
}

fn last_word_before_bracket_or_colon(param: &str) -> Option<&str> {
    let decl = param.split(" : ").next().unwrap_or(param);
    let decl = decl.split(" [").next().unwrap_or(decl);
    decl.split(' ').rfind(|w| !w.is_empty())
}

/// Builds the source to compile for `entry`.
///
/// Without arguments, the entry function is compiled as it is. With arguments, a wrapper
/// `mme_entry` takes every non-`uniform` parameter of the function and passes the
/// arguments to its `uniform` parameters, in order.
pub fn wrapper(ast: &EffectAst, shader_source: &str, entry: &Entry) -> Result<Wrapper, String> {
    let func: &Function = ast
        .functions
        .iter()
        .find(|f| f.name == entry.function && f.has_body)
        .ok_or_else(|| format!("function {} is not defined", entry.function))?;
    if entry.args_text.is_empty() {
        return Ok(Wrapper {
            source: shader_source.to_string(),
            entry_point: entry.function.clone(),
        });
    }
    let mut call = Vec::new();
    let mut decl = Vec::new();
    let mut next_arg = entry.args.iter();
    for p in &func.params {
        if p.split(' ').next() == Some("uniform") {
            let a = next_arg.next().ok_or_else(|| {
                format!(
                    "{} has more uniform parameters than the {} compile arguments",
                    func.name,
                    entry.args.len()
                )
            })?;
            call.push(a.clone());
        } else {
            let name = last_word_before_bracket_or_colon(p)
                .ok_or_else(|| format!("cannot find the name of parameter {p:?}"))?;
            decl.push(p.clone());
            call.push(name.to_string());
        }
    }
    if next_arg.next().is_some() {
        return Err(format!(
            "{} has fewer uniform parameters than the {} compile arguments",
            func.name,
            entry.args.len()
        ));
    }
    let ret = func.return_type.rsplit(' ').next().unwrap_or("void");
    let semantic = func
        .return_semantic
        .as_ref()
        .map(|s| format!(": {s}"))
        .unwrap_or_default();
    let ret_kw = if ret == "void" { "" } else { "return " };
    let wrapper = format!(
        "\n{ret} {WRAPPER_ENTRY}({}) {semantic} {{ {ret_kw}{}({}); }}\n",
        decl.join(", "),
        func.name,
        call.join(", ")
    );
    Ok(Wrapper {
        source: format!("{shader_source}{wrapper}"),
        entry_point: WRAPPER_ENTRY.to_string(),
    })
}
