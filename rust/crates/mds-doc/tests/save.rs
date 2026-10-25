//! The load and save gate: every PMM fixture loads into a document and
//! saves back to its own bytes, except where `pmm_save.cpp` normalizes.

use mds_doc::{Document, ModelFile};
use std::path::PathBuf;

fn dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

fn load(name: &str) -> (Vec<u8>, Document) {
    let data = std::fs::read(dir().join(name)).unwrap();
    let doc = Document::load(&data, |p| std::fs::read(dir().join(p)).ok()).unwrap();
    (data, doc)
}

/// `(offset, input byte, saved byte)` of every byte that differs.
fn diff(a: &[u8], b: &[u8]) -> Vec<(usize, u8, u8)> {
    assert_eq!(a.len(), b.len(), "length");
    a.iter()
        .zip(b)
        .enumerate()
        .filter(|(_, (x, y))| x != y)
        .map(|(i, (x, y))| (i, *x, *y))
        .collect()
}

/// Bytes 11 and 12 of the model paths of slots 1, 2 and 3: the shared
/// scratch buffer still holds "mx" of slot 0's "chain8_ik.pmx" after the
/// 10-byte paths and their NUL. The offsets are the same in all four files.
const PATH_RESIDUE: [(usize, u8, u8); 6] = [
    (5341, 0, b'm'),
    (5342, 0, b'x'),
    (6300, 0, b'm'),
    (6301, 0, b'x'),
    (7495, 0, b'm'),
    (7496, 0, b'x'),
];

fn fixtures() -> Vec<String> {
    let mut names: Vec<String> = std::fs::read_dir(dir())
        .unwrap()
        .filter_map(|e| e.ok()?.file_name().into_string().ok())
        .filter(|n| n.ends_with(".pmm"))
        .collect();
    names.sort();
    names
}

#[test]
fn every_fixture_saves_back() {
    let names = fixtures();
    assert_eq!(
        names,
        [
            "camera3.pmm",
            "swing600-golden.pmm",
            "swing600-nophys.pmm",
            "swing600.pmm"
        ]
    );
    for name in &names {
        let (data, doc) = load(name);
        assert!(doc.models.iter().all(|m| !matches!(m, ModelFile::Missing)));
        let out = doc.save().unwrap();
        let path = |slot: usize| &out[PATH_RESIDUE[2 * slot - 2].0 - 11..][..13];
        assert_eq!(path(1), b"morph4.pmx\0mx", "{name}");
        assert_eq!(diff(&data, &out), PATH_RESIDUE, "{name}");
        let again = Document::load(&out, |p| std::fs::read(dir().join(p)).ok()).unwrap();
        assert_eq!(
            again.save().unwrap(),
            out,
            "{name}: a saved file saves back"
        );
    }
}

/// Each mutation sets a flag that is 1 to another non-zero value, or puts
/// bytes where the C++ writes zeros; saving undoes it.
#[test]
fn save_normalizes_what_pmm_save_rewrites() {
    let (data, mut doc) = load("swing600.pmm");
    let reference = doc.save().unwrap();
    let p = &mut doc.pmm;
    p.header[27] = 0x5a;
    p.settings.options[1] = 2;
    let m = &mut p.models[0];
    m.selection.load_complete = 7;
    m.selection.group_count_repeat = 0;
    m.selection.group_flags[0] = 9;
    m.bone_keys.heads_mut()[0].allocated = 2;
    let first = m.bone_keys.records()[0].0;
    m.bone_keys.get_mut(first).unwrap().allocated = 3;
    m.display_keys.heads_mut()[0].ik_enabled[0] = 4;
    m.ik_pose[0] = 5;
    m.path.raw[200] = 0x41;
    p.camera_perspective = 6;
    p.wave.path.raw[3] = 0x42;
    p.view.ground_grid = 8;
    p.physics.projected_shadow_blend = 2;
    p.appearance.max_frame = -3;
    p.appearance.floor_visible = 4;
    let saved = doc.save().unwrap();
    let mut expect = reference.clone();
    // max frame -3 is written as 0: the last i32 before the tail.
    let at = expect.len() - (1 + 5 * 4) - 4;
    expect[at..at + 4].copy_from_slice(&0i32.to_le_bytes());
    assert_eq!(diff(&expect, &saved), []);
    assert_eq!(diff(&data, &reference), PATH_RESIDUE);
}

#[test]
fn a_file_without_the_tail_gets_registration_3() {
    let (_, mut doc) = load("swing600.pmm");
    let reference = doc.save().unwrap();
    doc.pmm.tail = mds_formats::pmm::Tail::Absent;
    let saved = doc.save().unwrap();
    let mut expect = reference;
    let tail = expect.len() - 4 * 5;
    for slot in 0..4 {
        expect[tail + 5 * slot + 1..tail + 5 * slot + 5].copy_from_slice(&3i32.to_le_bytes());
    }
    assert_eq!(saved, expect);
}
