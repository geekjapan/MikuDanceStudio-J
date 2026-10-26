//! The persistent path (`Renderer`) against `render_frame`: the same pixels, no pipeline rebuilt
//! on later frames, buffers refreshed for a new pose, and multisampling into a caller's texture.
//! With no adapter, every test reports SKIP, which is not a pass.

use mds_formats::pmx::Pmx;
use mds_render::{Camera, Frame, Gpu, Light, Mesh, Pose, Renderer, PIXEL_OFFSET_D3D9};

const W: u32 = 128;
const H: u32 = 96;
const BACKGROUND: [u8; 4] = [209, 219, 230, 255];

fn gpu_or_skip() -> Option<Gpu> {
    let gpu = Gpu::new().expect("device");
    if gpu.is_none() {
        eprintln!("SKIP: no wgpu adapter on this host (not a pass)");
    }
    gpu
}

fn morph4() -> Mesh {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../../tests/fixtures/rust/morph4.pmx");
    Mesh::from_pmx(&Pmx::read(&std::fs::read(path).unwrap()).unwrap()).unwrap()
}

fn morph_pose(mesh_morphs: usize, weight: f32) -> Pose {
    Pose {
        morphs: vec![weight; mesh_morphs],
        ..Pose::default()
    }
}

fn frame<'a>(models: &'a [(&'a Mesh, Option<&'a Pose>)]) -> Frame<'a> {
    let camera = Camera {
        target: [0.0, 0.5, 0.0],
        rotation: [0.0, std::f32::consts::PI, 0.0],
        distance: -3.0,
        fov_deg: 30.0,
        orthographic: false,
    };
    Frame {
        width: W,
        height: H,
        view: camera.view(W, H),
        light: Light {
            color: [0.6; 3],
            direction: [-0.5, -1.0, 0.5],
        },
        background: BACKGROUND,
        toon: true,
        models,
        samples: &[[0.0, 0.0]],
        pixel_offset: PIXEL_OFFSET_D3D9,
    }
}

