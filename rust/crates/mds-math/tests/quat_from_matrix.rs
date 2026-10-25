//! `Quat::from_matrix` against `D3DXQuaternionRotationMatrix` on the
//! reference host, including every recorded case the earlier radicand
//! grouping missed.

use mds_math::{Mat4, Quat};

fn bits(tok: &str) -> f32 {
    f32::from_bits(u32::from_str_radix(tok, 16).expect("hex bits"))
}

#[test]
fn matches_d3dx_on_the_recorded_matrices() {
    let data = include_str!("data/quat-from-matrix.txt");
    let mut cases = 0;
    for (n, line) in data
        .lines()
        .enumerate()
        .filter(|(_, l)| !l.starts_with('#'))
    {
        let v: Vec<f32> = line.split_whitespace().map(bits).collect();
        assert_eq!(v.len(), 20, "line {}", n + 1);
        let got = Quat::from_matrix(&Mat4(v[..16].try_into().unwrap())).0;
        let want = &v[16..];
        assert!(
            got.iter()
                .zip(want)
                .all(|(a, b)| a.to_bits() == b.to_bits()),
            "line {}: got {:08x?}, want {:08x?}",
            n + 1,
            got.map(f32::to_bits),
            want.iter().map(|x| x.to_bits()).collect::<Vec<_>>()
        );
        cases += 1;
    }
    assert_eq!(cases, 2500);
}
