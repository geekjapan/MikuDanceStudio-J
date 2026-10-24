# P1. Bullet 2.75 from Rust, deterministic across CPUs

Question. Can a Rust program drive the vendored Bullet 2.75 through a C ABI, and
does one physics scene give bit-identical results on every target CPU?

Answer. Yes to both, once platform libm is replaced by `det_math.h`.

## Setup

- `shim/bt_shim.cpp` exposes `bt_world_new`, `bt_world_step`, `bt_world_hash`
  and `bt_world_tip_y` as `extern "C"`. The scene is a kinematic root capsule
  with 8 capsules hanging from it, linked by `btGeneric6DofSpringConstraint`
  with angular springs, gravity (0, -98, 0) and a static plane. The root follows
  a fixed polynomial path. Each frame calls `stepSimulation(1/30, 1, 1/60)`.
  The hash is FNV-1a over every body's transform and velocities.
- `build_bullet.sh` compiles `LinearMath`, `BulletCollision`, `BulletDynamics`
  from `recipes/bullet275/bullet-src/src` plus the shim with
  `-O2 -ffp-contract=off -fno-fast-math -fdeclspec`.
- `rs/` is a dependency-free Cargo crate that links `libbtshim.a`, runs 600
  frames, and writes one hash per frame to `trace.txt`.
- `shim/det_math.h` is force-included (`-include`) in the det builds. It routes
  `sinf`, `cosf`, `tanf`, `asinf`, `acosf`, `atanf`, `atan2f`, `expf`, `logf`
  and `powf` through the double-precision function and rounds to float.
- `linux_run.sh` repeats both builds inside `rust:1-bookworm` with clang.

## Results

| Target | libm | Final hash (frame 599) | trace.txt sha256 prefix |
|---|---|---|---|
| macOS arm64 | system | `29c3124e22c6ca1b` | `86a489a5dc5f0ad9` |
| macOS x86_64 (Rosetta) | system | `3ae627445fc532f6` | `5e0b5744ebfe98e8` |
| Linux arm64 (glibc) | system | `19602262462a8cb1` | `686352388a478199` |
| Linux amd64 (glibc) | system | `19602262462a8cb1` | `686352388a478199` |
| macOS arm64 | det_math | `b7be367fb1ece153` | `66bdc24e5bc301de` |
| macOS x86_64 (Rosetta) | det_math | `b7be367fb1ece153` | `66bdc24e5bc301de` |
| Linux arm64 | det_math | `b7be367fb1ece153` | `66bdc24e5bc301de` |
| Linux amd64 | det_math | `b7be367fb1ece153` | `66bdc24e5bc301de` |

The two macOS system-libm builds first diverge at frame 30. All four det_math
traces are byte-identical.

## What this does not show

- Windows. No Windows x64 build ran. MSVC's CRT math is a fifth libm.
- Parity with MikuMikuDance. The vendored `mmd*` x87 replay helpers compile
  only under `_MSC_VER && _M_IX86`. Every build here takes the plain float path,
  so the reachable parity target is the x64 (SSE) behavior, not x86 MMD.
- Real MMD scenes. The scene is synthetic. PMX rigid bodies and joints were not
  loaded.

## Toolchains

- macOS 27.0.1, Apple clang 21.0.0 (clang-2100.3.34.2), rustc 1.95.0.
- Linux image `rust@sha256:48b7f435b8fc6378ce43b44f15e3a47fd8919b2825f835c39bd4bd3da50af5b8`
  (`rust:1-bookworm`), rustc 1.99.1, Debian clang.

Paths in the scripts point at `/tmp/proto-bullet` and this checkout. They are
throwaway prototype scripts, kept as the record of what ran.
