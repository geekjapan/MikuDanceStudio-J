# Check Bullet contact translation

Run the focused native differential check from the repository root.

```sh
python3 tools/bullet-rust-contact-check/check.py --out-dir /tmp/mds-bullet-contacts
```

The check requires Python 3, clang++, and the installed Rust 1.95.0 toolchain. The native driver follows the existing shape check's macOS and Linux compiler setup. The Rust contact tests also run through `core::contact` after that module is exported by the integration owner.

`check.py` compiles the vendored `btSphereSphereCollisionAlgorithm`, `btConvexPlaneCollisionAlgorithm`, `btManifoldResult`, `btPersistentManifold`, shape implementations, collision objects, and algorithm bases. A test-only dispatcher supplies one owned manifold. Every unexpected dispatcher method aborts. It derives the manifold threshold by calling the real shape `getContactBreakingThreshold()` methods. Plane algorithms use the native default one perturbation iteration and one-point minimum.

The native build force-includes the existing `det_math.h`, uses the existing SSE emulation headers, and links the actual Rust CRT implementation. It does not reproduce contact formulas in the C++ driver. The driver initializes shape identifiers to -1. A separate native identity query proves that the corpus includes contacts produced only by perturbation, in both input orders.

The generated input corpus and native output must match the checked-in fixtures. Rust then replays every operation and compares point count, order, threshold, all 21 initialized contact float words, and lifetime. Excluded fields are native pointers, padding, triangle identifiers, and solver-only friction directions and their validity flag. The Rust contact record omits those solver fields. New Rust contacts initialize all their fields. Existing impulse and lifetime values survive nearest-point replacement.

The corpus covers sphere pairs, sphere/box/Y-capsule against planes in both orders, moving and tilted planes, rotations, epsilon fallbacks, equality boundaries, zero and negative raw dimensions, +/-0 support directions, stale contacts, and perturbation-only contacts. Direct cache traces exercise all four replacement slots, deepest-point scoring, equal-area and nearest-point ties, strict merge thresholds, swap-last removal, refresh, and impulse/lifetime retention. Unit assertions check the cache rules separately. As in native Bullet, zero-area degeneracy can tie the protected deepest point's zero score and select slot zero.

`--record` intentionally replaces both checked-in fixtures with newly captured native output. Normal verification never changes fixtures. The output directory retains the native executable, Rust test executable, generated inputs, native output, and compiled CRT libraries.

This is an altered translation of Bullet 2.75 and its vendored local patches. The Bullet zlib notice remains in `rust/crates/mds-bullet/src/core/mod.rs`. Patch ancestry remains subject to the migration's separate provenance audit. This work does not relicense Bullet as MIT.

The production backend remains native. Box-box, general convex GJK/EPA, CCD, broadphase, filtering, callbacks, solver, and world are outside this unit. Supported-host CI and the whole integration suite are separate gates.
