//! Animated textures on `tests/data/blink.gif` and `blink.png` (4x2, red, then green on the left
//! half, then blue; written by Pillow, which crops the second frame to 2x2): the frame timing of
//! `anime_texture.cpp` and the composed frames.

use std::path::Path;

use mds_mmert::anime::Anime;

fn open(name: &str) -> Anime {
    Anime::open(
        &Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("tests/data")
            .join(name),
    )
    .unwrap()
}

const R: [u8; 4] = [255, 0, 0, 255];
const G: [u8; 4] = [0, 255, 0, 255];
const B: [u8; 4] = [0, 0, 255, 255];

fn frames(a: &mut Anime) -> Vec<Vec<u8>> {
    (0..a.timeline.starts.len())
        .map(|i| a.pixels(i).to_vec())
        .collect()
}

fn expected() -> Vec<Vec<u8>> {
    [[R; 8], [G, G, R, R, G, G, R, R], [B; 8]]
        .iter()
        .map(|f| f.concat())
        .collect()
}

#[test]
fn gif_frames_follow_the_delay_table() {
    let mut a = open("blink.gif");
    assert_eq!((a.width, a.height), (4, 2));
    // 10 cs, 0 cs (1/30 s), 20 cs; NETSCAPE2.0 loops twice.
    let t = &a.timeline;
    assert_eq!(t.starts, [0.0, 0.1, 1.0 / 30.0 + 0.1]);
    assert_eq!(t.total, 1.0 / 30.0 + 0.3);
    assert_eq!(t.loops, 2);
    let at = |time: f64| t.frame(time, 0.0, 1.0);
    assert_eq!(
        [at(0.05), at(0.11), at(0.2), at(0.4), at(0.45)],
        [0, 1, 2, 0, 1]
    );
    // After two loops the last frame holds; before the offset the first one shows.
    assert_eq!([at(0.7), at(100.0), t.frame(0.5, 1.0, 1.0)], [2, 2, 0]);
    assert_eq!(frames(&mut a), expected());
    assert_eq!(
        a.pixels(1),
        expected()[1],
        "a GIF recomposes from the first frame"
    );
}

#[test]
fn apng_frames_follow_the_fctl_delays() {
    let mut a = open("blink.png");
    // fcTL delays 1/10, 0/1 (1/30 s), 1/20 as exact fractions; acTL plays three times.
    let t = &a.timeline;
    assert_eq!(t.starts, [0.0, 0.1, 2.0 / 15.0]);
    assert_eq!(t.total, 11.0 / 60.0);
    assert_eq!(t.loops, 3);
    // Speed 2 from an offset of 1 s: 1.06 s is 0.12 s into the loop.
    assert_eq!(t.frame(1.06, 1.0, 2.0), 1);
    assert_eq!(t.frame(3.5 * t.total, 0.0, 1.0), 2);
    assert_eq!(frames(&mut a), expected());
}

#[test]
fn still_images_are_not_animated() {
    let dir = std::env::temp_dir().join("mds-mmert-anime");
    std::fs::create_dir_all(&dir).unwrap();
    let still = dir.join("still.png");
    let mut out = Vec::new();
    let mut enc = png::Encoder::new(&mut out, 1, 1);
    enc.set_color(png::ColorType::Rgba);
    enc.write_header().unwrap().write_image_data(&R).unwrap();
    std::fs::write(&still, out).unwrap();
    let err = Anime::open(&still).err().unwrap();
    assert_eq!(
        err,
        format!(
            "failed to open '{}': source image must be animated\n",
            still.display()
        )
    );
}

#[test]
fn corpus_gifs_decode() {
    let corpus = match std::env::var_os("MDS_CORPUS") {
        Some(p) => std::path::PathBuf::from(p),
        None => std::env::temp_dir().join("mds-corpus"),
    }
    .join("ray-mmd");
    if !corpus.is_dir() {
        eprintln!(
            "SKIP: no corpus at {} (a skip is not a pass)",
            corpus.display()
        );
        return;
    }
    for rel in [
        "Materials/Emissive/BodyLine/bodyline.gif",
        "Materials/Emissive/Rainbow/rainbow.gif",
        "Lighting/RectangleLight/Default GIF/texture/rance.gif",
    ] {
        let mut a = Anime::open(&corpus.join(rel)).unwrap();
        let n = a.timeline.starts.len();
        eprintln!(
            "{rel}: {}x{}, {n} frames, {:.3} s",
            a.width, a.height, a.timeline.total
        );
        assert!(n > 1 && a.timeline.total > 0.0);
        let last = a.pixels(n - 1).to_vec();
        assert_eq!(last.len(), (a.width * a.height * 4) as usize);
        assert!(
            last.iter().any(|&b| b != 0),
            "{rel}: the last frame is empty"
        );
    }
}
