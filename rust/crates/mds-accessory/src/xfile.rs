//! A reader for the DirectX `.x` container: the text format and the binary
//! format (`xof 0302txt`, `0303txt`, `0302bin`, `0303bin`; float size `0032` or
//! `0064`) into a tree of data objects.
//!
//! D3DX reads `.x` files through `ID3DXFile`, whose templates define which
//! numbers belong to which member. This reader keeps every object's numbers
//! and strings flat in file order and leaves the meaning to
//! [`crate::mesh`], which is enough because every count in the templates it
//! needs is stored in the data. Compressed files (`tzip`, `bzip`) return
//! [`Error::Unsupported`].

use crate::Error;

#[derive(Clone, Debug, PartialEq)]
pub enum Value {
    Int(i64),
    Float(f32),
    /// A string as stored: raw bytes, usually Shift-JIS.
    Str(Vec<u8>),
}

#[derive(Clone, Debug, PartialEq)]
pub enum Child {
    Node(Node),
    /// `{ Name }`: a reference to a named object declared elsewhere.
    Ref(String),
}

#[derive(Clone, Debug, PartialEq)]
pub struct Node {
    pub kind: String,
    pub name: Option<String>,
    pub values: Vec<Value>,
    pub children: Vec<Child>,
}

const MAX_DEPTH: usize = 64;

/// Parses a whole file into its top-level data objects. Template
/// declarations are skipped.
pub fn parse(data: &[u8]) -> Result<Vec<Node>, Error> {
    if data.len() < 16 || &data[..4] != b"xof " {
        return Err(Error::BadHeader);
    }
    if !matches!(&data[4..8], b"0302" | b"0303") || !matches!(&data[12..16], b"0032" | b"0064") {
        return Err(Error::BadHeader);
    }
    let body = &data[16..];
    match &data[8..12] {
        b"txt " => parse_text(body),
        b"bin " => parse_binary(body, &data[12..16] == b"0064"),
        b"tzip" | b"bzip" => Err(Error::Unsupported("compressed .x (tzip, bzip)")),
        _ => Err(Error::BadHeader),
    }
}

// ---------------------------------------------------------------------------
// Text
// ---------------------------------------------------------------------------

#[derive(Debug)]
enum Tok {
    Open,
    Close,
    Str(Vec<u8>),
    Guid,
    Word(String),
}

fn tokenize(src: &[u8]) -> Result<Vec<Tok>, Error> {
    let mut out = Vec::new();
    let mut i = 0;
    while i < src.len() {
        let c = src[i];
        match c {
            b' ' | b'\t' | b'\r' | b'\n' | 0 | b';' | b',' => i += 1,
            b'#' => i = skip_line(src, i),
            b'/' if src.get(i + 1) == Some(&b'/') => i = skip_line(src, i),
            b'{' => {
                out.push(Tok::Open);
                i += 1;
            }
            b'}' => {
                out.push(Tok::Close);
                i += 1;
            }
            b'"' => {
                let end = src[i + 1..]
                    .iter()
                    .position(|&b| b == b'"')
                    .ok_or(Error::Syntax("unterminated string"))?;
                out.push(Tok::Str(src[i + 1..i + 1 + end].to_vec()));
                i += end + 2;
            }
            b'<' => {
                let end = src[i..]
                    .iter()
                    .position(|&b| b == b'>')
                    .ok_or(Error::Syntax("unterminated GUID"))?;
                out.push(Tok::Guid);
                i += end + 1;
            }
            _ => {
                let end = src[i..]
                    .iter()
                    .position(|b| b" \t\r\n\0;,{}\"<".contains(b))
                    .map_or(src.len(), |n| i + n);
                out.push(Tok::Word(
                    String::from_utf8_lossy(&src[i..end]).into_owned(),
                ));
                i = end;
            }
        }
    }
    Ok(out)
}

fn skip_line(src: &[u8], mut i: usize) -> usize {
    while i < src.len() && src[i] != b'\n' {
        i += 1;
    }
    i
}

fn number(word: &str) -> Option<Value> {
    let first = *word.as_bytes().first()?;
    if !(first.is_ascii_digit() || matches!(first, b'+' | b'-' | b'.')) {
        return None;
    }
    if let Ok(i) = word.parse::<i64>() {
        return Some(Value::Int(i));
    }
    word.parse::<f32>().ok().map(Value::Float)
}

