//! MME in the application: the effects the embedded MMEffect of the C++ application loads, drawn
//! through `mds-mmert`.
//!
//! * The assignment ([`Mme::autoload`]): per object (the PMM models, then its accessories) the
//!   effect file beside the object file (`MmeFindEffectFileForModel`,
//!   `third_party/mmeffect/src/mmeffect/emm_manager.cpp`), then the rows of `<pmm stem>.emm`
//!   beside the PMM (`MmeBuildEmmPathForPmm`, `MmeEmmLoad`), as the first frame after a PMM load
//!   applies them.
//! * The frame ([`Mme::render`]): the host of `mds-mmert/tests/mmegold.rs`, the test that gates
//!   `mds-mmert` on the C++ images, generalized from object 0 to every object. The camera, light
//!   and world matrices as `SetupFrameWorldTransform` and `OnBeginScene` compose them; each
//!   offscreen turn's objects; then the scene: per material subset the object pass, then the
//!   edge pass, each with the technique `SasSelectTechnique` picks; a post effect draws the
//!   objects at its `ScriptExternal`; the animated textures tick at the end.
//!
//! The host is duplicated here, not shared: `mds-mmert` keeps it in a test file. The MME frame is
//! drawn on the device of `mds-mmert` (its `Gpu` cannot be built on another device) and read back.
//!
//! Not drawn yet, as `mds-mmert` has no call for them: objects without an effect (the host's
//! standard shading, `mds-render`, on its own device), effect geometry of accessories (they only
//! carry post effects) and PMD models, skinning and morphs (`Model::from_pmx` is the bind pose),
//! and the orthographic camera.

use std::cell::{Cell, RefCell};
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use mds_doc::{Document, ModelFile};
use mds_formats::pmm::Pmm;
use mds_math::Mat4;
use mds_mme::sas::SEM_OFFSCREEN;
use mds_mmert::bind::{look_at_lh, mul, perspective_lh, Mat, DRAW_EDGE, DRAW_OBJECT};
use mds_mmert::control::{Controls, Object};
use mds_mmert::emm::{self, Assignment, Live};
use mds_mmert::scene::{turn_draw, TurnDraw, TurnObject};
use mds_mmert::{DrawInput, Effect, Gpu, Model, Scene, Target};
use mds_physics::PhysicsScene;
use mds_render::Camera;
use mds_shader::vkd3d::Vkd3d;

/// MMEffect `SasMmdPass`: the draw modes `plan::select` takes.
const PASS_OBJECT: i32 = 0;
const PASS_EDGE: i32 = 3;
/// PMX material flag: draw the edge.
const FLAG_EDGE: u8 = 0x10;

/// The menu state of MMEffect (`MmeContext::effectEnabled`, `g_autoReload`, `g_emmAutoSave`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Switches {
    /// Enable Effect, 40006 and Ctrl+Shift+E: off, the scene draws without effects.
    pub enabled: bool,
    /// Auto Reload, 40001: an effect file that changed on disk loads again.
    pub auto_reload: bool,
    /// Auto Save Mapping File, 40022: saving the PMM writes the `.emm` beside it.
    pub auto_save: bool,
}

impl Default for Switches {
    /// The checks of `IDR_MME_MENU_JP` (`third_party/mmeffect/res/MMEffect.rc`).
    fn default() -> Switches {
        Switches {
            enabled: true,
            auto_reload: true,
            auto_save: true,
        }
    }
}

/// The view an MME frame is drawn from.
pub struct View<'a> {
    pub camera: &'a Camera,
    /// `[r, g, b, x, y, z]`: the light color and the direction it travels.
    pub light: [f32; 6],
    pub frame: u32,
    /// `ELAPSEDTIME`.
    pub elapsed: f32,
    pub size: [u32; 2],
}

