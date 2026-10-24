//! Bounds-checked little-endian reader and the matching writer.

use crate::Error;

pub(crate) type Result<T> = std::result::Result<T, Error>;

/// A cursor over the input. Every read checks the remaining length first.
pub(crate) struct Reader<'a> {
    data: &'a [u8],
    pos: usize,
}

impl<'a> Reader<'a> {
    pub fn new(data: &'a [u8]) -> Self {
        Reader { data, pos: 0 }
    }

    pub fn remaining(&self) -> usize {
        self.data.len() - self.pos
    }

    pub fn invalid(&self, what: &'static str) -> Error {
        Error::Invalid {
            offset: self.pos,
            what,
        }
    }

    pub fn bytes(&mut self, n: usize) -> Result<&'a [u8]> {
        if n > self.remaining() {
            return Err(Error::Truncated {
                offset: self.data.len(),
            });
        }
        let out = &self.data[self.pos..self.pos + n];
        self.pos += n;
        Ok(out)
    }

    pub fn array<const N: usize>(&mut self) -> Result<[u8; N]> {
        let mut out = [0; N];
        out.copy_from_slice(self.bytes(N)?);
        Ok(out)
    }

    /// The bytes after the cursor, kept verbatim.
    pub fn rest(&mut self) -> Vec<u8> {
        let out = self.data[self.pos..].to_vec();
        self.pos = self.data.len();
        out
    }

    pub fn u8(&mut self) -> Result<u8> {
        Ok(self.array::<1>()?[0])
    }
    pub fn u16(&mut self) -> Result<u16> {
        Ok(u16::from_le_bytes(self.array()?))
    }
    pub fn i16(&mut self) -> Result<i16> {
        Ok(i16::from_le_bytes(self.array()?))
    }
    pub fn u32(&mut self) -> Result<u32> {
        Ok(u32::from_le_bytes(self.array()?))
    }
    pub fn i32(&mut self) -> Result<i32> {
        Ok(i32::from_le_bytes(self.array()?))
    }
    pub fn f32(&mut self) -> Result<f32> {
        Ok(f32::from_bits(self.u32()?))
    }
    pub fn f32s<const N: usize>(&mut self) -> Result<[f32; N]> {
        let mut out = [0.0; N];
        for v in &mut out {
            *v = self.f32()?;
        }
        Ok(out)
    }

    /// Reads `n` records of at least `min_size` bytes each. The length check
    /// runs before the allocation, so a hostile count cannot allocate more
    /// than the input could hold.
    pub fn vec<T>(
        &mut self,
        n: usize,
        min_size: usize,
        mut item: impl FnMut(&mut Self) -> Result<T>,
    ) -> Result<Vec<T>> {
        if n.saturating_mul(min_size.max(1)) > self.remaining() {
            return Err(Error::Truncated {
                offset: self.data.len(),
            });
        }
        let mut out = Vec::with_capacity(n);
        for _ in 0..n {
            out.push(item(self)?);
        }
        Ok(out)
    }

    /// A count that must not exceed `limit` (the C++ reader's cap).
    pub fn limit(&self, n: usize, limit: usize, what: &'static str) -> Result<usize> {
        if n > limit {
            return Err(self.invalid(what));
        }
        Ok(n)
    }
}

/// Little-endian output buffer.
#[derive(Default)]
pub(crate) struct Writer {
    pub out: Vec<u8>,
}

impl Writer {
    pub fn invalid(&self, what: &'static str) -> Error {
        Error::Invalid {
            offset: self.out.len(),
            what,
        }
    }
    pub fn bytes(&mut self, b: &[u8]) {
        self.out.extend_from_slice(b);
    }
    pub fn u8(&mut self, v: u8) {
        self.out.push(v);
    }
    pub fn u16(&mut self, v: u16) {
        self.bytes(&v.to_le_bytes());
    }
    pub fn i16(&mut self, v: i16) {
        self.bytes(&v.to_le_bytes());
    }
    pub fn u32(&mut self, v: u32) {
        self.bytes(&v.to_le_bytes());
    }
    pub fn i32(&mut self, v: i32) {
        self.bytes(&v.to_le_bytes());
    }
    pub fn f32(&mut self, v: f32) {
        self.u32(v.to_bits());
    }
    pub fn f32s(&mut self, v: &[f32]) {
        for &x in v {
            self.f32(x);
        }
    }
    /// A record count as a u32/i32 field; fails when it does not fit.
    pub fn count32(&mut self, n: usize) -> Result<()> {
        let n = i32::try_from(n).map_err(|_| self.invalid("count too large"))?;
        self.i32(n);
        Ok(())
    }
}
