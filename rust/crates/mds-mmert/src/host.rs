//! The host MMEffect runs in: the scene's objects, the frame's camera and light, and the order of
//! the draws of one frame, as the C++ application drives MMEffect. `tests/mmegold.rs` (against
//! the C++ images) and `mds-app` both draw through it.
//!
//! * The camera, light and world matrices are composed as `SetupFrameWorldTransform`
//!   (`src/render/debug_geometry.cpp`) and `OnBeginScene` do ([`scene`]); the orthographic
//!   projection is the one `SetupFrameWorldTransform` installs.
//! * The objects ([`Host::add`]): PMX and PMD models, posed every frame through `mds-skin` from
//!   the bone matrices and morph values of `mds-pose`, and accessories.
//! * A frame ([`Host::render`]): each offscreen turn's objects, then the scene: per object and
//!   material subset the object pass, then the edge pass, each with the technique
//!   `SasSelectTechnique` picks; a post effect draws the objects at its `ScriptExternal`; the
//!   animated textures tick at the end.
//! * What each subset of an object draws in a target follows the draw gate of `callbacks.cpp`
//!   (`MmeHandleDrawIndexedPrimitive`): a hidden subset nothing; a subset with an effect that
//!   loads and has a technique for it, that effect; every other subset is the host's own draw,
//!   the raw draw the C++ forwards. In an offscreen turn the target's rows and the mapping
//!   dialog's overrides ([`Frame::offscreen`]) say which effect, as [`crate::scene`] resolves.
//! * The host's own draws are `mds-render`'s standard MMD shading of those subsets (a mesh whose
//!   other subsets are left out), on the runtime's device, composited into the target before the
//!   effects draw; their depth goes into the target's depth stencil with MME's matrices, so an
//!   effect object behind them is hidden as in MMEffect, where both share one depth buffer.
//!
//! Not ported: the background picture and the projected ground shadow under the effect objects;
//! the host's edge pass of a subset whose effect has no edge technique (`mds-render` draws the
//! edge with the object). The models are skinned by `mds-render` for the host's draws and here
//! for the effects' and the depth's: `mds-render` takes no skinned vertices.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use mds_accessory::{Accessory, AccessoryState};
use mds_formats::pmd::Pmd;
use mds_formats::pmm::Pmm;
use mds_formats::pmx::Pmx;
use mds_math::Mat4;
use mds_mme::sas::SEM_OFFSCREEN;
use mds_pose::model::Model as Posed;
use mds_render::{AccessoryDraw, AccessoryMesh, Camera, Image, Light, Mesh, Pose, Renderer, Stage};
use mds_shader::vkd3d::Vkd3d;
use mds_skin::Skin;

use crate::bind::{look_at_lh, mul, perspective_lh, Mat, DRAW_EDGE, DRAW_OBJECT};
use crate::control::{Controls, Object};
use crate::emm::Assignment;
use crate::model::STRIDE;
use crate::scene::{turn_draw, Offscreen, TurnDraw, TurnObject, NO_OVERRIDES};
use crate::{DrawInput, Effect, Gpu, Model, Scene, Target};

/// MMEffect `SasMmdPass`: the draw modes `plan::select` takes.
const PASS_OBJECT: i32 = 0;
const PASS_EDGE: i32 = 3;

/// The multisampling of the host's own draws: WebGPU guarantees 4 for their formats.
const STANDARD_SAMPLES: u32 = 4;

/// An object file as the host loads it.
pub enum Source<'a> {
    Pmx(&'a Pmx),
    Pmd(&'a Pmd),
    Accessory(Accessory),
    /// A file that did not load: the object is listed and draws nothing.
    Missing,
}

/// One frame: the document's scene at `frame`, from `camera`, at `size` pixels.
pub struct Frame<'a> {
    pub pmm: &'a Pmm,
    /// The posed models (`PhysicsScene::scene.models`), found by slot.
    pub poses: &'a [Posed],
    pub camera: &'a Camera,
    /// `[r, g, b, x, y, z]`: the light color and the direction it travels.
    pub light: [f32; 6],
    pub frame: u32,
    /// `ELAPSEDTIME`.
    pub elapsed: f32,
    pub size: (u32, u32),
    /// One per object, in the order of [`Host::add`]: the PMM models, then its accessories.
    pub assignments: &'a [Assignment],
    /// The mapping dialog's overrides of the offscreen targets.
    pub offscreen: &'a Offscreen,
    /// The file of an effect path as an assignment stores it.
    pub resolve: &'a dyn Fn(&str) -> PathBuf,
}

/// A loaded effect and the object (an index into the objects) it is assigned to.
pub struct Loaded {
    pub file: PathBuf,
    pub stamp: Option<SystemTime>,
    pub effect: Effect,
    pub owner: usize,
}

/// An `OFFSCREENRENDERTARGET` of a loaded effect: a tab of the mapping dialog
/// (`DlgCollectOffscreenTabs`, `mme_dlg.cpp:268`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OffscreenTarget {
    /// The file of the effect that declares it, the key of [`Frame::offscreen`].
    pub file: PathBuf,
    pub name: String,
    /// Its `Description` annotation, the tab's caption (`DlgRefreshCaption`, `:423`).
    pub description: String,
    /// The object the effect is assigned to.
    pub owner: usize,
    /// Its `DefaultEffect` rows.
    pub rows: Vec<(String, String)>,
    /// Per object, whether it carries a post effect (`renderClass` not 0), in the last frame.
    pub carriers: Vec<bool>,
}

/// A model file, kept for the meshes that draw only some of its subsets.
enum File {
    Pmx(Box<Pmx>),
    Pmd(Box<Pmd>),
}

/// A model's pose inputs and its standard-shading meshes.
struct Shape {
    skin: Skin,
    mesh: Mesh,
    edge_scale: f32,
    bones: Vec<String>,
    morphs: Vec<String>,
    file: File,
    /// The texture files by the name the model stores, as read at load.
    // ponytail: the bytes stay in memory for the partial meshes; keep the reader instead if
    // models with large textures make this matter.
    textures: HashMap<String, Option<Vec<u8>>>,
    /// The meshes of some subsets, by the mask of the subsets drawn; dropped after a frame that
    /// does not draw them.
    partial: HashMap<Vec<bool>, Mesh>,
    used: HashSet<Vec<bool>>,
}

