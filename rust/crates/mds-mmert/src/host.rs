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
//! * The objects without an effect, and the `none` rows of an offscreen turn, are the host's own
//!   draw: `mds-render`'s standard MMD shading of those objects, on the runtime's device,
//!   composited into the target before the effect draws.
//!
//! Not ported: the background picture and the projected ground shadow under the effect objects;
//! an object with an effect on some of its subsets draws only those (`mds-render` draws whole
//! meshes).

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use mds_accessory::{Accessory, AccessoryState};
use mds_formats::pmd::Pmd;
use mds_formats::pmm::Pmm;
use mds_formats::pmx::Pmx;
use mds_math::Mat4;
use mds_mme::sas::SEM_OFFSCREEN;
use mds_pose::model::Model as Posed;
use mds_render::{AccessoryDraw, AccessoryMesh, Camera, Light, Mesh, Pose, Renderer, Stage};
use mds_shader::vkd3d::Vkd3d;
use mds_skin::Skin;

use crate::bind::{look_at_lh, mul, perspective_lh, Mat, DRAW_EDGE, DRAW_OBJECT};
use crate::control::{Controls, Object};
use crate::emm::Assignment;
use crate::scene::{turn_draw, TurnDraw, TurnObject};
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

/// A model's pose inputs and its standard-shading mesh.
struct Shape {
    skin: Skin,
    mesh: Mesh,
    edge_scale: f32,
    bones: Vec<String>,
    morphs: Vec<String>,
}

enum Kind {
    Model(Box<Shape>),
    Accessory(Box<AccessoryMesh>),
    Missing,
}

struct Item {
    /// The file name with its extension, which `CONTROLOBJECT` and the turn rows match.
    name: String,
    /// The geometry the effects draw.
    model: Option<Model>,
    kind: Kind,
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
    target: Option<Target>,
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
/// `SetupFrameWorldTransform` writes. MME's `VIEW` is the world times the view, and an object's
/// `WORLD` its device world (its own world times the frame world) times the inverse of the frame
/// world. Also returns the frame world and its inverse; `None` for a camera with no inverse.
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
    s.light_diffuse = [r, g, b];
    s.light_specular = [r, g, b];
    s.time = frame as f32 / 30.0;
    s.elapsed = elapsed;
    Some((s, frame_world.0, inverse))
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
    f: &'a Frame<'a>,
}

