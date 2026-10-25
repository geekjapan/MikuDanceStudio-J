//! `CONTROLOBJECT` parameters: values read from other objects of the scene. Ported from
//! `third_party/mmeffect/src/mmeffect/material_bind.cpp` (`MmeUpdateControlObjects`,
//! `ResolveOneControl`, `ControlParameterTypeCode`, `SetControlDefaults`, `KindGuessForName`),
//! `model_data.cpp` (`ModelData::BuildNameTable`, the accessory pseudo-bones),
//! `model_name_registry.h` (`ModelNameRegistry::Find`), and `pass_planner.cpp`
//! (`MmeRefreshObjectPlan`: the object matrix and render order).
//!
//! The values the C++ reads through the `ExpGetPmd*` and `ExpGetAcs*` host exports come from
//! [`Controls`], which the application fills each frame.

use std::collections::BTreeMap;

use mds_mme::fx::{CLASS_MATRIX_COLUMNS, CLASS_MATRIX_ROWS, CLASS_VECTOR, TYPE_BOOL};
use mds_mme::sas::Sas;

use crate::bind::{Mat, IDENTITY};

/// One object of the scene as the host reports it.
#[derive(Clone, Debug)]
pub struct Object {
    /// The file name with its extension (`ModelData::name`), which `CONTROLOBJECT` names it by.
    pub name: String,
    /// A PMD or PMX model; otherwise an accessory.
    pub model: bool,
    /// `|ExpGetPmdOrder|` or `|ExpGetAcsOrder|`.
    pub order: i32,
    /// `ExpGetPmdDisp` or `ExpGetAcsDisp`.
    pub shown: bool,
    /// `ExpGetAcsWorldMat` of an accessory. A model's object matrix is the identity.
    pub world: Mat,
    /// Bone names and world matrices (`ExpGetPmdBoneName`, `ExpGetPmdBoneWorldMat`) by index.
    pub bones: Vec<(String, Mat)>,
    /// Morph names and values (`ExpGetPmdMorphName`, `ExpGetPmdMorphValue`) by index.
    pub morphs: Vec<(String, f32)>,
    /// An accessory's X, Y, Z, Rx, Ry, Rz, Si, Tr (`ExpGetAcsX` ... `ExpGetAcsTr`).
    pub accessory: [f32; 8],
    /// `GetAcsAttachedPmd`: the model (an index into [`Controls::objects`]) and bone an
    /// accessory is attached to.
    pub attached: Option<(usize, i32)>,
}

impl Object {
    /// A model with no bones or morphs.
    pub fn model(name: &str, order: i32) -> Object {
        Object {
            name: name.to_string(),
            model: true,
            order,
            shown: true,
            world: IDENTITY,
            bones: Vec::new(),
            morphs: Vec::new(),
            accessory: [0.0; 8],
            attached: None,
        }
    }

    /// `ModelData::findNameIndex`: bones 0, 1, ..., then morphs -1, -2, ... inserted over them;
    /// an accessory has the fixed pseudo-bones.
    fn name_index(&self, item: &str) -> Option<i32> {
        if !self.model {
            const PSEUDO: [&str; 10] = ["X", "Y", "Z", "XYZ", "Rx", "Ry", "Rz", "Rxyz", "Si", "Tr"];
            return PSEUDO.iter().position(|&p| p == item).map(|i| i as i32);
        }
        if let Some(m) = self.morphs.iter().rposition(|(n, _)| n == item) {
            return Some(-(m as i32) - 1);
        }
        self.bones
            .iter()
            .rposition(|(n, _)| n == item)
            .map(|b| b as i32)
    }

    fn matrix(&self) -> Mat {
        if self.model {
            IDENTITY
        } else {
            self.world
        }
    }
}

/// The scene's objects in host enumeration order (models, then accessories).
#[derive(Clone, Debug, Default)]
pub struct Controls {
    pub objects: Vec<Object>,
}

impl Controls {
    /// `ModelNameRegistry::Find`: of the objects with this name (first registered per order,
    /// orders compared unsigned), the last whose order is not after the owner's, else the last.
    fn find(&self, name: &str, owner_order: i32) -> Option<usize> {
        let mut by_order: BTreeMap<u32, usize> = BTreeMap::new();
        for (i, o) in self.objects.iter().enumerate() {
            if o.name == name {
                by_order.entry(o.order as u32).or_insert(i);
            }
        }
        let mut selected = None;
        for (&order, &i) in &by_order {
            if owner_order < order as i32 {
                break;
            }
            selected = Some(i);
        }
        selected.or_else(|| by_order.values().next_back().copied())
    }

    /// `KindGuessForName`: the first registered object's kind, else accessory for `.x`.
    fn guess_model(&self, name: &str) -> bool {
        match self
            .objects
            .iter()
            .enumerate()
            .filter(|(_, o)| o.name == name)
            .min_by_key(|(i, o)| (o.order as u32, *i))
        {
            Some((_, o)) => o.model,
            None => !(name.ends_with(".x") || name.ends_with(".X")),
        }
    }
}

