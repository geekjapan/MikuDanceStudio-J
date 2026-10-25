//! PMM version 0001 scenes (`tests/fixtures/rust/pmm1`, written by
//! `gen_pmm1.py`) read into the `Pmm` of the 0002 reader. The dump of each
//! oracle fixture is the output of `tools/pmm1_check`, the portable C++
//! reader of `next` with the rules of `src/io/pmm_load_v1.cpp` applied; see
//! `tools/pmm1_check/dump.cpp` for the line format that `render` repeats.

use std::fmt::Write as _;
use std::path::PathBuf;

use mds_formats::key_pool::{Key, KeyPool};
use mds_formats::pmd::Pmd;
use mds_formats::pmm::{Pmm, Tail};
use mds_formats::text::FixedSjis;

const ORACLE: [&str; 3] = ["v1_rig", "v1_scene", "v1_multi"];
const SCENES: [&str; 5] = ["v1_rig", "v1_scene", "v1_multi", "v1_noparent", "v1_edge"];

fn dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust/pmm1")
}

fn load(name: &str) -> Vec<u8> {
    let path = dir().join(name);
    std::fs::read(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

fn pmd_of(path: &FixedSjis<256>) -> Option<Pmd> {
    let end = path.raw.iter().position(|&b| b == 0).unwrap_or(256);
    let name = std::str::from_utf8(&path.raw[..end]).ok()?;
    Pmd::read(&std::fs::read(dir().join(name)).ok()?).ok()
}

fn read(data: &[u8]) -> Result<Pmm, mds_formats::Error> {
    Pmm::read_with(data, |_, _, path| pmd_of(path))
}

fn scene(name: &str) -> Pmm {
    read(&load(&format!("{name}.pmm"))).unwrap_or_else(|e| panic!("{name}: {e}"))
}

fn f(v: f32) -> String {
    format!(" {:08x}", v.to_bits())
}

fn fs(v: &[f32]) -> String {
    v.iter().map(|&x| f(x)).collect()
}

fn ns<T: std::fmt::Display>(v: &[T]) -> String {
    v.iter().map(|x| format!(" {x}")).collect()
}

fn s(raw: &[u8]) -> String {
    let end = raw.iter().position(|&b| b == 0).unwrap_or(raw.len());
    format!(" s:{}", String::from_utf8_lossy(&raw[..end]))
}

fn track<K: Key>(
    out: &mut String,
    heads: &str,
    rows: &str,
    pool: &KeyPool<K>,
    row: impl Fn(&K) -> String,
) {
    let n = pool.heads().len();
    writeln!(out, "{heads} {n} {}", pool.records().len()).unwrap();
    let all = pool
        .heads()
        .iter()
        .enumerate()
        .map(|(i, k)| (i as u32, k))
        .chain(pool.records().iter().map(|(i, k)| (*i, k)));
    for (i, k) in all {
        writeln!(
            out,
            "{rows} {i} {} {} {}{}",
            k.frame(),
            k.previous(),
            k.next(),
            row(k)
        )
        .unwrap();
    }
}

/// The text that `tools/pmm1_check/dump.cpp` prints for the same scene.
fn render(p: &Pmm) -> String {
    let mut o = String::new();
    let st = &p.settings;
    writeln!(
        o,
        "settings {} {} {}{}{}",
        st.render_width,
        st.render_height,
        st.panel_width,
        f(st.camera_fov),
        ns(&st.options)
    )
    .unwrap();
    writeln!(
        o,
        "selected {} models {}",
        p.selected_model_slot,
        p.models.len()
    )
    .unwrap();
    for m in &p.models {
        let l = &m.selection;
        writeln!(
            o,
            "model {} bones {} morphs {} ik {}",
            m.slot,
            m.bone_names.len(),
            m.morph_names.len(),
            m.ik_bones.len()
        )
        .unwrap();
        writeln!(
            o,
            "sel {} {} {}{} {} {}",
            l.combo_index,
            l.load_complete,
            l.selected_bone,
            ns(&l.selected_morphs),
            l.bone_list_pos,
            l.max_frame
        )
        .unwrap();
        writeln!(o, "groups{}", ns(&l.group_flags)).unwrap();
        writeln!(
            o,
            "flags {}{} {} {}",
            m.post_load,
            f(m.edge_scale),
            m.toon,
            m.display_order
        )
        .unwrap();
        track(&mut o, "bonekeys", "bk", &m.bone_keys, |k| {
            format!(
                "{}{}{} {}",
                ns(&k.interpolation),
                fs(&k.position),
                fs(&k.rotation),
                k.allocated
            )
        });
        track(&mut o, "morphkeys", "mk", &m.morph_keys, |k| {
            format!("{} {}", f(k.value), k.allocated)
        });
        track(&mut o, "displaykeys", "dk", &m.display_keys, |k| {
            format!(" {}{} {}", k.visible, ns(&k.ik_enabled), k.allocated)
        });
        for (i, b) in m.bone_pose.iter().enumerate() {
            writeln!(
                o,
                "bp {i}{}{} {} {}",
                fs(&b.translation),
                fs(&b.rotation),
                b.flags[1],
                b.flags[2]
            )
            .unwrap();
        }
        for (i, v) in m.morph_pose.iter().enumerate() {
            writeln!(o, "mp {i}{}", f(*v)).unwrap();
        }
        for (i, v) in m.ik_pose.iter().enumerate() {
            writeln!(o, "ip {i} {v}").unwrap();
        }
    }
    track(&mut o, "camerakeys", "ck", &p.camera, |k| {
        let curve: Vec<u8> = k.interpolation.iter().flatten().copied().collect();
        format!(
            "{}{}{} {} {}{} {} {} {}",
            f(k.distance),
            fs(&k.eye),
            fs(&k.target),
            k.parent_model,
            k.parent_bone,
            ns(&curve),
            k.perspective,
            k.fov,
            k.selected
        )
    });
    writeln!(
        o,
        "camerastate{} {}",
        fs(&p.camera_state),
        p.camera_perspective
    )
    .unwrap();
    track(&mut o, "lightkeys", "lk", &p.light, |k| {
        format!("{}{} {}", fs(&k.color), fs(&k.direction), k.selected)
    });
    writeln!(o, "lightstate{}", fs(&p.light_state)).unwrap();
    writeln!(
        o,
        "accessories selected {} scroll {} count {}",
        p.selected_accessory_slot,
        p.display_list_scroll,
        p.accessories.len()
    )
    .unwrap();
    for a in &p.accessories {
        writeln!(
            o,
            "acc {}{}{}{} {}",
            a.slot,
            s(&a.list_name.raw),
            s(&a.name.raw),
            s(&a.path.raw),
            a.order
        )
        .unwrap();
        track(&mut o, "accessorykeys", "ak", &a.keys, |k| {
            format!(
                " {} {} {}{}{}{} {} {}",
                k.opacity_visible,
                k.parent_model,
                k.parent_bone,
                fs(&k.position),
                fs(&k.rotation),
                f(k.scale),
                k.shadow,
                k.selected
            )
        });
        let t = &a.state;
        writeln!(
            o,
            "accstate {} {} {}{}{}{} {} {}",
            t.opacity_visible,
            t.parent_model,
            t.parent_bone,
            fs(&t.rotation),
            f(t.scale),
            fs(&t.position),
            t.shadow,
            t.additive
        )
        .unwrap();
    }
    let t = &p.timeline;
    writeln!(
        o,
        "timeline {} {} {} {} {} {} {} {} {} {}",
        t.current_frame,
        t.start_frame,
        t.last_registered_frame,
        t.edit_mode,
        t.camera_reference_mode,
        t.playback_loop,
        t.return_to_start,
        t.start_at_current,
        t.play_start_frame,
        t.play_stop_frame
    )
    .unwrap();
    writeln!(o, "wave {}{}", p.wave.enabled, s(&p.wave.path.raw)).unwrap();
    for (tag, b) in [("avi", &p.avi), ("picture", &p.picture)] {
        writeln!(
            o,
            "{tag} {} {}{}{} {}",
            b.offset[0],
            b.offset[1],
            f(b.scale),
            s(&b.path.raw),
            b.enabled
        )
        .unwrap();
    }
    let v = &p.view;
    writeln!(
        o,
        "view {} {} {}{} {}",
        v.fps_overlay,
        v.ground_grid,
        v.ground_shadow,
        f(v.fps_limit),
        v.capture_mode
    )
    .unwrap();
    let h = &p.physics;
    writeln!(
        o,
        "physics {}{} {} {}{} {}{} {}",
        h.accessory_render_order,
        f(h.projected_shadow_ambient),
        h.projected_shadow_blend,
        h.playback_mode,
        f(h.gravity_magnitude),
        h.gravity_noise,
        fs(&h.gravity_direction),
        h.gravity_noise_enabled
    )
    .unwrap();
    writeln!(
        o,
        "selfshadow {}{}",
        p.self_shadow_mode,
        f(p.physics_interval)
    )
    .unwrap();
    track(&mut o, "selfshadowkeys", "sk", &p.self_shadow, |k| {
        format!(" {}{} {}", k.mode, f(k.distance), k.selected)
    });
    let a = &p.appearance;
    writeln!(
        o,
        "appearance{} {} {} {}{} {} {} {} {}",
        ns(&a.outline_color),
        a.black_background,
        a.camera_parent_model,
        a.camera_parent_bone,
        fs(&a.camera_attachment_basis),
        a.follow_camera,
        a.suppress_camera_transform,
        a.floor_visible,
        a.max_frame
    )
    .unwrap();
    o.push_str("registrations");
    if let Tail::Registrations(rs) = &p.tail {
        for r in rs {
            write!(o, " {}:{}", r.slot, r.selection).unwrap();
        }
    }
    o.push('\n');
    o
}

#[test]
fn the_oracle_dumps_match() {
    for name in ORACLE {
        let path = dir().join("expected").join(format!("{name}.dump"));
        let Ok(expected) = std::fs::read_to_string(&path) else {
            println!("SKIP {name}: no {}", path.display());
            continue;
        };
        let got = render(&scene(name));
        if let Some((n, (a, b))) = expected
            .lines()
            .zip(got.lines())
            .enumerate()
            .find(|(_, (a, b))| a != b)
        {
            panic!("{name}: line {}\n oracle: {a}\n   rust: {b}", n + 1);
        }
        assert_eq!(
            expected.lines().count(),
            got.lines().count(),
            "{name}: line count"
        );
    }
}

#[test]
fn a_saved_scene_is_a_0002_that_reads_back_to_the_same_scene() {
    for name in SCENES {
        let p = scene(name);
        let bytes = p.write().unwrap_or_else(|e| panic!("{name}: {e}"));
        assert!(bytes.starts_with(b"Polygon Movie maker 0002\0"), "{name}");
        let q = Pmm::read(&bytes).unwrap_or_else(|e| panic!("{name}: {e}"));
        assert_eq!(format!("{p:?}"), format!("{q:?}"), "{name}");
        assert!(q.write().unwrap() == bytes, "{name}: second write differs");
    }
}

#[test]
fn the_pmd_gives_the_counts_names_and_selectors_the_stream_leaves_out() {
    let p = scene("v1_multi");
    let slots: Vec<u8> = p.models.iter().map(|m| m.slot).collect();
    assert_eq!(slots, [1, 3, 5]);
    let chain = &p.models[0];
    assert_eq!(chain.bone_names.len(), 8);
    assert_eq!(chain.morph_names.len(), 0);
    assert_eq!(chain.group_count, 4);
    assert_eq!(chain.selector_bones, [-1, 0, 1]);
    let rig = &p.models[1];
    assert_eq!(rig.name.text, "rig3");
    assert_eq!(rig.name_en.text, "rig3");
    assert_eq!(rig.bone_names[3].text, "腕ＩＫ");
    assert_eq!(rig.morph_names.len(), 3);
    assert_eq!(rig.ik_bones, [3]);
    assert_eq!(rig.selector_bones, [-1, 0, 3]);
    assert_eq!(rig.group_count, 4);
    assert_eq!(rig.selector_pose, vec![[0, 0, -1, 0]; 3]);
    assert!(rig.display_keys.heads()[0]
        .selectors
        .iter()
        .all(|&s| s == [-1, 0]));
}

#[test]
fn a_group_flag_count_that_differs_from_the_pmd_keeps_the_pmd_count() {
    let p = scene("v1_edge");
    let m = &p.models[0];
    assert_eq!(m.group_count, 4);
    assert_eq!(m.selection.group_flags, [1, 0, 1, 0]);
}

#[test]
fn a_sparse_record_with_frame_zero_is_dropped() {
    let p = scene("v1_edge");
    let keys = &p.models[0].bone_keys;
    assert_eq!(keys.records().len(), 3);
    assert!(keys.records().iter().all(|(_, k)| k.frame != 0));
}

#[test]
fn without_a_camera_parent_the_list_is_not_read() {
    let p = scene("v1_noparent");
    assert_eq!(p.camera.heads()[0].parent_model, -1);
    assert_eq!(p.appearance.camera_parent_model, -1);
    assert_eq!(p.appearance.floor_visible, 1);
    assert_eq!(p.models[0].display_order, 4);
}

#[test]
fn a_tail_that_stops_at_a_gate_keeps_the_defaults_after_it() {
    let p = scene("v1_multi");
    assert_eq!(p.appearance.floor_visible, 1);
    assert_eq!(p.appearance.outline_color, [0; 3]);
    assert_eq!(
        p.models.iter().map(|m| m.display_order).collect::<Vec<_>>(),
        [1, 1, 3]
    );
    assert_eq!(
        p.models.iter().map(|m| m.toon).collect::<Vec<_>>(),
        [1, 0, 1]
    );
    let none = scene("v1_scene");
    assert_eq!(none.physics.playback_mode, 2);
    assert!(matches!(&none.tail, Tail::Registrations(r) if r.len() == 1 && r[0].selection == 3));
}

fn find(data: &[u8], needle: &[u8]) -> usize {
    let at: Vec<usize> = data
        .windows(needle.len())
        .enumerate()
        .filter(|(_, w)| *w == needle)
        .map(|(i, _)| i)
        .collect();
    assert_eq!(at.len(), 1, "{needle:?} matches {at:?}");
    at[0]
}

fn links(frame: u32, previous: u32, next: u32) -> Vec<u8> {
    [frame, previous, next]
        .iter()
        .flat_map(|v| v.to_le_bytes())
        .collect()
}

#[test]
fn a_broken_bone_chain_ends_at_the_last_consistent_key() {
    let mut data = load("v1_rig.pmm");
    // Bone 2's chain is head 2, records 4 (frame 5), 8 (40) and 9 (41).
    let at = find(&data, &links(40, 4, 9));
    data[at + 4..at + 8].copy_from_slice(&99u32.to_le_bytes());
    let keys = read(&data).unwrap();
    let pool = &keys.models[0].bone_keys;
    assert_eq!(pool.get(4).unwrap().next, 0);
    assert_eq!(pool.get(8).unwrap().next, 9);
    assert_eq!(pool.get(2).unwrap().next, 4);
}

#[test]
fn a_scene_that_cannot_be_read_is_an_error() {
    let rig = load("v1_rig.pmm");
    let scene = load("v1_scene.pmm");
    let multi = load("v1_multi.pmm");
    assert!(
        read(&rig[..rig.len() - 1]).is_err(),
        "cut inside the last section"
    );
    assert!(
        read(&rig[..rig.len() - 40]).is_err(),
        "cut inside a section"
    );
    assert!(
        read(&scene[..scene.len() - 1]).is_err(),
        "cut inside the configuration"
    );
    let mut longer = scene.clone();
    longer.push(0);
    assert!(
        read(&longer).is_err(),
        "a byte after a scene without a tail"
    );
    let mut longer = multi.clone();
    longer.push(0);
    assert!(read(&longer).is_err(), "a byte after a gate byte of 0");

    let name = b"chain8.pmd";
    let slot = find(&multi, name) - 21;
    let mut dup = multi.clone();
    dup[slot] = 5;
    assert!(read(&dup).is_err(), "the same slot twice");
    dup[slot] = 255;
    assert!(read(&dup).is_err(), "slot 255");

    let missing = Pmm::read_with(&multi, |_, _, path| {
        pmd_of(path).filter(|pmd| pmd.bones.len() != 8)
    });
    assert!(missing.is_err(), "a model file that cannot be opened");
}

#[test]
fn the_0002_reader_names_the_missing_model_files() {
    let err = Pmm::read(&load("v1_rig.pmm")).unwrap_err().to_string();
    assert!(err.contains("version 1"), "{err}");
}
