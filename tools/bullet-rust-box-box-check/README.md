# Verify the Rust Bullet box detector

Run from the repository root with Python 3, clang++, and Rust 1.95.0 installed.

```sh
python3 tools/bullet-rust-box-box-check/check.py --out-dir /tmp/mds-bullet-box-box
```

The command compares the new `core/box_box.rs` module with the actual vendored Bullet 2.75 detector. The module is registered in the shared pure core and selected by `PairManifold::new` for two boxes. It returns up to four ordered `BoxContact` records from `box_box_contacts(shape_a, world_a, shape_b, world_b)`. Each record contains the normal on B, world point on B, and signed distance. Non-box input returns `None`. Supported boxes use identity shape scaling and rigid world transforms.

The first oracle layer calls `btBoxBoxDetector::getClosestPoints` with a real `Result` sink. It compares count, order, normal, point, and distance as raw float bits. The second layer repeatedly calls the actual `btBoxBoxCollisionAlgorithm`, `btManifoldResult`, and `btPersistentManifold`. It compares the manifold threshold, count, order, local points, world points, normal, distance, friction, restitution, all three impulses, lifetime, and friction-direction validity. Directions are compared only when valid. The native driver seeds valid directions before reading them and never reads uninitialized directions.

Owned manifolds refresh after every collision call without clearing. Borrowed manifolds retain points until an explicit refresh. The native dispatcher derives the threshold from both real shape methods. The Rust harness uses production `PairManifold::new/process` for owned manifolds. A temporary copy of `contact.rs` exposes the shared trace test as a child module so borrowed characterization can reach the unchanged private add/refresh methods. It adds no production API and implements no separate contact cache.

The corpus covers separation, exact touching, face and edge contacts, clipping through eight vertices, deepest-first angular culling, input swaps, near-parallel bases, thin shapes, small negative implicit extents, and dimensions from 0.000001 to thousands. Repeated traces cover slides, merge and breaking thresholds, separation, re-entry, refresh, and impulse retention. Materials vary between the two bodies.

The checker also builds an observation-only temporary copy of `btBoxBoxDetector.cpp`. Two calls record selected SAT code, clipped polygon size, and penetrating candidate count before culling. The original vendor file is never changed. `observation.diff` and `detector.sha256` retain the exact hook and source identity. Output from the observed detector must match the unmodified detector byte for byte. Coverage assertions require all 15 selected SAT codes, polygon sizes three through eight, and candidate counts one through eight. Polygon size zero denotes the edge-contact hook. These observations do not prove every internal branch or every early separating-axis exit.

The final author regression compiles a temporary Rust variant that keeps the first four candidates instead of applying native angular culling. The comparison must reject that variant. `first-four-regression.txt` retains the observed mismatch. Production source is unchanged by this test.

The output directory retains generated inputs, native output, both native executables, the Rust executable, CRT libraries, the temporary cache adapter, coverage, native source hashes, and regression evidence. The checker also verifies compact frozen native traces in `tests/box_box_data`. The combined `pure_bullet.rs` runner exercises these fixtures without native code or environment-dependent skips. Per-operation native coverage selects complete owned groups covering all 15 SAT codes, polygon sizes three through eight, and pre-cull counts one through eight. No fixture regeneration flag is provided. Native builds use the existing deterministic CRT math and SSE emulation with contraction disabled. Rust arithmetic preserves the vendored mixed float and double expressions, axis order, strict comparisons, and contact order.

This is an altered translation of the vendored Bullet 2.75 ODE-derived box detector. `box_box.rs` retains the original Russell L. Smith and Erwin Coumans zlib notice. This work does not relicense Bullet.

The shared dispatcher now supports box-box alongside sphere-sphere and convex-plane pairs. Other convex pairs remain explicitly unsupported. GJK and EPA, capsule fast paths, ray tests, CCD, and public World integration remain outside this unit. The Linux native CI job runs this full corpus as its eleventh group. General builds and shared pure CI cover the four supported targets separately.
