//! Offscreen wgpu rendering of PMX and PMD models with MMD-style shading.
//!
//! Three entry points:
//!
//! * [`render`] draws one PMX in bind pose from a camera that its bounding box fixes, at
//!   [`WIDTH`] x [`HEIGHT`], with no multisampling. The image-hash test records it.
//! * [`render_frame`] draws a posed scene: any number of [`Mesh`]es with a [`Pose`] each, from the
//!   PMM [`Camera`] and [`Light`] of a frame ([`scene`] reads them from a PMM), averaging
//!   several sub-pixel shifted renders the way an 8x multisample resolve averages its samples, in
//!   linear light (the golden images' resolve is gamma correct).
//! * [`Renderer`] is what both run on: it is built on the caller's wgpu device and keeps its
//!   pipelines and the buffers of the models between frames. [`Renderer::render_into`] draws into
//!   a texture of the caller's with hardware multisampling, with no read back, for a window.
//!   [`Gpu`] holds a `Renderer` on a device of its own for the two functions above.
//!
//! The `_with` variants ([`render_frame_with`], [`Renderer::render_frame_with`],
//! [`Renderer::render_into_with`]) also take a [`Stage`]: the PMM settings beyond the models
//! (self-shadow, the projected ground shadow and the accessories); [`scene::stage_at`] reads it
//! from a PMM and [`scene::accessory_at`] places an [`AccessoryMesh`].
//!
//! Shading follows MMD's standard pipeline as the golden images show it: the color is
//! `saturate(ambient + diffuse * light)` times the texture, the sphere map (multiply or add) and the
//! toon, plus a Blinn-Phong highlight `specular * light * (N.H)^power` that uses the eye position
//! (a local viewer, also under the orthographic projection). With self-shadow off the toon is the
//! toon texture looked up by the angle to the light, with the interpolated normal not
//! renormalized; with self-shadow on it is a blend toward the toon's shadow color by the angle to
//! the light (see [`SelfShadow::shades`]). A back face is lit with its normal as it is, not
//! flipped. Materials with the edge flag get an inverted-hull edge.
//! Diffuse alpha blends. The ground shadow is the model flattened along the light onto the ground,
//! blended once per pixel.
//!
//! The vertex buffers and material values of every frame are `mds-skin`'s: BDEF, SDEF and QDEF
//! skinning, vertex, UV and material morphs, and the edge hull and color the C++ computes. The edge
//! pass draws its edge buffer as it is.
//!
//! [`Mesh::load_textures`] decodes the texture, sphere and toon files a model names ([`Image`]);
//! a slot without one is drawn with its default (white, none, a built-in toon texture).
//! Accessories ([`AccessoryMesh`], from `mds-accessory`) are lit as Direct3D 9's fixed-function
//! pipeline lights them, with the accessory light ten times as bright.
//!
//! [`Stage::picture`] draws a background picture as a quad in output pixels.
//!
//! Not in this crate yet: the self-shadow map.

mod accessory;
mod mesh;
pub mod picture;
mod png;
mod renderer;
pub mod scene;
mod texture;
mod view;

pub use accessory::{AccessoryDraw, AccessoryMesh};
use mds_formats::pmx::Pmx;
pub use mesh::{Mesh, Pose};
pub use renderer::Renderer;
use std::sync::{Mutex, MutexGuard, PoisonError};
pub use texture::Image;
pub use view::{Camera, Light, View};

pub const WIDTH: u32 = 512;
pub const HEIGHT: u32 = 512;
/// Color the bind-pose target is cleared to (RGBA8).
pub const CLEAR: [u8; 4] = [209, 219, 230, 255];

const COLOR_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8Unorm;
/// The ground shadow needs a stencil. On Apple GPUs this is a 32-bit float depth, as before the
/// stencil was added.
const DEPTH_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Depth24PlusStencil8;

/// Encodes RGBA8 pixels (top row first) as a PNG.
pub use png::encode as encode_png;

// ---- gpu ----

/// A wgpu device with no window, and the [`Renderer`] that [`render`] and [`render_frame`] share.
pub struct Gpu {
    device: wgpu::Device,
    queue: wgpu::Queue,
    renderer: Mutex<Renderer>,
    /// `name|backend`, the key the hash regression test records hashes under.
    pub adapter: String,
}

