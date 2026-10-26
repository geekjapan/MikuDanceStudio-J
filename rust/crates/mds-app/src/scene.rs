//! What the frame dump and the window derive from the document to draw it: the meshes of the
//! model and accessory files with their textures, the background picture ([`Assets`]), and the
//! [`Frame`] and [`Stage`] of one physics state from one camera.
//!
//! Files: the path the PMM stores when that file exists, else the file of the same name in the
//! PMM's folder ([`resolve`]). Textures resolve against the folder of the model or accessory
//! file that names them.

use mds_doc::{Document, ModelFile};
use mds_physics::PhysicsScene;
use mds_render::picture::PictureQuad;
use mds_render::{
    scene, AccessoryDraw, AccessoryMesh, Camera, Frame, Image, Light, Mesh, Picture, Stage,
    PIXEL_OFFSET_D3D9,
};
use std::path::{Path, PathBuf};
use std::sync::Arc;

/// The background of the C++ application without `Data\color.txt` (white, as the golden images
/// show it).
pub const BACKGROUND: [u8; 4] = [255; 4];

/// Where a path as the PMM stores it is on disk: the stored path when it exists (with `\` as the
/// separator of the system), else the file of that name in `dir`.
pub fn resolve(dir: &Path, stored: &str) -> PathBuf {
    // A path stored with `\` separators names the same file on a system with `/` ones.
    let native = stored.replace('\\', std::path::MAIN_SEPARATOR_STR);
    if let Some(direct) = [stored, &native]
        .map(Path::new)
        .into_iter()
        .find(|p| p.is_file())
    {
        return direct.to_path_buf();
    }
    dir.join(stored.rsplit(['\\', '/']).next().unwrap_or(stored))
}

/// The bytes of a model path as the PMM stores it.
pub fn read_model(dir: &Path, stored: &str) -> Result<Vec<u8>, String> {
    std::fs::read(resolve(dir, stored)).map_err(|e| format!("{stored}: {e}"))
}

/// A reader of the texture names a file at `file` stores (relative to its folder, `\` or `/`).
fn beside(file: &Path) -> impl Fn(&str) -> Option<Vec<u8>> + '_ {
    let folder = file.parent().unwrap_or(Path::new("."));
    move |name| std::fs::read(folder.join(name.replace('\\', "/"))).ok()
}

/// One mesh per document model, in PMM order, with its textures and edge scale.
pub fn meshes(doc: &Document, dir: &Path) -> Result<Vec<Mesh>, String> {
    doc.models
        .iter()
        .zip(&doc.pmm.models)
        .map(|(file, m)| {
            let mut mesh = match file {
                ModelFile::Pmx(pmx) => Mesh::from_pmx(pmx),
                ModelFile::Pmd(pmd) => Mesh::from_pmd(pmd),
                ModelFile::Missing => Err(format!("{}: model file not found", m.path.text)),
            }?;
            mesh.load_textures(beside(&resolve(dir, &m.path.text)));
            mesh.set_edge_scale(m.edge_scale);
            Ok(mesh)
        })
        .collect()
}

/// What a document draws that its files hold: the model meshes, the accessory meshes and the
/// background picture.
pub struct Assets {
    /// One per `pmm.models` entry.
    pub meshes: Vec<Mesh>,
    /// One per `pmm.accessories` entry; `None` for a file that does not load (the C++ loader
    /// drops it and draws nothing).
    pub accessories: Vec<Option<AccessoryMesh>>,
    /// The picture of `pmm.picture` when it is enabled and decodes.
    pub picture: Option<Arc<Image>>,
}

impl Assets {
    pub fn load(doc: &Document, dir: &Path) -> Result<Assets, String> {
        Ok(Assets {
            meshes: meshes(doc, dir)?,
            accessories: Assets::load_accessories(doc, dir),
            picture: picture(doc, dir),
        })
    }

    pub fn load_accessories(doc: &Document, dir: &Path) -> Vec<Option<AccessoryMesh>> {
        let a = &doc.pmm.accessories;
        a.iter().map(|a| accessory(dir, &a.path.text)).collect()
    }

    /// The textures, sphere maps and toons of every model and accessory read again from their
    /// files, as menu 278 does (`ReloadTextureCache`, `src/window/enhance_model_io.cpp:779`, after
    /// `InitToonTextures`, `src/render/toon_textures.cpp:62`). Returns the files found that did
    /// not decode; the C++ keeps no texture for them either.
    pub fn reload_textures(&mut self, doc: &Document, dir: &Path) -> Vec<(String, String)> {
        let mut errors = Vec::new();
        for (mesh, m) in self.meshes.iter_mut().zip(&doc.pmm.models) {
            errors.extend(mesh.load_textures(beside(&resolve(dir, &m.path.text))));
        }
        for (mesh, a) in self.accessories.iter_mut().zip(&doc.pmm.accessories) {
            if let Some(mesh) = mesh {
                errors.extend(mesh.load_textures(beside(&resolve(dir, &a.path.text))));
            }
        }
        errors
    }

    /// The model edge scales again from the document (`Command::SetEdgeScale`).
    pub fn set_edge_scales(&mut self, doc: &Document) {
        for (mesh, m) in self.meshes.iter_mut().zip(&doc.pmm.models) {
            mesh.set_edge_scale(m.edge_scale);
        }
    }
}

