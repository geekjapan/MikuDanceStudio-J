//! Replays the `tools/keypool_check` operation sequences through the Rust
//! operations and compares every pool state with the C++ harness's dump.
//!
//! The dump (`tests/data/keypool-depth4.txt`) holds, for each UI
//! configuration of the harness, the explored states at depth 4 and the
//! successor of every state under every command (see `WriteDumpHeader` in
//! `tools/keypool_check/keypool_check.cpp`).
//! Regenerate it with
//!
//!     tools/keypool_check/run.sh 4 --dump rust/crates/mds-edit/tests/data/keypool-depth4.txt
//!
//! A state is checked as the records its sequence changes (payload
//! included); a transition is checked at the harness's own resolution
//! (frames, links, marks and the cursor).

use mds_edit::{
    BoneClip, BoneExtra, BoneInfo, BoneTarget, DisplayClip, Extra, IkChain, MorphClip, MorphInfo,
    Rig, Selector, Tracks,
};
use mds_formats::pmm::{BoneKey, DisplayKey, MorphKey};
use std::collections::HashMap;

const WINDOW: u32 = 24;
/// Shift-JIS 右b and 左b.
const BONE_NAMES: [&[u8]; 2] = [b"\x89\x45b", b"\x8D\xB6b"];
const ROOT: &[u8] = b"\x83\x8B\x81\x5B\x83\x67";

/// `BuildModel` of the harness: bone0 moves and has a rigid body, bone1 is
/// the IK bone and a fixed-axis bone.
fn rig() -> Rig {
    let bone = |i: usize| BoneInfo {
        name: BONE_NAMES[i].to_vec(),
        ..BoneInfo::new("")
    };
    let rigid = BoneInfo {
        rigid_body: true,
        ..bone(0)
    };
    let twist = BoneInfo {
        writes_position: false,
        twist: true,
        translation: [1.0, 0.25, 0.0],
        ..bone(1)
    };
    Rig {
        bones: vec![rigid, twist],
        morphs: ["morph0", "morph1"]
            .map(|n| MorphInfo {
                name: n.into(),
                value: 0.0,
            })
            .to_vec(),
        ik_chains: vec![IkChain {
            bone: 1,
            enabled: 1,
        }],
        selectors: vec![
            Selector {
                bone: -1i32 as u32,
                linked_model: -1,
                linked_bone: 0,
            },
            Selector {
                bone: 0,
                linked_model: 2,
                linked_bone: 1,
            },
        ],
        pmx: true,
        load_complete: 1,
        auto_interpolation: false,
    }
}

fn extra() -> Extra {
    Extra {
        bones: vec![
            BoneExtra {
                physics_rotation: [0.0, 0.6, 0.0, 0.8],
                ..BoneExtra::default()
            },
            BoneExtra {
                axis: [0.48, 0.6, 0.64],
                ..BoneExtra::default()
            },
        ],
        ..Extra::default()
    }
}

/// The model state the commands change.
#[derive(Clone)]
struct Model {
    tracks: Tracks,
    rig: Rig,
    extra: Extra,
}

/// `BoneClip` of the harness.
fn bone_clip(name: &[u8], frame: u32) -> BoneClip {
    let mut interpolation = [0u8; 16];
    for (j, b) in interpolation.iter_mut().enumerate() {
        *b = (7 * j as u32 + frame) as u8;
    }
    BoneClip {
        name: name.to_vec(),
        frame: 0,
        rotation: if frame % 2 == 1 {
            [-0.3, 0.1, -0.2, 0.9273618]
        } else {
            [0.1, 0.2, 0.3, 0.9273618]
        },
        position: [1.5 * frame as f32, 0.5, -0.25],
        physics_disabled: (frame & 1) as u8,
        interpolation,
    }
}

