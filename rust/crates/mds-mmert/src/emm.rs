//! EMM and EMD files: the effect-to-object assignment MME keeps next to a PMM (`.emm`) and per
//! model (`.emd`). Ported from `third_party/mmeffect/src/mmeffect/emm_manager.cpp` (`EmmFile::Load`,
//! `EmmFile::Save`, `EmdFile::Load`, `EmdFile::Save`, `MmeEmmLoad`, `MmeEmmSave`, `MmeEmdLoad`,
//! `MmeEmdSave`, `MmeFindEffectFileForModel`, `MmeBuildEmmPathForPmm`) and the byte contract in
//! `emm_manager.h`.
//!
//! The files are ANSI text read with `fgets` in `"rt"` mode and written in `"wt"` mode, so on disk
//! lines end with CRLF. [`parse_emm`] and [`parse_emd`] take the bytes, match on bytes as the C++
//! does, and decode each field from Shift-JIS; the writers encode Shift-JIS and write CRLF.
//!
//! The assignment state is [`Assignment`], one per live object; [`apply_emm`], [`save_emm`],
//! [`apply_emd`], and [`save_emd`] read and write it the way the C++ manager reads and writes its
//! `ModelData` records. Loading the effects an assignment names is the caller's job.
//!
//! `_fullpath` and `_splitpath` depend on the process directory and on Windows; here the
//! directory is a parameter ([`abs_path`]).

use std::collections::{BTreeMap, BTreeSet};

/// `kNone`: the value of an unassigned row.
pub const NONE: &str = "none";

/// One `[Object]` row: `Pmd<slot>` or `Acs<slot>` and the object file.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ObjectRecord {
    pub model: bool,
    pub slot: i32,
    pub path: String,
}

/// One object's rows in an `[Effect*]` section (`EmmEffectEntry`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Entry {
    /// `Pmd0`, `Acs3`, or `Obj` (EMD).
    pub key: String,
    /// The whole-object row: `""` when the file has none, [`NONE`] when unassigned.
    pub effect: String,
    pub has_show: bool,
    pub shown: bool,
    /// `[n]` rows, with the same `""`/[`NONE`] convention.
    pub subsets: BTreeMap<i32, String>,
    /// `[n].show` rows.
    pub subset_shows: BTreeMap<i32, bool>,
}

impl Entry {
    pub fn new(key: &str) -> Entry {
        Entry {
            key: key.to_string(),
            effect: String::new(),
            has_show: false,
            shown: true,
            subsets: BTreeMap::new(),
            subset_shows: BTreeMap::new(),
        }
    }
}

/// `[Effect]` (the default section) or `[Effect@<base>(<n>)]` (`EmmEffectSection`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Section {
    pub name: String,
    /// Empty for the default section.
    pub base: String,
    pub owner_key: String,
    pub owner_subset: i32,
    pub owner_material: String,
    pub default_path: String,
    pub entries: Vec<Entry>,
}

