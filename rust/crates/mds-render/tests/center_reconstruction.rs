mod common;

const SHADER: &str = include_str!("../src/shader.wgsl");
const ATTR: [[f64; 3]; 3] = [[0.2, 0.4, 0.6], [1.8, -0.6, 2.5], [-0.8, 1.5, -1.2]];
const TOLERANCE: f64 = 0.00005;

fn helper(name: &str) -> &str {
    let start = SHADER.find(&format!("fn {name}(")).expect("actual helper");
    let end = SHADER[start..].find("\n}").expect("helper end") + start + 2;
    &SHADER[start..end]
}

fn reference(x: f64, y: f64, w: [f64; 3]) -> [f64; 3] {
    let b = [
        1.0 - (x + 2.0) / 16.0 - (y + 2.0) / 16.0,
        (x + 2.0) / 16.0,
        (y + 2.0) / 16.0,
    ];
    let d: f64 = (0..3).map(|i| b[i] / w[i]).sum();
    assert!(d.is_finite() && d > 0.0);
    std::array::from_fn(|c| (0..3).map(|i| b[i] * ATTR[i][c] / w[i]).sum::<f64>() / d)
}

fn old_predictions(w: [f64; 3], offset: [f64; 2]) -> Vec<[f64; 3]> {
    let a = reference(3.5, 3.5, w);
    // Ordinary derivatives may select either row/column of the 2x2 quad.
    [2.5, 3.5]
        .into_iter()
        .flat_map(|y| {
            [2.5, 3.5].into_iter().map(move |x| {
                let (l, r) = (reference(2.5, y, w), reference(3.5, y, w));
                let (t, b) = (reference(x, 2.5, w), reference(x, 3.5, w));
                std::array::from_fn(|c| {
                    a[c] - (r[c] - l[c]) * offset[0] - (b[c] - t[c]) * offset[1]
                })
            })
        })
        .collect()
}

fn distance(a: [f64; 3], b: [f64; 3], channels: usize) -> f64 {
    (0..channels)
        .map(|c| (a[c] - b[c]).abs())
        .fold(0.0, f64::max)
}

fn render(gpu: &mds_render::Gpu, name: &str, w: [f64; 3], offset: [f64; 2]) -> [f64; 3] {
    let actual = helper(name);
    let call = if actual.contains("q: f32") {
        format!(
            "{name}(i.a{}, i.p.w)",
            if name == "center_uv" { ".xy" } else { "" }
        )
    } else {
        format!(
            "{name}(i.a{})",
            if name == "center_uv" { ".xy" } else { "" }
        )
    };
    let result = if name == "center_uv" {
        format!("vec4<f32>({call}, 0.0, 1.0)")
    } else {
        format!("vec4<f32>({call}, 1.0)")
    };
    let source = format!(
        r#"
struct Scene {{ ground_shadow_plane: vec4<f32> }}
const scene = Scene(vec4<f32>(0.0, {ox}, {oy}, 0.0));
{actual}
struct Out {{ @builtin(position) p: vec4<f32>, @location(0) a: vec3<f32> }}
@vertex fn vs(@builtin(vertex_index) k: u32) -> Out {{
    let xy = array<vec2<f32>,3>(vec2<f32>(-2.0,-2.0), vec2<f32>(14.0,-2.0), vec2<f32>(-2.0,14.0))[k];
    let w = array<f32,3>({w0}, {w1}, {w2})[k];
    let a = array<vec3<f32>,3>(vec3<f32>(0.2,0.4,0.6), vec3<f32>(1.8,-0.6,2.5), vec3<f32>(-0.8,1.5,-1.2))[k];
    return Out(vec4<f32>((xy.x / 4.0 - 1.0) * w, (1.0 - xy.y / 4.0) * w, 0.5 * w, w), a);
}}
@fragment fn fs(i: Out) -> @location(0) vec4<f32> {{ return {result}; }}
"#,
        ox = offset[0],
        oy = offset[1],
        w0 = w[0],
        w1 = w[1],
        w2 = w[2]
    );
    let device = gpu.device();
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("actual center helper calibration"),
        source: wgpu::ShaderSource::Wgsl(source.into()),
    });
    let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("center calibration"),
        layout: None,
        vertex: wgpu::VertexState {
            module: &shader,
            entry_point: Some("vs"),
            compilation_options: Default::default(),
            buffers: &[],
        },
        primitive: Default::default(),
        depth_stencil: None,
        multisample: Default::default(),
        fragment: Some(wgpu::FragmentState {
            module: &shader,
            entry_point: Some("fs"),
            compilation_options: Default::default(),
            targets: &[Some(wgpu::ColorTargetState {
                format: wgpu::TextureFormat::Rgba32Float,
                blend: None,
                write_mask: wgpu::ColorWrites::ALL,
            })],
        }),
        multiview_mask: None,
        cache: None,
    });
    let size = wgpu::Extent3d {
        width: 8,
        height: 8,
        depth_or_array_layers: 1,
    };
    let target = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("float calibration"),
        size,
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: wgpu::TextureFormat::Rgba32Float,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
        view_formats: &[],
    });
    let view = target.create_view(&Default::default());
    let buffer = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("float readback"),
        size: 256 * 8,
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    let mut encoder = device.create_command_encoder(&Default::default());
    {
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("calibration triangle"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: &view,
                depth_slice: None,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT),
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: None,
            timestamp_writes: None,
            occlusion_query_set: None,
            multiview_mask: None,
        });
        pass.set_pipeline(&pipeline);
        pass.draw(0..3, 0..1);
    }
    encoder.copy_texture_to_buffer(
        target.as_image_copy(),
        wgpu::TexelCopyBufferInfo {
            buffer: &buffer,
            layout: wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(256),
                rows_per_image: Some(8),
            },
        },
        size,
    );
    gpu.queue().submit([encoder.finish()]);
    let slice = buffer.slice(..);
    let (tx, rx) = std::sync::mpsc::channel();
    slice.map_async(wgpu::MapMode::Read, move |r| {
        tx.send(r).unwrap();
    });
    device.poll(wgpu::PollType::wait_indefinitely()).unwrap();
    rx.recv().unwrap().unwrap();
    let mapped = slice.get_mapped_range().unwrap();
    let at = 3 * 256 + 3 * 16;
    let result = std::array::from_fn(|c| {
        f32::from_le_bytes(mapped[at + c * 4..at + c * 4 + 4].try_into().unwrap()) as f64
    });
    assert_eq!(
        f32::from_le_bytes(mapped[at + 12..at + 16].try_into().unwrap()),
        1.0,
        "triangle covers measurement"
    );
    result
}

