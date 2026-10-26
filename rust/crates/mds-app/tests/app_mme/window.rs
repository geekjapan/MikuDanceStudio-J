//! `Mme::render_into`, the window's path: the MME frame drawn on the caller's device into the
//! caller's texture is the picture `Mme::render` reads back from a device of its own.

use super::{stage, vkd3d_lib};
use mds_app::editor::Editor;

const SIZE: [u32; 2] = [160, 90];

/// The pixels of an RGBA8 texture, top row first.
fn read(device: &wgpu::Device, queue: &wgpu::Queue, texture: &wgpu::Texture) -> Vec<u8> {
    let [w, h] = SIZE;
    let padded = (w * 4).next_multiple_of(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT);
    let buf = device.create_buffer(&wgpu::BufferDescriptor {
        label: None,
        size: u64::from(padded * h),
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    let mut enc = device.create_command_encoder(&Default::default());
    enc.copy_texture_to_buffer(
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
    queue.submit([enc.finish()]);
    buf.slice(..).map_async(wgpu::MapMode::Read, |r| r.unwrap());
    device.poll(wgpu::PollType::wait_indefinitely()).unwrap();
    let mapped = buf.slice(..).get_mapped_range().unwrap();
    mapped
        .chunks(padded as usize)
        .flat_map(|row| row[..(w * 4) as usize].to_vec())
        .collect()
}

#[test]
fn the_window_texture_gets_the_frame_without_a_read_back() {
    let Some(gpu) = mds_render::Gpu::new().expect("device") else {
        eprintln!("SKIP: no wgpu adapter on this host (not a pass)");
        return;
    };
    let lib = vkd3d_lib();
    if let Err(e) = mds_shader::vkd3d::Vkd3d::open(&lib) {
        eprintln!("SKIP: vkd3d-shader not loaded: {e} (not a pass)");
        return;
    }
    let dir = std::env::temp_dir().join(format!("mds-app-mme-window-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    stage("control", &dir, std::path::Path::new(""));
    let mut editor = Editor::open(&dir.join("control.pmm")).unwrap();
    editor.mme.vkd3d = Some(lib);
    let view = editor.view(0, SIZE, 0.0).unwrap();
    let read_back = editor
        .mme
        .render(&editor.doc, &editor.physics, &view)
        .unwrap();
    let (device, queue) = (gpu.device(), gpu.queue());
    let texture = device.create_texture(&wgpu::TextureDescriptor {
        label: None,
        size: wgpu::Extent3d {
            width: SIZE[0],
            height: SIZE[1],
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: wgpu::TextureFormat::Rgba8Unorm,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
        view_formats: &[],
    });
    editor
        .mme
        .render_into(device, queue, &editor.doc, &editor.physics, &view, &texture)
        .unwrap();
    let shown = read(device, queue, &texture);
    // The two models (control.fx on chain8, morph4 in the host's shading) are on the picture.
    let background = &read_back[..4];
    let drawn = read_back.chunks(4).filter(|p| p != &background).count();
    assert!(drawn > 300, "{drawn} pixels drawn");
    assert_eq!(shown, read_back);
    std::fs::remove_dir_all(&dir).unwrap();
}