impl Section {
    pub fn is_default(&self) -> bool {
        self.base.is_empty()
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Emm {
    pub version: i32,
    pub objects: Vec<ObjectRecord>,
    pub sections: Vec<Section>,
}

impl Emm {
    /// The `Default` row of the default section.
    pub fn default_effect(&self) -> &str {
        self.sections
            .iter()
            .find(|s| s.is_default())
            .map_or("", |s| s.default_path.as_str())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Emd {
    pub version: i32,
    /// The `Obj` entry.
    pub entry: Entry,
}

/// One `MmeLogWrite` line; `message_box` is its flag 1 (the original also shows it in a
/// message box).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Log {
    pub text: String,
    pub message_box: bool,
}

fn log(out: &mut Vec<Log>, text: String, message_box: bool) {
    out.push(Log { text, message_box });
}

fn sjis(b: &[u8]) -> String {
    encoding_rs::SHIFT_JIS
        .decode_without_bom_handling(b)
        .0
        .into_owned()
}

fn to_sjis(s: &str) -> Vec<u8> {
    encoding_rs::SHIFT_JIS.encode(s).0.into_owned()
}

/// `isspace` in the C locale.
fn space(b: u8) -> bool {
    matches!(b, b' ' | b'\t' | b'\n' | 0x0B | 0x0C | b'\r')
}

fn trim(s: &[u8]) -> &[u8] {
    let b = s.iter().position(|&c| !space(c)).unwrap_or(s.len());
    let e = s.iter().rposition(|&c| !space(c)).map_or(b, |i| i + 1);
    &s[b..e.max(b)]
}

/// The lines `fgets(line, 0x400, f)` returns from a file opened with `"rt"`: CRLF read as LF,
/// Ctrl-Z ends the file, and a line longer than 1023 bytes comes back in pieces.
fn fgets_lines(bytes: &[u8]) -> Vec<Vec<u8>> {
    let mut text = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() && bytes[i] != 0x1A {
        if bytes[i] == b'\r' && bytes.get(i + 1) == Some(&b'\n') {
            i += 1;
        }
        text.push(bytes[i]);
        i += 1;
    }
    let mut out = Vec::new();
    let mut line = Vec::new();
    for b in text {
        line.push(b);
        if b == b'\n' || line.len() == 0x3FF {
            out.push(std::mem::take(&mut line));
        }
    }
    if !line.is_empty() {
        out.push(line);
    }
    out
}

/// `^\[([^\[\]]+)\]$`.
fn section_header(t: &[u8]) -> Option<&[u8]> {
    if t.len() < 2 || t[0] != b'[' || t[t.len() - 1] != b']' {
        return None;
    }
    let inner = &t[1..t.len() - 1];
    (!inner.is_empty() && !inner.iter().any(|&c| c == b'[' || c == b']')).then_some(inner)
}

/// `^([^=\s]+)\s*=\s*(.*)$`.
fn key_value(t: &[u8]) -> Option<(&[u8], &[u8])> {
    let eq = t.iter().position(|&c| c == b'=')?;
    let k = trim(&t[..eq]);
    if k.is_empty() || k.iter().any(|&c| c == b' ' || c == b'\t') {
        return None;
    }
    Some((k, trim(&t[eq + 1..])))
}

/// `boost::lexical_cast<int>`: an optional sign, digits, all of the text, no overflow.
fn lexical_int(s: &str) -> Option<i32> {
    let (neg, digits) = match s.as_bytes().first() {
        Some(b'-') => (true, &s[1..]),
        Some(b'+') => (false, &s[1..]),
        _ => (false, s),
    };
    if digits.is_empty() || !digits.bytes().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let mut v: i64 = 0;
    for c in digits.bytes() {
        v = v * 10 + i64::from(c - b'0');
        if v > 0x7FFF_FFFF {
            return None;
        }
    }
    Some(if neg { -v } else { v } as i32)
}

fn word(c: u8) -> bool {
    c.is_ascii_alphanumeric() || c == b'_'
}

/// `(Pmd|Acs)\d+` at the start of `s`: the length matched.
fn object_key_len(s: &str) -> Option<usize> {
    if !(s.starts_with("Pmd") || s.starts_with("Acs")) {
        return None;
    }
    let n = s[3..].bytes().take_while(u8::is_ascii_digit).count();
    (n > 0).then_some(3 + n)
}

/// `(\[(\d+)\])?` at the start of `s`: the digits, and the length matched.
fn subset_suffix(s: &str) -> (Option<&str>, usize) {
    if let Some(rest) = s.strip_prefix('[') {
        let n = rest.bytes().take_while(u8::is_ascii_digit).count();
        if n > 0 && rest.as_bytes().get(n) == Some(&b']') {
            return (Some(&rest[..n]), n + 2);
        }
    }
    (None, 0)
}

/// `\w+(\(\d+\))?` is all of `s`.
fn base_with_counter(s: &str) -> Option<&str> {
    let n = s.bytes().take_while(|&c| word(c)).count();
    if n == 0 {
        return None;
    }
    let rest = &s[n..];
    if rest.is_empty() {
        return Some(&s[..n]);
    }
    let inner = rest.strip_prefix('(')?.strip_suffix(')')?;
    (!inner.is_empty() && inner.bytes().all(|c| c.is_ascii_digit())).then_some(&s[..n])
}

/// `ParsedEmm`.
#[derive(Default)]
struct Parsed {
    version: i32,
    version_parsed: bool,
    abort_logging: bool,
    section_names: Vec<String>,
    objects: Vec<ObjectRecord>,
    sections: Vec<Section>,
    current: Option<usize>,
    seen: BTreeMap<String, BTreeSet<String>>,
}

impl Parsed {
    /// `HandleSection` (FUN_180049930).
    fn section(&mut self, name: &str) -> bool {
        if self.section_names.iter().any(|n| n == name) {
            return false;
        }
        self.section_names.push(name.to_string());
        if name == "Info" || name == "Object" {
            return true;
        }
        let base = if name == "Effect" {
            Some(String::new())
        } else {
            // ^Effect@((\w+)(\(\d+\))?)$
            name.strip_prefix("Effect@")
                .and_then(base_with_counter)
                .map(str::to_string)
        };
        let Some(base) = base else {
            return false;
        };
        self.sections.push(Section {
            name: name.to_string(),
            base,
            owner_key: String::new(),
            owner_subset: -1,
            owner_material: String::new(),
            default_path: String::new(),
            entries: Vec::new(),
        });
        self.current = Some(self.sections.len() - 1);
        true
    }

    /// `HandleKeyValue` (FUN_180049EB0); `emd` is the EmdFile flag.
    fn key_value(
        &mut self,
        section: &str,
        key: &str,
        value: &str,
        path: &str,
        emd: bool,
        out: &mut Vec<Log>,
    ) -> bool {
        // Every row registers its key first: a second row with the key in the section is
        // rejected, and an empty value is rejected with the key still registered.
        if !self
            .seen
            .entry(section.to_string())
            .or_default()
            .insert(key.to_string())
        {
            return false;
        }
        if value.is_empty() {
            return false;
        }
        if section == "Info" {
            if key != "Version" {
                return false;
            }
            let Some(v) = lexical_int(value) else {
                return false;
            };
            self.version = v;
            self.version_parsed = true;
            if v > 0 && v <= 3 {
                return true;
            }
            log(
                out,
                format!("MikuMikuEffect ver.0.37 cannot support this EMM file format:\n{path}"),
                true,
            );
            self.abort_logging = true;
            return false;
        }
        if section == "Object" {
            // ^((Pmd|Acs)(\d+))$
            if object_key_len(key) != Some(key.len()) {
                return false;
            }
            let Some(slot) = lexical_int(&key[3..]) else {
                return false;
            };
            let model = key.starts_with("Pmd");
            match self
                .objects
                .iter_mut()
                .find(|o| o.model == model && o.slot == slot)
            {
                Some(o) => o.path = value.to_string(),
                None => self.objects.push(ObjectRecord {
                    model,
                    slot,
                    path: value.to_string(),
                }),
            }
            return true;
        }
        if !section.starts_with("Effect") {
            return false;
        }
        let Some(cur) = self.current else {
            return false;
        };
        let sec = &mut self.sections[cur];
        if key == "Default" {
            if !sec.is_default() {
                return false;
            }
            sec.default_path = value.to_string();
            return true;
        }
        if key == "Owner" {
            // ^((Pmd|Acs)\d+)(\[(\d+)\])?(@(\w+(\(\d+\))?))?$
            let Some(n) = object_key_len(value) else {
                return false;
            };
            let (digits, m) = subset_suffix(&value[n..]);
            let rest = &value[n + m..];
            let material = match rest.strip_prefix('@') {
                None if rest.is_empty() => String::new(),
                None => return false,
                Some(m) if base_with_counter(m).is_some() => m.to_string(),
                Some(_) => return false,
            };
            let subset = match digits {
                Some(d) => match lexical_int(d) {
                    Some(v) => v,
                    None => return false,
                },
                None => -1,
            };
            sec.owner_key = value[..n].to_string();
            sec.owner_subset = subset;
            sec.owner_material = material;
            return true;
        }
        // ^((Pmd|Acs)\d+|Obj)(\[(\d+)\])?(\.show)?$, Obj only in an EMD, never in an EMM.
        let n = if key.starts_with("Obj") {
            3
        } else {
            match object_key_len(key) {
                Some(n) => n,
                None => return false,
            }
        };
        let (digits, m) = subset_suffix(&key[n..]);
        let show = match &key[n + m..] {
            "" => false,
            ".show" => true,
            _ => return false,
        };
        let base = &key[..n];
        if (base == "Obj") != emd {
            return false;
        }
        let subset = match digits {
            Some(d) => match lexical_int(d) {
                Some(v) => v,
                None => return false,
            },
            None => -1,
        };
        let i = match sec.entries.iter().position(|e| e.key == base) {
            Some(i) => i,
            None => {
                sec.entries.push(Entry::new(base));
                sec.entries.len() - 1
            }
        };
        let entry = &mut sec.entries[i];
        if show {
            let shown = match value {
                "true" => true,
                "false" => false,
                _ => return false,
            };
            if subset < 0 {
                entry.has_show = true;
                entry.shown = shown;
            } else {
                entry.subset_shows.insert(subset, shown);
            }
        } else if subset < 0 {
            entry.effect = value.to_string();
        } else {
            entry.subsets.insert(subset, value.to_string());
        }
        true
    }

    fn object_key_exists(&self, key: &str) -> bool {
        self.objects
            .iter()
            .any(|o| key_name(o.model, o.slot) == key)
    }
}

/// `KeyName`: `Pmd<slot>` or `Acs<slot>`.
pub fn key_name(model: bool, slot: i32) -> String {
    format!("{}{slot}", if model { "Pmd" } else { "Acs" })
}

/// The shared line driver (FUN_180047BD0) with the EmmFile or EmdFile virtuals.
fn drive(bytes: &[u8], path: &str, emd: bool, out: &mut Vec<Log>) -> Option<(Parsed, usize)> {
    let mut p = Parsed::default();
    let mut current = String::new();
    let lines = fgets_lines(bytes);
    if lines
        .first()
        .is_some_and(|l| l.starts_with(&[0xEF, 0xBB, 0xBF]))
    {
        log(out, format!("Error: failed to load file: {path}"), false);
        log(
            out,
            format!("MikuMikuEffect ver.0.37 cannot support this file format:\n{path}"),
            true,
        );
        return None;
    }
    for (n, raw) in lines.iter().enumerate() {
        let cut = raw
            .iter()
            .position(|&c| c == b';' || c == b'#')
            .unwrap_or(raw.len());
        let text = trim(&raw[..cut]);
        if text.is_empty() {
            continue;
        }
        let reject = format!(
            "Error: failed to load file: {path} (line {}):\n  '{}'",
            n + 1,
            sjis(raw)
        );
        let ok = if let Some(name) = section_header(text) {
            let name = sjis(name);
            let allowed = !emd || name == "Info" || name == "Effect";
            let ok = allowed && p.section(&name);
            if ok {
                current = name;
            }
            ok
        } else if let Some((k, v)) = key_value(text) {
            let (k, v) = (sjis(k), sjis(v));
            // The EmdFile rejects `[Effect] Default` before the shared handler sees it.
            !(emd && current == "Effect" && k == "Default")
                && p.key_value(&current, &k, &v, path, emd, out)
        } else {
            false
        };
        if !ok && !p.abort_logging {
            log(out, reject, true);
        }
    }
    Some((p, lines.len()))
}

fn validation_failed(error: &str, path: &str, p: &Parsed, lines: usize, out: &mut Vec<Log>) {
    log(out, format!("{error}\n"), true);
    if !p.abort_logging {
        log(
            out,
            format!("Error: failed to load file: {path} (line {lines})"),
            true,
        );
    }
}

/// `EmmFile::Load`: the file, or `None` with the reason in the log.
pub fn parse_emm(bytes: &[u8], path: &str) -> (Option<Emm>, Vec<Log>) {
    let mut out = Vec::new();
    let Some((p, lines)) = drive(bytes, path, false, &mut out) else {
        return (None, out);
    };
    let has = |n: &str| p.section_names.iter().any(|s| s == n);
    let mut error = String::new();
    if !has("Info") {
        error = "section 'Info' was not found".into();
    } else if !p.version_parsed || p.version == 0 {
        error = "key 'Version' was not found".into();
    } else if !has("Object") {
        error = "section 'Object' was not found".into();
    } else if !has("Effect") {
        error = "section 'Effect' was not found".into();
    } else {
        'sections: for s in &p.sections {
            if s.is_default() {
                if s.default_path.is_empty() {
                    error = "key 'Default' was not found".into();
                    break;
                }
            } else if s.owner_key.is_empty() {
                error = "key 'Owner' was not found".into();
                break;
            } else if !p.object_key_exists(&s.owner_key) {
                error = format!("unknown object '{}'", s.owner_key);
                break;
            }
            for e in &s.entries {
                if !p.object_key_exists(&e.key) {
                    error = format!("unknown object '{}'", e.key);
                    break 'sections;
                }
            }
        }
    }
    if !error.is_empty() {
        validation_failed(&error, path, &p, lines, &mut out);
        return (None, out);
    }
    let emm = Emm {
        version: p.version,
        objects: p.objects,
        sections: p.sections,
    };
    (Some(emm), out)
}

/// `EmdFile::Load`.
pub fn parse_emd(bytes: &[u8], path: &str) -> (Option<Emd>, Vec<Log>) {
    let mut out = Vec::new();
    let Some((mut p, lines)) = drive(bytes, path, true, &mut out) else {
        return (None, out);
    };
    let error = if !p.section_names.iter().any(|s| s == "Info") {
        "section 'Info' was not found"
    } else if !p.version_parsed || p.version == 0 {
        "key 'Version' was not found"
    } else if p.sections.len() != 1 {
        "section 'Effect' was not found"
    } else if p.sections[0].entries.len() != 1 {
        "key 'Obj' was not found"
    } else {
        ""
    };
    if !error.is_empty() {
        validation_failed(error, path, &p, lines, &mut out);
        return (None, out);
    }
    let entry = p.sections[0].entries.remove(0);
    (
        Some(Emd {
            version: p.version,
            entry,
        }),
        out,
    )
}

/// Text written as `"wt"` writes it: LF as CRLF, then Shift-JIS.
fn wt(text: &str) -> Vec<u8> {
    to_sjis(&text.replace('\n', "\r\n"))
}

fn tf(b: bool) -> &'static str {
    if b {
        "true"
    } else {
        "false"
    }
}

/// The rows of one entry after its whole-object row (`EmmFile::Save`): `.show`, then `[n]` and
/// `[n].show` for n up to the largest recorded subset.
fn entry_rows(s: &mut String, e: &Entry) {
    if !e.effect.is_empty() {
        s.push_str(&format!("{} = {}\n", e.key, e.effect));
    }
    if e.has_show {
        s.push_str(&format!("{}.show = {}\n", e.key, tf(e.shown)));
    }
    let max = e
        .subsets
        .keys()
        .chain(e.subset_shows.keys())
        .copied()
        .max()
        .unwrap_or(-1);
    for n in 0..=max {
        if let Some(p) = e.subsets.get(&n) {
            s.push_str(&format!("{}[{n}] = {p}\n", e.key));
        }
        if let Some(v) = e.subset_shows.get(&n) {
            s.push_str(&format!("{}[{n}].show = {}\n", e.key, tf(*v)));
        }
    }
}

/// `EmmFile::Save`: `[Info]`, `[Object]`, and the default `[Effect]` section with `entries`.
/// Named `[Effect@...]` sections are not written (the C++ port's documented divergence).
pub fn write_emm(objects: &[ObjectRecord], default: &str, entries: &[Entry]) -> Vec<u8> {
    let mut s = String::from("[Info]\nVersion = 3\n\n[Object]\n");
    for o in objects {
        s.push_str(&format!("{} = {}\n", key_name(o.model, o.slot), o.path));
    }
    s.push_str(&format!("\n[Effect]\nDefault = {default}\n"));
    for e in entries {
        entry_rows(&mut s, e);
    }
    s.push('\n');
    wt(&s)
}

/// `EmdFile::Save`.
pub fn write_emd(entry: &Entry) -> Vec<u8> {
    let mut s = String::from("[Info]\nVersion = 3\n\n[Effect]\n");
    let mut e = entry.clone();
    e.key = "Obj".into();
    entry_rows(&mut s, &e);
    s.push('\n');
    wt(&s)
}

/// A live object as the host enumerates it (`ExpGetPmd*` and `ExpGetAcs*`).
#[derive(Clone, Debug)]
pub struct Live {
    pub model: bool,
    /// The index in the host's model or accessory list.
    pub slot: i32,
    /// The object file as the host holds it.
    pub path: String,
    pub materials: i32,
    /// `ModelData::renderClass`: nonzero for an object that carries a scene-class effect.
    pub render_class: i32,
}

/// What an object is assigned (`ModelData::effectFile`, `shown`, `subsetEffects`, and the
/// `[n].show` registry). Paths are as assigned; `""` is unassigned.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Assignment {
    pub effect: String,
    pub shown: bool,
    pub subsets: BTreeMap<i32, String>,
    pub subset_shows: BTreeMap<i32, bool>,
}

