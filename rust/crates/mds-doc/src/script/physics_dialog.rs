//! The physics model dialog of menu 262 (`PhysicsModelDlgProc`,
//! `src/window/physics_model_dialog.cpp`) as the script's `dialog` lines
//! drive it: the text of each edit box, the records it shows, and the
//! collect and fill steps between them and
//! [`EditState::physics_scratch`](crate::EditState::physics_scratch).
//!
//! The group (719), combo (707, 708, 741..743), add, delete, copy and paste
//! controls are not driven; their record fields stay as the dialog read
//! them, which is what the C++ collect step writes back.

use super::atof;
use crate::{Command, Document, PhysicsField, PI_LIT};
use mds_formats::pmd::{Joint, Rigid};
use mds_formats::text::FixedSjis;
use std::collections::HashMap;

/// `kPiF` (0x40490FDB) of `ReadEditDegrees`.
const PI_F: f32 = std::f32::consts::PI;
/// `kPiShort` (0x40490FD8) of the displays and the Y angle limits.
const PI_SHORT: f32 = f32::from_bits(0x4049_0FD8);

const BODY_NAME: u16 = 705;
const SIZE: u16 = 709;
const POSITION: u16 = 712;
const ROTATION: u16 = 715;
const MASS: u16 = 718;
/// Linear damping, angular damping, restitution, friction.
const DAMPING: u16 = 720;
const SPHERE: u16 = 726;
const PHYSICAL: u16 = 729;
const BONE_FOLLOW: u16 = 730;
const ALIGN: u16 = 731;
const JOINT_NAME: u16 = 740;
const JOINT_POSITION: u16 = 744;
const JOINT_ROTATION: u16 = 754;
const SPRING_LINEAR: u16 = 748;
const SPRING_ANGULAR: u16 = 751;
/// The linear upper and lower limits, X Y Z.
const LINEAR_UPPER: [u16; 3] = [757, 759, 761];
const LINEAR_LOWER: [u16; 3] = [747, 758, 760];
const ANGULAR_UPPER: [u16; 3] = [763, 765, 767];
const ANGULAR_LOWER: [u16; 3] = [762, 764, 766];
const BODY_LIST: u16 = 704;
const JOINT_LIST: u16 = 736;

/// The edits of `CollectBodyEdits` (693-735), in its order.
const BODY_EDITS: [u16; 15] = [
    BODY_NAME, 709, 710, 711, 712, 713, 714, 715, 716, 717, MASS, 720, 721, 722, 723,
];
/// The edits of `CollectJointEdits` (782-830), in its order.
const JOINT_EDITS: [u16; 25] = [
    JOINT_NAME, 744, 745, 746, 754, 755, 756, 757, 759, 761, 747, 758, 760, 763, 765, 767, 762,
    764, 766, 748, 749, 750, 751, 752, 753,
];

/// The edits the collect steps read, and the ones a script may type into.
fn typed(id: u16) -> bool {
    BODY_EDITS.contains(&id) || JOINT_EDITS.contains(&id)
}

/// The SJIS bytes of a name edit (`GetWindowTextA(.., 100)`).
fn name_bytes(text: &str) -> Vec<u8> {
    let mut raw = crate::add_model::sjis(text, usize::MAX).raw;
    raw.truncate(99);
    raw
}

/// `strcpy_s(name, 20, text)`: the bytes after the NUL stay.
fn set_name(f: &mut FixedSjis<20>, raw: &[u8]) -> Result<(), String> {
    if raw.len() >= 20 {
        return Err("a name longer than its buffer (strcpy_s fails)".into());
    }
    f.raw[..raw.len()].copy_from_slice(raw);
    f.raw[raw.len()] = 0;
    f.text = mds_formats::text::decode_sjis(&f.raw);
    Ok(())
}

#[derive(Default)]
pub(super) struct PhysicsDialog {
    /// The edit texts; an edit never set holds "" (the template's).
    texts: HashMap<u16, String>,
    /// `selectedRigidIndex` and `selectedJointIndex`.
    body: Option<usize>,
    joint: Option<usize>,
    /// The bone-alignment check box (731).
    align: bool,
    /// The joint page radio (801) is checked.
    joint_page: bool,
}

fn f2(v: f32) -> String {
    format!("{:.2}", f64::from(v))
}

