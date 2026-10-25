//! EMM and EMD round trips on the generated files in `tests/data/` (CRLF, Shift-JIS paths): a file
//! in the writer's shape loads, applies to live objects, and saves back to the same bytes, as
//! `MmeEmmLoad` then `MmeEmmSave` does in the C++.

use std::path::Path;

use mds_mmert::emm::{self, Assignment, Live};

fn data(name: &str) -> Vec<u8> {
    std::fs::read(
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("tests/data")
            .join(name),
    )
    .unwrap()
}

fn live(model: bool, slot: i32, path: &str, materials: i32) -> Live {
    Live {
        model,
        slot,
        path: path.to_string(),
        materials,
        render_class: 0,
    }
}

const CWD: &str = "C:\\MMD";

#[test]
fn emm_loads_applies_and_saves_to_the_same_bytes() {
    let bytes = data("scene.emm");
    let (file, log) = emm::parse_emm(&bytes, "C:\\MMD\\UserFile\\scene.emm");
    assert_eq!(log, []);
    let file = file.unwrap();
    assert_eq!(file.version, 3);
    assert_eq!(file.objects.len(), 3);
    assert_eq!(
        file.objects[0].path,
        "C:\\MMD\\UserFile\\Model\\初音ミク.pmx"
    );
    let section = &file.sections[0];
    assert_eq!(file.default_effect(), "none");
    assert_eq!(
        emm::write_emm(&file.objects, &section.default_path, &section.entries),
        bytes
    );

    // The host lists the accessory first and names the files relative to the process directory;
    // the rows still reach the objects by kind and path.
    let objects = [
        live(false, 0, "UserFile\\Accessory\\ソラ.x", 1),
        live(true, 0, "UserFile\\Model\\初音ミク.pmx", 3),
        live(true, 1, "UserFile\\Model\\chain8.pmx", 2),
    ];
    let mut assigned = vec![Assignment::default(); objects.len()];
    let exists = |p: &str| p.ends_with("main.fx");
    let (default, report) = emm::apply_emm(
        &file,
        "C:\\MMD\\UserFile\\scene.emm",
        &objects,
        &mut assigned,
        CWD,
        &exists,
    );
    assert_eq!(default, "");
    assert_eq!(report.unmatched, Vec::<String>::new());
    assert_eq!(report.missing, ["C:\\MMD\\Effects\\skin.fx"]);
    assert_eq!(
        report.log[0].text,
        "The following effect files do not exist:\n\nC:\\MMD\\Effects\\skin.fx"
    );
    assert_eq!(assigned[1].effect, "C:\\MMD\\Effects\\main.fx");
    assert_eq!(assigned[1].subsets[&0], "");
    assert!(!assigned[1].subset_shown(2) && assigned[1].subset_shown(1));
    assert_eq!(assigned[0].effect, "");
    assert!(!assigned[2].shown && assigned[2].subset_shown(1));
    assert_eq!(emm::save_emm(&objects, &assigned, &default, CWD), bytes);
}

