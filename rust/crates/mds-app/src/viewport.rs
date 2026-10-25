//! The window's viewport: one [`Renderer`] on eframe's wgpu device draws the editor's frame into
//! a texture this module owns, and egui shows that texture as a native texture. Nothing is read
//! back.

use crate::editor::Editor;
use eframe::egui_wgpu;
use mds_render::Renderer;

/// Hardware multisampling of the window. WebGPU guarantees 4 for `Rgba8Unorm` and
/// `Depth32Float`; the frame dump keeps the C++ 8x pattern.
pub const WINDOW_SAMPLES: u32 = 4;

/// The format [`Renderer::render_into`] draws and egui samples as gamma-encoded RGBA.
const FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8Unorm;

pub struct Viewport {
    device: wgpu::Device,
    renderer: Renderer,
    target: Option<(wgpu::Texture, wgpu::TextureView)>,
}

impl Viewport {
    pub fn new(device: &wgpu::Device, queue: &wgpu::Queue) -> Result<Viewport, String> {
        Ok(Viewport {
            device: device.clone(),
            renderer: Renderer::new(device, queue)?,
            target: None,
        })
    }

    /// Draws the editor's frame at `size` pixels. Returns the target and whether it is a new
    /// texture (the first draw or a new size).
    pub fn draw(
        &mut self,
        editor: &Editor,
        size: [u32; 2],
        sample_count: u32,
    ) -> Result<(&wgpu::Texture, &wgpu::TextureView, bool), String> {
        let resized = self
            .target
            .as_ref()
            .is_none_or(|(t, _)| [t.width(), t.height()] != size);
        if resized {
            let texture = self.device.create_texture(&wgpu::TextureDescriptor {
                label: Some("viewport"),
                size: wgpu::Extent3d {
                    width: size[0],
                    height: size[1],
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: FORMAT,
                usage: wgpu::TextureUsages::RENDER_ATTACHMENT
                    | wgpu::TextureUsages::TEXTURE_BINDING
                    | wgpu::TextureUsages::COPY_SRC,
                view_formats: &[],
            });
            let view = texture.create_view(&Default::default());
            self.target = Some((texture, view));
        }
        let (texture, view) = self.target.as_ref().expect("target created above");
        let renderer = &mut self.renderer;
        editor.with_frame(size, &[[0.0, 0.0]], |f| {
            renderer.render_into(view, f, sample_count)
        })??;
        Ok((texture, view, resized))
    }
}

/// A [`Viewport`] registered with eframe's egui renderer.
pub struct WindowViewport {
    viewport: Viewport,
    egui: egui_wgpu::RenderState,
    texture: Option<egui::TextureId>,
}

impl WindowViewport {
    pub fn new(egui: &egui_wgpu::RenderState) -> Result<WindowViewport, String> {
        Ok(WindowViewport {
            viewport: Viewport::new(&egui.device, &egui.queue)?,
            egui: egui.clone(),
            texture: None,
        })
    }

    /// Draws the editor's frame at `size` pixels and returns the egui texture that shows it.
    pub fn show(&mut self, editor: &Editor, size: [u32; 2]) -> Result<egui::TextureId, String> {
        let (_, view, resized) = self.viewport.draw(editor, size, WINDOW_SAMPLES)?;
        let mut egui = self.egui.renderer.write();
        let filter = wgpu::FilterMode::Nearest;
        let id = match self.texture {
            Some(id) if resized => {
                egui.update_egui_texture_from_wgpu_texture(&self.egui.device, view, filter, id);
                id
            }
            Some(id) => id,
            None => egui.register_native_texture(&self.egui.device, view, filter),
        };
        self.texture = Some(id);
        Ok(id)
    }
}
