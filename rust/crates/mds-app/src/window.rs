//! The window: the viewport, a play panel and File > Open / Quit, on eframe.
//!
//! Each pass runs what the C++ frame loop runs in camera mode: the playback catch-up while
//! playing ([`Playback::pass`], then the frame-step passes up to the cursor), else the arrow
//! keys and the numpad presets; the viewport drags and the wheel; then the draw. The viewport is
//! drawn by `mds-render` into memory and shown as an egui texture: one sample while playing or
//! dragging, the 8x pattern of the frame dump once the view rests.

use eframe::egui;
use egui::{Event, Key, MouseWheelUnit, PointerButton, Sense, TextureOptions};
use mds_app::navigation::{self, KeyState, Modifiers, Repeat, ViewButton, WHEEL_DELTA};
use mds_app::playback::{Options, Pass, Playback};
use mds_app::viewer::Viewer;
use mds_render::{Camera, Gpu, SAMPLES_8X};
use std::path::{Path, PathBuf};
use std::time::Instant;

const NUMPAD: [(Key, u8); 10] = [
    (Key::Num0, 0),
    (Key::Num1, 1),
    (Key::Num2, 2),
    (Key::Num3, 3),
    (Key::Num4, 4),
    (Key::Num5, 5),
    (Key::Num6, 6),
    (Key::Num7, 7),
    (Key::Num8, 8),
    (Key::Num9, 9),
];

pub fn run(pmm: Option<PathBuf>) -> Result<(), String> {
    let gpu = Gpu::new()?.ok_or("no wgpu adapter")?;
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
        Box::new(move |_| {
            let mut app = App::new(gpu);
            if let Some(path) = pmm {
                app.open(&path);
            }
            Ok(Box::new(app))
        }),
    )
    .map_err(|e| e.to_string())
}

/// What the viewport texture shows, to draw again only when it changes.
#[derive(Clone, Copy, PartialEq)]
struct Shown {
    frame: u32,
    camera: Camera,
    size: [u32; 2],
    full: bool,
}

/// An opened scene with its view state.
struct Open {
    viewer: Viewer,
    options: Options,
    /// `currentFrame`.
    current: i32,
    camera: Camera,
    playback: Option<Playback>,
}

struct App {
    gpu: Gpu,
    clock: Instant,
    open: Option<Open>,
    status: String,
    texture: Option<egui::TextureHandle>,
    shown: Option<Shown>,
    repeat: Repeat,
    arrows_down: [bool; 2],
    /// `MDS_APP_SCREENSHOT=<png>`: play from the start, write the window's own pixels to the
    /// file after [`SCREENSHOT_AFTER_MS`] and quit (a capture where screen recording is not
    /// allowed).
    screenshot: Option<PathBuf>,
}

const SCREENSHOT_AFTER_MS: u64 = 4000;

impl App {
    fn new(gpu: Gpu) -> App {
        App {
            gpu,
            clock: Instant::now(),
            open: None,
            status: "File > Open a PMM".into(),
            texture: None,
            shown: None,
            repeat: Repeat::default(),
            arrows_down: [false; 2],
            screenshot: std::env::var_os("MDS_APP_SCREENSHOT").map(PathBuf::from),
        }
    }

    fn now_ms(&self) -> u64 {
        self.clock.elapsed().as_millis() as u64
    }

    fn open(&mut self, path: &Path) {
        let opened = Viewer::open(path).and_then(|viewer| {
            let t = &viewer.pmm.timeline;
            let (options, current) = (Options::of(t), t.current_frame);
            let mut open = Open {
                camera: viewer.track_camera()?,
                viewer,
                options,
                current,
                playback: None,
            };
            open.seek(current)?;
            Ok(open)
        });
        match opened {
            Ok(open) => {
                self.status = path.display().to_string();
                self.open = Some(open);
            }
            Err(e) => self.status = e,
        }
    }
}

impl Open {
    /// Moves the scene to `frame` and the camera to the track's (camera mode).
    fn seek(&mut self, frame: i32) -> Result<(), String> {
        self.viewer.seek(frame.max(0) as u32)?;
        self.camera = self.viewer.track_camera()?;
        Ok(())
    }

