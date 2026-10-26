//! `mds_mmert::host` draws a model through its effect in the pose `mds-pose` gives it, not in its
//! bind pose: `chain8.pmx` of the mmegold `objects` scene with `objects.fx`, once as loaded and
//! once with every bone moved 5 units along x. The camera looks along -z (yaw pi), so +x is to
//! the left of the picture, 5 units there being about 168 pixels (distance 20, 30 degrees, 360
//! pixels high). A PMD model and an accessory draw through the same effect.

use mds_formats::pmm::Pmm;
use mds_formats::pmx::Pmx;
use mds_math::Mat4;
use mds_mmert::emm::Assignment;
use mds_mmert::host::{Frame, Host, Source};
use mds_render::Camera;
use mds_scene::track::{evaluate_camera, evaluate_light, CameraMode, LightMode};

mod common;

const W: u32 = 640;
const H: u32 = 360;

/// The mean x of the pixels that are not the corner's colour.
fn mean_x(px: &[u8]) -> f32 {
    let bg = &px[..3];
    let xs: Vec<u32> = (0..W * H)
        .filter(|&i| &px[i as usize * 4..i as usize * 4 + 3] != bg)
        .map(|i| i % W)
        .collect();
    assert!(xs.len() > 1000, "the model covers {} pixels", xs.len());
    xs.iter().sum::<u32>() as f32 / xs.len() as f32
}

#[test]
fn a_posed_model_draws_in_its_pose() {
    let Some(gpu) = common::gpu() else { return };
    let Some(vk) = common::vkd3d() else { return };
    let fixtures = common::fixtures();
    let pmm = Pmm::read(&std::fs::read(fixtures.join("mmegold/objects.pmm")).unwrap()).unwrap();
    let pmx = Pmx::read(&std::fs::read(fixtures.join("chain8.pmx")).unwrap()).unwrap();
    let mut host = Host::new((W, H));
    host.add(&gpu, "chain8.pmx", Source::Pmx(&pmx), 1.0, |_| None)
        .unwrap();
    let c = evaluate_camera(&pmm.camera, 0.0, CameraMode::Playback).unwrap();
    let camera = Camera {
        target: c.position,
        rotation: c.rotation,
        distance: c.distance,
        fov_deg: c.fov,
        orthographic: false,
    };
    let light = evaluate_light(&pmm.light, 0.0, LightMode::Playback).unwrap();
    let assignments = [Assignment {
        effect: "objects.fx".into(),
        ..Assignment::default()
    }];
    let effects = fixtures.join("mme/effects");
    let resolve = |p: &str| effects.join(p);
    let mut posed = mds_pose::model::Model::from_pmx(pmm.models[0].slot, &pmx).unwrap();
    let mut draw = |posed: &mds_pose::model::Model| {
        let f = Frame {
            pmm: &pmm,
            poses: std::slice::from_ref(posed),
            camera: &camera.into(),
            view_offset: [0.0; 2],
            shadow_map: Default::default(),
            shadow_map_display: false,
            light,
            frame: 0,
            elapsed: 0.0,
            size: (W, H),
            assignments: &assignments,
            offscreen: &Default::default(),
            resolve: &resolve,
        };
        let mut log = Vec::new();
        let skipped = host.render(&gpu, &vk, &f, &mut log);
        assert!(skipped.is_empty(), "{skipped:?} {log:?}");
        host.target().unwrap().read(&gpu).unwrap()
    };
    for b in &mut posed.bones {
        b.mat_init = Mat4::IDENTITY;
    }
    let bind = mean_x(&draw(&posed));
    for b in &mut posed.bones {
        b.mat_init = Mat4::translation(5.0, 0.0, 0.0);
    }
    let moved = mean_x(&draw(&posed));
    let shift = bind - moved;
    assert!((150.0..190.0).contains(&shift), "moved {shift} pixels left");
}

