//! VPD poses: Shift-JIS text. The reader follows `ReadVpd` in
//! `vpd_format.cpp` on `next` line by line; the writer emits the layout of
//! the MMD port `src/io/vpd_file.cpp` (`%f` values, its comments), with the
//! line ending of the file that was read.

use crate::io::Result;
use crate::text::Sjis;
use crate::Error;

/// Most bones the C++ reader accepts.
const MAX_BONES: i64 = 100_000;
/// Longest line the C++ reader accepts.
const MAX_LINE: usize = 1 << 20;

#[derive(Clone, Debug)]
pub struct Vpd {
    /// The model line up to ".osm;" (all of it when ".osm;" is missing).
    pub model_name: Sjis,
    pub bones: Vec<Bone>,
    /// Lines end in CR LF, as MMD on Windows writes them.
    pub crlf: bool,
}

#[derive(Clone, Debug)]
pub struct Bone {
    /// The text after '{' on the bone line.
    pub name: Sjis,
    pub translation: [f32; 3],
    pub rotation: [f32; 4],
}

struct Lines<'a> {
    data: &'a [u8],
    pos: usize,
    crlf: Option<bool>,
}

impl<'a> Lines<'a> {
    fn err(&self, what: &'static str) -> Error {
        Error::Invalid {
            offset: self.pos,
            what,
        }
    }

    /// `ReadLine`: up to '\n', one trailing '\r' removed. A last line
    /// without '\n' counts; an empty end of file does not.
    fn line(&mut self) -> Result<&'a [u8]> {
        let rest = &self.data[self.pos..];
        let (mut line, used) = match rest.iter().position(|&b| b == b'\n') {
            Some(n) => (&rest[..n], n + 1),
            None if rest.is_empty() => {
                return Err(Error::Truncated {
                    offset: self.data.len(),
                })
            }
            None => (rest, rest.len()),
        };
        if line.len() > MAX_LINE {
            return Err(self.err("line too long"));
        }
        let cr = line.last() == Some(&b'\r');
        if cr {
            line = &line[..line.len() - 1];
        }
        self.crlf.get_or_insert(cr);
        self.pos += used;
        Ok(line)
    }

    fn nonempty_line(&mut self) -> Result<&'a [u8]> {
        loop {
            let line = self.line()?;
            if !line.is_empty() {
                return Ok(line);
            }
        }
    }
}

/// The longest prefix of `s` that `strtod` reads as a decimal number,
/// after leading blanks: sign, digits, '.', digits, exponent.
fn scan_float(s: &[u8]) -> Option<(f32, &[u8])> {
    let start = s
        .iter()
        .position(|b| !b.is_ascii_whitespace())
        .unwrap_or(s.len());
    let s = &s[start..];
    let mut i = usize::from(matches!(s.first(), Some(b'+' | b'-')));
    let digits = |s: &[u8], i: usize| s[i..].iter().take_while(|b| b.is_ascii_digit()).count();
    let int = digits(s, i);
    i += int;
    let mut frac = 0;
    if s.get(i) == Some(&b'.') {
        frac = digits(s, i + 1);
        i += 1 + frac;
    }
    if int + frac == 0 {
        // "%f" prints infinities and NaN as words; strtod reads them back.
        // ponytail: strtod also takes "nan(...)" and hex floats; MMD never
        // writes them, so they fail here.
        let negative = s.first() == Some(&b'-');
        let word = |w: &[u8]| {
            s.get(i..i + w.len())
                .is_some_and(|t| t.eq_ignore_ascii_case(w))
        };
        let (value, len) = if word(b"infinity") {
            (f32::INFINITY, 8)
        } else if word(b"inf") {
            (f32::INFINITY, 3)
        } else if word(b"nan") {
            (f32::NAN, 3)
        } else {
            return None;
        };
        let value = if negative { -value } else { value };
        return Some((value, &s[i + len..]));
    }
    if matches!(s.get(i), Some(b'e' | b'E')) {
        let sign = usize::from(matches!(s.get(i + 1), Some(b'+' | b'-')));
        let exp = digits(s, i + 1 + sign);
        if exp > 0 {
            i += 1 + sign + exp;
        }
    }
    let text = std::str::from_utf8(&s[..i]).ok()?;
    Some((text.parse().ok()?, &s[i..]))
}

/// `sscanf(line, " %f,%f,...;")` returning N conversions, plus the C++
/// check that the line holds a ';' somewhere.
fn scan_values<const N: usize>(line: &[u8]) -> Option<[f32; N]> {
    if !line.contains(&b';') {
        return None;
    }
    let mut out = [0.0; N];
    let mut rest = line;
    for (k, v) in out.iter_mut().enumerate() {
        if k > 0 {
            rest = rest.strip_prefix(b",")?;
        }
        let (x, tail) = scan_float(rest)?;
        *v = x;
        rest = tail;
    }
    Some(out)
}