#[test]
fn owner_sections_apply_and_save_flattened() {
    let (file, log) = emm::parse_emm(&data("owner.emm"), "C:\\MMD\\UserFile\\owner.emm");
    assert_eq!(log, []);
    let file = file.unwrap();
    assert_eq!(file.version, 2);
    assert_eq!(file.sections.len(), 2);
    let owner = &file.sections[1];
    assert_eq!(
        (owner.name.as_str(), owner.base.as_str()),
        ("Effect@a(1)", "a")
    );
    assert_eq!(
        (
            owner.owner_key.as_str(),
            owner.owner_subset,
            owner.owner_material.as_str()
        ),
        ("Pmd0", 1, "a")
    );
    // `..\Model\a.pmx` joined with the EMM's directory is this object's file.
    let objects = [live(true, 0, "C:\\MMD\\Model\\a.pmx", 2)];
    let mut assigned = vec![Assignment::default()];
    let (default, report) = emm::apply_emm(
        &file,
        "C:\\MMD\\UserFile\\owner.emm",
        &objects,
        &mut assigned,
        CWD,
        &|_| true,
    );
    assert_eq!(report, emm::ApplyReport::default());
    assert_eq!(default, "C:\\MMD\\Effects\\default.fx");
    let saved = emm::save_emm(&objects, &assigned, &default, CWD);
    let want = "[Info]\nVersion = 3\n\n[Object]\nPmd0 = C:\\MMD\\Model\\a.pmx\n\n[Effect]\n\
Default = C:\\MMD\\Effects\\default.fx\nPmd0 = C:\\MMD\\Effects\\main.fx\nPmd0.show = true\n\
Pmd0[1] = C:\\MMD\\Effects\\hair.fx\nPmd0[1].show = false\n\n";
    assert_eq!(
        String::from_utf8(saved).unwrap(),
        want.replace('\n', "\r\n")
    );

    let other = [live(true, 0, "D:\\elsewhere\\b.pmx", 1)];
    let (_, report) = emm::apply_emm(&file, "x.emm", &other, &mut assigned, CWD, &|_| true);
    assert_eq!(report.unmatched, ["b.pmx"]);
    assert_eq!(
        report.log[0].text,
        "x.emm\nFailed to load effect mapping for the following objects:\n\n  b.pmx"
    );
}

#[test]
fn emd_loads_applies_and_saves_to_the_same_bytes() {
    let bytes = data("model.emd");
    let path = "C:\\MMD\\UserFile\\Model\\a.emd";
    let (file, log) = emm::parse_emd(&bytes, path);
    assert_eq!(log, []);
    let file = file.unwrap();
    assert_eq!(emm::write_emd(&file.entry), bytes);
    let mut a = Assignment {
        effect: "old.fx".into(),
        ..Assignment::default()
    };
    a.subsets.insert(5, "old.fx".into());
    let report = emm::apply_emd(&file, path, 2, &mut a, &|_| true);
    assert_eq!(report.missing, Vec::<String>::new());
    assert_eq!(a.subsets.len(), 2, "the EMD replaces the old rows");
    assert_eq!(emm::save_emd(&a, path, 2, 0, CWD), bytes);

    // A relative value joins the EMD's directory; the save writes it absolute.
    let rel = b"[Info]\nVersion = 1\n[Effect]\nObj = ..\\fx\\x.fx\nObj[3] = hide\n";
    let (file, _) = emm::parse_emd(rel, path);
    let report = emm::apply_emd(&file.unwrap(), path, 2, &mut a, &|_| true);
    assert_eq!(report, emm::ApplyReport::default());
    assert_eq!(a.effect, "C:\\MMD\\UserFile\\Model\\..\\fx\\x.fx");
    assert!(a.subsets.is_empty(), "[3] is past the two materials");
    let saved = String::from_utf8(emm::save_emd(&a, path, 2, 0, CWD)).unwrap();
    assert!(
        saved.contains("Obj = C:\\MMD\\UserFile\\fx\\x.fx\r\n"),
        "{saved}"
    );

    // An EMD takes only Obj rows, and an EMM never does.
    let (none, log) = emm::parse_emd(b"[Info]\nVersion = 3\n[Effect]\nPmd0 = a.fx\n", path);
    assert!(none.is_none());
    assert_eq!(
        log.last().unwrap().text,
        format!("Error: failed to load file: {path} (line 4)")
    );
}

#[test]
fn effects_are_found_beside_the_model() {
    let exists = |p: &str| p == "C:\\m\\fx.fx" || p == "C:\\m\\a.fx" || p == "C:\\d.fx";
    assert_eq!(
        emm::effect_for_model("C:\\m\\a.pmx", "", &exists),
        "C:\\m\\a.fx"
    );
    assert_eq!(
        emm::effect_for_model("C:\\m\\b[fx.fx].pmx", "", &exists),
        "C:\\m\\fx.fx"
    );
    assert_eq!(
        emm::effect_for_model("C:\\m\\c.pmx", "C:\\d.fx", &exists),
        "C:\\d.fx"
    );
    assert_eq!(emm::effect_for_model("C:\\m\\c.pmx", "", &exists), "");
}
