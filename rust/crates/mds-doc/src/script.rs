//! The command language of the C++ `--mds-script` oracle
//! (`src/tools/script_parse.hpp`, `src/tools/script_mode.cpp`), mapped onto
//! [`Command`]s. `tests/fixtures/rust/script/README.md` says which handler
//! each line drives; the [`Command`] it maps to ports that handler.

mod dialogs;
mod physics_dialog;

use crate::frame::FrameLoop;
use crate::{Command, Document, Error, GlobalTrack, PhysicsField, SelectAll, ViewOption};
use dialogs::{AccessoryOrderDialog, EnglishDialog, ModelOrderDialog, OutsideParentDialog};
use physics_dialog::PhysicsDialog;
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
    /// The dialog the `dialog` lines drive, while it is open.
    dialog: Option<Dialog>,
    frames: FrameLoop,
}

/// The dialogs of the `... open` commands.
enum Dialog {
    /// Menu 262, modeless.
    Physics(PhysicsDialog),
    /// Menu 259, modeless.
    English(EnglishDialog),
    /// Menus 288 and 289, modal.
    ModelOrder(ModelOrderDialog),
    /// Menu 249, modal.
    AccessoryOrder(AccessoryOrderDialog),
    /// Button 442, modal.
    OutsideParent(OutsideParentDialog),
}

