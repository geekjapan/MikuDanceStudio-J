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
`--record` replaces only this check's new frozen input and native output files.
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
Signaling NaNs and x87 Win32 behavior are not covered. Native recapture runs on
Linux x64 CI; the other CI jobs replay the frozen native-derived prefix.
