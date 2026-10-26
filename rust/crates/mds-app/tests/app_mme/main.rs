//! `mds-app --frame-dump` of every scene of `tests/fixtures/rust/mmegold/` against the C++ MME
//! images, by the per-pixel rule and gate list of `mds-mmert/tests/mmegold.rs` ([`LIMITS`],
//! [`flat`], [`score`], [`overlay`] and [`PIXEL_GATED`] are copied from there, because a test
//! file of another crate cannot be imported). Both draw through `mds_mmert::host`, so the models
//! without an effect are compared, not masked.
//!
//! Each scene is staged as the Windows lane `tools/oracle/mmegold.ps1` stages it: the PMM with its
//! EMM beside it, the `$(fixtures)`, `$(mmegold)` and `$(corpus)` effect paths made absolute, and
//! the model and accessory files next to the PMM. The app then autoloads the EMM, as the C++ app
//! does. Needs the vkd3d-shader library (`MDS_VKD3D_LIB`, else the one `tools/vkd3d/build.sh`
//! leaves in the temp directory) and, for the ray-mmd scenes, the corpus of
//! `tools/fixtures/fetch_corpus.sh` (`MDS_CORPUS`); without them it prints SKIP.
//!
//! `MDS_APP_MME_DIR=<dir>` keeps the staged scenes and the dumped PNGs there.
//!
//! [`menu`] has the tests of the MMEffect menu and the mapping dialog, [`editor`] those of two
//! editor calls beside them, [`window`] the frame drawn into a window's texture.

mod editor;
mod menu;
mod window;

use std::path::{Path, PathBuf};
use std::process::Command;

const W: u32 = 640;
const H: u32 = 360;

/// Scenes and their probed frames (`SCENES` of `gen_mmegold.py`).
const SCENES: [(&str, &[u32]); 8] = [
    ("objects", &[0, 30]),
    ("post", &[0, 30]),
    ("offscreen", &[0, 30]),
    ("timeofday", &[0, 30]),
    ("main", &[0, 30]),
    ("control", &[0, 15, 30]),
    ("anime", &[0, 3, 4, 9, 30]),
    ("ray", &[0, 30]),
];

/// Scenes whose every probed frame meets [`LIMITS`] in `mmegold.rs`. `post` joins them once its
/// fixed effect `mmegold/post.fx` is in the fixtures (slice `cppfix`).
const PIXEL_GATED: &[&str] = &[
    "objects",
    "offscreen",
    "timeofday",
    "main",
    "control",
    "anime",
];

pub fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

fn mmegold() -> PathBuf {
    fixtures().join("mmegold")
}

fn gated(name: &str) -> bool {
    PIXEL_GATED.contains(&name) || (name == "post" && mmegold().join("post.fx").is_file())
}

pub fn vkd3d_lib() -> PathBuf {
    match std::env::var_os("MDS_VKD3D_LIB") {
        Some(p) => PathBuf::from(p),
        None if cfg!(target_os = "macos") => {
            std::env::temp_dir().join("mds-vkd3d/macos/lib/libvkd3d-shader.1.dylib")
        }
        None => {
            let arch = if cfg!(target_arch = "x86_64") {
                "amd64"
            } else {
                "arm64"
            };
            std::env::temp_dir().join(format!("mds-vkd3d/linux-{arch}/lib/libvkd3d-shader.so.1"))
        }
    }
}

fn corpus() -> Option<PathBuf> {
    let dir = match std::env::var_os("MDS_CORPUS") {
        Some(p) => PathBuf::from(p),
        None => std::env::temp_dir().join("mds-corpus"),
    }
    .join("ray-mmd");
    dir.is_dir().then_some(dir)
}

