//! Byte-exact readers and writers for the MikuMikuDance file formats: PMD
//! and PMX models, VMD motions, VPD poses, and PMM v2 scenes.
//!
//! # Data shape
//!
//! Each format is a typed struct that keeps every field the C++ writers emit,
//! in file order, so `write(read(bytes)) == bytes` for every file that
//! reads. Integers and floats keep their bits; byte flags keep the value as
//! read, not a `bool`. A field that a flag in the file switches on or off
//! (PMX bone flags, weight types, morph kinds) is read and written only when
//! the flag says so. Sections that a file may end before (the PMD English,
//! toon and physics sections, the VMD camera to IK sections, the PMM tail)
//! are `Option`s or enums that remember where the file ended. Bytes after
//! the last section that the C++ reader ignores are kept in `trailing`.
//!
//! Strings keep their raw bytes next to the decoded text (`text`). The
//! writers emit the raw bytes, so a name that does not survive a Shift-JIS
//! round trip, or residue after the NUL of a fixed-width field, writes back
//! unchanged. PMD, VMD, VPD and PMM are Shift-JIS (cp932); PMX is UTF-16LE
//! or UTF-8 per its header.
//!
//! PMM key tracks are [`key_pool::KeyPool`]s: the C++ fixed-capacity pool
//! with the track heads at their C++ indices and the raw `previous` and
//! `next` indices of every record, because `src/io/pmm_save.cpp` writes those
//! indices into the file. The pool allocates as `kfa::AllocateFromCursor`
//! does. The reader takes only the record order the C++ writer emits.
//!
//! VPD is text. Its writer emits the MMD layout (`%f` values), so a VPD that
//! MMD or the MMD port wrote reads and writes back to the same bytes.
//!
//! Every count is checked against the C++ cap and the bytes left before
//! anything is allocated. Bad input returns [`Error`]; no input panics.

mod io;
pub mod key_pool;
pub mod pmd;
pub mod pmm;
pub mod pmx;
pub mod text;
pub mod vmd;
pub mod vpd;

use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Error {
    /// The input ends inside a field.
    Truncated { offset: usize },
    /// A value the format does not allow, at this input (or output) offset.
    Invalid { offset: usize, what: &'static str },
    /// No known signature.
    UnknownFormat,
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Truncated { offset } => write!(f, "file ends at byte {offset} inside a field"),
            Error::Invalid { offset, what } => write!(f, "byte {offset}: {what}"),
            Error::UnknownFormat => write!(f, "not a PMD, PMX, VMD, VPD or PMM file"),
        }
    }
}

impl std::error::Error for Error {}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Pmd,
    Pmx,
    Vmd,
    Vpd,
    Pmm,
}

/// The format named by the file's signature.
pub fn detect(data: &[u8]) -> Option<Kind> {
    let head = &data[..data.len().min(30)];
    if data.starts_with(b"Pmd") {
        Some(Kind::Pmd)
    } else if data.starts_with(b"PMX ") {
        Some(Kind::Pmx)
    } else if data.starts_with(b"Vocaloid Motion Data") {
        Some(Kind::Vmd)
    } else if data.starts_with(b"Vocaloid Pose Data file") {
        Some(Kind::Vpd)
    } else if head.windows(19).any(|w| w == b"Polygon Movie maker") {
        Some(Kind::Pmm)
    } else {
        None
    }
}

#[derive(Clone, Debug)]
pub enum Document {
    Pmd(Box<pmd::Pmd>),
    Pmx(pmx::Pmx),
    Vmd(vmd::Vmd),
    Vpd(vpd::Vpd),
    Pmm(Box<pmm::Pmm>),
}

impl Document {
    pub fn read(data: &[u8]) -> Result<Self, Error> {
        Ok(match detect(data).ok_or(Error::UnknownFormat)? {
            Kind::Pmd => Document::Pmd(Box::new(pmd::Pmd::read(data)?)),
            Kind::Pmx => Document::Pmx(pmx::Pmx::read(data)?),
            Kind::Vmd => Document::Vmd(vmd::Vmd::read(data)?),
            Kind::Vpd => Document::Vpd(vpd::Vpd::read(data)?),
            Kind::Pmm => Document::Pmm(Box::new(pmm::Pmm::read(data)?)),
        })
    }

    pub fn write(&self) -> Result<Vec<u8>, Error> {
        match self {
            Document::Pmd(d) => d.write(),
            Document::Pmx(d) => d.write(),
            Document::Vmd(d) => d.write(),
            Document::Vpd(d) => Ok(d.write()),
            Document::Pmm(d) => d.write(),
        }
    }
}