#[derive(Clone, Copy, Debug)]
struct Op {
    kind: Kind,
    target: usize,
    frame: u32,
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Kind {
    PasteBone,
    PasteMorph,
    PasteDisplay,
    RegisterBone,
    RegisterMorph,
    RegisterDisplay,
    SelectBone,
    Delete,
    PasteMirrored,
    PasteToSelected,
}

impl Kind {
    fn parse(s: &str) -> Kind {
        match s {
            "paste-bone" => Kind::PasteBone,
            "paste-morph" => Kind::PasteMorph,
            "paste-display" => Kind::PasteDisplay,
            "register-bone" => Kind::RegisterBone,
            "register-morph" => Kind::RegisterMorph,
            "register-display" => Kind::RegisterDisplay,
            "select-bone" => Kind::SelectBone,
            "delete" => Kind::Delete,
            "paste-mirrored" => Kind::PasteMirrored,
            "paste-to-selected" => Kind::PasteToSelected,
            _ => panic!("unknown command kind {s}"),
        }
    }
}

/// One command, as the harness's `Apply`/`Paste` replays the UI handler.
fn apply(m: &mut Model, op: Op) {
    let f = op.frame;
    let Model {
        tracks: t,
        rig,
        extra,
    } = m;
    let paste =
        |t: &mut Tracks, bones: &[BoneClip], morphs: &[MorphClip], displays: &[DisplayClip]| {
            t.paste_with(rig, extra, bones, morphs, displays, f as i32)
                .unwrap();
        };
    match op.kind {
        Kind::PasteBone => paste(t, &[bone_clip(BONE_NAMES[op.target], f)], &[], &[]),
        Kind::PasteMorph => paste(
            t,
            &[],
            &[MorphClip {
                name: format!("morph{}", op.target).into_bytes(),
                frame: 0,
                value: 0.25 * (f + 1) as f32,
            }],
            &[],
        ),
        Kind::PasteDisplay => paste(
            t,
            &[],
            &[],
            &[DisplayClip {
                frame: 0,
                visible: if f == 1 { 0 } else { 1 },
                ik: vec![(BONE_NAMES[1].to_vec(), (f & 1) as u8)],
                selectors: vec![
                    (ROOT.to_vec(), -2, f as i32),
                    (BONE_NAMES[0].to_vec(), -2, f as i32),
                ],
            }],
        ),
        Kind::PasteMirrored => {
            let clip = bone_clip(BONE_NAMES[op.target], f);
            t.paste_bones(rig, extra, &[clip], f as i32, BoneTarget::Mirrored)
                .unwrap();
        }
        Kind::PasteToSelected => {
            let clip = bone_clip(BONE_NAMES[1 - op.target], f);
            let target = BoneTarget::Selected(op.target as i32);
            t.paste_bones(rig, extra, &[clip], f as i32, target)
                .unwrap();
        }
        Kind::RegisterBone => {
            extra.bones[0].physics_translation = [0.5 + f as f32, 1.5, -2.0];
            let mut selected = vec![false; rig.bones.len()];
            selected[op.target] = true;
            t.register_selected_bone_keys_with(rig, extra, &selected, f)
                .unwrap();
        }
        Kind::RegisterMorph => {
            t.clear_marks();
            t.register_morph_current(rig, op.target as i32, f).unwrap();
        }
        Kind::RegisterDisplay => {
            t.clear_marks();
            t.register_display_current(rig, f).unwrap();
        }
        // A timeline click marks the one key at that frame of the track.
        Kind::SelectBone => {
            t.clear_marks();
            let mut i = op.target as u32;
            for _ in 0..WINDOW {
                let k = t.bone.get(i).cloned().unwrap_or_default();
                if k.frame == f {
                    t.bone.get_mut(i).unwrap().allocated = 1;
                    break;
                }
                i = k.next;
                if i == 0 {
                    break;
                }
            }
        }
        Kind::Delete => t.delete_marked(rig).unwrap(),
    }
}

// ---- the dump's text for a state ------------------------------------------

fn hex(f: f32) -> String {
    format!("{:x}", f.to_bits())
}

/// The record lines of `StateLines` in the harness: b0..b23, m0..m23,
/// d0..d23, r0..r1, g.
fn state_lines(m: &Model) -> Vec<String> {
    let (t, rig) = (&m.tracks, &m.rig);
    let mut out = Vec::new();
    for i in 0..WINDOW {
        let k: BoneKey = t.bone.get(i).cloned().unwrap_or_default();
        let ip: String = k.interpolation.iter().map(|b| format!("{b:02x}")).collect();
        out.push(format!(
            "b{i} f{} p{} n{} a{} d{} i{ip} x{}.{}.{} q{}.{}.{}.{}",
            k.frame,
            k.previous,
            k.next,
            k.allocated,
            k.physics_disabled,
            hex(k.position[0]),
            hex(k.position[1]),
            hex(k.position[2]),
            hex(k.rotation[0]),
            hex(k.rotation[1]),
            hex(k.rotation[2]),
            hex(k.rotation[3]),
        ));
    }
    for i in 0..WINDOW {
        let k: MorphKey = t.morph.get(i).cloned().unwrap_or_default();
        out.push(format!(
            "m{i} f{} p{} n{} a{} v{}",
            k.frame,
            k.previous,
            k.next,
            k.allocated,
            hex(k.value)
        ));
    }
    for i in 0..WINDOW {
        let k: DisplayKey = t.display.get(i).cloned().unwrap_or(DisplayKey {
            visible: 1,
            ik_enabled: vec![1; rig.ik_chains.len()],
            selectors: vec![[-1, 0]; rig.selectors.len()],
            ..DisplayKey::default()
        });
        let ik: Vec<String> = k.ik_enabled.iter().map(|b| b.to_string()).collect();
        let sel: Vec<String> = k
            .selectors
            .iter()
            .map(|s| format!("{}:{}", s[0], s[1]))
            .collect();
        out.push(format!(
            "d{i} f{} p{} n{} a{} v{} k{} s{}",
            k.frame,
            k.previous,
            k.next,
            k.allocated,
            k.visible,
            ik.join("."),
            sel.join(".")
        ));
    }
    for (i, (b, e)) in rig.bones.iter().zip(&m.extra.bones).enumerate() {
        let (x, q) = (b.translation, b.rotation);
        out.push(format!(
            "r{i} d{} x{}.{}.{} q{}.{}.{}.{}",
            e.physics_disabled,
            hex(x[0]),
            hex(x[1]),
            hex(x[2]),
            hex(q[0]),
            hex(q[1]),
            hex(q[2]),
            hex(q[3]),
        ));
    }
    out.push(format!("g c{} x{}", t.search_cursor, t.max_frame));
    out
}

/// What the harness's `Snapshot` keeps: frame, links and mark of every
/// window record, and the cursor.
fn snapshot(t: &Tracks) -> Vec<u32> {
    let mut v = Vec::new();
    for i in 0..WINDOW {
        let b = t.bone.get(i).cloned().unwrap_or_default();
        v.extend([b.frame, b.previous, b.next, b.allocated.into()]);
    }
    for i in 0..WINDOW {
        let m = t.morph.get(i).cloned().unwrap_or_default();
        v.extend([m.frame, m.previous, m.next, m.allocated.into()]);
    }
    for i in 0..WINDOW {
        let d = t.display.get(i).cloned().unwrap_or_default();
        v.extend([d.frame, d.previous, d.next, d.allocated.into()]);
    }
    v.push(t.search_cursor);
    v
}

/// The harness cuts a transition when the cursor or a link leaves the window.
fn leaves_window(t: &Tracks) -> bool {
    fn out<K: mds_formats::key_pool::Key>(p: &mds_formats::key_pool::KeyPool<K>) -> bool {
        let far = |i: u32, k: &K| k.next() >= WINDOW || (i >= WINDOW && k.frame() != 0);
        p.heads().iter().enumerate().any(|(i, k)| far(i as u32, k))
            || p.records().iter().any(|(i, k)| far(*i, k))
    }
    t.search_cursor >= WINDOW || out(&t.bone) || out(&t.morph) || out(&t.display)
}

struct State {
    model: Model,
    lines: Vec<String>,
}

type Lines<'a> = std::iter::Peekable<std::str::Lines<'a>>;

/// Replays one `config` section. Returns (states, transitions, cuts).
fn replay_section(lines: &mut Lines, alphabet: &[Op], start: Model) -> (usize, usize, usize) {
    let mut states: Vec<State> = Vec::new();
    let mut snapshots: HashMap<Vec<u32>, usize> = HashMap::new();
    let mut tree: Vec<(usize, usize)> = Vec::new(); // (parent, command) by state id
    let trace = |tree: &[(usize, usize)], id: usize| {
        let mut ops = Vec::new();
        let mut at = id;
        while tree[at].0 != usize::MAX {
            ops.push(format!("{:?}", alphabet[tree[at].1]));
            at = tree[at].0;
        }
        ops.reverse();
        ops.join(" -> ")
    };

    // S blocks: one per state, in discovery order.
    while let Some(head) = lines.next_if(|l| l.starts_with("S ")) {
        let f: Vec<&str> = head.split(' ').collect();
        let id: usize = f[1].parse().unwrap();
        assert_eq!(id, states.len(), "state ids are consecutive");
        let mut expected: Vec<&str> = Vec::new();
        while let Some(l) = lines.next_if(|l| l.starts_with(' ')) {
            expected.push(&l[1..]);
        }
        let (model, got, parent, cmd) = if f[2] == "-" {
            let l = state_lines(&start);
            (start.clone(), l, usize::MAX, usize::MAX)
        } else {
            let parent: usize = f[2].parse().unwrap();
            let cmd: usize = f[3].parse().unwrap();
            let mut m = states[parent].model.clone();
            apply(&mut m, alphabet[cmd]);
            let delta: Vec<String> = state_lines(&m)
                .into_iter()
                .zip(&states[parent].lines)
                .filter(|(a, b)| a != *b)
                .map(|(a, _)| a)
                .collect();
            (m, delta, parent, cmd)
        };
        tree.push((parent, cmd));
        assert!(
            got.iter().map(String::as_str).eq(expected.iter().copied()),
            "state {id} differs after {}\n  C++ : {expected:#?}\n  Rust: {got:#?}",
            trace(&tree, id)
        );
        snapshots.insert(snapshot(&model.tracks), id);
        let lines = state_lines(&model);
        states.push(State { model, lines });
    }

    // T lines: the successor of every state under every command.
    let (mut transitions, mut cuts) = (0, 0);
    while let Some(l) = lines.next_if(|l| l.starts_with("T ")) {
        let f: Vec<&str> = l.split(' ').collect();
        let id: usize = f[1].parse().unwrap();
        assert_eq!(f.len() - 2, alphabet.len());
        for (c, to) in f[2..].iter().enumerate() {
            let mut m = states[id].model.clone();
            apply(&mut m, alphabet[c]);
            transitions += 1;
            if *to == "-" {
                cuts += 1;
                assert!(
                    leaves_window(&m.tracks),
                    "state {id} cmd {c}: C++ cut it, Rust stays in the window"
                );
            } else {
                let to: usize = to.parse().unwrap();
                assert_eq!(
                    snapshots.get(&snapshot(&m.tracks)),
                    Some(&to),
                    "transition from state {id} ({}) by {:?} should reach state {to}",
                    trace(&tree, id),
                    alphabet[c]
                );
            }
        }
    }
    (states.len(), transitions, cuts)
}

#[test]
fn rust_operations_reproduce_the_cpp_dump() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/data/keypool-depth4.txt");
    let text = std::fs::read_to_string(path).unwrap();
    let mut lines = text.lines().peekable();
    assert_eq!(lines.next(), Some("keypool-dump 2"));
    assert_eq!(lines.next(), Some("depth 4"));
    assert_eq!(lines.next(), Some("bones 2 morphs 2 frames 3 window 24"));

