//! The `--mds-script` oracle (`tests/fixtures/rust/script/`): every script
//! replays through [`Document`] and every file it saves equals the C++
//! output in `expected/<script>/`, byte for byte.
//!
//! The `.emm` beside each PMM is not compared: it holds the absolute paths
//! that MME resolved on the Windows host (`C:\mds\w2-script\repo\out\ci\
//! build\Release\chain8.pmx`), which no replay outside that checkout can
//! produce, and the MME effect map is not part of the document.

use mds_doc::script::{Runner, Saved};
use mds_media::background::Viewport;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// The viewport of the hidden main window on the oracle host, as
/// `MediaAspect` reads it, with `viewScale` `width * 1.2 / 1280`
/// (`ui_viewport_refresh.cpp` 224). `script4/expected/background/loaded.pmm`
/// places the AVI (32 by 24) at Y -214 and the picture (2 by 2) at -500;
/// widths 2280 to 2291 with half heights 640 to 645 give both, and
/// 2280 by 1280 is taken.
const HOST_VIEWPORT: Viewport = Viewport {
    hide_left: 2280,
    hide_right: 0,
    hide_top: 0,
    hide_bottom: 1280,
    view_scale: (2280.0 * 1.2 / 1280.0) as f32,
};

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

/// A load path as the C++ handlers get it: relative to the exe directory,
/// where the lane stages `tests/fixtures/rust/*` and `script/inputs/*`.
fn read_input(path: &str) -> Option<Vec<u8>> {
    let name = path.trim_start_matches(".\\");
    [
        fixtures(),
        fixtures().join("script/inputs"),
        fixtures().join("script2/inputs"),
        fixtures().join("script3/inputs"),
        fixtures().join("vsq"),
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../mds-media/tests/fixtures/bgmovie"),
    ]
    .iter()
    .find_map(|d| std::fs::read(d.join(name)).ok())
}

fn manifest(dir: &Path) -> Vec<(u32, String)> {
    let text = std::fs::read_to_string(dir.join("manifest.tsv")).unwrap();
    text.lines()
        .skip(1)
        .map(|l| {
            let mut w = l.split('\t');
            (
                w.next().unwrap().parse().unwrap(),
                w.next().unwrap().to_string(),
            )
        })
        .collect()
}

/// The first byte that differs, or the length when one is a prefix.
fn first_diff(a: &[u8], b: &[u8]) -> Option<usize> {
    a.iter()
        .zip(b)
        .position(|(x, y)| x != y)
        .or((a.len() != b.len()).then(|| a.len().min(b.len())))
}

/// With `MDS_DOC_DUMP=<dir>`, the two sides of a PMM mismatch as `Debug`
/// text, for a field-level diff.
fn dump(script: &str, file: &str, rust: &[u8], cpp: &[u8]) {
    let (Ok(dir), true) = (std::env::var("MDS_DOC_DUMP"), file.ends_with(".pmm")) else {
        return;
    };
    for (side, bytes) in [("rust", rust), ("cpp", cpp)] {
        let text = match mds_formats::pmm::Pmm::read(bytes) {
            Ok(p) => format!("{p:#?}"),
            Err(e) => e.to_string(),
        };
        let path = Path::new(&dir).join(format!("{script}-{file}.{side}.txt"));
        std::fs::write(path, text).unwrap();
    }
}

/// `messages.tsv`: the step and text of every answered info box.
fn messages(dir: &Path) -> BTreeMap<u32, String> {
    let Ok(text) = std::fs::read_to_string(dir.join("messages.tsv")) else {
        return BTreeMap::new();
    };
    text.lines()
        .skip(1)
        .map(|l| {
            let w: Vec<&str> = l.split('\t').collect();
            (w[0].parse().unwrap(), w[2].to_string())
        })
        .collect()
}

/// The count in an info box text ("7個のポイントを削除しました").
fn count_of(text: &str) -> Option<u32> {
    let digits: String = text.chars().take_while(char::is_ascii_digit).collect();
    digits.parse().ok()
}

