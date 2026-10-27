use super::*;
use std::fmt::Write;
use std::io::Write as IoWrite;

fn volume(out: &mut String, v: Aabb) {
    for f in v.min.0.into_iter().chain(v.max.0) {
        write!(out, ",{}", f.to_bits()).unwrap();
    }
}
fn serialize(tree: &Dbvt, node: Option<NodeId>, out: &mut String, ids: &mut Vec<NodeId>) {
    let Some(n) = node else {
        out.push('_');
        return;
    };
    ids.push(n);
    match tree.node(n).kind {
        Kind::Leaf(k) => write!(out, "{}", k.0).unwrap(),
        Kind::Branch(_) => out.push('B'),
    }
    volume(out, tree.node(n).volume);
    if let Some([a, b]) = tree.children(n) {
        out.push('(');
        serialize(tree, Some(a), out, ids);
        out.push(';');
        serialize(tree, Some(b), out, ids);
        out.push(')');
    }
}
fn invariant(tree: &Dbvt) {
    fn visit(tree: &Dbvt, n: NodeId, parent: Option<NodeId>, seen: &mut Vec<NodeId>) {
        assert_eq!(tree.node(n).parent, parent);
        assert!(!seen.contains(&n));
        assert_ne!(tree.free, Some(n));
        seen.push(n);
        if let Some(c) = tree.children(n) {
            for child in c {
                visit(tree, child, Some(n), seen);
            }
        }
    }
    let mut seen = Vec::new();
    if let Some(root) = tree.root {
        visit(tree, root, None, &mut seen);
    }
    assert_eq!(
        tree.nodes.iter().filter(|n| n.is_some()).count(),
        seen.len() + usize::from(tree.free.is_some())
    );
}
fn vec3<'a>(words: &mut impl Iterator<Item = &'a str>) -> Vec3 {
    Vec3(std::array::from_fn(|_| {
        words.next().unwrap().parse().unwrap()
    }))
}
fn aabb<'a>(words: &mut impl Iterator<Item = &'a str>) -> Aabb {
    Aabb {
        min: vec3(words),
        max: vec3(words),
    }
}
fn execute(tree: &mut Dbvt, line: &str) -> String {
    let mut w = line.split_whitespace();
    let op = w.next().unwrap();
    let mut events = String::new();
    match op {
        "i" => {
            let k = ProxyKey(w.next().unwrap().parse().unwrap());
            tree.insert(k, aabb(&mut w));
        }
        "u" => {
            let k = ProxyKey(w.next().unwrap().parse().unwrap());
            tree.update(k, aabb(&mut w));
        }
        "p" => {
            let k = ProxyKey(w.next().unwrap().parse().unwrap());
            let mut v = aabb(&mut w);
            let vel = vec3(&mut w);
            let m = w.next().unwrap().parse().unwrap();
            let result = tree.update_predicted(k, &mut v, Some(vel), Some(m));
            write!(events, "{}", u8::from(result)).unwrap();
            volume(&mut events, v);
        }
        "r" => tree.remove(ProxyKey(w.next().unwrap().parse().unwrap())),
        "e" => tree.reinsert(
            ProxyKey(w.next().unwrap().parse().unwrap()),
            w.next().unwrap().parse().unwrap(),
        ),
        "l" => tree.lookahead = w.next().unwrap().parse().unwrap(),
        "n" => tree.optimize_incremental(w.next().unwrap().parse().unwrap()),
        "t" => tree.optimize_top_down(w.next().unwrap().parse().unwrap()),
        "b" => tree.optimize_bottom_up(),
        "c" => tree.clear(),
        "v" => tree.collide_volume(aabb(&mut w), |k| write!(events, "{},", k.0).unwrap()),
        "s" => tree.collide_tree(tree, |a, b| write!(events, "{}:{},", a.0, b.0).unwrap()),
        "x" => {
            let mut other = Dbvt::new(tree.policy);
            for i in 0..4 {
                other.insert(
                    ProxyKey(100 + i),
                    Aabb {
                        min: Vec3([i as f32 - 2.0, -1.0, -1.0]),
                        max: Vec3([i as f32 + 1.0, 2.0, 2.0]),
                    },
                );
            }
            tree.collide_tree(&other, |a, b| write!(events, "{}:{},", a.0, b.0).unwrap());
        }
        "h" => match tree.bounds() {
            Some(v) => {
                events.push('1');
                volume(&mut events, v);
            }
            None => events.push('0'),
        },
        "f" => {
            let key = ProxyKey(w.next().unwrap().parse().unwrap());
            tree.collide_leaf(tree, key, |a, b| {
                write!(events, "{}:{},", a.0, b.0).unwrap()
            });
        }
        "g" => {
            let mut other = Dbvt::new(tree.policy);
            other.insert(ProxyKey(100), aabb(&mut w));
            tree.collide_leaf(&other, ProxyKey(100), |a, b| {
                write!(events, "{}:{},", a.0, b.0).unwrap()
            });
        }
        "q" => {
            let from = vec3(&mut w);
            let inv = vec3(&mut w);
            let max = w.next().unwrap().parse().unwrap();
            let aabb = aabb(&mut w);
            tree.ray_test(
                from,
                inv,
                inv.0.map(|x| usize::from(x < 0.0)),
                max,
                aabb,
                |k| {
                    write!(events, "{},", k.0).unwrap();
                    false
                },
            );
        }
        _ => panic!("unknown operation"),
    }
    invariant(tree);
    events
}
#[allow(
    dead_code,
    reason = "capture helpers run through the mandatory standalone harness"
)]
pub(crate) fn native_controlled_address_parity(policy: DbvtPolicy) {
    let root = std::path::PathBuf::from(
        std::env::var("DBVT_FIXTURES").expect("run check.py to capture the real native oracle"),
    );
    let inputs = std::fs::read_to_string(root.join("inputs.tsv")).unwrap();
    assert_eq!(
        inputs.lines().count(),
        2355,
        "mandatory full capture corpus"
    );
    for order in 0..3 {
        let native = std::fs::read_to_string(root.join(format!("native-{order}.tsv"))).unwrap();
        assert_eq!(inputs.lines().count(), native.lines().count());
        let mut output = std::fs::File::create(root.join(format!("rust-{order}.tsv"))).unwrap();
        let mut tree = Dbvt::new(policy);
        for (i, (input, expected)) in inputs.lines().zip(native.lines()).enumerate() {
            let events = execute(&mut tree, input);
            let fields: Vec<_> = expected.split('|').collect();
            let mut topology = String::new();
            let mut ids = Vec::new();
            serialize(&tree, tree.root, &mut topology, &mut ids);
            let state = format!(
                "{},{},{},{}",
                tree.leaves,
                tree.lookahead,
                tree.opath,
                u8::from(tree.free.is_some())
            );
            writeln!(output, "{i}\t{input}\t{state}|{topology}||{events}").unwrap();
            assert_eq!(state, fields[0], "order {order} operation {i}: {input}");
            assert_eq!(topology, fields[1], "order {order} operation {i}: {input}");
            assert_eq!(events, fields[3], "order {order} operation {i}: {input}");
            ids.extend(tree.free);
            let ranks: Vec<usize> = fields[2]
                .split(',')
                .filter(|s| !s.is_empty())
                .map(|s| s.parse().unwrap())
                .collect();
            assert_eq!(ids.len(), ranks.len());
            let mut map = vec![0; tree.nodes.len()];
            for (n, rank) in ids.into_iter().zip(ranks) {
                map[n.0] = rank;
            }
            tree.address_ranks = Some(map);
        }
    }
}
#[test]
fn production_address_order_and_query_sets() {
    let mut tree = Dbvt::new(DbvtPolicy::GenericReference);
    for i in 0..80 {
        let x = (i % 11) as f32;
        tree.insert(
            ProxyKey(i),
            Aabb {
                min: Vec3([x, 0.0, 0.0]),
                max: Vec3([x + 2.0, 1.0, 1.0]),
            },
        );
    }
    for _ in 0..20 {
        for (i, n) in tree.nodes.iter().enumerate() {
            if let Some(n) = n {
                if let Some(p) = n.parent {
                    assert_eq!(
                        tree.parent_after(p, NodeId(i)),
                        tree.address(p) > tree.address(NodeId(i))
                    );
                }
            }
        }
        tree.optimize_incremental(80);
        invariant(&tree);
        let query = Aabb {
            min: Vec3([4.0, 0.0, 0.0]),
            max: Vec3([7.0, 1.0, 1.0]),
        };
        let mut actual = Vec::new();
        tree.collide_volume(query, |k| actual.push(k.0));
        actual.sort_unstable();
        let expected: Vec<_> = (0..80)
            .filter(|i| {
                let x = (i % 11) as f32;
                x <= 7.0 && x + 2.0 >= 4.0
            })
            .collect();
        assert_eq!(actual, expected);
    }
}
#[test]
fn merge_preserves_right_operand_zero_and_nan_bits() {
    let a = Aabb {
        min: Vec3([0.0, f32::NAN, 1.0]),
        max: Vec3([0.0, f32::NAN, 2.0]),
    };
    let b = Aabb {
        min: Vec3([-0.0, 3.0, 1.0]),
        max: Vec3([-0.0, 4.0, 2.0]),
    };
    let merged = a.merge(b);
    assert_eq!(merged.min.0.map(f32::to_bits), b.min.0.map(f32::to_bits));
    assert_eq!(merged.max.0.map(f32::to_bits), b.max.0.map(f32::to_bits));
}

