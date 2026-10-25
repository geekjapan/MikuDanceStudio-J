//! What the three key types share: the doubly linked track in a pool, and
//! the walk and splice of the C++ registrars.

use crate::{Error, Result, Rig};
use mds_formats::key_pool::{Key, KeyPool};
use mds_formats::pmm::{BoneKey, DisplayKey, MorphKey};

/// A key whose links and mark the editor writes. `allocated` is the mark
/// of "selected key" (the C++ `allocated` byte).
pub trait Link: Key + Clone {
    /// The record a never-used pool slot holds (zeroed memory, plus the
    /// loader's display defaults).
    fn blank(rig: &Rig) -> Self;
    fn set_frame(&mut self, frame: u32);
    fn set_previous(&mut self, index: u32);
    fn set_next(&mut self, index: u32);
    fn allocated(&self) -> u8;
    fn set_allocated(&mut self, mark: u8);
}

macro_rules! link_fields {
    () => {
        fn set_frame(&mut self, frame: u32) {
            self.frame = frame;
        }
        fn set_previous(&mut self, index: u32) {
            self.previous = index;
        }
        fn set_next(&mut self, index: u32) {
            self.next = index;
        }
        fn allocated(&self) -> u8 {
            self.allocated
        }
        fn set_allocated(&mut self, mark: u8) {
            self.allocated = mark;
        }
    };
}

impl Link for BoneKey {
    fn blank(_: &Rig) -> Self {
        BoneKey::default()
    }
    link_fields!();
}

impl Link for MorphKey {
    fn blank(_: &Rig) -> Self {
        MorphKey::default()
    }
    link_fields!();
}

impl Link for DisplayKey {
    fn blank(rig: &Rig) -> Self {
        DisplayKey {
            visible: 1,
            ik_enabled: vec![1; rig.ik_chains.len()],
            selectors: vec![[-1, 0]; rig.selectors.len()],
            ..DisplayKey::default()
        }
    }
    link_fields!();
}

/// A bone track head as the loader makes it: default Bezier curves and the
/// identity rotation.
pub(crate) fn bone_head() -> BoneKey {
    let mut k = BoneKey::default();
    reset_interpolation(&mut k);
    k.rotation[3] = 1.0;
    k
}

/// `ResetBoneInterpolation` for the four lanes.
pub(crate) fn reset_interpolation(k: &mut BoneKey) {
    for lane in 0..4 {
        reset_lane(k, lane);
    }
}

/// `ResetBoneInterpolation`: the default curve of one lane.
fn reset_lane(k: &mut BoneKey, lane: usize) {
    set_in(k, lane, 20, 20);
    set_out(k, lane, 107, 107);
}

/// The control point at the start of the curve (x, y).
fn set_in(k: &mut BoneKey, lane: usize, x: u8, y: u8) {
    k.interpolation[lane] = x;
    k.interpolation[lane + 4] = y;
}

/// The control point at the end of the curve.
fn set_out(k: &mut BoneKey, lane: usize, x: u8, y: u8) {
    k.interpolation[lane + 8] = x;
    k.interpolation[lane + 12] = y;
}

/// `RebuildBoneInterpolation` (VA 0x49D4D0): the automatic curve of one
/// lane at the key `index`, and the ends it shares with its neighbours.
/// Lanes 0 to 2 follow the position; lane 3 (rotation) and the track heads
/// get the default curve.
pub fn rebuild_interpolation(
    pool: &mut KeyPool<BoneKey>,
    rig: &Rig,
    index: u32,
    lane: usize,
) -> Result<()> {
    let heads = rig.bones.len() as u32;
    if lane >= 3 || index < heads {
        reset_lane(slot(pool, rig, index)?, lane);
        return Ok(());
    }
    let value = |pool: &KeyPool<BoneKey>, i: u32| -> Result<f32> {
        links(pool, i)?;
        Ok(pool.get(i).map_or(0.0, |k| k.position[lane]))
    };
    let (_, previous, next) = links(pool, index)?;
    let current = value(pool, index)?;
    let before = value(pool, previous)?;
    if before == current {
        reset_lane(slot(pool, rig, index)?, lane);
        return Ok(());
    }
    if previous < heads {
        set_in(slot(pool, rig, index)?, lane, 64, 0);
    } else {
        let earlier = value(pool, links(pool, previous)?.1)?;
        let (out, inn) = if (before - earlier) * (current - before) > 0.0 {
            ((87, 87), (40, 40))
        } else {
            ((64, 127), (64, 0))
        };
        set_out(slot(pool, rig, previous)?, lane, out.0, out.1);
        set_in(slot(pool, rig, index)?, lane, inn.0, inn.1);
    }
    if next == 0 {
        set_out(slot(pool, rig, index)?, lane, 64, 127);
        return Ok(());
    }
    let after = value(pool, next)?;
    let (out, inn) = if (after - current) * (current - before) <= 0.0 {
        ((64, 127), (64, 0))
    } else {
        ((87, 87), (40, 40))
    };
    set_out(slot(pool, rig, index)?, lane, out.0, out.1);
    set_in(slot(pool, rig, next)?, lane, inn.0, inn.1);
    Ok(())
}