impl Default for Assignment {
    fn default() -> Self {
        Assignment {
            effect: String::new(),
            shown: true,
            subsets: BTreeMap::new(),
            subset_shows: BTreeMap::new(),
        }
    }
}

impl Assignment {
    /// `MmeEmmEffectiveSubsetShown`: the subset's record, else the object's.
    pub fn subset_shown(&self, subset: i32) -> bool {
        self.subset_shows
            .get(&subset)
            .copied()
            .unwrap_or(self.shown)
    }
}

fn rooted(p: &str) -> bool {
    let b = p.as_bytes();
    (b.len() >= 2 && b[0].is_ascii_alphabetic() && b[1] == b':')
        || b.first().is_some_and(|&c| c == b'/' || c == b'\\')
}

/// `JoinPath`: `dir` and a path that may be relative.
pub fn join_path(dir: &str, path: &str) -> String {
    if rooted(path) || dir.is_empty() {
        return path.to_string();
    }
    let mut out = dir.to_string();
    if !out.ends_with(['/', '\\']) {
        // The C++ always adds `\`; a POSIX directory gets `/`.
        let posix = dir.starts_with('/') && !dir.contains('\\');
        out.push(if posix { '/' } else { '\\' });
    }
    out + path
}

/// `_fullpath`: `path` against the directory `cwd`, with `.` and `..` resolved. The separator is
/// `\` for Windows paths (a drive letter or a `\`), `/` otherwise.
// ponytail: no UNC paths and no per-drive current directories.
pub fn abs_path(path: &str, cwd: &str) -> String {
    if path.is_empty() {
        return String::new();
    }
    let full = if rooted(path) {
        path.to_string()
    } else {
        join_path(cwd, path)
    };
    let windows = full.contains('\\') || full.as_bytes().get(1) == Some(&b':');
    let sep = if windows { "\\" } else { "/" };
    let (drive, rest) = match full.as_bytes() {
        [d, b':', ..] if d.is_ascii_alphabetic() => (&full[..2], &full[2..]),
        _ => ("", full.as_str()),
    };
    let mut parts: Vec<&str> = Vec::new();
    for p in rest.split(['/', '\\']) {
        match p {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            p => parts.push(p),
        }
    }
    format!("{drive}{sep}{}", parts.join(sep))
}

