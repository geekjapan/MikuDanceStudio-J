//! What `ID3DXEffect` reports for an effect, built from the mds-fx syntax tree: the
//! top-level parameters with their descriptions, annotations, and initial values, and the
//! techniques and passes with the shader profiles they compile.
//!
//! The getters follow the D3DX9 conversion rules the runtime relies on: `GetFloat`, `GetInt`,
//! and `GetBool` read scalars only, the array getters copy as many components as there are,
//! and numbers convert between bool, int, and float.

use mds_fx::{Annotation, Effect, Initializer, StateValue, Value};

pub const CLASS_SCALAR: u8 = 0;
pub const CLASS_VECTOR: u8 = 1;
pub const CLASS_MATRIX_ROWS: u8 = 2;
pub const CLASS_MATRIX_COLUMNS: u8 = 3;
pub const CLASS_OBJECT: u8 = 4;
pub const CLASS_STRUCT: u8 = 5;

pub const TYPE_VOID: u8 = 0;
pub const TYPE_BOOL: u8 = 1;
pub const TYPE_INT: u8 = 2;
pub const TYPE_FLOAT: u8 = 3;
pub const TYPE_STRING: u8 = 4;
pub const TYPE_TEXTURE: u8 = 5;
pub const TYPE_TEXTURE2D: u8 = 7;
pub const TYPE_TEXTURE3D: u8 = 8;
pub const TYPE_TEXTURECUBE: u8 = 9;

/// `D3DXPARAMETER_DESC` without the name: class, type, rows, columns, elements.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Desc {
    pub class: u8,
    pub ty: u8,
    pub rows: u32,
    pub columns: u32,
    pub elements: u32,
}

impl Desc {
    fn components(&self) -> usize {
        (self.rows * self.columns * self.elements.max(1)) as usize
    }

    pub fn is_numeric(&self) -> bool {
        matches!(self.ty, TYPE_BOOL | TYPE_INT | TYPE_FLOAT) && self.class <= CLASS_MATRIX_COLUMNS
    }

    fn is_scalar(&self) -> bool {
        self.rows == 1 && self.columns == 1 && self.elements == 0 && self.is_numeric()
    }

    pub fn is_texture(&self) -> bool {
        (TYPE_TEXTURE..=TYPE_TEXTURECUBE).contains(&self.ty)
    }
}

/// One component of a numeric value, already in the declared type.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Num {
    Bool(bool),
    Int(i32),
    Float(f32),
}

impl Num {
    pub fn float(self) -> f32 {
        match self {
            Num::Bool(b) => f32::from(u8::from(b)),
            Num::Int(i) => i as f32,
            Num::Float(f) => f,
        }
    }

    pub fn int(self) -> i32 {
        match self {
            Num::Bool(b) => i32::from(b),
            Num::Int(i) => i,
            Num::Float(f) => f as i32,
        }
    }

    pub fn bool(self) -> bool {
        match self {
            Num::Bool(b) => b,
            Num::Int(i) => i != 0,
            Num::Float(f) => f != 0.0,
        }
    }

    fn to_type(self, ty: u8) -> Num {
        match ty {
            TYPE_BOOL => Num::Bool(self.bool()),
            TYPE_INT => Num::Int(self.int()),
            _ => Num::Float(self.float()),
        }
    }
}

/// The value D3DX holds for a parameter or annotation.
#[derive(Clone, Debug, PartialEq)]
pub enum Data {
    Str(String),
    Nums(Vec<Num>),
    /// No value, or one this model cannot evaluate.
    None,
}

/// A parameter or an annotation: both are `D3DXHANDLE`s with a description in D3DX.
#[derive(Clone, Debug)]
pub struct Item {
    pub name: String,
    pub semantic: String,
    pub desc: Desc,
    /// `D3DX_PARAMETER_SHARED` (`Flags & 1`), which the oracle prints as `literal`.
    pub shared: bool,
    pub annotations: Vec<Item>,
    pub data: Data,
}

impl Item {
    /// The annotation `name`, matched without case like `SasFindAnnotation`.
    pub fn annotation(&self, name: &str) -> Option<&Item> {
        self.annotations
            .iter()
            .find(|a| a.name.eq_ignore_ascii_case(name))
    }

    pub fn get_string(&self) -> Option<&str> {
        match &self.data {
            Data::Str(s) if self.desc.ty == TYPE_STRING && self.desc.elements == 0 => Some(s),
            _ => None,
        }
    }