/// One frame of `host`'s first object with `objects.fx`: its pixels.
fn draw_with_objects_fx(
    gpu: &mds_mmert::Gpu,
    vk: &mds_shader::vkd3d::Vkd3d,
    host: &mut Host,
    poses: &[mds_pose::model::Model],
) -> Vec<u8> {
    let fixtures = common::fixtures();
    let pmm = Pmm::read(&std::fs::read(fixtures.join("mmegold/objects.pmm")).unwrap()).unwrap();
    let c = evaluate_camera(&pmm.camera, 0.0, CameraMode::Playback).unwrap();
    let camera = Camera {
        target: c.position,
        rotation: c.rotation,
        distance: c.distance,
        fov_deg: c.fov,
        orthographic: false,
    };
    let assignments = [Assignment {
        effect: "objects.fx".into(),
        ..Assignment::default()
    }];
    let effects = fixtures.join("mme/effects");
    let resolve = |p: &str| effects.join(p);
    let f = Frame {
        pmm: &pmm,
        poses,
        camera: &camera.into(),
        view_offset: [0.0; 2],
        shadow_map: Default::default(),
        shadow_map_display: false,
        light: evaluate_light(&pmm.light, 0.0, LightMode::Playback).unwrap(),
        frame: 0,
        elapsed: 0.0,
        size: (W, H),
        assignments: &assignments,
        offscreen: &Default::default(),
        resolve: &resolve,
    };
    let mut log = Vec::new();
    let skipped = host.render(gpu, vk, &f, &mut log);
    assert!(skipped.is_empty(), "{skipped:?} {log:?}");
    host.target().unwrap().read(gpu).unwrap()
}

/// The pixels that are not the corner's colour.
fn covered(px: &[u8]) -> usize {
    px.chunks(4).filter(|p| p[..3] != px[..3]).count()
}

#[test]
fn a_pmd_model_and_an_accessory_draw_through_their_effect() {
    let Some(gpu) = common::gpu() else { return };
    let Some(vk) = common::vkd3d() else { return };
    let fixtures = common::fixtures();
    let pmd =
        mds_formats::pmd::Pmd::read(&std::fs::read(fixtures.join("chain8.pmd")).unwrap()).unwrap();
    let mut host = Host::new((W, H));
    host.add(&gpu, "chain8.pmd", Source::Pmd(&pmd), 1.0, |_| None)
        .unwrap();
    // The PMM's model slot, so the pose is found.
    let pmm = Pmm::read(&std::fs::read(fixtures.join("mmegold/objects.pmm")).unwrap()).unwrap();
    let mut posed = mds_pose::model::Model::from_pmd(pmm.models[0].slot, &pmd).unwrap();
    for b in &mut posed.bones {
        b.mat_init = Mat4::IDENTITY;
    }
    let pmd_px = draw_with_objects_fx(&gpu, &vk, &mut host, std::slice::from_ref(&posed));
    assert!(covered(&pmd_px) > 1000, "PMD covers {}", covered(&pmd_px));

    // An accessory as the only object: its geometry drawn by the effect, as an object is.
    let acc = mds_accessory::vac::load_file(&fixtures.join("accessory/cube.x")).unwrap();
    let mut host = Host::new((W, H));
    host.add(&gpu, "cube.x", Source::Accessory(acc), 1.0, |_| None)
        .unwrap();
    let acc_px = draw_with_objects_fx(&gpu, &vk, &mut host, &[]);
    assert!(
        covered(&acc_px) > 100,
        "accessory covers {}",
        covered(&acc_px)
    );
}

/// One frame of `objects.pmm`'s camera and light over `host`'s objects: its pixels.
fn draw_scene(
    gpu: &mds_mmert::Gpu,
    vk: &mds_shader::vkd3d::Vkd3d,
    host: &mut Host,
    pmm: &Pmm,
    poses: &[mds_pose::model::Model],
    assignments: &[Assignment],
) -> Vec<u8> {
    let effects = common::fixtures().join("mme/effects");
    let resolve = |p: &str| effects.join(p);
    let c = evaluate_camera(&pmm.camera, 0.0, CameraMode::Playback).unwrap();
    let camera = Camera {
        target: c.position,
        rotation: c.rotation,
        distance: c.distance,
        fov_deg: c.fov,
        orthographic: false,
    };
    let f = Frame {
        pmm,
        poses,
        camera: &camera.into(),
        view_offset: [0.0; 2],
        shadow_map: Default::default(),
        shadow_map_display: false,
        light: evaluate_light(&pmm.light, 0.0, LightMode::Playback).unwrap(),
        frame: 0,
        elapsed: 0.0,
        size: (W, H),
        assignments,
        offscreen: &Default::default(),
        resolve: &resolve,
    };
    let mut log = Vec::new();
    let skipped = host.render(gpu, vk, &f, &mut log);
    assert!(skipped.is_empty(), "{skipped:?} {log:?}");
    host.target().unwrap().read(gpu).unwrap()
}

