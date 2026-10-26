use super::*;
use std::fmt::Write;

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
#[test]
fn native_controlled_address_parity() {
    let root = std::path::PathBuf::from(
        std::env::var("DBVT_FIXTURES").expect("run check.py to capture the real native oracle"),
    );
    let inputs = std::fs::read_to_string(root.join("inputs.tsv")).unwrap();
    for order in 0..3 {
        let native = std::fs::read_to_string(root.join(format!("native-{order}.tsv"))).unwrap();
        assert_eq!(inputs.lines().count(), native.lines().count());
        let mut tree = Dbvt::new();
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
    let mut tree = Dbvt::new();
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