struct AccessoryShape {
    mesh: AccessoryMesh,
    source: Accessory,
    textures: HashMap<String, Option<Vec<u8>>>,
    partial: HashMap<Vec<bool>, AccessoryMesh>,
    used: HashSet<Vec<bool>>,
}

enum Kind {
    Model(Box<Shape>),
    Accessory(Box<AccessoryShape>),
    Missing,
}

struct Item {
    /// The file name with its extension, which `CONTROLOBJECT` and the turn rows match.
    name: String,
    /// The geometry the effects draw.
    model: Option<Model>,
    kind: Kind,
    /// `model` holds this frame's pose.
    skinned: bool,
}

/// `mds-render` on the runtime's device, drawing into a scratch texture that [`Blit`] composites.
struct Standard {
    renderer: Renderer,
    scratch: Option<wgpu::Texture>,
}

pub struct Host {
    /// The back buffer `ViewportRatio` targets are sized against.
    pub backbuffer: (u32, u32),
    objects: Vec<Item>,
    /// The assigned effects, then those the offscreen turns load.
    effects: Vec<Loaded>,
    standard: Option<Standard>,
    blit: Option<Blit>,
    depth: Option<Depth>,
    target: Option<Target>,
    carriers: Vec<bool>,
}

fn file_name(path: &str) -> &str {
    path.rsplit(['\\', '/']).next().unwrap_or(path)
}

fn stamp(path: &Path) -> Option<SystemTime> {
    std::fs::metadata(path).and_then(|m| m.modified()).ok()
}

/// The frame's camera, light, and clocks as MMEffect's `OnBeginScene` sees them: the device
/// world is the frame world of `SetupFrameWorldTransform` (the target to the origin, then yaw,
/// pitch, roll), the device view its fixed look along +z from the camera distance, and the
/// projection `RefreshMainWindowViewport`'s, or under the orthographic camera the matrix
/// `SetupFrameWorldTransform` writes (`debug_geometry.cpp:550-556`, the aspect of the render size,
/// `ui_viewport_refresh.cpp:129`). MME's `VIEW` is the world times the view, and an object's
/// `WORLD` its device world (its own world times the frame world) times the inverse of the frame
/// world. The light is a model's: its diffuse is 0, the color is the ambient and the specular
/// (`command_panel_toggles.cpp:414`, `material_bind.cpp:1906`). Also returns the frame world and
/// its inverse; `None` for a camera with no inverse.
pub fn scene(
    camera: &Camera,
    light: [f32; 6],
    frame: u32,
    elapsed: f32,
    (w, h): (u32, u32),
) -> Option<(Scene, Mat, Mat)> {
    let c = camera;
    let [pitch, yaw, roll] = c.rotation;
    let t = Mat4::translation(-c.target[0], -c.target[1], -c.target[2]);
    let r = Mat4::multiply(&Mat4::rotation_y(yaw), &Mat4::rotation_x(pitch));
    let r = Mat4::multiply(&r, &Mat4::rotation_z(roll));
    let frame_world = Mat4::multiply(&t, &r);
    let inverse = frame_world.inverse()?.0 .0;
    let eye = [0.0, 0.0, c.distance];
    let look = look_at_lh(eye, [0.0, 0.0, c.distance + 80.0], [0.0, 1.0, 0.0]);
    let aspect = w as f32 / h as f32;
    let [r, g, b, x, y, z] = light;
    let mut s = Scene::default_view(w, h);
    s.world = mul(&frame_world.0, &inverse);
    s.view = mul(&frame_world.0, &look);
    s.projection = if c.orthographic {
        let x = -2.0 / c.distance;
        let mut p = [0.0; 16];
        p[0] = x;
        p[5] = aspect * x;
        p[10] = 0.0013;
        p[15] = 1.0;
        p
    } else {
        let fov = (f64::from(c.fov_deg) * std::f64::consts::PI / 180.0) as f32;
        perspective_lh(fov, aspect, 1.0, 100000.0)
    };
    s.light_direction = [x, y, z];
    s.light_ambient = [r, g, b];
    s.light_diffuse = [0.0; 3];
    s.light_specular = [r, g, b];
    s.time = frame as f32 / 30.0;
    s.elapsed = elapsed;
    Some((s, frame_world.0, inverse))
}

/// The scene of an accessory: its own world in the frame world, and the light of the accessory
/// pass, diffuse 1 and the ambient 0.3 darker (`SetAccessoryLight`, `accessory.cpp:210`, as
/// `material_bind.cpp:1919-1940` reads it back).
fn accessory_scene(scene: &Scene, world: &Mat, frame_world: &Mat, inverse: &Mat) -> Scene {
    Scene {
        world: mul(&mul(world, frame_world), inverse),
        light_diffuse: [1.0; 3],
        light_ambient: scene.light_ambient.map(|c| c - 0.3),
        ..scene.clone()
    }
}

/// `ExpGetPmdBoneWorldMat`: the bone's position moved by its world matrix.
fn bone_world(b: &mds_pose::model::Bone) -> Mat {
    let [x, y, z] = b.position;
    Mat4::multiply(&Mat4::translation(x, y, z), &b.mat_init).0
}

/// What one frame of [`Host::render`] works from besides the frame itself.
struct Drawn<'a> {
    scenes: Vec<Scene>,
    poses: Vec<Option<Pose>>,
    accessories: Vec<Option<(AccessoryState, Mat)>>,
    frame_world: Mat,
    self_shadow: bool,
    f: &'a Frame<'a>,
}

/// What one object draws into one target: the subsets the host draws, and each effect with the
/// subsets it draws.
#[derive(Clone)]
struct Plan {
    o: usize,
    host: Vec<bool>,
    effects: Vec<(usize, Vec<bool>)>,
}

impl Host {
    pub fn new(backbuffer: (u32, u32)) -> Host {
        Host {
            backbuffer,
            objects: Vec::new(),
            effects: Vec::new(),
            standard: None,
            blit: None,
            depth: None,
            target: None,
            carriers: Vec::new(),
        }
    }

