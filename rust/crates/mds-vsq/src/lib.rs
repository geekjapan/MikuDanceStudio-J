//! VSQ lip sync: a VOCALOID sequence file to the lip sync text and the
//! morph keys of the vowel faces.
//!
//! A port of `LoadVsqFile` in `src/io/vsq_load.cpp`, the handler of menu 224
//! (`MDS_CMD_LOAD_LIP_SYNC` in `src/window/command_file_menu.cpp`) and of a
//! dropped `.vsq` file (`src/window/ui_dropfiles.cpp`). Both pass only the
//! path; the active model supplies the morph names. The drop path first
//! refuses camera mode with its own message box, which belongs to the caller.
//!
//! The C++ writes the SMF as text, then reads that text back with `fgets`
//! and `strstr` to find the tempo changes and the notes, then writes the
//! lip sync lines over the same file. This port keeps that route, because the
//! scans decide what a file means: a line over 255 bytes is read in pieces,
//! a section out of order is not found, and a missing line ends in a loop
//! that never returns or a null write. [`Stop`] reports those outcomes.
//! `tests/dumps.rs` compares every fixture of `tests/fixtures/rust/vsq` with
//! the dump of `tools/vsq_check`, which links the real C++.
//!
//! Left to the caller, which has the document: opening and naming the files
//! ([`txt_path`]), the message boxes ([`Reject::message`]), clearing the
//! allocated marks of the three key pools before the keys are registered,
//! registering [`LipSync::keys`] (the C++ sets the morph value to the weight
//! and calls `RegisterMorphKeyCurrent` for each, in order), and the frame
//! epilogue for [`LipSync::final_frame`]: the current frame, the frame edit
//! box, the seek, and the timeline start.
//!
//! The C++ opens its files in Windows text mode. The text this crate returns
//! has `\n` only; on Windows the file holds `\r\n` and a `\r` in the data
//! reaches the scans.

mod cfile;
mod smf;

use cfile::{atoi, sprintf_into, Line, Lines};

pub(crate) const JP_SYSEX: &[u8] = b"SysEx\x83C\x83x\x83\x93\x83g\x82\xaa\x82\xa0\x82\xe8\x82\xdc\x82\xb7\x81B\x82\xa8\x8e\xe8\x8f\xe3\x82\xb0\x81_(^o^)\x81_";
pub(crate) const JP_CAPTION: &[u8] = b"vsq\x89\xf0\x90\xcd";
pub(crate) const JP_ANALYSIS: &[u8] =
    b"vsq\x89\xf0\x90\xcd\x83G\x83\x89\x81[\x94\xad\x90\xb6\x81I\x81I";
pub(crate) const JP_NO_A: &[u8] = b"\x82\xb1\x82\xcc\x83\x82\x83f\x83\x8b\x82\xcc\x95\x5c\x8f\xee\x82\xc9\x81h\x82\xa0\x81h\x82\xcc\x8c`\x82\xaa\x82\xc8\x82\xa2\x88\xd7\x0a\x8e\xa9\x93\xae\x83\x8a\x83b\x83v\x83V\x83\x93\x83N\x82\xcd\x82\xc5\x82\xab\x82\xdc\x82\xb9\x82\xf1";
pub(crate) const JP_NO_I: &[u8] = b"\x82\xb1\x82\xcc\x83\x82\x83f\x83\x8b\x82\xcc\x95\x5c\x8f\xee\x82\xc9\x81h\x82\xa2\x81h\x82\xcc\x8c`\x82\xaa\x82\xc8\x82\xa2\x88\xd7\x0a\x8e\xa9\x93\xae\x83\x8a\x83b\x83v\x83V\x83\x93\x83N\x82\xcd\x82\xc5\x82\xab\x82\xdc\x82\xb9\x82\xf1";
pub(crate) const JP_NO_U: &[u8] = b"\x82\xb1\x82\xcc\x83\x82\x83f\x83\x8b\x82\xcc\x95\x5c\x8f\xee\x82\xc9\x81h\x82\xa4\x81h\x82\xcc\x8c`\x82\xaa\x82\xc8\x82\xa2\x88\xd7\x0a\x8e\xa9\x93\xae\x83\x8a\x83b\x83v\x83V\x83\x93\x83N\x82\xcd\x82\xc5\x82\xab\x82\xdc\x82\xb9\x82\xf1";
pub(crate) const JP_NO_O: &[u8] = b"\x82\xb1\x82\xcc\x83\x82\x83f\x83\x8b\x82\xcc\x95\x5c\x8f\xee\x82\xc9\x81h\x82\xa8\x81h\x82\xcc\x8c`\x82\xaa\x82\xc8\x82\xa2\x88\xd7\x0a\x8e\xa9\x93\xae\x83\x8a\x83b\x83v\x83V\x83\x93\x83N\x82\xcd\x82\xc5\x82\xab\x82\xdc\x82\xb9\x82\xf1";
pub(crate) const JP_KEY_MAJOR: &[u8] =
    b"\x83L\x81[(\x92\xb2) \x81\x94(\x81\xf3)\x82\xcc\x90\x94:%d \x92\xb7\x92\xb2";