fn effect(path: &str) -> Assignment {
    Assignment {
        effect: path.into(),
        ..Assignment::default()
    }
}

/// The pixels covered in `px` whose four neighbours are covered too: away from the
/// antialiased silhouette.
fn interior(px: &[u8]) -> Vec<usize> {
    let bg = &px[..3];
    let on = |x: i64, y: i64| {
        let i = (y * i64::from(W) + x) as usize * 4;
        (0..i64::from(W)).contains(&x) && (0..i64::from(H)).contains(&y) && &px[i..i + 3] != bg
    };
    (0..(W * H) as i64)
        .filter(|&i| {
            let (x, y) = (i % i64::from(W), i / i64::from(W));
            on(x, y) && on(x - 1, y) && on(x + 1, y) && on(x, y - 1) && on(x, y + 1)
        })
        .map(|i| i as usize)
        .collect()
}

/// Item 1 of the host: a model the host draws hides an effect model behind it, through the
/// depth it writes with MME's matrices (MMEffect draws both into one depth buffer). `chain8.pmx`
/// twice: A at the origin with no effect, B with `objects.fx` moved 10 units away from the
/// camera and 1 to the side, so it shows beside A and is covered where they overlap.
#[test]
fn a_host_drawn_model_hides_an_effect_model_behind_it() {
    let Some(gpu) = common::gpu() else { return };
    let Some(vk) = common::vkd3d() else { return };
    let fixtures = common::fixtures();
    let mut pmm = Pmm::read(&std::fs::read(fixtures.join("mmegold/objects.pmm")).unwrap()).unwrap();
    let pmx = Pmx::read(&std::fs::read(fixtures.join("chain8.pmx")).unwrap()).unwrap();
    let mut b = pmm.models[0].clone();
    b.slot = pmm.models[0].slot + 1;
    pmm.models.push(b);
    let pose = |slot: u8, m: Mat4| {
        let mut p = mds_pose::model::Model::from_pmx(slot, &pmx).unwrap();
        for b in &mut p.bones {
            b.mat_init = m;
        }
        p
    };
    let (sa, sb) = (pmm.models[0].slot, pmm.models[1].slot);
    let mut host = Host::new((W, H));
    for name in ["a.pmx", "b.pmx"] {
        host.add(&gpu, name, Source::Pmx(&pmx), 0.0, |_| None)
            .unwrap();
    }
    // The camera's distance axis: B moved along it shrinks when it moves away.
    let none = Assignment::default();
    let mut only_b = |z: f32| {
        let poses = [
            pose(sa, Mat4::translation(0.0, -1000.0, 0.0)),
            pose(sb, Mat4::translation(1.0, 0.0, z)),
        ];
        draw_scene(
            &gpu,
            &vk,
            &mut host,
            &pmm,
            &poses,
            &[none.clone(), effect("objects.fx")],
        )
    };
    let (near, far) = (covered(&only_b(-10.0)), covered(&only_b(10.0)));
    let away = if near < far { -10.0 } else { 10.0 };
    let b_alone = only_b(away);
    let a_pose = pose(sa, Mat4::IDENTITY);
    let a_alone = draw_scene(
        &gpu,
        &vk,
        &mut host,
        &pmm,
        &[
            a_pose.clone(),
            pose(sb, Mat4::translation(0.0, -1000.0, 0.0)),
        ],
        &[none.clone(), effect("objects.fx")],
    );
    let both = draw_scene(
        &gpu,
        &vk,
        &mut host,
        &pmm,
        &[a_pose, pose(sb, Mat4::translation(1.0, 0.0, away))],
        &[none.clone(), effect("objects.fx")],
    );
    let a = interior(&a_alone);
    let bg = &b_alone[..3];
    let overlap: Vec<usize> = a
        .iter()
        .copied()
        .filter(|&i| &b_alone[i * 4..i * 4 + 3] != bg)
        .collect();
    assert!(
        overlap.len() > 200,
        "B behind A over {} pixels",
        overlap.len()
    );
    let differ = a
        .iter()
        .filter(|&&i| both[i * 4..i * 4 + 3] != a_alone[i * 4..i * 4 + 3])
        .count();
    assert_eq!(
        differ,
        0,
        "B shows through A at {differ} of {} pixels",
        a.len()
    );
    // B still draws where A does not cover it.
    let beside = (0..(W * H) as usize)
        .filter(|&i| a_alone[i * 4..i * 4 + 3] == a_alone[..3] && &b_alone[i * 4..i * 4 + 3] != bg)
        .filter(|&i| both[i * 4..i * 4 + 3] == b_alone[i * 4..i * 4 + 3])
        .count();
    assert!(beside > 200, "B beside A at {beside} pixels");

    let mut transparent = pmx.clone();
    for material in &mut transparent.materials {
        material.diffuse[3] = 0.0;
        material.flags &= !0x10;
    }
    let mut transparent_host = Host::new((W, H));
    transparent_host
        .add(
            &gpu,
            "transparent.pmx",
            Source::Pmx(&transparent),
            0.0,
            |_| None,
        )
        .unwrap();
    transparent_host
        .add(&gpu, "b.pmx", Source::Pmx(&pmx), 0.0, |_| None)
        .unwrap();
    let transparent_px = draw_scene(
        &gpu,
        &vk,
        &mut transparent_host,
        &pmm,
        &[
            pose(sa, Mat4::IDENTITY),
            pose(sb, Mat4::translation(1.0, 0.0, away)),
        ],
        &[none.clone(), effect("objects.fx")],
    );
    assert!(
        transparent_px == b_alone,
        "zero-alpha host material must not hide B"
    );
    let mut morphed = pmx.clone();
    for material in &mut morphed.materials {
        material.flags &= !0x10;
    }
    let mut values = [0.0; 28];
    values[3] = -1.0;
    let name = mds_formats::text::PmxText {
        raw: Vec::new(),
        text: String::new(),
    };
    morphed.morphs.push(mds_formats::pmx::Morph {
        name: name.clone(),
        name_en: name,
        panel: 4,
        kind: 8,
        offsets: mds_formats::pmx::Offsets::Material(vec![mds_formats::pmx::MaterialOffset {
            material: -1,
            operation: 1,
            values,
        }]),
    });
    let mut a = mds_pose::model::Model::from_pmx(sa, &morphed).unwrap();
    for bone in &mut a.bones {
        bone.mat_init = Mat4::IDENTITY;
    }
    a.morphs.last_mut().unwrap().value = 1.0;
    let mut host = Host::new((W, H));
    host.add(&gpu, "morphed.pmx", Source::Pmx(&morphed), 0.0, |_| None)
        .unwrap();
    host.add(&gpu, "b.pmx", Source::Pmx(&pmx), 0.0, |_| None)
        .unwrap();
    let pixels = draw_scene(
        &gpu,
        &vk,
        &mut host,
        &pmm,
        &[a, pose(sb, Mat4::translation(1.0, 0.0, away))],
        &[none, effect("objects.fx")],
    );
    assert!(
        pixels == b_alone,
        "material morph to zero alpha must not hide B"
    );
}