    /// Adds the next object (the PMM models in order, then the accessories) named `name` (its
    /// stored path). `read` returns the bytes of a texture by the name the file stores, relative
    /// to the file's folder. An object that does not load is still added, and draws nothing.
    pub fn add(
        &mut self,
        gpu: &Gpu,
        name: &str,
        source: Source,
        edge_scale: f32,
        read: impl FnMut(&str) -> Option<Vec<u8>>,
    ) -> Result<(), String> {
        let (r, model, kind) = match load(gpu, source, edge_scale, read) {
            Ok((model, kind)) => (Ok(()), model, kind),
            Err(e) => (Err(format!("{name}: {e}")), None, Kind::Missing),
        };
        self.objects.push(Item {
            name: file_name(name).to_string(),
            model,
            kind,
            skinned: false,
        });
        r
    }

    /// The loaded effects.
    pub fn effects(&self) -> &[Loaded] {
        &self.effects
    }

    /// The offscreen targets of the loaded effects, in the order their turns run.
    pub fn offscreen_targets(&self) -> Vec<OffscreenTarget> {
        let mut out = Vec::new();
        for l in &self.effects {
            let sas = &l.effect.sas;
            for r in sas.resources.iter().filter(|r| r.semantic == SEM_OFFSCREEN) {
                let description = sas
                    .fx
                    .params
                    .get(r.param)
                    .and_then(|p| p.annotation("Description"))
                    .and_then(|a| a.get_string())
                    .unwrap_or("");
                out.push(OffscreenTarget {
                    file: l.file.clone(),
                    name: r.name.clone(),
                    description: description.to_string(),
                    owner: l.owner,
                    rows: r.default_effect.clone(),
                    carriers: self.carriers.clone(),
                });
            }
        }
        out
    }

    /// The back buffer of the last frame.
    pub fn target(&self) -> Option<&Target> {
        self.target.as_ref()
    }

    /// Drops the effects whose file changed on disk since they loaded: those load again at the
    /// next frame. Returns how many.
    pub fn reload_changed(&mut self) -> usize {
        let before = self.effects.len();
        self.effects.retain(|l| stamp(&l.file) == l.stamp);
        before - self.effects.len()
    }

    /// The last frame into `dst`, a texture of the target's size with `RENDER_ATTACHMENT` usage
    /// on the runtime's device, opaque.
    pub fn output_into(&mut self, gpu: &Gpu, dst: &wgpu::Texture) -> Result<(), String> {
        let target = self.target.as_ref().ok_or("no frame drawn")?;
        let src = target.color.create_view(&Default::default());
        let blit = self.blit.get_or_insert_with(|| Blit::new(&gpu.device));
        blit.run(gpu, &src, dst, false);
        Ok(())
    }

    /// Index of the loaded effect `file`, loading it for `owner`; `None` when it does not load
    /// (logged).
    fn effect_for(
        &mut self,
        gpu: &Gpu,
        vk: &Vkd3d,
        file: &Path,
        owner: usize,
        log: &mut Vec<String>,
    ) -> Option<usize> {
        if let Some(i) = self.effects.iter().position(|l| l.file == file) {
            return Some(i);
        }
        // The effect's includes and textures may sit anywhere above it (`..\ray.conf`), so the
        // root it resolves below is the file system's.
        let root = file.ancestors().last().unwrap_or(Path::new("/"));
        log.push(format!("Loading effect file: {}", file.display()));
        match Effect::load(gpu, vk, file, root, self.backbuffer) {
            Ok(effect) => {
                if effect.sas.has_errors {
                    log.push(effect.sas.log.clone());
                }
                self.effects.push(Loaded {
                    file: file.to_path_buf(),
                    stamp: stamp(file),
                    effect,
                    owner,
                });
                Some(self.effects.len() - 1)
            }
            Err(e) => {
                log.push(format!("{}: {e}", file.display()));
                None
            }
        }
    }

    /// The poses of the frame, one per object, for the host's draws; the effects' buffers take
    /// them on demand ([`Host::skin`]).
    fn poses(&mut self, f: &Frame) -> Vec<Option<Pose>> {
        let mut poses = Vec::with_capacity(self.objects.len());
        for (o, item) in self.objects.iter_mut().enumerate() {
            item.skinned = false;
            if let Kind::Model(shape) = &mut item.kind {
                shape.used.clear();
            } else if let Kind::Accessory(shape) = &mut item.kind {
                shape.used.clear();
            }
            let posed = f
                .pmm
                .models
                .get(o)
                .and_then(|m| f.poses.iter().find(|p| p.slot == m.slot));
            let model = matches!(item.kind, Kind::Model(_)) && item.model.is_some();
            poses.push(posed.filter(|_| model).map(mds_render::scene::pose_of));
        }
        poses
    }

    /// The pose of object `o` in its buffers, the vertex and material values of `mds-skin`, once
    /// a frame and only for the draws that read them.
    fn skin(&mut self, gpu: &Gpu, o: usize, drawn: &Drawn) {
        let item = &mut self.objects[o];
        if std::mem::replace(&mut item.skinned, true) {
            return;
        }
        let (Kind::Model(shape), Some(model), Some(pose)) =
            (&mut item.kind, &mut item.model, drawn.poses[o].as_ref())
        else {
            return;
        };
        // A pose shorter or longer than the model's tables is padded or cut, as `mds-render`
        // pads it.
        let skin = &mut shape.skin;
        let mut weights = vec![0.0; skin.morph_count()];
        let mut bones = vec![Mat4::IDENTITY; skin.bone_count()];
        for (w, &v) in weights.iter_mut().zip(&pose.morphs) {
            *w = v;
        }
        for (b, &m) in bones.iter_mut().zip(&pose.skin) {
            *b = Mat4(m);
        }
        skin.apply_morphs(&weights);
        skin.update(
            &weights,
            &bones,
            &mds_skin::View {
                world: Mat4(drawn.frame_world),
                camera_position: drawn.f.camera.target,
                camera_fov: drawn.f.camera.fov_deg,
                edge_scale: shape.edge_scale,
                self_shadow: drawn.self_shadow,
            },
        );
        model.update(&gpu.queue, skin);
    }

