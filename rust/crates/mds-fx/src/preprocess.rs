//! C-style preprocessor for effect files, with the MME include rules.
//!
//! It handles `#include`, `#define` (object and function-like, with `#` and `##`),
//! `#undef`, `#if`/`#ifdef`/`#ifndef`/`#elif`/`#else`/`#endif`, `#error`, and ignores
//! `#pragma`, `#line`, and `#warning`. Comments are removed and line continuations are
//! joined. The output has one line per source line, and a map from every output line back
//! to its file and line.
//!
//! Include rules (from the P2 prototype, `corpus.py`): a path resolves against the directory of
//! the top-level `.fx` file first and the directory of the including file second. Path parts
//! match without case, and `\` counts as `/`.

use std::borrow::Cow;
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::rc::Rc;

use crate::error::FxError;
use crate::lex::{scan, Kind};

const MAX_INCLUDE_DEPTH: usize = 64;
const MAX_EXPAND_DEPTH: usize = 128;
/// Token budget for all macro expansion in one effect. Stops exponential macros.
const EXPAND_BUDGET: usize = 8_000_000;

/// Preprocessor options.
///
/// The default mirrors `third_party/mmeffect/src/mmeffect/effect_engine.cpp`
/// (`D3DXCreateEffectFromFileW` call): `_INDEX` is `PSIZE15`, and `MME_MIPMAP` is defined
/// (empty) when the engine's mip-filter latch is set.
#[derive(Clone, Debug)]
pub struct Options {
    /// Define `MME_MIPMAP`.
    pub mip_filter: bool,
    /// Extra `(name, value)` object macros.
    pub defines: Vec<(String, String)>,
    /// Also resolve `#include "..."` lines in skipped `#if` regions, and the includes of
    /// those files. The P2 prototype expanded includes as text before it evaluated any
    /// `#if`, so a dangling include in a disabled branch was an error there. D3DX does not
    /// look at disabled branches, so this is off by default and a corpus check turns it on.
    pub strict_includes: bool,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            mip_filter: true,
            defines: Vec::new(),
            strict_includes: false,
        }
    }
}

/// A line of an original source file. `file` indexes [`Preprocessed::files`].
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Origin {
    pub file: u32,
    pub line: u32,
}

/// Which directory an include resolved against.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Via {
    TopLevelDir,
    IncludingDir,
}

/// One resolved `#include`, in the order the preprocessor met it.
#[derive(Clone, Debug)]
pub struct Include {
    pub from: Origin,
    /// The file that holds the `#include` line.
    pub from_path: PathBuf,
    pub name: String,
    pub resolved: PathBuf,
    pub via: Via,
}

#[derive(Clone, Debug)]
pub struct Preprocessed {
    /// Preprocessed text. Line `n` (1-based) came from `origins[n - 1]`.
    pub text: String,
    pub origins: Vec<Origin>,
    /// Every file that contributed. Index 0 is the top-level file.
    pub files: Vec<PathBuf>,
    pub includes: Vec<Include>,
}

impl Preprocessed {
    /// Maps a 1-based line of [`Self::text`] to its file and line.
    pub fn origin(&self, line: u32) -> Option<(&Path, u32)> {
        let o = self.origins.get((line as usize).checked_sub(1)?)?;
        Some((self.files.get(o.file as usize)?, o.line))
    }

    /// Builds an error that names the original file and line of `line` in [`Self::text`].
    pub fn error(&self, line: u32, message: impl Into<String>) -> FxError {
        match self.origin(line) {
            Some((p, l)) => FxError::new(p, l, message),
            None => FxError::new(self.files.first().cloned().unwrap_or_default(), 0, message),
        }
    }
}

/// Decodes source bytes: UTF-8 (with or without BOM) when valid, otherwise Shift-JIS (cp932).
pub fn decode(bytes: &[u8]) -> Cow<'_, str> {
    let bytes = bytes.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(bytes);
    match std::str::from_utf8(bytes) {
        Ok(s) => Cow::Borrowed(s),
        Err(_) => encoding_rs::SHIFT_JIS.decode_without_bom_handling(bytes).0,
    }
}

/// Resolves `rel` below `base`. Parts match without case, `\` counts as `/`. An exact-case
/// entry wins over a case-folded one, so the result does not depend on the file system.
pub fn resolve_ci(base: &Path, rel: &str) -> Option<PathBuf> {
    let mut cur = if base.as_os_str().is_empty() {
        PathBuf::from(".")
    } else {
        base.to_path_buf()
    };
    for part in rel.replace('\\', "/").split('/') {
        match part {
            "" | "." => {}
            ".." => cur.push(".."),
            p => {
                let want = p.to_lowercase();
                let mut folded: Option<std::ffi::OsString> = None;
                let mut exact = None;
                for e in fs::read_dir(&cur).ok()? {
                    let name = e.ok()?.file_name();
                    let s = name.to_string_lossy();
                    if s == p {
                        exact = Some(name.clone());
                        break;
                    }
                    if s.to_lowercase() == want && folded.as_ref().map_or(true, |f| name < *f) {
                        folded = Some(name.clone());
                    }
                }
                cur.push(exact.or(folded)?);
            }
        }
    }
    cur.is_file().then_some(cur)
}

/// Preprocesses the file at `path`.
pub fn preprocess_file(path: &Path, opts: &Options) -> Result<Preprocessed, FxError> {
    let bytes =
        fs::read(path).map_err(|e| FxError::new(path, 0, format!("cannot read file: {e}")))?;
    preprocess_bytes(path, &bytes, opts)
}

