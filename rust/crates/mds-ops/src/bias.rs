//! Center position bias (menu 219) and physics ON/OFF frame conversion
//! (menu 275): the two operations that read the model's bone table.

use crate::model::{active_model, check};
use crate::pool::{indices, links, walk_limit};
use crate::{Error, ModelFacts, Result};
use mds_formats::pmm::Pmm;

/// Menu 219, the model-offset dialog (`src/window/command_file_menu.cpp`
/// 1042-1093): adds `offset` to the position of every marked bone key whose
/// bone is a root (`parent == -1`). The bone of a key is found by following
/// `previous` from the record until the index is below the bone count, so a
/// marked head counts as the key of its own bone.
///
/// The gate is the mark (`allocated`), not "every root-bone key": keys that
/// are not selected keep their position. The caller sets the physics-reset
/// flag, which the C++ sets here.
pub fn center_position_bias(pmm: &mut Pmm, facts: &ModelFacts, offset: [f32; 3]) -> Result<()> {
    if pmm.settings.options[0] != 0 {
        return Err(Error::WrongMode);
    }
    let m = active_model(pmm)?;
    check(&pmm.models[m], facts)?;
    let pool = &mut pmm.models[m].bone_keys;
    let bones = pool.heads().len() as u32;
    let mut roots = Vec::new();
    for i in indices(pool, |_, k| k.allocated != 0) {
        let mut bone = i;
        let mut steps = 0;
        while bone >= bones {
            bone = links(pool, bone)?.1;
            steps += 1;
            if steps > walk_limit(pool) {
                return Err(Error::Corrupt);
            }
        }
        if facts.bones[bone as usize].parent == -1 {
            roots.push(i);
        }
    }
    for i in roots {
        if let Some(k) = pool.get_mut(i) {
            for (p, o) in k.position.iter_mut().zip(offset) {
                *p += o;
            }
        }
    }
    Ok(())
}

/// Menu 275, `ApplyPhysicsOnOff` (`src/window/misc_dialogs.cpp` 652-768):
/// sets `physics_disabled` of every marked key of every bone that has a
/// rigid body, walking the bone's track from its head. The dialog's combo
/// choice 0 ("ON (X mark)") is `physics_disabled = false`, choice 1 ("OFF")
/// is `true`. Nothing happens when no such key is marked.
pub fn set_physics_on_off(pmm: &mut Pmm, facts: &ModelFacts, physics_disabled: bool) -> Result<()> {
    let m = active_model(pmm)?;
    check(&pmm.models[m], facts)?;
    let pool = &mut pmm.models[m].bone_keys;
    let mut hit = Vec::new();
    for (bone, _) in facts.bones.iter().enumerate().filter(|(_, f)| f.rigid_body) {
        let mut cur = bone as u32;
        let mut steps = 0;
        loop {
            if pool.get(cur).is_some_and(|k| k.allocated != 0) {
                hit.push(cur);
            }
            let next = links(pool, cur)?.2;
            if next == 0 {
                break;
            }
            cur = next;
            steps += 1;
            if steps > walk_limit(pool) {
                return Err(Error::Corrupt);
            }
        }
    }
    for i in hit {
        if let Some(k) = pool.get_mut(i) {
            k.physics_disabled = u8::from(physics_disabled);
        }
    }
    Ok(())
}
