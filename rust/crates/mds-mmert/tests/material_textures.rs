use std::path::Path;

use mds_formats::{pmm::Pmm, pmx::Pmx, text::PmxText};
use mds_mmert::{
    bind::{Scene, DRAW_EDGE, DRAW_OBJECT},
    model::Model,
    DrawInput, Effect, Gpu, Target,
};

mod common;

#[test]
fn fixture_top_level_symbols_are_disjoint() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/data/material-textures.fx");
    let fx = mds_fx::Effect::parse_file(&path).unwrap();
    let mut symbols = std::collections::HashSet::new();
    for name in fx
        .ast
        .globals
        .iter()
        .map(|g| &g.name)
        .chain(fx.ast.functions.iter().map(|f| &f.name))
        .chain(fx.ast.structs.iter().map(|s| &s.name))
    {
        assert!(
            symbols.insert(name.as_str()),
            "duplicate top-level symbol {name}"
        );
    }
    for technique in &fx.ast.techniques {
        let name = technique
            .name
            .as_deref()
            .expect("named diagnostic technique");
        assert!(
            symbols.insert(name),
            "technique collides with top-level symbol {name}"
        );
    }
    assert!(
        fx.ast
            .techniques
            .iter()
            .all(|t| t.name.as_deref().unwrap().starts_with("MdsMaterial")),
        "diagnostic technique names must use the non-keyword MdsMaterial prefix"
    );
}

fn png(pixels: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    let mut enc = png::Encoder::new(&mut out, (pixels.len() / 4) as u32, 1);
    enc.set_color(png::ColorType::Rgba);
    enc.write_header()
        .unwrap()
        .write_image_data(pixels)
        .unwrap();
    out
}

fn pmx() -> Pmx {
    Pmx::read(&std::fs::read(common::fixtures().join("chain8.pmx")).unwrap()).unwrap()
}

fn model(gpu: &Gpu) -> Model {
    let mut pmx = pmx();
    pmx.materials = vec![pmx.materials[0].clone(); 3];
    pmx.textures = (0..3)
        .flat_map(|i| {
            [
                text(&format!("base{i}")),
                text(&format!("sphere{i}")),
                text(&format!("toon{i}")),
            ]
        })
        .collect();
    for (i, m) in pmx.materials.iter_mut().enumerate() {
        m.face_vertex_count = 0;
        m.texture = i as i32 * 3;
        m.sphere = i as i32 * 3 + 1;
        m.sphere_mode = 3;
        m.shared_toon = 0;
        m.toon = i as i32 * 3 + 2;
    }
    let mut model = Model::from_pmx(&gpu.device, &pmx).unwrap();
    model.load_textures(gpu, image, |_| panic!("custom name read as shared"));
    assert_eq!(model.materials[0].sphere_mode, 3);
    assert_eq!(model.materials[2].sphere_mode, 0);
    assert!(!model.materials[2].has_texture);
    assert!(model.materials[2].toon);
    model
}

fn image(n: &str) -> Option<Vec<u8>> {
    Some(png(match n {
        "base0" => &[64, 0, 0, 128, 112, 0, 0, 192],
        "sphere0" => &[0, 96, 0, 255],
        "toon0" => &[0, 0, 128, 255],
        "base1" => &[192, 0, 0, 255],
        "sphere1" => &[0, 160, 0, 255],
        "toon1" => &[0, 0, 32, 255],
        "base3" => &[16, 0, 0, 255],
        "sphere3" => &[0, 48, 0, 255],
        "toon3" => &[0, 0, 224, 255],
        _ => return None,
    }))
}