/// Preprocesses `bytes` as if they were the file at `path`. Includes still read from disk,
/// relative to `path`.
pub fn preprocess_bytes(
    path: &Path,
    bytes: &[u8],
    opts: &Options,
) -> Result<Preprocessed, FxError> {
    let (r, pp) = run(path, bytes, opts);
    r?;
    Ok(Preprocessed {
        text: pp.out,
        origins: pp.origins,
        files: pp.files,
        includes: pp.includes,
    })
}

/// The includes that [`preprocess_bytes`] resolved before it finished or failed. For a file
/// that fails on a missing include, this lists what resolved first.
pub fn resolved_includes(path: &Path, bytes: &[u8], opts: &Options) -> Vec<Include> {
    run(path, bytes, opts).1.includes
}

fn run(path: &Path, bytes: &[u8], opts: &Options) -> (Result<(), FxError>, Pp) {
    let root = path.parent().map(Path::to_path_buf).unwrap_or_default();
    let mut pp = Pp {
        root: root.clone(),
        macros: HashMap::new(),
        out: String::with_capacity(bytes.len() * 2),
        origins: Vec::new(),
        files: Vec::new(),
        file_ids: HashMap::new(),
        includes: Vec::new(),
        cache: HashMap::new(),
        budget: EXPAND_BUDGET,
        strict: opts.strict_includes,
        stack: vec![path.to_path_buf()],
    };
    pp.define_object("_INDEX", "PSIZE15");
    if opts.mip_filter {
        pp.define_object("MME_MIPMAP", "");
    }
    for (n, v) in &opts.defines {
        pp.define_object(n, v);
    }
    let id = pp.file_id(path);
    let r = pp
        .process(id, &decode(bytes), &root, 0, Term::None)
        .map(|_| ());
    (r, pp)
}

// ---------------------------------------------------------------------------------------
// Logical lines: line splicing and comment removal.

/// How a physical line ended in its source file.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Term {
    Lf,
    CrLf,
    /// The last line of a file that has no final newline.
    None,
}

impl Term {
    fn as_str(self) -> &'static str {
        match self {
            Term::Lf => "\n",
            Term::CrLf => "\r\n",
            Term::None => "",
        }
    }
}

struct Lines<'a> {
    src: &'a str,
    pos: usize,
    line: u32,
    in_block: bool,
    /// Terminators of the physical lines of the logical line that `next` returned last.
    terms: Vec<Term>,
}

impl<'a> Lines<'a> {
    fn new(src: &'a str) -> Self {
        Lines {
            src,
            pos: 0,
            line: 1,
            in_block: false,
            terms: Vec::new(),
        }
    }

    /// Reads one logical line into `buf` (comments replaced, continuations joined). Returns
    /// the first physical line number and the number of physical lines used.
    fn next(&mut self, buf: &mut String) -> Option<(u32, u32)> {
        if self.pos >= self.src.len() {
            return None;
        }
        buf.clear();
        self.terms.clear();
        let first = self.line;
        let mut n = 0u32;
        let mut line_comment = false;
        loop {
            let rest = &self.src[self.pos..];
            let (raw, adv) = match rest.find('\n') {
                Some(k) => (&rest[..k], k + 1),
                None => (rest, rest.len()),
            };
            self.pos += adv;
            self.line += 1;
            n += 1;
            let had_cr = raw.ends_with('\r');
            self.terms.push(if adv == raw.len() {
                Term::None
            } else if had_cr {
                Term::CrLf
            } else {
                Term::Lf
            });
            let raw = raw.strip_suffix('\r').unwrap_or(raw);
            let bytes = raw.as_bytes();
            let len = bytes.len();
            // inside a line comment that a backslash continued, the whole line is comment
            let mut copy_from = if line_comment { len } else { 0 };
            let mut i = copy_from;
            while i < len {
                if self.in_block {
                    match raw[i..].find("*/") {
                        Some(k) => {
                            i += k + 2;
                            self.in_block = false;
                            copy_from = i;
                        }
                        None => {
                            i = len;
                            copy_from = len;
                        }
                    }
                    continue;
                }
                match bytes[i] {
                    b'"' => {
                        let mut j = i + 1;
                        while j < len {
                            match bytes[j] {
                                b'\\' => j += 2,
                                b'"' => {
                                    j += 1;
                                    break;
                                }
                                _ => j += 1,
                            }
                        }
                        i = j.min(len);
                        while !raw.is_char_boundary(i) {
                            i += 1;
                        }
                    }
                    b'/' if bytes.get(i + 1) == Some(&b'/') => {
                        buf.push_str(&raw[copy_from..i]);
                        line_comment = true;
                        i = len;
                        copy_from = len;
                    }
                    b'/' if bytes.get(i + 1) == Some(&b'*') => {
                        buf.push_str(&raw[copy_from..i]);
                        buf.push(' ');
                        self.in_block = true;
                        i += 2;
                        copy_from = i;
                    }
                    _ => i += 1,
                }
            }
            if copy_from < len {
                buf.push_str(&raw[copy_from..]);
            }
            let spliced = raw.ends_with('\\');
            if spliced && !line_comment && !self.in_block && buf.ends_with('\\') {
                buf.pop();
            }
            if !(spliced || self.in_block) || self.pos >= self.src.len() {
                return Some((first, n));
            }
        }
    }
}