    fn nums(&self) -> Option<&[Num]> {
        match &self.data {
            Data::Nums(n) if self.desc.is_numeric() => Some(n),
            _ => None,
        }
    }

    fn scalar(&self) -> Option<Num> {
        if !self.desc.is_scalar() {
            return None;
        }
        self.nums()?.first().copied()
    }

    pub fn get_float(&self) -> Option<f32> {
        self.scalar().map(Num::float)
    }

    pub fn get_int(&self) -> Option<i32> {
        self.scalar().map(Num::int)
    }

    pub fn get_bool(&self) -> Option<bool> {
        self.scalar().map(Num::bool)
    }

    /// `GetVector`: the components of a scalar or vector over `seed`.
    pub fn get_vector(&self, mut seed: [f32; 4]) -> Option<[f32; 4]> {
        if self.desc.elements != 0 || self.desc.class > CLASS_VECTOR {
            return None;
        }
        for (s, n) in seed.iter_mut().zip(self.nums()?) {
            *s = n.float();
        }
        Some(seed)
    }

    /// `GetIntArray` / `GetFloatArray` / `GetBoolArray`: at most `count` components.
    pub fn get_array(&self, count: usize) -> Option<Vec<Num>> {
        Some(self.nums()?.iter().take(count).copied().collect())
    }

    pub fn set_int(&mut self, v: i32) {
        if self.desc.is_numeric() {
            if let Data::Nums(n) = &mut self.data {
                if let Some(first) = n.first_mut() {
                    *first = Num::Int(v).to_type(self.desc.ty);
                }
            }
        }
    }
}

#[derive(Clone, Debug)]
pub struct Pass {
    pub name: String,
    pub annotations: Vec<Item>,
    /// The compiled vertex shader: profile and entry function.
    pub vs: Option<(String, String)>,
    pub ps: Option<(String, String)>,
}

#[derive(Clone, Debug)]
pub struct Technique {
    pub name: String,
    pub annotations: Vec<Item>,
    pub passes: Vec<Pass>,
}

/// The D3DX side of one compiled effect.
#[derive(Clone, Debug)]
pub struct Fx {
    pub params: Vec<Item>,
    pub techniques: Vec<Technique>,
    /// Function name and parameter texts, for the PSIZE15 input probe.
    pub functions: Vec<(String, Vec<String>)>,
}

impl Fx {
    pub fn new(effect: &Effect) -> Fx {
        let ast = &effect.ast;
        let params = ast
            .globals
            .iter()
            .filter(|g| !g.modifiers.iter().any(|m| m == "static"))
            .map(|g| {
                let column_major = g.modifiers.iter().any(|m| m == "column_major");
                // `float2 K[6][9]` is one array of 54 elements.
                let elements = if g.array.is_empty() {
                    0
                } else {
                    g.array
                        .iter()
                        .map(|d| fold(d).map_or(0, |v| v.int().max(0) as u32))
                        .product()
                };
                let mut desc = shape(&g.ty, column_major);
                desc.elements = elements;
                let data = match &g.initializer {
                    Some(Initializer::Value(v)) => data(v, &desc),
                    _ if desc.is_numeric() => {
                        Data::Nums(vec![Num::Int(0).to_type(desc.ty); desc.components()])
                    }
                    _ => Data::None,
                };
                Item {
                    name: g.name.clone(),
                    semantic: g.semantic.clone().unwrap_or_default(),
                    desc,
                    shared: g.modifiers.iter().any(|m| m == "shared"),
                    annotations: annotations(&g.annotations),
                    data,
                }
            })
            .collect();
        let techniques = ast
            .techniques
            .iter()
            .map(|t| Technique {
                name: t.name.clone().unwrap_or_default(),
                annotations: annotations(&t.annotations),
                passes: t
                    .passes
                    .iter()
                    .map(|p| {
                        let shader = |state: &str| {
                            p.states.iter().rev().find_map(|s| match &s.value {
                                StateValue::Compile(c) if s.name.eq_ignore_ascii_case(state) => {
                                    Some((c.profile.clone(), c.function.clone()))
                                }
                                _ => None,
                            })
                        };
                        Pass {
                            name: p.name.clone().unwrap_or_default(),
                            annotations: annotations(&p.annotations),
                            vs: shader("VertexShader"),
                            ps: shader("PixelShader"),
                        }
                    })
                    .collect(),
            })
            .collect();
        let functions = ast
            .functions
            .iter()
            .map(|f| (f.name.clone(), f.params.clone()))
            .collect();
        Fx {
            params,
            techniques,
            functions,
        }
    }

