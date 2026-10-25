//! The scene the window and the frame dump draw: a PMM opened read-only, its models, and the
//! `mds-physics` world stepped to the current frame.
//!
//! The physics moves the way `--mds-frame-dump` moves it (`src/tools/trace_mode.cpp`,
//! `RunFrameDump`): the PMM load, then one frame-step pass (`PlaybackCatchup` + `PhysicsFrame` at
//! 30 fps) per frame. A seek forward steps; a seek back loads again and steps from frame 0, because
//! `mds-physics` has no seek. The C++ application seeks the keys instead and lets the live world
//! settle (`StopPlayback` in `src/app/playback_state.cpp` sets `PhysicsResetPending`).
//!
//! Model files: the path the PMM stores when that file exists, else the file of the same name in
//! the PMM's folder.

use mds_formats::pmm::Pmm;
use mds_formats::{pmd::Pmd, pmx::Pmx};
use mds_physics::PhysicsScene;
use mds_render::{scene, Camera, Frame, Gpu, Mesh, PIXEL_OFFSET_D3D9};
use std::path::{Path, PathBuf};

/// The background of the C++ application without `Data\color.txt` (white, as the golden images
/// show it).
const BACKGROUND: [u8; 4] = [255; 4];

pub struct Viewer {
    pub pmm: Pmm,
    dir: PathBuf,
    /// One per PMM model, in PMM order.
    meshes: Vec<Mesh>,
    physics: PhysicsScene,
    frame: u32,
}

fn read_model(dir: &Path, stored: &str) -> Result<Vec<u8>, String> {
    let direct = Path::new(stored);
    if direct.is_file() {
        return std::fs::read(direct).map_err(|e| format!("{stored}: {e}"));
    }
    let name = stored.rsplit(['\\', '/']).next().unwrap_or(stored);
    std::fs::read(dir.join(name)).map_err(|e| format!("{stored}: {e}"))
}

impl Viewer {
    pub fn open(path: &Path) -> Result<Viewer, String> {
        let data = std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
        let pmm = mds_scene::load_scene(&data).map_err(|e| format!("{}: {e}", path.display()))?;
        let dir = path.parent().unwrap_or(Path::new(".")).to_path_buf();
        let meshes = pmm
            .models
            .iter()
            .map(|m| {
                let stored = m.path.text.as_str();
                let data = read_model(&dir, stored)?;
                if stored.to_ascii_lowercase().ends_with(".pmd") {
                    Mesh::from_pmd(&Pmd::read(&data).map_err(|e| format!("{stored}: {e}"))?)
                } else {
                    Mesh::from_pmx(&Pmx::read(&data).map_err(|e| format!("{stored}: {e}"))?)
                }
            })
            .collect::<Result<Vec<_>, String>>()?;
        let physics = PhysicsScene::new(&pmm, |p| read_model(&dir, p))?;
        Ok(Viewer {
            pmm,
            dir,
            meshes,
            physics,
            frame: 0,
        })
    }

    pub fn frame(&self) -> u32 {
        self.frame
    }

    /// One frame-step pass: the pose of the next frame.
    pub fn step(&mut self) -> Result<(), String> {
        self.physics
            .step()
            .map_err(|e| format!("frame {}: {e}", self.frame + 1))?;
        self.frame += 1;
        Ok(())
    }

    pub fn seek(&mut self, frame: u32) -> Result<(), String> {
        if frame < self.frame {
            self.physics = PhysicsScene::new(&self.pmm, |p| read_model(&self.dir, p))?;
            self.frame = 0;
        }
        while self.frame < frame {
            self.step()?;
        }
        Ok(())
    }

    /// The camera of the PMM camera track at the current frame.
    pub fn track_camera(&self) -> Result<Camera, String> {
        scene::camera_at(&self.pmm, self.frame)
            .ok_or_else(|| format!("camera track at frame {}", self.frame))
    }

    /// Draws the current frame from `camera`; `samples` as [`Frame::samples`].
    pub fn render(
        &self,
        gpu: &Gpu,
        width: u32,
        height: u32,
        camera: &Camera,
        samples: &[[f32; 2]],
    ) -> Result<Vec<u8>, String> {
        let poses: Vec<_> = self
            .pmm
            .models
            .iter()
            .map(|m| {
                let model = self.physics.scene.models.iter().find(|s| s.slot == m.slot);
                model.map(scene::pose_of).ok_or("model slot lost")
            })
            .collect::<Result<_, _>>()?;
        let models: Vec<_> = self
            .meshes
            .iter()
            .zip(&poses)
            .map(|(m, p)| (m, Some(p)))
            .collect();
        let light = scene::light_at(&self.pmm, self.frame)
            .ok_or_else(|| format!("light track at frame {}", self.frame))?;
        mds_render::render_frame(
            gpu,
            &Frame {
                width,
                height,
                view: camera.view(width, height),
                light,
                background: BACKGROUND,
                toon: scene::self_shadow_mode_2_at(&self.pmm, self.frame),
                models: &models,
                samples,
                pixel_offset: PIXEL_OFFSET_D3D9,
            },
        )
    }
}
