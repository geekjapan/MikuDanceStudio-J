//! What `SaveSceneFile` (`src/io/pmm_save.cpp`) writes differently from a
//! plain `Pmm::write` of the scene as read. The list is in the crate doc.

use mds_formats::pmm::{Pmm, Registration, Tail};
use mds_formats::text::{FixedSjis, Sjis};

/// `frameRegistrationSelection` of a fresh model (`model_init.cpp`), which
/// a file without the registration tail leaves in place.
pub(crate) const DEFAULT_REGISTRATION: i32 = 3;

fn flag(b: &mut u8) {
    *b = u8::from(*b != 0);
}

fn cstr(raw: &[u8]) -> &[u8] {
    &raw[..raw.iter().position(|&b| b == 0).unwrap_or(raw.len())]
}

fn name(s: &mut Sjis) {
    let n = cstr(&s.raw).len();
    s.raw.truncate(n);
}

fn fixed<const N: usize>(raw: [u8; N]) -> FixedSjis<N> {
    FixedSjis {
        text: mds_formats::text::decode_sjis(&raw),
        raw,
    }
}

/// The transparency byte through the float the C++ keeps:
/// `opacity = (100 - (b >> 1)) / 100.0f` on load, then `ScaleQuirkByte`.
pub fn opacity_byte(b: u8) -> u8 {
    let opacity = (100 - i32::from(b >> 1)) as f32 / 100.0;
    opacity_visible(opacity, b & 1)
}

/// `ScaleQuirkByte`: `(char)((-0x1C - (int)(opacity * 100.0)) * 2)`, plus 1
/// when visible.
pub fn opacity_visible(opacity: f32, visible: u8) -> u8 {
    let v = (f64::from(opacity) * 100.0) as i32;
    ((-0x1C_i32).wrapping_sub(v).wrapping_mul(2) as u8).wrapping_add(u8::from(visible != 0))
}

/// `atol` of the first `max - 1` characters of the edit text the C++ reads
/// back (`GetWindowTextA(edit, buf, max)`).
fn edit_readback(v: i32, max: usize) -> i32 {
    let text = v.to_string();
    let text = &text[..text.len().min(max - 1)];
    text.parse().unwrap_or(0)
}

/// The shared 256-byte `text` buffer of `SaveSceneFile`. It starts zeroed;
/// each conversion writes the string and its NUL and leaves the rest.
struct Scratch([u8; 256]);

impl Scratch {
    /// `WideToSjis`, which leaves the buffer untouched for an empty path.
    fn path(&mut self, raw: &[u8]) -> [u8; 256] {
        let s = cstr(raw);
        if !s.is_empty() {
            self.put(s);
        }
        self.0
    }
    /// `CB_GETLBTEXT`: always writes, if only the NUL.
    fn put(&mut self, s: &[u8]) {
        let n = s.len().min(255);
        self.0[..n].copy_from_slice(&s[..n]);
        self.0[n] = 0;
    }
}

/// A path written after `memset(text, 0, 0x100)`.
fn zeroed_path(raw: &[u8; 256]) -> [u8; 256] {
    let mut out = [0; 256];
    let s = cstr(raw);
    out[..s.len()].copy_from_slice(s);
    out
}

