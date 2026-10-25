//! The command language of the C++ `--mds-script` oracle
//! (`src/tools/script_parse.hpp`, `src/tools/script_mode.cpp`), mapped onto
//! [`Command`]s. `tests/fixtures/rust/script/README.md` says which handler
//! each line drives; the [`Command`] it maps to ports that handler.

use crate::{Command, Document, Error, GlobalTrack, SelectAll};
use std::collections::BTreeMap;

/// A file a save step wrote.
#[derive(Clone, Debug)]
pub struct Saved {
    pub name: String,
    pub bytes: Vec<u8>,
}

/// A document and the out directory of one script.
pub struct Runner {
    pub doc: Document,
    pub out: BTreeMap<String, Vec<u8>>,
    /// The self-shadow range edit (561), once a script typed into it.
    shadow_range: Option<String>,
    gravity_open: bool,
}

impl Default for Runner {
    fn default() -> Self {
        Runner::new()
    }
}

/// `SplitScriptWords`: spaces and tabs separate words; a quoted word may
/// hold spaces.
fn words(line: &str) -> Result<Vec<String>, String> {
    let mut out = Vec::new();
    let mut rest = line;
    loop {
        rest = rest.trim_start_matches([' ', '\t', '\r']);
        if rest.is_empty() {
            return Ok(out);
        }
        if let Some(q) = rest.strip_prefix('"') {
            let end = q.find('"').ok_or("unterminated quote")?;
            out.push(q[..end].to_string());
            rest = &q[end + 1..];
        } else {
            let end = rest.find([' ', '\t', '\r']).unwrap_or(rest.len());
            out.push(rest[..end].to_string());
            rest = &rest[end..];
        }
    }
}

/// The float pi of the edit handlers (`kPiLit`, 3.141592025756836).
const PI_LIT: f64 = 3.141592025756836;

/// The first `max - 1` characters of an edit (`GetWindowTextA(edit, buf,
/// max)`).
fn edit_text(s: &str, max: usize) -> &str {
    let n = s.char_indices().nth(max - 1).map_or(s.len(), |(i, _)| i);
    &s[..n]
}

/// `atof` of the edit text: the longest leading decimal number, else 0.
fn atof(s: &str, max: usize) -> f64 {
    let s = edit_text(s, max).trim_start();
    (1..=s.len())
        .rev()
        .filter(|&n| s.is_char_boundary(n))
        .find_map(|n| s[..n].parse::<f64>().ok())
        .unwrap_or(0.0)
}

/// `atol` of the edit text.
fn atol(s: &str, max: usize) -> i64 {
    let s = edit_text(s, max).trim_start();
    (1..=s.len())
        .rev()
        .filter(|&n| s.is_char_boundary(n))
        .find_map(|n| s[..n].parse::<i64>().ok())
        .unwrap_or(0)
}

fn e(e: Error) -> String {
    e.to_string()
}

impl Runner {
    /// The scene the application starts with.
    pub fn new() -> Runner {
        Runner {
            doc: Document::startup(),
            out: BTreeMap::new(),
            shadow_range: None,
            gravity_open: false,
        }
    }