// ---------------------------------------------------------------------------------------
// Macro tokens.

#[derive(Clone, Debug)]
struct Tok {
    text: String,
    kind: Kind,
    /// Whitespace came before this token.
    ws: bool,
}

fn tokenize(s: &str) -> Vec<Tok> {
    let b = s.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    let mut ws = false;
    while i < b.len() {
        if b[i].is_ascii_whitespace() {
            ws = true;
            i += 1;
            continue;
        }
        let (kind, end) = scan(s, i);
        out.push(Tok {
            text: s[i..end].to_string(),
            kind,
            ws,
        });
        ws = false;
        i = end;
    }
    out
}

fn render(toks: &[Tok]) -> String {
    let mut s = String::new();
    for (i, t) in toks.iter().enumerate() {
        if i > 0 && t.ws {
            s.push(' ');
        }
        s.push_str(&t.text);
    }
    s
}

struct Macro {
    params: Option<Vec<String>>,
    body: Vec<Tok>,
}

struct Cond {
    parent_active: bool,
    taken: bool,
    active: bool,
    seen_else: bool,
    line: u32,
}

struct Pp {
    root: PathBuf,
    macros: HashMap<String, Rc<Macro>>,
    out: String,
    origins: Vec<Origin>,
    files: Vec<PathBuf>,
    file_ids: HashMap<PathBuf, u32>,
    includes: Vec<Include>,
    cache: HashMap<PathBuf, Rc<str>>,
    budget: usize,
    strict: bool,
    /// Files being read right now, innermost last. Stops cycles in strict include scanning.
    stack: Vec<PathBuf>,
}

fn is_ident_char(c: u8) -> bool {
    c.is_ascii_alphanumeric() || c == b'_'
}

impl Pp {
    fn define_object(&mut self, name: &str, value: &str) {
        let body = tokenize(value);
        self.macros
            .insert(name.to_string(), Rc::new(Macro { params: None, body }));
    }

    fn file_id(&mut self, path: &Path) -> u32 {
        if let Some(&id) = self.file_ids.get(path) {
            return id;
        }
        let id = self.files.len() as u32;
        self.files.push(path.to_path_buf());
        self.file_ids.insert(path.to_path_buf(), id);
        id
    }

    /// Appends one output line. A line that ended its file without a newline takes the
    /// terminator of the `#include` line that pulled the file in (`outer`), the way textual
    /// inclusion joins them.
    fn emit(&mut self, text: &str, file: u32, line: u32, term: Term, outer: Term) {
        self.out.push_str(text);
        self.out
            .push_str(if term == Term::None { outer } else { term }.as_str());
        self.origins.push(Origin { file, line });
    }

    /// Blank output lines for source lines `first..` with the given terminators.
    fn blanks(&mut self, file: u32, first: u32, terms: &[Term], outer: Term) {
        for (k, t) in terms.iter().enumerate() {
            self.emit("", file, first + k as u32, *t, outer);
        }
    }

    /// Preprocesses one file into the output. Returns whether the file ended without a final
    /// newline, so that its last line took the terminator of the including line.
    fn process(
        &mut self,
        file: u32,
        text: &str,
        dir: &Path,
        depth: usize,
        outer: Term,
    ) -> Result<bool, FxError> {
        let path = self.files[file as usize].clone();
        let err = |line: u32, m: String| FxError::new(&path, line, m);
        let mut lines = Lines::new(text);
        let mut buf = String::new();
        let mut conds: Vec<Cond> = Vec::new();
        while let Some((first, _)) = lines.next(&mut buf) {
            let active = conds.last().map_or(true, |c| c.active);
            if let Some(rest) = buf.trim_start().strip_prefix('#') {
                let rest = rest.trim_start();
                let name_end = rest
                    .bytes()
                    .position(|c| !is_ident_char(c))
                    .unwrap_or(rest.len());
                let (name, args) = (&rest[..name_end], rest[name_end..].trim());
                match name {
                    "if" | "ifdef" | "ifndef" => {
                        let v = if !active {
                            false
                        } else if name == "if" {
                            self.eval_if(args).map_err(|m| err(first, m))?
                        } else {
                            self.macros
                                .contains_key(args.split_whitespace().next().unwrap_or(""))
                                == (name == "ifdef")
                        };
                        conds.push(Cond {
                            parent_active: active,
                            taken: v || !active,
                            active: v,
                            seen_else: false,
                            line: first,
                        });
                    }
                    "elif" => {
                        let (parent, taken, seen_else) = match conds.last() {
                            Some(c) => (c.parent_active, c.taken, c.seen_else),
                            None => return Err(err(first, "#elif without #if".into())),
                        };
                        if seen_else {
                            return Err(err(first, "#elif after #else".into()));
                        }
                        let v = if !parent || taken {
                            false
                        } else {
                            self.eval_if(args).map_err(|m| err(first, m))?
                        };
                        if let Some(c) = conds.last_mut() {
                            c.active = v;
                            c.taken |= v;
                        }
                    }
                    "else" => match conds.last_mut() {
                        Some(c) if !c.seen_else => {
                            c.active = c.parent_active && !c.taken;
                            c.taken = true;
                            c.seen_else = true;
                        }
                        Some(_) => return Err(err(first, "duplicate #else".into())),
                        None => return Err(err(first, "#else without #if".into())),
                    },
                    "endif" => {
                        if conds.pop().is_none() {
                            return Err(err(first, "#endif without #if".into()));
                        }
                    }
                    "include" if !active && self.strict => {
                        self.eager_include(args, file, first, dir, depth, &path)?
                    }
                    _ if !active => {}
                    "" | "pragma" | "line" | "warning" => {}
                    "define" => self.define(args).map_err(|m| err(first, m))?,
                    "undef" => {
                        self.macros
                            .remove(args.split_whitespace().next().unwrap_or(""));
                    }
                    "error" => return Err(err(first, format!("#error {args}"))),
                    "include" => {
                        let dterm = lines.terms.last().copied().unwrap_or(Term::Lf);
                        let eff = if dterm == Term::None { outer } else { dterm };
                        let unterminated =
                            self.include(args, file, first, dir, depth, &path, eff)?;
                        if !unterminated && eff != Term::None {
                            // the content ended with a newline, so the include line's own
                            // terminator makes one more blank line
                            self.emit("", file, first, eff, eff);
                        }
                        continue;
                    }
                    other => return Err(err(first, format!("unknown directive #{other}"))),
                }
                self.blanks(file, first, &lines.terms, outer);
            } else if !active {
                self.blanks(file, first, &lines.terms, outer);
            } else if !self.has_macro(&buf) {
                self.emit(&buf, file, first, lines.terms[0], outer);
                self.blanks(file, first + 1, &lines.terms[1..], outer);
            } else {
                let mut toks = tokenize(&buf);
                let mut terms = lines.terms.clone();
                let mut more = String::new();
                while self.needs_more(&toks) {
                    let Some(_) = lines.next(&mut more) else {
                        break;
                    };
                    let mut extra = tokenize(&more);
                    if let Some(f) = extra.first_mut() {
                        f.ws = true;
                    }
                    toks.extend(extra);
                    terms.extend_from_slice(&lines.terms);
                }
                let out = self
                    .expand(&toks, &mut Vec::new(), 0)
                    .map_err(|m| err(first, m))?;
                self.emit(&render(&out), file, first, terms[0], outer);
                self.blanks(file, first + 1, &terms[1..], outer);
            }
        }
        if let Some(c) = conds.last() {
            return Err(err(c.line, "unterminated #if".into()));
        }
        Ok(lines.terms.last() == Some(&Term::None))
    }