    /// The scene's objects as the host exports them: the models by draw order (1-based), with
    /// their bones and morphs from the pose, then the accessories.
    fn controls(&self, f: &Frame, accessories: &[Option<(AccessoryState, Mat)>]) -> Controls {
        let mut objects = Vec::new();
        for (i, (m, item)) in f.pmm.models.iter().zip(&self.objects).enumerate() {
            let mut o = Object::model(&item.name, i as i32 + 1);
            let posed = f.poses.iter().find(|p| p.slot == m.slot);
            if let (Kind::Model(shape), Some(posed)) = (&item.kind, posed) {
                o.bones = shape
                    .bones
                    .iter()
                    .zip(&posed.bones)
                    .map(|(n, p)| (n.clone(), bone_world(p)))
                    .collect();
                o.morphs = shape
                    .morphs
                    .iter()
                    .zip(&posed.morphs)
                    .map(|(n, p)| (n.clone(), p.value))
                    .collect();
            }
            objects.push(o);
        }
        let items = self.objects.iter().skip(f.pmm.models.len());
        for ((a, item), state) in f.pmm.accessories.iter().zip(items).zip(accessories) {
            let mut o = Object::model(&item.name, i32::from(a.order) + 1);
            o.model = false;
            match state {
                Some((state, world)) => {
                    o.shown = state.visible;
                    o.world = *world;
                    let [x, y, z] = state.position;
                    let [rx, ry, rz] = state.rotation;
                    o.accessory = [x, y, z, rx, ry, rz, state.scale, state.opacity];
                }
                None => o.shown = false,
            }
            objects.push(o);
        }
        Controls { objects }
    }