/// The scene as `SaveSceneFile` writes it.
pub fn normalize(src: &Pmm) -> Pmm {
    let mut p = src.clone();
    p.header = [0; 30];
    p.header[..24].copy_from_slice(b"Polygon Movie maker 0002");
    p.settings.options.iter_mut().for_each(flag);

    // Model and accessory blocks are written in slot order.
    p.models.sort_by_key(|m| m.slot);
    let names: Vec<_> = p.accessories.iter().map(|a| a.list_name.clone()).collect();
    p.accessories.sort_by_key(|a| a.slot);

    let mut text = Scratch([0; 256]);
    for m in &mut p.models {
        name(&mut m.name);
        name(&mut m.name_en);
        m.path = fixed(text.path(&m.path.raw));
        m.bone_names.iter_mut().for_each(name);
        m.morph_names.iter_mut().for_each(name);
        let s = &mut m.selection;
        flag(&mut s.load_complete);
        s.group_count_repeat = m.group_count;
        s.group_flags.iter_mut().for_each(flag);
        for k in m.bone_keys.heads_mut() {
            flag(&mut k.allocated);
            flag(&mut k.physics_disabled);
        }
        for_records(&mut m.bone_keys, |k| {
            flag(&mut k.allocated);
            flag(&mut k.physics_disabled);
        });
        m.morph_keys
            .heads_mut()
            .iter_mut()
            .for_each(|k| flag(&mut k.allocated));
        for_records(&mut m.morph_keys, |k| flag(&mut k.allocated));
        let display = |k: &mut mds_formats::pmm::DisplayKey| {
            flag(&mut k.visible);
            k.ik_enabled.iter_mut().for_each(flag);
            flag(&mut k.allocated);
        };
        m.display_keys.heads_mut().iter_mut().for_each(display);
        for_records(&mut m.display_keys, display);
        for b in &mut m.bone_pose {
            b.flags.iter_mut().for_each(flag);
        }
        m.ik_pose.iter_mut().for_each(flag);
        flag(&mut m.post_load);
        flag(&mut m.toon);
    }

    let camera = |k: &mut mds_formats::pmm::CameraKey| {
        flag(&mut k.perspective);
        flag(&mut k.selected);
    };
    p.camera.heads_mut().iter_mut().for_each(camera);
    for_records(&mut p.camera, camera);
    flag(&mut p.camera_perspective);
    p.light
        .heads_mut()
        .iter_mut()
        .for_each(|k| flag(&mut k.selected));
    for_records(&mut p.light, |k| flag(&mut k.selected));

    for (a, list) in p.accessories.iter_mut().zip(&names) {
        text.put(cstr(&list.raw));
        let mut raw = [0; 100];
        raw.copy_from_slice(&text.0[..100]);
        a.list_name = fixed(raw);
    }
    for a in &mut p.accessories {
        // `strcpy_s` into the accessory record on load.
        let mut raw = [0; 100];
        let s = cstr(&a.name.raw);
        raw[..s.len()].copy_from_slice(s);
        a.name = fixed(raw);
        a.path = fixed(text.path(&a.path.raw));
        let key = |k: &mut mds_formats::pmm::AccessoryKey| {
            k.opacity_visible = opacity_byte(k.opacity_visible);
            flag(&mut k.shadow);
            flag(&mut k.selected);
        };
        a.keys.heads_mut().iter_mut().for_each(key);
        for_records(&mut a.keys, key);
        let s = &mut a.state;
        s.opacity_visible = opacity_byte(s.opacity_visible);
        flag(&mut s.shadow);
        flag(&mut s.additive);
    }

    let t = &mut p.timeline;
    flag(&mut t.playback_loop);
    flag(&mut t.return_to_start);
    flag(&mut t.start_at_current);
    t.play_start_frame = edit_readback(t.play_start_frame, 8);
    t.play_stop_frame = edit_readback(t.play_stop_frame, 8);
    flag(&mut p.wave.enabled);
    p.wave.path = fixed(zeroed_path(&p.wave.path.raw));
    p.avi.path = fixed(zeroed_path(&p.avi.path.raw));
    p.picture.path = fixed(zeroed_path(&p.picture.path.raw));
    p.picture.enabled = u32::from(p.picture.enabled != 0);
    flag(&mut p.view.fps_overlay);
    flag(&mut p.view.ground_grid);
    flag(&mut p.view.ground_shadow);
    flag(&mut p.physics.projected_shadow_blend);
    flag(&mut p.physics.gravity_noise_enabled);
    let gravity = |k: &mut mds_formats::pmm::GravityKey| {
        flag(&mut k.noise_enabled);
        flag(&mut k.selected);
    };
    p.gravity.heads_mut().iter_mut().for_each(gravity);
    for_records(&mut p.gravity, gravity);
    flag(&mut p.self_shadow_mode);
    p.self_shadow
        .heads_mut()
        .iter_mut()
        .for_each(|k| flag(&mut k.selected));
    for_records(&mut p.self_shadow, |k| flag(&mut k.selected));
    let a = &mut p.appearance;
    flag(&mut a.black_background);
    flag(&mut a.follow_camera);
    flag(&mut a.suppress_camera_transform);
    flag(&mut a.floor_visible);
    a.max_frame = edit_readback(a.max_frame, 10).max(0);

    // The loader assigns each registration to its slot; the writer emits
    // one per model in slot order.
    let mut by_slot = [DEFAULT_REGISTRATION; 256];
    if let Tail::Registrations(regs) = &src.tail {
        for r in regs {
            by_slot[r.slot as usize] = r.selection;
        }
    }
    p.tail = Tail::Registrations(
        p.models
            .iter()
            .map(|m| Registration {
                slot: m.slot,
                selection: by_slot[m.slot as usize],
            })
            .collect(),
    );
    p
}

/// Applies `f` to every non-head record of a pool.
fn for_records<K: mds_formats::key_pool::Key + Clone>(
    pool: &mut mds_formats::key_pool::KeyPool<K>,
    mut f: impl FnMut(&mut K),
) {
    let indices: Vec<u32> = pool.records().iter().map(|r| r.0).collect();
    for i in indices {
        if let Some(k) = pool.get_mut(i) {
            f(k);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn opacity_byte_through_the_float() {
        // (100 - n) / 100.0f is below the decimal for 65 of the 128 n, so
        // `(int)(opacity * 100.0)` truncates a percent: towards 0, which is
        // up for a positive opacity and down for a negative one.
        let changed: Vec<(u8, u8)> = (0..=255u8)
            .map(|b| (b, opacity_byte(b)))
            .filter(|(b, o)| b != o)
            .collect();
        assert_eq!(changed.len(), 130);
        for (b, o) in [
            (0, 0),
            (1, 1),
            (8, 10),
            (9, 11),
            (100, 100),
            (198, 200),
            (202, 200),
        ] {
            assert_eq!(opacity_byte(b), o, "byte {b}");
        }
        assert!(changed
            .iter()
            .all(|&(b, o)| o == b.wrapping_add(2) || o == b - 2));
    }

    #[test]
    fn edit_readback_keeps_seven_characters() {
        assert_eq!(edit_readback(599, 8), 599);
        assert_eq!(edit_readback(12_345_678, 8), 1_234_567);
        assert_eq!(edit_readback(-1_234_567, 8), -123_456);
        assert_eq!(edit_readback(-5, 10).max(0), 0);
    }
}
