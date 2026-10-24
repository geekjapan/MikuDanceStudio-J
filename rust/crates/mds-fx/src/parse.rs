//! Parser for preprocessed, lexed effect text.
//!
//! It reads globals (type, name, array dimensions, semantic, annotations, initializer),
//! `sampler_state` blocks, and `technique`/`pass` blocks with state assignments and
//! `compile` expressions. It records function signatures and skips function bodies, struct
//! bodies, and `cbuffer` blocks after checking that their brackets balance.

use crate::ast::*;
use crate::lex::{Kind, Token};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParseError {
    /// 1-based line of the preprocessed text.
    pub line: u32,
    pub message: String,
}

type Res<T> = Result<T, ParseError>;

const MODIFIERS: [&str; 17] = [
    "static",
    "uniform",
    "const",
    "extern",
    "shared",
    "volatile",
    "row_major",
    "column_major",
    "precise",
    "groupshared",
    "in",
    "out",
    "inout",
    "linear",
    "centroid",
    "nointerpolation",
    "noperspective",
];

const MAX_VALUE_DEPTH: u32 = 8;

pub fn parse(src: &str, toks: &[Token]) -> Result<EffectAst, ParseError> {
    let mut p = P {
        src,
        t: toks,
        pos: 0,
    };
    let mut ast = EffectAst::default();
    p.file(&mut ast)?;
    Ok(ast)
}

struct P<'a> {
    src: &'a str,
    t: &'a [Token],
    pos: usize,
}

fn closer(open: &str) -> Option<&'static str> {
    match open {
        "(" => Some(")"),
        "[" => Some("]"),
        "{" => Some("}"),
        _ => None,
    }
}

fn is_vector_type(name: &str) -> bool {
    ["float", "int", "uint", "half", "bool", "double"]
        .iter()
        .any(|b| {
            name.strip_prefix(b).is_some_and(|r| {
                !r.is_empty() && r.bytes().all(|c| c.is_ascii_digit() || c == b'x')
            })
        })
}

fn is_float_type(name: &str) -> bool {
    ["float", "half", "double"]
        .iter()
        .any(|b| name.starts_with(b))
}

fn number(text: &str) -> Option<Value> {
    let s = text.to_ascii_lowercase();
    if let Some(h) = s.strip_prefix("0x") {
        let h = h.trim_end_matches(['u', 'l']);
        return i64::from_str_radix(h, 16).ok().map(Value::Int);
    }
    if s.contains(['.', 'e']) || s.ends_with(['f', 'h']) {
        let f = s.trim_end_matches(['f', 'h', 'l']).parse::<f64>().ok()?;
        return Some(Value::Float(f));
    }
    s.trim_end_matches(['u', 'l'])
        .parse::<i64>()
        .ok()
        .map(Value::Int)
}

fn coerce(ty: &str, v: Value) -> Value {
    let base = ty.to_ascii_lowercase();
    match v {
        Value::Int(i) if matches!(base.as_str(), "float" | "half" | "double") => {
            Value::Float(i as f64)
        }
        Value::Int(i) if base == "bool" => Value::Bool(i != 0),
        Value::Vector(vs) if is_float_type(&base) => {
            Value::Vector(vs.into_iter().map(|e| coerce("float", e)).collect())
        }
        other => other,
    }
}

