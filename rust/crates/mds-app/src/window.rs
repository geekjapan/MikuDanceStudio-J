//! The window shell on eframe: each pass runs every area's `pass`, the key chords, one
//! [`Editor::pump`], then draws the areas where [`ui::AREAS`] places them. The labels are
//! Japanese, so the window installs one CJK font of the system ([`CJK_FONTS`]) at start.

use eframe::egui;
use mds_app::editor::Editor;
use mds_app::ui::{self, Ctx, Place, AREAS};
use mds_app::viewport::WindowViewport;
use std::path::PathBuf;
use std::time::Instant;

pub fn run(pmm: Option<PathBuf>) -> Result<(), String> {
    let editor = match &pmm {
        Some(path) => Editor::open(path)?,
        None => Editor::empty(),
    };
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("MikuDanceStudio")
            .with_position([0.0, 0.0])
            .with_inner_size([1280.0, 720.0]),
        ..Default::default()
    };
    eframe::run_native(
        "MikuDanceStudio",
        options,
        Box::new(move |cc| {
            install_cjk_font(&cc.egui_ctx);
            let state = cc.wgpu_render_state.as_ref().ok_or("no wgpu renderer")?;
            let max = state.adapter.limits().max_texture_dimension_2d as i32;
            Ok(Box::new(App {
                max_texture_size: [max; 2],
                viewport: WindowViewport::new(state)?,
                status: pmm.map_or_else(String::new, |p| p.display().to_string()),
                editor,
                clock: Instant::now(),
                screenshot: Screenshot::from_env(),
            }))
        }),
    )
    .map_err(|e| e.to_string())
}

/// System fonts with the Japanese glyphs, by platform, first found wins: file and face index.
const CJK_FONTS: &[(&str, u32)] = &[
    ("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 0),
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
    ("/Library/Fonts/Arial Unicode.ttf", 0),
    ("C:\\Windows\\Fonts\\meiryo.ttc", 0),
    ("C:\\Windows\\Fonts\\YuGothM.ttc", 0),
    ("C:\\Windows\\Fonts\\msgothic.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", 0),
    (
        "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
        0,
    ),
    ("/usr/share/fonts/truetype/fonts-japanese-gothic.ttf", 0),
];

/// The first of [`CJK_FONTS`] as the fallback of egui's own fonts, which keep the Latin text;
/// with none, egui's fonts alone and a warning.
fn install_cjk_font(ctx: &egui::Context) {
    use egui::epaint::text::{FontInsert, FontPriority, InsertFontFamily};
    let Some((path, data, index)) = CJK_FONTS
        .iter()
        .find_map(|&(p, i)| Some((p, std::fs::read(p).ok()?, i)))
    else {
        eprintln!("mds-app: no CJK font found; Japanese labels will not show");
        return;
    };
    let families = [egui::FontFamily::Proportional, egui::FontFamily::Monospace]
        .map(|family| InsertFontFamily {
            family,
            priority: FontPriority::Lowest,
        })
        .to_vec();
    let data = egui::FontData::from_blob(std::sync::Arc::new(data), index);
    ctx.add_font(FontInsert::new(path, data, families));
}

struct App {
    editor: Editor,
    /// The device's largest texture, which bounds the render size (menu 212).
    max_texture_size: [i32; 2],
    viewport: WindowViewport,
    clock: Instant,
    status: String,
    screenshot: Option<Screenshot>,
}

/// `MDS_APP_SCREENSHOT=<png>`: play from the start; after [`Screenshot::AFTER_MS`], with
/// `MDS_APP_SAVE_AS=<pmm>` set, stop and save the scene there (through Ctrl+S, which playback
/// refuses); then write the window's own pixels to the PNG and quit (a capture where screen
/// recording is not allowed).
struct Screenshot {
    png: PathBuf,
    save_as: Option<PathBuf>,
    started: bool,
}

impl Screenshot {
    const AFTER_MS: u64 = 4000;

    fn from_env() -> Option<Screenshot> {
        Some(Screenshot {
            png: std::env::var_os("MDS_APP_SCREENSHOT")?.into(),
            save_as: std::env::var_os("MDS_APP_SAVE_AS").map(PathBuf::from),
            started: false,
        })
    }

    fn pass(&mut self, ui: &egui::Ui, ctx: &mut Ctx) -> bool {
        if !self.started {
            self.started = true;
            ctx.run("ctl:408");
        }
        if ctx.now_ms < Self::AFTER_MS {
            return false;
        }
        if let Some(path) = &self.save_as {
            if ctx.editor.playing() {
                ctx.run("ctl:408");
            }
            ctx.editor.path = Some(path.clone());
            ctx.run("key:Ctrl+S");
            eprintln!("mds-app: {}", ctx.status);
        }
        let png = self.png.clone();
        ui.ctx().request_screenshot(move |image| {
            let [w, h] = image.size.map(|n| n as u32);
            let rgba: Vec<u8> = image.pixels.iter().flat_map(|c| c.to_array()).collect();
            let code = match std::fs::write(&png, mds_render::encode_png(w, h, &rgba)) {
                Ok(()) => 0,
                Err(e) => {
                    eprintln!("mds-app: {}: {e}", png.display());
                    1
                }
            };
            std::process::exit(code);
        });
        true
    }
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        // Set every pass: opening a scene builds a new document.
        self.editor.doc.edit.max_texture_size = Some(self.max_texture_size);
        let mut ctx = Ctx {
            editor: &mut self.editor,
            now_ms: self.clock.elapsed().as_millis() as u64,
            egui: Some(ui.ctx().clone()),
            viewport: Some(&mut self.viewport),
            status: &mut self.status,
        };
        if self
            .screenshot
            .as_mut()
            .is_some_and(|s| s.pass(ui, &mut ctx))
        {
            self.screenshot = None;
        }
        for area in &AREAS {
            (area.pass)(ui, &mut ctx);
        }
        ui::keys(ui, &mut ctx);
        if let Err(e) = ctx.editor.pump(ctx.now_ms) {
            *ctx.status = e;
        }

        egui::Panel::top("menu").show(ui, |ui| {
            egui::MenuBar::new().ui(ui, |ui| {
                for area in &AREAS {
                    if let Place::Menu(title) = area.place {
                        ui.menu_button(title, |ui| (area.show)(ui, &mut ctx));
                    }
                }
            });
        });
        egui::Panel::bottom("bottom").show(ui, |ui| {
            for area in AREAS.iter().filter(|a| a.place == Place::Bottom) {
                ui.horizontal(|ui| (area.show)(ui, &mut ctx));
            }
            ui.label(ctx.status.as_str());
        });
        let side: Vec<_> = AREAS
            .iter()
            .filter(|a| a.place == Place::Side && !(a.actions)().is_empty())
            .collect();
        if !side.is_empty() {
            egui::Panel::right("side").show(ui, |ui| {
                egui::ScrollArea::vertical().show(ui, |ui| {
                    for area in side {
                        egui::CollapsingHeader::new(area.name)
                            .default_open(true)
                            .show(ui, |ui| (area.show)(ui, &mut ctx));
                    }
                });
            });
        }
        egui::CentralPanel::default().show(ui, |ui| {
            for place in [Place::Viewport, Place::Dialog] {
                for area in AREAS.iter().filter(|a| a.place == place) {
                    (area.show)(ui, &mut ctx);
                }
            }
        });
        // The C++ frame loop runs every pass: physics settles and plays without input.
        ui.ctx().request_repaint();
    }
}
