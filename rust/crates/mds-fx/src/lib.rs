//! Parser for MikuMikuEffect (`.fx`) files.
//!
//! [`Effect::parse_file`] preprocesses (includes, macros, conditionals), lexes, and parses an
//! effect. It never panics on bad input; every failure is an [`FxError`] that names the
//! original file and line.
//!
//! ```no_run
//! let fx = mds_fx::Effect::parse_file("Main/main.fx".as_ref())?;
//! for t in &fx.ast.techniques {
//!     println!("{:?}: {} passes", t.name, t.passes.len());
//! }
//! let source = fx.shader_source(); // technique blocks removed, strings joined
//! for entry in fx.entries() {
//!     let w = fx.wrapper(&entry)?; // source + entry point with uniform args bound
//!     println!("{} {}", entry.profile, w.entry_point);
//! }
//! # Ok::<(), mds_fx::FxError>(())
//! ```

pub mod ast;
mod discover;
pub mod entries;
mod error;
pub mod lex;
pub mod parse;
pub mod preprocess;
#[cfg(test)]
mod testutil;

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::path::Path;

pub use ast::*;
pub use discover::{discover, Found};
pub use entries::{Entry, Wrapper};
pub use error::FxError;
pub use preprocess::{decode, Include, Options, Origin, Preprocessed, Via};

/// A parsed effect file.
#[derive(Clone, Debug)]
pub struct Effect {
    pub ast: EffectAst,
    pre: Preprocessed,
    shader: String,
}

impl Effect {
    pub fn parse_file(path: &Path) -> Result<Effect, FxError> {
        Self::parse_file_with(path, &Options::default())
    }

    pub fn parse_file_with(path: &Path, opts: &Options) -> Result<Effect, FxError> {
        let bytes = std::fs::read(path)
            .map_err(|e| FxError::new(path, 0, format!("cannot read file: {e}")))?;
        Self::parse_bytes_with(path, &bytes, opts)
    }

    /// Parses `bytes` as the file at `path`. Includes resolve relative to `path`.
    pub fn parse_bytes(path: &Path, bytes: &[u8]) -> Result<Effect, FxError> {
        Self::parse_bytes_with(path, bytes, &Options::default())
    }

    pub fn parse_bytes_with(path: &Path, bytes: &[u8], opts: &Options) -> Result<Effect, FxError> {
        let pre = preprocess::preprocess_bytes(path, bytes, opts)?;
        let toks = lex::lex(&pre.text).map_err(|e| pre.error(e.line, e.message))?;
        let ast = parse::parse(&pre.text, &toks).map_err(|e| pre.error(e.line, e.message))?;
        let shader = build_shader_source(&pre.text, &toks, &ast);
        Ok(Effect { ast, pre, shader })
    }

    /// The preprocessed text with `technique` blocks removed (their lines stay blank) and
    /// adjacent string literals joined.
    pub fn shader_source(&self) -> &str {
        &self.shader
    }

    /// Unique shader entries, in order of first appearance.
    pub fn entries(&self) -> Vec<Entry> {
        entries::entries(&self.ast)
    }

    /// The source and entry point to compile for `entry`, with its `uniform` parameters bound
    /// to the `compile` arguments.
    pub fn wrapper(&self, entry: &Entry) -> Result<Wrapper, FxError> {
        entries::wrapper(&self.ast, &self.shader, entry).map_err(|m| {
            let line = self
                .ast
                .functions
                .iter()
                .find(|f| f.name == entry.function)
                .map_or(0, |f| f.line);
            self.pre.error(line, m)
        })
    }

    pub fn preprocessed(&self) -> &Preprocessed {
        &self.pre
    }

    pub fn includes(&self) -> &[Include] {
        &self.pre.includes
    }

    /// Maps a 1-based line of the preprocessed text (the `line` fields of the AST and of
    /// [`Self::shader_source`]) to its source file and line.
    pub fn origin(&self, line: u32) -> Option<(&Path, u32)> {
        self.pre.origin(line)
    }

