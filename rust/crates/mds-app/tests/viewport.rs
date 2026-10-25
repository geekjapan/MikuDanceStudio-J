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
    for (frame, now) in [(150, 100), (40, 200), (599, 300)] {
        editor.seek(frame).unwrap();
        editor.pump(now).unwrap();
        let (texture, _, _) = viewport.draw(&editor, SIZE, 1).unwrap();
        let window = read(&gpu, texture);
        let dump = editor
            .with_stage(SIZE, &ONE, |f, s| mds_render::render_frame_with(&gpu, f, s))
            .unwrap()
            .unwrap();
        assert!(
            covered(&window) > 1000,
            "frame {frame}: the models are drawn"
        );
        assert!(window == dump, "frame {frame}: window and dump differ");
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
        let camera = scene::track_camera(&doc, frame).unwrap();
        let shot = Shot {
            physics: &physics,
            frame,
            camera: &camera,
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