pub(crate) const JP_KEY_MINOR: &[u8] =
    b"\x83L\x81[(\x92\xb2) \x81\x94(\x81\xf3)\x82\xcc\x90\x94:%d \x92Z\x92\xb2";

/// The four vowel faces a model must carry.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Face {
    A,
    I,
    U,
    O,
}

impl Face {
    /// The morph name, "あ", "い", "う" or "お".
    pub fn name(self) -> &'static str {
        match self {
            Face::A => "あ",
            Face::I => "い",
            Face::U => "う",
            Face::O => "お",
        }
    }

    /// Shift-JIS of [`Face::name`] and a NUL: the model compares three bytes.
    fn needle(self) -> [u8; 3] {
        [
            0x82,
            match self {
                Face::A => 0xa0,
                Face::I => 0xa2,
                Face::U => 0xa4,
                Face::O => 0xa8,
            },
            0,
        ]
    }
}

/// One morph key to register: the face's weight at a frame. `morph` is the
/// index in the model's morph table, the first one named like the face.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Key {
    pub frame: i32,
    pub morph: usize,
    pub face: Face,
    pub weight: f32,
}

/// A load that reached the end.
#[derive(Clone, Debug, PartialEq)]
pub struct LipSync {
    /// In registration order. The C++ registers each key at the current
    /// frame of the face's morph, so the last weight set on a face is 0.
    pub keys: Vec<Key>,
    /// `(int)(end of the last note * 30)`, the new current frame. None when
    /// the file has no notes and the frame stays.
    pub final_frame: Option<i32>,
}

/// A load that ended with a message box.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Reject {
    /// A SysEx event in a track. The box is Japanese in both languages.
    SysEx,
    /// A status byte or meta type the walk has no case for.
    Analysis,
    /// The model has no morph named like the face, or no morphs at all
    /// (reported as the face A).
    NoFace(Face),
}

impl Reject {
    /// The text and the caption of the message box, in Shift-JIS.
    pub fn message(self, english: bool) -> (&'static [u8], &'static [u8]) {
        match self {
            Reject::SysEx => (JP_SYSEX, JP_CAPTION),
            Reject::Analysis if english => (b"vsq analysis error!!", b"vsq analysis"),
            Reject::Analysis => (JP_ANALYSIS, JP_CAPTION),
            Reject::NoFace(face) => (
                match (face, english) {
                    (Face::A, true) => {
                        b"Cannot Lipsync because this model has not facial data of 'a'!!"
                    }
                    (Face::I, true) => {
                        b"Cannot Lipsync because this model has not facial data of 'i'!!"
                    }
                    (Face::U, true) => {
                        b"Cannot Lipsync because this model has not facial data of 'u'!!"
                    }
                    (Face::O, true) => {
                        b"Cannot Lipsync because this model has not facial data of 'o'!!"
                    }
                    (Face::A, false) => JP_NO_A,
                    (Face::I, false) => JP_NO_I,
                    (Face::U, false) => JP_NO_U,
                    (Face::O, false) => JP_NO_O,
                },
                if english { b"lipsync" } else { JP_CAPTION },
            ),
        }
    }
}

/// Why a load did not reach the end.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Stop {
    /// A message box and a return.
    Rejected(Reject),
    /// A scan that never ends: a line it looks for is not in the file.
    Hang,
    /// A null pointer write or a CRT parameter failure.
    Fault(&'static str),
}

