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

/// Every string of a PMX model, for re-encoding.
fn pmx_texts(m: &mut mds_formats::pmx::Pmx) -> Vec<&mut mds_formats::text::PmxText> {
    let mut out = vec![
        &mut m.name,
        &mut m.name_en,
        &mut m.comment,
        &mut m.comment_en,
    ];
    out.extend(m.textures.iter_mut());
    for x in &mut m.materials {
        out.extend([&mut x.name, &mut x.name_en, &mut x.memo]);
    }
    for x in &mut m.bones {
        out.extend([&mut x.name, &mut x.name_en]);
    }
    for x in &mut m.morphs {
        out.extend([&mut x.name, &mut x.name_en]);
    }
    for x in &mut m.frames {
        out.extend([&mut x.name, &mut x.name_en]);
    }
    for x in &mut m.rigids {
        out.extend([&mut x.name, &mut x.name_en]);
    }
    for x in m.joints.iter_mut().flatten() {
        out.extend([&mut x.name, &mut x.name_en]);
    }
    out
}

#[test]
fn utf8_pmx_reads_and_writes_back() {
    let Document::Pmx(mut pmx) = Document::read(&fixture("chain8.pmx")).unwrap() else {
        panic!("chain8.pmx is not a PMX");
    };
    pmx.globals[0] = 1;
    let mut before = Vec::new();
    for t in pmx_texts(&mut pmx) {
        t.raw = t.text.as_bytes().to_vec();
        before.push(t.text.clone());
    }
    // "Hair1" is 5 bytes: UTF-8 allows the odd lengths UTF-16 forbids.
    assert!(before.iter().any(|t| t.len() % 2 == 1));
    let bytes = pmx.write().unwrap();
    let Document::Pmx(mut again) = Document::read(&bytes).unwrap() else {
        panic!("not a PMX");
    };
    let after: Vec<String> = pmx_texts(&mut again)
        .iter()
        .map(|t| t.text.clone())
        .collect();
    assert_eq!(after, before);
    assert!(again.write().unwrap() == bytes);
}

#[test]
fn pmm_accessory_blocks_write_back() {
    use mds_formats::key_pool::GLOBAL_KEY_CAPACITY;
    use mds_formats::pmm::{Accessory, AccessoryKey, AccessoryState};
    use mds_formats::text::FixedSjis;
    let mut scene = swing();
    let mut name = [0; 100];
    name[..5].copy_from_slice(b"stage");
    let head = AccessoryKey {
        next: 7,
        opacity_visible: 1,
        parent_model: -1,
        scale: 1.0,
        ..AccessoryKey::default()
    };
    let mut keys = KeyPool::new(GLOBAL_KEY_CAPACITY, vec![head]).unwrap();
    let key = AccessoryKey {
        frame: 30,
        position: [1.0, 2.0, 3.0],
        scale: 2.0,
        ..AccessoryKey::default()
    };
    keys.insert(7, key).unwrap();
    let text = |raw| FixedSjis {
        raw,
        text: "stage".into(),
    };
    let accessory = Accessory {
        list_name: text(name),
        slot: 0,
        name: text(name),
        path: FixedSjis {
            raw: [0; 256],
            text: String::new(),
        },
        order: 0,
        keys,
        state: AccessoryState {
            opacity_visible: 1,
            scale: 1.0,
            ..AccessoryState::default()
        },
    };
    scene.accessories.push(accessory.clone());
    scene.accessories.push(Accessory {
        slot: 3,
        ..accessory
    });
    let bytes = scene.write().unwrap();
    // Per accessory: a 100-byte list name, then slot, name, path, order,
    // head key, count, (index, key) and the 39-byte state.
    let block = 100 + 1 + 100 + 256 + 1 + 51 + 4 + (4 + 51) + 39;
    assert_eq!(bytes.len(), 9961 + 2 * block);
    let again = Pmm::read(&bytes).unwrap();
    assert_eq!(again.accessories[1].slot, 3);
    let key = again.accessories[0].keys.get(7).unwrap();
    assert_eq!(key.position, [1.0, 2.0, 3.0]);
    assert!(again.write().unwrap() == bytes);
    // Lets the C++ reader check the layout: see the RM-5 report.
    if let Ok(path) = std::env::var("MDS_FORMATS_DUMP_ACCESSORY_PMM") {
        std::fs::write(path, &bytes).unwrap();
    }
}
