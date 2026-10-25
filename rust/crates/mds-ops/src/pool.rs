//! Record access shared by the operations: the C++ arrays read with absent
//! records as zeros, and writes that create the record they land on.

use crate::{Error, Result};
use mds_formats::key_pool::{Key, KeyPool};
use mds_formats::pmm::{
    AccessoryKey, BoneKey, CameraKey, DisplayKey, GravityKey, LightKey, MorphKey, SelfShadowKey,
};

/// A key whose links and selection mark the operations write. The mark is
/// the `allocated` byte of the model keys and the `selected` byte of the
/// global keys.
pub(crate) trait Rec: Key + Clone + Default {
    fn set_frame(&mut self, frame: u32);
    fn set_previous(&mut self, index: u32);
    fn set_next(&mut self, index: u32);
    fn mark(&self) -> u8;
    fn set_mark(&mut self, mark: u8);
}

macro_rules! rec {
    ($($t:ty => $mark:ident),*) => {$(
        impl Rec for $t {
            fn set_frame(&mut self, frame: u32) {
                self.frame = frame;
            }
            fn set_previous(&mut self, index: u32) {
                self.previous = index;
            }
            fn set_next(&mut self, index: u32) {
                self.next = index;
            }
            fn mark(&self) -> u8 {
                self.$mark
            }
            fn set_mark(&mut self, mark: u8) {
                self.$mark = mark;
            }
        }
    )*};
}
rec!(
    BoneKey => allocated,
    MorphKey => allocated,
    DisplayKey => allocated,
    CameraKey => selected,
    LightKey => selected,
    GravityKey => selected,
    SelfShadowKey => selected,
    AccessoryKey => selected
);

/// `(frame, previous, next)` of a record; a slot the pool never held reads
/// as zeros.
pub(crate) fn links<K: Key>(pool: &KeyPool<K>, index: u32) -> Result<(u32, u32, u32)> {
    if index >= pool.capacity() {
        return Err(Error::Corrupt);
    }
    Ok(pool
        .get(index)
        .map_or((0, 0, 0), |k| (k.frame(), k.previous(), k.next())))
}

/// A copy of the record, zeros for a slot the pool never held.
pub(crate) fn read<K: Rec>(pool: &KeyPool<K>, index: u32) -> Result<K> {
    if index >= pool.capacity() {
        return Err(Error::Corrupt);
    }
    Ok(pool.get(index).cloned().unwrap_or_default())
}

/// The record at `index`, made from zeros first if the pool never held one
/// (the C++ writes into zeroed memory there).
pub(crate) fn slot<K: Rec>(pool: &mut KeyPool<K>, index: u32) -> Result<&mut K> {
    if index >= pool.capacity() {
        return Err(Error::Corrupt);
    }
    if pool.get(index).is_none() {
        pool.insert(index, K::default()).ok_or(Error::Corrupt)?;
    }
    pool.get_mut(index).ok_or(Error::Corrupt)
}

/// Indices of the heads and records for which `f(index, key)` holds, in
/// index order.
pub(crate) fn indices<K: Rec>(pool: &KeyPool<K>, f: impl Fn(u32, &K) -> bool) -> Vec<u32> {
    let heads = pool.heads().iter().enumerate().map(|(i, k)| (i as u32, k));
    let rest = pool.records().iter().map(|(i, k)| (*i, k));
    heads
        .chain(rest)
        .filter(|(i, k)| f(*i, k))
        .map(|(i, _)| i)
        .collect()
}

/// Like [`indices`] without the heads: the records at or past the number of
/// bone, morph or display heads.
pub(crate) fn record_indices<K: Rec>(pool: &KeyPool<K>, f: impl Fn(&K) -> bool) -> Vec<u32> {
    pool.records()
        .iter()
        .filter(|(_, k)| f(k))
        .map(|(i, _)| *i)
        .collect()
}

/// The unlink every frame-line delete does: `prev.next = next` then
/// `next.previous = prev`, through whatever the two links hold (a track
/// that ended at its last key writes `previous` of record 0).
pub(crate) fn unlink<K: Rec>(pool: &mut KeyPool<K>, prev: u32, next: u32) -> Result<()> {
    slot(pool, prev)?.set_next(next);
    slot(pool, next)?.set_previous(prev);
    Ok(())
}

/// Runs `f` on a copy of the pool and keeps the copy only when `f` succeeds,
/// so an operation that finds a broken link leaves the pool as it was.
pub(crate) fn atomic<K: Rec, T>(
    pool: &mut KeyPool<K>,
    f: impl FnOnce(&mut KeyPool<K>) -> Result<T>,
) -> Result<T> {
    let mut work = pool.clone();
    let out = f(&mut work)?;
    *pool = work;
    Ok(out)
}

/// Sets the mark of every head and record to `f(index, key)`, the
/// "clear every flag, then set it where it applies" loop of the select-all
/// commands.
pub(crate) fn set_marks<K: Rec>(pool: &mut KeyPool<K>, f: impl Fn(u32, &K) -> bool) {
    for i in indices(pool, |_, _| true) {
        let on = pool.get(i).is_some_and(|k| f(i, k));
        if let Some(k) = pool.get_mut(i) {
            k.set_mark(u8::from(on));
        }
    }
}

/// A walk bound for the loops that follow `next`: more steps than the pool
/// has records means a cycle.
pub(crate) fn walk_limit<K: Key>(pool: &KeyPool<K>) -> u32 {
    pool.capacity()
}