    /// True when the line mentions an identifier that is a macro. Conservative: strings and
    /// numbers can only cause a false positive, which costs time and not correctness.
    fn has_macro(&self, line: &str) -> bool {
        if self.macros.is_empty() {
            return false;
        }
        let b = line.as_bytes();
        let mut i = 0;
        while i < b.len() {
            if is_ident_char(b[i]) {
                let mut j = i + 1;
                while j < b.len() && is_ident_char(b[j]) {
                    j += 1;
                }
                if !b[i].is_ascii_digit() && self.macros.contains_key(&line[i..j]) {
                    return true;
                }
                i = j;
            } else {
                i += 1;
            }
        }
        false
    }

    /// True when a function-like macro call opens a parenthesis that the line does not close.
    fn needs_more(&self, toks: &[Tok]) -> bool {
        let mut i = 0;
        while i < toks.len() {
            let is_call = toks[i].kind == Kind::Ident
                && self
                    .macros
                    .get(&toks[i].text)
                    .is_some_and(|m| m.params.is_some())
                && toks.get(i + 1).is_some_and(|t| t.text == "(");
            if is_call {
                let mut depth = 1;
                let mut j = i + 2;
                while j < toks.len() && depth > 0 {
                    match toks[j].text.as_str() {
                        "(" => depth += 1,
                        ")" => depth -= 1,
                        _ => {}
                    }
                    j += 1;
                }
                if depth > 0 {
                    return true;
                }
                i = j;
            } else {
                i += 1;
            }
        }
        false
    }

    fn define(&mut self, args: &str) -> Result<(), String> {
        let (kind, name_end) = if args.is_empty() {
            (Kind::Unknown, 0)
        } else {
            scan(args, 0)
        };
        if kind != Kind::Ident {
            return Err("#define needs a macro name".into());
        }
        let name = args[..name_end].to_string();
        let rest = &args[name_end..];
        let m = if let Some(inner) = rest.strip_prefix('(') {
            let close = inner
                .find(')')
                .ok_or("#define: missing ')' in parameter list")?;
            let mut params = Vec::new();
            for p in inner[..close].split(',') {
                let p = p.trim();
                if p.is_empty() && close == 0 {
                    continue;
                }
                if p.is_empty() || scan(p, 0) != (Kind::Ident, p.len()) {
                    return Err(format!("#define {name}: unsupported parameter {p:?}"));
                }
                params.push(p.to_string());
            }
            let mut body = tokenize(&inner[close + 1..]);
            if let Some(f) = body.first_mut() {
                f.ws = false;
            }
            Macro {
                params: Some(params),
                body,
            }
        } else {
            let mut body = tokenize(rest);
            if let Some(f) = body.first_mut() {
                f.ws = false;
            }
            Macro { params: None, body }
        };
        self.macros.insert(name, Rc::new(m));
        Ok(())
    }

    fn spend(&mut self, n: usize) -> Result<(), String> {
        self.budget = self
            .budget
            .checked_sub(n)
            .ok_or("macro expansion is too large")?;
        Ok(())
    }