    /// `GetParameterByName(NULL, name)`: an exact, case-sensitive top-level name.
    pub fn param_by_name(&self, name: &str) -> Option<usize> {
        self.params.iter().position(|p| p.name == name)
    }

    pub fn technique_by_name(&self, name: &str) -> Option<usize> {
        self.techniques.iter().position(|t| t.name == name)
    }
}

/// The description of a declared type. Unknown names (user structs) are `STRUCT`/`VOID`.
pub fn shape(ty: &str, column_major: bool) -> Desc {
    let ty = ty.trim();
    let object = |ty| Desc {
        class: CLASS_OBJECT,
        ty,
        rows: 0,
        columns: 0,
        elements: 0,
    };
    let lower = ty.to_ascii_lowercase();
    let obj = match lower.as_str() {
        "string" => Some(TYPE_STRING),
        "texture" => Some(TYPE_TEXTURE),
        "texture1d" => Some(6),
        "texture2d" => Some(TYPE_TEXTURE2D),
        "texture3d" => Some(TYPE_TEXTURE3D),
        "texturecube" => Some(TYPE_TEXTURECUBE),
        "sampler" => Some(10),
        "sampler1d" => Some(11),
        "sampler2d" => Some(12),
        "sampler3d" => Some(13),
        "samplercube" => Some(14),
        "pixelshader" => Some(15),
        "vertexshader" => Some(16),
        _ => None,
    };
    if let Some(t) = obj {
        return object(t);
    }
    let num = |class, ty, rows, columns| Desc {
        class,
        ty,
        rows,
        columns,
        elements: 0,
    };
    let matrix = if column_major {
        CLASS_MATRIX_COLUMNS
    } else {
        CLASS_MATRIX_ROWS
    };
    match ty {
        "matrix" => return num(matrix, TYPE_FLOAT, 4, 4),
        "vector" => return num(CLASS_VECTOR, TYPE_FLOAT, 1, 4),
        _ => {}
    }
    let (base, dims) = ty.split_at(ty.find(|c: char| c.is_ascii_digit()).unwrap_or(ty.len()));
    let base_ty = match base {
        "bool" => TYPE_BOOL,
        "int" | "uint" | "dword" => TYPE_INT,
        "float" | "half" | "double" => TYPE_FLOAT,
        _ => {
            return num(CLASS_STRUCT, TYPE_VOID, 1, 1);
        }
    };
    let digit = |s: &str| s.parse::<u32>().ok().filter(|n| (1..=4).contains(n));
    let parsed = match dims.split_once('x') {
        None if dims.is_empty() => Some(num(CLASS_SCALAR, base_ty, 1, 1)),
        None => digit(dims).map(|c| num(CLASS_VECTOR, base_ty, 1, c)),
        Some((r, c)) => digit(r)
            .zip(digit(c))
            .map(|(r, c)| num(matrix, base_ty, r, c)),
    };
    parsed.unwrap_or(num(CLASS_STRUCT, TYPE_VOID, 1, 1))
}

fn annotations(list: &[Annotation]) -> Vec<Item> {
    list.iter()
        .map(|a| {
            let desc = shape(&a.ty, false);
            Item {
                name: a.name.clone(),
                semantic: String::new(),
                desc,
                shared: false,
                annotations: Vec::new(),
                data: data(&a.value, &desc),
            }
        })
        .collect()
}

/// The value of an initializer in the declared type. A single number fills a vector, as
/// HLSL promotes a scalar.
fn data(v: &Value, desc: &Desc) -> Data {
    if desc.ty == TYPE_STRING {
        return match v {
            Value::Str(s) => Data::Str(s.clone()),
            _ => Data::None,
        };
    }
    if !desc.is_numeric() {
        return Data::None;
    }
    let mut out = Vec::new();
    if !flatten(v, &mut out) {
        return Data::None;
    }
    let n = desc.components();
    if out.len() == 1 && n > 1 {
        out = vec![out[0]; n];
    }
    if out.len() < n {
        out.resize(n, Num::Int(0));
    }
    out.truncate(n);
    Data::Nums(out.into_iter().map(|x| x.to_type(desc.ty)).collect())
}