/// The scene `name` in `dir`: the PMM, its EMM with absolute effect paths, the models, and the
/// accessory; the effects of `mmegold/` with `blink.gif` in `dir/mmegold`.
pub fn stage(name: &str, dir: &Path, corpus: &Path) {
    let effects = dir.join("mmegold");
    std::fs::create_dir_all(&effects).unwrap();
    for e in std::fs::read_dir(mmegold()).unwrap() {
        let p = e.unwrap().path();
        if p.extension().is_some_and(|x| x == "fx") {
            std::fs::copy(&p, effects.join(p.file_name().unwrap())).unwrap();
        }
    }
    let gif = Path::new(env!("CARGO_MANIFEST_DIR")).join("../mds-mmert/tests/data/blink.gif");
    std::fs::copy(gif, effects.join("blink.gif")).unwrap();
    for m in ["chain8.pmx", "morph4.pmx"] {
        std::fs::copy(fixtures().join(m), dir.join(m)).unwrap();
    }
    if corpus.join("ray.x").is_file() {
        std::fs::copy(corpus.join("ray.x"), dir.join("ray.x")).unwrap();
    }
    std::fs::copy(
        mmegold().join(format!("{name}.pmm")),
        dir.join(format!("{name}.pmm")),
    )
    .unwrap();
    let root = |p: &Path| p.to_string_lossy().into_owned() + "/";
    let emm = std::fs::read_to_string(mmegold().join(format!("{name}.emm"))).unwrap();
    let emm: String = emm
        .lines()
        .map(|l| match l.split_once(" = $(") {
            Some((key, rest)) => {
                let (var, path) = rest.split_once(")\\").unwrap();
                let base = match var {
                    "fixtures" => root(&fixtures().join("mme/effects")),
                    "mmegold" => root(&effects),
                    "corpus" => root(corpus),
                    _ => panic!("unknown effect root {var}"),
                };
                format!("{key} = {base}{}\r\n", path.replace('\\', "/"))
            }
            None => format!("{l}\r\n"),
        })
        .collect();
    std::fs::write(dir.join(format!("{name}.emm")), emm).unwrap();
}

// ---- pixels (mmegold.rs) ----

/// A pixel is close when no channel of R, G, B is more than `tolerance` from the golden image.
/// An image passes when `min_close` of its pixels are close and every other pixel is on an edge
/// of the golden image (its 3x3 neighbourhood there is not one colour within `tolerance`).
struct Limits {
    tolerance: u8,
    min_close: f64,
}

const LIMITS: Limits = Limits {
    tolerance: 4,
    min_close: 0.995,
};

#[derive(Debug)]
struct Score {
    pixels: usize,
    close: f64,
    max: u8,
    mean: f64,
    /// Pixels beyond the tolerance inside a flat area of the golden image.
    flat: usize,
}

impl Score {
    fn passes(&self) -> bool {
        self.close >= LIMITS.min_close && self.flat == 0
    }
}

fn pixel_diff(a: &[u8], i: usize, b: &[u8], j: usize) -> u8 {
    (0..3)
        .map(|c| a[i * 4 + c].abs_diff(b[j * 4 + c]))
        .max()
        .unwrap()
}

/// Whether the 3x3 neighbourhood of pixel `i` of `gold` is one colour within the tolerance.
fn flat(gold: &[u8], i: usize) -> bool {
    let (x, y) = ((i % W as usize) as i64, (i / W as usize) as i64);
    (-1..=1).all(|dy| {
        (-1..=1).all(|dx| {
            let (nx, ny) = (x + dx, y + dy);
            !(0..W as i64).contains(&nx)
                || !(0..H as i64).contains(&ny)
                || pixel_diff(gold, i, gold, (ny * W as i64 + nx) as usize) <= LIMITS.tolerance
        })
    })
}

