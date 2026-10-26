# Nonvirtual convex support parity

`Shape` ports the sphere, box, and Y capsule branches of Bullet 2.75's
`localGetSupportVertexWithoutMarginNonVirtual` and `localGetSupportVertexNonVirtual`.
Only static planes return `None`. Identity scaling and default margins match the
application. Raw dimensions remain unchecked, as in `mds_mmd_body_create`.

The virtual support entry remains available for convex-plane collision. Its box
expands each axis, while nonvirtual support adds a normalized 0.04 margin to a
corner. Capsule support retains the native length associations, reciprocal
multiplication, positive cap first, strict maximum comparison, and separate
radius multiplication and margin subtraction.

Run the native check with Python 3, Clang, and Rust 1.95.0.

```sh
python3 tools/bullet-rust-support-check/check.py --out-dir /tmp/bullet-support
```

The checker calls the actual vendored shape APIs, compares 3,377 full rows with
pure Rust, and checks the frozen 1,600-row complete prefix. Each row compares nine
raw output words across both nonvirtual entries and the existing virtual entry.
The original ARM fixtures are immutable. `support-profiles.json` fixes the SHA-256
hashes and enumerates every permitted case and field difference in the Linux x64
profile. Only 210 arithmetic NaN sign words in 126 compact cases differ. All other
words, row IDs, schemas, and counts remain exact.
The shared `tools/bullet-rust-math-check/check.py --rust-only` runner replays the
same prefix without a C++ compiler on all four supported CI hosts.

The directed prefix includes axes, octants, signed zeros, nonunit directions,
tiny and huge values, positive, zero, and negative dimensions, margin-adjacent
float dimensions, and quiet NaN and both infinities in each input position.
Capsule and margin length checks include exactly the threshold and its two
adjacent float words. The remaining 2,000 full rows use a deterministic seed.
No NaN sign or payload normalization is applied.

An observed copy of `btConvexShape.cpp` records capsule lengths, cap comparisons,
and margin lengths and fallbacks. Its stdout must equal the original executable's
stdout byte for byte. The checker retains the hook diff, compiler command,
provenance, source and capture hashes, raw coverage, and a coverage summary.
The original Bullet sources and all older fixtures remain unchanged.

Eight isolated Rust mutations must fail against the compact prefix. They replace
the nonvirtual entry with the virtual entry, add the sphere radius without margin,
remove capsule margin subtraction, admit equal cap dots, admit capsule threshold
equality, change either length association, or combine capsule radius and margin.
Mutation source copies and failing test logs remain under the output directory.

This is a prerequisite for generic convex collision. It does not implement GJK,
EPA, mixed-pair dispatch, world integration, or nonidentity shape scaling.
Signaling NaNs and x87 Win32 behavior are not covered. The `bullet-support-host-profiles.yml` workflow captures original and observed native
stdout and replays all 3,377 rows against Rust on Windows x64, macOS ARM64,
Linux x64, and Linux ARM64. It saves `native.tsv`, `observed.tsv`, `rust.tsv`,
compiler commands, source manifests, hashes, and host provenance. Windows uses
MSVC with the reviewed joint host probe's CMake flags and native static libraries.
The helper runs the full same-host Rust replay before checking a frozen profile.
Unknown host profiles fail after their captures are saved. Windows and Linux ARM64
profiles require actual captures and review before promotion. No host is inferred
from another host's CPU architecture.

Run the capture and comparator negative controls with:

```sh
python3 -m unittest discover -s tools/bullet-rust-support-check -v
```

The Linux profile comes from artifact 12689482840 of run 40399749981, capture commit
`012fe478b852cb21de7c0c4dd134529c2331d348`. Its checked source tree is equivalent to
`0a3f0b5880cce4008c041c2fa954f916a9c98b74`. Support sources match
`6c87687fc80cd1480afa6ba8f0a2a8d7421586be`. The ARM baseline is the accepted
3,377-row capture, not the older 3,188-row capture. Captured native agreement
between hosts does not establish same-host Rust replay until that replay runs.
