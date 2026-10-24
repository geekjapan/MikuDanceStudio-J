//! Strings as stored in the files: the raw bytes, which the writers emit
//! unchanged, next to the decoded text, which is for display only.

use crate::io::{Reader, Result, Writer};
use encoding_rs::{SHIFT_JIS, UTF_16LE, UTF_8};

/// Decodes Shift-JIS (cp932) up to the first NUL. Invalid bytes decode to
/// U+FFFD; the raw bytes stay as read.
pub fn decode_sjis(raw: &[u8]) -> String {
    let end = raw.iter().position(|&b| b == 0).unwrap_or(raw.len());
    SHIFT_JIS
        .decode_without_bom_handling(&raw[..end])
        .0
        .into_owned()
}

/// A fixed-width Shift-JIS field (PMD names, VMD key names, PMM paths). The
/// bytes after the NUL are kept, so residue in the field survives a save.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FixedSjis<const N: usize> {
    pub raw: [u8; N],
    pub text: String,
}

impl<const N: usize> FixedSjis<N> {
    pub(crate) fn read(r: &mut Reader) -> Result<Self> {
        let raw = r.array::<N>()?;
        Ok(FixedSjis {
            text: decode_sjis(&raw),
            raw,
        })
    }
    pub(crate) fn write(&self, w: &mut Writer) {
        w.bytes(&self.raw);
    }
}

/// A Shift-JIS string of any width: the length-prefixed names of PMM, the
/// 10 or 20 byte VMD model name, and the VPD names.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Sjis {
    pub raw: Vec<u8>,
    pub text: String,
}

impl Sjis {
    pub fn from_raw(raw: Vec<u8>) -> Self {
        Sjis {
            text: decode_sjis(&raw),
            raw,
        }
    }
    /// A PMM name: one length byte, then the bytes.
    pub(crate) fn read_u8_prefixed(r: &mut Reader) -> Result<Self> {
        let n = r.u8()? as usize;
        Ok(Sjis::from_raw(r.bytes(n)?.to_vec()))
    }
    pub(crate) fn write_u8_prefixed(&self, w: &mut Writer) -> Result<()> {
        let n = u8::try_from(self.raw.len()).map_err(|_| w.invalid("name longer than 255"))?;
        w.u8(n);
        w.bytes(&self.raw);
        Ok(())
    }
}

/// The two PMX text encodings, selected by the header's first global.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PmxEncoding {
    Utf16Le,
    Utf8,
}

/// A PMX string: u32 byte length, then the bytes in the header's encoding.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PmxText {
    pub raw: Vec<u8>,
    pub text: String,
}

/// Longest PMX string the C++ reader accepts.
const MAX_PMX_TEXT: u32 = 1 << 20;

impl PmxText {
    pub(crate) fn read(r: &mut Reader, enc: PmxEncoding) -> Result<Self> {
        let n = r.u32()?;
        // The C++ reader rejects odd lengths; they only make sense in UTF-8.
        if n > MAX_PMX_TEXT || (enc == PmxEncoding::Utf16Le && n % 2 != 0) {
            return Err(r.invalid("bad PMX text length"));
        }
        let raw = r.bytes(n as usize)?.to_vec();
        let coder = match enc {
            PmxEncoding::Utf16Le => UTF_16LE,
            PmxEncoding::Utf8 => UTF_8,
        };
        let text = coder.decode_without_bom_handling(&raw).0.into_owned();
        Ok(PmxText { raw, text })
    }
    pub(crate) fn write(&self, w: &mut Writer) -> Result<()> {
        w.count32(self.raw.len())?;
        w.bytes(&self.raw);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sjis_keeps_bytes_that_do_not_decode() {
        // 0x81 0x20 is not a valid cp932 pair; the raw bytes must survive.
        let s = Sjis::from_raw(vec![0x93, 0xaa, 0x81, 0x20, 0, 0x55]);
        assert_eq!(s.raw, [0x93, 0xaa, 0x81, 0x20, 0, 0x55]);
        assert!(s.text.starts_with('頭'));
        assert!(s.text.contains('\u{fffd}'));
        assert!(!s.text.contains('U'), "text stops at the NUL");
    }
}
