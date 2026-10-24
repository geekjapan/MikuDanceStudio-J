//! `KeyPool<K>`: one PMM key track pool, modelled on the C++ arrays that
//! `src/io/pmm_save.cpp` writes.
//!
//! The C++ pool is a fixed array of `capacity` records. Records
//! `0..heads` are the track heads (bone `i` and morph `i` at index `i`, the
//! display and global tracks at index 0). The other records are free when
//! their frame is 0. Each record links to the previous and next record of its
//! track by raw pool index, and the file stores those indices. So the pool
//! keeps the indices as read, keeps every key at its C++ index, and keeps the
//! gaps that freed keys leave.
//!
//! Storage is sparse (heads, then the occupied records sorted by index), so
//! a 600000-record bone pool costs only its keys.

use crate::io::{Reader, Result, Writer};

/// Pool capacities of the C++ port (x64 layout; x86 files fit inside).
pub const BONE_KEY_CAPACITY: u32 = 600_000;
pub const MORPH_KEY_CAPACITY: u32 = 20_000;
pub const DISPLAY_KEY_CAPACITY: u32 = 1_000;
/// Camera, light, gravity, self-shadow and accessory tracks.
pub const GLOBAL_KEY_CAPACITY: u32 = 10_000;

/// Most sparse records the C++ reader accepts in one track.
const MAX_SPARSE: usize = 100_000;

/// A pool record: a frame and the raw links of its track.
pub trait Key {
    fn frame(&self) -> u32;
    fn previous(&self) -> u32;
    fn next(&self) -> u32;
}

#[derive(Clone, Debug)]
pub struct KeyPool<K> {
    capacity: u32,
    heads: Vec<K>,
    /// Occupied non-head records, strictly increasing index in
    /// `heads.len()..capacity`.
    records: Vec<(u32, K)>,
}

impl<K: Key> KeyPool<K> {
    /// A pool with these heads and no other records.
    pub fn new(capacity: u32, heads: Vec<K>) -> Option<Self> {
        (heads.len() <= capacity as usize).then_some(KeyPool {
            capacity,
            heads,
            records: Vec::new(),
        })
    }

    pub fn capacity(&self) -> u32 {
        self.capacity
    }
    pub fn heads(&self) -> &[K] {
        &self.heads
    }
    pub fn heads_mut(&mut self) -> &mut [K] {
        &mut self.heads
    }
    /// The non-head records as `(pool index, key)`, in index order.
    pub fn records(&self) -> &[(u32, K)] {
        &self.records
    }

    fn first_free(&self) -> u32 {
        self.heads.len() as u32
    }

    fn position(&self, index: u32) -> std::result::Result<usize, usize> {
        self.records.binary_search_by_key(&index, |r| r.0)
    }

    pub fn get(&self, index: u32) -> Option<&K> {
        if index < self.first_free() {
            return self.heads.get(index as usize);
        }
        self.position(index).ok().map(|p| &self.records[p].1)
    }

    pub fn get_mut(&mut self, index: u32) -> Option<&mut K> {
        if index < self.first_free() {
            return self.heads.get_mut(index as usize);
        }
        let p = self.position(index).ok()?;
        Some(&mut self.records[p].1)
    }

    /// Puts `key` at a non-head `index`, returning the record it replaces.
    /// `None` when `index` is a head or outside the pool.
    pub fn insert(&mut self, index: u32, key: K) -> Option<Option<K>> {
        if index < self.first_free() || index >= self.capacity {
            return None;
        }
        Some(match self.position(index) {
            Ok(p) => Some(std::mem::replace(&mut self.records[p].1, key)),
            Err(p) => {
                self.records.insert(p, (index, key));
                None
            }
        })
    }

    /// Frees a non-head record. Its neighbours keep their links; relinking
    /// is the caller's job, as in the C++ delete.
    pub fn remove(&mut self, index: u32) -> Option<K> {
        let p = self.position(index).ok()?;
        Some(self.records.remove(p).1)
    }

    /// The free-record scan of `kfa::AllocateFromCursor`
    /// (`src/model/keyframe_common.hpp`). The cursor never starts below the
    /// first non-head record, skips records whose frame is not 0, and stops
    /// at capacity. The cursor is left on the record found, or at capacity.
    pub fn allocate_from_cursor(&self, cursor: &mut u32) -> Option<u32> {
        *cursor = (*cursor).max(self.first_free());
        let mut p = self.position(*cursor).unwrap_or_else(|p| p);
        while *cursor < self.capacity {
            match self.records.get(p) {
                Some((i, k)) if *i == *cursor && k.frame() != 0 => {
                    *cursor += 1;
                    p += 1;
                }
                _ => return Some(*cursor),
            }
        }
        None
    }

    /// The well-formed-track property of `verify-keyframe-pool`: every
    /// track starts at its head with frame 0, `next` and `previous` agree,
    /// frames strictly increase, no record sits on two tracks or is linked
    /// as a non-first head, and every non-head record with a frame is on a
    /// track.
    pub fn validate_tracks(&self) -> std::result::Result<(), String> {
        let mut on_track = vec![false; self.records.len()];
        for t in 0..self.first_free() {
            let head = &self.heads[t as usize];
            if head.frame() != 0 {
                return Err(format!("head {t} has frame {}", head.frame()));
            }
            let (mut cur, mut frame, mut next) = (t, 0, head.next());
            while next != 0 {
                if next < self.first_free() {
                    return Err(format!("{cur} links into head record {next}"));
                }
                let p = self
                    .position(next)
                    .map_err(|_| format!("{cur} links to empty record {next}"))?;
                if std::mem::replace(&mut on_track[p], true) {
                    return Err(format!("record {next} is on two tracks"));
                }
                let rec = &self.records[p].1;
                if rec.previous() != cur {
                    return Err(format!(
                        "record {next} previous {} != {cur}",
                        rec.previous()
                    ));
                }
                if rec.frame() <= frame {
                    return Err(format!("record {next} frame does not increase"));
                }
                (cur, frame, next) = (next, rec.frame(), rec.next());
            }
        }
        match self
            .records
            .iter()
            .zip(&on_track)
            .find(|((_, k), on)| k.frame() != 0 && !**on)
        {
            Some(((i, _), _)) => Err(format!("record {i} is on no track")),
            None => Ok(()),
        }
    }

