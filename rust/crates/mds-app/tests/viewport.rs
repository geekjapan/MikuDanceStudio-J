//! The window's viewport path (one `Renderer`, `render_into` a texture the app owns) against
//! the frame dump's path (`render_frame` of the same frame, read back), at one sample: the dump
//! averages the 8x pattern and the window uses hardware multisampling, so the two agree only
//! per single sample. The texture is read back here only.

use mds_app::editor::Editor;
use mds_app::scene::{self, Assets, Shot};
use mds_app::viewport::Viewport;
use mds_physics::PhysicsScene;
use mds_render::Gpu;
use std::path::PathBuf;

const SIZE: [u32; 2] = [640, 360];
const ONE: [[f32; 2]; 1] = [[0.0, 0.0]];

fn dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

fn gpu_or_skip() -> Option<Gpu> {
    let gpu = Gpu::new().expect("device");
    if gpu.is_none() {
        eprintln!("SKIP: no wgpu adapter on this host (not a pass)");
    }
    gpu
}

fn read(gpu: &Gpu, texture: &wgpu::Texture) -> Vec<u8> {
    let [w, h] = SIZE;
    let padded = (w * 4).next_multiple_of(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT);
    let buf = gpu.device().create_buffer(&wgpu::BufferDescriptor {
        label: None,
        size: u64::from(padded * h),
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    let mut encoder = gpu.device().create_command_encoder(&Default::default());
    encoder.copy_texture_to_buffer(
        texture.as_image_copy(),
        wgpu::TexelCopyBufferInfo {
            buffer: &buf,
            layout: wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(padded),
                rows_per_image: Some(h),
            },
        },
        texture.size(),
    );
    gpu.queue().submit([encoder.finish()]);
    buf.slice(..).map_async(wgpu::MapMode::Read, |r| r.unwrap());
    gpu.device()
        .poll(wgpu::PollType::wait_indefinitely())
        .unwrap();
    let mapped = buf.slice(..).get_mapped_range().unwrap();
    mapped
        .chunks(padded as usize)
        .take(h as usize)
        .flat_map(|row| row[..(w * 4) as usize].iter().copied())
        .collect()
}

fn covered(px: &[u8]) -> usize {
    px.chunks(4).filter(|p| *p != scene::BACKGROUND).count()
}

#[test]
fn the_window_draws_the_pixels_of_the_dump() {
    let Some(gpu) = gpu_or_skip() else { return };
    let mut viewport = Viewport::new(gpu.device(), gpu.queue()).unwrap();
    let mut editor = Editor::open(&dir().join("swing600-golden.pmm")).unwrap();
    editor
        .apply(mds_doc::Command::SetViewOffset([1.5, -0.75]))
        .unwrap();
    editor
        .edit_camera_controls(|c| c.rotation = [0.1, 0.2, 0.05])
        .unwrap();
    editor.seek(0).unwrap();
    editor
        .apply(mds_doc::Command::SetSelfShadow {
            mode: 2,
            distance: 0.01,
        })
        .unwrap();
    editor
        .apply(mds_doc::Command::RegisterGlobalKeys(vec![
            mds_doc::GlobalTrack::SelfShadow,
        ]))
        .unwrap();
    for (frame, now) in [(150, 100), (40, 200), (599, 300)] {
        editor.shadow_map = if frame == 40 {
            mds_render::ShadowMapSize::Texels4096
        } else {
            mds_render::ShadowMapSize::Texels2048
        };
        editor.shadow_map_display = frame == 40;
        editor.seek(frame).unwrap();
        editor.pump(now).unwrap();
        let (texture, _, _) = viewport.draw(&editor, SIZE, 1).unwrap();
        let window = read(&gpu, texture);
        let dump = editor
            .with_stage(SIZE, &ONE, |f, s| mds_render::render_frame_with(&gpu, f, s))
            .unwrap()
            .unwrap();
        assert!(
            editor.shadow_map_display || covered(&window) > 1000,
            "frame {frame}: the models are drawn"
        );
        assert!(window == dump, "frame {frame}: window and dump differ");
        if editor.shadow_map_display {
            assert!(
                window.chunks_exact(4).all(|p| p[0] == p[1] && p[1] == p[2]),
                "the displayed depth map is grayscale"
            );
            assert!(
                window.chunks_exact(4).any(|p| p[0] < 255),
                "the displayed map contains model depth"
            );
        }
        eprintln!("frame {frame}: {} px covered, identical", covered(&window));
    }
}

/// On a scene without physics the window's live world and the dump's frame-step passes reach
/// the same pose, so the window shows the dump's picture of the frame.
#[test]
fn without_physics_the_window_shows_the_dumped_frame() {
    let Some(gpu) = gpu_or_skip() else { return };
    let path = dir().join("swing600-nophys.pmm");
    let mut viewport = Viewport::new(gpu.device(), gpu.queue()).unwrap();
    let mut editor = Editor::open(&path).unwrap();
    let doc = mds_app::file::read(&path).unwrap();
    let assets = Assets::load(&doc, &dir()).unwrap();
    let mut physics = PhysicsScene::new(&doc.pmm, |p| scene::read_model(&dir(), p)).unwrap();
    let mut at = 0;
    for frame in [0, 150, 300] {
        while at < frame {
            physics.step().unwrap();
            at += 1;
        }
        editor.seek(frame).unwrap();
        editor.pump(u64::from(frame)).unwrap();
        let (texture, _, _) = viewport.draw(&editor, SIZE, 1).unwrap();
        let window = read(&gpu, texture);
        let shot = Shot {
            physics: &physics,
            frame,
            camera: editor.camera_frame(),
            view_offset: [0.0; 2],
            size: SIZE,
            samples: &ONE,
            picture_viewport: None,
        };
        let dump = scene::with_stage(&doc, &assets, &shot, |f, s| {
            mds_render::render_frame_with(&gpu, f, s)
        })
        .unwrap()
        .unwrap();
        assert!(window == dump, "frame {frame}: window and dump differ");
        eprintln!("frame {frame}: {} px covered, identical", covered(&window));
    }
}

#[test]
fn standalone_dump_ignores_model_pan_while_the_editor_draws_it() {
    let Some(gpu) = gpu_or_skip() else { return };
    let scratch = std::env::temp_dir().join(format!("mds-dump-offset-{}", std::process::id()));
    std::fs::create_dir_all(&scratch).unwrap();
    let path = scratch.join("scene.pmm");
    let mut doc = mds_app::file::read(&dir().join("swing600-nophys.pmm")).unwrap();
    doc.pmm.settings.options[0] = 0;
    doc.pmm.appearance.follow_camera = 0;
    for model in &doc.pmm.models {
        let staged = scene::resolve(&scratch, &model.path.text);
        std::fs::create_dir_all(staged.parent().unwrap()).unwrap();
        std::fs::copy(scene::resolve(&dir(), &model.path.text), staged).unwrap();
    }
    let mut dumps = Vec::new();
    for (name, offset) in [("zero", [0.0; 2]), ("pan", [2.0, -1.0])] {
        doc.pmm.camera_state[3] = offset[0];
        doc.pmm.camera_state[4] = offset[1];
        std::fs::write(&path, doc.save().unwrap()).unwrap();
        let out = scratch.join(name);
        mds_app::dump::run(
            &gpu,
            &mds_app::dump::Request {
                pmm: path.clone(),
                out: out.clone(),
                frames: vec![0],
                picture_viewport: None,
            },
        )
        .unwrap();
        dumps.push(std::fs::read(out.join("scene-0.png")).unwrap());
    }
    assert_eq!(
        dumps[0], dumps[1],
        "standalone dumping keeps the forced camera track view"
    );
    let editor = Editor::open(&path).unwrap();
    editor
        .with_stage(SIZE, &ONE, |frame, _| {
            let point = [1.0, 2.0, 3.0];
            assert_eq!(
                frame.view.clip(point),
                editor
                    .camera_frame()
                    .view_with_offset([2.0, -1.0], SIZE[0], SIZE[1])
                    .clip(point)
            );
            assert_ne!(
                frame.view.clip(point),
                editor.camera_frame().view(SIZE[0], SIZE[1]).clip(point)
            );
        })
        .unwrap();
    std::fs::remove_dir_all(&scratch).unwrap();
}
