//! Cuts each fixture at every byte offset. The reader must return `Ok` at
//! exactly the offsets where the C++ readers on `next` (`model_reader.cpp`,
//! `vmd_format.cpp`, `vpd_format.cpp`, `pmm_scene_document.cpp`) accept the
//! cut file, and `Err` everywhere else, without a panic.
//!
//! The accepted offsets were measured by linking those readers into a
//! harness and feeding every proper prefix of each fixture. They are the
//! optional-section ends: PMD after the bone frames, after the toon names
//! and after the rigid bodies; VMD before the camera, light, self-shadow
//! and IK counts; VPD inside the last bone block's closing lines; PMM after
//! the appearance block.

use mds_formats::Document;

const ACCEPTED: [(&str, &[usize]); 7] = [
    ("chain8.pmd", &[1502, 3039, 3707]),
    ("chain8.pmx", &[]),
    ("chain8_ik.pmx", &[]),
    ("morph4.pmx", &[]),
    ("swing600.vmd", &[8196, 8383, 8443, 8465]),
    ("pose.vpd", &[471, 472, 473, 474]),
    ("swing600.pmm", &[9940]),
];

#[test]
fn cuts_are_accepted_exactly_where_cpp_accepts_them() {
    for (name, accepted) in ACCEPTED {
        let path = format!(
            "{}/../../../tests/fixtures/rust/{name}",
            env!("CARGO_MANIFEST_DIR")
        );
        let data = std::fs::read(&path).unwrap();
        let mut ok = Vec::new();
        for cut in 0..data.len() {
            let prefix = &data[..cut];
            if let Ok(doc) = Document::read(prefix) {
                ok.push(cut);
                if !name.ends_with(".vpd") {
                    assert!(
                        doc.write().unwrap() == prefix,
                        "{name} cut at {cut} does not write back"
                    );
                }
            }
        }
        assert_eq!(ok, accepted, "{name}");
    }
}