fn read_png(path: &Path) -> Vec<u8> {
    let data = std::fs::read(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let mut reader = png::Decoder::new(std::io::Cursor::new(data))
        .read_info()
        .unwrap();
    let mut buf = vec![0; reader.output_buffer_size().unwrap()];
    let info = reader.next_frame(&mut buf).unwrap();
    assert_eq!(info.color_type, png::ColorType::Rgba);
    assert_eq!((info.width, info.height), (W, H));
    buf
}

/// What the app draws besides the effects: the grid, the axes, the ground line, and the bone
/// marks. `offscreen-0.png` holds them alone (its effect draws nothing visible), so every pixel
/// that is not white there is left out.
fn overlay() -> Vec<bool> {
    read_png(&mmegold().join("offscreen-0.png"))
        .chunks(4)
        .map(|p| p[..3] != [255, 255, 255])
        .collect()
}

fn score(px: &[u8], gold: &[u8], mask: &[bool]) -> Score {
    let (mut n, mut close, mut max, mut sum, mut flats) = (0, 0, 0u8, 0u64, 0);
    for i in (0..(W * H) as usize).filter(|&i| !mask[i]) {
        let d = pixel_diff(px, i, gold, i);
        flats += usize::from(d > LIMITS.tolerance && flat(gold, i));
        n += 1;
        close += usize::from(d <= LIMITS.tolerance);
        max = max.max(d);
        sum += u64::from(d);
    }
    Score {
        pixels: n,
        close: close as f64 / n as f64,
        max,
        mean: sum as f64 / n as f64,
        flat: flats,
    }
}

#[test]
fn frame_dumps_meet_the_mmegold_rule() {
    if mds_render::Gpu::new().expect("device").is_none() {
        eprintln!("SKIP: no wgpu adapter on this host (not a pass)");
        return;
    }
    let lib = vkd3d_lib();
    if let Err(e) = mds_shader::vkd3d::Vkd3d::open(&lib) {
        eprintln!("SKIP: vkd3d-shader not loaded: {e} (not a pass)");
        return;
    }
    let corpus = corpus();
    let keep = std::env::var_os("MDS_APP_MME_DIR").map(PathBuf::from);
    let out = keep.clone().unwrap_or_else(|| {
        std::env::temp_dir().join(format!("mds-app-mme-{}", std::process::id()))
    });
    let mask = overlay();
    let mut table = Vec::new();
    let mut failures = Vec::new();
    for (name, frames) in SCENES {
        let emm = std::fs::read_to_string(mmegold().join(format!("{name}.emm"))).unwrap();
        let corpus = match &corpus {
            Some(c) => c.clone(),
            None if emm.contains("$(corpus)") => {
                eprintln!("SKIP {name}: needs the corpus (a skip is not a pass)");
                continue;
            }
            None => PathBuf::new(),
        };
        let dir = out.join(name);
        stage(name, &dir, &corpus);
        let status = Command::new(env!("CARGO_BIN_EXE_mds-app"))
            .env("MDS_VKD3D_LIB", &lib)
            .arg("--frame-dump")
            .arg(dir.join(format!("{name}.pmm")))
            .arg(dir.join("out"))
            .args(frames.iter().map(u32::to_string))
            .status()
            .unwrap();
        assert!(status.success(), "{name}: mds-app --frame-dump: {status}");
        for &f in frames {
            let px = read_png(&dir.join(format!("out/{name}-{f}.png")));
            let gold = read_png(&mmegold().join(format!("{name}-{f}.png")));
            let s = score(&px, &gold, &mask);
            let image = format!("{name}-{f}");
            table.push(format!(
                "{image:<14} {:>7} {:>9.5} {:>4} {:>7.3} {:>5} {:>7}  {}{}",
                s.pixels,
                s.close,
                s.max,
                s.mean,
                s.flat,
                (W * H) as usize - s.pixels,
                if gated(name) { "yes" } else { "no" },
                if s.passes() { "" } else { " (fails)" }
            ));
            if gated(name) && !s.passes() {
                failures.push(format!("{image}: {s:?}"));
            }
        }
    }
    eprintln!(
        "{:<14} {:>7} {:>9} {:>4} {:>7} {:>5} {:>7}  gated",
        "image", "pixels", "within 4", "max", "mean", "flat", "masked"
    );
    for l in &table {
        eprintln!("{l}");
    }
    if keep.is_none() {
        std::fs::remove_dir_all(&out).unwrap();
    }
    assert!(failures.is_empty(), "{failures:?}");
}