/// `_splitpath` + `_makepath` of the directory: everything up to the last separator.
pub fn dir_of(path: &str) -> String {
    path.rfind(['/', '\\'])
        .map_or(String::new(), |i| path[..=i].to_string())
}

/// `FileNameOf`: the file name and extension.
pub fn file_name(path: &str) -> String {
    path.rsplit(['/', '\\']).next().unwrap_or("").to_string()
}

fn ieq(a: &str, b: &str) -> bool {
    a.eq_ignore_ascii_case(b)
}

/// `TailIEqual`.
fn tail_ieq(a: &str, b: &str) -> bool {
    let n = a.len().min(b.len());
    if n == 0 || a.len() == b.len() {
        return ieq(a, b);
    }
    let (long, short) = if a.len() > b.len() { (a, b) } else { (b, a) };
    long.as_bytes()[long.len() - n..].eq_ignore_ascii_case(short.as_bytes())
}

/// `ObjectPathMatches`.
fn path_matches(record: &str, object: &str, emm_dir: &str, cwd: &str) -> bool {
    if ieq(record, object) {
        return true;
    }
    let (abs_record, abs_joined, abs_object) = (
        abs_path(record, cwd),
        abs_path(&join_path(emm_dir, record), cwd),
        abs_path(object, cwd),
    );
    ieq(&abs_record, &abs_object)
        || ieq(&abs_joined, &abs_object)
        || tail_ieq(&abs_record, &abs_object)
        || tail_ieq(&abs_joined, &abs_object)
}