impl PhysicsDialog {
    /// `InitPhysicsModelDialog` (574-691) on the selected PMD.
    pub(super) fn open(doc: &mut Document) -> Result<PhysicsDialog, String> {
        let (i, pmd) = doc.selected_pmd().map_err(super::e)?;
        let physics = pmd.extension.as_ref().and_then(|x| x.physics.as_ref());
        let rigids = physics.map(|p| p.rigids.clone()).unwrap_or_default();
        let joints = physics.and_then(|p| p.joints.clone()).unwrap_or_default();
        // The bones' edit transforms are neutralized (677-682); OK and
        // cancel seek them back.
        for p in &mut doc.pmm.models[i].bone_pose {
            p.translation = [0.0; 3];
            p.rotation = [0.0, 0.0, 0.0, 1.0];
        }
        let mut d = PhysicsDialog {
            body: (!rigids.is_empty()).then_some(0),
            joint: (!joints.is_empty()).then_some(0),
            ..PhysicsDialog::default()
        };
        d.show_body(&rigids);
        d.show_joint(&joints);
        doc.edit.physics_scratch = Some((rigids, joints));
        Ok(d)
    }

    fn set(&mut self, id: u16, text: String) {
        self.texts.insert(id, text);
    }

    fn text(&self, id: u16) -> &str {
        self.texts.get(&id).map_or("", String::as_str)
    }

    /// `ReadEditFloat`.
    fn float(&self, id: u16) -> f32 {
        atof(self.text(id), 256) as f32
    }

    /// `ReadEditDegrees`.
    fn degrees(&self, id: u16) -> f32 {
        self.float(id) / 180.0 * PI_F
    }

    /// `ReadEditFloatClamped`: below 0.1 the box becomes "0.1".
    fn clamped(&mut self, id: u16) -> f32 {
        if atof(self.text(id), 256) < 0.1 {
            self.set(id, "0.1".into());
        }
        self.float(id)
    }

    /// The validated Y angle limits (`CollectJointEdits` 812-824,
    /// `CheckYAngleLimit` 329-348): ten characters (256 on Enter), -90 and
    /// 90 excluded (80 or -80 instead, with a message box), over `kPiShort`.
    fn y_limit(&mut self, id: u16, max: usize) -> f32 {
        let mut v = atof(self.text(id), max) as f32;
        if v <= -90.0 || v >= 90.0 {
            let (value, text) = if v > -90.0 {
                (80.0, "80.00")
            } else {
                (-80.0, "-80.00")
            };
            v = value;
            self.set(id, text.into());
        }
        v / 180.0 * PI_SHORT
    }

    /// `UpdateShapeControls` (886-944): the size edits of the shape.
    fn show_shape(&mut self, shape: u8, r: Option<&Rigid>) {
        let shown = match shape {
            0 => 1,
            1 => 3,
            _ => 2,
        };
        match r {
            Some(r) => (0..shown).for_each(|a| self.set(SIZE + a as u16, f2(r.size[a]))),
            None if shape == 0 => self.set(SIZE, String::new()),
            None => {}
        }
    }

    /// `ApplyBodyRecordToEdits` (992-1053).
    fn show_body(&mut self, rigids: &[Rigid]) {
        let Some(r) = self.body.and_then(|i| rigids.get(i)) else {
            self.show_shape(0, None);
            (POSITION..DAMPING + 4).for_each(|id| self.set(id, String::new()));
            return;
        };
        self.set(BODY_NAME, r.name.text.clone());
        self.show_shape(r.shape, Some(r));
        for a in 0..3 {
            self.set(POSITION + a as u16, f2(r.position[a]));
            self.set(ROTATION + a as u16, f2(r.rotation[a] / PI_SHORT * 180.0));
        }
        self.set(MASS, format!("{:.3}", f64::from(r.mass)));
        let damping = [
            r.linear_damping,
            r.angular_damping,
            r.restitution,
            r.friction,
        ];
        for (k, v) in damping.into_iter().enumerate() {
            self.set(DAMPING + k as u16, format!("{:.3}", f64::from(v)));
        }
        self.align = r.mode == 2;
    }

    /// `ApplyJointRecordToEdits` (1062-1121).
    fn show_joint(&mut self, joints: &[Joint]) {
        let Some(j) = self.joint.and_then(|i| joints.get(i)) else {
            (JOINT_POSITION..=767).for_each(|id| self.set(id, String::new()));
            return;
        };
        let deg = |v: f32| f2(v / PI_SHORT * 180.0);
        self.set(JOINT_NAME, j.name.text.clone());
        for a in 0..3 {
            self.set(
                JOINT_POSITION + a as u16,
                format!("{:.4}", f64::from(j.position[a])),
            );
            self.set(JOINT_ROTATION + a as u16, deg(j.rotation[a]));
            self.set(LINEAR_UPPER[a], f2(j.translation_max[a]));
            self.set(LINEAR_LOWER[a], f2(j.translation_min[a]));
            self.set(ANGULAR_UPPER[a], deg(j.rotation_max[a]));
            self.set(ANGULAR_LOWER[a], deg(j.rotation_min[a]));
            self.set(SPRING_LINEAR + a as u16, f2(j.spring_translation[a]));
            self.set(SPRING_ANGULAR + a as u16, f2(j.spring_rotation[a]));
        }
    }