fn flatten(v: &Value, out: &mut Vec<Num>) -> bool {
    match v {
        Value::Int(i) => out.push(Num::Int(*i as i32)),
        Value::Float(f) => out.push(Num::Float(*f as f32)),
        Value::Bool(b) => out.push(Num::Bool(*b)),
        Value::Vector(items) => return items.iter().all(|i| flatten(i, out)),
        Value::Expr(text) => match fold(text) {
            Some(n) => out.push(n),
            None => return false,
        },
        Value::Ident(t) if t == "true" || t == "false" => out.push(Num::Bool(t == "true")),
        _ => return false,
    }
    true
}

/// Folds an expression of numbers, `+ - * /`, and parentheses the way the HLSL compiler folds
/// a constant initializer: integers stay integers until a float joins them, floats are 32-bit.
/// The same rule as `mds_fx::reflect`, whose folder is private.
pub fn fold(expr: &str) -> Option<Num> {
    type Toks<'a> = std::iter::Peekable<std::str::SplitWhitespace<'a>>;
    fn apply(a: Num, op: &str, b: Num) -> Option<Num> {
        if let (Num::Int(a), Num::Int(b)) = (a, b) {
            return Some(Num::Int(match op {
                "+" => a.checked_add(b)?,
                "-" => a.checked_sub(b)?,
                "*" => a.checked_mul(b)?,
                _ => a.checked_div(b)?,
            }));
        }
        let (a, b) = (a.float(), b.float());
        Some(Num::Float(match op {
            "+" => a + b,
            "-" => a - b,
            "*" => a * b,
            _ => a / b,
        }))
    }
    fn sum(t: &mut Toks) -> Option<Num> {
        let mut acc = product(t)?;
        while let Some(&op @ ("+" | "-")) = t.peek() {
            t.next();
            acc = apply(acc, op, product(t)?)?;
        }
        Some(acc)
    }
    fn product(t: &mut Toks) -> Option<Num> {
        let mut acc = unary(t)?;
        while let Some(&op @ ("*" | "/")) = t.peek() {
            t.next();
            acc = apply(acc, op, unary(t)?)?;
        }
        Some(acc)
    }
    fn unary(t: &mut Toks) -> Option<Num> {
        let tok = t.next()?;
        match tok {
            "-" => Some(match unary(t)? {
                Num::Int(i) => Num::Int(i.checked_neg()?),
                Num::Float(f) => Num::Float(-f),
                Num::Bool(b) => Num::Int(-i32::from(b)),
            }),
            "+" => unary(t),
            "(" => {
                let v = sum(t)?;
                (t.next()? == ")").then_some(v)
            }
            "true" => Some(Num::Bool(true)),
            "false" => Some(Num::Bool(false)),
            _ => {
                let lit = tok.trim_end_matches(['f', 'F', 'h', 'H']);
                match lit.parse::<i32>() {
                    Ok(i) if lit.len() == tok.len() => Some(Num::Int(i)),
                    _ => lit.parse::<f32>().ok().map(Num::Float),
                }
            }
        }
    }
    let mut t = expr.split_whitespace().peekable();
    let v = sum(&mut t)?;
    t.next().is_none().then_some(v)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shapes() {
        let s = |t| {
            let d = shape(t, false);
            (d.class, d.ty, d.rows, d.columns)
        };
        assert_eq!(s("float4x4"), (CLASS_MATRIX_ROWS, TYPE_FLOAT, 4, 4));
        assert_eq!(s("matrix"), (CLASS_MATRIX_ROWS, TYPE_FLOAT, 4, 4));
        assert_eq!(s("float2"), (CLASS_VECTOR, TYPE_FLOAT, 1, 2));
        assert_eq!(s("texture2D"), (CLASS_OBJECT, TYPE_TEXTURE2D, 0, 0));
        assert_eq!(s("VS_OUT"), (CLASS_STRUCT, TYPE_VOID, 1, 1));
    }

    #[test]
    fn folds_constants() {
        assert_eq!(fold("( 3 + 1 ) * 2"), Some(Num::Int(8)));
        assert_eq!(fold("127.0 / 255.0"), Some(Num::Float(127.0f32 / 255.0)));
        assert_eq!(fold("a + 1"), None);
    }
}
