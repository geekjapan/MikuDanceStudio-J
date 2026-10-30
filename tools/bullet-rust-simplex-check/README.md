# Bullet 2.75 simplex comparison

This standalone check compares `core/simplex.rs` with the vendored
`btVoronoiSimplexSolver.cpp`, compiled unchanged. It does not connect the Rust
solver to GJK, EPA, or the public World.

Run from `rust/` with Python 3, Clang, and Rust 1.95.0 installed.

```sh
python3 ../tools/bullet-rust-simplex-check/check.py --out-dir /tmp/mds-simplex
```

The helper compiles the native solver with `-O2 -ffp-contract=off
-fno-fast-math` and the existing `det_math.h` and SSE emulation configuration.
It checks both native source hashes before compilation. It compiles the Rust
solver through a dedicated `#[path]` harness using the existing `Vec3`.
The kernel is exposed by the shared core module. The harness and native-free
pure driver share one trace runner. The twelfth native CI group runs this helper;
no dependency or build script is added.

The finite-input corpus contains 2,286 scenarios and 29,940 operations. It covers
all three segment usage masks, all seven triangle masks, and all fifteen nonempty
tetrahedron masks. The check asserts these masks against actual native output.
It also asserts native degeneracy below, exactly at, and above the `1e-4f`
plane-sign threshold. Cases include all simplex sizes, winding and permutations,
face and edge ties, duplicates, independent stored `w` and witness values,
removed-last-vertex membership, signed zero, ULP neighbors, coincident and
collinear vertices, coplanar tetrahedra, cancellation, subnormals, large finite
overflow, repeated closest queries, compute-points-first queries, and cache
retention across invalid queries and reset. A separate exceptional-input corpus
contains 13 scenarios and 172 operations, including its valid cache seed.

Each snapshot includes the operation result, count, full/empty flags, dirty and
valid flags, degeneracy, four usage bits, four barycentrics, last `w`, maximum
vertex length, defined cached witnesses and closest vector, defined closest
simplex point, vertex order and stored `w/p/q`, and defined returned vectors.
Every non-NaN float uses its raw bits, including signed zero and infinities.
NaNs compare by classification. Their payloads are not a portable contract.
Finite inputs that overflow can also produce NaNs under this rule.

The native oracle tracks cache and closest-point initialization separately.
An underscore marks a field that native Bullet has not initialized. The first
valid singleton seeds the witness caches before any empty closest query.
The oracle does not fabricate values for undefined fields or copy the solver
algorithm. Rust initializes fresh caches to zero for safety. Equivalence claims
exclude native fields before their first defined value.

`fixtures/*.tsv.gz` contain frozen native snapshots. Python's standard library
decodes them and compares them to the live native capture. Invalid compression,
source changes, fixture changes, and field mismatches fail the check.
`fixtures/sha256.json` records compressed fixture, decoded fixture, and generated
input hashes. Raw inputs, captures, labels, compiler command, and `summary.json`
remain in the selected output directory. `--record` deliberately replaces only
these helper-owned fixture files and their hash manifest.

The helper also compiles a temporary mutant that returns stored `w` for a
singleton instead of `p - q`. The native comparison must reject it.
Three Rust tests cover the selected native snapshots, fifth-vertex rejection and cache/last-vertex behavior. The selected plain-text
fixtures and provenance are documented in
`rust/crates/mds-bullet/tests/simplex_data/README.md`.
Run those tests without native compilation or capture from `rust/`.

```sh
rustup run 1.95.0 rustc --edition=2021 --crate-name mds_crtmath --crate-type rlib -O crates/mds-crtmath/src/lib.rs -o /tmp/libmds_crtmath.rlib
rustup run 1.95.0 rustc --edition=2021 --test -D warnings -O ../tools/bullet-rust-simplex-check/harness.rs --extern mds_crtmath=/tmp/libmds_crtmath.rlib -o /tmp/mds-simplex-tests
/tmp/mds-simplex-tests
```

The Rust type supports four meaningful simplex vertices and rejects a fifth
before changing state. Bullet's five-slot storage does not establish valid
five-vertex GJK behavior. The application uses only three vector components and
resets the simplex for every GJK query. No SIMD fourth-lane or frame-cache
behavior is claimed. EPA uses a different internal algorithm and is excluded.
The translated source retains the Bullet zlib notice and the Ericson,
Real-Time Collision Detection, Morgan Kaufmann, and Elsevier credit conditions.