/// `strtol(line) ` followed by ';'.
fn scan_count(line: &[u8]) -> Option<i64> {
    let start = line
        .iter()
        .position(|b| !b.is_ascii_whitespace())
        .unwrap_or(line.len());
    let s = &line[start..];
    let sign = usize::from(matches!(s.first(), Some(b'+' | b'-')));
    let digits = s[sign..].iter().take_while(|b| b.is_ascii_digit()).count();
    if digits == 0 || s.get(sign + digits) != Some(&b';') {
        return None;
    }
    // More than 18 digits overflows strtol (ERANGE) or exceeds the cap.
    let n: i64 = std::str::from_utf8(&s[..sign + digits])
        .ok()?
        .parse()
        .ok()?;
    Some(n)
}

impl Vpd {
    pub fn read(data: &[u8]) -> Result<Self> {
        let mut l = Lines {
            data,
            pos: 0,
            crlf: None,
        };
        if l.line()? != b"Vocaloid Pose Data file" {
            return Err(l.err("not a VPD file"));
        }
        if !l.line()?.is_empty() {
            return Err(l.err("second line is not empty"));
        }
        let model = l.line()?;
        let end = model
            .windows(5)
            .position(|w| w == b".osm;")
            .unwrap_or(model.len());
        let model_name = Sjis::from_raw(model[..end].to_vec());
        let count = scan_count(l.line()?)
            .filter(|n| (0..=MAX_BONES).contains(n))
            .ok_or(l.err("bad bone count"))?;
        let mut bones = Vec::new();
        for _ in 0..count {
            let line = l.nonempty_line()?;
            let brace = line
                .iter()
                .position(|&b| b == b'{')
                .ok_or(l.err("bone line without '{'"))?;
            let name = Sjis::from_raw(line[brace + 1..].to_vec());
            let translation = scan_values(l.line()?).ok_or(l.err("bad translation"))?;
            let rotation = scan_values(l.line()?).ok_or(l.err("bad rotation"))?;
            let close = l.line()?;
            if close.iter().find(|&&b| b != b' ' && b != b'\t') != Some(&b'}') {
                return Err(l.err("bone block does not close"));
            }
            bones.push(Bone {
                name,
                translation,
                rotation,
            });
        }
        Ok(Vpd {
            model_name,
            bones,
            crlf: l.crlf.unwrap_or(true),
        })
    }

    /// The MMD layout. Values print as C `%f` of the float widened to
    /// double.
    pub fn write(&self) -> Vec<u8> {
        // ponytail: Rust rounds exact decimal ties (such as 0.0078125) half
        // to even, as glibc does; an MSVC CRT that rounds them away from
        // zero would print the last digit one higher.
        let f = |v: &[f32]| -> String {
            v.iter()
                .map(|&x| match x {
                    // glibc's spelling; Rust would print "NaN".
                    _ if x.is_nan() && x.is_sign_negative() => "-nan".into(),
                    _ if x.is_nan() => "nan".into(),
                    _ => format!("{:.6}", f64::from(x)),
                })
                .collect::<Vec<_>>()
                .join(",")
        };
        let nl: &[u8] = if self.crlf { b"\r\n" } else { b"\n" };
        let mut out = Vec::new();
        let mut line = |parts: &[&[u8]]| {
            for p in parts {
                out.extend_from_slice(p);
            }
            out.extend_from_slice(nl);
        };
        line(&[b"Vocaloid Pose Data file"]);
        line(&[]);
        // 親ファイル名 and 総ポーズボーン数 in Shift-JIS, as in vpd_file.cpp.
        line(&[
            &self.model_name.raw,
            b".osm;\t\t// \x90\x65\x83\x74\x83\x40\x83\x43\x83\x8b\x96\xbc",
        ]);
        let count = self.bones.len().to_string();
        line(&[
            count.as_bytes(),
            b";\t\t\t\t// \x91\x8d\x83\x7c\x81\x5b\x83\x59\x83\x7b\x81\x5b\x83\x93\x90\x94",
        ]);
        line(&[]);
        for (i, b) in self.bones.iter().enumerate() {
            line(&[format!("Bone{i}{{").as_bytes(), &b.name.raw]);
            line(&[
                b"  ",
                f(&b.translation).as_bytes(),
                b";\t\t\t\t// trans x,y,z",
            ]);
            line(&[
                b"  ",
                f(&b.rotation).as_bytes(),
                b";\t\t// Quaternion x,y,z,w",
            ]);
            line(&[b"}"]);
            line(&[]);
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn floats_scan_like_strtod() {
        assert_eq!(scan_float(b" 1.5,"), Some((1.5, &b","[..])));
        assert_eq!(scan_float(b"-0.25e1;"), Some((-2.5, &b";"[..])));
        assert_eq!(scan_float(b"3e;"), Some((3.0, &b"e;"[..])));
        assert_eq!(scan_float(b".;"), None);
        assert_eq!(scan_float(b"-inf,"), Some((f32::NEG_INFINITY, &b","[..])));
        assert!(scan_float(b"nan;").is_some_and(|(x, _)| x.is_nan()));
        assert_eq!(scan_values::<3>(b"  1,2,3 // ;"), Some([1.0, 2.0, 3.0]));
        assert_eq!(scan_values::<3>(b"  1,2,3"), None, "needs a ';'");
        assert_eq!(
            scan_values::<3>(b"  1 ,2,3;"),
            None,
            "',' right after the number"
        );
        assert_eq!(scan_count(b"3;\t// x"), Some(3));
        assert_eq!(scan_count(b"3 ;"), None);
    }
}