#[test]
fn sampled_slots_follow_the_draw_snapshot_without_sticking() {
    let Some(gpu) = common::gpu() else { return };
    let Some(vk) = common::vkd3d() else { return };
    let (_, errors) = gpu.scoped(|| {
        let mut first = model(&gpu);
        let mut second = model(&gpu);
        for m in &mut second.materials {
            m.texture = Some("base3".into());
            m.sphere = Some("sphere3".into());
            m.toon_texture = Some("toon3".into());
        }
        second.load_textures(&gpu, image, |_| None);
        let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/data");
        let mut effect =
            Effect::load(&gpu, &vk, &dir.join("material-textures.fx"), &dir, (32, 32)).unwrap();
        let scene = Scene::default_view(32, 32);
        let target = Target::new(&gpu, (32, 32));
        {
            let mut draw = |model: &Model, subset, kind, tech, dst: &Target| {
                dst.clear_turn(&gpu, Some(0xffffffff), 1.0, false);
                let input = DrawInput {
                    scene: &scene,
                    geometry: Some((model, subset)),
                    draw_type: kind,
                    controls: None,
                    owner: None,
                    offscreen_owner: None,
                };
                let report = effect.draw_technique(&gpu, dst, &input, tech);
                assert!(report.skipped.is_empty(), "{:?}", report.skipped);
                assert_eq!(report.drawn, 1);
                let px = dst.read(&gpu).unwrap();
                let pixel = |x: usize| px[(16 * 32 + x) * 4..(16 * 32 + x) * 4 + 4].to_vec();
                (pixel(8), pixel(24))
            };
            assert_eq!(
                draw(&first, 0, DRAW_OBJECT, 1, &target),
                (vec![64, 96, 128, 128], vec![112, 96, 128, 192])
            );
            assert_eq!(
                draw(&first, 1, DRAW_OBJECT, 1, &target).0,
                [192, 160, 32, 255]
            );
            assert_eq!(draw(&first, 2, DRAW_OBJECT, 1, &target).0, [0, 0, 0, 255]);
            assert_eq!(
                draw(&second, 0, DRAW_OBJECT, 1, &target).0,
                [16, 48, 224, 255]
            );
            assert_eq!(draw(&first, 0, DRAW_EDGE, 1, &target).0, [0, 0, 128, 255]);
            assert_eq!(draw(&first, 0, DRAW_OBJECT, 2, &target).0, [0, 0, 0, 255]);
            assert_eq!(draw(&first, 0, DRAW_OBJECT, 3, &target).0, [0, 0, 0, 255]);
        }
        let r = effect
            .sas
            .resources
            .iter()
            .position(|r| r.name == "Turn")
            .unwrap();
        let offscreen = effect.begin_offscreen(&gpu, r).unwrap();
        let input = DrawInput {
            scene: &scene,
            geometry: Some((&first, 0)),
            draw_type: DRAW_OBJECT,
            controls: None,
            owner: None,
            offscreen_owner: Some(0),
        };
        let report = effect.draw_technique(&gpu, &offscreen, &input, 1);
        assert!(report.skipped.is_empty(), "{:?}", report.skipped);
        assert_eq!(
            &offscreen.read(&gpu).unwrap()[(16 * 32 + 8) * 4..(16 * 32 + 8) * 4 + 4],
            &[64, 96, 128, 128]
        );
        let input = DrawInput {
            geometry: None,
            ..input
        };
        effect.draw_technique(&gpu, &target, &input, 1);
        assert_eq!(
            &target.read(&gpu).unwrap()[(16 * 32 + 8) * 4..(16 * 32 + 8) * 4 + 4],
            &[0, 0, 0, 255]
        );
        effect.tick_animes(&gpu, 0.0);
        assert_eq!(effect.animes[0].shown, Some(0));
        effect.draw_technique(&gpu, &target, &input, 4);
        assert_eq!(
            &target.read(&gpu).unwrap()[(16 * 32 + 8) * 4..(16 * 32 + 8) * 4 + 4],
            &[255, 0, 0, 255]
        );
        assert_eq!(effect.animes[0].shown, Some(0));
        effect.tick_animes(&gpu, 0.11);
        effect.draw_technique(&gpu, &target, &input, 4);
        assert_eq!(
            &target.read(&gpu).unwrap()[(16 * 32 + 8) * 4..(16 * 32 + 8) * 4 + 4],
            &[0, 255, 0, 255]
        );
        let mut geometry = Model::from_pmx(&gpu.device, &oracle_model()).unwrap();
        geometry.load_textures(&gpu, |n| image(n.trim_end_matches(".png")), |_| None);
        let target_geometry = Target::new(&gpu, (320, 180));
        let mut geometry_scene = Scene::default_view(320, 180);
        geometry_scene.view =
            mds_mmert::bind::look_at_lh([0.0, 4.0, 20.0], [0.0, 4.0, 0.0], [0.0, 1.0, 0.0]);
        target_geometry.clear_turn(&gpu, Some(0xffffffff), 1.0, false);
        for subset in 0..3 {
            let input = DrawInput {
                scene: &geometry_scene,
                geometry: Some((&geometry, subset)),
                draw_type: DRAW_OBJECT,
                ..input
            };
            let report = effect.draw_technique(&gpu, &target_geometry, &input, 0);
            assert!(report.skipped.is_empty(), "{:?}", report.skipped);
            assert_eq!(report.drawn, 1);
        }
        let pixels = target_geometry.read(&gpu).unwrap();
        for color in [
            [64, 96, 128, 128],
            [112, 96, 128, 192],
            [192, 160, 32, 255],
            [0, 0, 0, 255],
        ] {
            assert!(
                pixels.chunks_exact(4).filter(|px| *px == color).count() > 20,
                "geometry missing {color:?}"
            );
        }
        let before = first
            .materials
            .iter()
            .map(|m| m.textures.clone())
            .collect::<Vec<_>>();
        let mut p = pmx();
        p.morphs.push(mds_formats::pmx::Morph {
            name: text("UV"),
            name_en: text("UV"),
            panel: 4,
            kind: 3,
            offsets: mds_formats::pmx::Offsets::Uv(vec![(0, [0.5, 0.0, 0.0, 0.0])]),
        });
        let mut skin = mds_skin::Skin::from_pmx(&p).unwrap();
        skin.apply_morphs(&[1.0]);
        skin.update(
            &[1.0],
            &vec![mds_math::Mat4::IDENTITY; p.bones.len()],
            &mds_skin::View {
                world: mds_math::Mat4::IDENTITY,
                camera_position: [0.0, 0.0, 20.0],
                camera_fov: 30.0,
                edge_scale: 1.0,
                self_shadow: false,
            },
        );
        assert_eq!(skin.main[6], p.vertices[0].uv[0] + 0.5);
        first.update(&gpu.queue, &skin);
        assert_eq!(
            first
                .materials
                .iter()
                .map(|m| m.textures.clone())
                .collect::<Vec<_>>(),
            before
        );
    });
    assert!(errors.is_empty(), "wgpu errors {errors:?}");
}