/// The effects of a document and their assignment.
pub struct Mme {
    pub switches: Switches,
    /// One per object: the PMM models in order, then the accessories.
    pub assignments: Vec<Assignment>,
    /// The objects the assignments are of: model or accessory, slot, and stored path.
    objects: Vec<(bool, i32, String)>,
    /// `Default` of the EMM's `[Effect]` section, `""` for `none`.
    pub default: String,
    /// The folder relative effect paths resolve against (the PMM's).
    dir: PathBuf,
    /// The MME log (the log window, 40002).
    pub log: RefCell<Vec<String>>,
    /// The device, the compiler and the loaded effects, built at the first MME frame.
    runtime: RefCell<Option<Runtime>>,
    /// The runtime could not start (no adapter or no vkd3d-shader): the scene draws without
    /// effects until [`Mme::unload`], as the C++ draws when MMEffect does not initialize.
    failed: Cell<bool>,
    /// The back buffer `ViewportRatio` targets are sized against; `None` is the frame's size.
    pub backbuffer: Option<(u32, u32)>,
    /// The vkd3d-shader library; `None` is [`Vkd3d::load`]'s (`MDS_VKD3D_LIB`, else beside the
    /// executable).
    pub vkd3d: Option<PathBuf>,
}

struct Loaded {
    path: PathBuf,
    stamp: Option<SystemTime>,
    effect: Effect,
    /// The object (an index into the assignments) the effect is assigned to.
    owner: usize,
}

struct Runtime {
    gpu: Gpu,
    vk: Vkd3d,
    state: State,
}

struct State {
    /// One per PMM model; `None` for a PMD or missing file.
    models: Vec<Option<Model>>,
    /// The assigned effects, then those the offscreen turns load.
    effects: Vec<Loaded>,
    target: Option<Target>,
    backbuffer: (u32, u32),
}

/// The objects of a document as the EMM sees them: the models, then the accessories.
pub fn live(doc: &Document) -> Vec<Live> {
    let p = &doc.pmm;
    let models = p.models.iter().zip(&doc.models).map(|(m, f)| Live {
        model: true,
        slot: i32::from(m.slot),
        path: m.path.text.clone(),
        materials: match f {
            ModelFile::Pmx(x) => x.materials.len() as i32,
            ModelFile::Pmd(d) => d.materials.len() as i32,
            ModelFile::Missing => 0,
        },
        render_class: 0,
    });
    let accessories = p.accessories.iter().map(|a| Live {
        model: false,
        slot: i32::from(a.slot),
        path: a.path.text.clone(),
        materials: 0,
        render_class: 0,
    });
    models.chain(accessories).collect()
}

/// An effect path as an EMM or the assignment stores it, on this system: `\` as the separator,
/// relative to `dir`.
pub fn effect_file(dir: &Path, stored: &str) -> PathBuf {
    let native = stored.replace('\\', std::path::MAIN_SEPARATOR_STR);
    let windows_rooted = stored.as_bytes().get(1) == Some(&b':');
    match Path::new(&native).is_absolute() || windows_rooted {
        true => PathBuf::from(native),
        false => dir.join(native),
    }
}

/// The `.emm` beside a PMM (`MmeBuildEmmPathForPmm`).
pub fn emm_path(pmm: &Path) -> PathBuf {
    pmm.with_extension("emm")
}

impl Mme {
    /// No effects: the scene of a document without an EMM and without effect files beside its
    /// objects.
    pub fn none(dir: &Path) -> Mme {
        Mme {
            switches: Switches::default(),
            assignments: Vec::new(),
            objects: Vec::new(),
            default: String::new(),
            dir: dir.to_path_buf(),
            log: RefCell::new(Vec::new()),
            runtime: RefCell::new(None),
            failed: Cell::new(false),
            backbuffer: None,
            vkd3d: None,
        }
    }

    /// The assignment of `doc` when it was loaded from `pmm` (see the module doc); `None` is a
    /// scene not saved yet.
    pub fn autoload(doc: &Document, pmm: Option<&Path>) -> Mme {
        let dir = pmm.and_then(Path::parent).unwrap_or(Path::new("."));
        let mut mme = Mme::none(dir);
        mme.assign_beside(doc);
        if let Some(path) = pmm.map(emm_path).filter(|p| p.is_file()) {
            if let Err(e) = mme.load_emm(doc, &path) {
                mme.log.borrow_mut().push(e);
            }
        }
        mme
    }

    /// The effect file beside each object file, where the object has none.
    fn assign_beside(&mut self, doc: &Document) {
        let live = live(doc);
        self.assignments
            .resize_with(live.len(), Assignment::default);
        self.objects = live.iter().map(key).collect();
        for (a, l) in self.assignments.iter_mut().zip(&live) {
            if a.effect.is_empty() {
                let object = crate::scene::resolve(&self.dir, &l.path);
                a.effect = emm::effect_for_model(&object.to_string_lossy(), "", &|p| {
                    Path::new(p).is_file()
                });
            }
        }
    }