    /// Renders `f` into the back buffer ([`Host::target`]) and returns why draws were skipped.
    /// Effects that load are logged into `log`.
    pub fn render(
        &mut self,
        gpu: &Gpu,
        vk: &Vkd3d,
        f: &Frame,
        log: &mut Vec<String>,
    ) -> Vec<String> {
        let Some((scene, frame_world, inverse)) =
            scene(f.camera, f.light, f.frame, f.elapsed, f.size)
        else {
            return vec!["camera matrix".into()];
        };
        if self
            .target
            .as_ref()
            .is_none_or(|t| (t.color.width(), t.color.height()) != f.size)
        {
            self.target = Some(Target::new(gpu, f.size));
        }
        let n_models = f.pmm.models.len();
        let poses = self.poses(f);
        let accessories: Vec<_> = f
            .pmm
            .accessories
            .iter()
            .map(|a| mds_render::scene::accessory_at(a, f.frame, f.poses))
            .collect();
        let controls = self.controls(f, &accessories);
        let default = Assignment::default();
        let assignment = |o: usize| f.assignments.get(o).unwrap_or(&default);

        // The assigned effects, loaded: (object, effect) per distinct file of each object.
        let mut assigned: Vec<(usize, usize)> = Vec::new();
        for o in 0..self.objects.len() {
            let a = assignment(o);
            let files = std::iter::once(&a.effect).chain(a.subsets.values());
            for p in files.filter(|p| !p.is_empty()) {
                let file = (f.resolve)(p);
                if let Some(e) = self.effect_for(gpu, vk, &file, o, log) {
                    if !assigned.contains(&(o, e)) {
                        assigned.push((o, e));
                    }
                }
            }
        }
        let post = |effects: &[Loaded], e: usize| effects[e].effect.sas.script_class == 1;
        // A post effect's object carries it and draws as no object.
        let carriers: Vec<bool> = (0..self.objects.len())
            .map(|o| {
                assigned
                    .iter()
                    .any(|&(oo, e)| oo == o && post(&self.effects, e))
            })
            .collect();
        let posts: Vec<(usize, usize)> = assigned
            .iter()
            .copied()
            .filter(|&(o, e)| assignment(o).shown && post(&self.effects, e))
            .collect();
        let scenes: Vec<Scene> = (0..self.objects.len())
            .map(
                |o| match o.checked_sub(n_models).and_then(|i| accessories.get(i)) {
                    Some(Some((_, w))) => accessory_scene(&scene, w, &frame_world, &inverse),
                    _ => scene.clone(),
                },
            )
            .collect();
        let drawn = Drawn {
            scenes,
            poses,
            accessories,
            frame_world,
            self_shadow: mds_render::scene::stage_at(f.pmm, f.frame)
                .self_shadow
                .is_some_and(|s| s.shades()),
            f,
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

        // The offscreen turns: each target of each loaded effect, every object drawn as its rows
        // and the dialog's overrides say.
        for c in 0..self.effects.len() {
            let owner = self.effects[c].owner;
            let targets: Vec<usize> = (0..self.effects[c].effect.sas.resources.len())
                .filter(|&r| self.effects[c].effect.sas.resources[r].semantic == SEM_OFFSCREEN)
                .collect();
            for r in targets {
                let Some(turn) = self.effects[c].effect.begin_offscreen(gpu, r) else {
                    continue;
                };
                let key = (
                    self.effects[c].file.clone(),
                    self.effects[c].effect.sas.resources[r].name.clone(),
                );
                let overrides = f.offscreen.get(&key);
                let mut plans = Vec::new();
                for (o, &carrier) in carriers.iter().enumerate() {
                    let Some(model) = &self.objects[o].model else {
                        continue;
                    };
                    let obj = TurnObject {
                        name: &self.objects[o].name,
                        owner: owner == o,
                        render_class: i32::from(carrier),
                        main: assignment(o),
                        overrides: overrides.and_then(|m| m.get(&o)).unwrap_or(&NO_OVERRIDES),
                        resolve: f.resolve,
                    };
                    let res = &self.effects[c].effect.sas.resources[r];
                    let draws = (0..model.materials.len())
                        .map(|s| turn_draw(res, &obj, Some(s as i32)))
                        .collect();
                    plans.push(self.plan(gpu, vk, o, draws, log));
                }
                skipped.extend(self.draw_plans(gpu, &turn, &plans, &drawn, &base, Some(owner)));
            }
        }

        // The scene: a post effect draws the objects at its ScriptExternal; without one the
        // objects draw into the back buffer after the host's clear.
        let target = self.target.take().expect("target created above");
        target.clear_turn(gpu, Some(scene.background), 1.0, true);
        let mut plans = Vec::new();
        for o in (0..self.objects.len()).filter(|&o| !carriers[o]) {
            let Some(model) = &self.objects[o].model else {
                continue;
            };
            let a = assignment(o);
            let draws = (0..model.materials.len() as i32)
                .map(|s| {
                    if !a.subset_shown(s) {
                        return TurnDraw::Hide;
                    }
                    let p = a.subsets.get(&s).filter(|p| !p.is_empty());
                    match p.unwrap_or(&a.effect) {
                        p if p.is_empty() => TurnDraw::Host,
                        p => TurnDraw::Effect((f.resolve)(p)),
                    }
                })
                .collect();
            plans.push(self.plan(gpu, vk, o, draws, log));
        }
        if posts.is_empty() {
            skipped.extend(self.draw_plans(gpu, &target, &plans, &drawn, &base, None));
        }
        for (owner, p) in posts {
            // The post effect leaves the list while it runs, so that the scene draw can borrow the
            // object effects.
            let mut post = self.effects.remove(p);
            let mut plans = plans.clone();
            for (e, _) in plans.iter_mut().flat_map(|plan| &mut plan.effects) {
                if *e > p {
                    *e -= 1;
                }
            }
            let input = DrawInput {
                scene: &drawn.scenes[owner],
                owner: Some(owner),
                ..base
            };
            let mut inner = Vec::new();
            let r = post
                .effect
                .frame_with_scene(gpu, &target, &input, &mut |_, t| {
                    inner.extend(self.draw_plans(gpu, t, &plans, &drawn, &base, None));
                });
            self.effects.insert(p, post);
            skipped.extend(r.skipped);
            skipped.extend(inner);
        }
        for l in &mut self.effects {
            l.effect.tick_animes(gpu, scene.time);
        }
        for item in &mut self.objects {
            if let Kind::Model(shape) = &mut item.kind {
                let Shape { partial, used, .. } = &mut **shape;
                partial.retain(|mask, _| used.contains(mask));
            } else if let Kind::Accessory(shape) = &mut item.kind {
                shape.partial.retain(|mask, _| shape.used.contains(mask));
            }
        }
        self.target = Some(target);
        self.carriers = carriers;
        skipped
    }

    /// The plan of object `o` from what each of its subsets draws: a subset whose effect does
    /// not load, or has no object technique for it, is the host's (the raw draw the C++ forwards
    /// for a null binding or technique, `callbacks.cpp:236-281`).
    fn plan(
        &mut self,
        gpu: &Gpu,
        vk: &Vkd3d,
        o: usize,
        draws: Vec<TurnDraw>,
        log: &mut Vec<String>,
    ) -> Plan {
        let n = draws.len();
        let mut plan = Plan {
            o,
            host: vec![false; n],
            effects: Vec::new(),
        };
        for (s, d) in draws.into_iter().enumerate() {
            match d {
                TurnDraw::Hide => {}
                TurnDraw::Host => plan.host[s] = true,
                TurnDraw::Effect(file) => match self.effect_for(gpu, vk, &file, o, log) {
                    Some(e) if self.has_technique(e, o, s) => {
                        match plan.effects.iter_mut().find(|(x, _)| *x == e) {
                            Some((_, mask)) => mask[s] = true,
                            None => {
                                let mut mask = vec![false; n];
                                mask[s] = true;
                                plan.effects.push((e, mask));
                            }
                        }
                    }
                    _ => plan.host[s] = true,
                },
            }
        }
        plan
    }

    /// Whether effect `e` has an object technique for subset `s` of object `o`.
    fn has_technique(&self, e: usize, o: usize, s: usize) -> bool {
        let Some(m) = self.objects[o]
            .model
            .as_ref()
            .and_then(|m| m.materials.get(s))
        else {
            return false;
        };
        let sas = &self.effects[e].effect.sas;
        let tex = (m.has_texture, m.sphere_mode > 0, m.toon);
        mds_mme::plan::select(sas, PASS_OBJECT, s as i32, tex.0, tex.1, tex.2)
            .0
            .is_some()
    }

    /// The draws of `plans` into `target`: the host's subsets, their depth when an effect draws
    /// after them, then each effect's subsets. `turn` is the owner of the offscreen target being
    /// drawn, whose size is the effects' `VIEWPORTPIXELSIZE`.
    fn draw_plans(
        &mut self,
        gpu: &Gpu,
        target: &Target,
        plans: &[Plan],
        drawn: &Drawn,
        base: &DrawInput,
        turn: Option<usize>,
    ) -> Vec<String> {
        let mut skipped = Vec::new();
        let host: Vec<(usize, &[bool])> = plans
            .iter()
            .filter(|p| p.host.contains(&true))
            .map(|p| (p.o, &p.host[..]))
            .collect();
        if let Err(e) = self.draw_standard(gpu, target, &host, drawn) {
            skipped.push(e);
        }
        if !host.is_empty() && plans.iter().any(|p| !p.effects.is_empty()) {
            self.draw_depth(gpu, target, &host, drawn);
        }
        let viewport = (target.color.width(), target.color.height());
        for p in plans {
            if !p.effects.is_empty() {
                self.skin(gpu, p.o, drawn);
            }
            let scene = Scene {
                viewport: if turn.is_some() {
                    viewport
                } else {
                    drawn.scenes[p.o].viewport
                },
                ..drawn.scenes[p.o].clone()
            };
            for (e, mask) in &p.effects {
                let input = DrawInput {
                    scene: &scene,
                    owner: Some(p.o),
                    offscreen_owner: turn,
                    ..*base
                };
                let effect = &mut self.effects[*e].effect;
                let item = &self.objects[p.o];
                skipped.extend(draw_object(gpu, effect, item, &|s| mask[s], target, &input));
            }
        }
        skipped
    }

    /// The host's own draw of the subsets `list` gives (object, subsets) into `target`:
    /// `mds-render` on a transparent scratch texture, composited over the target, so a target
    /// the effect cleared keeps its color. The projection is the frame's in every target, as the
    /// C++ sets it once a frame (`frame_scene.cpp:338`) and a turn changes only the viewport
    /// (`pass_planner.cpp:1747`).
    fn draw_standard(
        &mut self,
        gpu: &Gpu,
        target: &Target,
        list: &[(usize, &[bool])],
        drawn: &Drawn,
    ) -> Result<(), String> {
        if list.is_empty() {
            return Ok(());
        }
        for &(o, mask) in list {
            if let Kind::Model(shape) = &mut self.objects[o].kind {
                if !mask.contains(&false) {
                    continue;
                }
                if !shape.partial.contains_key(mask) {
                    let mesh = partial_mesh(shape, mask)?;
                    shape.partial.insert(mask.to_vec(), mesh);
                }
                shape.used.insert(mask.to_vec());
            } else if let Kind::Accessory(shape) = &mut self.objects[o].kind {
                if !mask.contains(&false) {
                    continue;
                }
                shape.partial.entry(mask.to_vec()).or_insert_with(|| {
                    let mut acc = shape.source.clone();
                    for (face, &material) in acc.face_material.iter().enumerate() {
                        if !mask.get(material as usize).copied().unwrap_or(false) {
                            acc.indices[face * 3..face * 3 + 3].fill(0);
                        }
                    }
                    let mut mesh = AccessoryMesh::new(acc);
                    mesh.load_textures(|n| shape.textures.get(n).cloned().flatten());
                    mesh
                });
                shape.used.insert(mask.to_vec());
            }
        }
        let f = drawn.f;
        let n_models = f.pmm.models.len();
        let mut models = Vec::new();
        let mut accessories = Vec::new();
        for &(o, mask) in list {
            match &self.objects[o].kind {
                Kind::Model(shape) => {
                    let mesh = shape.partial.get(mask).unwrap_or(&shape.mesh);
                    models.push((mesh, drawn.poses[o].as_ref()));
                }
                Kind::Accessory(shape) => {
                    let mesh = shape.partial.get(mask).unwrap_or(&shape.mesh);
                    if let Some(Some((state, world))) = drawn.accessories.get(o - n_models) {
                        accessories.push(AccessoryDraw {
                            mesh,
                            state,
                            world: *world,
                        });
                    }
                }
                Kind::Missing => {}
            }
        }
        let (w, h) = (target.color.width(), target.color.height());
        let [r, g, b, x, y, z] = f.light;
        let frame = mds_render::Frame {
            width: w,
            height: h,
            view: f.camera.view(f.size.0, f.size.1),
            light: Light {
                color: [r, g, b],
                direction: [x, y, z],
            },
            background: [0; 4],
            toon: true,
            models: &models,
            samples: &[[0.0, 0.0]],
            pixel_offset: mds_render::PIXEL_OFFSET_D3D9,
        };
        let stage = Stage {
            accessories: &accessories,
            ..mds_render::scene::stage_at(f.pmm, f.frame)
        };
        let standard = match &mut self.standard {
            Some(s) => s,
            None => self.standard.insert(Standard {
                renderer: Renderer::new(&gpu.device, &gpu.queue)?,
                scratch: None,
            }),
        };
        if standard
            .scratch
            .as_ref()
            .is_none_or(|t| (t.width(), t.height()) != (w, h))
        {
            standard.scratch = Some(gpu.device.create_texture(&wgpu::TextureDescriptor {
                label: Some("host draw"),
                size: wgpu::Extent3d {
                    width: w,
                    height: h,
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: wgpu::TextureFormat::Rgba8Unorm,
                usage: wgpu::TextureUsages::RENDER_ATTACHMENT
                    | wgpu::TextureUsages::TEXTURE_BINDING,
                view_formats: &[],
            }));
        }
        let view = standard
            .scratch
            .as_ref()
            .expect("scratch created above")
            .create_view(&Default::default());
        standard
            .renderer
            .render_into_with(&view, &frame, &stage, STANDARD_SAMPLES)?;
        let blit = self.blit.get_or_insert_with(|| Blit::new(&gpu.device));
        blit.run(gpu, &view, &target.color, true);
        Ok(())
    }

    /// The depth of the host's subsets `list` gives into `target`'s depth stencil, from their
    /// posed vertices and the `WORLDVIEWPROJECTION` an effect gets.
    fn draw_depth(&mut self, gpu: &Gpu, target: &Target, list: &[(usize, &[bool])], drawn: &Drawn) {
        let n_models = drawn.f.pmm.models.len();
        for &(o, _) in list {
            self.skin(gpu, o, drawn);
        }
        let format = target.depth.format();
        let depth = self.depth.get_or_insert_with(|| Depth::new(&gpu.device));
        let mut draws = Vec::new();
        for &(o, mask) in list {
            let Some(model) = &self.objects[o].model else {
                continue;
            };
            let hidden = o
                .checked_sub(n_models)
                .is_some_and(|a| !matches!(&drawn.accessories[a], Some((s, _)) if s.visible));
            if hidden {
                continue;
            }
            let s = &drawn.scenes[o];
            let wvp = mul(&s.world, &mul(&s.view, &s.projection));
            let bytes: Vec<u8> = wvp.iter().flat_map(|v| v.to_le_bytes()).collect();
            let uniform = crate::model::buffer(&gpu.device, wgpu::BufferUsages::UNIFORM, &bytes);
            let group = gpu.device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("host depth"),
                layout: &depth.layout,
                entries: &[wgpu::BindGroupEntry {
                    binding: 0,
                    resource: uniform.as_entire_binding(),
                }],
            });
            let opacity = o
                .checked_sub(n_models)
                .and_then(|a| drawn.accessories.get(a))
                .and_then(|a| a.as_ref())
                .map_or(1.0, |(s, _)| s.opacity);
            draws.push((model, mask, group, opacity));
        }
        for cull in [true, false] {
            depth.pipeline(&gpu.device, format, cull);
        }
        let view = target.depth.create_view(&Default::default());
        let mut enc = gpu.device.create_command_encoder(&Default::default());
        {
            let mut rp = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("host depth"),
                color_attachments: &[],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &view,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Load,
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: format.has_stencil_aspect().then_some(wgpu::Operations {
                        load: wgpu::LoadOp::Load,
                        store: wgpu::StoreOp::Store,
                    }),
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            for (model, mask, group, opacity) in &draws {
                rp.set_bind_group(0, group, &[]);
                rp.set_vertex_buffer(0, model.vertices.slice(..));
                rp.set_index_buffer(model.indices.slice(..), wgpu::IndexFormat::Uint32);
                for (m, _) in model.materials.iter().zip(*mask).filter(|(_, &on)| on) {
                    if m.diffuse[3] * opacity <= 0.0 {
                        continue;
                    }
                    let cull = !m.double_sided;
                    rp.set_pipeline(&depth.pipelines[&(format, cull)]);
                    rp.draw_indexed(m.start..m.start + m.count, 0, 0..1);
                }
            }
        }
        gpu.queue.submit([enc.finish()]);
    }
}

