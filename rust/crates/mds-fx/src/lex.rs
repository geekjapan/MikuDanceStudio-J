//! Lexer for preprocessed effect text.
//!
//! [`scan`] is the single token scanner. The preprocessor uses it for macro tokens and
//! [`lex`] uses it for the parser. [`lex`] joins adjacent string literals into one token,
//! because MME `Script` annotations are written as `"a;" "b;"`.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Ident,
    Number,
    /// A complete string literal.
    Str,
    Punct,
    /// An unterminated string or a character no HLSL token starts with.
    Unknown,
}

const PUNCT3: [&str; 3] = ["<<=", ">>=", "..."];
const PUNCT2: [&str; 21] = [
    "##", "==", "!=", "<=", ">=", "&&", "||", "<<", ">>", "++", "--", "+=", "-=", "*=", "/=", "%=",
    "&=", "|=", "^=", "::", "->",
];

fn is_ident_start(c: u8) -> bool {
    c.is_ascii_alphabetic() || c == b'_'
}

fn is_ident_char(c: u8) -> bool {
    c.is_ascii_alphanumeric() || c == b'_'
}

/// Scans one token that starts at byte `i`. `src[i]` must not be whitespace and `i` must
/// lie on a char boundary. Returns the token kind and its end offset (always `> i`).
pub fn scan(src: &str, i: usize) -> (Kind, usize) {
    let b = src.as_bytes();
    let len = b.len();
    let c = b[i];
    if is_ident_start(c) {
        let mut j = i + 1;
        while j < len && is_ident_char(b[j]) {
            j += 1;
        }
        return (Kind::Ident, j);
    }
    if c.is_ascii_digit() || (c == b'.' && i + 1 < len && b[i + 1].is_ascii_digit()) {
        let mut j = i + 1;
        while j < len {
            let d = b[j];
            let exp_sign = (d == b'+' || d == b'-') && matches!(b[j - 1], b'e' | b'E' | b'p' | b'P');
            if is_ident_char(d) || d == b'.' || exp_sign {
                j += 1;
            } else {
                break;
            }
        }
        return (Kind::Number, j);
    }
    if c == b'"' {
        let mut j = i + 1;
        while j < len {
            match b[j] {
                b'\\' => j += 2,
                b'"' => return (Kind::Str, j + 1),
                b'\n' => return (Kind::Unknown, j),
                _ => j += 1,
            }
        }
        return (Kind::Unknown, len);
    }
    if let Some(rest) = src.get(i..) {
        for p in PUNCT3 {
            if rest.starts_with(p) {
                return (Kind::Punct, i + 3);
            }
        }
        for p in PUNCT2 {
            if rest.starts_with(p) {
                return (Kind::Punct, i + 2);
            }
        }
    }
    if b"{}[]()<>;:,.=+-*/%&|^!~?#".contains(&c) {
        return (Kind::Punct, i + 1);
    }
    let n = src[i..].chars().next().map_or(1, char::len_utf8);
    (Kind::Unknown, i + n)
}

/// Resolves the escapes of a string literal body (the text between the quotes).
pub fn unescape(body: &str) -> String {
    let mut out = String::with_capacity(body.len());
    let mut it = body.chars();
    while let Some(c) = it.next() {
        if c != '\\' {
            out.push(c);
            continue;
        }
        match it.next() {
            Some('n') => out.push('\n'),
            Some('t') => out.push('\t'),
            Some('r') => out.push('\r'),
            Some('0') => out.push('\0'),
            Some(e @ ('\\' | '"' | '\'')) => out.push(e),
            Some(other) => {
                out.push('\\');
                out.push(other);
            }
            None => out.push('\\'),
        }
    }
    out
}

#[derive(Clone, Debug)]
pub struct Token {
    pub kind: Kind,
    /// Byte range in the lexed text. For a joined string it covers every piece.
    pub start: usize,
    pub end: usize,
    /// 1-based line of `start`.
    pub line: u32,
    /// For `Kind::Str`: the unescaped contents, all joined pieces together.
    pub value: String,
    /// For a joined `Kind::Str`: the raw source text of the single joined literal.
    pub raw: Option<String>,
    /// Newlines that sat between the joined pieces.
    pub gap_newlines: u32,
}

