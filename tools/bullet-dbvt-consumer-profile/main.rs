extern crate mds_bullet_sys;
#[path = "../../rust/crates/mds-bullet/src/core/dbvt.rs"]
pub mod dbvt;
pub use dbvt_math as math;
#[path = "../../rust/crates/mds-bullet/src/core/pair_cache.rs"]
pub mod pair_cache;

unsafe extern "C" {
    fn mds_consumer_oracle(order: i32) -> i32;
    fn mds_consumer_aabb(words: *const u32, result: *mut u32);
}

fn main() {
    let mode = std::env::args().nth(1).expect("probe mode");
    if mode == "oracle" {
        std::process::exit(unsafe {
            mds_consumer_oracle(
                std::env::args()
                    .nth(2)
                    .unwrap_or("0".into())
                    .parse()
                    .unwrap(),
            )
        });
    }
    if mode == "select" {
        let mut tree = dbvt::Dbvt::new();
        for (i, point) in [[0.5, 8388608.0, 0.5], [1.0, 8388608.0, 0.0], [0.0; 3]]
            .into_iter()
            .enumerate()
        {
            tree.insert(
                pair_cache::ProxyKey(i as u32 + 1),
                dbvt::Aabb {
                    min: math::Vec3(point),
                    max: math::Vec3(point),
                },
            );
        }
        tree.collide_volume(
            dbvt::Aabb {
                min: math::Vec3([-1.0; 3]),
                max: math::Vec3([2.0, 8388609.0, 2.0]),
            },
            |key| print!("{},", key.0),
        );
        println!();
        return;
    }
    assert!(mode == "native-aabb" || mode == "rust-aabb");
    let base = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0];
    let mut cases = vec![
        [base, base],
        [base, [1.0, 0.0, 0.0, 2.0, 1.0, 1.0]],
        [base, [2.0; 6]],
    ];
    for bits in [0u32, 0x80000000, 0x7fc00001, 0x7fc00002] {
        for operand in 0..2 {
            for lane in 0..6 {
                let mut pair = [base, base];
                pair[operand][lane] = f32::from_bits(bits);
                cases.push(pair);
            }
        }
    }
    for (id, pair) in cases.into_iter().enumerate() {
        let words: [u32; 12] = std::array::from_fn(|i| pair[i / 6][i % 6].to_bits());
        let mut result = [0; 13];
        if mode == "native-aabb" {
            unsafe {
                mds_consumer_aabb(words.as_ptr(), result.as_mut_ptr());
            }
        } else {
            let [a, b] = pair.map(|v| dbvt::Aabb {
                min: math::Vec3(v[..3].try_into().unwrap()),
                max: math::Vec3(v[3..].try_into().unwrap()),
            });
            result[0] = a.intersects(b) as u32;
            for (i, merged) in [a.merge(b), b.merge(a)].into_iter().enumerate() {
                for (j, value) in merged.min.0.into_iter().chain(merged.max.0).enumerate() {
                    result[1 + i * 6 + j] = value.to_bits();
                }
            }
        }
        println!(
            "{id}|{}|{}",
            words.map(|v| v.to_string()).join(","),
            result.map(|v| v.to_string()).join(",")
        );
    }
}