/// The mesh of `shape` that draws only the subsets of `mask`: the faces of the others are made
/// degenerate, so the material indices and the material morphs stay as they are.
fn partial_mesh(shape: &Shape, mask: &[bool]) -> Result<Mesh, String> {
    let on = |k: usize| mask.get(k).copied().unwrap_or(false);
    let mut mesh = match &shape.file {
        File::Pmx(pmx) => {
            let mut pmx = (**pmx).clone();
            let mut start = 0usize;
            for (k, m) in pmx.materials.iter().enumerate() {
                let end = (start + m.face_vertex_count.max(0) as usize).min(pmx.indices.len());
                if !on(k) {
                    pmx.indices[start..end].fill(0);
                }
                start = end;
            }
            Mesh::from_pmx(&pmx)?
        }
        File::Pmd(pmd) => {
            let mut pmd = (**pmd).clone();
            let mut start = 0usize;
            for (k, m) in pmd.materials.iter().enumerate() {
                let end = (start + m.face_vertex_count as usize).min(pmd.indices.len());
                if !on(k) {
                    pmd.indices[start..end].fill(0);
                }
                start = end;
            }
            Mesh::from_pmd(&pmd)?
        }
    };
    mesh.load_textures(|n| shape.textures.get(n).cloned().flatten());
    mesh.set_edge_scale(shape.edge_scale);
    Ok(mesh)
}

