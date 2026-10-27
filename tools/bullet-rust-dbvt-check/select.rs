use crate::dbvt::{Aabb, Dbvt};
use crate::math::Vec3;
use crate::pair_cache::ProxyKey;

#[test]
fn directed_select_association_matches_native() {
    let mut tree = Dbvt::new(crate::policy());
    for (key, point) in [
        (1, [0.5, 8388608.0, 0.5]),
        (2, [1.0, 8388608.0, 0.0]),
        (3, [0.0, 0.0, 0.0]),
    ] {
        tree.insert(
            ProxyKey(key),
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
    let root = std::path::PathBuf::from(std::env::var("DBVT_FIXTURES").unwrap());
    let native = std::fs::read_to_string(root.join("original-select-stdout.log")).unwrap();
    let expected: Vec<u32> = native
        .lines()
        .last()
        .unwrap()
        .split('|')
        .next_back()
        .unwrap()
        .split(',')
        .filter(|s| !s.is_empty())
        .map(|s| s.parse().unwrap())
        .collect();
    assert_eq!(events, expected);
    assert_eq!(
        events,
        if crate::policy() == crate::dbvt::DbvtPolicy::MmdWin64Sse {
            vec![3, 2, 1]
        } else {
            vec![2, 3, 1]
        }
    );
}
