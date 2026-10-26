# Check the Bullet Rust math translation

Run the focused native and native-free gate on macOS or Linux with Clang, Python 3, and the existing Rust 1.95.0 toolchain.

```sh
python3 tools/bullet-rust-math-check/check.py
```

The script compiles only `mds-crtmath` and the C++ header oracle. It compares the native output with `rust/crates/mds-bullet/tests/data/math-native-bits.tsv`, then runs the combined standalone Rust math, shape and free-body pilot tests. It does not build `mds-bullet-sys`, the application, or the workspace. Compiler outputs use an isolated temporary directory. Pass `--work-dir PATH` to place that directory under an assigned evidence store.

To run only the frozen-fixture Rust checks on any supported host, including
Windows x64, use `python3 tools/bullet-rust-math-check/check.py --rust-only`.
This mode builds only the `mds-crtmath` rlib and the combined test executable.
It does not invoke C++, build scripts, Cargo, or `mds-bullet-sys`.

To replace the fixture after an intentional native behavior change, pass `--record`. Review the fixture change before accepting it.

The native oracle includes the actual vendored `btVector3`, `btMatrix3x3`, `btQuaternion`, `btTransform`, and `btTransformUtil` headers. Clang uses the same `-O2 -ffp-contract=off -fno-fast-math -fdeclspec` flags, `shim/sse_emu` include, and force-included `shim/det_math.h` as the current non-MSVC native build. The oracle links the real Rust `mds-crtmath` C exports. It does not use system sin/cos substitutes. `BT_USE_SSE` is asserted, and the solver dot expression uses the emulated intrinsics in the same order as the locally patched `_vmathVfDot3`.

The C++ oracle and Rust math are altered translations of the vendored Bullet 2.75 sources, including local patches. The Bullet zlib notice is retained in `rust/crates/mds-bullet/src/core/mod.rs`. Local patch ancestry remains pending audit. These files do not relicense Bullet as MIT.

## Fixture format and coverage

Each TSV row begins with its operation name. Every remaining word is an eight-digit hexadecimal IEEE f32 bit pattern. Inputs precede outputs, in the order below. Matrices contain three rows. Transforms contain the basis followed by the origin.

| Operation | Input fields | Output fields | Rows |
| --- | --- | --- | --- |
| `vector` | a, b | add, subtract, negate a, cross, scalar dot, a length squared, a length, normalized a, solver SSE dot | 49 |
| `quaternion` | axis, angle, other quaternion, vector | axis-angle quaternion, conjugate, product, rotated vector, length squared, normalized quaternion, basis | 25 |
| `basis` | a, b, vector | product, inverse, transpose, applied vector | 16 |
| `transform` | a, b, point | product, rigid inverse, applied point, inverse-applied point, extracted quaternion | 25 |
| `integrate` | transform, linear velocity, angular velocity, dt | integrated transform | 1000 |

The 1115 rows compare 14986 output words. Cases include cancellation that distinguishes scalar `(x+y)+z` from solver `(z+y)+x`, signed zero, small vectors, nonorthogonal invertible matrices, arbitrary rotation axes, and all four matrix-to-quaternion branches. Angular velocities cover zero, below/equal/above 0.001, the Taylor and trigonometric paths, and below/equal/above the angular-motion clamp at dt=1/60. Timesteps include zero, 1/60, 1/8, and a negative value. Clamp boundary velocities are 47.123878479003906, 47.1238899230957, and 47.1239013671875. The middle value multiplied by float dt equals the float threshold.

Normalization requires nonzero finite inputs. Matrix inverse requires a nonsingular basis. Quaternion conjugation and rigid transform inverse retain Bullet's unit-quaternion and orthonormal-basis assumptions. NaN payloads, infinities, denormal handling, and Win32 x87 patches are outside this fixture. Win32 is unsupported by the migration target contract.

Recorded and checked on Apple Silicon macOS 27.0.1 with Apple Clang 21.0.0 and rustc 1.95.0. Other supported host executions remain required in CI. A matching ARM64 result does not prove Windows x64, Linux x64, or Linux ARM64 execution.