#[test]
fn native_empty_partition_regression_terminates() {
    let inputs = include_str!("native-topdown-nontermination.tsv");
    let mut tree = Dbvt::new(DbvtPolicy::GenericReference);
    for input in inputs.lines().take(294) {
        execute(&mut tree, input);
    }
    let mut before = String::new();
    serialize(&tree, tree.root, &mut before, &mut Vec::new());
    tree.optimize_top_down(4);
    invariant(&tree);
    let mut after = String::new();
    serialize(&tree, tree.root, &mut after, &mut Vec::new());
    assert_eq!(leaf_records(&before), leaf_records(&after));
    for i in 0..20 {
        let q = Aabb {
            min: Vec3([i as f32 - 10.0, -10.0, -10.0]),
            max: Vec3([i as f32 - 9.0, 10.0, 10.0]),
        };
        let mut actual = Vec::new();
        tree.collide_volume(q, |k| actual.push(k.0));
        actual.sort_unstable();
        let mut expected: Vec<_> = tree
            .nodes
            .iter()
            .enumerate()
            .filter_map(|(j, n)| {
                if tree.free == Some(NodeId(j)) {
                    return None;
                }
                n.as_deref().and_then(|n| match n.kind {
                    Kind::Leaf(k) if tree.policy.intersects(n.volume, q) => Some(k.0),
                    _ => None,
                })
            })
            .collect();
        expected.sort_unstable();
        assert_eq!(actual, expected);
    }
}
fn leaf_records(topology: &str) -> Vec<&str> {
    let mut records: Vec<_> = topology
        .split(['(', ';', ')'])
        .filter(|s| !s.is_empty() && !s.starts_with('B') && *s != "_")
        .collect();
    records.sort_unstable();
    records
}
#[allow(
    dead_code,
    reason = "capture helpers run through the mandatory standalone harness"
)]
fn query_set(events: &str) -> Vec<String> {
    let mut result: Vec<_> = events
        .split(',')
        .filter(|e| !e.is_empty())
        .map(|e| {
            if let Some((a, b)) = e.split_once(':') {
                let a: u32 = a.parse().unwrap();
                let b: u32 = b.parse().unwrap();
                format!("{}:{}", a.min(b), a.max(b))
            } else {
                e.to_owned()
            }
        })
        .collect();
    result.sort_unstable();
    result
}
#[allow(
    dead_code,
    reason = "capture helpers run through the mandatory standalone harness"
)]
pub(crate) fn ordinary_native_and_production_allocator_query_sets(policy: DbvtPolicy) {
    let root = std::path::PathBuf::from(std::env::var("DBVT_FIXTURES").unwrap());
    let inputs = std::fs::read_to_string(root.join("inputs.tsv")).unwrap();
    assert_eq!(
        inputs.lines().count(),
        2355,
        "mandatory full capture corpus"
    );
    let native = std::fs::read_to_string(root.join("native-3.tsv")).unwrap();
    assert_eq!(inputs.lines().count(), native.lines().count());
    let mut output = std::fs::File::create(root.join("rust-3.tsv")).unwrap();
    let mut tree = Dbvt::new(policy);
    for (i, (input, expected)) in inputs.lines().zip(native.lines()).enumerate() {
        let events = execute(&mut tree, input);
        let fields: Vec<_> = expected.split('|').collect();
        let mut topology = String::new();
        serialize(&tree, tree.root, &mut topology, &mut Vec::new());
        let state = format!(
            "{},{},{},{}",
            tree.leaves,
            tree.lookahead,
            tree.opath,
            u8::from(tree.free.is_some())
        );
        writeln!(output, "{i}\t{input}\t{state}|{topology}||{events}").unwrap();
        assert_eq!(
            leaf_records(&topology),
            leaf_records(fields[1]),
            "operation {i} {input}"
        );
        if matches!(input.as_bytes()[0], b'v' | b's' | b'q' | b'x' | b'f' | b'g') {
            assert_eq!(
                query_set(&events),
                query_set(fields[3]),
                "operation {i} {input}"
            );
        } else {
            assert_eq!(events, fields[3], "operation {i} {input}");
        }
    }
}

