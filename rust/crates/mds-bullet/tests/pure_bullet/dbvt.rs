use crate::core::{
    dbvt::{Aabb, Dbvt, DbvtPolicy},
    math::Vec3,
    pair_cache::ProxyKey,
};

fn words(line: &str) -> Vec<u32> {
    line.split(',').map(|word| word.parse().unwrap()).collect()
}
fn box_from(words: &[u32]) -> Aabb {
    Aabb {
        min: Vec3(std::array::from_fn(|i| f32::from_bits(words[i]))),
        max: Vec3(std::array::from_fn(|i| f32::from_bits(words[i + 3]))),
    }
}
fn bits(aabb: Aabb) -> Vec<u32> {
    aabb.min
        .0
        .into_iter()
        .chain(aabb.max.0)
        .map(f32::to_bits)
        .collect()
}

#[test]
fn actual_windows_51_numeric_rows_preserve_both_merge_orders() {
    let inputs: Vec<_> = include_str!("../dbvt_data/inputs.tsv").lines().collect();
    let inline: Vec<_> = include_str!("../dbvt_data/inline-aabb.tsv")
        .lines()
        .collect();
    let archive: Vec<_> = include_str!("../dbvt_data/archive-merge.tsv")
        .lines()
        .collect();
    let intersect: Vec<_> = include_str!("../dbvt_data/archive-intersect.tsv")
        .lines()
        .collect();
    assert_eq!(
        [inputs.len(), inline.len(), archive.len(), intersect.len()],
        [51; 4]
    );
    let mut generic_mismatches = 0;
    for id in 0..51 {
        let input: Vec<u32> = inputs[id]
            .split_whitespace()
            .map(|word| word.parse().unwrap())
            .collect();
        assert_eq!(input.len(), 12);
        let (a, b) = (box_from(&input[..6]), box_from(&input[6..]));
        let mut actual = vec![id as u32, DbvtPolicy::MmdWin64Sse.intersects(a, b) as u32];
        actual.extend(bits(a.merge(b)));
        actual.extend(bits(b.merge(a)));
        assert_eq!(actual, words(inline[id]), "inline case {id}");
        assert_eq!(words(intersect[id]), [id as u32, actual[1]]);
        let mut merged = vec![id as u32];
        for pair in [[a, b], [b, a]] {
            let mut tree = Dbvt::new(DbvtPolicy::MmdWin64Sse);
            for (key, volume) in pair.into_iter().enumerate() {
                tree.insert(ProxyKey(key as u32), volume);
            }
            merged.extend(bits(tree.bounds().unwrap()));
        }
        assert_eq!(merged, words(archive[id]), "archive case {id}");
        generic_mismatches +=
            usize::from(DbvtPolicy::GenericReference.intersects(a, b) as u32 != actual[1]);
    }
    assert_eq!(generic_mismatches, 24);
}

#[test]
fn actual_windows_directed_select_and_genuine_generic_are_distinct() {
    for (policy, expected) in [
        (DbvtPolicy::MmdWin64Sse, vec![3, 2, 1]),
        (DbvtPolicy::GenericReference, vec![2, 3, 1]),
    ] {
        let mut tree = Dbvt::new(policy);
        for (i, point) in [[0.5, 8388608.0, 0.5], [1.0, 8388608.0, 0.0], [0.0; 3]]
            .into_iter()
            .enumerate()
        {
            tree.insert(
                ProxyKey(i as u32 + 1),
                Aabb {
                    min: Vec3(point),
                    max: Vec3(point),
                },
            );
        }
        let mut events = Vec::new();
        tree.collide_volume(
            Aabb {
                min: Vec3([-1.0; 3]),
                max: Vec3([2.0, 8388609.0, 2.0]),
            },
            |key| events.push(key.0),
        );
        assert_eq!(events, expected);
        if policy == DbvtPolicy::MmdWin64Sse {
            let native: Vec<u32> = include_str!("../dbvt_data/select.tsv")
                .trim()
                .split(',')
                .filter(|s| !s.is_empty())
                .map(|s| s.parse().unwrap())
                .collect();
            assert_eq!(events, native);
        }
    }
}

#[test]
fn root_bounds_and_stored_leaf_tt_survive_update_and_clear() {
    for policy in [DbvtPolicy::MmdWin64Sse, DbvtPolicy::GenericReference] {
        let mut tree = Dbvt::new(policy);
        assert_eq!(tree.bounds(), None);
        let volume = Aabb {
            min: Vec3([0.0; 3]),
            max: Vec3([1.0; 3]),
        };
        tree.insert(ProxyKey(1), volume);
        tree.collide_leaf(&tree, ProxyKey(1), |_, _| panic!("self leaf"));
        tree.insert(ProxyKey(2), volume);
        let mut events = Vec::new();
        tree.collide_leaf(&tree, ProxyKey(1), |a, b| events.push((a, b)));
        assert_eq!(events, [(ProxyKey(2), ProxyKey(1))]);
        let far = Aabb {
            min: Vec3([5.0; 3]),
            max: Vec3([6.0; 3]),
        };
        tree.update(ProxyKey(1), far);
        tree.collide_leaf(&tree, ProxyKey(1), |_, _| {
            panic!("must use updated stored leaf")
        });
        assert_eq!(tree.bounds(), Some(volume.merge(far)));
        tree.clear();
        assert_eq!(tree.leaf_count(), 2);
        assert_eq!(tree.bounds(), None);
        tree.insert(ProxyKey(3), far);
        assert_eq!(tree.bounds(), Some(far));
    }
}

#[test]
#[should_panic(expected = "cross-tree DBVT policies must match")]
fn cross_tree_rejects_mixed_policy_even_when_empty() {
    Dbvt::new(DbvtPolicy::MmdWin64Sse)
        .collide_tree(&Dbvt::new(DbvtPolicy::GenericReference), |_, _| {});
}

#[test]
#[should_panic(expected = "cross-tree DBVT policies must match")]
fn cross_leaf_rejects_mixed_policy() {
    let mut other = Dbvt::new(DbvtPolicy::GenericReference);
    other.insert(
        ProxyKey(1),
        Aabb {
            min: Vec3([0.0; 3]),
            max: Vec3([1.0; 3]),
        },
    );
    Dbvt::new(DbvtPolicy::MmdWin64Sse).collide_leaf(&other, ProxyKey(1), |_, _| {});
}