    /// Button 408.
    fn toggle_play(&mut self, now_ms: u64) -> Result<(), String> {
        match self.playback.take() {
            Some(p) => self.stop(&p),
            None => {
                let last = self.viewer.pmm.timeline.last_registered_frame;
                let p = Playback::start(&self.options, self.current, last, now_ms);
                self.seek(p.frame() as i32)?;
                self.playback = Some(p);
                Ok(())
            }
        }
    }

    fn stop(&mut self, p: &Playback) -> Result<(), String> {
        self.current = p.stop_frame(&self.options, self.current);
        self.seek(self.current)
    }

    /// One pass of the playback catch-up.
    fn play_pass(&mut self, now_ms: u64) -> Result<(), String> {
        let Some(mut p) = self.playback else {
            return Ok(());
        };
        match p.pass(&self.options, now_ms) {
            Pass::Playing | Pass::Looped => {
                self.playback = Some(p);
                self.seek(p.frame() as i32)
            }
            Pass::Stopped => {
                self.playback = None;
                self.stop(&p)
            }
        }
    }

    fn last_frame(&self) -> i32 {
        let t = &self.viewer.pmm.timeline;
        t.last_registered_frame
            .max(t.play_stop_frame)
            .max(self.current)
    }
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        let now = self.now_ms();
        let mut result = Ok(());
        let mut open_file = None;
        if let Some(open) = self.open.as_mut().filter(|_| self.screenshot.is_some()) {
            if open.playback.is_none() && now < SCREENSHOT_AFTER_MS {
                result = open.toggle_play(now);
            } else if now >= SCREENSHOT_AFTER_MS {
                let path = self.screenshot.take().unwrap();
                ui.ctx().request_screenshot(move |image| {
                    let [w, h] = image.size.map(|n| n as u32);
                    let rgba: Vec<u8> = image.pixels.iter().flat_map(|c| c.to_array()).collect();
                    let code = match std::fs::write(&path, mds_render::encode_png(w, h, &rgba)) {
                        Ok(()) => 0,
                        Err(e) => {
                            eprintln!("mds-app: {}: {e}", path.display());
                            1
                        }
                    };
                    std::process::exit(code);
                });
            }
            ui.ctx().request_repaint();
        }

        egui::Panel::top("menu").show(ui, |ui| {
            egui::MenuBar::new().ui(ui, |ui| {
                ui.menu_button("File", |ui| {
                    if ui.button("Open...").clicked() {
                        open_file = rfd::FileDialog::new()
                            .add_filter("PMM", &["pmm"])
                            .pick_file();
                    }
                    if ui.button("Quit").clicked() {
                        ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close);
                    }
                });
            });
        });
        if let Some(path) = open_file {
            self.open(&path);
            self.shown = None;
        }

        if let Some(open) = &mut self.open {
            result = result.and(open.play_pass(now));
        }

        egui::Panel::bottom("play").show(ui, |ui| {
            ui.horizontal(|ui| {
                let Some(open) = &mut self.open else {
                    ui.label(&self.status);
                    return;
                };
                let playing = open.playback.is_some();
                if ui.button(if playing { "stop" } else { "play" }).clicked() {
                    result = open.toggle_play(now);
                }
                ui.add_enabled_ui(!playing, |ui| {
                    if ui.button("<").clicked() && open.current > 0 {
                        open.current -= 1;
                        result = open.seek(open.current);
                    }
                    let mut frame = open.current;
                    let last = open.last_frame();
                    if ui
                        .add(egui::DragValue::new(&mut frame).range(0..=99_999))
                        .changed()
                        | ui.add(egui::Slider::new(&mut frame, 0..=last).show_value(false))
                            .changed()
                    {
                        open.current = frame;
                        result = open.seek(frame);
                    }
                    if ui.button(">").clicked() {
                        open.current += 1;
                        result = open.seek(open.current);
                    }
                    let o = &mut open.options;
                    ui.label("play");
                    ui.add(egui::DragValue::new(&mut o.start_frame).range(0..=99_999));
                    ui.label("to");
                    ui.add(egui::DragValue::new(&mut o.stop_frame).range(0..=99_999));
                    ui.checkbox(&mut o.from_current, "from current");
                    ui.checkbox(&mut o.stop_at_playhead, "stop at playhead");
                });
                ui.checkbox(&mut open.options.looped, "loop");
                ui.separator();
                for button in ViewButton::ALL {
                    if ui.button(button.label()).clicked() {
                        button.apply(&mut open.camera);
                    }
                }
                ui.separator();
                let shown = open.playback.map_or(open.viewer.frame(), |p| p.frame());
                ui.label(format!("frame {shown}"));
            });
            if let Err(e) = &result {
                ui.colored_label(egui::Color32::RED, e);
            }
        });

        egui::CentralPanel::default().show(ui, |ui| self.viewport(ui));
        if let Err(e) = result {
            self.status = e;
        }
    }
}

