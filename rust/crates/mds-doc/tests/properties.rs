//! Random command sequences over the fixtures: every pool stays valid, and
//! undo then redo gives the saved bytes back. A small deterministic
//! generator, so a failure names its seed.

use mds_doc::history::Entry;
use mds_doc::{Command, Document, GlobalTrack, Track};
use std::path::PathBuf;

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
    fn below(&mut self, n: usize) -> usize {
        (self.next() >> 33) as usize % n
    }
    fn f(&mut self) -> f32 {
        self.below(2001) as f32 / 100.0 - 10.0
    }
    fn v3(&mut self) -> [f32; 3] {
        [self.f(), self.f(), self.f()]
    }
}

fn dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust")
}

const GLOBALS: [GlobalTrack; 4] = [
    GlobalTrack::Camera,
    GlobalTrack::Light,
    GlobalTrack::SelfShadow,
    GlobalTrack::Gravity,
];

fn command(r: &mut Rng, d: &Document) -> Option<Command> {
    let active = d
        .pmm
        .models
        .iter()
        .find(|m| m.slot == d.pmm.selected_model_slot);
    let bones = active.map_or(1, |m| m.bone_names.len().max(1));
    let morphs = active.map_or(1, |m| m.morph_names.len().max(1));
    Some(match r.below(24) {
        0 => {
            let m = &d.pmm.models[r.below(d.pmm.models.len())];
            Command::SelectModel(m.slot)
        }
        1 => Command::SelectCameraMode,
        2 | 3 => Command::SetFrame(r.below(800) as u32),
        4 => Command::SelectBones((0..1 + r.below(3)).map(|_| r.below(bones) as u32).collect()),
        5 => Command::SetBonePose {
            bone: r.below(bones) as u32,
            translation: r.v3(),
            rotation: [0.0, 0.0, 0.0, 1.0],
        },
        6 => Command::SetMorph {
            morph: r.below(morphs) as u32,
            value: r.f() / 10.0,
        },
        7 => Command::SetCamera {
            position: r.v3(),
            rotation: r.v3(),
            distance: r.f() * 4.0,
            fov: 30.0,
            perspective: r.below(2) == 0,
        },
        8 => Command::SetSelfShadow {
            mode: r.below(3) as u8,
            distance: 0.01,
        },
        9 => Command::ClearKeySelection,
        22 => Command::SetLight {
            color: [r.f() / 10.0, 0.5, 0.5],
            direction: r.v3(),
        },
        23 => Command::SetGravity {
            acceleration: r.f(),
            noise: r.below(20) as i32,
            direction: r.v3(),
            noise_enabled: r.below(2) == 0,
        },
        10 | 11 => {
            let track = match r.below(4) {
                0 => Track::Bone(r.below(bones) as u32),
                1 => Track::Morph(r.below(morphs) as u32),
                2 => Track::Display,
                _ => Track::Global(GLOBALS[r.below(4)]),
            };
            let from = r.below(700) as u32;
            Command::SelectKeys {
                track,
                from,
                to: from + r.below(300) as u32,
            }
        }
        12 | 13 => Command::RegisterBoneKeys,
        14 => Command::RegisterMorphKey(r.below(morphs) as i32),
        15 => Command::RegisterDisplayKey,
        16 => {
            Command::RegisterGlobalKeys(GLOBALS.into_iter().filter(|_| r.below(2) == 0).collect())
        }
        17 => Command::Copy,
        18 => Command::Paste,
        19 => {
            // A selected light, self-shadow or gravity head cuts its track
            // when deleted (commands.rs `deleting_the_light_head_cuts_its_track`).
            let p = &d.pmm;
            let heads = [
                p.light.heads()[0].selected,
                p.self_shadow.heads()[0].selected,
                p.gravity.heads()[0].selected,
            ];
            if heads.iter().any(|&s| s != 0) {
                return None;
            }
            Command::DeleteSelectedKeys
        }
        20 => Command::Undo,
        _ => Command::Redo,
    })
}