/// What [`apply_emm`] and [`apply_emd`] report.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ApplyReport {
    /// The file names of the live objects no `[Object]` row matched.
    pub unmatched: Vec<String>,
    /// The assigned effect files that do not exist, sorted and without duplicates.
    pub missing: Vec<String>,
    pub log: Vec<Log>,
}

fn missing_report(mut assigned: Vec<String>, exists: &dyn Fn(&str) -> bool, r: &mut ApplyReport) {
    assigned.sort();
    assigned.dedup();
    r.missing = assigned.into_iter().filter(|p| !exists(p)).collect();
    if !r.missing.is_empty() {
        let mut m = String::from("The following effect files do not exist:\n");
        for p in &r.missing {
            m.push('\n');
            m.push_str(p);
        }
        log(&mut r.log, m, true);
    }
}

/// `MmeEmmLoad` after the file parsed: the default effect (`""` for `none`), and the rows applied
/// to `assignments` (one per `live` object). `[Object]` rows match live objects by kind and path,
/// not by slot. `exists` answers whether an effect file exists.
pub fn apply_emm(
    emm: &Emm,
    emm_path: &str,
    live: &[Live],
    assignments: &mut [Assignment],
    cwd: &str,
    exists: &dyn Fn(&str) -> bool,
) -> (String, ApplyReport) {
    let default = match emm.default_effect() {
        NONE => String::new(),
        d => d.to_string(),
    };
    let mut report = ApplyReport::default();
    let mut records = emm.objects.clone();
    records.sort_by_key(|r| r.slot);
    let emm_dir = dir_of(emm_path);
    let mut by_key: BTreeMap<String, usize> = BTreeMap::new();
    for (i, obj) in live.iter().enumerate() {
        let kind = || records.iter().filter(|r| r.model == obj.model);
        let matched = kind()
            .find(|r| path_matches(&r.path, &obj.path, &emm_dir, cwd))
            .or_else(|| kind().find(|r| ieq(&file_name(&r.path), &file_name(&obj.path))));
        match matched {
            Some(r) => {
                by_key.insert(key_name(r.model, r.slot), i);
            }
            None => report.unmatched.push(file_name(&obj.path)),
        }
    }
    if !report.unmatched.is_empty() {
        let mut m =
            format!("{emm_path}\nFailed to load effect mapping for the following objects:\n");
        for n in &report.unmatched {
            m.push_str("\n  ");
            m.push_str(n);
        }
        log(&mut report.log, m, true);
    }
    let mut assigned = Vec::new();
    for section in &emm.sections {
        for e in &section.entries {
            let Some(&i) = by_key.get(&e.key) else {
                continue;
            };
            let a = &mut assignments[i];
            if !e.effect.is_empty() {
                a.effect = if e.effect == NONE {
                    String::new()
                } else {
                    e.effect.clone()
                };
                if !a.effect.is_empty() {
                    assigned.push(a.effect.clone());
                }
            }
            if e.has_show {
                a.shown = e.shown;
            }
            for (&n, p) in &e.subsets {
                let p = if p == NONE { String::new() } else { p.clone() };
                if !p.is_empty() {
                    assigned.push(p.clone());
                }
                a.subsets.insert(n, p);
            }
            for (&n, &v) in &e.subset_shows {
                if n >= 0 && n < live[i].materials {
                    a.subset_shows.insert(n, v);
                }
            }
        }
    }
    missing_report(assigned, exists, &mut report);
    (default, report)
}

