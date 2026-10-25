//! Phase 1 of `LoadVsqFile`: the Standard MIDI File walk that writes the
//! text dump (`src/io/vsq_load.cpp`, "Phase 1"; `ReadBeWord` and
//! `ReadFixedString` of `src/model/model_query_helpers.cpp`).

use crate::{fmt_d, Reject, JP_KEY_MAJOR, JP_KEY_MINOR};

/// A file read one byte at a time. At end of file `_read` returns without
/// storing, so the byte variable keeps its previous value.
struct Reader<'a> {
    data: &'a [u8],
    pos: usize,
}

impl Reader<'_> {
    fn read(&mut self, byte: &mut u8) {
        if let Some(&b) = self.data.get(self.pos) {
            *byte = b;
            self.pos += 1;
        }
    }

    /// `ReadBeWord`: `n` bytes, big endian. The byte variable lives for the
    /// whole call, so a short file repeats its last byte.
    fn be_word(&mut self, n: i32) -> i32 {
        let mut acc = 0i32;
        let mut byte = 0u8;
        for _ in 0..n.max(0) {
            self.read(&mut byte);
            acc = i32::from(byte).wrapping_add(acc.wrapping_shl(8));
        }
        acc
    }

    /// `ReadFixedString`: `len` bytes, cut at the first NUL.
    fn fixed_string(&mut self, len: i32) -> Vec<u8> {
        let mut byte = 0u8;
        let mut out = Vec::new();
        for _ in 0..len.max(0) {
            self.read(&mut byte);
            out.push(byte);
        }
        out.truncate(out.iter().position(|&b| b == 0).unwrap_or(out.len()));
        out
    }
}

/// What the walk leaves behind for the later phases.
pub(crate) struct Dump {
    pub(crate) text: Vec<u8>,
    pub(crate) division: i32,
    pub(crate) tempo_count: usize,
    /// Set when the walk stopped with a message box. The text is then the
    /// part of the dump written so far.
    pub(crate) rejected: Option<Reject>,
}

fn put(out: &mut Vec<u8>, s: &str) {
    out.extend_from_slice(s.as_bytes());
}

/// Walks the SMF in `data` and writes the text dump. Nothing is checked:
/// the magic and the chunk lengths are read and dropped.
pub(crate) fn dump(data: &[u8]) -> Dump {
    let mut r = Reader { data, pos: 0 };
    let mut out = Vec::new();
    let mut tempo_count = 0usize;

    r.fixed_string(4);
    r.be_word(4);
    r.be_word(2);
    let ntracks = r.be_word(2);
    put(&mut out, &format!("[number of Track:{ntracks}]\n"));
    let division = r.be_word(2);
    put(&mut out, &format!("[UnitTime:{division}]\n\n"));

    let done = |out, tempo_count, rejected| Dump {
        text: out,
        division,
        tempo_count,
        rejected,
    };

    let mut track = 0;
    while track < ntracks {
        put(&mut out, &format!("[Track{track}]\n"));
        r.fixed_string(4);
        r.be_word(4);
        let mut time = 0i32;
        loop {
            let mut delta = r.be_word(1);
            if delta > 0x7f {
                loop {
                    let v = r.be_word(1);
                    delta = (delta - 0x80).wrapping_shl(7).wrapping_add(v);
                    if v <= 0x7f {
                        break;
                    }
                }
            }
            time = time.wrapping_add(delta);
            let status = r.be_word(1);
            match status {
                0x80..=0x9f | 0xb0..=0xbf => {
                    r.be_word(2);
                    continue;
                }
                0xf0 | 0xf7 => return done(out, tempo_count, Some(Reject::SysEx)),
                0xff => {}
                _ => return done(out, tempo_count, Some(Reject::Analysis)),
            }
            match r.be_word(1) {
                0 => {
                    r.be_word(1);
                }
                1 => {
                    let len = r.be_word(1);
                    r.fixed_string(8);
                    let text = r.fixed_string(len - 8);
                    out.extend_from_slice(&text);
                }
                2..=5 => {
                    let len = r.be_word(1);
                    r.fixed_string(len);
                }
                0x2f => {
                    if r.be_word(1) != 0 {
                        continue;
                    }
                    put(&mut out, &format!("[End of Track{track}]\n\n"));
                    track += 1;
                    break;
                }
                0x51 => {
                    r.be_word(1);
                    let tempo = r.be_word(3);
                    put(
                        &mut out,
                        &format!("[ChangeTempo time={time},tempo={tempo}]\n"),
                    );
                    tempo_count += 1;
                }
                0x58 => {
                    // The length byte and the four fields are read; the text
                    // built from them is never written.
                    let mut len = 0u8;
                    r.read(&mut len);
                    for _ in 0..4 {
                        r.be_word(1);
                    }
                }
                0x59 => {
                    r.be_word(1);
                    let sf = r.be_word(1);
                    let mi = r.be_word(1);
                    out.extend_from_slice(&fmt_d(
                        if mi == 0 { JP_KEY_MAJOR } else { JP_KEY_MINOR },
                        sf,
                    ));
                    out.push(b'\n');
                }
                _ => return done(out, tempo_count, Some(Reject::Analysis)),
            }
        }
    }
    done(out, tempo_count, None)
}
