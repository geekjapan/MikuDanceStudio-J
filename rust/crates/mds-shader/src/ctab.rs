//! The constant table (`CTAB` comment) of a D3D9 shader bytecode (`d3dbc`) blob.

use std::fmt;

/// `D3DXREGISTER_SET`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RegisterSet {
    Bool,
    Int4,
    Float4,
    Sampler,
}

impl RegisterSet {
    /// The register prefix in an assembly listing: `b`, `i`, `c`, or `s`.
    pub fn prefix(self) -> char {
        match self {
            RegisterSet::Bool => 'b',
            RegisterSet::Int4 => 'i',
            RegisterSet::Float4 => 'c',
            RegisterSet::Sampler => 's',
        }
    }
}

/// One parameter and the registers it occupies.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Constant {
    pub name: String,
    pub set: RegisterSet,
    pub index: u16,
    pub count: u16,
}

impl fmt::Display for Constant {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}={}{}", self.name, self.set.prefix(), self.index)?;
        if self.count != 1 {
            write!(f, "+{}", self.count)?;
        }
        Ok(())
    }
}

const COMMENT: u32 = 0xfffe;
const TAG_CTAB: u32 = u32::from_le_bytes(*b"CTAB");

fn u32_at(b: &[u8], off: usize) -> Option<u32> {
    let s = b.get(off..off.checked_add(4)?)?;
    Some(u32::from_le_bytes([s[0], s[1], s[2], s[3]]))
}

fn u16_at(b: &[u8], off: usize) -> Option<u16> {
    let s = b.get(off..off.checked_add(2)?)?;
    Some(u16::from_le_bytes([s[0], s[1]]))
}

fn cstr_at(b: &[u8], off: usize) -> Option<String> {
    let rest = b.get(off..)?;
    let end = rest.iter().position(|&c| c == 0)?;
    Some(String::from_utf8_lossy(&rest[..end]).into_owned())
}

/// Returns the payload of the `CTAB` comment: the bytes after the tag, where the table
/// offsets start.
fn find_ctab(d3dbc: &[u8]) -> Result<&[u8], String> {
    let mut off = 4; // skip the version token
    loop {
        let tok = u32_at(d3dbc, off).ok_or("no CTAB comment before the first instruction")?;
        if tok & 0xffff != COMMENT {
            return Err("no CTAB comment before the first instruction".into());
        }
        let words = ((tok >> 16) & 0x7fff) as usize;
        let start = off + 4;
        let end = start + words * 4;
        let body = d3dbc
            .get(start..end)
            .ok_or("a comment runs past the end of the shader")?;
        if u32_at(body, 0) == Some(TAG_CTAB) {
            return Ok(&body[4..]);
        }
        off = end;
    }
}

/// Parses the constant table of `d3dbc`. Every offset is checked against the comment size.
pub fn parse(d3dbc: &[u8]) -> Result<Vec<Constant>, String> {
    let t = find_ctab(d3dbc)?;
    let bad = |what: &str| format!("CTAB {what} is out of bounds");
    let size = u32_at(t, 0).ok_or_else(|| bad("header"))?;
    if size != 28 {
        return Err(format!("CTAB header size is {size}, want 28"));
    }
    let count = u32_at(t, 12).ok_or_else(|| bad("header"))? as usize;
    let info = u32_at(t, 16).ok_or_else(|| bad("header"))? as usize;
    if count > t.len() / 20 {
        return Err(bad("constant count"));
    }
    let mut out = Vec::with_capacity(count);
    for i in 0..count {
        let e = info + i * 20;
        let name_off = u32_at(t, e).ok_or_else(|| bad("constant"))? as usize;
        let set = match u16_at(t, e + 4).ok_or_else(|| bad("constant"))? {
            0 => RegisterSet::Bool,
            1 => RegisterSet::Int4,
            2 => RegisterSet::Float4,
            3 => RegisterSet::Sampler,
            s => return Err(format!("CTAB register set {s} is unknown")),
        };
        out.push(Constant {
            name: cstr_at(t, name_off).ok_or_else(|| bad("name"))?,
            set,
            index: u16_at(t, e + 6).ok_or_else(|| bad("constant"))?,
            count: u16_at(t, e + 8).ok_or_else(|| bad("constant"))?,
        });
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A ps_3_0 blob with one comment that is not a CTAB, then a CTAB with two constants.
    fn blob() -> Vec<u8> {
        let mut t: Vec<u8> = Vec::new();
        let put = |t: &mut Vec<u8>, v: u32| t.extend_from_slice(&v.to_le_bytes());
        put(&mut t, 28); // size
        put(&mut t, 0); // creator
        put(&mut t, 0xffff0300); // version
        put(&mut t, 2); // constants
        put(&mut t, 28); // constant info
        put(&mut t, 0); // flags
        put(&mut t, 0); // target
        let names = 28 + 2 * 20;
        for (name_off, set, index, count) in [(names, 2u16, 3u16, 4u16), (names + 6, 3, 0, 1)] {
            put(&mut t, name_off);
            t.extend_from_slice(&set.to_le_bytes());
            t.extend_from_slice(&index.to_le_bytes());
            t.extend_from_slice(&count.to_le_bytes());
            t.extend_from_slice(&0u16.to_le_bytes());
            put(&mut t, 0);
            put(&mut t, 0);
        }
        t.extend_from_slice(b"World\0Samp\0");
        while t.len() % 4 != 0 {
            t.push(0);
        }
        let mut b = Vec::new();
        b.extend_from_slice(&0xffff0300u32.to_le_bytes());
        b.extend_from_slice(&(COMMENT | (2 << 16)).to_le_bytes());
        b.extend_from_slice(b"TEXTabcd");
        let words = (t.len() / 4 + 1) as u32;
        b.extend_from_slice(&(COMMENT | (words << 16)).to_le_bytes());
        b.extend_from_slice(b"CTAB");
        b.extend_from_slice(&t);
        b.extend_from_slice(&0x0000ffffu32.to_le_bytes()); // end
        b
    }

    #[test]
    fn reads_names_and_registers() {
        let c = parse(&blob()).unwrap();
        let s: Vec<String> = c.iter().map(|c| c.to_string()).collect();
        assert_eq!(s, ["World=c3+4", "Samp=s0"]);
    }

    #[test]
    fn rejects_truncated_input_without_panicking() {
        let b = blob();
        for n in 0..b.len() {
            let _ = parse(&b[..n]);
        }
        assert!(parse(&b[..b.len() - 8]).is_err());
    }
}
