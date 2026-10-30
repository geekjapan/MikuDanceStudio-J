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

The combined `pure_bullet.rs` executable also runs the math and shape fixtures.
Use the pinned, native-free command on Windows x64, macOS ARM64, Linux x64 or
Linux ARM64 (Python 3 and Rust 1.95.0 required):

```sh
python3 tools/bullet-rust-math-check/check.py --rust-only
```

The dedicated `bullet-primitives.yml` workflow runs these six tests on all four
supported hosts, and recaptures math and shapes from native sources on Linux x64.
Workflow configuration is not evidence that those hosted jobs have passed.

The translated core retains the full Bullet zlib notice in `src/core/mod.rs`.
Pilot math/body/time operations were compared with stock Bullet 2.75 non-x86
branches from the official archive with SHA-256
`0ebae4b2afabcd493d5878efb4582f3dda82e2088b3ca18d6ec6aeb0ef69329d`.
New math (including solver SSE dot) and shape inertia include vendored local
patches whose ancestry remains pending audit, as do unported vendored ranges. The wrapper remains MIT and crate metadata
remains `MIT AND Zlib`. Frozen fixtures establish numerical behavior, not legal
provenance or complete Bullet/L2 replacement.