    /// Hash of the preprocessed content: the tokens of every line and each line's ending
    /// (LF or CRLF), but not the spacing between tokens. Files with equal keys preprocess to
    /// the same text up to spacing. The P2 prototype dropped such duplicates by the hash of the
    /// preprocessor output, which keeps line endings and line positions.
    pub fn content_key(&self) -> u64 {
        let mut h = DefaultHasher::new();
        for line in self.pre.text.split('\n') {
            let (body, cr) = match line.strip_suffix('\r') {
                Some(b) => (b, true),
                None => (line, false),
            };
            let mut i = 0;
            while i < body.len() {
                if body.as_bytes()[i].is_ascii_whitespace() {
                    i += 1;
                    continue;
                }
                let (_, e) = lex::scan(body, i);
                body[i..e].hash(&mut h);
                i = e;
            }
            (cr, 0xFFu8).hash(&mut h);
        }
        h.finish()
    }
}

fn build_shader_source(src: &str, toks: &[lex::Token], ast: &EffectAst) -> String {
    let mut edits: Vec<(usize, usize, String)> = Vec::new();
    for t in &ast.techniques {
        let mut end = t.span.end;
        let rest = &src[end..];
        let trimmed = rest.trim_start();
        if trimmed.starts_with(';') {
            end += rest.len() - trimmed.len() + 1;
        }
        edits.push((
            t.span.start,
            end,
            "\n".repeat(src[t.span.start..end].matches('\n').count()),
        ));
    }
    for t in toks {
        if let Some(raw) = &t.raw {
            edits.push((
                t.start,
                t.end,
                format!("{raw}{}", "\n".repeat(t.gap_newlines as usize)),
            ));
        }
    }
    edits.sort_by_key(|e| e.0);
    let mut out = String::with_capacity(src.len());
    let mut pos = 0;
    for (s, e, r) in edits {
        if s < pos {
            continue; // inside a removed technique block
        }
        out.push_str(&src[pos..s]);
        out.push_str(&r);
        pos = e;
    }
    out.push_str(&src[pos..]);
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::TempTree;

    fn parse(src: &str) -> Effect {
        let t = TempTree::new();
        t.write("a.fx", src.as_bytes());
        Effect::parse_file(&t.path("a.fx")).unwrap()
    }

    const SRC: &str = "\
float4x4 W : WORLD;
float4 VS(float4 p : POSITION, uniform float s, uniform float2 o) : POSITION { return p * s; }
float4 PS(float4 c : COLOR0, uniform float k) : COLOR { return c * k; }
float4 Plain() : COLOR { return 1; }
technique T < string Script = \"RenderColorTarget0=;\"
                              \"Pass=P0;\"; > {
  pass P0 {
    VertexShader = compile vs_3_0 VS(2.0, float2(1, 0));
    PixelShader = compile ps_3_0 PS(0.5);
  }
  pass P1 { PixelShader = compile ps_3_0 Plain(); }
}
technique T2 { pass { PixelShader = compile ps_3_0 PS(0.5); } };
";

    #[test]
    fn shader_source_drops_techniques_and_keeps_lines() {
        let fx = parse(SRC);
        let s = fx.shader_source();
        assert!(!s.contains("technique") && !s.contains("compile"));
        assert!(s.contains("float4 VS("));
        assert_eq!(s.lines().count(), SRC.lines().count());
    }

    #[test]
    fn shader_source_joins_strings_outside_techniques() {
        let fx = parse("string S = \"a;\"\n \"b;\";\nfloat x;\n");
        assert_eq!(fx.shader_source(), "string S = \"a;b;\"\n;\nfloat x;\n");
    }

    #[test]
    fn entries_are_unique() {
        let fx = parse(SRC);
        let e = fx.entries();
        let names: Vec<_> = e
            .iter()
            .map(|e| {
                (
                    e.profile.as_str(),
                    e.function.as_str(),
                    e.args_text.as_str(),
                )
            })
            .collect();
        assert_eq!(
            names,
            [
                ("vs_3_0", "VS", "2.0 , float2 ( 1 , 0 )"),
                ("ps_3_0", "PS", "0.5"),
                ("ps_3_0", "Plain", "")
            ]
        );
        assert_eq!(
            fx.ast.techniques[0].annotations[0].value,
            Value::Str("RenderColorTarget0=;Pass=P0;".into())
        );
    }

    #[test]
    fn wrapper_binds_uniform_arguments() {
        let fx = parse(SRC);
        let e = fx.entries();
        let w = fx.wrapper(&e[0]).unwrap();
        assert_eq!(w.entry_point, "__mme_entry");
        assert!(w.source.starts_with(fx.shader_source()));
        assert!(
            w.source.ends_with("\nfloat4 __mme_entry(float4 p : POSITION) : POSITION { return VS(p, 2.0, float2 ( 1 , 0 )); }\n"),
            "{}",
            w.source
        );
        let w = fx.wrapper(&e[1]).unwrap();
        assert!(w
            .source
            .ends_with("float4 __mme_entry(float4 c : COLOR0) : COLOR { return PS(c, 0.5); }\n"));
        let w = fx.wrapper(&e[2]).unwrap();
        assert_eq!(
            (w.entry_point.as_str(), w.source.as_str()),
            ("Plain", fx.shader_source())
        );
    }

    #[test]
    fn wrapper_rejects_mismatched_arguments() {
        let fx = parse("float4 F(uniform float a, uniform float b) : COLOR { return a; }\ntechnique T { pass { PixelShader = compile ps_3_0 F(1); } }");
        let e = fx.entries();
        assert!(fx
            .wrapper(&e[0])
            .unwrap_err()
            .message
            .contains("more uniform"));
        let fx = parse("float4 F(uniform float a) : COLOR { return a; }\ntechnique T { pass { PixelShader = compile ps_3_0 F(1, 2); } }");
        assert!(fx
            .wrapper(&fx.entries()[0])
            .unwrap_err()
            .message
            .contains("fewer uniform"));
        let fx = parse("technique T { pass { PixelShader = compile ps_3_0 Nope(); } }");
        assert!(fx
            .wrapper(&fx.entries()[0])
            .unwrap_err()
            .message
            .contains("not defined"));
    }

    #[test]
    fn errors_name_the_original_file_and_line() {
        let t = TempTree::new();
        t.write("a.fx", b"#include \"b.fxsub\"\nfloat ok;\n");
        t.write("b.fxsub", b"// c\n\nfloat a;\nfloat b = ;\n");
        let e = Effect::parse_file(&t.path("a.fx")).unwrap_err();
        assert_eq!((e.path.clone(), e.line), (t.path("b.fxsub"), 4));
        t.write("b.fxsub", b"float a;\nstring s = \"open;\n");
        let e = Effect::parse_file(&t.path("a.fx")).unwrap_err();
        assert_eq!((e.path, e.line), (t.path("b.fxsub"), 2));
    }

    #[test]
    fn macro_generated_techniques_are_parsed() {
        let fx = parse(
            "float4 PS() : COLOR { return 0; }\n#define TEC(n, p) technique n < string MMDPass = p; > { pass P { PixelShader = compile ps_3_0 PS(); } }\nTEC(A, \"object\")\nTEC(B, \"object_ss\")\n",
        );
        assert_eq!(fx.ast.techniques.len(), 2);
        assert_eq!(
            fx.ast.techniques[1].annotations[0].value,
            Value::Str("object_ss".into())
        );
        assert_eq!(fx.entries().len(), 1);
        // a macro expansion maps to the line of its invocation
        assert_eq!(fx.origin(fx.ast.techniques[1].line).unwrap().1, 4);
    }

    #[test]
    fn shift_jis_and_utf8_agree() {
        let utf8 =
            "// \u{30c6}\u{30b9}\u{30c8}\nstring Name = \"\u{30c6}\u{30b9}\u{30c8}\";\nfloat x;\n";
        let (sjis, _, bad) = encoding_rs::SHIFT_JIS.encode(utf8);
        assert!(!bad && std::str::from_utf8(&sjis).is_err());
        let t = TempTree::new();
        t.write("sjis.fx", &sjis);
        t.write("utf8.fx", utf8.as_bytes());
        let a = Effect::parse_file(&t.path("sjis.fx")).unwrap();
        let b = Effect::parse_file(&t.path("utf8.fx")).unwrap();
        assert_eq!(a.ast, b.ast);
        assert_eq!(a.shader_source(), b.shader_source());
        assert_eq!(a.content_key(), b.content_key());
    }
}
