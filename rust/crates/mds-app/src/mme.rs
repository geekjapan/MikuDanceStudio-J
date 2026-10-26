//! MME in the application: the effects the embedded MMEffect of the C++ application loads, drawn
//! through `mds-mmert`.
//!
//! * The assignment ([`Mme::autoload`]): per object (the PMM models, then its accessories) the
//!   effect file beside the object file (`MmeFindEffectFileForModel`,
//!   `third_party/mmeffect/src/mmeffect/emm_manager.cpp`), then the rows of `<pmm stem>.emm`
//!   beside the PMM (`MmeBuildEmmPathForPmm`, `MmeEmmLoad`), as the first frame after a PMM load
//!   applies them.
//! * The frame ([`Mme::render`], [`Mme::render_into`]): `mds_mmert::host`, the host that
//!   `mds-mmert/tests/mmegold.rs` gates on the C++ images, over the document's models (PMX and
//!   PMD, posed) and accessories. [`Mme::render`] draws on a device of its own and reads the
//!   picture back; [`Mme::render_into`] draws on the caller's device into the caller's texture.

use std::cell::{Cell, RefCell};
use std::path::{Path, PathBuf};

use mds_doc::{Document, ModelFile};
use mds_mmert::emm::{self, Assignment, Live};
use mds_mmert::host::{Frame, Host, OffscreenTarget, Source};
use mds_mmert::scene::Offscreen;
use mds_mmert::Gpu;
use mds_physics::PhysicsScene;
use mds_render::CameraFrame;
use mds_shader::vkd3d::Vkd3d;

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
    pub camera: &'a CameraFrame,
    pub view_offset: [f32; 2],
    pub shadow_map: mds_render::ShadowMapSize,
    pub shadow_map_display: bool,
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
    /// The mapping dialog's edits of the offscreen targets (`SasResource::effectOverrides` and
    /// `shownOverrides`). They outlive the effects loading again, which the dialog's every edit
    /// causes here; Reload All clears them.
    pub offscreen: Offscreen,
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

