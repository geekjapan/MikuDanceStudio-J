//! Replays the `tools/keypool_check` operation sequences through the Rust
//! operations and compares every pool state with the C++ harness's dump.
//!
//! The dump (`tests/data/keypool-depth4.txt`) holds the explored states of
//! the harness at depth 4 and the successor of every state under every
//! command (see `WriteDump` in `tools/keypool_check/keypool_check.cpp`).
//! Regenerate it with
//!
//!     tools/keypool_check/run.sh 4 --dump rust/crates/mds-edit/tests/data/keypool-depth4.txt
//!
//! A state is checked as the records its sequence changes (payload
//! included); a transition is checked at the harness's own resolution
//! (frames, links, marks and the cursor).

use mds_edit::{
    BoneClip, BoneInfo, DisplayClip, IkChain, MorphClip, MorphInfo, Rig, Selector, Tracks,
};
use mds_formats::pmm::{BoneKey, DisplayKey, MorphKey};
use std::collections::HashMap;

const WINDOW: u32 = 24;

/// `BuildModel` of the harness.
fn rig() -> Rig {
    Rig {
        bones: vec![BoneInfo::new("bone0"), BoneInfo::new("bone1")],
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
        selectors: vec![Selector {
            bone: 0,
            linked_model: -1,
            linked_bone: 0,
        }],
        pmx: true,
        load_complete: 1,
        auto_interpolation: false,
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
            _ => panic!("unknown command kind {s}"),
        }
    }
}

/// One command, as the harness's `Apply`/`Paste` replays the UI handler.
fn apply(t: &mut Tracks, rig: &Rig, op: Op) {
    let paste =
        |t: &mut Tracks, bones: &[BoneClip], morphs: &[MorphClip], displays: &[DisplayClip]| {
            t.paste(rig, bones, morphs, displays, op.frame as i32)
                .unwrap();
        };
    match op.kind {
        Kind::PasteBone => paste(
            t,
            &[BoneClip {
                name: format!("bone{}", op.target).into_bytes(),
                frame: 0,
                rotation: [0.0, 0.0, 0.0, 1.0],
                position: [0.0; 3],
                physics_disabled: 0,
                interpolation: [0; 16],
            }],
            &[],
            &[],
        ),
        Kind::PasteMorph => paste(
            t,
            &[],
            &[MorphClip {
                name: format!("morph{}", op.target).into_bytes(),
                frame: 0,
                value: 0.0,
            }],
            &[],
        ),
        Kind::PasteDisplay => paste(
            t,
            &[],
            &[],
            &[DisplayClip {
                frame: 0,
                visible: 1,
                ik: vec![],
                selectors: vec![],
            }],
        ),
        Kind::RegisterBone => {
            let mut selected = vec![false; rig.bones.len()];
            selected[op.target] = true;
            t.register_selected_bone_keys(rig, &selected, op.frame)
                .unwrap();
        }
        Kind::RegisterMorph => {
            t.clear_marks();
            t.register_morph_current(rig, op.target as i32, op.frame)
                .unwrap();
        }
        Kind::RegisterDisplay => {
            t.clear_marks();
            t.register_display_current(rig, op.frame).unwrap();
        }
        // A timeline click marks the one key at that frame of the track.
        Kind::SelectBone => {
            t.clear_marks();
            let mut i = op.target as u32;
            for _ in 0..WINDOW {
                let k = t.bone.get(i).cloned().unwrap_or_default();
                if k.frame == op.frame {
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
/// d0..d23, g.
fn state_lines(t: &Tracks, rig: &Rig) -> Vec<String> {
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
    tracks: Tracks,
    lines: Vec<String>,
}

#[test]
fn rust_operations_reproduce_the_cpp_dump() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/data/keypool-depth4.txt");
    let text = std::fs::read_to_string(path).unwrap();
    let mut lines = text.lines().peekable();
    assert_eq!(lines.next(), Some("keypool-dump 1"));
    assert!(lines.next().unwrap().starts_with("depth "));
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

    let rig = rig();
    let mut states: Vec<State> = Vec::new();
    let mut snapshots: HashMap<Vec<u32>, usize> = HashMap::new();
    let trace = |states: &[(usize, usize)], id: usize| {
        let mut ops = Vec::new();
        let mut at = id;
        while states[at].0 != usize::MAX {
            ops.push(format!("{:?}", alphabet[states[at].1]));
            at = states[at].0;
        }
        ops.reverse();
        ops.join(" -> ")
    };
    let mut tree: Vec<(usize, usize)> = Vec::new(); // (parent, command) by state id

    // S blocks: one per state, in discovery order.
    while let Some(head) = lines.next_if(|l| l.starts_with("S ")) {
        let f: Vec<&str> = head.split(' ').collect();
        let id: usize = f[1].parse().unwrap();
        assert_eq!(id, states.len(), "state ids are consecutive");
        let mut expected: Vec<&str> = Vec::new();
        while let Some(l) = lines.next_if(|l| l.starts_with(' ')) {
            expected.push(&l[1..]);
        }
        let (tracks, got, parent, cmd) = if f[2] == "-" {
            let t = Tracks::new(&rig);
            let l = state_lines(&t, &rig);
            (t, l.clone(), usize::MAX, usize::MAX)
        } else {
            let parent: usize = f[2].parse().unwrap();
            let cmd: usize = f[3].parse().unwrap();
            let mut t = states[parent].tracks.clone();
            apply(&mut t, &rig, alphabet[cmd]);
            let l = state_lines(&t, &rig);
            let delta: Vec<String> = l
                .iter()
                .zip(&states[parent].lines)
                .filter(|(a, b)| a != b)
                .map(|(a, _)| a.clone())
                .collect();
            (t, delta, parent, cmd)
        };
        tree.push((parent, cmd));
        assert!(
            got.iter().map(String::as_str).eq(expected.iter().copied()),
            "state {id} differs after {}\n  C++ : {expected:#?}\n  Rust: {got:#?}",
            trace(&tree, id)
        );
        // `lines` of the state: parent lines patched by the delta.
        let full = state_lines(&tracks, &rig);
        snapshots.insert(snapshot(&tracks), id);
        states.push(State {
            tracks,
            lines: full,
        });
    }
    let n_states = states.len();

    // T lines: the successor of every state under every command.
    let mut transitions = 0;
    let mut cuts = 0;
    while let Some(l) = lines.next_if(|l| l.starts_with("T ")) {
        let f: Vec<&str> = l.split(' ').collect();
        let id: usize = f[1].parse().unwrap();
        assert_eq!(f.len() - 2, alphabet.len());
        for (c, to) in f[2..].iter().enumerate() {
            let mut t = states[id].tracks.clone();
            apply(&mut t, &rig, alphabet[c]);
            transitions += 1;
            if *to == "-" {
                cuts += 1;
                assert!(
                    leaves_window(&t),
                    "state {id} cmd {c}: C++ cut it, Rust stays in the window"
                );
            } else {
                let to: usize = to.parse().unwrap();
                assert_eq!(
                    snapshots.get(&snapshot(&t)),
                    Some(&to),
                    "transition from state {id} ({}) by {:?} should reach state {to}",
                    trace(&tree, id),
                    alphabet[c]
                );
            }
        }
    }
    assert_eq!(lines.next(), None, "unparsed lines at the end of the dump");
    println!(
        "keypool replay: {n_states} states and {transitions} transitions compared ({cuts} cut at the window bound)"
    );
    assert!(
        n_states > 10_000 && transitions > 80_000,
        "dump is not the depth 4 run"
    );
}
