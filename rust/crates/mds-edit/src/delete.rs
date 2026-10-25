//! `DeleteMarkedModelKeys` (VA 0x4A09E0).

use crate::link::{indices, links, rebuild_interpolation, slot, Link};
use crate::{Result, Rig, Tracks};
use mds_formats::key_pool::KeyPool;

/// Frees every marked record of one pool, in index order, as the C++ loop
/// does: `reset(pool, i, previous, next)` clears the record's own payload. A
/// record at or past `heads` is unlinked from its neighbours and its links
/// cleared; a head keeps its `next` and only loses its `previous`.
///
/// The unlink writes through whatever `previous` and `next` hold, so the
/// last key of a track writes `previous` of record 0, as in the original.
fn free_marked<K: Link>(
    pool: &mut KeyPool<K>,
    rig: &Rig,
    heads: u32,
    mut reset: impl FnMut(&mut KeyPool<K>, u32, u32, u32) -> Result<()>,
) -> Result<()> {
    for i in indices(pool, |k| k.allocated() != 0) {
        let (_, prev, next) = links(pool, i)?;
        slot(pool, rig, i)?.set_frame(0);
        if i >= heads {
            slot(pool, rig, prev)?.set_next(next);
            slot(pool, rig, next)?.set_previous(prev);
        }
        slot(pool, rig, i)?.set_allocated(0);
        reset(pool, i, prev, next)?;
        let rec = slot(pool, rig, i)?;
        if i >= heads {
            rec.set_next(0);
        }
        rec.set_previous(0);
    }
    Ok(())
}

impl Tracks {
    /// Deletes every marked key of the three pools. With automatic
    /// interpolation, the curves of the key after each deleted bone key (or
    /// before it, at the end of a track) are rebuilt.
    pub fn delete_marked(&mut self, rig: &Rig) -> Result<()> {
        // The display pool has one head (record 0) and the other pools one
        // per bone or morph.
        free_marked(&mut self.display, rig, 1, |p, i, _, _| {
            let k = slot(p, rig, i)?;
            k.visible = 1;
            k.ik_enabled
                .iter_mut()
                .take(rig.ik_chains.len())
                .for_each(|b| *b = 1);
            for s in k.selectors.iter_mut().take(rig.selectors.len()) {
                *s = [-1, 0];
            }
            Ok(())
        })?;
        free_marked(
            &mut self.morph,
            rig,
            rig.morphs.len() as u32,
            |p, i, _, _| {
                slot(p, rig, i)?.value = 0.0;
                Ok(())
            },
        )?;
        free_marked(
            &mut self.bone,
            rig,
            rig.bones.len() as u32,
            |p, i, prev, next| {
                let k = slot(p, rig, i)?;
                k.position = [0.0; 3];
                k.rotation = [0.0, 0.0, 0.0, 1.0];
                if rig.bones.get(i as usize).is_some_and(|b| b.rigid_body) {
                    k.physics_disabled = 0;
                }
                if rig.auto_interpolation {
                    let neighbour = if next != 0 { next } else { prev };
                    for lane in 0..4 {
                        rebuild_interpolation(p, rig, neighbour, lane)?;
                    }
                }
                Ok(())
            },
        )?;
        Ok(())
    }
}