struct Runtime {
    gpu: Gpu,
    vk: Vkd3d,
    host: Host,
    /// Built on a caller's device ([`Mme::render_into`]), not on one of its own.
    shared: bool,
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
/// relative to `dir`, with the case-insensitive lookup of Windows.
pub fn effect_file(dir: &Path, stored: &str) -> PathBuf {
    let native = stored.replace('\\', std::path::MAIN_SEPARATOR_STR);
    let windows_rooted = stored.as_bytes().get(1) == Some(&b':');
    let path = match Path::new(&native).is_absolute() || windows_rooted {
        true => PathBuf::from(native),
        false => dir.join(native),
    };
    let root = path.ancestors().last().unwrap_or(Path::new("."));
    let relative = path.strip_prefix(root).unwrap().to_string_lossy();
    mds_fx::preprocess::resolve_ci(root, &relative).unwrap_or(path)
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
            offscreen: Offscreen::new(),
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
                    effect_file(Path::new(""), p).is_file()
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

    /// `DlgDisassembleFlow` (`mme_dlg.cpp:1459`): the effect `stored` (as an assignment stores
    /// it) in shader assembly, with `\r\n` line breaks (`DlgDisassembleNormalizeLineEnds`,
    /// `:1406`); empty when it does not load, as the C++ shows an empty window.
    pub fn disassemble(&self, stored: &str) -> String {
        let vk = match &self.vkd3d {
            Some(p) => Vkd3d::open(p),
            None => Vkd3d::load(),
        };
        let text =
            vk.and_then(|vk| mds_shader::disassemble_file(&vk, &effect_file(&self.dir, stored)));
        match text {
            Ok(t) => crlf(&t),
            Err(e) => {
                self.log.borrow_mut().push(e);
                String::new()
            }
        }
    }

    /// The offscreen targets of the loaded effects, the tabs of the mapping dialog.
    pub fn offscreen_targets(&self) -> Vec<OffscreenTarget> {
        self.runtime
            .borrow()
            .as_ref()
            .map_or_else(Vec::new, |r| r.host.offscreen_targets())
    }

    /// How many effects are loaded (assigned ones and those of the offscreen turns).
    pub fn loaded(&self) -> usize {
        self.runtime
            .borrow()
            .as_ref()
            .map_or(0, |r| r.host.effects().len())
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
        let was: Vec<Option<usize>> = live(doc)
            .iter()
            .map(|l| self.objects.iter().position(|o| *o == key(l)))
            .collect();
        self.assignments = was
            .iter()
            .map(|i| i.map_or_else(Assignment::default, |i| old[i].clone()))
            .collect();
        for objects in self.offscreen.values_mut() {
            let old = std::mem::take(objects);
            for (now, i) in was.iter().enumerate() {
                if let Some(o) = i.and_then(|i| old.get(&i)) {
                    objects.insert(now, o.clone());
                }
            }
        }
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
        rt.as_mut().map_or(0, |rt| rt.host.reload_changed())
    }

    /// Draws the frame of `view` with the effects and returns its RGBA pixels, top row first.
    pub fn render(
        &self,
        doc: &Document,
        physics: &PhysicsScene,
        view: &View,
    ) -> Result<Vec<u8>, String> {
        let mut slot = self.runtime.borrow_mut();
        let rt = self.runtime_on(&mut slot, doc, view, None)?;
        self.frame(rt, doc, physics, view);
        let target = rt.host.target().ok_or("no MME frame")?;
        let mut px = target.read(&rt.gpu)?;
        for p in px.chunks_exact_mut(4) {
            p[3] = 255;
        }
        Ok(px)
    }

    /// [`Mme::render`] on `device` (a window's) into `texture`, a texture of `view.size` with
    /// `RENDER_ATTACHMENT` usage, with no read back. The runtime starts again on another device.
    pub fn render_into(
        &self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        doc: &Document,
        physics: &PhysicsScene,
        view: &View,
        texture: &wgpu::Texture,
    ) -> Result<(), String> {
        let mut slot = self.runtime.borrow_mut();
        let rt = self.runtime_on(&mut slot, doc, view, Some((device, queue)))?;
        self.frame(rt, doc, physics, view);
        let Runtime { gpu, host, .. } = rt;
        host.output_into(gpu, texture)
    }

    /// The runtime, started at the first frame (and on `device` when it runs on another one).
    fn runtime_on<'a>(
        &self,
        slot: &'a mut Option<Runtime>,
        doc: &Document,
        view: &View,
        device: Option<(&wgpu::Device, &wgpu::Queue)>,
    ) -> Result<&'a mut Runtime, String> {
        // Devices of two wgpu instances can compare equal, so the runtime also starts again
        // when it moves between its own device and a caller's.
        if slot.as_ref().is_some_and(|rt| {
            rt.shared != device.is_some() || device.is_some_and(|(d, _)| rt.gpu.device != *d)
        }) {
            *slot = None;
        }
        if slot.is_none() {
            let started = self.start(doc, view.size, device).inspect_err(|e| {
                self.failed.set(true);
                self.log.borrow_mut().push(e.clone());
            });
            *slot = Some(started?);
        }
        Ok(slot.as_mut().expect("runtime built above"))
    }

    fn frame(&self, rt: &mut Runtime, doc: &Document, physics: &PhysicsScene, view: &View) {
        let dir = &self.dir;
        let resolve = |p: &str| effect_file(dir, p);
        let f = Frame {
            pmm: &doc.pmm,
            poses: &physics.scene.models,
            camera: view.camera,
            view_offset: view.view_offset,
            shadow_map: view.shadow_map,
            shadow_map_display: view.shadow_map_display,
            light: view.light,
            frame: view.frame,
            elapsed: view.elapsed,
            size: (view.size[0], view.size[1]),
            assignments: &self.assignments,
            offscreen: &self.offscreen,
            resolve: &resolve,
        };
        let mut log = Vec::new();
        let Runtime { gpu, vk, host, .. } = rt;
        let (skipped, errors) = gpu.scoped(|| host.render(gpu, vk, &f, &mut log));
        let mut l = self.log.borrow_mut();
        l.extend(log);
        if !skipped.is_empty() {
            l.push(format!("skipped draws: {skipped:?}"));
        }
        if !errors.is_empty() {
            l.push(format!("wgpu errors: {errors:?}"));
        }
    }

    fn start(
        &self,
        doc: &Document,
        size: [u32; 2],
        device: Option<(&wgpu::Device, &wgpu::Queue)>,
    ) -> Result<Runtime, String> {
        let gpu = match device {
            Some((d, q)) => Gpu::from_device(d, q, "window"),
            None => Gpu::new()?.ok_or("MME: no wgpu adapter")?,
        };
        let vk = match &self.vkd3d {
            Some(p) => Vkd3d::open(p),
            None => Vkd3d::load(),
        }
        .map_err(|e| format!("MME: vkd3d-shader: {e}"))?;
        let mut host = Host::new(self.backbuffer.unwrap_or((size[0], size[1])));
        let mut log = self.log.borrow_mut();
        for (m, file) in doc.pmm.models.iter().zip(&doc.models) {
            let path = crate::scene::resolve(&self.dir, &m.path.text);
            let source = match file {
                ModelFile::Pmx(pmx) => Source::Pmx(pmx),
                ModelFile::Pmd(pmd) => Source::Pmd(pmd),
                ModelFile::Missing => Source::Missing,
            };
            let added = host.add_with_shared(
                &gpu,
                &m.path.text,
                source,
                m.edge_scale,
                beside(&path),
                shared_toon,
            );
            log.extend(added.err());
        }
        for a in &doc.pmm.accessories {
            let path = crate::scene::resolve(&self.dir, &a.path.text);
            let source =
                mds_accessory::vac::load_file(&path).map_or(Source::Missing, Source::Accessory);
            let added =
                host.add_with_shared(&gpu, &a.path.text, source, 1.0, beside(&path), shared_toon);
            log.extend(added.err());
        }
        Ok(Runtime {
            gpu,
            vk,
            host,
            shared: device.is_some(),
        })
    }
}