/// What a load leaves behind.
#[derive(Clone, Debug, PartialEq)]
pub struct Run {
    /// The sibling `.txt` file as the load leaves it: the lip sync lines
    /// once they are written, otherwise the dump of the SMF.
    pub txt: Vec<u8>,
    pub outcome: Result<LipSync, Stop>,
}

/// The path of the `.txt` file for a `.vsq` path: the first `.vsq` becomes
/// `.txt`, case sensitive. The C++ writes through a null pointer when there
/// is none, so None here.
pub fn txt_path(vsq_path: &str) -> Option<String> {
    let at = vsq_path.find(".vsq")?;
    Some(format!("{}.txt{}", &vsq_path[..at], &vsq_path[at + 4..]))
}

/// `%d` in one of the constants above.
fn fmt_d(fmt: &[u8], v: i32) -> Vec<u8> {
    let at = fmt.windows(2).position(|w| w == b"%d").unwrap_or(fmt.len());
    let mut out = fmt[..at].to_vec();
    out.extend_from_slice(v.to_string().as_bytes());
    out.extend_from_slice(fmt.get(at + 2..).unwrap_or(&[]));
    out
}

/// One note of the sequence (`VsqEvent`, 0x24 bytes in the C++).
#[derive(Default)]
struct Event {
    consonant: [u8; 6],
    vowel: u8,
    token: [u8; 9],
    start: f32,
    end: f32,
    handle: [u8; 10],
}

fn cstr(b: &[u8]) -> &[u8] {
    &b[..b.iter().position(|&c| c == 0).unwrap_or(b.len())]
}

/// Loads `vsq`, a VSQ file, for a model whose morph names are `morphs`.
pub fn lip_sync(vsq: &[u8], morphs: &[&[u8]]) -> Run {
    let dump = smf::dump(vsq);
    if let Some(reject) = dump.rejected {
        return Run {
            txt: dump.text,
            outcome: Err(Stop::Rejected(reject)),
        };
    }
    match read_events(&dump) {
        Ok(events) => Run {
            txt: lines_text(&events),
            outcome: register(&events, morphs),
        },
        Err(stop) => Run {
            txt: dump.text,
            outcome: Err(stop),
        },
    }
}

/// Phases 2 to 4: tempo table, note records, seconds and phonemes.
fn read_events(dump: &smf::Dump) -> Result<Vec<Event>, Stop> {
    let mut line = Line::new();

    let mut rd = Lines::new(&dump.text);
    let mut tempos: Vec<(i32, i32)> = Vec::new();
    for _ in 0..dump.tempo_count {
        rd.fgets(&mut line);
        rd.seek(&mut line, b"[ChangeTempo time=")?;
        let fault = Stop::Fault("tempo line");
        let p = line.find(0, b"=").ok_or(fault)? + 1;
        let q = line.find(p, b",").ok_or(fault)?;
        line.set(q, 0);
        let time = atoi(line.cstr(p));
        let p2 = line.find(q + 1, b"=").ok_or(fault)? + 1;
        let q2 = line.find(p2, b"]").ok_or(fault)?;
        line.set(q2, 0);
        tempos.push((time, atoi(line.cstr(p2))));
    }

    rd.seek(&mut line, b"[EventList]")?;
    let mut count = 0usize;
    rd.fgets(&mut line);
    rd.fgets(&mut line);
    if line.contains(b"=ID#") {
        loop {
            count += 1;
            let got = rd.fgets(&mut line);
            if !line.contains(b"=ID#") {
                break;
            }
            if !got {
                return Err(Stop::Hang);
            }
        }
    }

    let mut events: Vec<Event> = (0..count).map(|_| Event::default()).collect();
    let mut rd = Lines::new(&dump.text);
    rd.seek(&mut line, b"[EventList]")?;
    rd.fgets(&mut line);

    for ev in &mut events {
        rd.fgets(&mut line);
        let p = line.find(0, b"=").ok_or(Stop::Fault("tick line"))?;
        line.set(p, 0);
        ev.start = atoi(line.cstr(0)) as f32;
    }
    for (i, ev) in events.iter_mut().enumerate() {
        let id = format!("[ID#{:04}]", i + 1);
        rd.seek(&mut line, id.as_bytes())?;
        rd.seek(&mut line, b"Length=")?;
        let p = line.find(0, b"=").ok_or(Stop::Fault("length line"))?;
        ev.end = atoi(line.cstr(p + 1)) as f32;
        rd.seek(&mut line, b"LyricHandle=")?;
        let p = line.find(0, b"=").ok_or(Stop::Fault("handle line"))?;
        sprintf_into(&mut ev.handle, 10, line.cstr(p + 1))?;
        ev.handle[6] = 0;
    }

    for ev in &mut events {
        rd.seek(&mut line, cstr(&ev.handle))?;
        rd.fgets(&mut line);
        let fault = Stop::Fault("lyric line");
        let m = line.find(0, b"\",\"").ok_or(fault)?;
        line.set(m, 0);
        let quote = line.find(0, b"\"").ok_or(fault)?;
        sprintf_into(&mut ev.token, 8, line.cstr(quote + 1))?;

        if line.at(m + 4) == b'"' {
            ev.consonant[0] = 0;
            ev.vowel = line.at(m + 3);
        } else if line.at(m + 4) == b'\\' {
            if line.at(m + 5) == b' ' {
                line.set(m + 5, 0);
                sprintf_into(&mut ev.consonant, 6, line.cstr(m + 3))?;
                ev.vowel = line.at(m + 6);
            } else {
                ev.consonant[0] = 0;
                ev.vowel = b'N';
            }
        } else if let Some(space) = line.find(m + 1, b" ") {
            line.set(space, 0);
            sprintf_into(&mut ev.consonant, 6, line.cstr(m + 3))?;
            ev.vowel = line.at(space + 1);
        } else {
            ev.consonant[0] = 0;
            ev.vowel = b'N';
        }
        if ev.vowel == b'M' {
            ev.vowel = b'u';
        }
    }

    to_seconds(&mut events, &tempos, dump.division)?;
    Ok(events)
}

