//! Trace format 1. This module is the only place that knows the grammar.
//!
//! ```text
//! mds-trace 1 <L1|L2>
//! <frame> <kind> <index> <hexfloat> <hexfloat> ...
//! ```
//!
//! Fields are C99 `%a` hex floats. They are compared as raw `f64` bits, so
//! `-0` and `0`, and NaNs with different payloads, are different values.
//! Every line, the last included, ends with `\n`.

pub const MAX_LINE: usize = 64 * 1024;
const MAX_HEX_DIGITS: usize = 32;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Level {
    L1,
    L2,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Field {
    pub bits: u64,
    pub text: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Record {
    pub frame: u32,
    pub kind: String,
    pub index: u32,
    pub fields: Vec<Field>,
}

pub fn parse_header(line: &str) -> Result<Level, &'static str> {
    let mut t = line.split(' ');
    if t.next() != Some("mds-trace") {
        return Err("bad header: expected 'mds-trace 1 <level>'");
    }
    if t.next() != Some("1") {
        return Err("unsupported trace format version");
    }
    let level = match t.next() {
        Some("L1") => Level::L1,
        Some("L2") => Level::L2,
        _ => return Err("bad header: level must be L1 or L2"),
    };
    if t.next().is_some() {
        return Err("bad header: trailing tokens");
    }
    Ok(level)
}

pub fn parse_record(line: &str) -> Result<Record, &'static str> {
    let mut t = line.split(' ');
    let frame = parse_u32(t.next())?;
    let kind = t.next().ok_or("missing track kind")?;
    if kind.is_empty()
        || !kind
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
    {
        return Err("bad track kind");
    }
    let index = parse_u32(t.next())?;
    let mut fields = Vec::new();
    for tok in t {
        fields.push(Field {
            bits: parse_hex_float(tok)?,
            text: tok.to_owned(),
        });
    }
    if fields.is_empty() {
        return Err("record has no fields");
    }
    Ok(Record {
        frame,
        kind: kind.to_owned(),
        index,
        fields,
    })
}

fn parse_u32(tok: Option<&str>) -> Result<u32, &'static str> {
    let tok = tok.ok_or("missing frame or index")?;
    if tok.is_empty() || tok.len() > 10 || !tok.bytes().all(|b| b.is_ascii_digit()) {
        return Err("bad frame or index number");
    }
    tok.parse().map_err(|_| "frame or index out of range")
}

/// Parses a `%a` hex float (or `inf`, `nan`, `nan(0x...)`) to exact `f64` bits.
/// A value that a double cannot hold exactly is an error, never rounded.
pub fn parse_hex_float(tok: &str) -> Result<u64, &'static str> {
    const ERR: &str = "bad hex float";
    const EXP_ALL: u64 = 0x7ff << 52;
    let (sign, rest) = match tok.strip_prefix('-') {
        Some(r) => (1u64 << 63, r),
        None => (0, tok),
    };
    if rest == "inf" {
        return Ok(sign | EXP_ALL);
    }
    if let Some(p) = rest.strip_prefix("nan") {
        // A bare nan is the default quiet NaN, which is what glibc prints.
        let payload = if p.is_empty() {
            1u64 << 51
        } else {
            let h = p
                .strip_prefix("(0x")
                .and_then(|x| x.strip_suffix(')'))
                .filter(|h| !h.is_empty() && h.len() <= 13)
                .ok_or(ERR)?;
            let v = u64::from_str_radix(h, 16).map_err(|_| ERR)?;
            if v == 0 || v >> 52 != 0 {
                return Err(ERR);
            }
            v
        };
        return Ok(sign | EXP_ALL | payload);
    }

    let body = rest.strip_prefix("0x").ok_or(ERR)?;
    let (mant_s, exp_s) = body.split_once('p').ok_or(ERR)?;
    let (int_s, frac_s) = mant_s.split_once('.').unwrap_or((mant_s, ""));
    let ndigits = int_s.len() + frac_s.len();
    if ndigits == 0 || ndigits > MAX_HEX_DIGITS {
        return Err(ERR);
    }
    let mut mant: u128 = 0;
    for c in int_s.chars().chain(frac_s.chars()) {
        mant = (mant << 4) | u128::from(c.to_digit(16).ok_or(ERR)?);
    }
    let (esign, edigits) = match exp_s.as_bytes().first() {
        Some(b'-') => (-1i64, &exp_s[1..]),
        Some(b'+') => (1, &exp_s[1..]),
        _ => (1, exp_s),
    };
    if edigits.is_empty() || edigits.len() > 5 || !edigits.bytes().all(|b| b.is_ascii_digit()) {
        return Err(ERR);
    }
    let mut e = esign * edigits.parse::<i64>().map_err(|_| ERR)? - 4 * frac_s.len() as i64;

    if mant == 0 {
        return Ok(sign);
    }
    let tz = mant.trailing_zeros();
    mant >>= tz;
    e += i64::from(tz);
    let bl = i64::from(128 - mant.leading_zeros());
    if bl > 53 {
        return Err("hex float is not exactly a double");
    }
    let top = e + bl - 1; // unbiased exponent of the leading bit
    if top > 1023 {
        return Err("hex float out of range");
    }
    if top >= -1022 {
        let frac = ((mant << (53 - bl)) as u64) & ((1 << 52) - 1);
        Ok(sign | (((top + 1023) as u64) << 52) | frac)
    } else {
        let sh = e + 1074;
        if sh < 0 {
            return Err("hex float is not exactly a double");
        }
        Ok(sign | ((mant << sh) as u64))
    }
}