    /// Runs one script line. `read` maps a load path as written to the file
    /// bytes. Returns the files a save wrote.
    pub fn run_line(
        &mut self,
        line: &str,
        read: &mut dyn FnMut(&str) -> Option<Vec<u8>>,
    ) -> Result<Vec<Saved>, String> {
        let w = words(line)?;
        if w.is_empty() || w[0].starts_with('#') {
            return Ok(Vec::new());
        }
        let w: Vec<&str> = w.iter().map(String::as_str).collect();
        let mut load = |p: &str| -> Result<Vec<u8>, String> {
            match p.strip_prefix("out/") {
                Some(name) => self.out.get(name).cloned(),
                None => read(p),
            }
            .ok_or_else(|| format!("input file not found: {p}"))
        };
        let cmd = match w.as_slice() {
            ["new"] => Command::NewScene,
            ["load", "pmm", p] => {
                let data = load(p)?;
                self.doc.load_scene(&data, |m| read(m)).map_err(e)?;
                return Ok(Vec::new());
            }
            ["save", "pmm", name] => {
                let bytes = self.doc.save().map_err(e)?;
                return Ok(self.saved(name, bytes));
            }
            ["select", "camera"] => Command::SelectCameraMode,
            ["frame", f] => Command::SetFrame(atol(f, 8) as u32),
            ["camera", "position", x, y, z] => {
                for (axis, v) in [x, y, z].into_iter().enumerate() {
                    let mut v = atof(v, 100);
                    if axis == 2 && self.doc.pmm.appearance.camera_parent_model >= 0 {
                        v = -v;
                    }
                    self.camera(|s| s[axis] = v as f32)?;
                }
                return Ok(Vec::new());
            }
            ["camera", "rotation", x, y, z] => {
                // `CommitEditControlTail`: pitch is the negated X.
                let x = atof(x, 100);
                self.camera(|s| s[6] = (-x * PI_LIT / 180.0) as f32)?;
                let y = atof(y, 100);
                self.camera(|s| s[7] = (y * PI_LIT / 180.0) as f32)?;
                let z = atof(z, 100);
                self.camera(|s| s[8] = (z * PI_LIT / 180.0) as f32)?;
                return Ok(Vec::new());
            }
            ["camera", "distance", d] => {
                let d = atof(d, 100);
                self.camera(|s| s[5] = (-d) as f32)?;
                return Ok(Vec::new());
            }
            ["camera", "fov", f] => {
                let f = atol(f, 8) as f32;
                let p = &self.doc.pmm;
                let mut position = [0.0; 3];
                position.copy_from_slice(&p.camera_state[..3]);
                let rotation = [p.camera_state[6], p.camera_state[7], p.camera_state[8]];
                Command::SetCamera {
                    position,
                    rotation,
                    distance: p.camera_state[5],
                    fov: f,
                    perspective: p.camera_perspective != 0,
                }
            }
            ["light", "color", r, g, b] => {
                for (i, v) in [r, g, b].into_iter().enumerate() {
                    let v = (atol(v, 8) as f64 * 0.00390625) as f32;
                    self.light(|l| l[i] = v)?;
                }
                return Ok(Vec::new());
            }
            ["light", "direction", x, y, z] => {
                for (i, v) in [x, y, z].into_iter().enumerate() {
                    let v = atof(v, 8) as f32;
                    self.light(|l| l[3 + i] = v)?;
                }
                return Ok(Vec::new());
            }
            ["shadow", "mode", m] => Command::SetSelfShadow {
                mode: m.parse().map_err(|_| "bad mode")?,
                distance: self.doc.pmm.physics_interval,
            },
            ["shadow", "range", v] => {
                self.shadow_range = Some(v.to_string());
                Command::SetSelfShadow {
                    mode: self.doc.edit.self_shadow_mode,
                    distance: ((10000.0 - atof(v, 8)) / 100000.0) as f32,
                }
            }
            ["register", "camera"] => Command::RegisterGlobalKeys(vec![GlobalTrack::Camera]),
            ["register", "light"] => Command::RegisterGlobalKeys(vec![GlobalTrack::Light]),
            ["register", "shadow"] => {
                // Button 565 reads the range edit again, as a float.
                if let Some(text) = &self.shadow_range {
                    let v = atof(text, 8) as f32;
                    let distance = ((10000.0 - f64::from(v)) / 100000.0) as f32;
                    let mode = self.doc.edit.self_shadow_mode;
                    self.doc
                        .apply(Command::SetSelfShadow { mode, distance })
                        .map_err(e)?;
                }
                Command::RegisterGlobalKeys(vec![GlobalTrack::SelfShadow])
            }
            ["gravity", "open"] => {
                self.gravity_open = true;
                return Ok(Vec::new());
            }
            ["gravity", "magnitude", m] => {
                self.gravity_dialog()?;
                Command::SetGravityChannel(0, atof(m, 256) as f32)
            }
            ["gravity", "direction", x, y, z] => {
                self.gravity_dialog()?;
                for (i, v) in [x, y, z].into_iter().enumerate() {
                    let v = atof(v, 256) as f32;
                    self.doc
                        .apply(Command::SetGravityChannel(1 + i as u8, v))
                        .map_err(e)?;
                }
                return Ok(Vec::new());
            }
            ["register", "gravity"] => {
                self.gravity_dialog()?;
                Command::RegisterGlobalKeys(vec![GlobalTrack::Gravity])
            }
            ["gravity", "close"] => {
                self.gravity_dialog()?;
                self.gravity_open = false;
                Command::CloseGravityDialog
            }
            ["select", "all", what] => Command::SelectAll(match *what {
                "bone" => SelectAll::Bone,
                "display" => SelectAll::Display,
                "morph" => SelectAll::Morph,
                "camera" => SelectAll::Camera,
                "light" => SelectAll::Light,
                "shadow" => SelectAll::SelfShadow,
                "gravity" => SelectAll::Gravity,
                "accessory" => SelectAll::Accessory,
                _ => return Err("unknown select all".into()),
            }),
            ["save", "vmd", name] => {
                let model = self.doc.selected_model();
                let bytes = crate::vmd_save::save(&self.doc.pmm, model);
                return Ok(self.saved(name, bytes));
            }
            ["load", "vmd", p] => Command::LoadMotion(load(p)?),
            ["copy"] => Command::Copy,
            ["paste"] => Command::Paste,
            ["delete"] => Command::DeleteSelectedKeys,
            ["line", op, track] => Command::FrameLine {
                morph: match *track {
                    "bone" => false,
                    "morph" => true,
                    _ => return Err("unknown line".into()),
                },
                insert: match *op {
                    "insert" => true,
                    "delete" => false,
                    _ => return Err("unknown line".into()),
                },
            },
            ["undo"] => Command::Undo,
            ["redo"] => Command::Redo,
            _ => return Err("not ported".into()),
        };
        self.doc.apply(cmd).map_err(e)?;
        Ok(Vec::new())
    }

