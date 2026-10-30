//! The `.vac` wrapper read by `LoadAccessoryObject` (`accessory.cpp:462`): a text
//! file that names a `.x` file and sets the accessory's first placement.

use crate::accessory::{load_x, Accessory};
use crate::Error;
use std::path::Path;

#[derive(Clone, Debug, PartialEq)]
pub struct Vac {
    /// The second line: the `.x` file name.
    pub mesh: String,
    pub scale: f32,
    pub position: [f32; 3],
    pub rotation: [f32; 3],
    pub shadow_enabled: bool,
}

/// C `fscanf` on the bytes after the lines read so far, for the three formats used.
struct Scan<'a> {
    s: &'a [u8],
    pos: usize,
}

impl Scan<'_> {
    fn skip_ws(&mut self) {
        while self.s.get(self.pos).is_some_and(u8::is_ascii_whitespace) {
            self.pos += 1;
        }
    }
    fn float(&mut self) -> Option<f32> {
        self.skip_ws();
        let rest = &self.s[self.pos..];
        let n = rest
            .iter()
            .position(|b| !(b.is_ascii_digit() || b"+-.eE".contains(b)))
            .unwrap_or(rest.len());
        // `%f` takes the longest prefix that is a number.
        for end in (1..=n).rev() {
            if let Some(v) = std::str::from_utf8(&rest[..end])
                .ok()
                .and_then(|t| t.parse().ok())
            {
                self.pos += end;
                return Some(v);
            }
        }
        None
    }
    fn comma(&mut self) -> Option<()> {
        (self.s.get(self.pos) == Some(&b',')).then(|| self.pos += 1)
    }
    fn triple(&mut self) -> Option<[f32; 3]> {
        let x = self.float()?;
        self.comma()?;
        let y = self.float()?;
        self.comma()?;
        Some([x, y, self.float()?])
    }
    /// `fgets`: the rest of the current line, newline included.
    fn line(&mut self) -> &[u8] {
        let start = self.pos;
        while self.pos < self.s.len() {
            self.pos += 1;
            if self.s[self.pos - 1] == b'\n' {
                break;
            }
        }
        &self.s[start..self.pos]
    }
    fn int(&mut self) -> Option<i32> {
        self.skip_ws();
        let rest = &self.s[self.pos..];
        let n = rest
            .iter()
            .enumerate()
            .position(|(i, b)| !(b.is_ascii_digit() || (i == 0 && matches!(b, b'+' | b'-'))))
            .unwrap_or(rest.len());
        let v = std::str::from_utf8(&rest[..n]).ok()?.parse().ok()?;
        self.pos += n;
        Some(v)
    }
}

/// Reads the fields as the C++ does. A field `fscanf` cannot read keeps the
/// record default: scale 1, position and rotation 0, shadow on.
pub fn parse(text: &[u8]) -> Vac {
    let mut s = Scan { s: text, pos: 0 };
    s.line();
    let second = s.line().to_vec();
    let mesh = mds_formats::text::decode_sjis(second.strip_suffix(b"\n").unwrap_or(&second));
    let mesh = mesh.strip_suffix('\r').unwrap_or(&mesh).to_string();
    let mut vac = Vac {
        mesh,
        scale: 1.0,
        position: [0.0; 3],
        rotation: [0.0; 3],
        shadow_enabled: true,
    };
    // Simplification: C `fscanf` would go on reading after a failed field; this stops at
    // the first one and keeps the defaults for the rest.
    if let Some(v) = s.float() {
        vac.scale = v;
        if let Some(p) = s.triple() {
            vac.position = p;
            if let Some(r) = s.triple() {
                vac.rotation = r;
                s.line();
                s.line();
                vac.shadow_enabled = s.int().unwrap_or(0) == 0;
            }
        }
    }
    vac
}

/// Loads a `.vac`: the `.x` file next to it, with the placement of the `.vac`.
/// The C++ looks the `.x` up through `ResolveAnsiUserFile` (the `UserFile\Accessory`
/// folders); this reads it from the `.vac`'s directory.
pub fn load_vac(path: &Path) -> Result<Accessory, Error> {
    let io = |p: &Path, e: std::io::Error| Error::Io(format!("{}: {e}", p.display()));
    let text = std::fs::read(path).map_err(|e| io(path, e))?;
    let vac = parse(&text);
    let mesh_path = path.with_file_name(&vac.mesh);
    let mesh_path = if mesh_path.is_file() {
        mesh_path
    } else {
        let native = path.with_file_name(vac.mesh.replace('\\', "/"));
        mds_formats::path::resolve_path_ci(&native).unwrap_or(native)
    };
    let mut acc = load_x(&std::fs::read(&mesh_path).map_err(|e| io(&mesh_path, e))?)?;
    acc.state.scale = vac.scale;
    acc.state.position = vac.position;
    acc.state.rotation = vac.rotation;
    acc.state.shadow_enabled = vac.shadow_enabled;
    Ok(acc)
}

/// `LoadAccessoryFile` for a path: `.vac` by extension, otherwise a `.x` file.
/// `wcsstr(path, L".vac")` is a substring test in the C++, kept here.
pub fn load_file(path: &Path) -> Result<Accessory, Error> {
    if path.to_string_lossy().contains(".vac") {
        load_vac(path)
    } else {
        let data =
            std::fs::read(path).map_err(|e| Error::Io(format!("{}: {e}", path.display())))?;
        load_x(&data)
    }
}
