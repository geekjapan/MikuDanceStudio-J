//! Every RM-1 fixture reads and writes back to the same bytes, and the
//! fields the C++ code depends on come out as the fixture spec
//! (`tools/fixtures/gen_fixtures.py`) builds them.

use mds_formats::key_pool::{Key, KeyPool};
use mds_formats::pmm::Pmm;
use mds_formats::Document;

const FIXTURES: [&str; 7] = [
    "chain8.pmd",
    "chain8.pmx",
    "chain8_ik.pmx",
    "morph4.pmx",
    "swing600.vmd",
    "pose.vpd",
    "swing600.pmm",
];

fn fixture(name: &str) -> Vec<u8> {
    let path = format!(
        "{}/../../../tests/fixtures/rust/{name}",
        env!("CARGO_MANIFEST_DIR")
    );
    std::fs::read(&path).unwrap_or_else(|e| panic!("{path}: {e}"))
}

fn swing() -> Pmm {
    match Document::read(&fixture("swing600.pmm")).unwrap() {
        Document::Pmm(p) => *p,
        _ => panic!("swing600.pmm is not a PMM"),
    }
}

#[test]
fn every_fixture_writes_back_byte_identical() {
    for name in FIXTURES {
        let data = fixture(name);
        let doc = Document::read(&data).unwrap_or_else(|e| panic!("{name}: {e}"));
        assert!(
            doc.write().unwrap() == data,
            "{name} differs after a round trip"
        );
    }
}

/// `(index, frame, previous, next)` of every record in a pool.
fn links<K: Key>(pool: &KeyPool<K>) -> Vec<(u32, u32, u32, u32)> {
    let heads = pool.heads().iter().enumerate().map(|(i, k)| (i as u32, k));
    let records = pool.records().iter().map(|(i, k)| (*i, k));
    heads
        .chain(records)
        .map(|(i, k)| (i, k.frame(), k.previous(), k.next()))
        .collect()
}

#[test]
fn freed_bone_key_leaves_its_gap_and_links() {
    let scene = swing();
    let bones = &scene.models[0].bone_keys;
    // Bone 頭 (index 4), frame 300 was freed: record 34 is empty and the
    // chain bridges 25 (frame 200) to 46 (frame 400).
    assert_eq!(scene.models[0].bone_names[4].text, "頭");
    assert!(bones.get(34).is_none());
    assert_eq!(
        (bones.get(25).unwrap().frame, bones.get(25).unwrap().next),
        (200, 46)
    );
    assert_eq!(
        (
            bones.get(46).unwrap().frame,
            bones.get(46).unwrap().previous
        ),
        (400, 25)
    );
    // The kfa::AllocateFromCursor rule hands out the gap first.
    let mut cursor = 0;
    assert_eq!(bones.allocate_from_cursor(&mut cursor), Some(34));

    let again = Pmm::read(&scene.write().unwrap()).unwrap();
    for (a, b) in scene.models.iter().zip(&again.models) {
        assert_eq!(links(&a.bone_keys), links(&b.bone_keys));
        assert_eq!(links(&a.morph_keys), links(&b.morph_keys));
        assert_eq!(links(&a.display_keys), links(&b.display_keys));
        for check in [
            a.bone_keys.validate_tracks(),
            a.morph_keys.validate_tracks(),
            a.display_keys.validate_tracks(),
        ] {
            assert_eq!(check, Ok(()));
        }
    }
    assert!(again.models[0].bone_keys.get(34).is_none());
}

#[test]
fn bone_track_lengths_match_the_spec() {
    let scene = swing();
    let bones = &scene.models[0].bone_keys;
    let lengths: Vec<usize> = (0..bones.heads().len() as u32)
        .map(|head| {
            let mut n = 0;
            let mut at = bones.get(head).unwrap().next;
            while at != 0 {
                n += 1;
                at = bones.get(at).unwrap().next;
            }
            n + 1
        })
        .collect();
    assert_eq!(lengths, [2, 7, 5, 6, 6, 9, 11, 21, 3]);
}

#[test]
fn curve_tables_are_in_cpp_memory_order() {
    let scene = swing();
    let bones = &scene.models[0].bone_keys;
    // Bone 首 (3) uses the per-lane curve on every key after its head; the
    // spec table is already indexed lane + 4 * group.
    let first = bones.get(bones.get(3).unwrap().next).unwrap();
    assert_eq!(
        first.interpolation,
        [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 5, 15, 25, 35]
    );
    // The camera head uses the linear curve x1, y1, x2, y2 on all 6 channels.
    let cam = &scene.camera.heads()[0].interpolation;
    assert_eq!(*cam, [[20; 6], [20; 6], [107; 6], [107; 6]]);
}

#[test]
fn chain8_pmd_bone_names_decode_from_shift_jis() {
    let Document::Pmd(pmd) = Document::read(&fixture("chain8.pmd")).unwrap() else {
        panic!("chain8.pmd is not a PMD");
    };
    let names: Vec<&str> = pmd.bones.iter().map(|b| b.name.text.as_str()).collect();
    assert_eq!(
        names,
        [
            "全ての親",
            "センター",
            "上半身",
            "首",
            "頭",
            "髪1",
            "髪2",
            "髪3"
        ]
    );
}

#[test]
fn an_edited_field_is_written() {
    let mut scene = swing();
    scene.settings.render_width += 1;
    let again = Pmm::read(&scene.write().unwrap()).unwrap();
    assert_eq!(again.settings.render_width, 1281);
}