/// Replacements for a consonant, by vowel a, i, u, o.
const VOWEL_CLASSES: [(&[u8], [&[u8]; 4]); 11] = [
    (b"k'", [b"K", b"k", b"K", b"K"]),
    (b"S", [b"S", b"s", b"S", b"S"]),
    (b"tS", [b"T", b"t", b"T", b"T"]),
    (b"J", [b"N", b"n", b"N", b"N"]),
    (b"C", [b"H", b"h", b"H", b"H"]),
    (b"m'", [b"M", b"m", b"M", b"M"]),
    (b"4'", [b"R", b"r", b"R", b"R"]),
    (b"g'", [b"G", b"g", b"G", b"G"]),
    (b"dZ", [b"Z", b"z", b"Z", b"Z"]),
    (b"b'", [b"B", b"b", b"B", b"B"]),
    (b"p'", [b"P", b"p", b"P", b"P"]),
];
const PLAIN_CLASSES: [(&[u8], &[u8]); 5] = [
    (b"4", b"r"),
    (b"j", b"y"),
    (b"p\\", b"h"),
    (b"dz", b"z"),
    (b"ts", b"t"),
];

const MICRO: f64 = 9.999999974752427e-07;

/// One tempo segment, rounded to a float on each store.
fn segment(sec: f32, ticks: i32, xdiv: f32, tempo: i32) -> f32 {
    (f64::from(sec) + f64::from(ticks) / f64::from(xdiv) * f64::from(tempo) * MICRO) as f32
}