    /// Reads the file layout: `heads` dense records, an i32 count, then
    /// `(i32 index, record)` pairs. Only the order the C++ writer emits is
    /// accepted (index strictly increasing inside the pool, frame not 0), so
    /// every pool that reads also writes back to the same bytes.
    pub(crate) fn read(
        r: &mut Reader,
        heads: usize,
        capacity: u32,
        min_size: usize,
        mut item: impl FnMut(&mut Reader) -> Result<K>,
    ) -> Result<Self> {
        if heads > capacity as usize {
            return Err(r.invalid("more track heads than pool records"));
        }
        let heads = r.vec(heads, min_size, &mut item)?;
        let n = r.i32()?;
        let n = usize::try_from(n).map_err(|_| r.invalid("negative key count"))?;
        r.limit(n, MAX_SPARSE, "too many keys")?;
        let mut last = heads.len() as i64 - 1;
        let records = r.vec(n, 4 + min_size, |r| {
            let index = r.i32()?;
            if i64::from(index) <= last || index as u32 >= capacity {
                return Err(r.invalid("key index out of order or outside the pool"));
            }
            last = index.into();
            let key = item(r)?;
            if key.frame() == 0 {
                return Err(r.invalid("stored key has frame 0"));
            }
            Ok((index as u32, key))
        })?;
        Ok(KeyPool {
            capacity,
            heads,
            records,
        })
    }

    /// Writes the layout `read` takes, scanning the pool as
    /// `pmm_save.cpp` does: heads, then every record whose frame is not 0.
    pub(crate) fn write(
        &self,
        w: &mut Writer,
        heads: usize,
        mut item: impl FnMut(&mut Writer, &K) -> Result<()>,
    ) -> Result<()> {
        if self.heads.len() != heads {
            return Err(w.invalid("track head count differs from the table"));
        }
        for k in &self.heads {
            item(w, k)?;
        }
        let live = || self.records.iter().filter(|(_, k)| k.frame() != 0);
        w.count32(live().count())?;
        for (i, k) in live() {
            w.u32(*i);
            item(w, k)?;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Clone, Debug, PartialEq)]
    struct K(u32, u32, u32);
    impl Key for K {
        fn frame(&self) -> u32 {
            self.0
        }
        fn previous(&self) -> u32 {
            self.1
        }
        fn next(&self) -> u32 {
            self.2
        }
    }

    fn pool() -> KeyPool<K> {
        // Two tracks: 0 -> 2 -> 4 and 1 -> 3; index 5 is free (frame 0).
        let mut p = KeyPool::new(8, vec![K(0, 0, 2), K(0, 0, 3)]).unwrap();
        p.insert(2, K(10, 0, 4)).unwrap();
        p.insert(3, K(5, 1, 0)).unwrap();
        p.insert(4, K(20, 2, 0)).unwrap();
        p.insert(5, K(0, 0, 0)).unwrap();
        p
    }

    #[test]
    fn allocation_follows_allocate_from_cursor() {
        let p = pool();
        // A cursor below the first non-head record starts there.
        let mut c = 0;
        assert_eq!(p.allocate_from_cursor(&mut c), Some(5));
        assert_eq!(c, 5);
        // A record with frame 0 counts as free, an absent one too.
        let mut c = 6;
        assert_eq!(p.allocate_from_cursor(&mut c), Some(6));
        // Stops at capacity without reading past it.
        let mut full = KeyPool::new(3, vec![K(0, 0, 0)]).unwrap();
        full.insert(1, K(1, 0, 0)).unwrap();
        full.insert(2, K(2, 0, 0)).unwrap();
        let mut c = 1;
        assert_eq!(full.allocate_from_cursor(&mut c), None);
        assert_eq!(c, 3);
    }

    #[test]
    fn tracks_validate_and_breaks_are_named() {
        let mut p = pool();
        assert_eq!(p.validate_tracks(), Ok(()));
        assert!(p.insert(0, K(1, 0, 0)).is_none(), "heads are not records");
        p.get_mut(4).unwrap().1 = 3;
        assert!(p.validate_tracks().unwrap_err().contains("previous"));
        let mut p = pool();
        p.insert(6, K(7, 0, 0)).unwrap();
        assert!(p.validate_tracks().unwrap_err().contains("no track"));
    }

    #[test]
    fn freed_record_is_not_written() {
        let p = pool();
        let mut w = Writer::default();
        p.write(&mut w, 2, |w, k| {
            w.u32(k.0);
            Ok(())
        })
        .unwrap();
        // heads 0,0; count 3 (record 5 has frame 0); (2,10) (3,5) (4,20)
        let words: Vec<u32> = w
            .out
            .chunks(4)
            .map(|c| u32::from_le_bytes(c.try_into().unwrap()))
            .collect();
        assert_eq!(words, [0, 0, 3, 2, 10, 3, 5, 4, 20]);
    }
}