/// Item 2 of the host: an object whose effect is assigned to some subsets draws the others with
/// the standard shading, as the C++ forwards the raw draw of a subset with no binding
/// (`callbacks.cpp:236`). `chain8.pmx` split into two subsets, with `objects.fx` on subset 0
/// only, shows pixels of the all-effect picture and of the all-host one; with subset 0 hidden the
/// host draws the other alone.
#[test]
fn subsets_without_an_effect_draw_with_the_standard_shading() {
    let Some(gpu) = common::gpu() else { return };
    let Some(vk) = common::vkd3d() else { return };
    let fixtures = common::fixtures();
    let pmm = Pmm::read(&std::fs::read(fixtures.join("mmegold/objects.pmm")).unwrap()).unwrap();
    let mut pmx = Pmx::read(&std::fs::read(fixtures.join("chain8.pmx")).unwrap()).unwrap();
    // Its one material split in two halves of its faces.
    let mut second = pmx.materials[0].clone();
    let n = pmx.materials[0].face_vertex_count;
    pmx.materials[0].face_vertex_count = n / 6 * 3;
    second.face_vertex_count = n - n / 6 * 3;
    pmx.materials.push(second);
    let mut posed = mds_pose::model::Model::from_pmx(pmm.models[0].slot, &pmx).unwrap();
    for b in &mut posed.bones {
        b.mat_init = Mat4::IDENTITY;
    }
    let mut host = Host::new((W, H));
    host.add(&gpu, "chain8.pmx", Source::Pmx(&pmx), 0.0, |_| None)
        .unwrap();
    let poses = std::slice::from_ref(&posed);
    let mut draw = |a: Assignment| draw_scene(&gpu, &vk, &mut host, &pmm, poses, &[a]);
    let host_px = draw(Assignment::default());
    let effect_px = draw(effect("objects.fx"));
    let mut partial = Assignment::default();
    partial.subsets.insert(0, "objects.fx".into());
    let partial_px = draw(partial);
    let px = |p: &[u8], i: usize| p[i * 4..i * 4 + 3].to_vec();
    let (mut as_effect, mut as_host) = (0, 0);
    for i in interior(&partial_px) {
        let (p, h, e) = (px(&partial_px, i), px(&host_px, i), px(&effect_px, i));
        if h == e {
            continue;
        }
        as_effect += usize::from(p == e);
        as_host += usize::from(p == h);
    }
    assert!(
        as_effect > 100 && as_host > 100,
        "effect {as_effect}, host {as_host}"
    );
    // A hidden subset is not drawn by the host either (`callbacks.cpp:159`).
    let mut hidden = Assignment::default();
    hidden.subset_shows.insert(0, false);
    let hidden_px = draw(hidden);
    let (all, rest) = (covered(&host_px), covered(&hidden_px));
    assert!(
        rest > 100 && rest + 100 < all,
        "{rest} of {all} pixels without subset 0"
    );
}

