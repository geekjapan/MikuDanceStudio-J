//! What the frame dump and the window derive from the document to draw it: the meshes of the
//! model files, and the [`Frame`] of one physics state from one camera.
//!
//! Model files: the path the PMM stores when that file exists, else the file of the same name in
//! the PMM's folder.

use mds_doc::{Document, ModelFile};
use mds_physics::PhysicsScene;
use mds_render::{scene, Camera, Frame, Mesh, PIXEL_OFFSET_D3D9};
use std::path::Path;

/// The background of the C++ application without `Data\color.txt` (white, as the golden images
/// show it).
pub const BACKGROUND: [u8; 4] = [255; 4];

/// The bytes of a model path as the PMM stores it.
pub fn read_model(dir: &Path, stored: &str) -> Result<Vec<u8>, String> {
    let direct = Path::new(stored);
    if direct.is_file() {
        return std::fs::read(direct).map_err(|e| format!("{stored}: {e}"));
    }
    let name = stored.rsplit(['\\', '/']).next().unwrap_or(stored);
    std::fs::read(dir.join(name)).map_err(|e| format!("{stored}: {e}"))
}

/// One mesh per document model, in PMM order.
pub fn meshes(doc: &Document) -> Result<Vec<Mesh>, String> {
    doc.models
        .iter()
        .zip(&doc.pmm.models)
        .map(|(file, m)| match file {
            ModelFile::Pmx(pmx) => Mesh::from_pmx(pmx),
            ModelFile::Pmd(pmd) => Mesh::from_pmd(pmd),
            ModelFile::Missing => Err(format!("{}: model file not found", m.path.text)),
        })
        .collect()
}

/// Calls `draw` with the frame of `physics`' pose at timeline frame `frame`, from `camera`;
/// `samples` as [`Frame::samples`].
#[allow(clippy::too_many_arguments)]
pub fn with_frame<R>(
    doc: &Document,
    meshes: &[Mesh],
    physics: &PhysicsScene,
    frame: u32,
    camera: &Camera,
    size: [u32; 2],
    samples: &[[f32; 2]],
    draw: impl FnOnce(&Frame) -> R,
) -> Result<R, String> {
    let poses: Vec<_> = doc
        .pmm
        .models
        .iter()
        .map(|m| {
            let model = physics.scene.models.iter().find(|s| s.slot == m.slot);
            model.map(scene::pose_of).ok_or("model slot lost")
        })
        .collect::<Result<_, _>>()?;
    let models: Vec<_> = meshes
        .iter()
        .zip(&poses)
        .map(|(m, p)| (m, Some(p)))
        .collect();
    let light =
        scene::light_at(&doc.pmm, frame).ok_or_else(|| format!("light track at frame {frame}"))?;
    let [width, height] = size;
    Ok(draw(&Frame {
        width,
        height,
        view: camera.view(width, height),
        light,
        background: BACKGROUND,
        toon: scene::self_shadow_mode_2_at(&doc.pmm, frame),
        models: &models,
        samples,
        pixel_offset: PIXEL_OFFSET_D3D9,
    }))
}

/// The camera of the PMM camera track at `frame`.
pub fn track_camera(doc: &Document, frame: u32) -> Result<Camera, String> {
    scene::camera_at(&doc.pmm, frame).ok_or_else(|| format!("camera track at frame {frame}"))
}