struct TextParser {
    toks: Vec<Tok>,
    pos: usize,
}

impl TextParser {
    fn peek(&self, ahead: usize) -> Option<&Tok> {
        self.toks.get(self.pos + ahead)
    }

    fn skip_template(&mut self) -> Result<(), Error> {
        while !matches!(self.toks.get(self.pos), Some(Tok::Open) | None) {
            self.pos += 1;
        }
        let mut depth = 0usize;
        while let Some(t) = self.toks.get(self.pos) {
            self.pos += 1;
            match t {
                Tok::Open => depth += 1,
                Tok::Close => {
                    depth -= 1;
                    if depth == 0 {
                        return Ok(());
                    }
                }
                _ => {}
            }
        }
        Err(Error::Syntax("unterminated template"))
    }

    /// After the kind word: optional name, `{`, optional GUID, body, `}`.
    fn node(&mut self, kind: String, depth: usize) -> Result<Node, Error> {
        if depth > MAX_DEPTH {
            return Err(Error::Syntax("objects nested too deep"));
        }
        let mut name = None;
        if let Some(Tok::Word(w)) = self.peek(0) {
            name = Some(w.clone());
            self.pos += 1;
        }
        match self.toks.get(self.pos) {
            Some(Tok::Open) => self.pos += 1,
            _ => return Err(Error::Syntax("expected '{' after object type")),
        }
        if matches!(self.peek(0), Some(Tok::Guid)) {
            self.pos += 1;
        }
        let mut node = Node {
            kind,
            name,
            values: Vec::new(),
            children: Vec::new(),
        };
        loop {
            let tok = self
                .toks
                .get(self.pos)
                .ok_or(Error::Syntax("missing '}'"))?;
            self.pos += 1;
            match tok {
                Tok::Close => return Ok(node),
                Tok::Guid => {}
                Tok::Str(s) => node.values.push(Value::Str(s.clone())),
                Tok::Open => {
                    let Some(Tok::Word(r)) = self.peek(0) else {
                        return Err(Error::Syntax("empty reference"));
                    };
                    let r = r.clone();
                    self.pos += 1;
                    if matches!(self.peek(0), Some(Tok::Guid)) {
                        self.pos += 1;
                    }
                    match self.toks.get(self.pos) {
                        Some(Tok::Close) => self.pos += 1,
                        _ => return Err(Error::Syntax("reference without '}'")),
                    }
                    node.children.push(Child::Ref(r));
                }
                Tok::Word(w) => {
                    if let Some(v) = number(w) {
                        node.values.push(v);
                    } else {
                        let kind = w.clone();
                        let child = self.node(kind, depth + 1)?;
                        node.children.push(Child::Node(child));
                    }
                }
            }
        }
    }
}

fn parse_text(body: &[u8]) -> Result<Vec<Node>, Error> {
    let mut p = TextParser {
        toks: tokenize(body)?,
        pos: 0,
    };
    let mut nodes = Vec::new();
    while let Some(tok) = p.toks.get(p.pos) {
        p.pos += 1;
        match tok {
            Tok::Word(w) if w == "template" => p.skip_template()?,
            Tok::Word(w) => {
                let kind = w.clone();
                nodes.push(p.node(kind, 0)?);
            }
            _ => return Err(Error::Syntax("expected an object at top level")),
        }
    }
    Ok(nodes)
}

// ---------------------------------------------------------------------------
// Binary
// ---------------------------------------------------------------------------

const T_NAME: u16 = 1;
const T_STRING: u16 = 2;
const T_INTEGER: u16 = 3;
const T_GUID: u16 = 5;
const T_INT_LIST: u16 = 6;
const T_FLOAT_LIST: u16 = 7;
const T_OBRACE: u16 = 10;
const T_CBRACE: u16 = 11;
const T_COMMA: u16 = 19;
const T_SEMICOLON: u16 = 20;
const T_TEMPLATE: u16 = 31;

struct BinParser<'a> {
    d: &'a [u8],
    pos: usize,
    wide_floats: bool,
}