/// `LoadAccessoryFile` of a stored path (`.vac` or `.x`), with its textures.
pub fn accessory(dir: &Path, stored: &str) -> Option<AccessoryMesh> {
    let path = resolve(dir, stored);
    let acc = mds_accessory::vac::load_file(&path).ok()?;
    let mut mesh = AccessoryMesh::new(acc);
    mesh.load_textures(beside(&path));
    Some(mesh)
}

/// The background picture of `pmm.picture` when it is enabled and decodes.
pub fn picture(doc: &Document, dir: &Path) -> Option<Arc<Image>> {
    let p = &doc.pmm.picture;
    if p.enabled == 0 {
        return None;
    }
    let data = std::fs::read(resolve(dir, &p.path.text)).ok()?;
    Image::decode(&data).ok().map(Arc::new)
}

/// What one frame is drawn from besides the document and its assets.
pub struct Shot<'a> {
    pub physics: &'a PhysicsScene,
    /// The timeline frame (the light, self-shadow and accessory tracks are read at it).
    pub frame: u32,
    pub camera: &'a Camera,
    pub size: [u32; 2],
    /// As [`Frame::samples`].
    pub samples: &'a [[f32; 2]],
    /// The viewport `[left, top, right, bottom]` the background picture is placed in
    /// ([`PictureQuad::in_viewport`]), in output pixels; `None` is the whole output.
    pub picture_viewport: Option<[f32; 4]>,
}

/// Calls `draw` with the frame and the stage of `shot`: the models in `physics`' pose, the PMM's
/// light, self-shadow and ground shadow at the frame, its accessories and its background picture.
pub fn with_stage<R>(
    doc: &Document,
    assets: &Assets,
    shot: &Shot,
    draw: impl FnOnce(&Frame, &Stage) -> R,
) -> Result<R, String> {
    let light = scene::light_at(&doc.pmm, shot.frame)
        .ok_or_else(|| format!("light track at frame {}", shot.frame))?;
    with_stage_lit(doc, assets, shot, light, draw)
}

/// [`with_stage`] in `light`.
pub fn with_stage_lit<R>(
    doc: &Document,
    assets: &Assets,
    shot: &Shot,
    light: Light,
    draw: impl FnOnce(&Frame, &Stage) -> R,
) -> Result<R, String> {
    let pmm = &doc.pmm;
    let models = &shot.physics.scene.models;
    let poses: Vec<_> = pmm
        .models
        .iter()
        .map(|m| {
            let model = models.iter().find(|s| s.slot == m.slot);
            model.map(scene::pose_of).ok_or("model slot lost")
        })
        .collect::<Result<_, _>>()?;
    let drawn: Vec<_> = assets
        .meshes
        .iter()
        .zip(&poses)
        .map(|(m, p)| (m, Some(p)))
        .collect();
    let states: Vec<_> = pmm
        .accessories
        .iter()
        .zip(&assets.accessories)
        .filter_map(|(a, mesh)| Some((mesh.as_ref()?, scene::accessory_at(a, shot.frame, models)?)))
        .collect();
    let accessories: Vec<_> = states
        .iter()
        .map(|(mesh, (state, world))| AccessoryDraw {
            mesh,
            state,
            world: *world,
        })
        .collect();
    let [width, height] = shot.size;
    let picture = assets.picture.as_ref().map(|image| {
        let viewport = shot
            .picture_viewport
            .unwrap_or([0.0, 0.0, width as f32, height as f32]);
        let p = &pmm.picture;
        let quad = PictureQuad::in_viewport(
            image.width,
            image.height,
            p.scale,
            p.offset,
            viewport,
            pmm.settings.render_width as u32,
        );
        Picture {
            image,
            rect: quad.rect,
        }
    });
    let stage = Stage {
        accessories: &accessories,
        picture,
        ..scene::stage_at(pmm, shot.frame)
    };
    let frame = Frame {
        width,
        height,
        view: view(doc, shot.camera, shot.size),
        light,
        background: BACKGROUND,
        toon: true,
        models: &drawn,
        samples: shot.samples,
        pixel_offset: PIXEL_OFFSET_D3D9,
    };
    Ok(draw(&frame, &stage))
}

/// The camera of the PMM camera track at `frame`.
pub fn track_camera(doc: &Document, frame: u32) -> Result<Camera, String> {
    scene::camera_at(&doc.pmm, frame).ok_or_else(|| format!("camera track at frame {frame}"))
}

/// The camera the C++ draws from: the state at app+0x310 that the camera panel edits and a seek
/// or the playback copies from the track (`CopyCameraTerminal`, `src/app/playback_state.cpp`).
/// `cameraPerspective != 0` is the orthographic projection (`src/render/debug_geometry.cpp:550`).
pub fn state_camera(doc: &Document) -> Camera {
    let p = &doc.pmm;
    let s = &p.camera_state;
    Camera {
        target: [s[0], s[1], s[2]],
        rotation: [s[6], s[7], s[8]],
        distance: s[5],
        fov_deg: p.settings.camera_fov,
        orthographic: p.camera_perspective != 0,
    }
}

/// The view offsets belong to the model view, separate from its reference point.
pub fn view(doc: &Document, camera: &Camera, [width, height]: [u32; 2]) -> mds_render::View {
    let p = &doc.pmm;
    let offset = if p.settings.options[0] == 0 && p.appearance.follow_camera == 0 {
        [p.camera_state[3], p.camera_state[4]]
    } else {
        [0.0; 2]
    };
    camera.view_with_offset(offset, width, height)
}
