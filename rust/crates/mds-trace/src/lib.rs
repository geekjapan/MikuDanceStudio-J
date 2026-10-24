//! Reads two traces in trace format 1 and finds the first difference.

pub mod format;

use format::{parse_header, parse_record, Level, Record, MAX_LINE};
use std::fmt;
use std::io::{self, BufRead, Read};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Side {
    A,
    B,
}

#[derive(Debug)]
pub enum Error {
    Parse {
        side: Side,
        line: usize,
        msg: &'static str,
    },
    Io {
        side: Side,
        kind: io::ErrorKind,
    },
}

impl Error {
    pub fn side(&self) -> Side {
        match self {
            Error::Parse { side, .. } | Error::Io { side, .. } => *side,
        }
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Parse { line, msg, .. } => write!(f, "line {line}: {msg}"),
            Error::Io { kind, .. } => write!(f, "read error: {kind}"),
        }
    }
}

impl std::error::Error for Error {}

#[derive(Debug, PartialEq, Eq)]
pub enum Difference {
    Level {
        a: Level,
        b: Level,
    },
    /// The records at the same position name different tracks.
    Track {
        line: usize,
        a: Record,
        b: Record,
    },
    Field {
        a: Record,
        b: Record,
        field: usize,
    },
    /// One trace ends while the other still has a record.
    Length {
        line: usize,
        a_ended: bool,
    },
}

impl fmt::Display for Difference {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Difference::Level { a, b } => write!(f, "header: level a={a:?} b={b:?}"),
            Difference::Track { line, a, b } => write!(
                f,
                "line {line}: track differs: a=frame {} {} b=frame {} {}",
                a.frame,
                a.track(),
                b.frame,
                b.track()
            ),
            Difference::Field { a, b, field } => write!(
                f,
                "frame {} track {} field {}: a={} b={}",
                a.frame,
                a.track(),
                a.kind.fields[*field],
                a.fields[*field].text,
                b.fields[*field].text
            ),
            Difference::Length { line, a_ended } => write!(
                f,
                "line {line}: trace {} ends here, the other continues",
                if *a_ended { "a" } else { "b" }
            ),
        }
    }
}

struct Reader<R> {
    r: R,
    side: Side,
    line: usize,
}

impl<R: BufRead> Reader<R> {
    fn err(&self, msg: &'static str) -> Error {
        Error::Parse {
            side: self.side,
            line: self.line,
            msg,
        }
    }

    /// Next line without its `\n`; `None` at a clean end of input.
    fn next_line(&mut self) -> Result<Option<String>, Error> {
        let mut buf = Vec::new();
        let n = (&mut self.r)
            .take(MAX_LINE as u64 + 1)
            .read_until(b'\n', &mut buf)
            .map_err(|e| Error::Io {
                side: self.side,
                kind: e.kind(),
            })?;
        if n == 0 {
            return Ok(None);
        }
        self.line += 1;
        if buf.pop() != Some(b'\n') {
            return Err(self.err(if n > MAX_LINE {
                "line too long"
            } else {
                "truncated line (no newline at end)"
            }));
        }
        String::from_utf8(buf)
            .map(Some)
            .map_err(|_| self.err("line is not UTF-8"))
    }

    fn header(&mut self) -> Result<Level, Error> {
        match self.next_line()? {
            None => Err(Error::Parse {
                side: self.side,
                line: 1,
                msg: "empty trace",
            }),
            Some(l) => parse_header(&l).map_err(|m| self.err(m)),
        }
    }

    fn record(&mut self) -> Result<Option<Record>, Error> {
        match self.next_line()? {
            None => Ok(None),
            Some(l) => parse_record(&l).map(Some).map_err(|m| self.err(m)),
        }
    }
}

/// Compares two traces and returns the first difference, if any.
/// Each input is validated only as far as the comparison reads it.
pub fn diff(a: impl BufRead, b: impl BufRead) -> Result<Option<Difference>, Error> {
    let mut a = Reader {
        r: a,
        side: Side::A,
        line: 0,
    };
    let mut b = Reader {
        r: b,
        side: Side::B,
        line: 0,
    };
    let (la, lb) = (a.header()?, b.header()?);
    if la != lb {
        return Ok(Some(Difference::Level { a: la, b: lb }));
    }
    loop {
        let (ra, rb) = (a.record()?, b.record()?);
        let line = a.line.max(b.line);
        let (ra, rb) = match (ra, rb) {
            (None, None) => return Ok(None),
            (Some(_), None) => {
                return Ok(Some(Difference::Length {
                    line,
                    a_ended: false,
                }))
            }
            (None, Some(_)) => {
                return Ok(Some(Difference::Length {
                    line,
                    a_ended: true,
                }))
            }
            (Some(x), Some(y)) => (x, y),
        };
        if (ra.frame, ra.kind, &ra.indices) != (rb.frame, rb.kind, &rb.indices) {
            return Ok(Some(Difference::Track { line, a: ra, b: rb }));
        }
        if let Some(field) = (0..ra.fields.len()).find(|&i| ra.fields[i].bits != rb.fields[i].bits)
        {
            return Ok(Some(Difference::Field {
                a: ra,
                b: rb,
                field,
            }));
        }
    }
}