#[test]
fn oversized_material_images_clear_slots_before_gpu_upload() {
    let Some(gpu) = common::gpu() else { return };
    let (_, errors) = gpu.scoped(|| {
        let mut model = model(&gpu);
        let limit = gpu.device.limits().max_texture_dimension_2d;
        let oversized = png(&vec![255; (limit as usize + 1) * 4]);
        let decoded = mds_render::Image::decode(&oversized).unwrap();
        assert_eq!((decoded.width, decoded.height), (limit + 1, 1));
        eprintln!(
            "decoded {}x1 PNG exceeds device D2 limit {limit}",
            decoded.width
        );
        let material = &mut model.materials[0];
        assert!(material.textures.texture.is_some());
        assert!(material.textures.sphere.is_some());
        assert!(material.textures.toon.is_some());
        material.texture = Some("oversized.png".into());
        material.sphere = Some("oversized.png".into());
        material.toon_texture = Some("oversized.png".into());
        assert_eq!(material.sphere_mode, 3);
        model.load_textures(
            &gpu,
            |name| {
                if name == "oversized.png" {
                    Some(oversized.clone())
                } else {
                    image(name)
                }
            },
            |_| None,
        );
        let material = &model.materials[0];
        assert_eq!(material.textures, Default::default());
        assert!(!material.has_texture);
        assert_eq!(material.sphere_mode, 0);
        assert!(material.toon);
        assert!(model.materials[1].textures.texture.is_some());
    });
    assert!(errors.is_empty(), "wgpu errors {errors:?}");
}

fn text(s: &str) -> PmxText {
    PmxText {
        text: s.into(),
        raw: s.encode_utf16().flat_map(u16::to_le_bytes).collect(),
    }
}

