//! The delete button of the model panel (437, `DeleteSelectedModel`,
//! `src/window/command_frame_edit.cpp` 1186-1335).

use crate::{not, Command, Document, Error};
use mds_formats::key_pool::{Key, KeyPool};

/// Every record the pool holds, heads first.
fn each_key<K: Key>(pool: &mut KeyPool<K>, mut f: impl FnMut(&mut K)) {
    pool.heads_mut().iter_mut().for_each(&mut f);
    let at: Vec<u32> = pool.records().iter().map(|r| r.0).collect();
    for i in at {
        if let Some(k) = pool.get_mut(i) {
            f(k);
        }
    }
}

impl Document {
    /// [`Command::DeleteModel`], after the confirmation box.
    pub(crate) fn delete_model(&mut self, slot: u8) -> Result<(), Error> {
        let i = self
            .pmm
            .models
            .iter()
            .position(|m| m.slot == slot)
            .ok_or(not("no model in that slot"))?;
        let m = self.pmm.models.remove(i);
        self.models.remove(i);
        self.skeletons.remove(i);
        self.edit.models.remove(i);
        let found = i32::from(slot);
        let (sel, order) = (m.selection.combo_index, m.display_order);
        for m in &mut self.pmm.models {
            if m.selection.combo_index > sel {
                m.selection.combo_index -= 1;
            }
            if m.display_order > order {
                m.display_order -= 1;
            }
            // `DetachBoneBindings`, then the selectors of every display key.
            for p in &mut m.selector_pose {
                if p[2] == found {
                    (p[2], p[3]) = (-1, 0);
                }
            }
            each_key(&mut m.display_keys, |k| {
                for s in &mut k.selectors {
                    if s[0] == found {
                        *s = [-1, 0];
                    }
                }
            });
        }
        let a = &mut self.pmm.appearance;
        if a.camera_parent_model == found {
            (a.camera_parent_model, a.camera_parent_bone) = (-1, 0);
        }
        each_key(&mut self.pmm.camera, |k| {
            if k.parent_model == found {
                (k.parent_model, k.parent_bone) = (-1, 0);
            }
        });
        for acc in &mut self.pmm.accessories {
            if acc.state.parent_model == found {
                (acc.state.parent_model, acc.state.parent_bone) = (-1, 0);
            }
            each_key(&mut acc.keys, |k| {
                // The key keeps its bone and loses its visible flag.
                if k.parent_model == found {
                    k.parent_model = -1;
                    k.opacity_visible &= !1;
                }
            });
        }
        // The combo is set to its camera entry, then
        // `ApplyModelComboSelection`.
        self.apply(Command::SelectCameraMode)
    }
}
