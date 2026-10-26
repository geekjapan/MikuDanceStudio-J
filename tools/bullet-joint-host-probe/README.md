# Joint solver host output probe

This standalone diagnostic captures all 518 joint cases, including 20,580 SIMD
row events, from native Bullet and pure Rust on the same host. It does not edit
production arithmetic, strict checks, native source, or frozen fixtures.

Run from a checkout with Rust 1.95.0 and Clippy installed. All Rust commands run
from `rust/`, as in the original solver check.

```sh
python3 tools/bullet-joint-host-probe/probe.py \
  --profile clang-helper --out-dir /absolute/empty/evidence-directory
python3 -m unittest discover -s tools/bullet-joint-host-probe -v
```

The dedicated `bullet-joint-host-probe.yml` workflow runs Linux x64 and two Windows
x64 MSVC profiles. Windows activates the existing `vswhere` / `VsDevCmd` pattern.
`msvc-ffi-default` uses the current `mds-bullet-sys/build.rs` MSVC flags and omits
`WIN32`. `msvc-cmake-win32` adds `WIN32`, the original CMake profile's relevant
Bullet configuration macro. Both use `/O2 /MD /fp:precise /EHsc /W0`, the unchanged
force-included `det_math.h`, real MSVC intrinsics, and the real Rust CRT staticlib.
The latter characterizes the CMake macro configuration with the helper's math
adapter. It is not a full application build or an independently proven app
oracle. Neither Windows output is presumed to match Linux or the ARM fixture.

The probe executes an asserted temporary copy of the existing solver check. Its
two frozen-fixture early exits become explicit `FAIL diagnostic` observations.
The native oracle, source list, trace parser, and Rust build machinery remain the
existing ones. The copied Rust test reads the fresh same-host `native.tsv` at
compile time and replaces its per-word equality loop with actual TSV emission.
This uses the native oracle's serialized inputs even when C++ argument evaluation
order differs between compilers. It preserves the length check, all property assertions,
repeated-state handling, and links directly to unchanged production modules.
The harness redirects only its test path to that temporary copy. A changed
adapter anchor fails rather than silently adapting different code.

Each completed output directory contains the copied adapters and unified diffs,
`native.tsv`, `rust.tsv`, raw native `oracle.tsv`, `resolve.log`, `factors.tsv`,
`effective-profile.txt`, effective compiler commands, compiler/Rust versions,
source and artifact SHA-256 hashes, logs, and `status.json`. Comparison tables
retain every differing word exactly, including NaN payload/sign, signed zero,
finite values, infinity, and structural differences. `field` is the zero-based
TSV field, with case ID at field 0. Joint output word 0 is field 302.
No normalization is applied. Joint comparisons record SHA-256 fingerprints over
every case ID and all 301 serialized input words, in case order. A same-host
input mismatch fails the input invariant. Frozen comparisons explicitly report
input inequality when present, so output differences cannot be attributed to
arithmetic alone. Separate frozen comparisons remain visible even
when same-host Rust/native bits agree. The workflow fails on a same-host exact
mismatch or an incomplete capture; frozen-only differences are diagnostic FAIL
records and do not prevent collecting Rust output.

Failure finalization starts immediately after accepting the empty output
directory, including adapter setup and compiler, Rust, and Git metadata checks.
`status.json` records the failing phase, original error, and subprocess return
code. `sha256.json` covers existing sources and artifacts, including that status.
Every subprocess saves raw stdout, stderr, command, and return-code status before
checking success. Native factor and oracle stdout also reaches `factors.tsv` and
`oracle.tsv` on failure, preserving partial binary bytes. The original failure
propagates, and incomplete captures never receive an execution PASS. A nonempty
output directory is refused without changing its contents.

Each matrix job uploads its complete evidence even on failure. Windows profile
artifacts each contain a Rust capture and its comparison to that profile's actual
native capture. Workflow configuration is not evidence that a hosted run passed.