fn load(
    gpu: &Gpu,
    source: Source,
    edge_scale: f32,
    mut read: impl FnMut(&str) -> Option<Vec<u8>>,
) -> Result<(Option<Model>, Kind), String> {
    let mut textures: HashMap<String, Option<Vec<u8>>> = HashMap::new();
    let mut fetch = |n: &str| {
        textures
            .entry(n.to_string())
            .or_insert_with(|| read(n))
            .clone()
    };
    let (mut model, skin, mut mesh, bones, morphs, file) = match source {
        Source::Pmx(pmx) => (
            Model::from_pmx(&gpu.device, pmx)?,
            Skin::from_pmx(pmx)?,
            Mesh::from_pmx(pmx)?,
            pmx.bones.iter().map(|b| b.name.text.clone()).collect(),
            pmx.morphs.iter().map(|m| m.name.text.clone()).collect(),
            File::Pmx(Box::new(pmx.clone())),
        ),
        Source::Pmd(pmd) => (
            Model::from_pmd(&gpu.device, pmd)?,
            Skin::from_pmd(pmd)?,
            Mesh::from_pmd(pmd)?,
            pmd.bones.iter().map(|b| b.name.text.clone()).collect(),
            pmd.morphs.iter().map(|m| m.name.text.clone()).collect(),
            File::Pmd(Box::new(pmd.clone())),
        ),
        Source::Accessory(acc) => {
            let mut model = Model::from_accessory(&gpu.device, &acc)?;
            let mut mesh = AccessoryMesh::new(acc.clone());
            mesh.load_textures(&mut fetch);
            let loaded = loaded_files(&model, fetch);
            model.loaded(|n| loaded.contains(n));
            return Ok((
                Some(model),
                Kind::Accessory(Box::new(AccessoryShape {
                    mesh,
                    source: acc,
                    textures,
                    partial: HashMap::new(),
                    used: HashSet::new(),
                })),
            ));
        }
        Source::Missing => return Ok((None, Kind::Missing)),
    };
    mesh.load_textures(&mut fetch);
    mesh.set_edge_scale(edge_scale);
    let loaded = loaded_files(&model, fetch);
    model.loaded(|n| loaded.contains(n));
    let shape = Shape {
        skin,
        mesh,
        edge_scale,
        bones,
        morphs,
        file,
        textures,
        partial: HashMap::new(),
        used: HashSet::new(),
    };
    Ok((Some(model), Kind::Model(Box::new(shape))))
}

/// The texture and sphere files of `model` that read and decode.
fn loaded_files(model: &Model, mut fetch: impl FnMut(&str) -> Option<Vec<u8>>) -> HashSet<String> {
    let names = model
        .materials
        .iter()
        .flat_map(|m| [&m.texture, &m.sphere])
        .flatten();
    let mut loaded = HashSet::new();
    for n in names {
        if !loaded.contains(n) && fetch(n).is_some_and(|b| Image::decode(&b).is_ok()) {
            loaded.insert(n.clone());
        }
    }
    loaded
}

/// The object and edge passes of `item` with `effect` into `target`, over the subsets `subset`
/// admits.
fn draw_object(
    gpu: &Gpu,
    effect: &mut Effect,
    item: &Item,
    subset: &dyn Fn(usize) -> bool,
    target: &Target,
    input: &DrawInput,
) -> Vec<String> {
    let mut skipped = Vec::new();
    let Some(model) = &item.model else {
        return skipped;
    };
    for (mode, draw_type) in [(PASS_OBJECT, DRAW_OBJECT), (PASS_EDGE, DRAW_EDGE)] {
        for (s, m) in model.materials.iter().enumerate() {
            if !subset(s) || (mode == PASS_EDGE && !m.edge) {
                continue;
            }
            let input = DrawInput {
                geometry: Some((model, s)),
                draw_type,
                ..*input
            };
            // Every host draw binds the effect's parameters, whether a technique takes it or not
            // (MmeApplyModelRenderSnapshot).
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
            let Some(tech) = effect.sas.techniques.iter().position(|t| t.fx == h) else {
                continue;
            };
            let r = effect.draw_technique(gpu, target, &input, tech);
            skipped.extend(r.skipped);
        }
    }
    skipped
}

/// The depth-only draw of the host's subsets: position alone, `LESSEQUAL` as Direct3D 9's
/// default `D3DRS_ZFUNC`, the back faces culled unless the material is double sided.
// ponytail: the faces only, without the edge hull, and texture alpha does not cut the depth;
// add them when a scene shows the difference.
struct Depth {
    shader: wgpu::ShaderModule,
    layout: wgpu::BindGroupLayout,
    pipeline_layout: wgpu::PipelineLayout,
    pipelines: HashMap<(wgpu::TextureFormat, bool), wgpu::RenderPipeline>,
}

/// The matrix is uploaded as Direct3D's rows, which WGSL reads as columns: `m * v` is D3D's
/// `mul(v, m)`.
const DEPTH: &str = "
@group(0) @binding(0) var<uniform> wvp: mat4x4<f32>;
@vertex fn vs(@location(0) p: vec3<f32>) -> @builtin(position) vec4<f32> {
    return wvp * vec4<f32>(p, 1.0);
}
";

