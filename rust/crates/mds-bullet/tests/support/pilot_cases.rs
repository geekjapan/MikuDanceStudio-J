//! Shared inputs and row encoding for the native capture and pure Rust checks.

pub const BODIES: usize = 3;
pub const FRAMES: usize = 64;
pub const CASES: usize = 6;
pub const GRAVITY: [f32; 3] = [1.25, -9.8, -0.5];
pub const POSITIONS: [[f32; 3]; BODIES] = [[0.0, 5.0, 0.0], [2.5, -1.25, 3.0], [-9.0, 7.0, 0.125]];
pub const ROTATIONS: [[f32; 4]; BODIES] = [
    [0.0, 0.0, 0.0, 1.0],
    [0.1, -0.2, 0.3, 0.9],
    [0.9, 0.2, -0.1, 0.01],
];
pub const MASSES: [f32; BODIES] = [1.0, 2.3, 0.01];
pub const DAMPING: [f32; BODIES] = [0.0, 0.37, 0.85];

pub fn timing(case: usize, frame: usize) -> (f32, i32, f32) {
    let fixed = 1.0 / 60.0;
    match case {
        0 => (0.0, 1, fixed),
        1 => (fixed, 1, fixed),
        2 => (1.0 / 30.0, 1, fixed),
        3 => (1.0 / 30.0, 4, fixed),
        4 => (
            [0.0, fixed * 0.5, fixed, fixed * 2.5, fixed * 0.25][frame % 5],
            3,
            fixed,
        ),
        5 => (
            [0.0, fixed, 1.0 / 30.0, f32::EPSILON * 0.5][frame % 4],
            0,
            fixed,
        ),
        _ => unreachable!(),
    }
}

pub fn row(
    case: usize,
    frame: usize,
    steps: i32,
    hash: u64,
    transforms: [([f32; 3], [f32; 4]); BODIES],
) -> String {
    use std::fmt::Write;
    let mut line = format!("{case}\t{frame}\t{steps}\t{hash:016x}");
    for (position, rotation) in transforms {
        for value in position.into_iter().chain(rotation) {
            write!(line, "\t{:08x}", value.to_bits()).unwrap();
        }
    }
    line.push('\n');
    line
}