impl App {
    fn viewport(&mut self, ui: &mut egui::Ui) {
        let (rect, response) = ui.allocate_exact_size(ui.available_size(), Sense::drag());
        let Some(open) = &mut self.open else {
            return;
        };
        let ppp = ui.ctx().pixels_per_point();
        let (m, dt, wheel) = ui.input(|i| {
            let wheel: f32 = i
                .events
                .iter()
                .filter_map(|e| match e {
                    Event::MouseWheel {
                        unit: MouseWheelUnit::Line,
                        delta,
                        ..
                    } => Some(delta.y * f32::from(WHEEL_DELTA)),
                    // ponytail: a trackpad point counts as one WM_MOUSEWHEEL unit; tune if the
                    // zoom feels wrong.
                    Event::MouseWheel { delta, .. } => Some(delta.y),
                    _ => None,
                })
                .sum();
            let m = Modifiers {
                shift: i.modifiers.shift,
                ctrl: i.modifiers.ctrl || i.modifiers.mac_cmd,
            };
            (m, i.unstable_dt, wheel)
        });
        let keys_free = !ui.ctx().egui_wants_keyboard_input();
        let pixels = |v: f32| (v * ppp).round() as i32;
        let delta = response.drag_delta();
        let mut dragging = false;
        if response.dragged_by(PointerButton::Secondary) {
            navigation::right_drag(&mut open.camera, pixels(delta.x), pixels(delta.y), m);
            dragging = true;
        }
        if response.dragged_by(PointerButton::Middle) {
            navigation::middle_drag(&mut open.camera, pixels(delta.x), pixels(delta.y), m);
            dragging = true;
        }
        if response.hovered() && wheel != 0.0 {
            navigation::wheel(&mut open.camera, wheel.round() as i16);
        }
        let playing = open.playback.is_some();
        if keys_free && !playing {
            let mut step = 0;
            for (k, (key, dir)) in [(Key::ArrowLeft, -1), (Key::ArrowRight, 1)]
                .into_iter()
                .enumerate()
            {
                let down = ui.input(|i| i.key_down(key));
                if self
                    .repeat
                    .step(KeyState::of(self.arrows_down[k], down), m.ctrl, dt)
                {
                    step += dir;
                }
                self.arrows_down[k] = down;
            }
            if step != 0 && open.current + step >= 0 {
                open.current += step;
                if let Err(e) = open.seek(open.current) {
                    self.status = e;
                }
            }
            for (key, digit) in NUMPAD {
                if ui.input(|i| i.key_pressed(key)) {
                    navigation::numpad(&mut open.camera, digit);
                }
            }
        }

        let size = [(rect.width() * ppp) as u32, (rect.height() * ppp) as u32];
        if size[0] == 0 || size[1] == 0 {
            return;
        }
        let moving = playing || dragging || self.arrows_down.contains(&true);
        let want = Shown {
            frame: open.viewer.frame(),
            camera: open.camera,
            size,
            full: !moving,
        };
        if self.shown != Some(want) {
            let samples: &[[f32; 2]] = if want.full {
                &SAMPLES_8X
            } else {
                &[[0.0, 0.0]]
            };
            match open
                .viewer
                .render(&self.gpu, size[0], size[1], &open.camera, samples)
            {
                Ok(px) => {
                    let image = egui::ColorImage::from_rgba_unmultiplied(
                        [size[0] as usize, size[1] as usize],
                        &px,
                    );
                    match &mut self.texture {
                        Some(t) => t.set(image, TextureOptions::NEAREST),
                        None => {
                            self.texture = Some(ui.ctx().load_texture(
                                "viewport",
                                image,
                                TextureOptions::NEAREST,
                            ))
                        }
                    }
                    self.shown = Some(want);
                }
                Err(e) => self.status = e,
            }
        }
        if let Some(t) = &self.texture {
            let uv = egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0));
            ui.painter().image(t.id(), rect, uv, egui::Color32::WHITE);
        }
        if moving || self.shown.is_some_and(|s| !s.full) {
            ui.ctx().request_repaint();
        }
    }
}
