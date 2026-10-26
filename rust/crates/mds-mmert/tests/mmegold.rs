//! The runtime against the C++ application's MME path: the scenes, probes, and images of
//! `tests/fixtures/rust/mmegold/` (README there: `--mds-mme-dump`, the probe format).
//!
//! The test is the host. Per scene it loads the PMM, takes the effect rows of the EMM, loads the
//! effects, and renders every frame from 0 as the dump does: frame 0 twice, then each frame.
//! A frame draws each offscreen turn's objects, then the scene: per material subset the object
//! pass, then the edge pass, each with the technique `SasSelectTechnique` picks (a post effect
//! draws the scene at `ScriptExternal`), and ticks the animated textures at its end. The camera,
//! light, and world matrices are composed as `SetupFrameWorldTransform` and `OnBeginScene` do;
//! the poses come from `mds-physics` (physics mode 0: the motion alone).
//!
//! 1. Inputs: after each probed frame, every numeric parameter of every effect the probe lists
//!    equals it within [`VALUE_TOL`] (the count of bit-equal values is printed). `MOUSEPOSITION`
//!    follows the host's cursor and is not compared. [`KNOWN_INPUTS`] lists the known differences.
//! 2. Pixels: the 640x360 image against the golden PNG by the rule of [`LIMITS`], outside what
//!    the host draws itself: the grid, axes, ground line, and bone marks (every pixel that is not
//!    white in `offscreen-0.png`, whose effect draws nothing visible) and the models without an
//!    effect ([`Host::host_drawn`]). [`PIXEL_GATED`] lists the scenes that meet it; the table
//!    prints them all. Not gated: `ray`, whose C++ image is broken (`ClearSetStencil` is
//!    unsupported there), and `post`, whose C++ image is white everywhere, grid included, where
//!    the runtime's Final pass shows `Work` cleared to `ClearColor`.
//!
//! `MDS_MMERT_PNG_DIR=<dir>` writes `<scene>-<frame>.png` and a difference image per frame.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use mds_formats::pmm::Pmm;
use mds_formats::pmx::Pmx;
use mds_math::Mat4;
use mds_mme::sas::SEM_OFFSCREEN;
use mds_mmert::bind::{look_at_lh, mul, perspective_lh, Mat, DRAW_EDGE, DRAW_OBJECT};
use mds_mmert::control::{Controls, Object};
use mds_mmert::emm::{parse_emm, Assignment};
use mds_mmert::scene::{turn_draw, TurnDraw, TurnObject};
use mds_mmert::{DrawInput, Effect, Gpu, Model, Scene, Target};
use mds_physics::PhysicsScene;
use mds_scene::track::{evaluate_camera, evaluate_light, CameraMode, LightMode};
use mds_shader::vkd3d::Vkd3d;

mod common;

const W: u32 = 640;
const H: u32 = 360;
/// The back buffer of the C++ run (README), which `ViewportRatio` targets are sized against. The
/// picture is its 640x360 corner.
const BACKBUFFER: (u32, u32) = (3072, 1728);

/// Scenes and their probed frames (`SCENES` of `gen_mmegold.py`).
const SCENES: [(&str, &[u32]); 8] = [
    ("objects", &[0, 30]),
    ("post", &[0, 30]),
    ("offscreen", &[0, 30]),
    ("timeofday", &[0, 30]),
    ("main", &[0, 30]),
    ("control", &[0, 15, 30]),
    ("anime", &[0, 3, 4, 9, 30]),
    ("ray", &[0, 30]),
];

/// `|rust - probe| <= VALUE_TOL * max(1, |probe|)`. The probe's matrices come from D3DX on x64;
/// the runtime's from `mds-math` and plain f32 products, which differ in the last bits.
const VALUE_TOL: f32 = 1e-5;

/// `(scene, effect file, parameter)` that differ from the probe, and why.
const KNOWN_INPUTS: &[(&str, &str, &str, &str)] = &[(
    "ray",
    "ray-mmd/ray.fx",
    "MaterialPower",
    "a scene effect binds the stale device material of the host's last draw (5, chain8's power); \
     the runtime has no device material and binds none (0.1)",
)];

/// Scenes whose every probed frame meets [`LIMITS`].
const PIXEL_GATED: &[&str] = &[
    "objects",
    "offscreen",
    "timeofday",
    "main",
    "control",
    "anime",
];

/// MMEffect `SasMmdPass`: the draw modes `plan::select` takes.
const PASS_OBJECT: i32 = 0;
const PASS_EDGE: i32 = 3;

/// PMX material flag: draw the edge.
const FLAG_EDGE: u8 = 0x10;

fn mmegold() -> PathBuf {
    common::fixtures().join("mmegold")
}

