# Free sphere native oracle

`free-sphere-native.tsv` was recorded from the existing `mds_bt` shim at base
`4105040`, using its vendored Bullet 2.75, scalar SSE emulation and pure Rust UCRT
math replacements. No native source was changed for this capture.

From the repository root, regenerate it with:

```sh
cargo run --manifest-path rust/Cargo.toml -p mds-bullet --example free_sphere_oracle --release > rust/crates/mds-bullet/tests/data/free-sphere-native.tsv
```

Each row contains the case index, frame index, unclamped native substep count,
aggregate FNV state hash, then three bodies' position xyz and quaternion xyzw.
Float words and hashes are hexadecimal. The hash also checks each motion state's
3x3 basis and velocity x. Collision masks are zero. Inputs live in
`tests/support/pilot_cases.rs`.

The six cases use dt=0, dt=1/60, dt=1/30 with execution clamped to one step,
dt=1/30 with up to four steps, mixed fixed-step remainders, and variable steps
including zero and a value below Bullet's epsilon. There are 64 frames per case.
Masses, damping factors and rotations differ across the three bodies. These are
noncolliding, gravity-driven spheres. This fixture does not validate collisions,
constraints, sleeping or angular velocity driven by torque.

`free_sphere_native.rs` checks the live native shim against this recording.
`pure_bullet.rs` checks the native-free Rust pilot against the same recording.
The existing public World still uses the native shim.

The pure checks can run without compiling or linking Bullet or any C++ code:

```sh
rustc --edition=2021 --crate-name mds_crtmath --crate-type rlib -O rust/crates/mds-crtmath/src/lib.rs -o /tmp/libmds_crtmath_pure.rlib
rustc --edition=2021 --test -O rust/crates/mds-bullet/tests/pure_bullet.rs --extern mds_crtmath=/tmp/libmds_crtmath_pure.rlib -o /tmp/pure_bullet
/tmp/pure_bullet
```

The translated core retains Bullet's zlib notice in `src/core/mod.rs`. Its local
vendored patch ancestry remains pending audit. This is an initial migration
pilot, not evidence of complete Bullet or L2 replacement.