    let mut alphabet: Vec<Op> = Vec::new();
    while let Some(l) = lines.next_if(|l| l.starts_with("C ")) {
        let f: Vec<&str> = l.split(' ').collect();
        assert_eq!(f[1].parse::<usize>().unwrap(), alphabet.len());
        alphabet.push(Op {
            kind: Kind::parse(f[2]),
            target: f[3].parse().unwrap(),
            frame: f[4].parse().unwrap(),
        });
    }

    let mut configs = 0;
    while let Some(l) = lines.next_if(|l| l.starts_with("config ")) {
        let f: Vec<i32> = l.split(' ').skip(1).map(|v| v.parse().unwrap()).collect();
        let mut start = Model {
            tracks: Tracks::new(&rig()),
            rig: rig(),
            extra: extra(),
        };
        start.rig.auto_interpolation = f[0] != 0;
        start.extra.physics_checkbox = f[1] != 0;
        start.extra.physics_mode = f[2];
        let (states, transitions, cuts) = replay_section(&mut lines, &alphabet, start);
        println!(
            "keypool replay, {l}: {states} states and {transitions} transitions compared ({cuts} cut at the window bound)"
        );
        assert!(
            states > 12_000 && transitions > 120_000,
            "{l}: dump is not the depth 4 run"
        );
        configs += 1;
    }
    assert_eq!(lines.next(), None, "unparsed lines at the end of the dump");
    assert_eq!(configs, 4, "configurations in the dump");
}