impl BinParser<'_> {
    fn take(&mut self, n: usize) -> Result<&[u8], Error> {
        let end = self.pos.checked_add(n).filter(|&e| e <= self.d.len());
        let end = end.ok_or(Error::Syntax("binary .x ends inside a token"))?;
        let s = &self.d[self.pos..end];
        self.pos = end;
        Ok(s)
    }
    fn u16(&mut self) -> Result<u16, Error> {
        Ok(u16::from_le_bytes(self.take(2)?.try_into().unwrap()))
    }
    fn u32(&mut self) -> Result<u32, Error> {
        Ok(u32::from_le_bytes(self.take(4)?.try_into().unwrap()))
    }
    fn peek_token(&self) -> Option<u16> {
        self.d
            .get(self.pos..self.pos + 2)
            .map(|b| u16::from_le_bytes([b[0], b[1]]))
    }
    fn name(&mut self) -> Result<String, Error> {
        let n = self.u32()? as usize;
        Ok(String::from_utf8_lossy(self.take(n)?).into_owned())
    }

    fn skip_template(&mut self) -> Result<(), Error> {
        // Template bodies hold type names, arrays and brackets; only the braces matter.
        let mut depth = 0usize;
        loop {
            match self.u16()? {
                T_NAME => {
                    self.name()?;
                }
                T_GUID => {
                    self.take(16)?;
                }
                T_OBRACE => depth += 1,
                T_CBRACE => {
                    depth = depth
                        .checked_sub(1)
                        .ok_or(Error::Syntax("unbalanced template"))?;
                    if depth == 0 {
                        return Ok(());
                    }
                }
                T_INTEGER => {
                    self.u32()?;
                }
                _ => {}
            }
        }
    }

    /// After the type NAME token.
    fn node(&mut self, kind: String, depth: usize) -> Result<Node, Error> {
        if depth > MAX_DEPTH {
            return Err(Error::Syntax("objects nested too deep"));
        }
        let mut name = None;
        let mut t = self.u16()?;
        if t == T_NAME {
            name = Some(self.name()?);
            t = self.u16()?;
        }
        if t != T_OBRACE {
            return Err(Error::Syntax("expected '{' after object type"));
        }
        let mut node = Node {
            kind,
            name,
            values: Vec::new(),
            children: Vec::new(),
        };
        loop {
            match self.u16()? {
                T_CBRACE => return Ok(node),
                T_GUID => {
                    self.take(16)?;
                }
                T_COMMA | T_SEMICOLON => {}
                T_INTEGER => node.values.push(Value::Int(i64::from(self.u32()?))),
                T_STRING => {
                    let n = self.u32()? as usize;
                    node.values.push(Value::Str(self.take(n)?.to_vec()));
                    self.u16()?;
                }
                T_INT_LIST => {
                    let n = self.u32()? as usize;
                    for _ in 0..n {
                        node.values.push(Value::Int(i64::from(self.u32()?)));
                    }
                }
                T_FLOAT_LIST => {
                    let n = self.u32()? as usize;
                    for _ in 0..n {
                        let v = if self.wide_floats {
                            f64::from_le_bytes(self.take(8)?.try_into().unwrap()) as f32
                        } else {
                            f32::from_le_bytes(self.take(4)?.try_into().unwrap())
                        };
                        node.values.push(Value::Float(v));
                    }
                }
                T_NAME => {
                    let kind = self.name()?;
                    node.children.push(Child::Node(self.node(kind, depth + 1)?));
                }
                T_OBRACE => {
                    if self.u16()? != T_NAME {
                        return Err(Error::Syntax("empty reference"));
                    }
                    let r = self.name()?;
                    if self.peek_token() == Some(T_GUID) {
                        self.u16()?;
                        self.take(16)?;
                    }
                    if self.u16()? != T_CBRACE {
                        return Err(Error::Syntax("reference without '}'"));
                    }
                    node.children.push(Child::Ref(r));
                }
                _ => return Err(Error::Syntax("unexpected token in binary .x")),
            }
        }
    }
}

fn parse_binary(body: &[u8], wide_floats: bool) -> Result<Vec<Node>, Error> {
    let mut p = BinParser {
        d: body,
        pos: 0,
        wide_floats,
    };
    let mut nodes = Vec::new();
    while p.pos < body.len() {
        match p.u16()? {
            T_TEMPLATE => p.skip_template()?,
            T_NAME => {
                let kind = p.name()?;
                nodes.push(p.node(kind, 0)?);
            }
            _ => return Err(Error::Syntax("expected an object at top level")),
        }
    }
    Ok(nodes)
}