    fn expand(
        &mut self,
        input: &[Tok],
        hide: &mut Vec<String>,
        depth: usize,
    ) -> Result<Vec<Tok>, String> {
        if depth > MAX_EXPAND_DEPTH {
            return Err("macro expansion nests too deeply".into());
        }
        let mut out: Vec<Tok> = Vec::with_capacity(input.len());
        let mut i = 0;
        while i < input.len() {
            let t = &input[i];
            let mac = if t.kind == Kind::Ident && !hide.contains(&t.text) {
                self.macros.get(&t.text).cloned()
            } else {
                None
            };
            let Some(m) = mac else {
                out.push(t.clone());
                i += 1;
                continue;
            };
            self.spend(1)?;
            let Some(params) = &m.params else {
                let mut body = m.body.clone();
                if let Some(f) = body.first_mut() {
                    f.ws = t.ws;
                }
                hide.push(t.text.clone());
                let ex = self.expand(&body, hide, depth + 1);
                hide.pop();
                let ex = ex?;
                self.spend(ex.len())?;
                out.extend(ex);
                i += 1;
                continue;
            };
            let call = if input.get(i + 1).is_some_and(|n| n.text == "(") {
                collect_args(input, i + 2)
            } else {
                None
            };
            let Some((mut args, end)) = call else {
                out.push(t.clone());
                i += 1;
                continue;
            };
            if params.is_empty() && args.len() == 1 && args[0].is_empty() {
                args.clear();
            }
            if args.len() != params.len() {
                return Err(format!(
                    "macro {} expects {} arguments, got {}",
                    t.text,
                    params.len(),
                    args.len()
                ));
            }
            let mut expanded = Vec::with_capacity(args.len());
            for a in &args {
                expanded.push(self.expand(a, hide, depth + 1)?);
            }
            let res = substitute(&m, params, &args, &expanded);
            self.spend(res.len())?;
            hide.push(t.text.clone());
            let ex = self.expand(&res, hide, depth + 1);
            hide.pop();
            let mut ex = ex?;
            if let Some(f) = ex.first_mut() {
                f.ws = t.ws;
            }
            out.extend(ex);
            i = end;
        }
        Ok(out)
    }

    fn eval_if(&mut self, expr: &str) -> Result<bool, String> {
        let toks = tokenize(expr);
        let mut pre: Vec<Tok> = Vec::with_capacity(toks.len());
        let mut i = 0;
        while i < toks.len() {
            if toks[i].kind == Kind::Ident && toks[i].text == "defined" {
                let paren = toks.get(i + 1).is_some_and(|t| t.text == "(");
                let name = toks.get(i + if paren { 2 } else { 1 });
                let Some(name) = name.filter(|n| n.kind == Kind::Ident) else {
                    return Err("'defined' needs a macro name".into());
                };
                if paren && toks.get(i + 3).map(|t| t.text.as_str()) != Some(")") {
                    return Err("'defined(' is missing ')'".into());
                }
                let v = self.macros.contains_key(&name.text);
                pre.push(Tok {
                    text: if v { "1" } else { "0" }.into(),
                    kind: Kind::Number,
                    ws: true,
                });
                i += if paren { 4 } else { 2 };
            } else {
                pre.push(toks[i].clone());
                i += 1;
            }
        }
        let ex = self.expand(&pre, &mut Vec::new(), 0)?;
        let mut ev = Eval {
            t: &ex,
            pos: 0,
            depth: 0,
        };
        let v = ev.ternary()?;
        if ev.pos != ex.len() {
            return Err(format!(
                "unexpected {:?} in #if expression",
                ex[ev.pos].text
            ));
        }
        Ok(v != 0)
    }

    /// Resolves an include name: top-level directory first, including file's directory second.
    fn resolve(&self, name: &str, dir: &Path) -> Option<(PathBuf, Via)> {
        resolve_ci(&self.root, name)
            .map(|p| (p, Via::TopLevelDir))
            .or_else(|| resolve_ci(dir, name).map(|p| (p, Via::IncludingDir)))
    }

    fn load(&mut self, resolved: &Path) -> std::io::Result<Rc<str>> {
        if let Some(t) = self.cache.get(resolved) {
            return Ok(t.clone());
        }
        let bytes = fs::read(resolved)?;
        let t: Rc<str> = Rc::from(decode(&bytes).as_ref());
        self.cache.insert(resolved.to_path_buf(), t.clone());
        Ok(t)
    }

    fn include(
        &mut self,
        args: &str,
        file: u32,
        line: u32,
        dir: &Path,
        depth: usize,
        path: &Path,
        outer: Term,
    ) -> Result<bool, FxError> {
        let err = |m: String| FxError::new(path, line, m);
        let mut spec = args.to_string();
        if !spec.starts_with('"') && !spec.starts_with('<') {
            let ex = self
                .expand(&tokenize(args), &mut Vec::new(), 0)
                .map_err(&err)?;
            spec = render(&ex);
        }
        let close = match spec.chars().next() {
            Some('"') => '"',
            Some('<') => '>',
            _ => return Err(err("#include expects \"file\" or <file>".into())),
        };
        let name = match spec[1..].find(close) {
            Some(k) => spec[1..1 + k].to_string(),
            None => return Err(err("#include is missing its closing quote".into())),
        };
        if depth + 1 > MAX_INCLUDE_DEPTH {
            return Err(err(format!("include \"{name}\" nests too deeply")));
        }
        let Some((resolved, via)) = self.resolve(&name, dir) else {
            return Err(err(format!("include \"{name}\" not found")));
        };
        let text = self
            .load(&resolved)
            .map_err(|e| err(format!("cannot read include \"{name}\": {e}")))?;
        self.includes.push(Include {
            from: Origin { file, line },
            from_path: self.files[file as usize].clone(),
            name,
            resolved: resolved.clone(),
            via,
        });
        let id = self.file_id(&resolved);
        let sub_dir = resolved.parent().map(Path::to_path_buf).unwrap_or_default();
        self.stack.push(resolved);
        let r = self.process(id, &text, &sub_dir, depth + 1, outer);
        self.stack.pop();
        r
    }

