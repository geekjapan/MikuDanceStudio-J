//! Deterministic float transcendentals, the port of `det_math.hpp`.
//!
//! `f32::sin` and `f32::acos` call the platform `sinf` and `acosf`, which
//! round differently on macOS arm64, macOS x86_64 and Linux. These evaluate
//! in `f64` and round once to `f32`, as the C++ evaluator does. Every
//! transcendental on the evaluation path goes through this module.

pub fn acos(x: f32) -> f32 {
    f64::from(x).acos() as f32
}

pub fn sin(x: f32) -> f32 {
    f64::from(x).sin() as f32
}