/// The scene's own effects staged with `blink.gif` beside them, as `mmegold.ps1` stages them.
fn stage() -> PathBuf {
    let dir = std::env::temp_dir().join(format!("mds-mmertgold-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    for f in ["anime.fx", "control.fx"] {
        std::fs::copy(mmegold().join(f), dir.join(f)).unwrap();
    }
    let gif = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/data/blink.gif");
    std::fs::copy(gif, dir.join("blink.gif")).unwrap();
    dir
}

// ---- the probe ----

#[derive(Debug)]
struct Param {
    name: String,
    semantic: String,
    values: Vec<f32>,
}

#[derive(Debug)]
struct ProbeEffect {
    path: String,
    params: Vec<Param>,
}

#[derive(Debug)]
struct Probe {
    frame: u32,
    time: f32,
    /// `(object file, assigned effect or "-")`.
    objects: Vec<(String, String)>,
    effects: Vec<ProbeEffect>,
}

fn parse_probe(text: &str) -> Probe {
    let mut lines = text.lines();
    assert_eq!(lines.next(), Some("mds-mme-probe 1"));
    let mut p = Probe {
        frame: 0,
        time: 0.0,
        objects: Vec::new(),
        effects: Vec::new(),
    };
    for line in lines {
        let f: Vec<&str> = line.split(' ').collect();
        match f[0] {
            "frame" => {
                p.frame = f[1].parse().unwrap();
                p.time = f[2].parse().unwrap();
            }
            // object <file> effect <path> class C render R shown S; the path may hold spaces.
            "object" => {
                let at = f.iter().position(|&w| w == "effect").unwrap();
                let n = f.len();
                p.objects
                    .push((f[1..at].join(" "), f[at + 1..n - 6].join(" ")));
            }
            // effect <path> class C order O errors E
            "effect" => p.effects.push(ProbeEffect {
                path: f[1..f.len() - 6].join(" "),
                params: Vec::new(),
            }),
            // param <name> <semantic> <class> <type> <RxCxE> <value>...
            "param" => p.effects.last_mut().unwrap().params.push(Param {
                name: f[1].into(),
                semantic: f[2].into(),
                values: f[6..].iter().map(|v| v.parse().unwrap()).collect(),
            }),
            _ => panic!("unknown probe line: {line}"),
        }
    }
    p
}

// ---- the host ----

/// Where an effect path of the stage lives here: `(file, root)`.
fn local(path: &str, stage: &Path, corpus: &Path) -> (PathBuf, PathBuf) {
    let path = path.replace('\\', "/");
    let (dir, rest) = path.split_once('/').unwrap();
    let root = match dir {
        "effects" => common::fixtures().join("mme/effects"),
        "mmegold" => stage.to_path_buf(),
        "ray-mmd" => corpus.to_path_buf(),
        _ => panic!("unknown effect root in {path}"),
    };
    (root.join(rest), root)
}

/// The probe's spelling of an EMM effect row (`$(fixtures)\objects.fx` is `effects/objects.fx`).
fn stage_path(row: &str) -> String {
    row.replace("$(fixtures)", "effects")
        .replace("$(mmegold)", "mmegold")
        .replace("$(corpus)", "ray-mmd")
        .replace('\\', "/")
}

fn file_name(path: &str) -> &str {
    path.rsplit(['\\', '/']).next().unwrap()
}

fn scene_file(path: &str) -> Result<Vec<u8>, String> {
    let name = file_name(path);
    std::fs::read(common::fixtures().join(name)).map_err(|e| format!("{name}: {e}"))
}

fn m4(m: &Mat4) -> Mat {
    m.0
}

/// The frame's camera, light, and clocks as MMEffect's `OnBeginScene` sees them: the device
/// world is the frame world of `SetupFrameWorldTransform` (the target to the origin, then yaw,
/// pitch, roll), the device view its fixed look along +z from the camera distance, and the
/// projection `RefreshMainWindowViewport`'s. MME's `VIEW` is the world times the view, and an
/// object's `WORLD` its device world (its own world times the frame world) times the inverse of
/// the frame world. Also returns the frame world and its inverse.
fn host_scene(pmm: &Pmm, frame: u32, elapsed: f32) -> (Scene, Mat, Mat) {
    let c = evaluate_camera(&pmm.camera, f64::from(frame), CameraMode::Playback).unwrap();
    let [pitch, yaw, roll] = c.rotation;
    let t = Mat4::translation(-c.position[0], -c.position[1], -c.position[2]);
    let r = Mat4::multiply(&Mat4::rotation_y(yaw), &Mat4::rotation_x(pitch));
    let r = Mat4::multiply(&r, &Mat4::rotation_z(roll));
    let frame_world = Mat4::multiply(&t, &r);
    let inverse = frame_world.inverse().unwrap().0 .0;
    let eye = [0.0, 0.0, c.distance];
    let view = look_at_lh(eye, [0.0, 0.0, c.distance + 80.0], [0.0, 1.0, 0.0]);
    let fov = (f64::from(c.fov) * std::f64::consts::PI / 180.0) as f32;
    let light = evaluate_light(&pmm.light, f64::from(frame), LightMode::Playback).unwrap();
    let color = [light[0], light[1], light[2]];
    let mut s = Scene::default_view(W, H);
    s.world = mul(&m4(&frame_world), &inverse);
    s.view = mul(&m4(&frame_world), &view);
    s.projection = perspective_lh(fov, W as f32 / H as f32, 1.0, 100000.0);
    s.light_direction = [light[3], light[4], light[5]];
    s.light_ambient = color;
    s.light_diffuse = color;
    s.light_specular = color;
    s.time = frame as f32 / 30.0;
    s.elapsed = elapsed;
    (s, m4(&frame_world), inverse)
}

/// The scene's objects as the host exports them: the models by draw order (1-based), with
/// their bones and morphs from the pose, then the accessories.
fn host_controls(pmm: &Pmm, pmxs: &[Pmx], physics: &PhysicsScene, frame: u32) -> Controls {
    let mut objects = Vec::new();
    for (i, (m, pmx)) in pmm.models.iter().zip(pmxs).enumerate() {
        let mut o = Object::model(file_name(&m.path.text), i as i32 + 1);
        let posed = physics
            .scene
            .models
            .iter()
            .find(|p| p.slot == m.slot)
            .unwrap();
        o.bones = pmx
            .bones
            .iter()
            .zip(&posed.bones)
            .map(|(b, p)| (b.name.text.clone(), bone_world(p)))
            .collect();
        o.morphs = pmx
            .morphs
            .iter()
            .zip(&posed.morphs)
            .map(|(m, p)| (m.name.text.clone(), p.value))
            .collect();
        objects.push(o);
    }
    for (a, (state, world)) in pmm.accessories.iter().zip(accessories(pmm, physics, frame)) {
        let mut o = Object::model(file_name(&a.path.text), i32::from(a.order) + 1);
        o.model = false;
        o.shown = state.visible;
        o.world = world;
        let [x, y, z] = state.position;
        let [rx, ry, rz] = state.rotation;
        o.accessory = [x, y, z, rx, ry, rz, state.scale, state.opacity];
        objects.push(o);
    }
    Controls { objects }
}

/// `ExpGetPmdBoneWorldMat`: the bone's position moved by its world matrix.
fn bone_world(b: &mds_pose::model::Bone) -> Mat {
    let [x, y, z] = b.position;
    Mat4::multiply(&Mat4::translation(x, y, z), &b.mat_init).0
}

/// The state and world matrix of each PMM accessory at `frame`.
fn accessories(
    pmm: &Pmm,
    physics: &PhysicsScene,
    frame: u32,
) -> Vec<(mds_accessory::AccessoryState, Mat)> {
    pmm.accessories
        .iter()
        .map(|a| mds_render::scene::accessory_at(a, frame, &physics.scene.models).unwrap())
        .collect()
}

/// One loaded effect and the object (an index into the controls) it is assigned to.
struct Loaded {
    path: String,
    effect: Effect,
    owner: usize,
}

struct Host {
    pmm: Pmm,
    pmxs: Vec<Pmx>,
    model: Model,
    /// The effects the EMM assigns, then those the offscreen turns load.
    effects: Vec<Loaded>,
    stage: PathBuf,
    corpus: PathBuf,
    /// The EMM rows, by object index.
    assignments: Vec<Assignment>,
}

impl Host {
    fn new(gpu: &Gpu, vk: &Vkd3d, name: &str, stage: &Path, corpus: &Path) -> Host {
        let pmm =
            Pmm::read(&std::fs::read(mmegold().join(format!("{name}.pmm"))).unwrap()).unwrap();
        let pmxs: Vec<Pmx> = pmm
            .models
            .iter()
            .map(|m| Pmx::read(&scene_file(&m.path.text).unwrap()).unwrap())
            .collect();
        let model = Model::from_pmx(&gpu.device, &pmxs[0]).unwrap();
        let emm_path = mmegold().join(format!("{name}.emm"));
        let (emm, log) = parse_emm(
            &std::fs::read(&emm_path).unwrap(),
            &emm_path.to_string_lossy(),
        );
        let emm = emm.unwrap_or_else(|| panic!("{name}.emm: {log:?}"));
        let section = emm.sections.iter().find(|s| s.is_default()).unwrap();
        let n_models = pmm.models.len();
        let mut assignments = vec![Assignment::default(); n_models + pmm.accessories.len()];
        let mut effects = Vec::new();
        for e in &section.entries {
            let (model, slot) = if let Some(s) = e.key.strip_prefix("Pmd") {
                (true, s.parse::<usize>().unwrap())
            } else {
                (false, e.key.strip_prefix("Acs").unwrap().parse().unwrap())
            };
            let owner = if model { slot } else { n_models + slot };
            let path = stage_path(&e.effect);
            assignments[owner].effect = path.clone();
            let (file, root) = local(&path, stage, corpus);
            let effect = Effect::load(gpu, vk, &file, &root, BACKBUFFER)
                .unwrap_or_else(|e| panic!("{path}: {e}"));
            effects.push(Loaded {
                path,
                effect,
                owner,
            });
        }
        Host {
            pmm,
            pmxs,
            model,
            effects,
            stage: stage.to_path_buf(),
            corpus: corpus.to_path_buf(),
            assignments,
        }
    }

    /// The pixels the host draws with its own shading at `frame`: the screen rectangle, 2 px
    /// wider, of each model other than the effect owner that has no effect (`morph4.pmx` of
    /// `control`). Each vertex moves with its first bone.
    fn host_drawn(&self, physics: &PhysicsScene, frame: u32) -> Vec<bool> {
        let (scene, _, _) = host_scene(&self.pmm, frame, 0.0);
        let view_proj = mul(&scene.view, &scene.projection);
        let mut mask = vec![false; (W * H) as usize];
        for (i, (m, pmx)) in self.pmm.models.iter().zip(&self.pmxs).enumerate().skip(1) {
            if !self.assignments[i].effect.is_empty() {
                continue;
            }
            let posed = physics
                .scene
                .models
                .iter()
                .find(|p| p.slot == m.slot)
                .unwrap();
            let (mut lo, mut hi) = ([f32::MAX; 2], [f32::MIN; 2]);
            for v in &pmx.vertices {
                let b = &posed.bones[v.bones[0] as usize].mat_init.0;
                let p: [f32; 3] = std::array::from_fn(|c| {
                    v.position[0] * b[c]
                        + v.position[1] * b[4 + c]
                        + v.position[2] * b[8 + c]
                        + b[12 + c]
                });
                let clip: [f32; 4] = std::array::from_fn(|c| {
                    p[0] * view_proj[c]
                        + p[1] * view_proj[4 + c]
                        + p[2] * view_proj[8 + c]
                        + view_proj[12 + c]
                });
                let px = [
                    (clip[0] / clip[3] + 1.0) * 0.5 * W as f32,
                    (1.0 - clip[1] / clip[3]) * 0.5 * H as f32,
                ];
                for c in 0..2 {
                    lo[c] = lo[c].min(px[c]);
                    hi[c] = hi[c].max(px[c]);
                }
            }
            let range = |c: usize, n: u32| {
                (lo[c] - 2.0).floor().max(0.0) as u32..((hi[c] + 2.0).ceil().max(0.0) as u32).min(n)
            };
            for y in range(1, H) {
                for x in range(0, W) {
                    mask[(y * W + x) as usize] = true;
                }
            }
        }
        mask
    }

    /// Index of the loaded effect `path`, loading it for an offscreen turn's object.
    fn effect_for(&mut self, gpu: &Gpu, vk: &Vkd3d, file: &Path, owner: usize) -> usize {
        let rel = |root: &Path| file.strip_prefix(root).ok().map(Path::to_path_buf);
        let path = if let Some(r) = rel(&self.corpus) {
            format!("ray-mmd/{}", r.to_string_lossy())
        } else if let Some(r) = rel(&common::fixtures().join("mme/effects")) {
            format!("effects/{}", r.to_string_lossy())
        } else {
            format!("mmegold/{}", rel(&self.stage).unwrap().to_string_lossy())
        }
        .replace('\\', "/");
        if let Some(i) = self.effects.iter().position(|l| l.path == path) {
            return i;
        }
        let (file, root) = local(&path, &self.stage, &self.corpus);
        let effect = Effect::load(gpu, vk, &file, &root, BACKBUFFER)
            .unwrap_or_else(|e| panic!("{path}: {e}"));
        self.effects.push(Loaded {
            path,
            effect,
            owner,
        });
        self.effects.len() - 1
    }

    /// The object and edge passes of the model (object 0) with effect `e` into `target`.
    fn draw_model(
        &mut self,
        gpu: &Gpu,
        e: usize,
        target: &Target,
        input: &DrawInput,
    ) -> Vec<String> {
        let mut skipped = Vec::new();
        let model = &self.model;
        let pmx = &self.pmxs[0];
        for (mode, draw_type) in [(PASS_OBJECT, DRAW_OBJECT), (PASS_EDGE, DRAW_EDGE)] {
            for (s, m) in model.materials.iter().enumerate() {
                if mode == PASS_EDGE && pmx.materials[s].flags & FLAG_EDGE == 0 {
                    continue;
                }
                let effect = &mut self.effects[e].effect;
                let input = DrawInput {
                    geometry: Some((model, s)),
                    draw_type,
                    ..*input
                };
                // Every host draw binds the effect's parameters, whether a technique takes it
                // or not (MmeApplyModelRenderSnapshot).
                effect.bind(&input);
                // Only the object passes select by the material's Use* state.
                let object = mode == PASS_OBJECT;
                let (Some(h), _) = mds_mme::plan::select(
                    &effect.sas,
                    mode,
                    s as i32,
                    object && m.has_texture,
                    object && m.sphere_mode > 0,
                    object && m.toon,
                ) else {
                    continue;
                };
                let tech = effect
                    .sas
                    .techniques
                    .iter()
                    .position(|t| t.fx == h)
                    .unwrap();
                let r = effect.draw_technique(gpu, target, &input, tech);
                skipped.extend(r.skipped);
            }
        }
        skipped
    }

    /// Renders `frame` into `target` and returns why draws were skipped.
    fn render(
        &mut self,
        gpu: &Gpu,
        vk: &Vkd3d,
        target: &Target,
        frame: u32,
        elapsed: f32,
        physics: &PhysicsScene,
    ) -> Vec<String> {
        let (scene, frame_world, inverse) = host_scene(&self.pmm, frame, elapsed);
        let controls = host_controls(&self.pmm, &self.pmxs, physics, frame);
        // A post effect's carrier is the accessory: its WORLD is the accessory's.
        let n_models = self.pmm.models.len();
        let carrier_scenes: Vec<Scene> = accessories(&self.pmm, physics, frame)
            .iter()
            .map(|(_, w)| Scene {
                world: mul(&mul(w, &frame_world), &inverse),
                ..scene.clone()
            })
            .collect();
        let scene_of = |owner: usize| {
            if owner < n_models {
                &scene
            } else {
                &carrier_scenes[owner - n_models]
            }
        };
        let base = DrawInput {
            scene: &scene,
            geometry: None,
            draw_type: DRAW_OBJECT,
            controls: Some(&controls),
            owner: None,
            offscreen_owner: None,
        };
        let mut skipped = Vec::new();
        let names: Vec<String> = controls.objects.iter().map(|o| o.name.clone()).collect();

        // The offscreen turns: each target of each assigned effect, the model drawn as its rows say.
        let carriers: Vec<usize> = (0..self.effects.len()).collect();
        for c in carriers {
            let owner = self.effects[c].owner;
            let targets: Vec<usize> = (0..self.effects[c].effect.sas.resources.len())
                .filter(|&r| self.effects[c].effect.sas.resources[r].semantic == SEM_OFFSCREEN)
                .collect();
            for r in targets {
                let Some(turn) = self.effects[c].effect.begin_offscreen(gpu, r) else {
                    continue;
                };
                let obj = TurnObject {
                    name: &names[0],
                    owner: owner == 0,
                    render_class: i32::from(
                        self.effects
                            .iter()
                            .any(|l| l.owner == 0 && l.effect.sas.script_class == 1),
                    ),
                    main: &self.assignments[0],
                };
                let draw = turn_draw(&self.effects[c].effect.sas.resources[r], &obj, None);
                if let TurnDraw::Effect(file) = draw {
                    let e = self.effect_for(gpu, vk, &file, 0);
                    // VIEWPORTPIXELSIZE in a turn is its target's.
                    let turn_scene = Scene {
                        viewport: (turn.color.width(), turn.color.height()),
                        ..scene.clone()
                    };
                    let input = DrawInput {
                        scene: &turn_scene,
                        owner: Some(0),
                        offscreen_owner: Some(owner),
                        ..base
                    };
                    skipped.extend(self.draw_model(gpu, e, &turn, &input));
                }
            }
        }

        // The scene: a post effect draws the objects at its ScriptExternal; without one the
        // objects draw into the back buffer after the host's clear.
        target.clear_turn(gpu, Some(scene.background), 1.0, true);
        let objects: Vec<usize> = (0..self.effects.len())
            .filter(|&i| {
                let l = &self.effects[i];
                l.owner == 0
                    && l.path == self.assignments[0].effect
                    && l.effect.sas.script_class != 1
            })
            .collect();
        let posts: Vec<usize> = (0..self.effects.len())
            .filter(|&i| {
                let l = &self.effects[i];
                l.path == self.assignments[l.owner].effect && l.effect.sas.script_class == 1
            })
            .collect();
        if posts.is_empty() {
            for &e in &objects {
                let input = DrawInput {
                    owner: Some(0),
                    ..base
                };
                skipped.extend(self.draw_model(gpu, e, target, &input));
            }
        }
        for p in posts {
            // The post effect leaves the list while it runs, so that the scene draw can borrow the
            // object effects.
            let mut post = self.effects.remove(p);
            let objects: Vec<usize> = objects
                .iter()
                .map(|&e| if e > p { e - 1 } else { e })
                .collect();
            let input = DrawInput {
                scene: scene_of(post.owner),
                owner: Some(post.owner),
                ..base
            };
            let mut inner = Vec::new();
            let r = post
                .effect
                .frame_with_scene(gpu, target, &input, &mut |_, t| {
                    for &e in &objects {
                        let input = DrawInput {
                            owner: Some(0),
                            ..base
                        };
                        inner.extend(self.draw_model(gpu, e, t, &input));
                    }
                });
            self.effects.insert(p, post);
            skipped.extend(r.skipped);
            skipped.extend(inner);
        }
        for l in &mut self.effects {
            l.effect.tick_animes(gpu, scene.time);
        }
        skipped
    }
}

/// Renders `name` from frame 0 to its last probed frame and calls `at` after each probed frame
/// with the image, the skipped draws, and [`Host::host_drawn`]. Returns the wgpu errors.
fn run_scene(
    gpu: &Gpu,
    vk: &Vkd3d,
    host: &mut Host,
    frames: &[u32],
    mut at: impl FnMut(&Host, u32, Vec<u8>, Vec<String>, Vec<bool>),
) -> Vec<String> {
    let mut physics = PhysicsScene::new(&host.pmm, scene_file).unwrap();
    let target = Target::new(gpu, (W, H));
    let ((), errors) = gpu.scoped(|| {
        // The render while the app loads: the frame before frame 0 in edit mode, which makes
        // ELAPSEDTIME 0 at frame 0.
        host.render(gpu, vk, &target, 0, 0.0, &physics);
        for f in 0..=*frames.iter().max().unwrap() {
            if f > 0 {
                physics.step().unwrap();
            }
            let elapsed = if f == 0 { 0.0 } else { 1.0 / 30.0 };
            let skipped = host.render(gpu, vk, &target, f, elapsed, &physics);
            if frames.contains(&f) {
                let drawn = host.host_drawn(&physics, f);
                at(host, f, target.read(gpu).unwrap(), skipped, drawn);
            }
        }
    });
    errors
}

// ---- inputs ----

#[derive(Default)]
struct InputScore {
    values: usize,
    exact: usize,
    skipped: usize,
    /// Values of the parameters that differ.
    differing: usize,
    /// The differences not in [`KNOWN_INPUTS`], then the known ones.
    failures: Vec<String>,
    known: Vec<String>,
}

fn close(a: f32, b: f32) -> bool {
    (a - b).abs() <= VALUE_TOL * b.abs().max(1.0)
}

fn compare_inputs(scene: &str, host: &Host, probe: &Probe, out: &mut InputScore) {
    let at = format!("{scene}-{}", probe.frame);
    let assigned: Vec<(String, String)> = host
        .pmm
        .models
        .iter()
        .map(|m| file_name(&m.path.text).to_string())
        .chain(
            host.pmm
                .accessories
                .iter()
                .map(|a| a.path.text.replace('\\', "/")),
        )
        .zip(&host.assignments)
        .map(|(n, a)| {
            let e = if a.effect.is_empty() {
                "-".into()
            } else {
                a.effect.clone()
            };
            (n, e)
        })
        .collect();
    if assigned != probe.objects {
        out.failures.push(format!(
            "{at}: objects {assigned:?}, probe {:?}",
            probe.objects
        ));
    }
    for pe in &probe.effects {
        let Some(l) = host
            .effects
            .iter()
            .find(|l| l.path.eq_ignore_ascii_case(&pe.path))
        else {
            out.failures.push(format!("{at}: {} not loaded", pe.path));
            continue;
        };
        for p in &pe.params {
            if p.semantic == "MOUSEPOSITION" {
                out.skipped += p.values.len();
                continue;
            }
            let Some(i) = l.effect.sas.fx.param_by_name(&p.name) else {
                out.failures
                    .push(format!("{at}: {} has no parameter {}", pe.path, p.name));
                continue;
            };
            let rust = &l.effect.values[i];
            out.values += p.values.len();
            out.exact += rust
                .iter()
                .zip(&p.values)
                .filter(|(a, b)| a.to_bits() == b.to_bits())
                .count();
            if rust.len() == p.values.len()
                && rust.iter().zip(&p.values).all(|(&a, &b)| close(a, b))
            {
                continue;
            }
            out.differing += p.values.len();
            let line = format!(
                "{at}: {} {} ({}): rust {rust:?}, probe {:?}",
                pe.path, p.name, p.semantic, p.values
            );
            match KNOWN_INPUTS
                .iter()
                .find(|k| k.0 == scene && k.1 == pe.path && k.2 == p.name)
            {
                Some(k) => out.known.push(format!("{line} [known: {}]", k.3)),
                None => out.failures.push(line),
            }
        }
    }
}

// ---- pixels ----

/// A pixel is close when no channel of R, G, B is more than `tolerance` from the golden image.
/// An image passes when `min_close` of its pixels are close and every other pixel is on an edge
/// of the golden image (its 3x3 neighbourhood there is not one colour within `tolerance`): the
/// runtime draws without multisampling, so a silhouette pixel may differ by up to 255.
struct Limits {
    tolerance: u8,
    min_close: f64,
}

const LIMITS: Limits = Limits {
    tolerance: 4,
    min_close: 0.995,
};

#[derive(Debug)]
struct Score {
    pixels: usize,
    close: f64,
    max: u8,
    mean: f64,
    /// Pixels beyond the tolerance inside a flat area of the golden image.
    flat: usize,
}

impl Score {
    fn passes(&self) -> bool {
        self.close >= LIMITS.min_close && self.flat == 0
    }
}

/// Whether the 3x3 neighbourhood of pixel `i` of `gold` is one colour within the tolerance.
fn flat(gold: &[u8], i: usize) -> bool {
    let (x, y) = ((i % W as usize) as i64, (i / W as usize) as i64);
    (-1..=1).all(|dy| {
        (-1..=1).all(|dx| {
            let (nx, ny) = (x + dx, y + dy);
            !(0..W as i64).contains(&nx)
                || !(0..H as i64).contains(&ny)
                || pixel_diff_at(gold, i, (ny * W as i64 + nx) as usize) <= LIMITS.tolerance
        })
    })
}

fn pixel_diff_at(px: &[u8], i: usize, j: usize) -> u8 {
    (0..3)
        .map(|c| px[i * 4 + c].abs_diff(px[j * 4 + c]))
        .max()
        .unwrap()
}

fn read_png(path: &Path) -> Vec<u8> {
    let data = std::fs::read(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let mut reader = png::Decoder::new(std::io::Cursor::new(data))
        .read_info()
        .unwrap();
    let mut buf = vec![0; reader.output_buffer_size().unwrap()];
    let info = reader.next_frame(&mut buf).unwrap();
    assert_eq!(info.color_type, png::ColorType::Rgba);
    assert_eq!((info.width, info.height), (W, H));
    buf
}

fn encode_png(px: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    let mut enc = png::Encoder::new(&mut out, W, H);
    enc.set_color(png::ColorType::Rgba);
    enc.write_header().unwrap().write_image_data(px).unwrap();
    out
}

fn pixel_diff(a: &[u8], b: &[u8], i: usize) -> u8 {
    (0..3)
        .map(|c| a[i * 4 + c].abs_diff(b[i * 4 + c]))
        .max()
        .unwrap()
}

/// What the app draws besides the effects: the grid, the axes, the ground line, and the bone
/// marks. `offscreen-0.png` holds them alone (its effect draws nothing visible), so every pixel
/// that is not white there is left out.
fn overlay() -> Vec<bool> {
    read_png(&mmegold().join("offscreen-0.png"))
        .chunks(4)
        .map(|p| p[..3] != [255, 255, 255])
        .collect()
}

fn score(px: &[u8], gold: &[u8], mask: &[bool], name: &str, dir: Option<&Path>) -> Score {
    let n_px = (W * H) as usize;
    let mut diff: Vec<u8> = [255, 0, 255, 255].repeat(n_px);
    let (mut n, mut close, mut max, mut sum, mut flats) = (0, 0, 0u8, 0u64, 0);
    for i in (0..n_px).filter(|&i| !mask[i]) {
        let d = pixel_diff(px, gold, i);
        flats += usize::from(d > LIMITS.tolerance && flat(gold, i));
        let v = 255 - d.saturating_mul(4);
        diff[i * 4..i * 4 + 3].copy_from_slice(&[v, v, v]);
        n += 1;
        close += usize::from(d <= LIMITS.tolerance);
        max = max.max(d);
        sum += u64::from(d);
    }
    if let Some(dir) = dir {
        std::fs::create_dir_all(dir).unwrap();
        std::fs::write(dir.join(format!("{name}.png")), encode_png(px)).unwrap();
        std::fs::write(dir.join(format!("{name}-diff.png")), encode_png(&diff)).unwrap();
    }
    Score {
        pixels: n,
        close: close as f64 / n as f64,
        max,
        mean: sum as f64 / n as f64,
        flat: flats,
    }
}

#[test]
fn scenes_match_the_cpp_probes_and_images() {
    let Some(gpu) = common::gpu() else { return };
    let Some(vk) = common::vkd3d() else { return };
    let corpus = common::corpus();
    let stage = stage();
    let mask = overlay();
    let png_dir = std::env::var_os("MDS_MMERT_PNG_DIR").map(PathBuf::from);
    let mut inputs = InputScore::default();
    let mut table = vec![format!(
        "{:<14} {:>7} {:>9} {:>4} {:>7} {:>5}  gated",
        "image", "pixels", "within 4", "max", "mean", "flat"
    )];
    let mut pixel_failures = Vec::new();
    let mut by_scene: BTreeMap<&str, bool> = BTreeMap::new();
    for (name, frames) in SCENES {
        let text = std::fs::read_to_string(mmegold().join(format!("{name}.emm"))).unwrap();
        let corpus = match &corpus {
            Some(c) => c.clone(),
            None if text.contains("$(corpus)") => {
                eprintln!("SKIP {name}: needs the corpus (a skip is not a pass)");
                continue;
            }
            None => PathBuf::new(),
        };
        let mut host = Host::new(&gpu, &vk, name, &stage, &corpus);
        let errors = run_scene(
            &gpu,
            &vk,
            &mut host,
            frames,
            |host, f, px, skipped, drawn| {
                let probe = parse_probe(
                    &std::fs::read_to_string(mmegold().join(format!("{name}-{f}.mme.txt")))
                        .unwrap(),
                );
                assert_eq!((probe.frame, probe.time), (f, f as f32 / 30.0));
                compare_inputs(name, host, &probe, &mut inputs);
                if !skipped.is_empty() {
                    eprintln!("{name}-{f}: skipped draws {skipped:?}");
                }
                let gold = read_png(&mmegold().join(format!("{name}-{f}.png")));
                let image = format!("{name}-{f}");
                let mask: Vec<bool> = mask.iter().zip(&drawn).map(|(a, b)| a | b).collect();
                let s = score(&px, &gold, &mask, &image, png_dir.as_deref());
                let pass = s.passes();
                let gated = name != "ray" && PIXEL_GATED.contains(&name);
                *by_scene.entry(name).or_insert(true) &= pass;
                table.push(format!(
                    "{image:<14} {:>7} {:>9.5} {:>4} {:>7.3} {:>5}  {}{}",
                    s.pixels,
                    s.close,
                    s.max,
                    s.mean,
                    s.flat,
                    if gated { "yes" } else { "no" },
                    if pass { "" } else { " (fails)" }
                ));
                if gated && !pass {
                    pixel_failures.push(format!("{image}: {s:?}"));
                }
            },
        );
        if !errors.is_empty() {
            eprintln!("{name}: wgpu errors {errors:?}");
        }
    }
    eprintln!(
        "inputs: {} values, {} bit-equal, {} within {VALUE_TOL:e}, {} MOUSEPOSITION values not compared",
        inputs.values,
        inputs.exact,
        inputs.values - inputs.differing,
        inputs.skipped
    );
    for k in &inputs.known {
        eprintln!("  {k}");
    }
    for f in &inputs.failures {
        eprintln!("  DIFFERS {f}");
    }
    eprintln!(
        "pixels ({}, at least {} of the pixels):",
        LIMITS.tolerance, LIMITS.min_close
    );
    for l in &table {
        eprintln!("  {l}");
    }
    let passing: Vec<&str> = by_scene
        .iter()
        .filter(|(_, &p)| p)
        .map(|(n, _)| *n)
        .collect();
    eprintln!("scenes that meet the rule: {passing:?}");
    assert!(
        inputs.failures.is_empty(),
        "{} inputs differ",
        inputs.failures.len()
    );
    assert!(pixel_failures.is_empty(), "{pixel_failures:?}");
}

#[test]
fn missing_inputs_skip_instead_of_panicking() {
    let nowhere = std::env::temp_dir().join("mds-mmertgold-nowhere");
    assert!(common::vkd3d_at(&nowhere.join("libvkd3d-shader.dylib")).is_none());
    assert!(common::corpus_at(&nowhere).is_none());
}
