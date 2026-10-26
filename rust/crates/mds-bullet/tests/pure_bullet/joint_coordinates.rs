use super::core::joint_coordinates::calculate_coordinates;
use super::core::math::{Basis, Transform, Vec3};

#[test]
fn every_calculated_frame_and_coordinate_word_matches_native() {
    let fixture = std::env::var("MDS_COORDINATE_FIXTURE")
        .map(|path| std::fs::read_to_string(path).unwrap())
        .unwrap_or_else(|_| include_str!("../coordinate_data/native.tsv").to_owned());
    let mut count = 0;
    let mut branches = [false; 3];
    for line in fixture.lines() {
        let mut fields = line.split('\t');
        let id: usize = fields.next().unwrap().parse().unwrap();
        let words: Vec<u32> = fields
            .map(|v| u32::from_str_radix(v, 16).unwrap())
            .collect();
        assert_eq!(words.len(), 99, "case {id} input and output word count");
        let mut input = words[..48].iter().map(|v| f32::from_bits(*v));
        let [a, b, fa, fb] = std::array::from_fn(|_| Transform {
            basis: Basis(std::array::from_fn(|_| {
                std::array::from_fn(|_| input.next().unwrap())
            })),
            origin: Vec3(std::array::from_fn(|_| input.next().unwrap())),
        });
        let result = calculate_coordinates(a, b, fa, fb);
        let mut actual = Vec::new();
        for frame in result.frames_world {
            for row in frame.basis.0 {
                actual.extend(row.map(f32::to_bits));
            }
            actual.extend(frame.origin.0.map(f32::to_bits));
        }
        let c = result.coordinates;
        for row in c.basis_a_world.0 {
            actual.extend(row.map(f32::to_bits));
        }
        for v in [c.pivot_b_world, c.linear_diff, c.angular_diff] {
            actual.extend(v.0.map(f32::to_bits));
        }
        for v in c.angular_axes {
            actual.extend(v.0.map(f32::to_bits));
        }
        for (index, (&rust, &native)) in actual.iter().zip(&words[48..]).enumerate() {
            assert_eq!(
                rust,
                native,
                "case {id} result word {index}, rust {rust:08x}, native {native:08x}, input {:?}",
                &words[..48]
            );
        }
        assert_eq!(actual.len(), 51);
        let y = c.angular_diff.0[1];
        branches[if y == std::f32::consts::FRAC_PI_2 {
            2
        } else if y == -std::f32::consts::FRAC_PI_2 {
            0
        } else {
            1
        }] = true;
        count += 1;
    }
    assert!(count >= 2120);
    assert!(branches.into_iter().all(|seen| seen));
}