/// The record at `index`, made from `blank` first if the pool never held
/// one (the C++ writes into zeroed memory there).
pub(crate) fn slot<'a, K: Link>(
    pool: &'a mut KeyPool<K>,
    rig: &Rig,
    index: u32,
) -> Result<&'a mut K> {
    if index >= pool.capacity() {
        return Err(Error::Corrupt);
    }
    if pool.get(index).is_none() {
        pool.insert(index, K::blank(rig)).ok_or(Error::Corrupt)?;
    }
    pool.get_mut(index).ok_or(Error::Corrupt)
}

/// `(frame, previous, next)` of a record; a never-used slot reads as zeros.
pub(crate) fn links<K: Key>(pool: &KeyPool<K>, index: u32) -> Result<(u32, u32, u32)> {
    if index >= pool.capacity() {
        return Err(Error::Corrupt);
    }
    Ok(pool
        .get(index)
        .map_or((0, 0, 0), |k| (k.frame(), k.previous(), k.next())))
}

/// Where a key of some frame goes on a track.
#[derive(Clone, Copy, Debug)]
pub(crate) enum Spot {
    /// A key at that frame exists.
    Exact(u32),
    /// Past the last key of the track.
    After(u32),
    /// Before this key, which is later than the frame.
    Before(u32),
}

/// The walk every registrar starts with: from the track head along `next`
/// to the first key at or after `frame`.
pub(crate) fn locate<K: Key>(pool: &KeyPool<K>, head: u32, frame: u32) -> Result<Spot> {
    let mut cur = head;
    let mut steps = 0u32;
    if links(pool, cur)?.0 < frame {
        loop {
            let next = links(pool, cur)?.2;
            if next == 0 {
                break;
            }
            cur = next;
            steps += 1;
            if steps > pool.capacity() {
                return Err(Error::Corrupt);
            }
            if links(pool, cur)?.0 >= frame {
                break;
            }
        }
        if links(pool, cur)?.0 < frame {
            return Ok(Spot::After(cur));
        }
    }
    Ok(if links(pool, cur)?.0 == frame {
        Spot::Exact(cur)
    } else {
        Spot::Before(cur)
    })
}

/// Links the free record `fresh` in at `spot` and gives it `frame`. The
/// other fields of `fresh` stay as they are, as in the C++. For `After`,
/// `fresh.next` is not written: a free record's `next` is 0.
pub(crate) fn attach<K: Link>(
    pool: &mut KeyPool<K>,
    rig: &Rig,
    spot: Spot,
    fresh: u32,
    frame: u32,
) -> Result<()> {
    match spot {
        Spot::Exact(_) => return Err(Error::Corrupt),
        Spot::After(cur) => {
            slot(pool, rig, cur)?.set_next(fresh);
            slot(pool, rig, fresh)?.set_previous(cur);
        }
        Spot::Before(cur) => {
            let prev = links(pool, cur)?.1;
            slot(pool, rig, prev)?.set_next(fresh);
            slot(pool, rig, fresh)?.set_previous(prev);
            slot(pool, rig, cur)?.set_previous(fresh);
            slot(pool, rig, fresh)?.set_next(cur);
        }
    }
    slot(pool, rig, fresh)?.set_frame(frame);
    Ok(())
}

/// The own-scan free-record search of `RegisterMorphKeyCurrent` and
/// `RegisterDisplayKeyCurrent`: from the first non-head record, no cursor.
pub(crate) fn scan_free<K: Key>(pool: &KeyPool<K>) -> Option<u32> {
    let mut i = pool.heads().len() as u32;
    while i < pool.capacity() && links(pool, i).ok()?.0 != 0 {
        i += 1;
    }
    (i < pool.capacity()).then_some(i)
}

pub(crate) fn full<K: Key>(pool: &KeyPool<K>, name: &'static str) -> Error {
    Error::Full {
        pool: name,
        limit: pool.capacity(),
    }
}

/// The cursor reset of `Reset*KeyCursor`: from `start`, past used records.
pub(crate) fn reset_cursor<K: Key>(pool: &KeyPool<K>, start: u32) -> u32 {
    let mut c = start;
    while c < pool.capacity() && links(pool, c).is_ok_and(|l| l.0 != 0) {
        c += 1;
    }
    c
}

/// Indices of the pool's records (heads first) for which `f` holds.
pub(crate) fn indices<K: Link>(pool: &KeyPool<K>, f: impl Fn(&K) -> bool) -> Vec<u32> {
    let heads = pool.heads().iter().enumerate().map(|(i, k)| (i as u32, k));
    let rest = pool.records().iter().map(|(i, k)| (*i, k));
    heads
        .chain(rest)
        .filter(|(_, k)| f(k))
        .map(|(i, _)| i)
        .collect()
}

pub(crate) fn clear_marks<K: Link>(pool: &mut KeyPool<K>) {
    for i in indices(pool, |k| k.allocated() != 0) {
        if let Some(k) = pool.get_mut(i) {
            k.set_allocated(0);
        }
    }
}