/// `MmeEmmSave`: the `.emm` bytes of the live state. Paths are written absolute against `cwd`;
/// unassigned rows are `none`.
pub fn save_emm(live: &[Live], assignments: &[Assignment], default: &str, cwd: &str) -> Vec<u8> {
    let mut rows: Vec<(&Live, &Assignment)> = live
        .iter()
        .zip(assignments)
        .filter(|(l, _)| l.model)
        .chain(live.iter().zip(assignments).filter(|(l, _)| !l.model))
        .collect();
    rows.sort_by_key(|(l, _)| l.slot);
    let none_or = |p: &str| {
        if p.is_empty() {
            NONE.to_string()
        } else {
            abs_path(p, cwd)
        }
    };
    let objects: Vec<ObjectRecord> = rows
        .iter()
        .map(|(l, _)| ObjectRecord {
            model: l.model,
            slot: l.slot,
            path: abs_path(&l.path, cwd),
        })
        .collect();
    let entries: Vec<Entry> = rows
        .iter()
        .map(|(l, a)| {
            let mut e = Entry::new(&key_name(l.model, l.slot));
            e.has_show = true;
            e.shown = a.shown;
            // A scene-effect carrier keeps only its show row.
            if l.render_class == 0 {
                e.effect = none_or(&a.effect);
                e.subsets = a.subsets.iter().map(|(&n, p)| (n, none_or(p))).collect();
                e.subset_shows = a
                    .subset_shows
                    .iter()
                    .filter(|(&n, _)| n < l.materials)
                    .map(|(&n, &v)| (n, v))
                    .collect();
            }
            e
        })
        .collect();
    write_emm(&objects, &none_or(default), &entries)
}

