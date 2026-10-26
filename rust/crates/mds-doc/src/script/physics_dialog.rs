//! The physics model dialog of menu 262 (`PhysicsModelDlgProc`,
//! `src/window/physics_model_dialog.cpp`) as the script's `dialog` lines
//! drive it: the text of each edit box, the records it shows, and the
//! collect and fill steps between them and
//! [`EditState::physics_scratch`](crate::EditState::physics_scratch).
//!
//! The name (705, 740), group (719), combo (707, 708, 741..743), add,
//! delete, copy and paste controls are not driven; their record fields stay
//! as the dialog read them, which is what the C++ collect step writes back.

use super::atof;
use crate::{Command, Document};
use mds_formats::pmd::{Joint, Rigid};
use std::collections::HashMap;

/// `kPiF` (0x40490FDB) of `ReadEditDegrees`.
const PI_F: f32 = std::f32::consts::PI;
/// `kPiShort` (0x40490FD8) of the displays and the Y angle limits.
const PI_SHORT: f32 = 3.141592;

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

/// The edits the collect steps read, and the ones a script may type into.
fn typed(id: u16) -> bool {
    (SIZE..=MASS).contains(&id) || (DAMPING..DAMPING + 4).contains(&id) || (744..=767).contains(&id)
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
        let mut d = PhysicsDialog::default();
        d.body = (!rigids.is_empty()).then_some(0);
        d.joint = (!joints.is_empty()).then_some(0);
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

    /// The validated Y angle limits (`CollectJointEdits` 812-824,
    /// `CheckYAngleLimit` 329-348): ten characters, -90 and 90 excluded
    /// (80 or -80 instead, with a message box), over `kPiShort`.
    fn y_limit(&mut self, id: u16) -> f32 {
        let mut v = atof(self.text(id), 10) as f32;
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

    /// `CollectBodyEdits` (693-735).
    fn collect_body(&mut self, rigids: &mut [Rigid]) {
        let Some(r) = self.body.and_then(|i| rigids.get_mut(i)) else {
            return;
        };
        for a in 0..3 {
            let id = SIZE + a as u16;
            if atof(self.text(id), 256) < 0.1 {
                self.set(id, "0.1".into());
            }
            r.size[a] = self.float(id);
            r.position[a] = self.float(POSITION + a as u16);
            r.rotation[a] = self.degrees(ROTATION + a as u16);
        }
        r.mass = self.float(MASS);
        r.linear_damping = self.float(DAMPING);
        r.angular_damping = self.float(DAMPING + 1);
        r.restitution = self.float(DAMPING + 2);
        r.friction = self.float(DAMPING + 3);
    }

    /// `CollectJointEdits` (782-830).
    fn collect_joint(&mut self, joints: &mut [Joint]) {
        let Some(i) = self.joint.filter(|&i| i < joints.len()) else {
            return;
        };
        let mut j = joints[i].clone();
        for a in 0..3 {
            j.position[a] = self.float(JOINT_POSITION + a as u16);
            j.rotation[a] = self.degrees(JOINT_ROTATION + a as u16);
            j.translation_max[a] = self.float(LINEAR_UPPER[a]);
            j.translation_min[a] = self.float(LINEAR_LOWER[a]);
        }
        j.rotation_max[0] = self.degrees(ANGULAR_UPPER[0]);
        j.rotation_max[1] = self.y_limit(ANGULAR_UPPER[1]);
        j.rotation_max[2] = self.degrees(ANGULAR_UPPER[2]);
        j.rotation_min[0] = self.degrees(ANGULAR_LOWER[0]);
        j.rotation_min[1] = self.y_limit(ANGULAR_LOWER[1]);
        j.rotation_min[2] = self.degrees(ANGULAR_LOWER[2]);
        for a in 0..3 {
            j.spring_translation[a] = self.float(SPRING_LINEAR + a as u16);
            j.spring_rotation[a] = self.float(SPRING_ANGULAR + a as u16);
        }
        joints[i] = j;
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
            ["select", c, item] => {
                let item: usize = item.parse().map_err(|_| format!("bad item {item}"))?;
                match id(c)? {
                    BODY_LIST => {
                        self.collect_body(rigids);
                        if item < rigids.len() {
                            self.body = Some(item);
                            self.show_body(rigids);
                        }
                    }
                    JOINT_LIST => {
                        self.collect_joint(joints);
                        if item < joints.len() {
                            self.joint = Some(item);
                            self.show_joint(joints);
                        }
                    }
                    _ => return Err("not ported".into()),
                }
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
                self.collect_body(rigids);
                self.collect_joint(joints);
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
