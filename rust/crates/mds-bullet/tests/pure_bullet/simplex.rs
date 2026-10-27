use crate::core::math::Vec3;
use crate::core::simplex::VoronoiSimplexSolver;
use std::fmt::Write;
fn scalar(out: &mut String, f: f32) {
    if f.is_nan() {
        out.push_str(" nan");
    } else {
        write!(out, " {:x}", f.to_bits()).unwrap();
    }
}
fn vector(out: &mut String, v: Vec3) {
    for f in v.0 {
        scalar(out, f);
    }
}
fn read_vector<'a>(tokens: &mut impl Iterator<Item = &'a str>) -> Vec3 {
    Vec3(std::array::from_fn(|_| {
        f32::from_bits(u32::from_str_radix(tokens.next().unwrap(), 16).unwrap())
    }))
}
pub fn trace(input: &str) -> String {
    let mut output = String::new();
    let mut s = VoronoiSimplexSolver::default();
    let mut cache_defined = false;
    let mut point_defined = false;
    for line in input.lines() {
        let mut tokens = line.split_whitespace();
        let op = tokens.next().unwrap();
        let mut ret = -1;
        let mut returned = Vec::new();
        let before = s.num_vertices();
        let update = s.needs_update;
        match op {
            "R" => s.reset(),
            "A" => {
                let w = read_vector(&mut tokens);
                let p = read_vector(&mut tokens);
                let q = read_vector(&mut tokens);
                s.add_vertex(w, p, q);
            }
            "C" => {
                let mut v = Vec3::ZERO;
                ret = i32::from(s.closest(&mut v));
                if cache_defined || (update && (1..=3).contains(&before)) {
                    returned.push(v);
                }
            }
            "P" => {
                let (p, q) = s.compute_points();
                if cache_defined || (update && (1..=3).contains(&before)) {
                    returned.push(p);
                    returned.push(q);
                }
            }
            "B" => {
                if cache_defined {
                    returned.push(s.backup_closest());
                }
            }
            "I" => ret = i32::from(s.in_simplex(read_vector(&mut tokens))),
            _ => panic!("unknown operation"),
        }
        if (op == "C" || op == "P") && update {
            if (1..=3).contains(&before) {
                cache_defined = true;
            }
            if before >= 3 {
                point_defined = true;
            }
        }
        let mut out = format!(
            "{op} {ret} {} {} {} {} {} {}",
            s.num_vertices(),
            u8::from(s.full_simplex()),
            u8::from(s.empty_simplex()),
            u8::from(s.needs_update),
            u8::from(s.cached_valid),
            u8::from(s.result.degenerate)
        );
        for used in s.result.used {
            write!(out, " {}", u8::from(used)).unwrap();
        }
        for f in s.result.barycentric {
            scalar(&mut out, f);
        }
        vector(&mut out, s.last_w);
        scalar(&mut out, s.max_vertex());
        if cache_defined {
            vector(&mut out, s.cached_p1);
            vector(&mut out, s.cached_p2);
            vector(&mut out, s.cached_v);
        } else {
            out.push_str(" _ _ _ _ _ _ _ _ _");
        }
        if point_defined {
            vector(&mut out, s.result.point);
        } else {
            out.push_str(" _ _ _");
        }
        for v in s.get_simplex() {
            vector(&mut out, v.w);
            vector(&mut out, v.p);
            vector(&mut out, v.q);
        }
        for v in returned {
            vector(&mut out, v);
        }
        writeln!(output, "{out}").unwrap();
    }
    output
}

pub fn compare_trace(input: &str, expected: &str) {
    let actual = trace(input);
    let mut expected = expected.lines();
    for (operation, row) in actual.lines().enumerate() {
        assert_eq!(Some(row), expected.next(), "simplex operation {operation}");
    }
    assert!(
        expected.next().is_none(),
        "unconsumed native simplex operations"
    );
}
#[cfg(test)]
mod checks {
    use super::*;

    #[test]
    fn complete_native_scenarios_match_defined_fields() {
        for (input, expected) in [
            (
                include_str!("../simplex_data/finite-inputs.tsv"),
                include_str!("../simplex_data/finite-native.tsv"),
            ),
            (
                include_str!("../simplex_data/nonfinite-inputs.tsv"),
                include_str!("../simplex_data/nonfinite-native.tsv"),
            ),
        ] {
            compare_trace(input, expected);
        }
    }

    #[test]
    #[should_panic(expected = "a simplex supports at most four vertices")]
    fn rejects_fifth_vertex() {
        let mut solver = VoronoiSimplexSolver::default();
        for _ in 0..5 {
            solver.add_vertex(Vec3::ZERO, Vec3::ZERO, Vec3::ZERO);
        }
    }

    #[test]
    fn reset_retains_defined_witnesses_and_last_removed_vertex_is_found() {
        let mut solver = VoronoiSimplexSolver::default();
        let a = Vec3([1.0, 0.0, 0.0]);
        let b = Vec3([2.0, 0.0, 0.0]);
        solver.add_vertex(a, a, Vec3::ZERO);
        solver.add_vertex(b, b, Vec3::ZERO);
        let mut closest = Vec3::ZERO;
        assert!(solver.closest(&mut closest));
        assert_eq!(solver.num_vertices(), 1);
        assert!(solver.in_simplex(b));
        assert_eq!(solver.compute_points(), (a, Vec3::ZERO));
        solver.reset();
        assert!(!solver.closest(&mut closest));
        assert_eq!(closest, a);
        assert_eq!(solver.compute_points(), (a, Vec3::ZERO));
    }
}