#[test]
fn an_accessory_effect_hides_only_its_selected_material() {
    let gpu = common::gpu().expect("GPU required for accessory subset regression");
    let vk = common::vkd3d().expect("vkd3d required for accessory subset regression");
    let fixtures = common::fixtures();
    let mut pmm = Pmm::read(&std::fs::read(fixtures.join("mmegold/objects.pmm")).unwrap()).unwrap();
    pmm.models.clear();
    pmm.accessories = vec![mds_formats::pmm::Accessory {
        list_name: mds_formats::text::FixedSjis {
            raw: [0; 100],
            text: String::new(),
        },
        name: mds_formats::text::FixedSjis {
            raw: [0; 100],
            text: String::new(),
        },
        path: mds_formats::text::FixedSjis {
            raw: [0; 256],
            text: String::new(),
        },
        slot: 0,
        order: 0,
        keys: mds_formats::key_pool::KeyPool::new(
            10000,
            vec![mds_formats::pmm::AccessoryKey {
                opacity_visible: 1,
                parent_model: -1,
                scale: 0.1,
                ..Default::default()
            }],
        )
        .unwrap(),
        state: Default::default(),
    }];
    let acc = mds_accessory::load_x(
        br#"xof 0303txt 0032
Mesh Two {
8;
-4;-2;0;, -1;-2;0;, -1;2;0;, -4;2;0;,
1;-2;0;, 4;-2;0;, 4;2;0;, 1;2;0;;
4; 3;0,1,2;, 3;0,2,3;, 3;4,5,6;, 3;4,6,7;;
MeshMaterialList { 2; 4; 0,0,1,1;;
Material A { 1;0;0;1;; 1; 0;0;0;; 0;0;0;; }
Material B { 0;1;0;1;; 1; 0;0;0;; 0;0;0;; }
}
}"#,
    )
    .unwrap();
    let mut host = Host::new((W, H));
    host.add(&gpu, "two.x", Source::Accessory(acc.clone()), 0.0, |_| None)
        .unwrap();
    let all = draw_scene(&gpu, &vk, &mut host, &pmm, &[], &[Assignment::default()]);
    let dir = std::env::temp_dir().join(format!("mds-accessory-subsets-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let fx = dir.join("hide.fx");
    std::fs::write(
        &fx,
        "technique Hide < string MMDPass=\"object\"; string Subset=\"0\"; > {}",
    )
    .unwrap();
    let hidden = draw_scene(
        &gpu,
        &vk,
        &mut host,
        &pmm,
        &[],
        &[effect(fx.to_str().unwrap())],
    );
    let mut only_second = acc.clone();
    only_second.indices.drain(..6);
    only_second.face_material.drain(..2);
    let mut expected_host = Host::new((W, H));
    expected_host
        .add(
            &gpu,
            "second.x",
            Source::Accessory(only_second),
            0.0,
            |_| None,
        )
        .unwrap();
    let expected = draw_scene(
        &gpu,
        &vk,
        &mut expected_host,
        &pmm,
        &[],
        &[Assignment::default()],
    );
    assert!(
        covered(&expected) > 100,
        "material 1 must remain visible, covered {}, all {}",
        covered(&expected),
        covered(&all)
    );
    assert!(
        covered(&all) > covered(&expected) + 100,
        "material 0 must be visible in the control"
    );
    assert!(
        hidden == expected,
        "only material 1 should reach standard shading"
    );
    let restored = draw_scene(&gpu, &vk, &mut host, &pmm, &[], &[Assignment::default()]);
    assert!(
        restored == all,
        "removing the effect restores both materials"
    );

    let mut back = pmm.accessories[0].clone();
    back.slot = 1;
    back.keys.heads_mut()[0].position[2] = -1.0;
    pmm.accessories.push(back);
    let mut layered = Host::new((W, H));
    for name in ["front.x", "back.x"] {
        layered
            .add(&gpu, name, Source::Accessory(acc.clone()), 0.0, |_| None)
            .unwrap();
    }
    let absent = Assignment {
        shown: false,
        ..Assignment::default()
    };
    let behind = draw_scene(
        &gpu,
        &vk,
        &mut layered,
        &pmm,
        &[],
        &[absent, effect("objects.fx")],
    );
    let opaque = draw_scene(
        &gpu,
        &vk,
        &mut layered,
        &pmm,
        &[],
        &[Assignment::default(), effect("objects.fx")],
    );
    assert!(
        covered(&behind) > 100 && opaque != behind,
        "opaque accessory must occlude the effect control"
    );
    pmm.accessories[0].keys.heads_mut()[0].opacity_visible = 201;
    let transparent = draw_scene(
        &gpu,
        &vk,
        &mut layered,
        &pmm,
        &[],
        &[Assignment::default(), effect("objects.fx")],
    );
    assert!(
        transparent == behind,
        "zero accessory opacity must not write depth"
    );
    pmm.accessories[0].keys.heads_mut()[0].opacity_visible = 1;
    let mut clear = acc.clone();
    for material in &mut clear.materials {
        material.diffuse[3] = 0.0;
    }
    let mut layered = Host::new((W, H));
    layered
        .add(&gpu, "clear.x", Source::Accessory(clear), 0.0, |_| None)
        .unwrap();
    layered
        .add(&gpu, "back.x", Source::Accessory(acc), 0.0, |_| None)
        .unwrap();
    let transparent = draw_scene(
        &gpu,
        &vk,
        &mut layered,
        &pmm,
        &[],
        &[Assignment::default(), effect("objects.fx")],
    );
    assert!(
        transparent == behind,
        "zero accessory material alpha must not write depth"
    );
    std::fs::remove_dir_all(dir).unwrap();
}
