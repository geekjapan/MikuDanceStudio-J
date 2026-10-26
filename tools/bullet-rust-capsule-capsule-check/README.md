# Capsule pair parity check

The Rust `PairManifold` ports Bullet 2.75's Y-axis capsule fast path from
`btConvexConvexAlgorithm.cpp`. Capsule height is the distance between cap centers.
The segment calculation uses half that height and each capsule's radius directly.
The shape's 0.04 AABB margin does not enlarge the narrowphase radius.

The oracle constructs real capsule shapes, a Voronoi simplex solver, an EPA solver,
and an owned `btConvexConvexAlgorithm`. Its minimal dispatcher allocates a real
`btPersistentManifold`. Every transform step calls the original `processCollision`
with a real `btManifoldResult`. This fast path returns before GJK or EPA executes.

Run the check from the repository with Python 3, Clang, and Rust 1.95.0 installed.
The script runs compiler commands from `rust/`.

```sh
python3 tools/bullet-rust-capsule-capsule-check/check.py --out-dir /tmp/capsule-parity
```

The check compares every initialized manifold field in contact order using raw
float bits. It includes the breaking threshold, local and world witnesses, normal,
distance, combined materials, impulses, lifetime, and friction initialization.
Friction directions are compared only when initialized. Undefined directions are
serialized as zeros by both adapters. No helper witnesses are read after a distance
above the threshold returns early.

The directed scenarios cover parallel, exact antiparallel, skew and crossing axes,
both endpoint clamps, zero heights, asymmetric dimensions, coincident centerlines,
both tangent branches, exact threshold equality and its adjacent floats, reversed
inputs, large shared translations, and contact replacement, slide, separation, and
reentry. Another 400 deterministic generated scenarios extend the native comparison.
The committed fixtures retain the 32 complete directed scenarios, including all
observed branch labels. `--freeze` writes those native-derived fixture bytes.

The check compiles an observed copy of the original source under the output
directory. It records source hashes and the hook diff, compares the original and
observed stdout byte for byte, and requires every transform step to take the capsule
fast return. The vendor tree remains unchanged. Four temporary Rust mutations must
fail against the compact fixture. They admit threshold equality, add a 0.04 radius
margin, omit the A recomputation after the B clamp, or replace the tangent normal.

The pure runner consumes the same compact scenarios without native dependencies
beyond the existing Rust math crate. This check does not exercise world dispatch,
mixed convex pairs, GJK, EPA, the solver, or GPU behavior. The inherited Linux x64
joint case 512 NaN-sign gate remains separate.