fn target(device: &wgpu::Device) -> wgpu::Texture {
    device.create_texture(&wgpu::TextureDescriptor {
        label: Some("test target"),
        size: wgpu::Extent3d {
            width: W,
            height: H,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: wgpu::TextureFormat::Rgba8Unorm,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
        view_formats: &[],
    })
}

fn read(gpu: &Gpu, texture: &wgpu::Texture) -> Vec<u8> {
    let (device, queue) = (gpu.device(), gpu.queue());
    let padded = (W * 4).next_multiple_of(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT);
    let buf = device.create_buffer(&wgpu::BufferDescriptor {
        label: None,
        size: u64::from(padded * H),
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    let mut encoder = device.create_command_encoder(&Default::default());
    encoder.copy_texture_to_buffer(
        texture.as_image_copy(),
        wgpu::TexelCopyBufferInfo {
            buffer: &buf,
            layout: wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(padded),
                rows_per_image: Some(H),
            },
        },
        texture.size(),
    );
    queue.submit([encoder.finish()]);
    buf.slice(..).map_async(wgpu::MapMode::Read, |r| r.unwrap());
    device.poll(wgpu::PollType::wait_indefinitely()).unwrap();
    let mapped = buf.slice(..).get_mapped_range().unwrap();
    mapped
        .chunks(padded as usize)
        .take(H as usize)
        .flat_map(|row| row[..(W * 4) as usize].iter().copied())
        .collect()
}

fn covered(px: &[u8]) -> usize {
    px.chunks(4).filter(|p| *p != BACKGROUND).count()
}

fn render_into(gpu: &Gpu, renderer: &mut Renderer, f: &Frame, samples: u32) -> Vec<u8> {
    let texture = target(gpu.device());
    let view = texture.create_view(&Default::default());
    renderer.render_into(&view, f, samples).unwrap();
    read(gpu, &texture)
}

#[test]
fn render_into_equals_render_frame_and_keeps_its_pipelines() {
    let Some(gpu) = gpu_or_skip() else { return };
    let mesh = morph4();
    let rest = morph_pose(0, 0.0);
    let bent = morph_pose(4, 1.0);
    let mut renderer = Renderer::new(gpu.device(), gpu.queue()).unwrap();
    assert_eq!(renderer.pipelines_created(), 0);

    let models_a = [(&mesh, Some(&rest))];
    let frame_a = frame(&models_a);
    let a1 = render_into(&gpu, &mut renderer, &frame_a, 1);
    let built = renderer.pipelines_created();
    assert_eq!(built, 7);
    assert!(covered(&a1) > 100, "the model should cover some pixels");
    assert_eq!(a1, gpu_frame(&gpu, &frame_a), "render_into vs render_frame");

    let a2 = render_into(&gpu, &mut renderer, &frame_a, 1);
    assert_eq!(a1, a2, "the same frame twice");

    // A new pose must reach the persistent buffers.
    let models_b = [(&mesh, Some(&bent))];
    let frame_b = frame(&models_b);
    let b = render_into(&gpu, &mut renderer, &frame_b, 1);
    assert_ne!(a1, b, "the morph moves the model");
    assert_eq!(b, gpu_frame(&gpu, &frame_b));
    assert_eq!(render_into(&gpu, &mut renderer, &frame_a, 1), a1);

    assert_eq!(renderer.pipelines_created(), built, "no pipeline rebuilt");
    eprintln!(
        "pipelines after four frames: {}",
        renderer.pipelines_created()
    );
}

fn gpu_frame(gpu: &Gpu, f: &Frame) -> Vec<u8> {
    mds_render::render_frame(gpu, f).unwrap()
}

#[test]
fn render_frame_on_gpu_reuses_pipelines() {
    let Some(gpu) = gpu_or_skip() else { return };
    let mesh = morph4();
    let models = [(&mesh, None)];
    let f = frame(&models);
    let first = gpu_frame(&gpu, &f);
    let built = gpu.pipelines_created();
    assert_eq!(built, 7);
    assert_eq!(gpu_frame(&gpu, &f), first);
    assert_eq!(gpu.pipelines_created(), built);
}

#[test]
fn one_mesh_listed_twice_keeps_two_poses() {
    let Some(gpu) = gpu_or_skip() else { return };
    let mesh = morph4();
    let (rest, bent) = (morph_pose(0, 0.0), morph_pose(4, 1.0));
    let mut renderer = Renderer::new(gpu.device(), gpu.queue()).unwrap();
    let mut draw = |a: &Pose, b: &Pose| {
        let models = [(&mesh, Some(a)), (&mesh, Some(b))];
        render_into(&gpu, &mut renderer, &frame(&models), 1)
    };
    let mixed = draw(&rest, &bent);
    assert_ne!(mixed, draw(&rest, &rest));
    assert_ne!(mixed, draw(&bent, &bent));
}

#[test]
fn multisampled_render_resolves_into_the_target() {
    let Some(gpu) = gpu_or_skip() else { return };
    let mesh = morph4();
    let models = [(&mesh, None)];
    let f = frame(&models);
    let mut renderer = Renderer::new(gpu.device(), gpu.queue()).unwrap();
    let px = render_into(&gpu, &mut renderer, &f, 4);
    assert!(covered(&px) > 100);
    assert_eq!(renderer.pipelines_created(), 7);
    render_into(&gpu, &mut renderer, &f, 1);
    assert_eq!(renderer.pipelines_created(), 14, "one set per sample count");
    render_into(&gpu, &mut renderer, &f, 4);
    assert_eq!(renderer.pipelines_created(), 14);
    assert!(renderer
        .render_into(
            &target(gpu.device()).create_view(&Default::default()),
            &f,
            3
        )
        .is_err());
}