#[test]
fn production_sort_rotates_by_actual_box_address() {
    let mut tree = Dbvt::new(DbvtPolicy::GenericReference);
    let v = Aabb {
        min: Vec3([0.0; 3]),
        max: Vec3([1.0; 3]),
    };
    let a = tree.create(v, None, Kind::Leaf(ProxyKey(90)));
    let b = tree.create(v, None, Kind::Leaf(ProxyKey(91)));
    let (n, p) = if tree.address(a) < tree.address(b) {
        (a, b)
    } else {
        (b, a)
    };
    let children = std::array::from_fn(|i| tree.create(v, None, Kind::Leaf(ProxyKey(i as u32))));
    let sibling = tree.create(v, Some(p), Kind::Leaf(ProxyKey(3)));
    tree.node_mut(n).kind = Kind::Branch(children);
    tree.node_mut(n).parent = Some(p);
    for child in children {
        tree.node_mut(child).parent = Some(n);
    }
    tree.node_mut(p).kind = Kind::Branch([n, sibling]);
    tree.root = Some(p);
    tree.leaves = 3;
    let addresses = (tree.address(n), tree.address(p));
    assert!(addresses.1 > addresses.0);
    assert_eq!(tree.sort(n), p);
    assert_eq!(tree.root, Some(n));
    assert_eq!((tree.address(n), tree.address(p)), addresses);
    invariant(&tree);
}
#[test]
fn zero_center_split_falls_back_without_changing_leaves() {
    let mut tree = Dbvt::new(DbvtPolicy::GenericReference);
    tree.insert(
        ProxyKey(1),
        Aabb {
            min: Vec3([-3.0; 3]),
            max: Vec3([3.0; 3]),
        },
    );
    tree.insert(
        ProxyKey(2),
        Aabb {
            min: Vec3([0.5; 3]),
            max: Vec3([1.5; 3]),
        },
    );
    tree.optimize_top_down(1);
    invariant(&tree);
    let mut keys = Vec::new();
    tree.collide_volume(
        Aabb {
            min: Vec3([-10.0; 3]),
            max: Vec3([10.0; 3]),
        },
        |k| keys.push(k.0),
    );
    keys.sort_unstable();
    assert_eq!(keys, [1, 2]);
}