impl Host {
    pub fn new(backbuffer: (u32, u32)) -> Host {
        Host {
            backbuffer,
            objects: Vec::new(),
            effects: Vec::new(),
            standard: None,
            blit: None,
            target: None,
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
        });
        r
    }

    /// The loaded effects.
    pub fn effects(&self) -> &[Loaded] {
        &self.effects
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

    /// The models in the frame's pose: the vertex and material values of `mds-skin` written into
    /// each model's buffers. Returns the poses, one per object.
    fn pose(&mut self, gpu: &Gpu, f: &Frame, frame_world: &Mat) -> Vec<Option<Pose>> {
        let self_shadow = mds_render::scene::stage_at(f.pmm, f.frame)
            .self_shadow
            .is_some_and(|s| s.shades());
        let mut poses = Vec::with_capacity(self.objects.len());
        for (o, item) in self.objects.iter_mut().enumerate() {
            let posed = f
                .pmm
                .models
                .get(o)
                .and_then(|m| f.poses.iter().find(|p| p.slot == m.slot));
            let (Kind::Model(shape), Some(model), Some(posed)) =
                (&mut item.kind, &mut item.model, posed)
            else {
                poses.push(None);
                continue;
            };
            let pose = mds_render::scene::pose_of(posed);
            // A pose shorter or longer than the model's tables is padded or cut, as
            // `mds-render` pads it.
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
                    world: Mat4(*frame_world),
                    camera_position: f.camera.target,
                    camera_fov: f.camera.fov_deg,
                    edge_scale: shape.edge_scale,
                    self_shadow,
                },
            );
            model.update(&gpu.queue, skin);
            poses.push(Some(pose));
        }
        poses
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
        let poses = self.pose(gpu, f, &frame_world);
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
        // An accessory's WORLD is its own world matrix in the frame world.
        let scenes: Vec<Scene> = (0..self.objects.len())
            .map(
                |o| match o.checked_sub(n_models).and_then(|i| accessories.get(i)) {
                    Some(Some((_, w))) => Scene {
                        world: mul(&mul(w, &frame_world), &inverse),
                        ..scene.clone()
                    },
                    _ => scene.clone(),
                },
            )
            .collect();
        let drawn = Drawn {
            scenes,
            poses,
            accessories,
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
        let post = |effects: &[Loaded], e: usize| effects[e].effect.sas.script_class == 1;
        let carrier = |effects: &[Loaded], o: usize| {
            assigned.iter().any(|&(oo, e)| oo == o && post(effects, e))
        };
        let mut skipped = Vec::new();

        // The offscreen turns: each target of each loaded effect, every object drawn as its rows
        // say.
        for c in 0..self.effects.len() {
            let owner = self.effects[c].owner;
            let targets: Vec<usize> = (0..self.effects[c].effect.sas.resources.len())
                .filter(|&r| self.effects[c].effect.sas.resources[r].semantic == SEM_OFFSCREEN)
                .collect();
            for r in targets {
                let Some(turn) = self.effects[c].effect.begin_offscreen(gpu, r) else {
                    continue;
                };
                let (mut host, mut effects) = (Vec::new(), Vec::new());
                for o in 0..self.objects.len() {
                    if self.objects[o].model.is_none() {
                        continue;
                    }
                    let obj = TurnObject {
                        name: &self.objects[o].name,
                        owner: owner == o,
                        render_class: i32::from(carrier(&self.effects, o)),
                        main: assignment(o),
                    };
                    match turn_draw(&self.effects[c].effect.sas.resources[r], &obj, None) {
                        TurnDraw::Hide => {}
                        TurnDraw::Host => host.push(o),
                        TurnDraw::Effect(file) => {
                            if let Some(e) = self.effect_for(gpu, vk, &file, o, log) {
                                effects.push((o, e));
                            }
                        }
                    }
                }
                if let Err(e) = self.draw_standard(gpu, &turn, &host, &drawn) {
                    skipped.push(e);
                }
                // VIEWPORTPIXELSIZE in a turn is its target's.
                let viewport = (turn.color.width(), turn.color.height());
                for (o, e) in effects {
                    let turn_scene = Scene {
                        viewport,
                        ..drawn.scenes[o].clone()
                    };
                    let input = DrawInput {
                        scene: &turn_scene,
                        owner: Some(o),
                        offscreen_owner: Some(owner),
                        ..base
                    };
                    let effect = &mut self.effects[e].effect;
                    let item = &self.objects[o];
                    skipped.extend(draw_object(gpu, effect, item, &|_| true, &turn, &input));
                }
            }
        }

        // The scene: a post effect draws the objects at its ScriptExternal; without one the
        // objects draw into the back buffer after the host's clear. The objects with no effect
        // (and no post effect they carry) are the host's.
        let target = self.target.take().expect("target created above");
        target.clear_turn(gpu, Some(scene.background), 1.0, true);
        let objects: Vec<(usize, usize)> = assigned
            .iter()
            .copied()
            .filter(|&(_, e)| !post(&self.effects, e))
            .collect();
        let host: Vec<usize> = (0..self.objects.len())
            .filter(|&o| {
                self.objects[o].model.is_some()
                    && assignment(o).shown
                    && !assigned.iter().any(|&(oo, _)| oo == o)
            })
            .collect();
        let posts: Vec<(usize, usize)> = assigned
            .iter()
            .copied()
            .filter(|&(o, e)| assignment(o).shown && post(&self.effects, e))
            .collect();
        if posts.is_empty() {
            if let Err(e) = self.draw_standard(gpu, &target, &host, &drawn) {
                skipped.push(e);
            }
            skipped.extend(self.draw_objects(gpu, &objects, &target, &base, &drawn));
        }
        for (owner, p) in posts {
            // The post effect leaves the list while it runs, so that the scene draw can borrow the
            // object effects.
            let mut post = self.effects.remove(p);
            let objects: Vec<(usize, usize)> = objects
                .iter()
                .map(|&(o, e)| (o, if e > p { e - 1 } else { e }))
                .collect();
            let input = DrawInput {
                scene: &drawn.scenes[owner],
                owner: Some(owner),
                ..base
            };
            let mut inner = Vec::new();
            let r = post
                .effect
                .frame_with_scene(gpu, &target, &input, &mut |_, t| {
                    if let Err(e) = self.draw_standard(gpu, t, &host, &drawn) {
                        inner.push(e);
                    }
                    inner.extend(self.draw_objects(gpu, &objects, t, &base, &drawn));
                });
            self.effects.insert(p, post);
            skipped.extend(r.skipped);
            skipped.extend(inner);
        }
        for l in &mut self.effects {
            l.effect.tick_animes(gpu, scene.time);
        }
        self.target = Some(target);
        skipped
    }

    /// The effect draws of the scene's objects: per object and per effect its assignment names,
    /// the subsets that effect draws.
    fn draw_objects(
        &mut self,
        gpu: &Gpu,
        objects: &[(usize, usize)],
        target: &Target,
        base: &DrawInput,
        drawn: &Drawn,
    ) -> Vec<String> {
        let mut skipped = Vec::new();
        let default = Assignment::default();
        for &(o, e) in objects {
            let a = drawn.f.assignments.get(o).unwrap_or(&default);
            let path = self.effects[e].file.clone();
            let resolve = drawn.f.resolve;
            let subset = |s: usize| {
                let p = a.subsets.get(&(s as i32)).filter(|p| !p.is_empty());
                let file = resolve(p.unwrap_or(&a.effect));
                a.shown && a.subset_shown(s as i32) && file == path
            };
            let input = DrawInput {
                scene: &drawn.scenes[o],
                owner: Some(o),
                ..*base
            };
            let effect = &mut self.effects[e].effect;
            skipped.extend(draw_object(
                gpu,
                effect,
                &self.objects[o],
                &subset,
                target,
                &input,
            ));
        }
        skipped
    }

    /// The host's own draw of `list` into `target`: `mds-render` on a transparent scratch
    /// texture, composited over the target, so a target the effect cleared keeps its color.
    // ponytail: the target's depth does not get these objects, so an effect object behind one
    // still draws over it; a depth-only pass of their posed vertices with MME's matrices would fix
    // that.
    fn draw_standard(
        &mut self,
        gpu: &Gpu,
        target: &Target,
        list: &[usize],
        drawn: &Drawn,
    ) -> Result<(), String> {
        if list.is_empty() {
            return Ok(());
        }
        let f = drawn.f;
        let n_models = f.pmm.models.len();
        let mut models = Vec::new();
        let mut accessories = Vec::new();
        for &o in list {
            match &self.objects[o].kind {
                Kind::Model(shape) => models.push((&shape.mesh, drawn.poses[o].as_ref())),
                Kind::Accessory(mesh) => {
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
            view: f.camera.view(w, h),
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
}

fn load(
    gpu: &Gpu,
    source: Source,
    edge_scale: f32,
    read: impl FnMut(&str) -> Option<Vec<u8>>,
) -> Result<(Option<Model>, Kind), String> {
    let (model, skin, mut mesh, bones, morphs) = match source {
        Source::Pmx(pmx) => (
            Model::from_pmx(&gpu.device, pmx)?,
            Skin::from_pmx(pmx)?,
            Mesh::from_pmx(pmx)?,
            pmx.bones.iter().map(|b| b.name.text.clone()).collect(),
            pmx.morphs.iter().map(|m| m.name.text.clone()).collect(),
        ),
        Source::Pmd(pmd) => (
            Model::from_pmd(&gpu.device, pmd)?,
            Skin::from_pmd(pmd)?,
            Mesh::from_pmd(pmd)?,
            pmd.bones.iter().map(|b| b.name.text.clone()).collect(),
            pmd.morphs.iter().map(|m| m.name.text.clone()).collect(),
        ),
        Source::Accessory(acc) => {
            let model = Model::from_accessory(&gpu.device, &acc)?;
            let mut mesh = AccessoryMesh::new(acc);
            mesh.load_textures(read);
            return Ok((Some(model), Kind::Accessory(Box::new(mesh))));
        }
        Source::Missing => return Ok((None, Kind::Missing)),
    };
    mesh.load_textures(read);
    mesh.set_edge_scale(edge_scale);
    let shape = Shape {
        skin,
        mesh,
        edge_scale,
        bones,
        morphs,
    };
    Ok((Some(model), Kind::Model(Box::new(shape))))
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
