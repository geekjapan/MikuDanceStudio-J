//! The parameters, techniques, and passes of an effect in the shape of `fx_reflect.exe`
//! (RM-3), so that `tools/rust/fx_reflect_compare.py` can join the two per file.
//!
//! `class` and `type` use the D3DXPARAMETER_CLASS and D3DXPARAMETER_TYPE numbers. Strings are
//! the decoded text; the D3DX side holds raw bytes.

use std::fmt::Write;

use crate::ast::{Annotation, Global, Value};
use crate::Effect;

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
pub const TYPE_SAMPLER: u8 = 10;

/// What `ID3DXEffect::GetParameterDesc` reports for a declared type.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Shape {
    pub class: u8,
    pub ty: u8,
    pub rows: u8,
    pub columns: u8,
}

/// The shape of the type `ty` as written (`float3`, `float4x4`, `texture`), with `column_major`
/// set when the declaration says so. `None` for a type this module does not know, such as a
/// user struct.
pub fn shape(ty: &str, column_major: bool) -> Option<Shape> {
    let ty = ty.trim();
    let (class, ty_id, rows, columns) = match ty {
        "string" => (CLASS_OBJECT, TYPE_STRING, 0, 0),
        "texture" => (CLASS_OBJECT, TYPE_TEXTURE, 0, 0),
        "texture2D" => (CLASS_OBJECT, TYPE_TEXTURE2D, 0, 0),
        "sampler" => (CLASS_OBJECT, TYPE_SAMPLER, 0, 0),
        _ => {
            let (base, dims) =
                ty.split_at(ty.find(|c: char| c.is_ascii_digit()).unwrap_or(ty.len()));
            let ty_id = match base {
                "bool" => TYPE_BOOL,
                "int" => TYPE_INT,
                "float" | "half" | "double" => TYPE_FLOAT,
                _ => return None,
            };
            let digit = |s: &str| s.parse::<u8>().ok().filter(|n| (1..=4).contains(n));
            match dims.split_once('x') {
                None if dims.is_empty() => (CLASS_SCALAR, ty_id, 1, 1),
                None => (CLASS_VECTOR, ty_id, 1, digit(dims)?),
                Some((r, c)) => (
                    if column_major {
                        CLASS_MATRIX_COLUMNS
                    } else {
                        CLASS_MATRIX_ROWS
                    },
                    ty_id,
                    digit(r)?,
                    digit(c)?,
                ),
            }
        }
    };
    Some(Shape {
        class,
        ty: ty_id,
        rows,
        columns,
    })
}

struct Json(String);

impl Json {
    fn str(&mut self, s: &str) {
        self.0.push('"');
        for c in s.chars() {
            match c {
                '"' | '\\' => {
                    self.0.push('\\');
                    self.0.push(c);
                }
                c if (c as u32) < 0x20 => {
                    let _ = write!(self.0, "\\u{:04x}", c as u32);
                }
                c => self.0.push(c),
            }
        }
        self.0.push('"');
    }

    fn key(&mut self, k: &str) {
        self.str(k);
        self.0.push(':');
    }

    fn shape(&mut self, shape: Option<Shape>) {
        match shape {
            Some(s) => {
                let _ = write!(
                    self.0,
                    "\"class\":{},\"type\":{},\"rows\":{},\"columns\":{}",
                    s.class, s.ty, s.rows, s.columns
                );
            }
            None => self
                .0
                .push_str("\"class\":null,\"type\":null,\"rows\":null,\"columns\":null"),
        }
    }
}

/// D3DX keeps `static` variables out of the effect's parameter list.
fn is_parameter(g: &Global) -> bool {
    !g.modifiers.iter().any(|m| m == "static")
}

fn is_column_major(modifiers: &[String]) -> bool {
    modifiers.iter().any(|m| m == "column_major")
}