/// `ControlParameterTypeCode`: 0 bool, 1 float, 3 float3, 4 float4, 16 matrix.
fn type_code(class: u8, ty: u8, columns: u32) -> u8 {
    if class == CLASS_MATRIX_ROWS || class == CLASS_MATRIX_COLUMNS {
        16
    } else if class == CLASS_VECTOR {
        if ty == TYPE_BOOL {
            0
        } else if columns >= 4 {
            4
        } else {
            3
        }
    } else if ty == TYPE_BOOL {
        0
    } else {
        1
    }
}

fn set(values: &mut [f32], v: &[f32]) {
    for (d, s) in values.iter_mut().zip(v) {
        *d = *s;
    }
}

/// `MmeUpdateControlObjects`: every `CONTROLOBJECT` parameter of `sas` from `controls`, for the
/// object `owner` the effect is assigned to and, inside an offscreen turn, the object
/// `offscreen_owner` that carries the offscreen target (indices into [`Controls::objects`]).
pub fn resolve(
    sas: &Sas,
    values: &mut [Vec<f32>],
    controls: &Controls,
    owner: Option<usize>,
    offscreen_owner: Option<usize>,
) {
    let objects = &controls.objects;
    for c in &sas.controls {
        let owner_obj = owner.map(|i| &objects[i]);
        let mut target = owner_obj.and_then(|o| controls.find(&c.object, o.order));
        if target.is_none() {
            target = match c.object.as_str() {
                "(OffscreenOwner)" if offscreen_owner.is_some() => offscreen_owner,
                "(self)" => owner,
                "(AttachedModel)" => owner_obj
                    .filter(|o| !o.model)
                    .and_then(|o| o.attached)
                    .map(|a| a.0),
                _ => None,
            };
        }
        let desc = &sas.fx.params[c.param].desc;
        let code = type_code(desc.class, desc.ty, desc.columns);
        let has_item = !c.item.is_empty();
        let vals = &mut values[c.param];
        let Some(t) = target.map(|i| &objects[i]) else {
            let model = controls.guess_model(&c.object);
            match code {
                0 => set(vals, &[0.0]),
                1 => set(
                    vals,
                    &[if has_item {
                        0.0
                    } else if model {
                        1.0
                    } else {
                        10.0
                    }],
                ),
                3 => set(vals, &[0.0; 4]),
                4 => set(vals, &[0.0, 0.0, 0.0, 1.0]),
                _ => {
                    let s = if model { 1.0 } else { 10.0 };
                    let mut m = IDENTITY;
                    (m[0], m[5], m[10]) = (s, s, s);
                    set(vals, &m);
                }
            }
            continue;
        };
        // An identity matrix that holds either a whole matrix or a value in floats 12 to 14.
        let mut buf = IDENTITY;
        let mut matrix = false;
        if !has_item {
            buf = t.matrix();
            matrix = true;
        } else if owner_obj.is_some_and(|o| !o.model) && c.item == "(AttachedBone)" {
            if let Some((m, bone)) = owner_obj.and_then(|o| o.attached) {
                if target == Some(m) && bone >= 0 {
                    if let Some((_, w)) = objects[m].bones.get(bone as usize) {
                        buf = *w;
                        matrix = true;
                    }
                }
            }
        } else if let Some(index) = t.name_index(&c.item) {
            if t.model {
                if index < 0 {
                    buf[12] = t.morphs[(-index - 1) as usize].1;
                } else {
                    buf = t.bones[index as usize].1;
                    matrix = true;
                }
            } else {
                let a = &t.accessory;
                match index {
                    0..=2 => buf[12] = a[index as usize],
                    3 => buf[12..15].copy_from_slice(&a[0..3]),
                    4..=6 => buf[12] = a[index as usize - 1],
                    7 => buf[12..15].copy_from_slice(&a[3..6]),
                    8 | 9 => buf[12] = a[index as usize - 2],
                    _ => {}
                }
            }
        }
        match code {
            0 => set(vals, &[f32::from(u8::from(t.shown))]),
            1 => set(
                vals,
                &[if matrix {
                    (buf[0] * buf[0] + buf[1] * buf[1] + buf[2] * buf[2]).sqrt()
                } else {
                    buf[12]
                }],
            ),
            3 => set(vals, &[buf[12], buf[13], buf[14], 0.0]),
            4 => set(vals, &buf[12..16]),
            _ => set(vals, &buf),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names_resolve_by_render_order_and_table() {
        let mut a = Object::model("m.pmx", 5);
        a.bones = vec![("Root".into(), IDENTITY), ("Same".into(), IDENTITY)];
        a.morphs = vec![("Same".into(), 0.25)];
        let b = Object::model("m.pmx", 9);
        let c = Controls {
            objects: vec![a, b],
        };
        assert_eq!(c.objects[0].name_index("Same"), Some(-1));
        assert_eq!(c.objects[0].name_index("Root"), Some(0));
        // The owner at order 7 sees the m.pmx at 5; one before every candidate sees the last.
        assert_eq!(c.find("m.pmx", 7), Some(0));
        assert_eq!(c.find("m.pmx", 9), Some(1));
        assert_eq!(c.find("m.pmx", 1), Some(1));
        assert!(!c.guess_model("stage.x"));
        assert!(c.guess_model("m.pmx"));
        assert_eq!(type_code(CLASS_VECTOR, 3, 3), 3);
        assert_eq!(type_code(0, TYPE_BOOL, 1), 0);
    }
}
