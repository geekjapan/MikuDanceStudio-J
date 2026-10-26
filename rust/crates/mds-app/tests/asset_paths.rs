//! CPU-only asset loading through the same paths as the editor and frame dump.
use mds_app::{file, mme, scene};
use mds_doc::{Command, Document, ModelFile};
use std::path::{Path, PathBuf};

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("mds-assets-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

#[test]
fn scene_paths_keep_native_precedence_and_basename_fallback() {
    let dir = scratch("resolve");
    let file = dir.join("Model.PMX");
    std::fs::write(&file, b"model").unwrap();
    let stored = dir.join("model.pmx").to_string_lossy().replace('/', "\\");
    let native = PathBuf::from(stored.replace('\\', std::path::MAIN_SEPARATOR_STR));
    let expected = if native.is_file() {
        native
    } else {
        file.clone()
    };
    assert_eq!(scene::resolve(Path::new("unused"), &stored), expected);
    assert_eq!(scene::resolve(&dir, "C:\\Old\\model.pmx"), file);
    assert_eq!(
        scene::read_model(&dir, "C:\\Old\\model.pmx").unwrap(),
        b"model"
    );
    assert_eq!(
        scene::resolve(&dir, "C:\\Old\\Missing.PMX"),
        dir.join("Missing.PMX")
    );
    let exact = dir.join("exact.bin");
    std::fs::write(&exact, b"exact").unwrap();
    std::fs::create_dir_all(dir.join("fallback")).unwrap();
    std::fs::write(dir.join("fallback/exact.bin"), b"fallback").unwrap();
    assert_eq!(
        scene::resolve(&dir.join("fallback"), exact.to_str().unwrap()),
        exact
    );
    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn pmm_models_materials_accessories_and_background_load_without_rewriting_paths() {
    let dir = scratch("document");
    std::fs::create_dir_all(dir.join("Textures")).unwrap();
    let image = std::fs::read(fixtures().join("golden2/background.png")).unwrap();
    std::fs::write(dir.join("Textures/Image.PNG"), &image).unwrap();
    let mut pmx =
        mds_formats::pmx::Pmx::read(&std::fs::read(fixtures().join("chain8.pmx")).unwrap())
            .unwrap();
    let name = |text: &str| mds_formats::text::PmxText {
        raw: if pmx.globals[0] == 0 {
            text.encode_utf16().flat_map(u16::to_le_bytes).collect()
        } else {
            text.as_bytes().to_vec()
        },
        text: text.into(),
    };
    let absolute = dir
        .join("textures/image.png")
        .to_string_lossy()
        .into_owned();
    pmx.textures = vec![name("textures\\image.png"), name(&absolute)];
    for material in &mut pmx.materials {
        material.texture = 0;
        material.sphere = 1;
        material.sphere_mode = 1;
        material.shared_toon = 0;
        material.toon = 0;
    }
    std::fs::write(dir.join("Chain8.PMX"), pmx.write().unwrap()).unwrap();
    std::fs::copy(fixtures().join("accessory/cube.x"), dir.join("Cube.X")).unwrap();
    let mut doc = Document::startup();
    doc.apply(Command::LoadModel {
        path: "C:\\Old\\chain8.pmx".into(),
        data: pmx.write().unwrap(),
    })
    .unwrap();
    doc.pmm.picture.enabled = 1;
    doc.pmm.picture.path.text = "C:\\Old\\image.png".into();
    doc.pmm.picture.path.raw.fill(0);
    doc.pmm.picture.path.raw[..16].copy_from_slice(b"C:\\Old\\image.png");
    std::fs::write(dir.join("Image.PNG"), &image).unwrap();
    let data = doc.save().unwrap();
    let loaded = file::load(&data, &dir).unwrap();
    assert!(matches!(loaded.models[0], ModelFile::Pmx(_)));
    assert_eq!(loaded.pmm.models[0].path.text, "C:\\Old\\chain8.pmx");
    let mut assets = scene::Assets::load(&loaded, &dir).unwrap();
    assert!(assets.picture.is_some());
    assert!(assets.reload_textures(&loaded, &dir).is_empty());
    std::fs::write(dir.join("Textures/Image.PNG"), b"invalid image").unwrap();
    let errors = assets.reload_textures(&loaded, &dir);
    assert!(!errors.is_empty());
    assert!(errors.iter().any(|(name, _)| name == "textures\\image.png"));
    assert!(errors.iter().any(|(name, _)| name == &absolute));
    assert!(scene::accessory(&dir, "C:\\Old\\cube.x").is_some());
    let wave = std::fs::read(fixtures().join("script/inputs/tone.wav")).unwrap();
    std::fs::write(dir.join("Tone.WAV"), &wave).unwrap();
    assert_eq!(
        std::fs::read(scene::resolve(&dir, "C:\\Old\\tone.wav")).unwrap(),
        wave
    );
    assert_eq!(loaded.save().unwrap(), data);
    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn vac_ui_loads_case_folded_mesh_and_keeps_inner_name() {
    let dir = scratch("vac-ui");
    std::fs::create_dir_all(dir.join("Sub")).unwrap();
    std::fs::copy(fixtures().join("accessory/cube.x"), dir.join("Sub/mesh.x")).unwrap();
    let text = std::fs::read_to_string(fixtures().join("accessory/placed.vac"))
        .unwrap()
        .replace("cube.x", "Sub\\Mesh.X");
    let path = dir.join("placed.vac");
    std::fs::write(&path, &text).unwrap();
    let mut editor = mds_app::editor::Editor::empty();
    let mut status = String::new();
    let mut ctx = mds_app::ui::Ctx {
        editor: &mut editor,
        now_ms: 0,
        egui: None,
        viewport: None,
        status: &mut status,
    };
    mds_app::ui::file::load_vac_path(&mut ctx, &path).unwrap();
    assert_eq!(
        mds_accessory::vac::parse(text.as_bytes()).mesh,
        "Sub\\Mesh.X"
    );
    assert_eq!(ctx.editor.doc.pmm.accessories.len(), 1);
    assert_eq!(ctx.editor.doc.pmm.accessories[0].list_name.text, "Mesh.X");
    assert_eq!(ctx.editor.doc.pmm.accessories[0].state.scale, 2.5);
    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn uppercase_emm_is_discovered_but_save_path_remains_canonical() {
    let dir = scratch("emm");
    std::fs::copy(fixtures().join("chain8.pmx"), dir.join("chain8.pmx")).unwrap();
    let mut doc = Document::startup();
    doc.apply(Command::LoadModel {
        path: "chain8.pmx".into(),
        data: std::fs::read(fixtures().join("chain8.pmx")).unwrap(),
    })
    .unwrap();
    std::fs::write(dir.join("effect.fx"), b"effect").unwrap();
    let mut source = mme::Mme::none(&dir);
    source.assignments = vec![mds_mmert::emm::Assignment::default()];
    source.assignments[0].effect = dir.join("effect.fx").to_string_lossy().into_owned();
    let pmm = dir.join("Scene.PMM");
    std::fs::write(dir.join("Scene.EMM"), source.save_emm(&doc)).unwrap();
    let loaded = mme::Mme::autoload(&doc, Some(&pmm));
    assert!(!loaded.assignments[0].effect.is_empty());
    assert_eq!(mme::emm_path(&pmm), dir.join("Scene.emm"));
    let mut editor = mds_app::editor::Editor::new(doc, Some(pmm.clone())).unwrap();
    editor.mme = loaded;
    editor.save_as(&pmm).unwrap();
    assert!(dir.join("Scene.emm").is_file());
    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn toon_dialog_uses_selected_models_folder_and_preserves_typed_name() {
    let dir = scratch("toon-dialog");
    std::fs::create_dir_all(dir.join("Materials")).unwrap();
    let pmd = std::fs::read(fixtures().join("script3/inputs/lips.pmd")).unwrap();
    std::fs::write(dir.join("Lips.PMD"), &pmd).unwrap();
    std::fs::write(dir.join("Materials/Custom.BMP"), b"toon").unwrap();
    let mut editor =
        mds_app::editor::Editor::new(Document::startup(), Some(dir.join("Scene.pmm"))).unwrap();
    let egui = egui::Context::default();
    let mut status = String::new();
    let mut ctx = mds_app::ui::Ctx {
        editor: &mut editor,
        now_ms: 0,
        egui: Some(egui),
        viewport: None,
        status: &mut status,
    };
    mds_app::ui::model_panel::load(&mut ctx, "C:\\Old\\lips.pmd", pmd).unwrap();
    mds_app::actions::run(&mut ctx, "dlg:IDD_TOON_TEXTURE").unwrap();
    mds_app::ui::dialog::set_field(&mut ctx, 2, "materials\\custom.bmp");
    mds_app::ui::dialog::submit(&mut ctx).unwrap();
    let ModelFile::Pmd(pmd) = &ctx.editor.doc.models[0] else {
        panic!("PMD")
    };
    assert_eq!(
        pmd.extension.as_ref().unwrap().toon_textures[2].text,
        "materials\\custom.bmp"
    );
    assert_eq!(ctx.editor.doc.pmm.models[0].path.text, "C:\\Old\\lips.pmd");
    std::fs::remove_dir_all(dir).unwrap();
}

#[cfg(target_os = "linux")]
#[test]
fn scene_exact_direct_candidates_win_before_case_folded_candidates() {
    let dir = scratch("case-collision");
    for name in ["Model.PMX", "model.pmx"] {
        std::fs::write(dir.join(name), name).unwrap();
    }
    let literal = dir.join("literal\\asset.bin");
    std::fs::write(&literal, b"literal").unwrap();
    std::fs::create_dir_all(dir.join("literal")).unwrap();
    std::fs::write(dir.join("literal/asset.bin"), b"normalized").unwrap();
    assert_eq!(
        scene::resolve(Path::new("unused"), literal.to_str().unwrap()),
        literal
    );
    let stored = dir.join("model.pmx").to_string_lossy().replace('/', "\\");
    assert_eq!(
        scene::resolve(Path::new("unused"), &stored),
        dir.join("model.pmx")
    );
    assert_eq!(
        scene::resolve(&dir, "C:\\Old\\MODEL.PMX"),
        dir.join("Model.PMX")
    );
    std::fs::remove_dir_all(dir).unwrap();
}