/// `DlgDisassembleNormalizeLineEnds`: every `\n`, `\r` or `\r\n` ends a line with `\r\n`, NULs
/// drop, and a last line without a break gets one.
fn crlf(text: &str) -> String {
    let mut out = String::with_capacity(text.len() + text.len() / 16);
    let mut chars = text.chars().peekable();
    let mut line = String::new();
    while let Some(c) = chars.next() {
        match c {
            '\n' | '\r' => {
                out.push_str(&line);
                out.push_str("\r\n");
                line.clear();
                if c == '\r' && chars.peek() == Some(&'\n') {
                    chars.next();
                }
            }
            '\0' => {}
            c => line.push(c),
        }
    }
    if !line.is_empty() {
        out.push_str(&line);
        out.push_str("\r\n");
    }
    out
}

fn key(l: &Live) -> (bool, i32, String) {
    (l.model, l.slot, l.path.clone())
}

/// A reader of the texture names a file at `file` stores (relative to its folder, `\` or `/`).
fn beside(file: &Path) -> impl FnMut(&str) -> Option<Vec<u8>> + '_ {
    let folder = file.parent().unwrap_or(Path::new("."));
    move |name| std::fs::read(effect_file(folder, name)).ok()
}

/// Shared toon files are application data, independently of the object's folder.
fn shared_toon(name: &str) -> Option<Vec<u8>> {
    std::fs::read(Path::new("data").join(name)).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn effect_paths_and_texture_reader_match_windows_case() {
        let dir = std::env::temp_dir().join(format!("mds-mme-paths-{}", std::process::id()));
        let materials = dir.join("Materials");
        std::fs::create_dir_all(&materials).unwrap();
        let effect = materials.join("Material_2.0.fx");
        std::fs::write(&effect, b"effect").unwrap();
        let texture = materials.join("Diffuse.PNG");
        std::fs::write(&texture, b"texture").unwrap();
        let model = materials.join("material_2.0.pmx");
        std::fs::write(&model, b"").unwrap();
        let fixture = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../tests/fixtures/rust/mmegold/control.pmm");
        let mut doc = Document::load(&std::fs::read(fixture).unwrap(), |_| None).unwrap();
        doc.pmm.models[0].path.text = model.to_string_lossy().into_owned();
        let mme = Mme::autoload(&doc, None);
        assert!(!mme.assignments[0].effect.is_empty());
        assert_eq!(
            effect_file(Path::new(""), &mme.assignments[0].effect),
            effect
        );

        assert_eq!(effect_file(&dir, "Materials/Material_2.0.fx"), effect);
        assert_eq!(effect_file(&dir, "materials\\material_2.0.FX"), effect);
        assert_eq!(
            effect_file(&dir, "materials/../MATERIALS/material_2.0.fx"),
            effect
        );
        let absolute = dir.join("materials/material_2.0.FX");
        assert_eq!(
            effect_file(Path::new("unused"), absolute.to_str().unwrap()),
            effect
        );
        assert_eq!(
            beside(&effect)("..\\materials\\diffuse.png"),
            Some(b"texture".to_vec())
        );
        assert_eq!(beside(&effect)("missing.png"), None);
        assert_eq!(
            effect_file(&dir, "missing\\effect.fx"),
            dir.join("missing/effect.fx")
        );
        assert_eq!(
            effect_file(&dir, "C:\\missing\\effect.fx"),
            PathBuf::from("C:/missing/effect.fx")
        );
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn effect_paths_prefer_exact_case_then_deterministic_fallback() {
        let dir = std::env::temp_dir().join(format!("mds-mme-path-case-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        for name in ["Effect.fx", "effect.fx"] {
            std::fs::write(dir.join(name), name).unwrap();
        }
        assert_eq!(effect_file(&dir, "effect.fx"), dir.join("effect.fx"));
        assert_eq!(effect_file(&dir, "EFFECT.FX"), dir.join("Effect.fx"));
        std::fs::remove_dir_all(dir).unwrap();
    }
}
