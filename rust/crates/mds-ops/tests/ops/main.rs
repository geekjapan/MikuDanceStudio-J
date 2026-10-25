//! One test module per operation. The expected states come from reading the
//! C++ (each test names the lines it follows) and are written out here
//! independently of the code under test, on the fixtures of
//! `tests/fixtures/rust/` and on pools built in the tests.
//!
//! The scenes are `swing600.pmm` and `camera3.pmm`; the pools of the
//! hand-built tests replace a model's pool in a fixture scene.

mod common;

mod bias;
mod blink;
mod facial;
mod frame_line;
mod multiply;
mod physics;
mod range;
mod select;
mod unused;