/// Replays one script of `tests/fixtures/rust/<set>/`; `Err` names every
/// step and file that differ.
fn replay(set: &str, name: &str) -> Result<usize, String> {
    let root = fixtures().join(set);
    let script = std::fs::read_to_string(root.join(format!("{name}.txt"))).unwrap();
    let expected_dir = root.join("expected").join(name);
    let mut want: BTreeMap<u32, Vec<String>> = BTreeMap::new();
    for (step, file) in manifest(&expected_dir) {
        if !file.ends_with(".emm") {
            want.entry(step).or_default().push(file);
        }
    }
    let mut boxes = messages(&expected_dir);
    let mut runner = Runner::new();
    runner.doc.edit.viewport = Some(HOST_VIEWPORT);
    let mut compared = 0;
    let mut differ: Vec<String> = Vec::new();
    for (n, line) in script.lines().enumerate() {
        let step = n as u32 + 1;
        let saved: Vec<Saved> = match runner.run_line(line, &mut |p| read_input(p)) {
            Ok(s) => s,
            Err(e) => {
                let stop = format!("{name}.txt line {step} ({line}): {e}");
                differ.push(stop);
                return Err(differ.join("; then "));
            }
        };
        let reported = runner.doc.edit.reported;
        let want_box = boxes.remove(&step);
        if reported != want_box.as_deref().and_then(count_of) {
            differ.push(format!(
                "{name}.txt line {step}: info box count {reported:?}, c++ {want_box:?}"
            ));
        }
        let saved: Vec<Saved> = saved
            .into_iter()
            .filter(|s| !s.name.ends_with(".emm"))
            .collect();
        let names: Vec<String> = saved.iter().map(|s| s.name.clone()).collect();
        if names != want.remove(&step).unwrap_or_default() {
            return Err(format!(
                "{name}.txt line {step}: saved {names:?}, manifest differs"
            ));
        }
        for s in saved {
            let expected = std::fs::read(expected_dir.join(&s.name)).unwrap();
            if let Some(at) = first_diff(&s.bytes, &expected) {
                dump(name, &s.name, &s.bytes, &expected);
                // Later steps still run, so a dump shows every mismatch.
                differ.push(format!(
                    "{name}.txt line {step} {}: offset {at}: rust {:?}, c++ {:?} (lengths {} and {})",
                    s.name,
                    s.bytes.get(at),
                    expected.get(at),
                    s.bytes.len(),
                    expected.len()
                ));
                continue;
            }
            compared += 1;
        }
    }
    if !differ.is_empty() {
        return Err(differ.join("; "));
    }
    match want.into_iter().next() {
        Some((step, files)) => Err(format!("{name}.txt line {step}: {files:?} never saved")),
        None => Ok(compared),
    }
}

/// One script: `SKIP` without the expected outputs, else every saved file
/// equal.
fn check(name: &str) {
    check_in("script", name);
}

fn check_in(set: &str, name: &str) {
    let root = fixtures().join(set);
    if !root.join("expected").join(name).is_dir() {
        println!(
            "SKIP: {} is missing",
            root.join("expected").join(name).display()
        );
        return;
    }
    match replay(set, name) {
        Ok(n) => println!("{name}: {n} files equal"),
        Err(e) => panic!("{e}"),
    }
}

#[test]
fn empty() {
    check("empty");
}

#[test]
fn camera() {
    check("camera");
}

#[test]
fn morphs() {
    check("morphs");
}

#[test]
fn accessory() {
    check("accessory");
}

#[test]
fn motion() {
    check("motion");
}

#[test]
fn bones() {
    check("bones");
}

/// The bulk operations of `tests/fixtures/rust/script2/`, with the counts of
/// their info boxes (`messages.tsv`).
mod script2 {
    use super::check_in;

    #[test]
    fn bias() {
        check_in("script2", "bias");
    }

    #[test]
    fn blink() {
        check_in("script2", "blink");
    }

    #[test]
    fn facial() {
        check_in("script2", "facial");
    }

    #[test]
    fn lipshift() {
        check_in("script2", "lipshift");
    }

    #[test]
    fn multiply_bone() {
        check_in("script2", "multiply-bone");
    }

    #[test]
    fn multiply_camera() {
        check_in("script2", "multiply-camera");
    }

    #[test]
    fn multiply_morph() {
        check_in("script2", "multiply-morph");
    }

    #[test]
    fn physicsframes() {
        check_in("script2", "physicsframes");
    }

    #[test]
    fn registerall() {
        check_in("script2", "registerall");
    }

    #[test]
    fn resetmorphs() {
        check_in("script2", "resetmorphs");
    }

    #[test]
    fn scalerange() {
        check_in("script2", "scalerange");
    }

    #[test]
    fn unused() {
        check_in("script2", "unused");
    }
}

/// The document commands of `tests/fixtures/rust/script3/` (slice
/// `winoracle3`): the key drag, model delete, the camera reference, lip
/// sync, `.vac` accessories, menu 250 in camera mode, and the toon and
/// physics model edits of `pmdedit`, and the English name dialog.
mod script3 {
    use super::check_in;

    #[test]
    fn camref() {
        check_in("script3", "camref");
    }

    #[test]
    fn deletemodel() {
        check_in("script3", "deletemodel");
    }

    #[test]
    fn drag() {
        check_in("script3", "drag");
    }

    #[test]
    fn dragcamera() {
        check_in("script3", "dragcamera");
    }

    #[test]
    fn lipsync() {
        check_in("script3", "lipsync");
    }

    #[test]
    fn pastecamera() {
        check_in("script3", "pastecamera");
    }

    #[test]
    fn vac() {
        check_in("script3", "vac");
    }

    #[test]
    fn pmdedit() {
        check_in("script3", "pmdedit");
    }

    #[test]
    fn english() {
        check_in("script3", "english");
    }
}

/// The document commands of `tests/fixtures/rust/script4/` (slice
/// `script4`): the outside-parent and order dialogs, the view drags, the
/// physics record drag and edit boxes, the background media, and menu 263
/// on a PMX model.
mod script4 {
    use super::check_in;

    #[test]
    fn outsideparent() {
        check_in("script4", "outsideparent");
    }

    #[test]
    fn accessoryorder() {
        check_in("script4", "accessoryorder");
    }

    #[test]
    fn modelorder() {
        check_in("script4", "modelorder");
    }

    #[test]
    fn viewoffset() {
        check_in("script4", "viewoffset");
    }

    #[test]
    fn physicsdrag() {
        check_in("script4", "physicsdrag");
    }

    #[test]
    fn background() {
        check_in("script4", "background");
    }

    #[test]
    fn pmx263() {
        check_in("script4", "pmx263");
    }
}