impl Token {
    pub fn text<'a>(&'a self, src: &'a str) -> &'a str {
        match &self.raw {
            Some(r) => r,
            None => src.get(self.start..self.end).unwrap_or(""),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LexError {
    pub line: u32,
    pub message: String,
}

/// Lexes `src`. Comments are skipped, adjacent string literals are joined.
pub fn lex(src: &str) -> Result<Vec<Token>, LexError> {
    let b = src.as_bytes();
    let len = b.len();
    let mut toks = Vec::with_capacity(len / 5);
    let mut i = 0;
    let mut line = 1u32;
    while i < len {
        let c = b[i];
        if c == b'\n' {
            line += 1;
            i += 1;
            continue;
        }
        if c.is_ascii_whitespace() {
            i += 1;
            continue;
        }
        if c == b'/' && i + 1 < len && b[i + 1] == b'/' {
            while i < len && b[i] != b'\n' {
                i += 1;
            }
            continue;
        }
        if c == b'/' && i + 1 < len && b[i + 1] == b'*' {
            let start_line = line;
            i += 2;
            loop {
                if i + 1 >= len {
                    return Err(LexError { line: start_line, message: "unterminated comment".into() });
                }
                if b[i] == b'*' && b[i + 1] == b'/' {
                    i += 2;
                    break;
                }
                if b[i] == b'\n' {
                    line += 1;
                }
                i += 1;
            }
            continue;
        }
        let (kind, end) = scan(src, i);
        match kind {
            Kind::Unknown => {
                let msg = if c == b'"' {
                    "unterminated string literal".to_string()
                } else {
                    format!("unexpected character {:?}", src[i..].chars().next().unwrap_or('?'))
                };
                return Err(LexError { line, message: msg });
            }
            Kind::Str => {
                let mut tok = Token {
                    kind,
                    start: i,
                    end,
                    line,
                    value: unescape(&src[i + 1..end - 1]),
                    raw: None,
                    gap_newlines: 0,
                };
                let tok_line = line;
                line += src[i..end].matches('\n').count() as u32;
                // Join adjacent literals separated only by whitespace.
                loop {
                    let mut j = tok.end;
                    let mut nl = 0;
                    while j < len && b[j].is_ascii_whitespace() {
                        if b[j] == b'\n' {
                            nl += 1;
                        }
                        j += 1;
                    }
                    if j >= len || b[j] != b'"' {
                        break;
                    }
                    let (k2, e2) = scan(src, j);
                    if k2 != Kind::Str {
                        break;
                    }
                    if tok.raw.is_none() {
                        tok.raw = Some(src[tok.start..tok.end - 1].to_string());
                    }
                    if let Some(raw) = tok.raw.as_mut() {
                        raw.push_str(&src[j + 1..e2 - 1]);
                    }
                    tok.value.push_str(&unescape(&src[j + 1..e2 - 1]));
                    tok.gap_newlines += nl;
                    line += nl + src[j..e2].matches('\n').count() as u32;
                    tok.end = e2;
                }
                if let Some(r) = tok.raw.as_mut() {
                    r.push('"');
                }
                tok.line = tok_line;
                i = tok.end;
                toks.push(tok);
            }
            _ => {
                toks.push(Token { kind, start: i, end, line, value: String::new(), raw: None, gap_newlines: 0 });
                line += src[i..end].matches('\n').count() as u32;
                i = end;
            }
        }
    }
    Ok(toks)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn joins_adjacent_strings() {
        let src = "string S = \"a;\"\n  \"b;\" \"c\";";
        let t = lex(src).unwrap();
        let s = t.iter().find(|t| t.kind == Kind::Str).unwrap();
        assert_eq!(s.value, "a;b;c");
        assert_eq!(s.text(src), "\"a;b;c\"");
        assert_eq!(s.gap_newlines, 1);
        // the `;` after the strings is on line 2 and keeps its line number
        assert_eq!(t.last().unwrap().line, 2);
    }

    #[test]
    fn keeps_escapes_raw_when_joining() {
        let src = r#"x = "a\"" "b";"#;
        let t = lex(src).unwrap();
        let s = t.iter().find(|t| t.kind == Kind::Str).unwrap();
        assert_eq!(s.value, "a\"b");
        assert_eq!(s.text(src), r#""a\"b""#);
    }

    #[test]
    fn numbers_and_punct() {
        let src = "a = -1.5e-3f + .5 << 2 >= 0x1F;";
        let kinds: Vec<_> = lex(src).unwrap().iter().map(|t| t.text(src).to_string()).collect();
        assert_eq!(kinds, ["a", "=", "-", "1.5e-3f", "+", ".5", "<<", "2", ">=", "0x1F", ";"]);
    }

    #[test]
    fn bad_input_is_an_error() {
        assert!(lex("float a = @;").is_err());
        assert!(lex("string s = \"abc").is_err());
        assert!(lex("/* open").is_err());
        assert!(lex("日本語").is_err());
    }
}