    /// Strict mode: resolves an include that sits in a skipped region, then every include of
    /// that file, whatever the conditionals say. Nothing is added to the output.
    fn eager_include(
        &mut self,
        args: &str,
        file: u32,
        line: u32,
        dir: &Path,
        depth: usize,
        path: &Path,
    ) -> Result<(), FxError> {
        let err = |m: String| FxError::new(path, line, m);
        let Some(name) = args.strip_prefix('"').and_then(|r| r.split('"').next()) else {
            return Ok(());
        };
        let name = name.to_string();
        if depth + 1 > MAX_INCLUDE_DEPTH {
            return Err(err(format!("include \"{name}\" nests too deeply")));
        }
        let Some((resolved, via)) = self.resolve(&name, dir) else {
            return Err(err(format!("include \"{name}\" not found")));
        };
        self.includes.push(Include {
            from: Origin { file, line },
            from_path: self.files[file as usize].clone(),
            name: name.clone(),
            resolved: resolved.clone(),
            via,
        });
        if self.stack.contains(&resolved) {
            return Ok(());
        }
        let text = self
            .load(&resolved)
            .map_err(|e| err(format!("cannot read include \"{name}\": {e}")))?;
        let id = self.file_id(&resolved);
        let sub_dir = resolved.parent().map(Path::to_path_buf).unwrap_or_default();
        self.stack.push(resolved.clone());
        let r = self.eager_scan(id, &text, &sub_dir, depth + 1, &resolved);
        self.stack.pop();
        r
    }

    fn eager_scan(
        &mut self,
        file: u32,
        text: &str,
        dir: &Path,
        depth: usize,
        path: &Path,
    ) -> Result<(), FxError> {
        let mut lines = Lines::new(text);
        let mut buf = String::new();
        while let Some((first, _)) = lines.next(&mut buf) {
            let Some(rest) = buf.trim_start().strip_prefix('#') else {
                continue;
            };
            let Some(args) = rest.trim_start().strip_prefix("include") else {
                continue;
            };
            if args.starts_with(|c: char| c.is_ascii_alphanumeric() || c == '_') {
                continue;
            }
            self.eager_include(args.trim(), file, first, dir, depth, path)?;
        }
        Ok(())
    }
}

/// Splits call arguments starting at `start` (just after the `(`). Returns the arguments and
/// the index after the closing `)`, or `None` when the call is not closed.
fn collect_args(input: &[Tok], start: usize) -> Option<(Vec<Vec<Tok>>, usize)> {
    let mut args = Vec::new();
    let mut cur: Vec<Tok> = Vec::new();
    let mut depth = 0;
    for (j, t) in input.iter().enumerate().skip(start) {
        match t.text.as_str() {
            "(" => depth += 1,
            ")" if depth == 0 => {
                args.push(cur);
                return Some((args, j + 1));
            }
            ")" => depth -= 1,
            "," if depth == 0 => {
                args.push(std::mem::take(&mut cur));
                continue;
            }
            _ => {}
        }
        cur.push(t.clone());
    }
    None
}

fn substitute(m: &Macro, params: &[String], raw: &[Vec<Tok>], expanded: &[Vec<Tok>]) -> Vec<Tok> {
    let param = |t: &Tok| {
        if t.kind == Kind::Ident {
            params.iter().position(|p| *p == t.text)
        } else {
            None
        }
    };
    let is_paste = |t: Option<&Tok>| t.is_some_and(|t| t.text == "##");
    let mut res: Vec<Tok> = Vec::new();
    let mut paste = false;
    let mut k = 0;
    while k < m.body.len() {
        let b = &m.body[k];
        if b.text == "##" {
            paste = true;
            k += 1;
            continue;
        }
        if b.text == "#" {
            if let Some(pi) = m.body.get(k + 1).and_then(param) {
                let s = render(&raw[pi]).replace('\\', "\\\\").replace('"', "\\\"");
                res.push(Tok {
                    text: format!("\"{s}\""),
                    kind: Kind::Str,
                    ws: b.ws,
                });
                k += 2;
                continue;
            }
        }
        let mut piece: Vec<Tok> = match param(b) {
            Some(pi) if paste || is_paste(m.body.get(k + 1)) => raw[pi].clone(),
            Some(pi) => expanded[pi].clone(),
            None => vec![b.clone()],
        };
        if let Some(f) = piece.first_mut() {
            f.ws = b.ws;
        }
        if paste {
            paste = false;
            if let (Some(last), Some(first)) = (res.last_mut(), piece.first()) {
                last.text.push_str(&first.text);
                last.kind = scan(&last.text, 0).0;
                res.extend(piece.into_iter().skip(1));
                k += 1;
                continue;
            }
        }
        res.extend(piece);
        k += 1;
    }
    res
}