/// D3DX reports `float2 K[6][9]` as one array of 54 elements. `None` when a dimension is not
/// an integer literal.
fn elements(array: &[String]) -> Option<u32> {
    if array.is_empty() {
        return Some(0);
    }
    array
        .iter()
        .try_fold(1u32, |n, d| n.checked_mul(d.trim().parse().ok()?))
}

#[derive(Clone, Copy)]
enum Num {
    Int(i64),
    Float(f32),
}

impl Num {
    fn float(self) -> f32 {
        match self {
            Num::Int(i) => i as f32,
            Num::Float(f) => f,
        }
    }

    fn apply(self, op: &str, rhs: Num) -> Option<Num> {
        if let (Num::Int(a), Num::Int(b)) = (self, rhs) {
            return Some(Num::Int(match op {
                "+" => a.checked_add(b)?,
                "-" => a.checked_sub(b)?,
                "*" => a.checked_mul(b)?,
                _ => a.checked_div(b)?,
            }));
        }
        let (a, b) = (self.float(), rhs.float());
        Some(Num::Float(match op {
            "+" => a + b,
            "-" => a - b,
            "*" => a * b,
            _ => a / b,
        }))
    }
}

/// Folds an `Expr` of numbers, `+ - * /`, and parentheses the way D3DX folds an annotation
/// initializer: integers stay integers until a float joins them, floats are 32-bit.
fn fold(expr: &str) -> Option<Num> {
    fn sum(t: &mut std::iter::Peekable<std::str::SplitWhitespace>) -> Option<Num> {
        let mut acc = product(t)?;
        while let Some(&op @ ("+" | "-")) = t.peek() {
            t.next();
            acc = acc.apply(op, product(t)?)?;
        }
        Some(acc)
    }
    fn product(t: &mut std::iter::Peekable<std::str::SplitWhitespace>) -> Option<Num> {
        let mut acc = unary(t)?;
        while let Some(&op @ ("*" | "/")) = t.peek() {
            t.next();
            acc = acc.apply(op, unary(t)?)?;
        }
        Some(acc)
    }
    fn unary(t: &mut std::iter::Peekable<std::str::SplitWhitespace>) -> Option<Num> {
        let tok = t.next()?;
        match tok {
            "-" => Some(match unary(t)? {
                Num::Int(i) => Num::Int(i.checked_neg()?),
                Num::Float(f) => Num::Float(-f),
            }),
            "+" => unary(t),
            "(" => {
                let v = sum(t)?;
                (t.next()? == ")").then_some(v)
            }
            _ => {
                let lit = tok.trim_end_matches(['f', 'F', 'h', 'H']);
                match lit.parse::<i64>() {
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

/// The scalar components of `v`, as fx_reflect prints them: float bits, ints, and bools as 0/1.
/// `None` for identifiers and expressions, which fx_reflect cannot read either.
fn components(v: &Value, ty: Option<Shape>, out: &mut Vec<String>) -> bool {
    let as_float = ty.is_some_and(|s| s.ty == TYPE_FLOAT);
    match v {
        Value::Int(n) if as_float => out.push(format!("\"0x{:08x}\"", (*n as f32).to_bits())),
        Value::Int(n) => out.push(n.to_string()),
        Value::Float(f) if as_float => out.push(format!("\"0x{:08x}\"", (*f as f32).to_bits())),
        Value::Float(f) => out.push((*f as i64).to_string()),
        Value::Bool(b) => out.push(u8::from(*b).to_string()),
        Value::Vector(items) => return items.iter().all(|i| components(i, ty, out)),
        Value::Expr(text) => match fold(text) {
            Some(n) if as_float => out.push(format!("\"0x{:08x}\"", n.float().to_bits())),
            Some(Num::Int(i)) => out.push(i.to_string()),
            Some(Num::Float(f)) => out.push((f as i64).to_string()),
            None => return false,
        },
        _ => return false,
    }
    true
}

fn annotations(j: &mut Json, list: &[Annotation]) {
    j.0.push('[');
    for (i, a) in list.iter().enumerate() {
        if i > 0 {
            j.0.push(',');
        }
        let shape = shape(&a.ty, false);
        j.0.push('{');
        j.key("name");
        j.str(&a.name);
        j.0.push(',');
        j.shape(shape);
        j.0.push(',');
        j.key("value");
        let mut parts = Vec::new();
        match &a.value {
            Value::Str(s) => j.str(s),
            v if components(v, shape, &mut parts) => {
                let _ = write!(j.0, "[{}]", parts.join(","));
            }
            _ => j.0.push_str("null"),
        }
        j.0.push('}');
    }
    j.0.push(']');
}

fn parameter(j: &mut Json, g: &Global) {
    j.0.push('{');
    j.key("name");
    j.str(&g.name);
    j.0.push(',');
    j.key("semantic");
    j.str(g.semantic.as_deref().unwrap_or(""));
    j.0.push(',');
    j.shape(shape(&g.ty, is_column_major(&g.modifiers)));
    j.0.push(',');
    j.key("elements");
    match elements(&g.array) {
        Some(n) => {
            let _ = write!(j.0, "{n}");
        }
        None => j.0.push_str("null"),
    }
    j.0.push(',');
    j.key("declared");
    j.str(&format!("{} {}", g.modifiers.join(" "), g.ty));
    j.0.push(',');
    j.key("annotations");
    annotations(j, &g.annotations);
    j.0.push('}');
}

/// The object `reflect` would give for a file that failed to parse.
pub fn reflect_error(file: &str, message: &str) -> String {
    let mut j = Json(String::new());
    j.0.push('{');
    j.key("file");
    j.str(file);
    j.0.push_str(",\"result\":\"error\",");
    j.key("error");
    j.str(message);
    j.0.push('}');
    j.0
}

/// One JSON object (no trailing newline) for `fx`, labelled `file`.
pub fn reflect(file: &str, fx: &Effect) -> String {
    let mut j = Json(String::new());
    j.0.push('{');
    j.key("file");
    j.str(file);
    j.0.push_str(",\"result\":\"ok\",");
    j.key("parameters");
    j.0.push('[');
    for (i, g) in fx
        .ast
        .globals
        .iter()
        .filter(|g| is_parameter(g))
        .enumerate()
    {
        if i > 0 {
            j.0.push(',');
        }
        parameter(&mut j, g);
    }
    j.0.push_str("],");
    j.key("techniques");
    j.0.push('[');
    for (i, t) in fx.ast.techniques.iter().enumerate() {
        if i > 0 {
            j.0.push(',');
        }
        j.0.push('{');
        j.key("name");
        j.str(t.name.as_deref().unwrap_or(""));
        j.0.push(',');
        j.key("annotations");
        annotations(&mut j, &t.annotations);
        j.0.push(',');
        j.key("passes");
        j.0.push('[');
        for (k, p) in t.passes.iter().enumerate() {
            if k > 0 {
                j.0.push(',');
            }
            j.0.push('{');
            j.key("name");
            j.str(p.name.as_deref().unwrap_or(""));
            j.0.push(',');
            j.key("annotations");
            annotations(&mut j, &p.annotations);
            j.0.push('}');
        }
        j.0.push_str("]}");
    }
    j.0.push_str("]}");
    j.0
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::TempTree;

    fn json(src: &str) -> String {
        let t = TempTree::new();
        t.write("a.fx", src.as_bytes());
        reflect("a", &Effect::parse_file(&t.path("a.fx")).unwrap())
    }

    #[test]
    fn shapes_follow_the_d3dx_enums() {
        let s = |t, cm| shape(t, cm).map(|s| (s.class, s.ty, s.rows, s.columns));
        assert_eq!(s("float", false), Some((CLASS_SCALAR, TYPE_FLOAT, 1, 1)));
        assert_eq!(s("int", false), Some((CLASS_SCALAR, TYPE_INT, 1, 1)));
        assert_eq!(s("bool", false), Some((CLASS_SCALAR, TYPE_BOOL, 1, 1)));
        assert_eq!(s("float3", false), Some((CLASS_VECTOR, TYPE_FLOAT, 1, 3)));
        assert_eq!(
            s("float3x4", false),
            Some((CLASS_MATRIX_ROWS, TYPE_FLOAT, 3, 4))
        );
        assert_eq!(
            s("float4x4", true),
            Some((CLASS_MATRIX_COLUMNS, TYPE_FLOAT, 4, 4))
        );
        assert_eq!(s("string", false), Some((CLASS_OBJECT, TYPE_STRING, 0, 0)));
        assert_eq!(
            s("texture", false),
            Some((CLASS_OBJECT, TYPE_TEXTURE, 0, 0))
        );
        assert_eq!(
            s("texture2D", false),
            Some((CLASS_OBJECT, TYPE_TEXTURE2D, 0, 0))
        );
        assert_eq!(
            s("sampler", false),
            Some((CLASS_OBJECT, TYPE_SAMPLER, 0, 0))
        );
        assert_eq!(shape("VS_OUT", false), None);
        assert_eq!(shape("float5", false), None);
    }

    /// Known D3DX behavior: `static` variables are not effect parameters.
    #[test]
    fn static_globals_are_not_parameters() {
        let j =
            json("static float s = 1;\nstatic const float3 c = 0;\nfloat p;\nconst float q = 2;\n");
        assert!(
            j.contains("\"name\":\"p\"") && j.contains("\"name\":\"q\""),
            "{j}"
        );
        assert!(
            !j.contains("\"name\":\"s\"") && !j.contains("\"name\":\"c\""),
            "{j}"
        );
    }

    /// Known D3DX behavior: a multi-dimensional array is one array of the product.
    #[test]
    fn multi_dimensional_arrays_report_the_product() {
        let j = json("float2 K[6][9] = { 0 };\nfloat A[3];\nfloat B;\n");
        assert!(j.contains("\"name\":\"K\",\"semantic\":\"\",\"class\":1,\"type\":3,\"rows\":1,\"columns\":2,\"elements\":54"), "{j}");
        assert!(
            j.contains("\"name\":\"A\"") && j.contains("\"elements\":3"),
            "{j}"
        );
        assert_eq!(elements(&[]), Some(0));
        assert_eq!(elements(&["N".into()]), None);
    }

    /// Known D3DX behavior: the compiler folds constant annotation expressions, with 32-bit
    /// floats, and keeps the semantic's case.
    #[test]
    fn annotation_expressions_are_folded_and_semantics_keep_their_case() {
        let j = json(
            "#define L 3\ntexture T <int Miplevels = L + 1; float4 C = { 0, (127.0f / 255.0f), 0, 1 };>;\nfloat x : RenderColorTarget;\n",
        );
        assert!(j.contains("\"name\":\"Miplevels\",\"class\":0,\"type\":2,\"rows\":1,\"columns\":1,\"value\":[4]"), "{j}");
        assert!(
            j.contains("\"value\":[\"0x00000000\",\"0x3efefeff\",\"0x00000000\",\"0x3f800000\"]"),
            "{j}"
        );
        assert!(j.contains("\"semantic\":\"RenderColorTarget\""), "{j}");
        assert_eq!(fold("2 * ( 3 + 1 ) - 1").map(|n| n.float()), Some(7.0));
        assert!(fold("a + 1").is_none() && fold("1 +").is_none() && fold("1 / 0").is_none());
    }

    #[test]
    fn techniques_and_passes_list_names_and_annotations() {
        let j = json(
            "technique T < string Script = \"a\"; > { pass P < string N = \"x\"; > { } pass { } }\n",
        );
        assert!(j.contains("\"techniques\":[{\"name\":\"T\",\"annotations\":[{\"name\":\"Script\",\"class\":4,\"type\":4,\"rows\":0,\"columns\":0,\"value\":\"a\"}]"), "{j}");
        assert!(j.contains("\"passes\":[{\"name\":\"P\""), "{j}");
        assert!(j.contains("{\"name\":\"\",\"annotations\":[]}"), "{j}");
    }
}