    /// One body edit into `r`, as the collect step reads it, or with
    /// `enter` as Enter in it commits it (`PhysicsEditSubclassProc`
    /// 360-560, which also clamps the mass).
    fn read_body(&mut self, r: &mut Rigid, id: u16, enter: bool) -> Result<(), String> {
        match id {
            BODY_NAME => {
                let mut raw = name_bytes(self.text(id));
                if enter && raw.len() > 20 {
                    raw.truncate(19);
                }
                set_name(&mut r.name, &raw)?;
            }
            709..=711 => r.size[usize::from(id - SIZE)] = self.clamped(id),
            712..=714 => r.position[usize::from(id - POSITION)] = self.float(id),
            715..=717 => r.rotation[usize::from(id - ROTATION)] = self.degrees(id),
            MASS if enter => r.mass = self.clamped(id),
            MASS => r.mass = self.float(id),
            720 => r.linear_damping = self.float(id),
            721 => r.angular_damping = self.float(id),
            722 => r.restitution = self.float(id),
            723 => r.friction = self.float(id),
            _ => return Err(format!("edit {id} is not a body edit")),
        }
        Ok(())
    }

    /// One joint edit into `j`, as [`PhysicsDialog::read_body`].
    fn read_joint(&mut self, j: &mut Joint, id: u16, enter: bool) -> Result<(), String> {
        let axis = |ids: [u16; 3]| ids.iter().position(|&x| x == id);
        match id {
            JOINT_NAME => {
                let mut raw = name_bytes(self.text(id));
                if enter && raw.len() > 20 {
                    raw.truncate(19);
                }
                set_name(&mut j.name, &raw)?;
            }
            744..=746 => j.position[usize::from(id - JOINT_POSITION)] = self.float(id),
            754..=756 => j.rotation[usize::from(id - JOINT_ROTATION)] = self.degrees(id),
            748..=750 => j.spring_translation[usize::from(id - SPRING_LINEAR)] = self.float(id),
            751..=753 => j.spring_rotation[usize::from(id - SPRING_ANGULAR)] = self.float(id),
            765 => j.rotation_max[1] = self.y_limit(id, if enter { 256 } else { 10 }),
            764 => j.rotation_min[1] = self.y_limit(id, if enter { 256 } else { 10 }),
            _ => {
                if let Some(a) = axis(LINEAR_UPPER) {
                    j.translation_max[a] = self.float(id);
                } else if let Some(a) = axis(LINEAR_LOWER) {
                    j.translation_min[a] = self.float(id);
                } else if let Some(a) = axis(ANGULAR_UPPER) {
                    j.rotation_max[a] = self.degrees(id);
                } else if let Some(a) = axis(ANGULAR_LOWER) {
                    j.rotation_min[a] = self.degrees(id);
                } else {
                    return Err(format!("edit {id} is not a joint edit"));
                }
            }
        }
        Ok(())
    }

    /// `CollectBodyEdits` (693-735).
    fn collect_body(&mut self, rigids: &mut [Rigid]) -> Result<(), String> {
        let Some(r) = self.body.and_then(|i| rigids.get_mut(i)) else {
            return Ok(());
        };
        BODY_EDITS
            .iter()
            .try_for_each(|&id| self.read_body(r, id, false))
    }

    /// `CollectJointEdits` (782-830).
    fn collect_joint(&mut self, joints: &mut [Joint]) -> Result<(), String> {
        let Some(j) = self.joint.and_then(|i| joints.get_mut(i)) else {
            return Ok(());
        };
        JOINT_EDITS
            .iter()
            .try_for_each(|&id| self.read_joint(j, id, false))
    }

    /// A drag on the viewport tool (`EditModeRecord`,
    /// `frame_modes_bone.cpp` 158-224) on the selected body, or the
    /// selected joint on the joint page, then `EchoRecord` of the new value
    /// into its edit: `%3.2f`, the rotation in degrees, a joint position
    /// `%5.4f`.
    pub(super) fn drag(
        &mut self,
        doc: &mut Document,
        field: PhysicsField,
        axis: u8,
        dy: i32,
    ) -> Result<(), String> {
        let joint = self.joint_page;
        let Some(index) = (if joint { self.joint } else { self.body }) else {
            return Ok(());
        };
        // On the joint page Shift moves the joint too (`frame_modes_bone.cpp:196-204`).
        let field = match field {
            PhysicsField::Size if joint => PhysicsField::Position,
            f => f,
        };
        let cmd = Command::EditPhysicsRecord {
            joint,
            index: index as u32,
            field,
            axis,
            dy,
        };
        doc.apply(cmd).map_err(super::e)?;
        let (rigids, joints) = doc.edit.physics_scratch.as_ref().ok_or("closed")?;
        let a = usize::from(axis);
        let deg = |v: f32| format!("{:3.2}", f64::from(v) / PI_LIT * 180.0);
        let (id, text) = match (joint, field) {
            (true, PhysicsField::Rotation) => (JOINT_ROTATION, deg(joints[index].rotation[a])),
            (true, _) => (
                JOINT_POSITION,
                format!("{:5.4}", f64::from(joints[index].position[a])),
            ),
            (false, PhysicsField::Rotation) => (ROTATION, deg(rigids[index].rotation[a])),
            (false, PhysicsField::Position) => (
                POSITION,
                format!("{:3.2}", f64::from(rigids[index].position[a])),
            ),
            (false, PhysicsField::Size) => {
                (SIZE, format!("{:3.2}", f64::from(rigids[index].size[a])))
            }
        };
        self.set(id + u16::from(axis), text);
        Ok(())
    }

