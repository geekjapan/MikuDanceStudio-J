use super::core::axis_sweep::AxisSweep32;
use super::core::math::Vec3;
use super::core::pair_cache::{AlgorithmKey, ProxyKey};
use std::fmt::Write;

#[test]
fn real_native_fixture() {
    let inputs = include_str!("../axis_sweep_data/inputs.tsv");
    let expected = include_str!("../axis_sweep_data/native.tsv");
    let mut sweep = AxisSweep32::new_mmd();
    let mut actual = String::new();
    for line in inputs.lines() {
        let f: Vec<_> = line.split_whitespace().collect();
        let n = |i: usize| f[i].parse::<i64>().unwrap();
        let vector = |i: usize| Vec3(std::array::from_fn(|j| f32::from_bits(n(i + j) as u32)));
        let key = |i: usize| ProxyKey(n(i) as u32);
        let mut events = String::new();
        let mut release = |k: AlgorithmKey| {
            write!(events, "d{},f{},", k.0, k.0).unwrap();
        };
        let mut result = "-".to_string();
        match f[0] {
            "n" => sweep = AxisSweep32::for_test(vector(2), vector(5), n(1) as u32),
            "a" => {
                result = sweep
                    .add(
                        vector(5),
                        vector(8),
                        n(1) as usize,
                        n(2) as i16,
                        n(3) as i16,
                        n(4) as usize,
                    )
                    .0
                    .to_string()
            }
            "u" => sweep.update(key(1), vector(2), vector(5), &mut release),
            "r" => sweep.remove(key(1), &mut release),
            "z" => sweep.reset_pool(),
            "p" => sweep.calculate_overlapping_pairs(),
            "q" => result = u8::from(sweep.test_overlap(key(1), key(2))).to_string(),
            "t" => {
                if sweep.pairs()[n(1) as usize].algorithm.is_none() {
                    sweep.set_pair_algorithm(n(1) as usize, AlgorithmKey(n(2) as u32));
                }
                sweep.set_pair_internal_info(n(1) as usize, n(3) as usize);
            }
            "b" => {
                for i in 0..sweep.pairs().len() {
                    if sweep.pairs()[i].algorithm.is_none() {
                        sweep.set_pair_algorithm(i, AlgorithmKey(n(1) as u32 + i as u32));
                    }
                    sweep.set_pair_internal_info(i, n(1) as usize + i + 100);
                }
            }
            "c" => sweep.clean_pair(n(1) as usize, &mut release),
            _ => panic!("unknown operation"),
        }
        write!(actual, "{result}|{}:{}", sweep.len(), sweep.first_free()).unwrap();
        for edges in sweep.edges() {
            actual.push('|');
            for (i, edge) in edges.iter().enumerate() {
                write!(actual, "{i}:{}:{},", edge.pos, edge.handle).unwrap();
            }
        }
        actual.push('|');
        for (id, state) in sweep.states().iter().enumerate() {
            if let Some(h) = sweep.handle(ProxyKey(id as u32)) {
                write!(
                    actual,
                    "{id}:{}:{}:{}:{}:{}:",
                    state.uid, state.group, state.mask, h.owner, h.multi_sap_parent
                )
                .unwrap();
                for axis in 0..3 {
                    write!(actual, "{}:{}:", h.min_edges[axis], h.max_edges[axis]).unwrap();
                }
                actual.push(',');
            }
        }
        actual.push('|');
        for p in sweep.pairs() {
            write!(
                actual,
                "{}:{}:{}:{},",
                p.proxies[0].0,
                p.proxies[1].0,
                p.algorithm.map(|k| k.0).unwrap_or(0),
                p.internal_info
            )
            .unwrap();
        }
        writeln!(actual, "|{events}").unwrap();
    }
    for (i, (a, b)) in actual.lines().zip(expected.lines()).enumerate() {
        assert_eq!(
            a,
            b,
            "operation {}: {}",
            i + 1,
            inputs.lines().nth(i).unwrap()
        );
    }
    assert_eq!(actual.lines().count(), expected.lines().count());
}

#[test]
fn mmd_constructor_and_capacity() {
    let mut sweep = AxisSweep32::new_mmd();
    assert_eq!(sweep.capacity(), 1_500_000);
    assert!(sweep.is_empty());
    assert_eq!(sweep.first_free(), 1);
    assert_eq!(sweep.add(Vec3::ZERO, Vec3::ZERO, 0, 1, -1, 0), ProxyKey(1));
    assert_eq!(sweep.cache().pairs().len(), 0);
    sweep.remove(ProxyKey(1), |_| panic!("no algorithms"));
    sweep.reset_pool();
    assert!(sweep.is_empty());
}

#[test]
#[should_panic]
fn full_capacity_is_an_internal_precondition() {
    let mut sweep = AxisSweep32::for_test(Vec3([-1.0; 3]), Vec3([1.0; 3]), 2);
    for _ in 0..3 {
        sweep.add(Vec3::ZERO, Vec3::ZERO, 0, 1, -1, 0);
    }
}

#[test]
fn tied_edges_preserve_native_pair_history() {
    let mut sweep = AxisSweep32::new_mmd();
    for _ in 0..3 {
        sweep.add(Vec3::ZERO, Vec3::ZERO, 0, 1, -1, 0);
    }
    let pairs: Vec<_> = sweep
        .pairs()
        .iter()
        .map(|p| p.proxies.map(|k| k.0))
        .collect();
    assert_eq!(pairs, [[1, 2], [2, 3], [1, 3]]);
}