fn oracle_model() -> Pmx {
    let base = pmx();
    let mut p = base.clone();
    p.vertices.clear();
    p.indices.clear();
    p.materials.clear();
    p.textures = (0..2)
        .flat_map(|i| {
            [
                text(&format!("base{i}.png")),
                text(&format!("sphere{i}.png")),
                text(&format!("toon{i}.png")),
            ]
        })
        .collect();
    for i in 0..3 {
        let offset = p.vertices.len() as i32;
        p.vertices
            .extend(base.vertices.iter().cloned().map(|mut v| {
                v.position[0] += (i as f32 - 1.0) * 3.0;
                v
            }));
        p.indices.extend(base.indices.iter().map(|ix| ix + offset));
        let mut m = base.materials[0].clone();
        m.texture = if i < 2 { i * 3 } else { -1 };
        m.sphere = if i < 2 { i * 3 + 1 } else { -1 };
        m.sphere_mode = 3;
        m.shared_toon = 0;
        m.toon = if i < 2 { i * 3 + 2 } else { -1 };
        m.flags &= !0x10;
        p.materials.push(m);
    }
    p
}

#[test]
fn write_native_fixture() {
    let dir = std::env::var_os("MDS_MATERIAL_FIXTURE_DIR")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| {
            std::env::temp_dir().join(format!("mds-material-textures-{}", std::process::id()))
        });
    std::fs::create_dir_all(&dir).unwrap();
    let p = oracle_model();
    std::fs::write(dir.join("materials.pmx"), p.write().unwrap()).unwrap();
    let mut pmm =
        Pmm::read(&std::fs::read(common::fixtures().join("mmegold/objects.pmm")).unwrap()).unwrap();
    pmm.models[0].path.text = "materials.pmx".into();
    pmm.models[0].path.raw.fill(0);
    pmm.models[0].path.raw[..13].copy_from_slice(b"materials.pmx");
    let mut second = pmx();
    for v in &mut second.vertices {
        v.position[0] += 6.0;
    }
    second.textures = ["base3.png", "sphere3.png", "toon3.png"].map(text).to_vec();
    second.materials[0].texture = 0;
    second.materials[0].sphere = 1;
    second.materials[0].sphere_mode = 3;
    second.materials[0].shared_toon = 0;
    second.materials[0].toon = 2;
    second.materials[0].flags &= !0x10;
    std::fs::write(dir.join("second.pmx"), second.write().unwrap()).unwrap();
    let mut other = pmm.models[0].clone();
    other.slot = 1;
    other.selection.combo_index = 2;
    other.display_order = 1;
    other.path.raw.fill(0);
    other.path.raw[..10].copy_from_slice(b"second.pmx");
    other.path.text = "second.pmx".into();
    pmm.models.push(other);
    if let mds_formats::pmm::Tail::Registrations(regs) = &mut pmm.tail {
        regs.push(regs[0].clone());
    }
    std::fs::write(dir.join("materials.pmm"), pmm.write().unwrap()).unwrap();
    std::fs::write(
        dir.join("material-textures.fx"),
        include_bytes!("data/material-textures.fx"),
    )
    .unwrap();
    for i in [0, 1, 3] {
        for slot in ["base", "sphere", "toon"] {
            std::fs::write(
                dir.join(format!("{slot}{i}.png")),
                image(&format!("{slot}{i}")).unwrap(),
            )
            .unwrap();
        }
    }
    std::fs::write(dir.join("blink.gif"), include_bytes!("data/blink.gif")).unwrap();
    assert_eq!(
        Pmx::read(&std::fs::read(dir.join("materials.pmx")).unwrap())
            .unwrap()
            .materials
            .len(),
        3
    );
    let readback = Pmm::read(&std::fs::read(dir.join("materials.pmm")).unwrap()).unwrap();
    assert_eq!(readback.models.len(), 2);
    assert_eq!(
        readback
            .models
            .iter()
            .map(|m| m.selection.combo_index)
            .collect::<Vec<_>>(),
        [1, 2],
        "MMHack object orders must be nonzero and distinct"
    );
    std::fs::write(dir.join("materials.emm"),"[Info]\nVersion = 3\n[Object]\nPmd0 = materials.pmx\nPmd1 = second.pmx\n[Effect]\nDefault = none\nPmd0 = material-textures.fx\nPmd1 = material-textures.fx\n").unwrap();
}