#[test]
fn one_free_box_is_reused_and_dead_slots_stay_bounded() {
    let mut tree = Dbvt::new(DbvtPolicy::GenericReference);
    let volume = Aabb {
        min: Vec3([0.0; 3]),
        max: Vec3([1.0; 3]),
    };
    tree.insert(ProxyKey(1), volume);
    tree.insert(ProxyKey(2), volume);
    for _ in 0..100 {
        let leaf = tree.find(ProxyKey(2));
        let address = tree.address(leaf);
        tree.remove(ProxyKey(2));
        assert_eq!(tree.free, Some(leaf));
        assert_eq!(tree.nodes.iter().filter(|n| n.is_some()).count(), 2);
        tree.insert(ProxyKey(2), volume);
        assert_eq!(tree.address(tree.find(ProxyKey(2))), address);
        assert_eq!(tree.nodes.len(), 3);
        invariant(&tree);
    }
}

#[test]
fn large_finite_optimization_subprocess() {
    const CHILD: &str = "DBVT_LARGE_OPTIMIZATION_CHILD";
    if let Ok(mode) = std::env::var(CHILD) {
        let volume = Aabb {
            min: Vec3([0.0; 3]),
            max: Vec3([1e20; 3]),
        };
        assert!(volume
            .min
            .0
            .into_iter()
            .chain(volume.max.0)
            .all(f32::is_finite));
        assert!(volume.size().is_infinite());
        let mut tree = Dbvt::new(DbvtPolicy::GenericReference);
        for key in 0..3 {
            tree.insert(ProxyKey(key), volume);
        }
        if mode == "bottom" {
            tree.optimize_bottom_up();
        } else {
            tree.optimize_top_down(3);
        }
        invariant(&tree);
        assert_eq!(tree.leaf_count(), 3);
        for key in 0..3 {
            let actual = tree.volume(ProxyKey(key));
            assert_eq!(
                actual.min.0.map(f32::to_bits),
                volume.min.0.map(f32::to_bits)
            );
            assert_eq!(
                actual.max.0.map(f32::to_bits),
                volume.max.0.map(f32::to_bits)
            );
        }
        let mut keys = Vec::new();
        tree.collide_volume(volume, |key| keys.push(key.0));
        keys.sort_unstable();
        assert_eq!(keys, [0, 1, 2]);
        let mut pairs = Vec::new();
        tree.collide_tree(&tree, |a, b| pairs.push((a.0.min(b.0), a.0.max(b.0))));
        pairs.sort_unstable();
        assert_eq!(pairs, [(0, 1), (0, 2), (1, 2)]);
        return;
    }
    for mode in ["bottom", "top"] {
        let output = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                &format!(
                    "{}::large_finite_optimization_subprocess",
                    module_path!().split_once("::").unwrap().1
                ),
                "--nocapture",
            ])
            .env(CHILD, mode)
            .output()
            .unwrap();
        assert!(
            output.status.success() && String::from_utf8_lossy(&output.stdout).contains("1 passed"),
            "{mode}: {:?}\n{}",
            output.status,
            String::from_utf8_lossy(&output.stderr)
        );
    }
}