/// `ResolveEmdValue`: `none`, `hide`, and `main_default` unassign; other values join the EMD's
/// directory.
fn emd_value(raw: &str, dir: &str) -> String {
    match raw {
        "none" | "hide" | "main_default" => String::new(),
        _ => join_path(dir, raw),
    }
}

/// `MmeEmdLoad` for one target: the target's assignment is replaced by the `Obj` rows.
pub fn apply_emd(
    emd: &Emd,
    emd_path: &str,
    materials: i32,
    a: &mut Assignment,
    exists: &dyn Fn(&str) -> bool,
) -> ApplyReport {
    let dir = dir_of(emd_path);
    let e = &emd.entry;
    let shown = a.shown;
    *a = Assignment {
        shown,
        ..Assignment::default()
    };
    let mut assigned = Vec::new();
    if !e.effect.is_empty() {
        a.effect = emd_value(&e.effect, &dir);
        if !a.effect.is_empty() {
            assigned.push(a.effect.clone());
        }
    }
    if e.has_show {
        a.shown = e.shown;
    }
    for (&n, p) in e.subsets.iter().filter(|(&n, _)| n < materials) {
        let p = emd_value(p, &dir);
        if !p.is_empty() {
            assigned.push(p.clone());
        }
        a.subsets.insert(n, p);
    }
    for (&n, &v) in e.subset_shows.iter().filter(|(&n, _)| n < materials) {
        a.subset_shows.insert(n, v);
    }
    let mut report = ApplyReport::default();
    missing_report(assigned, exists, &mut report);
    report
}