    fn gravity_dialog(&self) -> Result<(), String> {
        if self.gravity_open {
            Ok(())
        } else {
            Err("the gravity dialog is not open (gravity open)".into())
        }
    }

    /// One commit of a camera readout edit (`CommitEditControlTail`, VA
    /// 0x0044BEF0): the other values stay.
    fn camera(&mut self, f: impl FnOnce(&mut [f32; 9])) -> Result<(), String> {
        let p = &self.doc.pmm;
        let mut s = p.camera_state;
        f(&mut s);
        let cmd = Command::SetCamera {
            position: [s[0], s[1], s[2]],
            rotation: [s[6], s[7], s[8]],
            distance: s[5],
            fov: p.settings.camera_fov,
            perspective: p.camera_perspective != 0,
        };
        self.doc.pmm.camera_state[3..5].copy_from_slice(&s[3..5]);
        self.doc.apply(cmd).map_err(e)
    }

    /// One commit of a light edit (`CommitEditControl`, VA 0x00463640).
    fn light(&mut self, f: impl FnOnce(&mut [f32; 6])) -> Result<(), String> {
        let mut l = self.doc.pmm.light_state;
        f(&mut l);
        let cmd = Command::SetLight {
            color: [l[0], l[1], l[2]],
            direction: [l[3], l[4], l[5]],
        };
        self.doc.apply(cmd).map_err(e)
    }

    fn saved(&mut self, name: &str, bytes: Vec<u8>) -> Vec<Saved> {
        self.out.insert(name.to_string(), bytes.clone());
        vec![Saved {
            name: name.to_string(),
            bytes,
        }]
    }
}