impl Gpu {
    /// `Ok(None)` when the host has no adapter. `WGPU_BACKEND` overrides the backend.
    pub fn new() -> Result<Option<Gpu>, String> {
        let backends = if cfg!(target_os = "macos") {
            wgpu::Backends::METAL
        } else if cfg!(windows) {
            wgpu::Backends::DX12
        } else {
            wgpu::Backends::VULKAN
        };
        let mut desc = wgpu::InstanceDescriptor::new_without_display_handle();
        desc.backends = backends;
        let instance = wgpu::Instance::new(desc.with_env());
        let Ok(adapter) =
            pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions::default()))
        else {
            return Ok(None);
        };
        let info = adapter.get_info();
        let (device, queue) = pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor {
            label: Some("mds-render"),
            ..Default::default()
        }))
        .map_err(|e| format!("cannot create a device on {}: {e}", info.name))?;
        Ok(Some(Gpu {
            renderer: Mutex::new(Renderer::new(&device, &queue)?),
            device,
            queue,
            adapter: format!("{}|{:?}", info.name, info.backend),
        }))
    }

    pub fn device(&self) -> &wgpu::Device {
        &self.device
    }

    pub fn queue(&self) -> &wgpu::Queue {
        &self.queue
    }

    /// Pipelines the shared renderer has built so far; see [`Renderer::pipelines_created`].
    pub fn pipelines_created(&self) -> usize {
        self.renderer().pipelines_created()
    }

    fn renderer(&self) -> MutexGuard<'_, Renderer> {
        self.renderer.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// What [`render_frame`] draws.
pub struct Frame<'a> {
    pub width: u32,
    pub height: u32,
    pub view: View,
    pub light: Light,
    /// Color the target is cleared to (RGBA8).
    pub background: [u8; 4],
    /// Whether the toon applies (MMD draws every model with one). Which toon follows the
    /// [`Stage`]'s self-shadow; the entry points without a stage take it as self-shadow mode 2
    /// ([`Stage::legacy`]).
    pub toon: bool,
    /// Models in draw order, each with its pose (`None` draws the bind pose).
    pub models: &'a [(&'a Mesh, Option<&'a Pose>)],
    /// One render per entry, the content shifted by the negated offset (in pixels from the pixel
    /// center, y down), then all renders averaged. `[[0.0, 0.0]]` is a single render.
    pub samples: &'a [[f32; 2]],
    /// Shifts the whole picture by this many pixels (x right, y down); [`PIXEL_OFFSET_D3D9`] for
    /// the picture the C++ app writes.
    pub pixel_offset: [f32; 2],
}

/// What a PMM frame draws besides the models' own passes. `Stage::default()` draws none of it.
#[derive(Clone, Copy, Default)]
pub struct Stage<'a> {
    /// The projected ground shadow (the PMM view flag `ground_shadow`), or `None`.
    pub ground_shadow: Option<GroundShadow>,
    /// Self-shadow (modes 1 and 2), or `None` (mode 0).
    pub self_shadow: Option<SelfShadow>,
    /// The accessories, in draw order; [`scene::accessory_at`] places one.
    pub accessories: &'a [AccessoryDraw<'a>],
    /// The background picture, drawn behind everything.
    pub picture: Option<Picture<'a>>,
}

/// A background picture and where it goes: `rect` is left, top, right, bottom in the pixels of
/// the output with Direct3D 9's pixel centers on integer coordinates, as the C++ app's
/// pre-transformed quad has them ([`picture::PictureQuad::in_viewport`]).
#[derive(Clone, Copy)]
pub struct Picture<'a> {
    pub image: &'a std::sync::Arc<Image>,
    pub rect: [f32; 4],
}

impl Stage<'_> {
    /// What [`render_frame`], [`Renderer::render_frame`] and [`Renderer::render_into`] draw, the
    /// shading from before there was a stage: `frame.toon` is self-shadow mode 2, no ground shadow.
    pub fn legacy(frame: &Frame) -> Stage<'static> {
        Stage {
            ground_shadow: None,
            self_shadow: frame.toon.then_some(SelfShadow {
                mode: 2,
                distance: 0.0,
            }),
            accessories: &[],
            picture: None,
        }
    }
}

/// The self-shadow track of a PMM at one frame.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SelfShadow {
    /// 1 or 2.
    pub mode: u8,
    /// The key's distance value (the app's default is 0.01125).
    pub distance: f32,
}