impl Depth {
    fn new(device: &wgpu::Device) -> Depth {
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("host depth"),
            source: wgpu::ShaderSource::Wgsl(DEPTH.into()),
        });
        let layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("host depth"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::VERTEX,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            }],
        });
        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("host depth"),
            bind_group_layouts: &[Some(&layout)],
            immediate_size: 0,
        });
        Depth {
            shader,
            layout,
            pipeline_layout,
            pipelines: HashMap::new(),
        }
    }

    fn pipeline(&mut self, device: &wgpu::Device, format: wgpu::TextureFormat, cull: bool) {
        let (shader, layout) = (&self.shader, &self.pipeline_layout);
        self.pipelines.entry((format, cull)).or_insert_with(|| {
            device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                label: Some("host depth"),
                layout: Some(layout),
                vertex: wgpu::VertexState {
                    module: shader,
                    entry_point: Some("vs"),
                    compilation_options: Default::default(),
                    buffers: &[Some(wgpu::VertexBufferLayout {
                        array_stride: STRIDE,
                        step_mode: wgpu::VertexStepMode::Vertex,
                        attributes: &[wgpu::VertexAttribute {
                            format: wgpu::VertexFormat::Float32x3,
                            offset: 0,
                            shader_location: 0,
                        }],
                    })],
                },
                primitive: wgpu::PrimitiveState {
                    front_face: wgpu::FrontFace::Cw,
                    cull_mode: cull.then_some(wgpu::Face::Back),
                    ..Default::default()
                },
                depth_stencil: Some(wgpu::DepthStencilState {
                    format,
                    depth_write_enabled: Some(true),
                    depth_compare: Some(wgpu::CompareFunction::LessEqual),
                    stencil: Default::default(),
                    bias: Default::default(),
                }),
                multisample: Default::default(),
                fragment: None,
                multiview_mask: None,
                cache: None,
            })
        });
    }
}

/// Copies a texture into a render target of another format at the same pixels: `over` blends
/// it as premultiplied color (and leaves the pixels it does not cover), otherwise it replaces
/// the target, opaque.
struct Blit {
    shader: wgpu::ShaderModule,
    layout: wgpu::BindGroupLayout,
    pipeline_layout: wgpu::PipelineLayout,
    pipelines: HashMap<(wgpu::TextureFormat, bool), wgpu::RenderPipeline>,
}

const BLIT: &str = "
@group(0) @binding(0) var src: texture_2d<f32>;
@vertex fn vs(@builtin(vertex_index) i: u32) -> @builtin(position) vec4<f32> {
    let p = vec2<f32>(f32((i << 1u) & 2u), f32(i & 2u));
    return vec4<f32>(p * 2.0 - 1.0, 0.0, 1.0);
}
@fragment fn over(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    let c = textureLoad(src, vec2<i32>(p.xy), 0);
    if c.a == 0.0 { discard; }
    return c;
}
@fragment fn opaque(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
    return vec4<f32>(textureLoad(src, vec2<i32>(p.xy), 0).rgb, 1.0);
}
";

impl Blit {
    fn new(device: &wgpu::Device) -> Blit {
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("blit"),
            source: wgpu::ShaderSource::Wgsl(BLIT.into()),
        });
        let layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("blit"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: false },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            }],
        });
        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("blit"),
            bind_group_layouts: &[Some(&layout)],
            immediate_size: 0,
        });
        Blit {
            shader,
            layout,
            pipeline_layout,
            pipelines: HashMap::new(),
        }
    }

    fn run(&mut self, gpu: &Gpu, src: &wgpu::TextureView, dst: &wgpu::Texture, over: bool) {
        let format = dst.format();
        let blendable = format
            .guaranteed_format_features(gpu.features)
            .flags
            .contains(wgpu::TextureFormatFeatureFlags::BLENDABLE);
        let (shader, layout) = (&self.shader, &self.pipeline_layout);
        let pipeline = self.pipelines.entry((format, over)).or_insert_with(|| {
            gpu.device
                .create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                    label: Some("blit"),
                    layout: Some(layout),
                    vertex: wgpu::VertexState {
                        module: shader,
                        entry_point: Some("vs"),
                        compilation_options: Default::default(),
                        buffers: &[],
                    },
                    primitive: Default::default(),
                    depth_stencil: None,
                    multisample: Default::default(),
                    fragment: Some(wgpu::FragmentState {
                        module: shader,
                        entry_point: Some(if over { "over" } else { "opaque" }),
                        compilation_options: Default::default(),
                        targets: &[Some(wgpu::ColorTargetState {
                            format,
                            blend: (over && blendable)
                                .then_some(wgpu::BlendState::PREMULTIPLIED_ALPHA_BLENDING),
                            write_mask: wgpu::ColorWrites::ALL,
                        })],
                    }),
                    multiview_mask: None,
                    cache: None,
                })
        });
        let group = gpu.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("blit"),
            layout: &self.layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::TextureView(src),
            }],
        });
        let view = dst.create_view(&wgpu::TextureViewDescriptor {
            mip_level_count: Some(1),
            ..Default::default()
        });
        let mut enc = gpu.device.create_command_encoder(&Default::default());
        {
            let mut rp = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("blit"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    depth_slice: None,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Load,
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            rp.set_pipeline(pipeline);
            rp.set_bind_group(0, &group, &[]);
            rp.draw(0..3, 0..1);
        }
        gpu.queue.submit([enc.finish()]);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The orthographic `PROJECTION` is `SetupFrameWorldTransform`'s matrix
    /// (`debug_geometry.cpp`, 0x46BC20): `-2 / distance`, the aspect times it, `0.0013`, `1`.
    #[test]
    fn the_orthographic_projection_is_the_cpp_matrix() {
        let camera = Camera {
            target: [0.0, 10.0, 0.0],
            rotation: [0.0, 0.0, 0.0],
            distance: -45.0,
            fov_deg: 30.0,
            orthographic: true,
        };
        let (s, _, _) = scene(&camera, [0.6; 6], 0, 0.0, (640, 360)).unwrap();
        let x = -2.0 / -45.0f32;
        let mut want = [0.0; 16];
        want[0] = x;
        want[5] = 640.0 / 360.0 * x;
        want[10] = 0.0013;
        want[15] = 1.0;
        assert_eq!(s.projection, want);
        assert!(x > 0.0);
        let perspective = Camera {
            orthographic: false,
            ..camera
        };
        let (p, _, _) = scene(&perspective, [0.6; 6], 0, 0.0, (640, 360)).unwrap();
        assert_eq!(p.projection[11], 1.0);
    }
}