impl<'a> P<'a> {
    fn tx(&self, i: usize) -> &'a str {
        self.t.get(i).map_or("", |t| t.text(self.src))
    }

    fn peek(&self) -> &'a str {
        self.tx(self.pos)
    }

    fn peek_at(&self, k: usize) -> &'a str {
        self.tx(self.pos + k)
    }

    fn kind_at(&self, i: usize) -> Option<Kind> {
        self.t.get(i).map(|t| t.kind)
    }

    fn eof(&self) -> bool {
        self.pos >= self.t.len()
    }

    fn line(&self) -> u32 {
        self.t.get(self.pos).or(self.t.last()).map_or(1, |t| t.line)
    }

    fn err<T>(&self, message: impl Into<String>) -> Res<T> {
        Err(ParseError {
            line: self.line(),
            message: message.into(),
        })
    }

    fn unexpected<T>(&self, wanted: &str) -> Res<T> {
        if self.eof() {
            self.err(format!("unexpected end of file, expected {wanted}"))
        } else {
            self.err(format!("unexpected {:?}, expected {wanted}", self.peek()))
        }
    }

    fn expect(&mut self, s: &str) -> Res<()> {
        if self.peek() == s && !self.eof() {
            self.pos += 1;
            Ok(())
        } else {
            self.unexpected(&format!("{s:?}"))
        }
    }

    fn ident(&mut self) -> Res<String> {
        if self.kind_at(self.pos) == Some(Kind::Ident) {
            self.pos += 1;
            Ok(self.tx(self.pos - 1).to_string())
        } else {
            self.unexpected("an identifier")
        }
    }

    fn join(&self, s: usize, e: usize) -> String {
        (s..e).map(|i| self.tx(i)).collect::<Vec<_>>().join(" ")
    }

    /// Consumes a bracket group that starts at the current token, checking nesting.
    fn skip_group(&mut self) -> Res<()> {
        let mut stack: Vec<&str> = Vec::new();
        loop {
            let t = self.peek();
            if self.eof() {
                return self.unexpected(&format!("{:?}", stack.last().copied().unwrap_or(")")));
            }
            if let Some(c) = closer(t) {
                stack.push(c);
            } else if matches!(t, ")" | "]" | "}") {
                if stack.last() != Some(&t) {
                    return self.err(format!("unmatched {t:?}"));
                }
                stack.pop();
            }
            self.pos += 1;
            if stack.is_empty() {
                return Ok(());
            }
        }
    }

    /// Finds the end of an expression: the first token at nesting depth 0 whose text is in
    /// `stops`. Returns its index and does not consume it.
    fn scan_until(&mut self, stops: &[&str]) -> Res<usize> {
        let start = self.pos;
        loop {
            if self.eof() {
                self.pos = start;
                return self.unexpected(&format!("{:?}", stops.first().copied().unwrap_or(";")));
            }
            let t = self.peek();
            if stops.contains(&t) {
                return Ok(self.pos);
            }
            if closer(t).is_some() {
                self.skip_group()?;
            } else if matches!(t, ")" | "]" | "}") {
                return self.err(format!("unmatched {t:?}"));
            } else {
                self.pos += 1;
            }
        }
    }

    /// Splits tokens `s..e` at top-level commas.
    fn split_commas(&self, s: usize, e: usize) -> Vec<(usize, usize)> {
        let mut out = Vec::new();
        let mut depth = 0i32;
        let mut from = s;
        for i in s..e {
            match self.tx(i) {
                "(" | "[" | "{" => depth += 1,
                ")" | "]" | "}" => depth -= 1,
                "," if depth == 0 => {
                    out.push((from, i));
                    from = i + 1;
                }
                _ => {}
            }
        }
        if from < e || !out.is_empty() {
            out.push((from, e));
        }
        out
    }

    // ----------------------------------------------------------------------------- values

    fn single(&self, i: usize) -> Value {
        let tok = &self.t[i];
        let text = tok.text(self.src);
        match tok.kind {
            Kind::Str => Value::Str(tok.value.clone()),
            Kind::Number => number(text).unwrap_or_else(|| Value::Expr(text.to_string())),
            Kind::Ident if text.eq_ignore_ascii_case("true") => Value::Bool(true),
            Kind::Ident if text.eq_ignore_ascii_case("false") => Value::Bool(false),
            Kind::Ident => Value::Ident(text.to_string()),
            _ => Value::Expr(text.to_string()),
        }
    }

    fn value(&self, s: usize, e: usize, depth: u32) -> Value {
        let n = e.saturating_sub(s);
        let expr = || Value::Expr(self.join(s, e));
        if n == 0 || e > self.t.len() {
            return expr();
        }
        if n == 1 {
            return self.single(s);
        }
        if n == 2 && matches!(self.tx(s), "-" | "+") && self.t[s + 1].kind == Kind::Number {
            return match (self.tx(s) == "-", self.single(s + 1)) {
                (true, Value::Int(i)) => Value::Int(i.wrapping_neg()),
                (true, Value::Float(f)) => Value::Float(-f),
                (false, v @ (Value::Int(_) | Value::Float(_))) => v,
                _ => expr(),
            };
        }
        if depth >= MAX_VALUE_DEPTH {
            return expr();
        }
        let (inner_s, inner_e) = if self.tx(s) == "{" && self.tx(e - 1) == "}" {
            (s + 1, e - 1)
        } else if n >= 3
            && self.t[s].kind == Kind::Ident
            && is_vector_type(self.tx(s))
            && self.tx(s + 1) == "("
            && self.tx(e - 1) == ")"
        {
            (s + 2, e - 1)
        } else {
            return expr();
        };
        // the outer brackets must pair up with each other
        let mut d = 0i32;
        for i in (inner_s - 1)..e {
            match self.tx(i) {
                "(" | "[" | "{" => d += 1,
                ")" | "]" | "}" => d -= 1,
                _ => {}
            }
            if d == 0 && i != e - 1 {
                return expr();
            }
        }
        Value::Vector(
            self.split_commas(inner_s, inner_e)
                .into_iter()
                .map(|(a, b)| self.value(a, b, depth + 1))
                .collect(),
        )
    }

    // ---------------------------------------------------------------------------- grammar

    fn file(&mut self, ast: &mut EffectAst) -> Res<()> {
        while !self.eof() {
            let kw = self.peek();
            match kw {
                ";" => self.pos += 1,
                "technique" | "technique10" | "technique11"
                    if matches!(self.peek_at(1), "{" | "<")
                        || self.kind_at(self.pos + 1) == Some(Kind::Ident) =>
                {
                    let t = self.technique()?;
                    ast.techniques.push(t);
                }
                "struct" => {
                    let line = self.line();
                    self.pos += 1;
                    let name = if self.kind_at(self.pos) == Some(Kind::Ident) {
                        self.ident()?
                    } else {
                        String::new()
                    };
                    if self.peek() != "{" {
                        return self.unexpected("'{'");
                    }
                    self.skip_group()?;
                    let end = self.scan_until(&[";"])?;
                    self.pos = end + 1;
                    ast.structs.push(StructDecl { name, line });
                }
                "cbuffer" | "tbuffer" => {
                    self.pos += 1;
                    let end = self.scan_until(&["{"])?;
                    self.pos = end;
                    self.skip_group()?;
                }
                "typedef" => {
                    let end = self.scan_until(&[";"])?;
                    self.pos = end + 1;
                }
                "}" | ")" | "]" => return self.err(format!("unmatched {kw:?}")),
                _ => self.decl(ast)?,
            }
        }
        Ok(())
    }

    /// `<type name = value; ...>` after a name or semantic.
    fn annotations(&mut self) -> Res<Vec<Annotation>> {
        self.expect("<")?;
        let mut out = Vec::new();
        loop {
            match self.peek() {
                ">" if !self.eof() => {
                    self.pos += 1;
                    return Ok(out);
                }
                ";" if !self.eof() => self.pos += 1,
                _ => {
                    let line = self.line();
                    let mut ty = self.ident()?;
                    while self.kind_at(self.pos) == Some(Kind::Ident)
                        && self.kind_at(self.pos + 1) == Some(Kind::Ident)
                    {
                        ty = self.ident()?; // `const string x`: keep the last word as the type
                    }
                    let name = self.ident()?;
                    while self.peek() == "[" {
                        self.skip_group()?;
                    }
                    let mut value = Value::Expr(String::new());
                    if self.peek() == "=" && !self.eof() {
                        self.pos += 1;
                        let s = self.pos;
                        let e = self.scan_until(&[";", ">"])?;
                        value = coerce(&ty, self.value(s, e, 0));
                    }
                    if !matches!(self.peek(), ";" | ">") {
                        return self.unexpected("';' or '>'");
                    }
                    out.push(Annotation {
                        ty,
                        name,
                        value,
                        line,
                    });
                }
            }
        }
    }

    fn technique(&mut self) -> Res<Technique> {
        let start = self.pos;
        let line = self.line();
        self.pos += 1;
        let name = if self.kind_at(self.pos) == Some(Kind::Ident) {
            Some(self.ident()?)
        } else {
            None
        };
        let annotations = if self.peek() == "<" {
            self.annotations()?
        } else {
            Vec::new()
        };
        self.expect("{")?;
        let mut passes = Vec::new();
        loop {
            match self.peek() {
                "}" if !self.eof() => break,
                ";" if !self.eof() => self.pos += 1,
                "pass" => passes.push(self.pass()?),
                _ => return self.unexpected("'pass' or '}'"),
            }
        }
        let end = self.t[self.pos].end;
        self.pos += 1;
        Ok(Technique {
            name,
            annotations,
            passes,
            line,
            span: self.t[start].start..end,
        })
    }

    fn pass(&mut self) -> Res<Pass> {
        let line = self.line();
        self.pos += 1;
        let name = if self.kind_at(self.pos) == Some(Kind::Ident) {
            Some(self.ident()?)
        } else {
            None
        };
        let annotations = if self.peek() == "<" {
            self.annotations()?
        } else {
            Vec::new()
        };
        self.expect("{")?;
        let states = self.states()?;
        Ok(Pass {
            name,
            annotations,
            states,
            line,
        })
    }

    /// State assignments up to and including the closing `}`.
    fn states(&mut self) -> Res<Vec<StateAssignment>> {
        let mut out = Vec::new();
        loop {
            match self.peek() {
                "}" if !self.eof() => {
                    self.pos += 1;
                    return Ok(out);
                }
                ";" if !self.eof() => self.pos += 1,
                _ => out.push(self.state()?),
            }
        }
    }

    fn state(&mut self) -> Res<StateAssignment> {
        let line = self.line();
        let name = self.ident()?;
        let mut index = None;
        if self.peek() == "[" {
            let ok = self.kind_at(self.pos + 1) == Some(Kind::Number) && self.peek_at(2) == "]";
            index = if ok {
                self.peek_at(1).parse::<u32>().ok()
            } else {
                None
            };
            if index.is_none() {
                return self.err("expected a number index in a state name");
            }
            self.pos += 3;
        }
        self.expect("=")?;
        let s = self.pos;
        let e = self.scan_until(&[";", "}"])?;
        if self.peek() == ";" {
            self.pos += 1;
        }
        if s == e {
            return Err(ParseError {
                line,
                message: format!("state {name} has no value"),
            });
        }
        let value = if self.tx(s) == "compile" {
            StateValue::Compile(self.compile(s, e)?)
        } else if name.eq_ignore_ascii_case("texture") {
            let (a, b) = match (self.tx(s), self.tx(e - 1)) {
                ("<", ">") | ("(", ")") if e - s >= 2 => (s + 1, e - 1),
                _ => (s, e),
            };
            if b == a + 1 && self.t[a].kind == Kind::Ident {
                StateValue::Texture(self.tx(a).to_string())
            } else {
                StateValue::Value(self.value(s, e, 0))
            }
        } else {
            StateValue::Value(self.value(s, e, 0))
        };
        Ok(StateAssignment {
            name,
            index,
            value,
            line,
        })
    }

    /// `compile <profile> <function>(<args>)` in tokens `s..e`.
    fn compile(&self, s: usize, e: usize) -> Res<Compile> {
        let bad = |m: &str| {
            Err(ParseError {
                line: self.t[s].line,
                message: m.to_string(),
            })
        };
        if e - s < 5
            || self.t[s + 1].kind != Kind::Ident
            || self.t[s + 2].kind != Kind::Ident
            || self.tx(s + 3) != "("
            || self.tx(e - 1) != ")"
        {
            return bad(
                "malformed compile expression, expected 'compile <profile> <function>(<args>)'",
            );
        }
        // the first `(` must close at the last token
        let mut d = 0i32;
        for i in (s + 3)..e {
            match self.tx(i) {
                "(" | "[" | "{" => d += 1,
                ")" | "]" | "}" => d -= 1,
                _ => {}
            }
            if d == 0 && i != e - 1 {
                return bad("unexpected tokens after the compile arguments");
            }
        }
        let (a, b) = (s + 4, e - 1);
        Ok(Compile {
            profile: self.tx(s + 1).to_string(),
            function: self.tx(s + 2).to_string(),
            args: self
                .split_commas(a, b)
                .into_iter()
                .map(|(x, y)| self.join(x, y))
                .collect(),
            args_text: self.join(a, b),
        })
    }

    fn sampler_state(&mut self) -> Res<SamplerState> {
        self.pos += 1; // sampler_state
        self.expect("{")?;
        Ok(SamplerState {
            states: self.states()?,
        })
    }

    /// A global declaration or a function.
    fn decl(&mut self, ast: &mut EffectAst) -> Res<()> {
        let line = self.line();
        let head_start = self.pos;
        loop {
            if self.kind_at(self.pos) == Some(Kind::Ident) {
                self.pos += 1;
            } else if self.peek() == "::" && !self.eof() {
                self.pos += 1;
            } else if self.peek() == "<"
                && self.pos > head_start
                && self.kind_at(self.pos + 1) == Some(Kind::Ident)
                && matches!(self.peek_at(2), ">" | ",")
            {
                // template arguments: `Texture2D<float4>`
                while !self.eof() && self.peek() != ">" {
                    self.pos += 1;
                }
                self.pos += 1;
            } else {
                break;
            }
        }
        let head_end = self.pos;
        if head_end - head_start < 2 || self.kind_at(head_end - 1) != Some(Kind::Ident) {
            self.pos = head_start;
            return self.unexpected("a declaration");
        }
        let name = self.tx(head_end - 1).to_string();
        let mut modifiers = Vec::new();
        let mut ty = Vec::new();
        for i in head_start..head_end - 1 {
            if MODIFIERS.contains(&self.tx(i)) {
                modifiers.push(self.tx(i).to_string());
            } else {
                ty.push(self.tx(i));
            }
        }
        let ty = ty.join(" ");
        if self.peek() == "(" && !self.eof() {
            return self.function(ast, self.join(head_start, head_end - 1), name, line);
        }
        let mut name = name;
        let mut line = line;
        loop {
            let mut g = Global {
                modifiers: modifiers.clone(),
                ty: ty.clone(),
                name,
                array: Vec::new(),
                semantic: None,
                annotations: Vec::new(),
                initializer: None,
                line,
            };
            loop {
                match self.peek() {
                    "[" => {
                        let s = self.pos + 1;
                        self.skip_group()?;
                        g.array.push(self.join(s, self.pos - 1));
                    }
                    ":" => {
                        self.pos += 1;
                        if matches!(self.peek(), "register" | "packoffset")
                            && self.peek_at(1) == "("
                        {
                            self.pos += 1;
                            self.skip_group()?;
                        } else {
                            let sem = self.ident()?;
                            g.semantic.get_or_insert(sem);
                        }
                    }
                    "<" => g.annotations.extend(self.annotations()?),
                    _ => break,
                }
            }
            if self.peek() == "=" && !self.eof() {
                self.pos += 1;
                if matches!(self.peek(), "sampler_state" | "SamplerState") && self.peek_at(1) == "{"
                {
                    g.initializer = Some(Initializer::Sampler(self.sampler_state()?));
                } else {
                    let s = self.pos;
                    let e = self.scan_until(&[",", ";"])?;
                    if s == e {
                        return self.err(format!("{} has an empty initializer", g.name));
                    }
                    g.initializer = Some(Initializer::Value(coerce(&ty, self.value(s, e, 0))));
                }
            }
            ast.globals.push(g);
            match self.peek() {
                "," if !self.eof() => {
                    self.pos += 1;
                    line = self.line();
                    name = self.ident()?;
                }
                ";" if !self.eof() => {
                    self.pos += 1;
                    return Ok(());
                }
                _ => return self.unexpected("',' or ';'"),
            }
        }
    }

    fn function(
        &mut self,
        ast: &mut EffectAst,
        return_type: String,
        name: String,
        line: u32,
    ) -> Res<()> {
        let open = self.pos;
        self.skip_group()?;
        let mut params: Vec<String> = self
            .split_commas(open + 1, self.pos - 1)
            .into_iter()
            .map(|(a, b)| self.join(a, b))
            .collect();
        if params.len() == 1 && params[0] == "void" {
            params.clear();
        }
        let mut return_semantic = None;
        if self.peek() == ":" && !self.eof() {
            self.pos += 1;
            return_semantic = Some(self.ident()?);
        }
        let has_body = match self.peek() {
            "{" if !self.eof() => {
                self.skip_group()?;
                true
            }
            ";" if !self.eof() => {
                self.pos += 1;
                false
            }
            _ => return self.unexpected("'{' or ';' after a function declaration"),
        };
        ast.functions.push(Function {
            name,
            return_type,
            params,
            return_semantic,
            has_body,
            line,
        });
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lex::lex;

    fn ast(src: &str) -> EffectAst {
        parse(src, &lex(src).unwrap()).unwrap()
    }

    fn fails(src: &str) -> ParseError {
        parse(src, &lex(src).unwrap()).unwrap_err()
    }

    #[test]
    fn annotation_types() {
        let a = ast(
            "float4x4 W : WORLD < string Object = \"Light\"; int N = 3; float F = 2; float3 V = float3(1, 2.5, -3);\n\
             bool B = 1; float2 R = {1, 2}; float N2 = -0.5f; string S = \"a\" \"b\"; bool T = true; float X = 0x10; \
             int Y = 2 * 3; >;",
        );
        let g = &a.globals[0];
        assert_eq!(
            (g.ty.as_str(), g.name.as_str(), g.semantic.as_deref()),
            ("float4x4", "W", Some("WORLD"))
        );
        let by = |n: &str| {
            g.annotations
                .iter()
                .find(|x| x.name == n)
                .unwrap()
                .value
                .clone()
        };
        assert_eq!(by("Object"), Value::Str("Light".into()));
        assert_eq!(by("N"), Value::Int(3));
        assert_eq!(by("F"), Value::Float(2.0));
        assert_eq!(
            by("V"),
            Value::Vector(vec![
                Value::Float(1.0),
                Value::Float(2.5),
                Value::Float(-3.0)
            ])
        );
        assert_eq!(by("B"), Value::Bool(true));
        assert_eq!(
            by("R"),
            Value::Vector(vec![Value::Float(1.0), Value::Float(2.0)])
        );
        assert_eq!(by("N2"), Value::Float(-0.5));
        assert_eq!(by("S"), Value::Str("ab".into()));
        assert_eq!(by("T"), Value::Bool(true));
        assert_eq!(by("X"), Value::Float(16.0));
        assert_eq!(by("Y"), Value::Expr("2 * 3".into()));
        assert_eq!(
            g.annotations.iter().find(|x| x.name == "V").unwrap().ty,
            "float3"
        );
    }

    #[test]
    fn globals_and_samplers() {
        let a = ast(
            "static const float4 C[2] = {1, 2}, D = float4(0,0,0,1);\n\
             texture2D T : RENDERCOLORTARGET <float2 ViewPortRatio = {1.0, 1.0};>;\n\
             Texture2D<float4> Tex : register(t0);\n\
             sampler S = sampler_state { texture = <T>; Filter = LINEAR; AddressU = CLAMP; MaxAnisotropy = 16; };\n\
             sampler S2 = sampler_state { Texture = (T); MIPFILTER = NONE };",
        );
        assert_eq!(a.globals.len(), 6);
        assert_eq!(a.globals[0].modifiers, ["static", "const"]);
        assert_eq!(a.globals[0].array, ["2"]);
        assert_eq!(
            a.globals[0].initializer,
            Some(Initializer::Value(Value::Vector(vec![
                Value::Float(1.0),
                Value::Float(2.0)
            ])))
        );
        assert_eq!(a.globals[1].name, "D");
        assert_eq!(
            a.globals[2].annotations[0].value,
            Value::Vector(vec![Value::Float(1.0), Value::Float(1.0)])
        );
        assert_eq!(a.globals[3].ty, "Texture2D < float4 >");
        let Some(Initializer::Sampler(s)) = &a.globals[4].initializer else {
            panic!()
        };
        assert_eq!(s.states[0].value, StateValue::Texture("T".into()));
        assert_eq!(
            s.states[1].value,
            StateValue::Value(Value::Ident("LINEAR".into()))
        );
        assert_eq!(s.states[3].value, StateValue::Value(Value::Int(16)));
        let Some(Initializer::Sampler(s2)) = &a.globals[5].initializer else {
            panic!()
        };
        assert_eq!(s2.states[0].value, StateValue::Texture("T".into()));
        assert_eq!(s2.states.len(), 2);
    }

    #[test]
    fn techniques_and_passes() {
        let a = ast("struct VS_OUT { float4 p : POSITION; };\n\
             VS_OUT VS(uniform float4x4 m, float4 p : POSITION) : POSITION { return mul(p, m); }\n\
             float4 PS(VS_OUT i) : COLOR { if (a < b) { return 0; } return 1; }\n\
             technique T0 < string MMDPass = \"object\"; > {\n\
               pass P0 { ColorOp[0] = Disable; AlphaBlendEnable = FALSE;\n\
                 VertexShader = compile vs_3_0 VS(world * 2, - 1);\n\
                 PixelShader = compile ps_3_0 PS(); }\n\
               pass { }\n\
             };\n\
             technique { pass P { } }");
        assert_eq!(a.structs[0].name, "VS_OUT");
        assert_eq!(a.functions.len(), 2);
        assert_eq!(
            a.functions[0].params,
            ["uniform float4x4 m", "float4 p : POSITION"]
        );
        assert_eq!(a.functions[0].return_semantic.as_deref(), Some("POSITION"));
        assert_eq!(a.techniques.len(), 2);
        let t = &a.techniques[0];
        assert_eq!(t.name.as_deref(), Some("T0"));
        assert_eq!(t.annotations[0].value, Value::Str("object".into()));
        assert_eq!(t.passes.len(), 2);
        let st = &t.passes[0].states;
        assert_eq!((st[0].name.as_str(), st[0].index), ("ColorOp", Some(0)));
        assert_eq!(st[1].value, StateValue::Value(Value::Bool(false)));
        let StateValue::Compile(c) = &st[2].value else {
            panic!()
        };
        assert_eq!((c.profile.as_str(), c.function.as_str()), ("vs_3_0", "VS"));
        assert_eq!(c.args, ["world * 2", "- 1"]);
        assert_eq!(c.args_text, "world * 2 , - 1");
        assert!(a.techniques[1].name.is_none());
        assert_eq!(a.pass_count(), 3);
        assert_eq!(a.compiles().count(), 2);
    }

    #[test]
    fn syntax_errors_are_reported_with_lines() {
        assert_eq!(fails("float a;\n\nfloat4 b = ;").line, 3);
        assert_eq!(fails("technique T { pass P { A = ; } }").line, 1);
        assert!(fails("technique T { pass P { A = compile vs_3_0 ; } }")
            .message
            .contains("compile"));
        assert!(fails("float a").message.contains("end of file"));
        assert!(fails("void f() { ").message.contains("end of file"));
        assert!(fails("}").message.contains("unmatched"));
        assert!(fails("float a < string s = 1 ; ")
            .message
            .contains("end of file"));
        assert!(fails("technique T { float x; }").message.contains("pass"));
        assert!(fails("x;").message.contains("declaration"));
        assert!(fails("float a[ = 1;").message.contains("end of file"));
        assert!(fails("void f() { ( ] }").message.contains("unmatched"));
    }

    #[test]
    fn deeply_nested_input_does_not_overflow_the_stack() {
        let n = 200_000;
        let src = format!("float a = {}1{};", "(".repeat(n), ")".repeat(n));
        let a = ast(&src);
        assert_eq!(a.globals.len(), 1);
        let src = format!("float a = {}1{};", "{".repeat(n), "}".repeat(n));
        let _ = parse(&src, &lex(&src).unwrap());
    }
}