    /// One `dialog` line. `Ok(true)` when it closed the dialog.
    pub(super) fn run(&mut self, doc: &mut Document, w: &[&str]) -> Result<bool, String> {
        let closed = "the physics model dialog is closed";
        let (mut rigids, mut joints) = doc.edit.physics_scratch.take().ok_or(closed)?;
        let r = self.run_on(doc, w, &mut rigids, &mut joints);
        if !matches!(r, Ok(true)) {
            doc.edit.physics_scratch = Some((rigids, joints));
        }
        r
    }

    fn run_on(
        &mut self,
        doc: &mut Document,
        w: &[&str],
        rigids: &mut Vec<Rigid>,
        joints: &mut Vec<Joint>,
    ) -> Result<bool, String> {
        let id = |s: &str| s.parse::<u16>().map_err(|_| format!("bad control id {s}"));
        match w {
            ["text", c, text] if typed(id(c)?) => self.set(id(c)?, text.to_string()),
            ["edit", c, text] if typed(id(c)?) => {
                let c = id(c)?;
                self.set(c, text.to_string());
                if BODY_EDITS.contains(&c) {
                    if let Some(r) = self.body.and_then(|i| rigids.get_mut(i)) {
                        self.read_body(r, c, true)?;
                    }
                } else if let Some(j) = self.joint.and_then(|i| joints.get_mut(i)) {
                    self.read_joint(j, c, true)?;
                }
            }
            ["select", c, item] => {
                let item: usize = item.parse().map_err(|_| format!("bad item {item}"))?;
                match id(c)? {
                    BODY_LIST => {
                        self.collect_body(rigids)?;
                        if item < rigids.len() {
                            self.body = Some(item);
                            self.show_body(rigids);
                        }
                    }
                    JOINT_LIST => {
                        self.collect_joint(joints)?;
                        if item < joints.len() {
                            self.joint = Some(item);
                            self.show_joint(joints);
                        }
                    }
                    _ => return Err("not ported".into()),
                }
            }
            // The page radios (1500-1507) collect the page they leave.
            ["click", "800"] => {
                self.collect_joint(joints)?;
                self.joint_page = false;
            }
            ["click", "801"] => {
                self.collect_body(rigids)?;
                self.joint_page = true;
            }
            ["click", c] => {
                let c = id(c)?;
                let r = self
                    .body
                    .and_then(|i| rigids.get_mut(i))
                    .ok_or("no rigid body is shown")?;
                match c {
                    // 0x2D6..0x2D8 (1466-1477).
                    SPHERE..=728 => {
                        r.shape = (c - SPHERE) as u8;
                        let shape = r.shape;
                        let r = r.clone();
                        self.show_shape(shape, Some(&r));
                    }
                    // 0x2D9..0x2DB (1478-1500); the check box toggles first.
                    PHYSICAL => r.mode = if self.align { 2 } else { 1 },
                    BONE_FOLLOW => r.mode = 0,
                    ALIGN => {
                        self.align = !self.align;
                        r.mode = match r.mode {
                            2 => 1,
                            1 => 2,
                            m => m,
                        };
                    }
                    _ => return Err("not ported".into()),
                }
            }
            // OK (1515-1540) and cancel (1541-1556): both seek the model.
            ["ok"] => {
                self.collect_body(rigids)?;
                self.collect_joint(joints)?;
                let i = doc.active_model().map_err(super::e)?;
                doc.seek(i);
                doc.apply(Command::SetPhysicsModel {
                    rigids: std::mem::take(rigids),
                    joints: std::mem::take(joints),
                })
                .map_err(super::e)?;
                return Ok(true);
            }
            ["cancel"] => {
                let i = doc.active_model().map_err(super::e)?;
                doc.seek(i);
                return Ok(true);
            }
            _ => return Err("not ported".into()),
        }
        Ok(false)
    }
}