thread_local! {
    static PANIC_AFTER_FETCH: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

pub(super) fn after_destructive_fetch(tree: &Dbvt) {
    if PANIC_AFTER_FETCH.with(|flag| flag.replace(false)) {
        assert!(
            tree.root.is_none(),
            "destructive fetch must relinquish root ownership"
        );
        panic!("injected failure after destructive fetch");
    }
}

#[test]
fn optimization_unwind_subprocess() {
    const CHILD: &str = "DBVT_OPTIMIZATION_UNWIND_CHILD";
    if let Ok(mode) = std::env::var(CHILD) {
        let result = std::panic::catch_unwind(|| {
            let mut tree = Dbvt::new(DbvtPolicy::GenericReference);
            for key in 0..3 {
                tree.insert(
                    ProxyKey(key),
                    Aabb {
                        min: Vec3([0.0; 3]),
                        max: Vec3([1.0; 3]),
                    },
                );
            }
            PANIC_AFTER_FETCH.with(|flag| flag.set(true));
            if mode == "bottom" {
                tree.optimize_bottom_up();
            } else {
                tree.optimize_top_down(3);
            }
        });
        let payload = result.expect_err("the injected panic must actually unwind through Drop");
        assert_eq!(
            payload.downcast_ref::<&str>(),
            Some(&"injected failure after destructive fetch")
        );
        assert!(!PANIC_AFTER_FETCH.with(|flag| flag.get()));
        return;
    }
    for mode in ["bottom", "top"] {
        let output = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                &format!(
                    "{}::optimization_unwind_subprocess",
                    module_path!().split_once("::").unwrap().1
                ),
                "--nocapture",
            ])
            .env(CHILD, mode)
            .output()
            .unwrap();
        assert!(
            output.status.success() && String::from_utf8_lossy(&output.stdout).contains("1 passed"),
            "{mode}: {:?}\n{}",
            output.status,
            String::from_utf8_lossy(&output.stderr)
        );
    }
}