#[test]
#[ignore = "real GPU diagnostic calibration; run separately from golden2"]
fn calibrate_actual_center_helpers() {
    let gpu = common::gpu_or_skip().expect("calibration requires a real adapter");
    let candidate = helper("center_uv").contains("q: f32");
    let cases = [
        ("constant_zero", [1.0; 3], [0.0, 0.0]),
        ("constant_positive", [1.0; 3], [0.375, 0.25]),
        ("constant_negative", [1.0; 3], [-0.375, -0.25]),
        ("varying_zero", [1.0, 2.0, 4.0], [0.0, 0.0]),
        ("varying_positive", [1.0, 2.0, 4.0], [0.375, 0.25]),
        ("varying_negative", [1.0, 2.0, 4.0], [-0.375, -0.25]),
        ("varying_mixed", [1.0, 2.0, 4.0], [0.375, -0.25]),
        ("valid_extrapolation", [1.0, 2.0, 4.0], [8.0, 0.0]),
    ];
    for name in ["center_uv", "center_world", "center_value"] {
        let channels = if name == "center_uv" { 2 } else { 3 };
        for (case, w, offset) in cases {
            let actual = render(&gpu, name, w, offset);
            assert!(actual.iter().all(|v| v.is_finite()));
            let expected = reference(3.5 - offset[0], 3.5 - offset[1], w);
            let old = old_predictions(w, offset);
            let new_error = distance(actual, expected, channels);
            let old_error = old
                .iter()
                .map(|&p| distance(actual, p, channels))
                .fold(f64::INFINITY, f64::min);
            let separation = old
                .iter()
                .map(|&p| distance(expected, p, channels))
                .fold(f64::INFINITY, f64::min);
            eprintln!("CENTER_CAL {{\"helper\":\"{name}\",\"case\":\"{case}\",\"actual\":{actual:?},\"reference\":{expected:?},\"new_error\":{new_error},\"old_error\":{old_error},\"separation\":{separation},\"tolerance\":{TOLERANCE},\"candidate\":{candidate}}}");
            assert!(
                if candidate { new_error } else { old_error } <= TOLERANCE,
                "actual helper disagrees with its mathematical model"
            );
            if case == "valid_extrapolation" {
                assert!(
                    separation > 100.0 * TOLERANCE,
                    "analytical discriminator must separate old and new"
                );
            }
        }
    }
}
