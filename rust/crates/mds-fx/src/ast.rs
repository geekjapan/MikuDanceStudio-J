//! Syntax tree of an effect file.
//!
//! `line` fields are 1-based lines of the preprocessed text. Use
//! [`Effect::origin`](crate::Effect::origin) to map one to its source file and line.

use std::ops::Range;

/// A literal value of an annotation, initializer, or state assignment.
#[derive(Clone, Debug, PartialEq)]
pub enum Value {
    Int(i64),
    Float(f64),
    Bool(bool),
    /// Unescaped string contents, adjacent literals joined.
    Str(String),
    /// A bare identifier, such as an enum value (`LINEAR`) or a texture name.
    Ident(String),
    /// `{ a, b }` or `float3(a, b)` with literal elements.
    Vector(Vec<Value>),
    /// Any other expression, as its tokens joined by single spaces.
    Expr(String),
}

/// `<string Name = "x";>` entry. `ty` is the declared type as written, for example `float3`.
#[derive(Clone, Debug, PartialEq)]
pub struct Annotation {
    pub ty: String,
    pub name: String,
    pub value: Value,
    pub line: u32,
}

/// `compile vs_3_0 Main(args)`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Compile {
    pub profile: String,
    pub function: String,
    /// Arguments split at top-level commas, each as tokens joined by single spaces.
    pub args: Vec<String>,
    /// All argument tokens joined by single spaces, as `shaders-direct.tsv` prints them.
    pub args_text: String,
}

#[derive(Clone, Debug, PartialEq)]
pub enum StateValue {
    Compile(Compile),
    /// `texture = <Name>`, `texture = (Name)`, or `texture = Name` in a `sampler_state`.
    Texture(String),
    Value(Value),
}

/// `Name = value;` or `Name[index] = value;` in a pass or a `sampler_state`.
#[derive(Clone, Debug, PartialEq)]
pub struct StateAssignment {
    pub name: String,
    pub index: Option<u32>,
    pub value: StateValue,
    pub line: u32,
}

/// `sampler_state { ... }`.
#[derive(Clone, Debug, PartialEq, Default)]
pub struct SamplerState {
    pub states: Vec<StateAssignment>,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Initializer {
    Sampler(SamplerState),
    Value(Value),
}

/// A global variable, texture, or sampler.
#[derive(Clone, Debug, PartialEq)]
pub struct Global {
    /// `static`, `const`, `uniform`, `shared`, and similar.
    pub modifiers: Vec<String>,
    pub ty: String,
    pub name: String,
    /// Array dimensions as written (`[2]` gives `"2"`).
    pub array: Vec<String>,
    pub semantic: Option<String>,
    pub annotations: Vec<Annotation>,
    pub initializer: Option<Initializer>,
    pub line: u32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Pass {
    pub name: Option<String>,
    pub annotations: Vec<Annotation>,
    pub states: Vec<StateAssignment>,
    pub line: u32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Technique {
    pub name: Option<String>,
    pub annotations: Vec<Annotation>,
    pub passes: Vec<Pass>,
    pub line: u32,
    /// Byte range of the whole block in the preprocessed text, `technique` through `}`.
    pub span: Range<usize>,
}

/// A function definition or prototype. Bodies are not parsed.
#[derive(Clone, Debug, PartialEq)]
pub struct Function {
    pub name: String,
    /// Modifiers and return type tokens, joined by single spaces.
    pub return_type: String,
    /// Each parameter as tokens joined by single spaces.
    pub params: Vec<String>,
    pub return_semantic: Option<String>,
    pub has_body: bool,
    pub line: u32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct StructDecl {
    pub name: String,
    pub line: u32,
}

#[derive(Clone, Debug, PartialEq, Default)]
pub struct EffectAst {
    pub globals: Vec<Global>,
    pub structs: Vec<StructDecl>,
    pub functions: Vec<Function>,
    pub techniques: Vec<Technique>,
}

impl EffectAst {
    pub fn pass_count(&self) -> usize {
        self.techniques.iter().map(|t| t.passes.len()).sum()
    }

    /// Every `compile` expression in pass order.
    pub fn compiles(&self) -> impl Iterator<Item = &Compile> {
        self.techniques.iter().flat_map(|t| &t.passes).flat_map(|p| &p.states).filter_map(|s| match &s.value {
            StateValue::Compile(c) => Some(c),
            _ => None,
        })
    }
}
