//! Dragging the marked keys along the timeline: the remap of
//! `HandleMouseMove` (`src/window/ui_mousemove.cpp` 330-404, `RemapList`
//! 121-173, `RemapAccList` 178-224) over the records that the mouse-down
//! (`SelectionStats`, `src/window/ui_editor_click.cpp` 171-336, and
//! `CollectGlobalTimelineSelection`, `timeline_selection.cpp`) collects.

use crate::{not, Document, Error};
use mds_formats::key_pool::{Key, KeyPool};

/// The marked records of `pool` that `RemapList` may move, as `(index,
/// frame)` in frame order. The C++ `qsort` is not stable, but two records
/// of one track never share a frame, and a record only reads its own
/// track, so the order of equal frames does not matter.
fn records<K: Key>(
    pool: &KeyPool<K>,
    marked: impl Fn(&K) -> bool,
    movable: impl Fn(u32) -> bool,
) -> Vec<(u32, u32)> {
    let mut r: Vec<(u32, u32)> = pool
        .records()
        .iter()
        .filter(|(i, k)| marked(k) && movable(*i))
        .map(|(i, k)| (*i, k.frame()))
        .collect();
    r.sort_by_key(|&(i, f)| (f as i32, i));
    r
}

/// One record of `RemapList`: the record at `index`, at `start` when the
/// drag began, moved by `row` frames but kept between its neighbours. The
/// new frame, for the maxima of a forward move.
fn remap<K: Key>(
    pool: &mut KeyPool<K>,
    index: u32,
    start: u32,
    row: i32,
    frame_of: fn(&mut K) -> &mut u32,
) -> Option<u32> {
    let frame = |pool: &KeyPool<K>, i| pool.get(i).map_or(0, |k| k.frame()) as i32;
    let k = pool.get(index)?;
    let (previous, next) = (k.previous(), k.next());
    let to = row.wrapping_add(start as i32);
    let new = if row == 0 {
        Some(start as i32)
    } else if row < 0 {
        let pf = frame(pool, previous);
        if pf.wrapping_add(1) < to {
            (to > 0).then_some(to)
        } else {
            Some(pf.wrapping_add(1))
        }
    } else if next == 0 {
        Some(to)
    } else {
        let nf = frame(pool, next);
        Some(if nf.wrapping_sub(1) > to {
            to
        } else {
            nf.wrapping_sub(1)
        })
    };
    let k = pool.get_mut(index)?;
    if let Some(f) = new {
        *frame_of(k) = f as u32;
    }
    Some(*frame_of(k))
}

/// `RemapList` over the records of one list: forward moves walk from the
/// last frame down, so a key's next neighbour has moved before it.
fn remap_list<K: Key>(
    pool: &mut KeyPool<K>,
    recs: &[(u32, u32)],
    row: i32,
    frame_of: fn(&mut K) -> &mut u32,
    mut moved: impl FnMut(u32),
) {
    if row > 0 {
        for &(i, f) in recs.iter().rev() {
            if let Some(f) = remap(pool, i, f, row, frame_of) {
                moved(f);
            }
        }
    } else {
        for &(i, f) in recs {
            remap(pool, i, f, row, frame_of);
        }
    }
}

impl Document {
    /// [`crate::Command::MoveSelectedKeys`].
    pub(crate) fn move_selected_keys(&mut self, row: i32) -> Result<(), Error> {
        if self.camera_mode() {
            self.move_global_keys(row);
            self.refresh_context();
            return Ok(());
        }
        let i = self.active().ok_or(not("no model in the selected slot"))?;
        // The mouse-down's undo entry (`ui_editor_click.cpp` 189-258): the
        // pose and every marked bone record, when one is marked.
        self.push_marked_undo(i);
        let m = &mut self.pmm.models[i];
        let (bones, morphs) = (
            m.bone_keys.heads().len() as u32,
            m.morph_keys.heads().len() as u32,
        );
        let display = records(&m.display_keys, |k| k.allocated != 0, |i| i > 0);
        let morph = records(&m.morph_keys, |k| k.allocated != 0, |i| i >= morphs);
        let bone = records(&m.bone_keys, |k| k.allocated != 0, |i| i >= bones);
        let mut max = m.selection.max_frame;
        let last = &mut self.pmm.timeline.last_registered_frame;
        // `if (*maxModel < frame) *maxModel = frame; if (last < *maxModel)
        // last = *maxModel`, both unsigned.
        let mut bump = |f: u32| {
            max = max.max(f);
            if (*last as u32) < max {
                *last = max as i32;
            }
        };
        remap_list(
            &mut m.display_keys,
            &display,
            row,
            |k| &mut k.frame,
            &mut bump,
        );
        remap_list(&mut m.morph_keys, &morph, row, |k| &mut k.frame, &mut bump);
        remap_list(&mut m.bone_keys, &bone, row, |k| &mut k.frame, &mut bump);
        m.selection.max_frame = max;
        self.seek(i);
        Ok(())
    }

    /// The camera-mode lists: camera, light, self shadow, gravity, then the
    /// accessories, whose records are sorted together over every slot.
    fn move_global_keys(&mut self, row: i32) {
        let p = &mut self.pmm;
        let last = &mut p.timeline.last_registered_frame;
        let mut bump = |f: u32| {
            if (*last as u32) < f {
                *last = f as i32;
            }
        };
        let any = |i| i > 0;
        let r = records(&p.camera, |k| k.selected != 0, any);
        remap_list(&mut p.camera, &r, row, |k| &mut k.frame, &mut bump);
        let r = records(&p.light, |k| k.selected != 0, any);
        remap_list(&mut p.light, &r, row, |k| &mut k.frame, &mut bump);
        let r = records(&p.self_shadow, |k| k.selected != 0, any);
        remap_list(&mut p.self_shadow, &r, row, |k| &mut k.frame, &mut bump);
        let r = records(&p.gravity, |k| k.selected != 0, any);
        remap_list(&mut p.gravity, &r, row, |k| &mut k.frame, &mut bump);
        let mut acc: Vec<(usize, u32, u32)> = Vec::new();
        for (a, x) in p.accessories.iter().enumerate() {
            let r = records(&x.keys, |k| k.selected != 0, any);
            acc.extend(r.into_iter().map(|(i, f)| (a, i, f)));
        }
        acc.sort_by_key(|&(a, i, f)| (f as i32, i, p.accessories[a].slot));
        let mut each = |&(a, i, f): &(usize, u32, u32)| {
            let keys = &mut p.accessories[a].keys;
            remap(keys, i, f, row, |k| &mut k.frame)
        };
        if row > 0 {
            for r in acc.iter().rev() {
                if let Some(f) = each(r) {
                    bump(f);
                }
            }
        } else {
            acc.iter().for_each(|r| {
                each(r);
            });
        }
    }
}