// ---------------------------------------------------------------------------------------
// `#if` expressions.

struct Eval<'a> {
    t: &'a [Tok],
    pos: usize,
    depth: u32,
}

impl Eval<'_> {
    fn peek(&self) -> &str {
        self.t.get(self.pos).map_or("", |t| t.text.as_str())
    }

    fn ternary(&mut self) -> Result<i64, String> {
        let c = self.binary(1)?;
        if self.peek() != "?" {
            return Ok(c);
        }
        self.pos += 1;
        let a = self.ternary()?;
        if self.peek() != ":" {
            return Err("'?' without ':' in #if expression".into());
        }
        self.pos += 1;
        let b = self.ternary()?;
        Ok(if c != 0 { a } else { b })
    }

    fn binary(&mut self, min: u8) -> Result<i64, String> {
        let mut lhs = self.unary()?;
        loop {
            let op = self.peek();
            let prec = match op {
                "||" => 1,
                "&&" => 2,
                "|" => 3,
                "^" => 4,
                "&" => 5,
                "==" | "!=" => 6,
                "<" | ">" | "<=" | ">=" => 7,
                "<<" | ">>" => 8,
                "+" | "-" => 9,
                "*" | "/" | "%" => 10,
                _ => return Ok(lhs),
            };
            if prec < min {
                return Ok(lhs);
            }
            let op = op.to_string();
            self.pos += 1;
            let rhs = self.binary(prec + 1)?;
            lhs = match op.as_str() {
                "||" => (lhs != 0 || rhs != 0) as i64,
                "&&" => (lhs != 0 && rhs != 0) as i64,
                "|" => lhs | rhs,
                "^" => lhs ^ rhs,
                "&" => lhs & rhs,
                "==" => (lhs == rhs) as i64,
                "!=" => (lhs != rhs) as i64,
                "<" => (lhs < rhs) as i64,
                ">" => (lhs > rhs) as i64,
                "<=" => (lhs <= rhs) as i64,
                ">=" => (lhs >= rhs) as i64,
                "<<" => lhs.wrapping_shl((rhs & 63) as u32),
                ">>" => lhs.wrapping_shr((rhs & 63) as u32),
                "+" => lhs.wrapping_add(rhs),
                "-" => lhs.wrapping_sub(rhs),
                "*" => lhs.wrapping_mul(rhs),
                "/" => lhs
                    .checked_div(rhs)
                    .ok_or("division by zero in #if expression")?,
                _ => lhs
                    .checked_rem(rhs)
                    .ok_or("division by zero in #if expression")?,
            };
        }
    }

    fn unary(&mut self) -> Result<i64, String> {
        self.depth += 1;
        if self.depth > 64 {
            return Err("#if expression nests too deeply".into());
        }
        let r = self.unary_inner();
        self.depth -= 1;
        r
    }

    fn unary_inner(&mut self) -> Result<i64, String> {
        let Some(t) = self.t.get(self.pos) else {
            return Err("#if expression ends early".into());
        };
        self.pos += 1;
        match (t.kind, t.text.as_str()) {
            (_, "!") => Ok((self.unary()? == 0) as i64),
            (_, "~") => Ok(!self.unary()?),
            (_, "-") => Ok(self.unary()?.wrapping_neg()),
            (_, "+") => self.unary(),
            (_, "(") => {
                let v = self.ternary()?;
                if self.peek() != ")" {
                    return Err("missing ')' in #if expression".into());
                }
                self.pos += 1;
                Ok(v)
            }
            (Kind::Number, s) => parse_int(s),
            (Kind::Ident, _) => Ok(0),
            (_, s) => Err(format!("unexpected {s:?} in #if expression")),
        }
    }
}