fn validate(d: &Document, what: &str) {
    let mut r = Vec::new();
    for m in &d.pmm.models {
        r.push(m.bone_keys.validate_tracks());
        r.push(m.morph_keys.validate_tracks());
        r.push(m.display_keys.validate_tracks());
    }
    r.push(d.pmm.camera.validate_tracks());
    r.push(d.pmm.light.validate_tracks());
    r.push(d.pmm.self_shadow.validate_tracks());
    r.push(d.pmm.gravity.validate_tracks());
    if let Some(e) = r.into_iter().find_map(Result::err) {
        panic!("{what}: {e}");
    }
}

/// Undo then redo of the latest entry, on a copy. Redo of a key edit or a
/// frame change re-seeks the entry's frame (`RedoKeyframeEdit` seeks unless
/// the entry is a pose), which re-evaluates every model pose and does not
/// put the frame back; the poses and the frame are taken from before.
fn undo_redo(d: &Document, what: &str) -> bool {
    if d.pmm.settings.options[0] != 0 {
        return false;
    }
    let Some(i) = d
        .pmm
        .models
        .iter()
        .position(|m| m.slot == d.pmm.selected_model_slot)
    else {
        return false;
    };
    let h = &d.edit.models[i].history;
    if !h.undo_dirty {
        return false;
    }
    let entry = h.undo[h.cursor].clone();
    if matches!(entry, Entry::Empty) {
        return false;
    }
    let before = d.save().unwrap();
    let mut c = d.clone();
    c.apply(Command::Undo).unwrap();
    c.apply(Command::Redo)
        .unwrap_or_else(|e| panic!("{what}: redo {e}"));
    if matches!(
        entry,
        Entry::BoneKeys { .. } | Entry::BonePoseWithFrame { .. }
    ) {
        let (cm, dm) = (&mut c.pmm.models[i], &d.pmm.models[i]);
        cm.bone_pose = dm.bone_pose.clone();
        cm.morph_pose = dm.morph_pose.clone();
        cm.ik_pose = dm.ik_pose.clone();
        cm.selector_pose = dm.selector_pose.clone();
        c.pmm.timeline.current_frame = d.pmm.timeline.current_frame;
    }
    assert!(
        c.save().unwrap() == before,
        "{what}: undo then redo after {entry:?}"
    );
    true
}

#[test]
fn random_commands_keep_pools_valid_and_undo_redo_exact() {
    let mut ok = std::collections::BTreeMap::<String, usize>::new();
    let mut checked = 0;
    for name in ["swing600.pmm", "swing600-nophys.pmm", "camera3.pmm"] {
        let Ok(data) = std::fs::read(dir().join(name)) else {
            println!("SKIP {name}: fixture missing");
            continue;
        };
        let base = Document::load(&data, |p| std::fs::read(dir().join(p)).ok()).unwrap();
        if base.pmm.models.is_empty() {
            println!("SKIP {name}: no models");
            continue;
        }
        for seed in 1..=40u64 {
            let mut r = Rng(seed.wrapping_mul(0x9E37_79B9_7F4A_7C15));
            let mut d = base.clone();
            d.apply(Command::ClearKeySelection).unwrap();
            for step in 0..120 {
                let Some(cmd) = command(&mut r, &d) else {
                    continue;
                };
                let what = format!("{name} seed {seed} step {step} {cmd:?}");
                // Errors (full pools, unported paths, no model) leave a
                // valid document too.
                let kind = what.split([' ', '(', '{']).nth(5).unwrap_or("").to_string();
                if d.apply(cmd).is_ok() {
                    *ok.entry(kind).or_default() += 1;
                }
                validate(&d, &what);
                checked += undo_redo(&d, &what) as usize;
            }
        }
    }
    println!("succeeded: {ok:?}; undo-redo checks: {checked}");
    assert!(checked > 0, "no fixture ran");
}