/// Phase 4: ticks to seconds through the tempo table, then the consonant
/// classes. The table walk keeps the C++ arithmetic: a crossed segment is
/// added with the current entry's tempo, and the tick left over is reduced
/// by the next entry's absolute time.
fn to_seconds(events: &mut [Event], tempos: &[(i32, i32)], division: i32) -> Result<(), Stop> {
    let xdiv = division as f32;
    for ev in events.iter_mut() {
        let mut tick = ev.start as i32;
        let mut sec = 0.0f32;
        let mut ci = 0usize;
        while !tempos.is_empty() {
            if ci + 1 == tempos.len() || tick <= tempos[ci + 1].0 {
                sec = segment(sec, tick, xdiv, tempos[ci].1);
                break;
            }
            let t = tempos[ci + 1].0;
            sec = segment(sec, t, xdiv, tempos[ci].1);
            tick = tick.wrapping_sub(t);
            ci += 1;
        }
        ev.start = sec;
        // With no tempo the C++ reads the block malloc(0) returned.
        let tempo = tempos.get(ci).ok_or(Stop::Fault("no tempo"))?.1;
        let len = ev.end;
        ev.end = sec + (MICRO * (f64::from(tempo) * (f64::from(len) / f64::from(xdiv)))) as f32;

        for (needle, to) in VOWEL_CLASSES {
            if cstr(&ev.consonant) == needle {
                let pick = match ev.vowel {
                    b'a' => Some(to[0]),
                    b'i' => Some(to[1]),
                    b'u' => Some(to[2]),
                    b'o' => Some(to[3]),
                    _ => None,
                };
                if let Some(s) = pick {
                    set_consonant(&mut ev.consonant, s);
                }
            }
        }
        for (needle, to) in PLAIN_CLASSES {
            if cstr(&ev.consonant) == needle {
                set_consonant(&mut ev.consonant, to);
            }
        }
        if ev.vowel == b'm' || ev.vowel == b'N' {
            ev.vowel = b'n';
        }
    }
    Ok(())
}

fn set_consonant(dst: &mut [u8; 6], s: &[u8]) {
    dst[..s.len()].copy_from_slice(s);
    dst[s.len()] = 0;
}

/// Phase 5: `"%7.3f -%7.3f   %-4s %1s %c"` per note. The `%c` of a NUL ends
/// the C string there.
fn lines_text(events: &[Event]) -> Vec<u8> {
    let mut out = Vec::new();
    for ev in events {
        let head = format!("{:7.3} -{:7.3}   ", f64::from(ev.start), f64::from(ev.end));
        out.extend_from_slice(head.as_bytes());
        let token = cstr(&ev.token);
        out.extend_from_slice(token);
        out.resize(out.len() + 4usize.saturating_sub(token.len()), b' ');
        out.push(b' ');
        let consonant = cstr(&ev.consonant);
        out.extend_from_slice(consonant);
        if consonant.is_empty() {
            out.push(b' ');
        }
        out.push(b' ');
        if ev.vowel != 0 {
            out.push(ev.vowel);
        }
        out.push(b'\n');
    }
    out
}

/// Phase 6 and the end of phase 7: find the faces, make the keys.
fn register(events: &[Event], morphs: &[&[u8]]) -> Result<LipSync, Stop> {
    let find = |face: Face| {
        let want = face.needle();
        morphs
            .iter()
            .position(|name| (0..3).all(|i| name.get(i).copied().unwrap_or(0) == want[i]))
            .ok_or(Stop::Rejected(Reject::NoFace(face)))
    };
    let (a, i, u, o) = (
        find(Face::A)?,
        find(Face::I)?,
        find(Face::U)?,
        find(Face::O)?,
    );

    let mut keys = Vec::new();
    for ev in events {
        let vowel = if ev.vowel == b'h' {
            ev.consonant[0]
        } else {
            ev.vowel
        };
        let (start, end) = (f64::from(ev.start), f64::from(ev.end));
        let frames = [
            -2 - (start * -30.0) as i32,
            (start * 30.0) as i32,
            -2 - (end * -30.0) as i32,
            (end * 30.0) as i32,
        ];
        let mut shape = |faces: &[(usize, Face, f32)]| {
            for (n, &frame) in frames.iter().enumerate() {
                for &(morph, face, peak) in faces {
                    let weight = if n == 0 || n == 3 { 0.0 } else { peak };
                    keys.push(Key {
                        frame,
                        morph,
                        face,
                        weight,
                    });
                }
            }
        };
        match vowel {
            b'a' => shape(&[(a, Face::A, 0.7)]),
            b'i' => shape(&[(i, Face::I, 0.6)]),
            b'u' => shape(&[(u, Face::U, 1.0)]),
            b'e' => shape(&[(a, Face::A, 0.5), (i, Face::I, 0.3)]),
            b'o' => shape(&[(o, Face::O, 1.0)]),
            _ => {}
        }
    }
    let final_frame = events.last().map(|ev| (f64::from(ev.end) * 30.0) as i32);
    Ok(LipSync { keys, final_frame })
}