fn parse_int(s: &str) -> Result<i64, String> {
    let t = s.trim_end_matches(|c: char| matches!(c, 'u' | 'U' | 'l' | 'L'));
    let bad = || format!("bad number {s:?} in #if expression");
    if let Some(h) = t.strip_prefix("0x").or_else(|| t.strip_prefix("0X")) {
        return i64::from_str_radix(h, 16)
            .or_else(|_| u64::from_str_radix(h, 16).map(|v| v as i64))
            .map_err(|_| bad());
    }
    if t.contains(['.', 'e', 'E']) || t.ends_with(['f', 'F']) {
        let f: f64 = t.trim_end_matches(['f', 'F']).parse().map_err(|_| bad())?;
        return Ok(f as i64);
    }
    if t.len() > 1 && t.starts_with('0') {
        if let Ok(v) = i64::from_str_radix(&t[1..], 8) {
            return Ok(v);
        }
    }
    t.parse::<i64>()
        .or_else(|_| t.parse::<u64>().map(|v| v as i64))
        .map_err(|_| bad())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::TempTree;

    fn pp(tree: &TempTree, top: &str) -> Result<Preprocessed, FxError> {
        preprocess_file(&tree.path(top), &Options::default())
    }

    fn text(src: &str) -> String {
        let t = TempTree::new();
        t.write("a.fx", src.as_bytes());
        pp(&t, "a.fx").unwrap().text
    }

    #[test]
    fn comments_and_continuations() {
        let out = text("a /* x\ny */ b // c \\\nd\n#define M 1 \\\n + 2\nM \"//not\"\n");
        let lines: Vec<_> = out.lines().collect();
        assert_eq!(lines[0].split_whitespace().collect::<Vec<_>>(), ["a", "b"]);
        assert!(
            lines.iter().any(|l| l.trim() == "1 + 2 \"//not\""),
            "{lines:?}"
        );
        // one output line per source line
        assert_eq!(lines.len(), 6);
    }

    #[test]
    fn conditionals_and_macros() {
        let out = text(
            "#define A 2\n#if A == 2 && defined(A) && !defined B\nyes\n#elif 1\nno1\n#else\nno2\n#endif\n\
             #ifdef MME_MIPMAP\nmip\n#endif\n#if _INDEX\nbad\n#endif\n#define F(x, y) (x + y)\nF(A, F(1, 2))\n",
        );
        let words: Vec<_> = out.split_whitespace().collect();
        assert_eq!(words, ["yes", "mip", "(2", "+", "(1", "+", "2))"]);
    }

    #[test]
    fn function_macro_call_across_lines() {
        let out = text("#define F(x, y) x * y\nF(1,\n  2) after\nnext\n");
        let lines: Vec<_> = out.lines().collect();
        assert_eq!(lines[1].trim(), "1 * 2 after");
        assert_eq!(lines[3].trim(), "next");
    }

    #[test]
    fn stringify_and_paste() {
        let out = text("#define S(x) #x\n#define P(a, b) a##b\nS(hi there) P(foo, 12)\n");
        assert!(out.contains("\"hi there\" foo12"), "{out}");
    }

    #[test]
    fn error_directive_names_line() {
        let t = TempTree::new();
        t.write("a.fx", b"x\n#if 1\n#error nope\n#endif\n");
        let e = pp(&t, "a.fx").unwrap_err();
        assert_eq!(e.line, 3);
        assert!(e.message.contains("nope"));
        assert!(e.to_string().contains("a.fx:3"));
    }

    #[test]
    fn malformed_input_is_an_error_not_a_panic() {
        for src in [
            "#if\n",
            "#if (1\n#endif\n",
            "#endif\n",
            "#else\n",
            "#define\n",
            "#define F(\n",
            "#if 1/0\n#endif\n",
            "#bogus\n",
            "#if 1\n",
            "#include\n",
            "#include \"\n",
        ] {
            let t = TempTree::new();
            t.write("a.fx", src.as_bytes());
            assert!(pp(&t, "a.fx").is_err(), "{src:?}");
        }
        // recursive macros end
        let out = text("#define A B\n#define B A\nA\n");
        assert!(out.contains('A') || out.contains('B'));
    }

    #[test]
    fn include_resolves_top_level_dir_first() {
        let t = TempTree::new();
        t.write("main.fx", b"#include \"common.fxsub\"\n");
        t.write("common.fxsub", b"top\n");
        t.write("sub/common.fxsub", b"nested\n");
        t.write("sub/mid.fxsub", b"#include \"common.fxsub\"\n");
        t.write("main2.fx", b"#include \"sub/mid.fxsub\"\n");
        t.write("main3.fx", b"#include \"SUB/Mid.fxsub\"\n");
        let r = pp(&t, "main2.fx").unwrap();
        // `common.fxsub` from sub/mid.fxsub resolves against the top-level dir, not sub/
        assert_eq!(r.text.split_whitespace().collect::<Vec<_>>(), ["top"]);
        assert!(r.includes.iter().all(|i| i.via == Via::TopLevelDir));
        assert_eq!(r.includes.len(), 2);
        let r = pp(&t, "main3.fx").unwrap();
        assert_eq!(r.includes[0].resolved, t.path("sub/mid.fxsub"));
    }

    #[test]
    fn include_falls_back_to_including_dir() {
        let t = TempTree::new();
        t.write("main.fx", b"#include \"sub\\\\mid.fxsub\"\n");
        t.write("sub/mid.fxsub", b"#include \"leaf.fxsub\"\n");
        t.write("sub/leaf.fxsub", b"leaf\n");
        let r = pp(&t, "main.fx").unwrap();
        assert_eq!(r.text.split_whitespace().collect::<Vec<_>>(), ["leaf"]);
        assert_eq!(r.includes[0].via, Via::TopLevelDir);
        assert_eq!(r.includes[1].via, Via::IncludingDir);
        // the leaf line maps back to its own file
        let (p, l) = r.origin(1).unwrap();
        assert_eq!((p, l), (t.path("sub/leaf.fxsub").as_path(), 1));
    }

    #[test]
    fn missing_include_names_the_include() {
        let t = TempTree::new();
        t.write("main.fx", b"\n#include \"shader/Missing.fxsub\"\n");
        let e = pp(&t, "main.fx").unwrap_err();
        assert_eq!(e.line, 2);
        assert!(e.message.contains("shader/Missing.fxsub"), "{e}");
    }

    #[test]
    fn include_cycle_stops() {
        let t = TempTree::new();
        t.write("a.fx", b"#include \"b.fxsub\"\n");
        t.write("b.fxsub", b"#include \"a.fx\"\n");
        assert!(pp(&t, "a.fx").unwrap_err().message.contains("too deeply"));
    }

    #[test]
    fn shift_jis_bytes_decode() {
        // "float4 a; // \x83\x65" is `テ` in Shift-JIS and invalid UTF-8
        let bytes = b"string s = \"\x83\x65\";\n";
        assert!(std::str::from_utf8(bytes).is_err());
        let t = TempTree::new();
        t.write("a.fx", bytes);
        assert!(pp(&t, "a.fx").unwrap().text.contains("\"テ\""));
    }
}
