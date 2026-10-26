use super::core::pair_cache::*;
use std::cell::RefCell;

#[test]
fn real_native_fixture() {
    let mut cache = HashedPairCache::new();
    let mut states: Vec<_> = (1..=48)
        .map(|uid| ProxyState {
            uid,
            group: 1,
            mask: -1,
        })
        .collect();
    let inputs = include_str!("../pair_cache_data/inputs.tsv");
    let expected = include_str!("../pair_cache_data/native.tsv");
    let mut actual = String::new();
    for line in inputs.lines() {
        let fields: Vec<_> = line.split_whitespace().collect();
        let n = |i: usize| {
            fields
                .get(i)
                .map(|v| v.parse::<i64>().unwrap())
                .unwrap_or(0)
        };
        let a = n(1) as usize;
        let b = n(2) as usize;
        let events = RefCell::new(String::new());
        let release = |key: AlgorithmKey| {
            events
                .borrow_mut()
                .push_str(&format!("d{},f{},", key.0, key.0))
        };
        let mut result = "-".to_string();
        let index = |v: Option<usize>| v.map(|i| i.to_string()).unwrap_or_else(|| "-".to_string());
        match fields[0] {
            "s" => {
                states[a] = ProxyState {
                    uid: n(2) as i32,
                    group: n(3) as i16,
                    mask: n(4) as i16,
                }
            }
            "a" => result = index(cache.add(ProxyKey(a as u32), ProxyKey(b as u32), &states)),
            "f" => result = index(cache.find(ProxyKey(a as u32), ProxyKey(b as u32), &states)),
            "r" => {
                result =
                    index(cache.remove(ProxyKey(a as u32), ProxyKey(b as u32), &states, release))
            }
            "t" => {
                if cache.pairs()[a].algorithm.is_none() {
                    cache.set_algorithm(a, AlgorithmKey(b as u32));
                }
                cache.set_internal_info(a, n(3) as usize);
            }
            "c" => cache.clean(a, release),
            "x" => cache.clean_proxy(ProxyKey(a as u32), release),
            "p" => cache.remove_proxy(ProxyKey(a as u32), &states, release),
            "v" => cache.process_all(
                &states,
                |pair| {
                    let [x, y] = pair.proxies;
                    events.borrow_mut().push_str(&format!("v{}:{},", x.0, y.0));
                    (x.0 + y.0) % a as u32 == 0
                },
                release,
            ),
            "q" => {
                let p = Pair::new(ProxyKey(a as u32), ProxyKey(b as u32), &states);
                result = format!("{}:{}", p.proxies[0].0, p.proxies[1].0);
            }
            _ => panic!("unknown operation"),
        }
        actual.push_str(&format!("{result}|"));
        for p in cache.pairs() {
            let [x, y] = p.proxies;
            actual.push_str(&format!(
                "{}:{}:{}:{}:{}:{},",
                x.0,
                y.0,
                states[x.0 as usize].uid,
                states[y.0 as usize].uid,
                p.algorithm.map(|k| k.0).unwrap_or(0),
                p.internal_info
            ));
        }
        let (capacity, buckets, next) = cache.tables();
        actual.push_str(&format!("|{capacity}|"));
        for i in buckets {
            actual.push_str(&format!("{},", i.map(|v| v as i64).unwrap_or(-1)));
        }
        actual.push('|');
        for i in next {
            actual.push_str(&format!("{},", i.map(|v| v as i64).unwrap_or(-1)));
        }
        actual.push_str(&format!("|{}\n", events.borrow()));
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
