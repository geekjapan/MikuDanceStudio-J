//! Automatic interpolation (checkbox 530, checked at start-up):
//! `RebuildBoneInterpolation` (`src/model/model_keyframe_edit.cpp`, VA
//! 0x0049D4D0) after a bone register and a bone delete. `mds-edit` runs
//! both with the box clear; the rebuild only rewrites curves, so it runs
//! here on the result, over the links and positions each C++ step saw.

use mds_formats::key_pool::KeyPool;
use mds_formats::pmm::BoneKey;
use std::collections::{BTreeMap, BTreeSet};

/// The links and positions a rebuild reads.
pub(crate) trait View {
    fn links(&self, i: u32) -> (u32, u32);
    fn position(&self, i: u32, lane: usize) -> f32;
}

/// The pool as it is.
pub(crate) struct Live<'a>(pub &'a KeyPool<BoneKey>);

impl View for Live<'_> {
    fn links(&self, i: u32) -> (u32, u32) {
        self.0.get(i).map_or((0, 0), |k| (k.previous, k.next))
    }
    fn position(&self, i: u32, lane: usize) -> f32 {
        self.0.get(i).map_or(0.0, |k| k.position[lane])
    }
}

fn curve(pool: &mut KeyPool<BoneKey>, i: u32, at: usize, a: u8, b: u8) {
    if let Some(k) = pool.get_mut(i) {
        k.interpolation[at] = a;
        k.interpolation[at + 4] = b;
    }
}

/// `RebuildBoneInterpolation` of record `index`, every lane.
pub(crate) fn rebuild(pool: &mut KeyPool<BoneKey>, v: &dyn View, index: u32) {
    let heads = pool.heads().len() as u32;
    for lane in 0..4 {
        if lane >= 3 || index < heads {
            curve(pool, index, lane, 20, 20);
            curve(pool, index, lane + 8, 107, 107);
            continue;
        }
        let (previous, next) = v.links(index);
        let current = v.position(index, lane);
        let before = v.position(previous, lane);
        if before == current {
            curve(pool, index, lane, 20, 20);
            curve(pool, index, lane + 8, 107, 107);
            continue;
        }
        if previous < heads {
            curve(pool, index, lane, 64, 0);
        } else {
            let earlier = v.position(v.links(previous).0, lane);
            if (before - earlier) * (current - before) > 0.0 {
                curve(pool, previous, lane + 8, 87, 87);
                curve(pool, index, lane, 40, 40);
            } else {
                curve(pool, previous, lane + 8, 64, 127);
                curve(pool, index, lane, 64, 0);
            }
        }
        if next == 0 {
            curve(pool, index, lane + 8, 64, 127);
            continue;
        }
        let after = v.position(next, lane);
        if (after - current) * (current - before) <= 0.0 {
            curve(pool, index, lane + 8, 64, 127);
            curve(pool, next, lane, 64, 0);
        } else {
            curve(pool, index, lane + 8, 87, 87);
            curve(pool, next, lane, 40, 40);
        }
    }
}

/// The pool during `DeleteMarkedKeyframes`: the records before the current
/// one in index order are unlinked, and their positions zeroed.
pub(crate) struct Deleting<'a> {
    pub before: &'a KeyPool<BoneKey>,
    pub links: BTreeMap<u32, (u32, u32)>,
    pub deleted: BTreeSet<u32>,
}

impl View for Deleting<'_> {
    fn links(&self, i: u32) -> (u32, u32) {
        self.links
            .get(&i)
            .copied()
            .unwrap_or_else(|| Live(self.before).links(i))
    }
    fn position(&self, i: u32, lane: usize) -> f32 {
        if self.deleted.contains(&i) {
            0.0
        } else {
            Live(self.before).position(i, lane)
        }
    }
}

/// The rebuilds of a bone delete of the marked records of `before`, onto
/// `after` (the pool once deleted): per marked record in index order, its
/// unlink, then the rebuild of its next record, else its previous one.
pub(crate) fn after_delete(before: &KeyPool<BoneKey>, after: &mut KeyPool<BoneKey>) {
    let heads = before.heads().len() as u32;
    let marked: Vec<u32> = before
        .heads()
        .iter()
        .enumerate()
        .map(|(i, k)| (i as u32, k))
        .chain(before.records().iter().map(|(i, k)| (*i, k)))
        .filter(|(_, k)| k.allocated != 0)
        .map(|(i, _)| i)
        .collect();
    let mut v = Deleting {
        before,
        links: BTreeMap::new(),
        deleted: BTreeSet::new(),
    };
    for i in marked {
        let (prev, next) = v.links(i);
        if i >= heads {
            let p = v.links(prev);
            v.links.insert(prev, (p.0, next));
            let n = v.links(next);
            v.links.insert(next, (prev, n.1));
        }
        v.deleted.insert(i);
        rebuild(after, &v, if next != 0 { next } else { prev });
        let own = v.links(i);
        v.links
            .insert(i, if i >= heads { (0, 0) } else { (0, own.1) });
    }
}
