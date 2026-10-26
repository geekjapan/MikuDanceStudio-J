//! The window's viewport: one [`Renderer`] on eframe's wgpu device draws the editor's frame into
//! a texture this module owns, and egui shows that texture as a native texture. Nothing is read
//! back, except with effects on ([`crate::mme`]): `mds-mmert` draws on its own device, so its
//! picture is read back and written into the texture.

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
    queue: wgpu::Queue,
    renderer: Renderer,
    target: Option<(wgpu::Texture, wgpu::TextureView)>,
    /// When the last MME frame was drawn (its `ELAPSEDTIME`).
    last_mme: Option<std::time::Instant>,
}

impl Viewport {
    pub fn new(device: &wgpu::Device, queue: &wgpu::Queue) -> Result<Viewport, String> {
        Ok(Viewport {
            device: device.clone(),
            queue: queue.clone(),
            renderer: Renderer::new(device, queue)?,
            target: None,
            last_mme: None,
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
                    | wgpu::TextureUsages::COPY_SRC
                    | wgpu::TextureUsages::COPY_DST,
                view_formats: &[],
            });
            let view = texture.create_view(&Default::default());
            self.target = Some((texture, view));
        }
        let (texture, view) = self.target.as_ref().expect("target created above");
        if editor.mme.active() {
            let now = std::time::Instant::now();
            let elapsed = self.last_mme.map_or(0.0, |t| (now - t).as_secs_f32());
            self.last_mme = Some(now);
            let shot = editor.view(editor.shown_frame(), size, elapsed)?;
            let px = editor.mme.render(&editor.doc, &editor.physics, &shot)?;
            self.queue.write_texture(
                texture.as_image_copy(),
                &px,
                wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(size[0] * 4),
                    rows_per_image: Some(size[1]),
                },
                texture.size(),
            );
            return Ok((texture, view, resized));
        }
        let renderer = &mut self.renderer;
        editor.with_stage(size, &[[0.0, 0.0]], |f, s| {
            renderer.render_into_with(view, f, s, sample_count)
        })??;
        Ok((texture, view, resized))
    }
}

/// The viewport fields `MediaAspect` reads when a background movie or picture loads, for the view
/// at `[left, top, right, bottom]` window pixels: the edges as `RefreshMainWindowViewport` keeps
/// them (`hideLeft` the right edge, `hideRight` the left one) and `viewScale = width * 1.2 / 1280`
/// (`src/window/ui_viewport_refresh.cpp:224`).
pub fn media_viewport([left, top, right, bottom]: [i32; 4]) -> mds_media::background::Viewport {
    mds_media::background::Viewport {
        hide_left: right,
        hide_right: left,
        hide_top: top,
        hide_bottom: bottom,
        view_scale: (f64::from(right - left) * 1.2 / 1280.0) as f32,
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
