//! The C library behavior `LoadVsqFile` leans on: a NUL-terminated line
//! buffer that keeps stale bytes, `fgets`, `strstr`, `atoi`, and the
//! `sprintf_s` whose format argument is data.

use crate::Stop;

/// `fgets(line, 0x100, f)` reads at most this many bytes.
const LINE: usize = 0x100;

/// The 0x100-byte `line` buffer shared by every scan. It starts zeroed,
/// `fgets` leaves the bytes behind the terminator as they were, and a
/// stored NUL ends the C string early.
pub(crate) struct Line {
    buf: [u8; LINE],
}

impl Line {
    pub(crate) fn new() -> Self {
        Line { buf: [0; LINE] }
    }

    /// Byte `i`, zero past the buffer.
    pub(crate) fn at(&self, i: usize) -> u8 {
        self.buf.get(i).copied().unwrap_or(0)
    }

    pub(crate) fn set(&mut self, i: usize, b: u8) {
        if let Some(slot) = self.buf.get_mut(i) {
            *slot = b;
        }
    }

    /// The C string starting at `from`.
    pub(crate) fn cstr(&self, from: usize) -> &[u8] {
        let tail = self.buf.get(from..).unwrap_or(&[]);
        &tail[..tail.iter().position(|&b| b == 0).unwrap_or(tail.len())]
    }

    /// `strstr(line + from, needle)` as an index into the buffer.
    pub(crate) fn find(&self, from: usize, needle: &[u8]) -> Option<usize> {
        let hay = self.cstr(from);
        if needle.is_empty() {
            return Some(from);
        }
        hay.windows(needle.len())
            .position(|w| w == needle)
            .map(|p| from + p)
    }

    pub(crate) fn contains(&self, needle: &[u8]) -> bool {
        self.find(0, needle).is_some()
    }
}

/// A file opened for reading, line by line.
pub(crate) struct Lines<'a> {
    data: &'a [u8],
    pos: usize,
}

impl<'a> Lines<'a> {
    pub(crate) fn new(data: &'a [u8]) -> Self {
        Lines { data, pos: 0 }
    }

    /// `fgets(line, 0x100, f)`. False at end of file, when the buffer is
    /// left as it was.
    pub(crate) fn fgets(&mut self, line: &mut Line) -> bool {
        let rest = &self.data[self.pos..];
        let limit = rest.len().min(LINE - 1);
        let n = match rest[..limit].iter().position(|&b| b == b'\n') {
            Some(i) => i + 1,
            None => limit,
        };
        if n == 0 {
            return false;
        }
        line.buf[..n].copy_from_slice(&rest[..n]);
        line.buf[n] = 0;
        self.pos += n;
        true
    }

    /// `do { fgets } while (strstr(line, needle) == NULL)`. At end of file
    /// the line stops changing, so a miss there is a loop that never ends.
    pub(crate) fn scan(&mut self, line: &mut Line, needle: &[u8]) -> Result<(), Stop> {
        loop {
            let got = self.fgets(line);
            if line.contains(needle) {
                return Ok(());
            }
            if !got {
                return Err(Stop::Hang);
            }
        }
    }

    /// `if (strstr(line, needle) == NULL) do { fgets } while (...)`.
    pub(crate) fn seek(&mut self, line: &mut Line, needle: &[u8]) -> Result<(), Stop> {
        if line.contains(needle) {
            Ok(())
        } else {
            self.scan(line, needle)
        }
    }
}

/// `atoi`: leading blanks, a sign, digits; the rest is ignored.
pub(crate) fn atoi(s: &[u8]) -> i32 {
    let mut i = 0;
    while s.get(i).is_some_and(|b| matches!(b, b' ' | b'\t'..=b'\r')) {
        i += 1;
    }
    let neg = match s.get(i) {
        Some(b'-') => {
            i += 1;
            true
        }
        Some(b'+') => {
            i += 1;
            false
        }
        _ => false,
    };
    let mut v: i64 = 0;
    while let Some(d) = s.get(i).filter(|b| b.is_ascii_digit()) {
        v = v.saturating_mul(10).saturating_add(i64::from(d - b'0'));
        i += 1;
    }
    (if neg { -v } else { v }) as i32
}

/// `sprintf_s(dst, cap, fmt)` with `fmt` taken from the file. `%%` is the
/// only directive with a defined result here; any other `%` has no argument
/// to read, and a result that does not fit makes the CRT end the process.
pub(crate) fn sprintf_into(dst: &mut [u8], cap: usize, fmt: &[u8]) -> Result<(), Stop> {
    let mut out = Vec::with_capacity(fmt.len());
    let mut it = fmt.iter();
    while let Some(&b) = it.next() {
        if b != b'%' {
            out.push(b);
        } else if it.next() == Some(&b'%') {
            out.push(b'%');
        } else {
            return Err(Stop::Fault("format directive without an argument"));
        }
    }
    if out.len() >= cap {
        return Err(Stop::Fault("sprintf_s overflow"));
    }
    dst[..out.len()].copy_from_slice(&out);
    dst[out.len()] = 0;
    Ok(())
}