    /// `MmeEmmLoad`: the rows of the EMM at `path` over the assignment.
    pub fn load_emm(&mut self, doc: &Document, path: &Path) -> Result<(), String> {
        let bytes = std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
        let name = path.to_string_lossy();
        let (parsed, log) = emm::parse_emm(&bytes, &name);
        self.log
            .borrow_mut()
            .extend(log.into_iter().map(|l| l.text));
        let parsed = parsed.ok_or_else(|| format!("{name}: not an EMM file"))?;
        let live = live(doc);
        self.assignments
            .resize_with(live.len(), Assignment::default);
        let dir = self.dir.clone();
        let cwd = dir.to_string_lossy().into_owned();
        let exists = |p: &str| effect_file(&dir, p).is_file();
        let (default, report) =
            emm::apply_emm(&parsed, &name, &live, &mut self.assignments, &cwd, &exists);
        self.default = default;
        self.log
            .borrow_mut()
            .extend(report.log.into_iter().map(|l| l.text));
        self.unload();
        Ok(())
    }

    /// `MmeEmmSave`: the EMM bytes of the assignment.
    pub fn save_emm(&self, doc: &Document) -> Vec<u8> {
        let cwd = self.dir.to_string_lossy();
        emm::save_emm(&live(doc), &self.assignments, &self.default, &cwd)
    }

    /// The folder relative effect paths resolve against.
    pub fn dir(&self) -> &Path {
        &self.dir
    }

    /// How many effects are loaded (assigned ones and those of the offscreen turns).
    pub fn loaded(&self) -> usize {
        self.runtime
            .borrow()
            .as_ref()
            .map_or(0, |r| r.state.effects.len())
    }

    /// Whether a frame draws through MME: effects on and an object with an effect.
    pub fn active(&self) -> bool {
        self.switches.enabled
            && !self.failed.get()
            && self
                .assignments
                .iter()
                .any(|a| !a.effect.is_empty() || a.subsets.values().any(|p| !p.is_empty()))
    }

    /// The objects changed (a model or accessory loaded or deleted): the assignment follows
    /// the new list, the meshes load again.
    pub fn objects_changed(&mut self, doc: &Document) {
        let old = std::mem::take(&mut self.assignments);
        self.assignments = live(doc)
            .iter()
            .map(|l| match self.objects.iter().position(|o| *o == key(l)) {
                Some(i) => old[i].clone(),
                None => Assignment::default(),
            })
            .collect();
        self.assign_beside(doc);
        self.unload();
    }

    /// Every effect and mesh again at the next frame (Reload All, 40004).
    pub fn unload(&self) {
        *self.runtime.borrow_mut() = None;
        self.failed.set(false);
    }

    /// The effects whose file changed on disk since they loaded (Auto Reload, 40001): those load
    /// again at the next frame. Returns how many.
    pub fn reload_changed(&self) -> usize {
        let mut rt = self.runtime.borrow_mut();
        let Some(rt) = rt.as_mut() else { return 0 };
        let effects = &mut rt.state.effects;
        let before = effects.len();
        effects.retain(|l| stamp(&l.path) == l.stamp);
        before - effects.len()
    }

    /// Draws the frame of `view` with the effects and returns its RGBA pixels, top row first.
    pub fn render(
        &self,
        doc: &Document,
        physics: &PhysicsScene,
        view: &View,
    ) -> Result<Vec<u8>, String> {
        let mut slot = self.runtime.borrow_mut();
        if slot.is_none() {
            let started = self.start(doc, view.size).inspect_err(|e| {
                self.failed.set(true);
                self.log.borrow_mut().push(e.clone());
            });
            *slot = Some(started?);
        }
        let Runtime { gpu, vk, state } = slot.as_mut().expect("runtime built above");
        let size = (view.size[0], view.size[1]);
        if state
            .target
            .as_ref()
            .is_none_or(|t| (t.color.width(), t.color.height()) != size)
        {
            state.target = Some(Target::new(gpu, size));
        }
        let (skipped, errors) = gpu.scoped(|| state.frame(gpu, vk, self, doc, physics, view));
        if !skipped.is_empty() {
            self.log
                .borrow_mut()
                .push(format!("skipped draws: {skipped:?}"));
        }
        if !errors.is_empty() {
            self.log
                .borrow_mut()
                .push(format!("wgpu errors: {errors:?}"));
        }
        let target = state.target.as_ref().expect("target created above");
        let mut px = target.read(gpu)?;
        for p in px.chunks_exact_mut(4) {
            p[3] = 255;
        }
        Ok(px)
    }