impl SelfShadow {
    /// Whether the self-shadow shading applies. In mode 1 the shadow range is
    /// `10000 - 100000 * distance` (the app's default 0.01125 is range 8875). The golden scene of
    /// `tests/fixtures/rust/golden`, in mode 1 at the raw distance 8875 (a negative range), shows
    /// no toon at all, not even the toon texture of self-shadow off; golden2 `selfshadow-0` (mode 1
    /// at 0.01125) has the self-shadow shading. Mode 2 at 5000 (golden frames 300 and 599) has it
    /// too, so the range gates mode 1 only.
    pub fn shades(&self) -> bool {
        self.mode == 2 || (self.mode == 1 && self.distance < 0.1)
    }
}

/// The ground shadow settings of a PMM (`Physics::projected_shadow_*`).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct GroundShadow {
    /// `projected_shadow_ambient`: the shadow's brightness.
    pub ambient: f32,
    /// `projected_shadow_blend`: the shadow is blended over the ground instead of opaque.
    pub translucent: bool,
}

/// The golden images sit half a pixel right and down of where the viewport transform of Direct3D 11
/// and wgpu puts a point: the models' edges and the 8 and 12 unit spacing of the model roots fit at
/// this offset to a few hundredths of a pixel (Direct3D 9 puts pixel centers on integer
/// coordinates).
pub const PIXEL_OFFSET_D3D9: [f32; 2] = [0.5, 0.5];

/// The sample positions of Direct3D's standard 8x multisample pattern, in pixels from the pixel
/// center (y down): the grid of 16ths `(1,-3) (-1,3) (5,1) (-3,-5) (-5,5) (-7,-1) (3,7) (7,-7)`.
pub const SAMPLES_8X: [[f32; 2]; 8] = [
    [1.0 / 16.0, -3.0 / 16.0],
    [-1.0 / 16.0, 3.0 / 16.0],
    [5.0 / 16.0, 1.0 / 16.0],
    [-3.0 / 16.0, -5.0 / 16.0],
    [-5.0 / 16.0, 5.0 / 16.0],
    [-7.0 / 16.0, -1.0 / 16.0],
    [3.0 / 16.0, 7.0 / 16.0],
    [7.0 / 16.0, -7.0 / 16.0],
];

/// Renders `pmx` in bind pose and returns `WIDTH * HEIGHT * 4` RGBA8 bytes, top row first.
///
/// Texture slots are not decoded yet: texture and sphere are white, toon is the built-in ramp
/// whatever the material names, and the sphere mode is passed as 0 (off).
pub fn render(gpu: &Gpu, pmx: &Pmx) -> Result<Vec<u8>, String> {
    let mesh = Mesh::from_pmx(pmx)?;
    let (min, max) = mesh.bounds();
    render_frame(
        gpu,
        &Frame {
            width: WIDTH,
            height: HEIGHT,
            view: view::bounding_box_view(min, max, mesh.front(), WIDTH as f32 / HEIGHT as f32),
            light: view::DEFAULT_LIGHT,
            background: CLEAR,
            toon: true,
            models: &[(&mesh, None)],
            samples: &[[0.0, 0.0]],
            pixel_offset: [0.0, 0.0],
        },
    )
}

/// Renders a posed scene and returns `width * height * 4` RGBA8 bytes, top row first. The pipelines
/// and the buffers of the models are kept in `gpu` for the next call; see [`Renderer::render_frame`].
pub fn render_frame(gpu: &Gpu, frame: &Frame) -> Result<Vec<u8>, String> {
    gpu.renderer().render_frame(frame)
}

/// [`render_frame`] with the passes of `stage`.
pub fn render_frame_with(gpu: &Gpu, frame: &Frame, stage: &Stage) -> Result<Vec<u8>, String> {
    gpu.renderer().render_frame_with(frame, stage)
}

fn srgb_to_linear_table() -> [f32; 256] {
    std::array::from_fn(|i| {
        let c = i as f32 / 255.0;
        if c <= 0.04045 {
            c / 12.92
        } else {
            ((c + 0.055) / 1.055).powf(2.4)
        }
    })
}

fn linear_to_srgb(l: f32) -> f32 {
    if l <= 0.003_130_8 {
        l * 12.92
    } else {
        1.055 * l.powf(1.0 / 2.4) - 0.055
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn srgb_round_trip_keeps_every_8_bit_value() {
        let table = super::srgb_to_linear_table();
        for (v, &lin) in table.iter().enumerate() {
            assert_eq!((super::linear_to_srgb(lin) * 255.0).round() as usize, v);
        }
    }
}