/// `MmeEmdSave`: one object's `.emd` bytes, paths absolute against the EMD's directory.
pub fn save_emd(
    a: &Assignment,
    emd_path: &str,
    materials: i32,
    render_class: i32,
    cwd: &str,
) -> Vec<u8> {
    let dir = dir_of(emd_path);
    let none_or = |p: &str| {
        if p.is_empty() {
            NONE.to_string()
        } else {
            abs_path(&join_path(&dir, p), cwd)
        }
    };
    let mut e = Entry::new("Obj");
    e.effect = none_or(&a.effect);
    e.has_show = !a.effect.is_empty();
    e.shown = a.shown;
    if render_class == 0 {
        e.subsets = a.subsets.iter().map(|(&n, p)| (n, none_or(p))).collect();
        e.subset_shows = a
            .subset_shows
            .iter()
            .filter(|(&n, _)| n < materials)
            .map(|(&n, &v)| (n, v))
            .collect();
    }
    write_emd(&e)
}

/// `MmeBuildEmmPathForPmm`: `<dir><name>.emm` beside a PMM, or `None` for the `(invalid)` path.
pub fn emm_path_for_pmm(pmm: &str) -> Option<String> {
    if pmm == "(invalid)" {
        return None;
    }
    let dir = dir_of(pmm);
    let name = &pmm[dir.len()..];
    let base = name.rfind('.').map_or(name, |i| &name[..i]);
    Some(format!("{dir}{base}.emm"))
}

/// `MmeFindEffectFileForModel`: `<dir><base>.fx` beside the model, then the `[<fx>]` in the
/// model's file name, then the EMM default; `""` when none exists.
pub fn effect_for_model(model_path: &str, default: &str, exists: &dyn Fn(&str) -> bool) -> String {
    let dir = dir_of(model_path);
    let name = &model_path[dir.len()..];
    let base = name.rfind('.').map_or(name, |i| &name[..i]);
    let same = format!("{dir}{base}.fx");
    if exists(&same) {
        return same;
    }
    if let Some(open) = base.find('[') {
        if let Some(close) = base[open..].find(']').map(|c| c + open) {
            if close > open + 1 {
                let embedded = format!("{dir}{}", &base[open + 1..close]);
                if exists(&embedded) {
                    return embedded;
                }
            }
        }
    }
    if !default.is_empty() && exists(default) {
        return default.to_string();
    }
    String::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn row_gates_follow_the_cpp() {
        let file = b"[Info]\r\nVersion = 3\r\n\r\n[Object]\r\nPmd0 = a.pmx\r\nPmd0 = b.pmx\r\n\
Acs1 =\r\nAcs1 = c.x\r\n[Effect]\r\nDefault = none\r\nPmd0 = x.fx ; comment\r\nObj = y.fx\r\n";
        let (emm, log) = parse_emm(file, "t.emm");
        let emm = emm.unwrap();
        // The second Pmd0 and both Acs1 rows (empty value, then a duplicate) are rejected.
        assert_eq!(emm.objects.len(), 1);
        assert_eq!(emm.objects[0].path, "a.pmx");
        assert_eq!(emm.sections[0].entries[0].effect, "x.fx");
        let lines: Vec<&str> = log.iter().map(|l| l.text.as_str()).collect();
        assert_eq!(
            lines,
            [
                "Error: failed to load file: t.emm (line 6):\n  'Pmd0 = b.pmx\n'",
                "Error: failed to load file: t.emm (line 7):\n  'Acs1 =\n'",
                "Error: failed to load file: t.emm (line 8):\n  'Acs1 = c.x\n'",
                "Error: failed to load file: t.emm (line 12):\n  'Obj = y.fx\n'",
            ]
        );
        let (none, log) = parse_emm(b"[Info]\nVersion = 4\n[Object]\n[Effect]\n", "v.emm");
        assert!(none.is_none());
        assert_eq!(
            log[0].text,
            "MikuMikuEffect ver.0.37 cannot support this EMM file format:\nv.emm"
        );
        // The version gate stops the line log; the validator still fails on the Default row.
        assert_eq!(log[1].text, "key 'Default' was not found\n");
        assert_eq!(log.len(), 2);
        assert!(parse_emm(b"\xEF\xBB\xBF[Info]\n", "b.emm").0.is_none());
        assert_eq!(
            abs_path("..\\fx\\a.fx", "C:\\mmd\\pmm\\"),
            "C:\\mmd\\fx\\a.fx"
        );
        assert_eq!(abs_path("b/./c.fx", "/home/u"), "/home/u/b/c.fx");
        assert_eq!(
            emm_path_for_pmm("C:\\mmd\\scene.pmm").as_deref(),
            Some("C:\\mmd\\scene.emm")
        );
    }
}