    fn start(&self, doc: &Document, size: [u32; 2]) -> Result<Runtime, String> {
        let gpu = Gpu::new()?.ok_or("MME: no wgpu adapter")?;
        let vk = match &self.vkd3d {
            Some(p) => Vkd3d::open(p),
            None => Vkd3d::load(),
        }
        .map_err(|e| format!("MME: vkd3d-shader: {e}"))?;
        let models = doc
            .models
            .iter()
            .map(|f| match f {
                ModelFile::Pmx(pmx) => Model::from_pmx(&gpu.device, pmx).ok(),
                _ => None,
            })
            .collect();
        Ok(Runtime {
            gpu,
            vk,
            state: State {
                models,
                effects: Vec::new(),
                target: None,
                backbuffer: self.backbuffer.unwrap_or((size[0], size[1])),
            },
        })
    }
}

fn key(l: &Live) -> (bool, i32, String) {
    (l.model, l.slot, l.path.clone())
}

fn stamp(path: &Path) -> Option<SystemTime> {
    std::fs::metadata(path).and_then(|m| m.modified()).ok()
}

fn file_name(path: &str) -> &str {
    path.rsplit(['\\', '/']).next().unwrap_or(path)
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
fn host_scene(view: &View) -> Result<(Scene, Mat, Mat), String> {
    let c = view.camera;
    let [w, h] = view.size;
    let [pitch, yaw, roll] = c.rotation;
    let t = Mat4::translation(-c.target[0], -c.target[1], -c.target[2]);
    let r = Mat4::multiply(&Mat4::rotation_y(yaw), &Mat4::rotation_x(pitch));
    let r = Mat4::multiply(&r, &Mat4::rotation_z(roll));
    let frame_world = Mat4::multiply(&t, &r);
    let inverse = frame_world.inverse().ok_or("camera matrix")?.0 .0;
    let eye = [0.0, 0.0, c.distance];
    let look = look_at_lh(eye, [0.0, 0.0, c.distance + 80.0], [0.0, 1.0, 0.0]);
    let fov = (f64::from(c.fov_deg) * std::f64::consts::PI / 180.0) as f32;
    let [r, g, b, x, y, z] = view.light;
    let mut s = Scene::default_view(w, h);
    s.world = mul(&m4(&frame_world), &inverse);
    s.view = mul(&m4(&frame_world), &look);
    s.projection = perspective_lh(fov, w as f32 / h as f32, 1.0, 100000.0);
    s.light_direction = [x, y, z];
    s.light_ambient = [r, g, b];
    s.light_diffuse = [r, g, b];
    s.light_specular = [r, g, b];
    s.time = view.frame as f32 / 30.0;
    s.elapsed = view.elapsed;
    Ok((s, m4(&frame_world), inverse))
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
) -> Vec<Option<(mds_accessory::AccessoryState, Mat)>> {
    let models = &physics.scene.models;
    let at = |a| mds_render::scene::accessory_at(a, frame, models);
    pmm.accessories.iter().map(at).collect()
}

/// The scene's objects as the host exports them: the models by draw order (1-based), with
/// their bones and morphs from the pose, then the accessories.
fn host_controls(doc: &Document, physics: &PhysicsScene, frame: u32) -> Controls {
    let pmm = &doc.pmm;
    let mut objects = Vec::new();
    for (i, (m, file)) in pmm.models.iter().zip(&doc.models).enumerate() {
        let mut o = Object::model(file_name(&m.path.text), i as i32 + 1);
        let posed = physics.scene.models.iter().find(|p| p.slot == m.slot);
        if let (ModelFile::Pmx(pmx), Some(posed)) = (file, posed) {
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
        }
        objects.push(o);
    }
    for (a, state) in pmm.accessories.iter().zip(accessories(pmm, physics, frame)) {
        let mut o = Object::model(file_name(&a.path.text), i32::from(a.order) + 1);
        o.model = false;
        match state {
            Some((state, world)) => {
                o.shown = state.visible;
                o.world = world;
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

impl State {
    /// Index of the loaded effect at `path` for `owner`, loading it; `None` when it does not
    /// load (logged).
    fn effect_for(
        &mut self,
        gpu: &Gpu,
        vk: &Vkd3d,
        mme: &Mme,
        path: &Path,
        owner: usize,
    ) -> Option<usize> {
        if let Some(i) = self.effects.iter().position(|l| l.path == path) {
            return Some(i);
        }
        // The effect's includes and textures may sit anywhere above it (`..\ray.conf`), so the
        // root it resolves below is the file system's.
        let root = path.ancestors().last().unwrap_or(Path::new("/"));
        mme.log
            .borrow_mut()
            .push(format!("Loading effect file: {}", path.display()));
        match Effect::load(gpu, vk, path, root, self.backbuffer) {
            Ok(effect) => {
                if effect.sas.has_errors {
                    mme.log.borrow_mut().push(effect.sas.log.clone());
                }
                self.effects.push(Loaded {
                    path: path.to_path_buf(),
                    stamp: stamp(path),
                    effect,
                    owner,
                });
                Some(self.effects.len() - 1)
            }
            Err(e) => {
                mme.log
                    .borrow_mut()
                    .push(format!("{}: {e}", path.display()));
                None
            }
        }
    }

    /// The object and edge passes of model `o` with effect `e` into `target`, over the subsets
    /// `subset` admits.
    #[allow(clippy::too_many_arguments)]
    fn draw_model(
        &mut self,
        gpu: &Gpu,
        doc: &Document,
        o: usize,
        e: usize,
        subset: &dyn Fn(usize) -> bool,
        target: &Target,
        input: &DrawInput,
    ) -> Vec<String> {
        let mut skipped = Vec::new();
        let (Some(Some(model)), Some(ModelFile::Pmx(pmx))) =
            (self.models.get(o), doc.models.get(o))
        else {
            return skipped;
        };
        for (mode, draw_type) in [(PASS_OBJECT, DRAW_OBJECT), (PASS_EDGE, DRAW_EDGE)] {
            for (s, m) in model.materials.iter().enumerate() {
                if !subset(s) || (mode == PASS_EDGE && pmx.materials[s].flags & FLAG_EDGE == 0) {
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
                let Some(tech) = effect.sas.techniques.iter().position(|t| t.fx == h) else {
                    continue;
                };
                let r = effect.draw_technique(gpu, target, &input, tech);
                skipped.extend(r.skipped);
            }
        }
        skipped
    }

    /// The effect draws of the scene's objects: per model and per effect its assignment names,
    /// the subsets that effect draws. Effects that are not loaded are skipped.
    fn draw_objects(
        &mut self,
        gpu: &Gpu,
        mme: &Mme,
        doc: &Document,
        objects: &[(usize, usize)],
        target: &Target,
        base: &DrawInput,
    ) -> Vec<String> {
        let mut skipped = Vec::new();
        for &(o, e) in objects {
            let a = &mme.assignments[o];
            let path = self.effects[e].path.clone();
            let dir = &mme.dir;
            let subset = |s: usize| {
                let p = a.subsets.get(&(s as i32)).filter(|p| !p.is_empty());
                let file = p.map_or_else(|| effect_file(dir, &a.effect), |p| effect_file(dir, p));
                a.shown && a.subset_shown(s as i32) && file == path
            };
            let input = DrawInput {
                owner: Some(o),
                ..*base
            };
            skipped.extend(self.draw_model(gpu, doc, o, e, &subset, target, &input));
        }
        skipped
    }

    /// One frame into the target; returns why draws were skipped.
    fn frame(
        &mut self,
        gpu: &Gpu,
        vk: &Vkd3d,
        mme: &Mme,
        doc: &Document,
        physics: &PhysicsScene,
        view: &View,
    ) -> Vec<String> {
        let mut skipped = Vec::new();
        let (scene, frame_world, inverse) = match host_scene(view) {
            Ok(s) => s,
            Err(e) => return vec![e],
        };
        let controls = host_controls(doc, physics, view.frame);
        let n_models = doc.pmm.models.len();
        // The assigned effects, loaded: (object, effect) per distinct file of each object.
        let mut assigned: Vec<(usize, usize)> = Vec::new();
        for (o, a) in mme.assignments.iter().enumerate() {
            let files = std::iter::once(&a.effect).chain(a.subsets.values());
            for p in files.filter(|p| !p.is_empty()) {
                let file = effect_file(&mme.dir, p);
                if let Some(e) = self.effect_for(gpu, vk, mme, &file, o) {
                    if !assigned.contains(&(o, e)) {
                        assigned.push((o, e));
                    }
                }
            }
        }
        // A post effect's carrier is an accessory: its WORLD is the accessory's.
        let carrier_scenes: Vec<Scene> = accessories(&doc.pmm, physics, view.frame)
            .iter()
            .map(|a| Scene {
                world: a
                    .as_ref()
                    .map_or(scene.world, |(_, w)| mul(&mul(w, &frame_world), &inverse)),
                ..scene.clone()
            })
            .collect();
        let scene_of = |owner: usize| match owner.checked_sub(n_models) {
            Some(i) => &carrier_scenes[i],
            None => &scene,
        };
        let base = DrawInput {
            scene: &scene,
            geometry: None,
            draw_type: DRAW_OBJECT,
            controls: Some(&controls),
            owner: None,
            offscreen_owner: None,
        };
        let post = |rt: &State, e: usize| rt.effects[e].effect.sas.script_class == 1;
        let names: Vec<String> = controls.objects.iter().map(|o| o.name.clone()).collect();

        // The offscreen turns: each target of each loaded effect, every model drawn as its rows say.
        for c in 0..self.effects.len() {
            let owner = self.effects[c].owner;
            let targets: Vec<usize> = (0..self.effects[c].effect.sas.resources.len())
                .filter(|&r| self.effects[c].effect.sas.resources[r].semantic == SEM_OFFSCREEN)
                .collect();
            for r in targets {
                let Some(turn) = self.effects[c].effect.begin_offscreen(gpu, r) else {
                    continue;
                };
                for (o, name) in names.iter().enumerate().take(n_models) {
                    let render_class =
                        i32::from(assigned.iter().any(|&(oo, e)| oo == o && post(self, e)));
                    let obj = TurnObject {
                        name,
                        owner: owner == o,
                        render_class,
                        main: &mme.assignments[o],
                    };
                    let draw = turn_draw(&self.effects[c].effect.sas.resources[r], &obj, None);
                    let TurnDraw::Effect(file) = draw else {
                        continue;
                    };
                    let Some(e) = self.effect_for(gpu, vk, mme, &file, o) else {
                        continue;
                    };
                    // VIEWPORTPIXELSIZE in a turn is its target's.
                    let turn_scene = Scene {
                        viewport: (turn.color.width(), turn.color.height()),
                        ..scene.clone()
                    };
                    let input = DrawInput {
                        scene: &turn_scene,
                        owner: Some(o),
                        offscreen_owner: Some(owner),
                        ..base
                    };
                    skipped.extend(self.draw_model(gpu, doc, o, e, &|_| true, &turn, &input));
                }
            }
        }

        // The scene: a post effect draws the objects at its ScriptExternal; without one the
        // objects draw into the back buffer after the host's clear.
        let Some(target) = self.target.take() else {
            return skipped;
        };
        target.clear_turn(gpu, Some(scene.background), 1.0, true);
        let objects: Vec<(usize, usize)> = assigned
            .iter()
            .copied()
            .filter(|&(o, e)| o < n_models && !post(self, e))
            .collect();
        let posts: Vec<(usize, usize)> = assigned
            .iter()
            .copied()
            .filter(|&(o, e)| mme.assignments[o].shown && post(self, e))
            .collect();
        if posts.is_empty() {
            skipped.extend(self.draw_objects(gpu, mme, doc, &objects, &target, &base));
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
                scene: scene_of(owner),
                owner: Some(owner),
                ..base
            };
            let mut inner = Vec::new();
            let r = post
                .effect
                .frame_with_scene(gpu, &target, &input, &mut |_, t| {
                    inner.extend(self.draw_objects(gpu, mme, doc, &objects, t, &base))
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
}