impl Dialog {
    /// The frame loop does not run while a modal dialog is up.
    fn modal(&self) -> bool {
        matches!(
            self,
            Dialog::ModelOrder(_) | Dialog::AccessoryOrder(_) | Dialog::OutsideParent(_)
        )
    }
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

use crate::PI_LIT;

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

/// A morph-panel lane: 0 eyebrow, 1 eye, 2 lip, 3 other.
fn lane_of(s: &str) -> Result<u8, String> {
    s.parse()
        .ok()
        .filter(|&l| l < 4)
        .ok_or_else(|| format!("bad lane {s}"))
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
            dialog: None,
            frames: FrameLoop::default(),
        }
    }

    /// Runs one script line, then the two `FrameDriver` pumps of 1/30 s
    /// the C++ runner runs after every step ([`FrameLoop`]). `read` maps a
    /// load path as written to the file bytes. Returns the files a save
    /// wrote.
    pub fn run_line(
        &mut self,
        line: &str,
        read: &mut dyn FnMut(&str) -> Option<Vec<u8>>,
    ) -> Result<Vec<Saved>, String> {
        self.doc.edit.reported = None;
        let saved = self.step(line, read)?;
        let modal = self.dialog.as_ref().is_some_and(Dialog::modal);
        if !modal && !words(line)?.first().is_none_or(|w| w.starts_with('#')) {
            self.pump(read)?;
        }
        Ok(saved)
    }

    /// The two `FrameDriver` pumps of 1/30 s that follow every step, for a
    /// caller that edited [`Runner::doc`] itself.
    pub fn pump(&mut self, read: &mut dyn FnMut(&str) -> Option<Vec<u8>>) -> Result<(), String> {
        for _ in 0..2 {
            let read = |p: &str| read(p).ok_or_else(|| format!("model file not found: {p}"));
            self.frames.pump(&mut self.doc, 1.0 / 30.0, read)?;
        }
        Ok(())
    }

    fn step(
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
            ["save", "vpd", name] => {
                let bytes = self.doc.save_pose().map_err(e)?;
                return Ok(self.saved(name, bytes));
            }
            ["save", "pmd", name] => {
                // The C++ runner answers the save dialog with `.\<name>`
                // (script3/README.md, "Saved PMDs").
                let bytes = self.doc.save_pmd(&format!(".\\{name}")).map_err(e)?;
                return Ok(self.saved(name, bytes));
            }
            ["load", "vpd", p] => Command::LoadPose(load(p)?),
            ["select", "model", name] => {
                let m = self
                    .doc
                    .pmm
                    .models
                    .iter()
                    .find(|m| m.name.text.eq_ignore_ascii_case(name))
                    .ok_or_else(|| format!("no model {name}"))?;
                Command::SelectModel(m.slot)
            }
            ["load", "model", p] => Command::LoadModel {
                path: p.to_string(),
                data: load(p)?,
            },
            ["select", "bone", name] => {
                // `SelectDisplayBone`: that bone only.
                let m = self.doc.selected_model().ok_or("no model selected")?;
                let b = m
                    .bone_names
                    .iter()
                    .position(|n| n.text == *name)
                    .ok_or_else(|| format!("the selected model has no bone {name}"))?;
                Command::SelectBones(vec![b as u32])
            }
            ["bone", what @ ("position" | "rotation"), x, y, z] => {
                let base = if *what == "position" { 0 } else { 3 };
                for (i, v) in [x, y, z].into_iter().enumerate() {
                    let cmd = Command::BoneReadoutEdit {
                        axis: base + i as u8,
                        value: atof(v, 100),
                    };
                    self.doc.apply(cmd).map_err(e)?;
                }
                return Ok(Vec::new());
            }
            ["register", "bone"] => Command::RegisterBoneKeys,
            ["register", "display"] => Command::RegisterDisplayKey,
            ["load", "accessory", p] if p.contains(".vac") => {
                // `LoadAccessoryObject` looks for the mesh next to the `.vac`.
                let vac = load(p)?;
                let name = mds_formats::text::decode_sjis(&crate::vac_mesh_name(&vac));
                let dir = p.rsplit_once('\\').map_or("", |(d, _)| d);
                let mesh_path = format!("{dir}\\{name}");
                Command::LoadVac {
                    path: p.to_string(),
                    mesh: load(&mesh_path)?,
                    vac,
                    mesh_path,
                }
            }
            ["load", "accessory", p] => Command::LoadAccessory {
                path: p.to_string(),
                data: load(p)?,
            },
            ["load", "wav", p] => Command::LoadWave {
                path: p.to_string(),
                data: load(p)?,
            },
            ["select", "accessory", name] => {
                let a = self
                    .doc
                    .pmm
                    .accessories
                    .iter()
                    .find(|a| a.list_name.text.eq_ignore_ascii_case(name))
                    .ok_or_else(|| format!("no accessory {name}"))?;
                Command::SelectAccessory(a.slot)
            }
            ["accessory", what @ ("position" | "rotation"), x, y, z] => {
                let base = if *what == "position" { 0 } else { 3 };
                for (i, v) in [x, y, z].into_iter().enumerate() {
                    let cmd = Command::AccessoryEdit {
                        field: base + i as u8,
                        value: atof(v, 8),
                    };
                    self.doc.apply(cmd).map_err(e)?;
                }
                return Ok(Vec::new());
            }
            ["accessory", "scale", v] => Command::AccessoryEdit {
                field: 6,
                value: atof(v, 8),
            },
            ["accessory", "opacity", v] => Command::AccessoryEdit {
                field: 7,
                value: atof(v, 8),
            },
            ["accessory", "parent", model, bone] => {
                let slot = if *model == "ground" {
                    None
                } else {
                    let m = self
                        .doc
                        .pmm
                        .models
                        .iter()
                        .find(|m| m.name.text.eq_ignore_ascii_case(model))
                        .ok_or_else(|| format!("no model {model}"))?;
                    Some(m.slot)
                };
                self.doc
                    .apply(Command::SetAccessoryParentModel(slot))
                    .map_err(e)?;
                if *bone == "-" {
                    return Ok(Vec::new());
                }
                let m = slot
                    .and_then(|s| self.doc.pmm.models.iter().find(|m| m.slot == s))
                    .ok_or("a parent bone without a parent model")?;
                let b = m
                    .bone_names
                    .iter()
                    .position(|n| n.text == *bone)
                    .ok_or_else(|| format!("no bone {bone}"))?;
                Command::SetAccessoryParentBone(b as u32)
            }
            ["register", "accessory"] => Command::RegisterGlobalKeys(vec![GlobalTrack::Accessory(
                self.doc.pmm.selected_accessory_slot,
            )]),
            ["select", "morph", lane, name] => {
                let lane = lane_of(lane)?;
                Command::SelectMorphLane {
                    lane,
                    morph: self.lane_morph(lane, name)?,
                }
            }
            ["morph", lane, v] => {
                // Edits 506/511/516/521 (`CommitEditControl`): the lane's
                // selected morph, if any.
                let lane = lane_of(lane)?;
                let m = self.doc.selected_model().ok_or("no model selected")?;
                let morph = m.selection.selected_morphs[usize::from(lane)];
                if morph < 0 {
                    return Ok(Vec::new());
                }
                Command::SetMorph {
                    morph: morph as u32,
                    value: atof(v, 8) as f32,
                }
            }
            ["register", "morph", lane] => {
                let lane = lane_of(lane)?;
                let m = self.doc.selected_model().ok_or("no model selected")?;
                Command::RegisterMorphKey(m.selection.selected_morphs[usize::from(lane)])
            }
            ["load", "vmd", p] => Command::LoadMotion(load(p)?),
            ["copy"] => Command::Copy,
            ["paste"] => Command::Paste,
            ["paste", "reverse"] => Command::PasteMirrored,
            ["paste", "different"] => Command::PasteToSelectedBone,
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
            ["bias", x, y, z] => Command::CenterPositionBias([x, y, z].map(|v| atof(v, 20) as f32)),
            ["delete", "unused"] => Command::RemoveUnusedKeys,
            ["shift", "lip", n] => Command::ShiftLipFrames(atol(n, 20) as i32),
            ["delete", "lip"] => Command::DeleteLipFrames,
            ["delete", "eye"] => Command::DeleteEyeFrames,
            ["delete", "eyebrow"] => Command::DeleteEyebrowFrames,
            ["register", "blink", start, end] => Command::RegisterBlinks {
                start: atol(start, 20) as i32,
                end: atol(end, 20) as i32,
            },
            ["register", "all", "morph"] => Command::RegisterAllMorphFrames,
            ["reset", "morphs"] => Command::ResetMorphs,
            ["multiply", "camera", v @ ..] if v.len() == 16 => {
                let mut p = mds_ops::CameraScale::default();
                for (i, pair) in v.chunks(2).enumerate() {
                    p.scale[i] = atof(pair[0], 20) as f32;
                    p.add[i] = atof(pair[1], 20) as f32;
                }
                Command::MultiplyCamera(p)
            }
            ["multiply", "bone", v @ ..] if v.len() == 12 => {
                let mut p = mds_ops::BoneScale::default();
                for (i, pair) in v.chunks(2).enumerate() {
                    p.scale[i] = atof(pair[0], 20) as f32;
                    p.add[i] = atof(pair[1], 20) as f32;
                }
                Command::MultiplyBone(p)
            }
            ["multiply", "morph", scale, add] => Command::MultiplyMorph {
                scale: atof(scale, 20) as f32,
                add: atof(add, 20) as f32,
            },
            ["physics", "frames", on @ ("on" | "off")] => Command::SetKeyPhysics {
                disabled: *on == "off",
            },
            ["scale", "range", from, to, rate, bone, morph, display] => {
                let check = |w: &str| match w {
                    "on" => Ok(true),
                    "off" => Ok(false),
                    _ => Err(format!("bad check box {w}")),
                };
                Command::ScaleFrames(mds_ops::RangeScale {
                    start: atol(from, 8) as i32,
                    end: atol(to, 8) as i32,
                    scale: atof(rate, 8),
                    bones: check(bone)?,
                    morphs: check(morph)?,
                    display: check(display)?,
                })
            }
            ["camera", "reference", m] => Command::SetCameraReference(atol(m, 8) as u8),
            ["delete", "model"] => {
                let m = self.doc.selected_model().ok_or("no model selected")?;
                Command::DeleteModel(m.slot)
            }
            ["drag", _, frames] => Command::MoveSelectedKeys(atol(frames, 100) as i32),
            ["load", "lip", "sync", p] => {
                // `ApplyModelComboSelection` grays menu 224 in camera mode
                // (`ui_model_reload.cpp` 453).
                if self.doc.camera_mode() {
                    return Err("menu item 224 is disabled".into());
                }
                let data = load(p)?;
                return self.lip_sync(p, &data, false);
            }
            ["drop", p] if p.to_ascii_lowercase().ends_with(".vsq") => {
                let data = load(p)?;
                return self.lip_sync(p, &data, true);
            }
            ["undo"] => Command::Undo,
            ["redo"] => Command::Redo,
            ["physics", "model", "open"] => {
                return self.open(|doc| Ok(Dialog::Physics(PhysicsDialog::open(doc)?)));
            }
            ["english", "open"] => {
                return self.open(|doc| Ok(Dialog::English(EnglishDialog::open(doc)?)));
            }
            ["model", which @ ("draw" | "calc"), "order", "open"] => {
                let calc = *which == "calc";
                return self.open(|doc| Ok(Dialog::ModelOrder(ModelOrderDialog::open(doc, calc))));
            }
            ["accessory", "order", "open"] => {
                return self
                    .open(|doc| Ok(Dialog::AccessoryOrder(AccessoryOrderDialog::open(doc))));
            }
            ["outside", "parent", "open"] => {
                return self.open(|doc| Ok(Dialog::OutsideParent(OutsideParentDialog::open(doc)?)));
            }
            ["dialog", rest @ ..] => {
                let doc = &mut self.doc;
                let closed = match self.dialog.as_mut().ok_or("no dialog is open")? {
                    Dialog::Physics(d) => d.run(doc, rest)?,
                    Dialog::English(d) => d.run(doc, rest)?,
                    Dialog::ModelOrder(d) => d.run(doc, rest)?,
                    Dialog::AccessoryOrder(d) => d.run(doc, rest)?,
                    Dialog::OutsideParent(d) => d.run(doc, rest)?,
                };
                if closed {
                    self.dialog = None;
                }
                return Ok(Vec::new());
            }
            ["view", "drag", button, modifier, dx, dy] => {
                let d = [dx, dy].map(|v| atol(v, 20) as f32);
                self.view_drag(button, modifier, d)?;
                return Ok(Vec::new());
            }
            ["physics", "drag", what, axis, modifier, dy] => {
                let Some(Dialog::Physics(d)) = self.dialog.as_mut() else {
                    return Err("the physics model dialog is not open".into());
                };
                if self.doc.camera_mode() {
                    return Err("the record drag is a model-mode drag".into());
                }
                let axis = match *axis {
                    "x" => 0,
                    "y" => 1,
                    "z" => 2,
                    _ => return Err(format!("bad axis {axis}")),
                };
                let field = match (*what, *modifier) {
                    ("rotate", _) => PhysicsField::Rotation,
                    ("move", "shift") => PhysicsField::Size,
                    ("move", _) => PhysicsField::Position,
                    _ => return Err(format!("bad drag {what}")),
                };
                d.drag(&mut self.doc, field, axis, atol(dy, 20) as i32)?;
                return Ok(Vec::new());
            }
            ["load", "background", what @ ("movie" | "picture"), p] => {
                let (path, data) = (p.to_string(), load(p)?);
                match *what {
                    "movie" => Command::LoadBackgroundMovie { path, data },
                    _ => Command::LoadBackgroundPicture { path, data },
                }
            }
            ["toggle", "background", "movie"] => {
                Command::ShowBackgroundMovie(self.doc.pmm.avi.enabled == 0)
            }
            ["toggle", "background", "picture"] => {
                Command::ShowBackgroundPicture(self.doc.pmm.picture.enabled == 0)
            }
            ["toggle", "black", "background"] => Command::SetViewOption {
                option: ViewOption::BlackBackground,
                on: self.doc.pmm.appearance.black_background == 0,
            },
            // The refusal is a box; no file is written.
            ["save", "pmd", "refused", name] => {
                return match self.doc.save_pmd(&format!(".\\{name}")) {
                    Err(_) => Ok(Vec::new()),
                    Ok(_) => Err(format!("{name} was saved, not refused")),
                };
            }
            // Menu 261: the dialog's edit `708 + slot` set, then OK
            // (`CollectToonFileNames`, `enhance_model_io.cpp` 57-95). The
            // texture has to load from the model directory, which
            // `pmd_load.cpp` cuts after the last backslash of the path, or
            // after its first character.
            ["toon", slot, name] => {
                let slot: usize = slot
                    .parse()
                    .ok()
                    .filter(|s| (1..=10).contains(s))
                    .ok_or_else(|| format!("bad toon slot {slot}"))?;
                let path = &self
                    .doc
                    .selected_model()
                    .ok_or("no model selected")?
                    .path
                    .text;
                let dir = match path.rfind('\\') {
                    Some(i) => &path[..=i],
                    None => path.get(..1).unwrap_or(""),
                };
                let file = format!("{dir}{name}");
                load(&file).map_err(|_| format!("cannot find {file} (a message box)"))?;
                let names = (1..=10)
                    .map(|i| match i == slot {
                        true => name.to_string(),
                        false => format!("toon{i:02}.bmp"),
                    })
                    .collect();
                Command::SetToonFileNames(names)
            }
            _ => return Err("not ported".into()),
        };
        self.doc.apply(cmd).map_err(e)?;
        Ok(Vec::new())
    }

    fn open(
        &mut self,
        open: impl FnOnce(&mut Document) -> Result<Dialog, String>,
    ) -> Result<Vec<Saved>, String> {
        if self.dialog.is_some() {
            return Err("a dialog is open".into());
        }
        self.dialog = Some(open(&mut self.doc)?);
        Ok(Vec::new())
    }

    /// The model-mode branches of `ConsumeRightButtonDrag` and
    /// `ConsumeMiddleButtonPan` (`src/app/pump_navigation.cpp` 316-390) for
    /// one held frame that moved by `d`: shift + right and the middle button
    /// pan the view offset, ctrl + right changes the distance, the plain
    /// right drag orbits.
    fn view_drag(&mut self, button: &str, modifier: &str, d: [f32; 2]) -> Result<(), String> {
        if self.doc.camera_mode() {
            return Err("not ported: the camera-mode view drags".into());
        }
        let p = &self.doc.pmm;
        let selected = self.doc.selected_model().map(|m| i32::from(m.slot));
        // `BoneEditPathActive`: the hold only refreshes the bone edit.
        let cam = p.appearance.camera_parent_model;
        if button == "right" && cam >= 0 && selected == Some(cam) && p.appearance.follow_camera != 0
        {
            return Ok(());
        }
        let [dx, dy] = d;
        let [x, y] = [p.camera_state[3], p.camera_state[4]];
        let pan = |scale: f32| Command::SetViewOffset([x - dx * scale, y + dy * scale]);
        let cmd = match (button, modifier) {
            ("right", "shift") => pan(0.1),
            ("right", "ctrl") => return self.camera(|s| s[5] -= dy * 0.1),
            ("right", "none") => {
                return self.camera(|s| {
                    s[7] -= dx * 0.01;
                    s[6] -= dy * 0.01;
                })
            }
            ("middle", "shift") => pan(0.5),
            ("middle", "ctrl") => pan(0.005),
            ("middle", "none") => pan(0.05),
            _ => return Err(format!("bad view drag {button} {modifier}")),
        };
        self.doc.apply(cmd).map_err(e)
    }

    /// The morph that `CB_FINDSTRINGEXACT` picks in a lane's combo (the
    /// morphs of panel `lane + 1`, case-insensitive), then the first morph
    /// of that name, as `MorphRowSelect` matches it.
    fn lane_morph(&self, lane: u8, name: &str) -> Result<u32, String> {
        let i = self.doc.active().ok_or("no model selected")?;
        let names = &self.doc.pmm.models[i].morph_names;
        let panels: Vec<u8> = match &self.doc.models[i] {
            crate::ModelFile::Pmx(p) => p.morphs.iter().map(|m| m.panel).collect(),
            crate::ModelFile::Pmd(p) => p.morphs.iter().map(|m| m.panel).collect(),
            crate::ModelFile::Missing => return Err("the model file is missing".into()),
        };
        let item = names
            .iter()
            .zip(&panels)
            .find(|(n, &p)| p == lane + 1 && n.text.eq_ignore_ascii_case(name))
            .ok_or_else(|| format!("no morph {name} in lane {lane}"))?;
        let first = names.iter().position(|n| n.raw == item.0.raw).unwrap_or(0);
        Ok(first as u32)
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

    /// `LoadVsqFile`, and the `.txt` it writes beside the VSQ (`L"wt"`:
    /// CRLF lines), named after the VSQ. The refusal of a drop in camera
    /// mode is an info box, not a failed step.
    fn lip_sync(&mut self, path: &str, vsq: &[u8], dropped: bool) -> Result<Vec<Saved>, String> {
        let run = match self.doc.lip_sync(vsq, dropped) {
            Err(Error::NotApplicable(_)) if dropped && self.doc.camera_mode() => {
                return Ok(Vec::new());
            }
            r => r.map_err(e)?,
        };
        let name = path.rsplit(['\\', '/']).next().unwrap_or(path);
        let txt = mds_vsq::txt_path(name).ok_or("a VSQ path without .vsq")?;
        let mut bytes = Vec::with_capacity(run.txt.len());
        for &b in &run.txt {
            if b == b'\n' {
                bytes.push(b'\r');
            }
            bytes.push(b);
        }
        Ok(self.saved(&txt, bytes))
    }

    fn saved(&mut self, name: &str, bytes: Vec<u8>) -> Vec<Saved> {
        self.out.insert(name.to_string(), bytes.clone());
        vec![Saved {
            name: name.to_string(),
            bytes,
        }]
    }
}
