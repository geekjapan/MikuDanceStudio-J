# Check registered world objects

Run from the repository root.

```sh
python3 tools/bullet-rust-world-objects-check/check.py --out-dir /absolute/new/evidence-directory
```

The checker builds both unchanged native shim constructors in separate translation units. Public construction retains DBVT. MMD construction retains AxisSweep32 and its ray accelerator. It compiles a native-free Rust replay separately. No Cargo build or native Rust dependency is required.

Each replay emits all 478 records in a fixed sequence. The original 206 records remain byte-for-byte cases within the expanded trace. Sixty-five snapshots cover public and MMD body registration, sphere/box/capsule/plane shapes, static/dynamic/kinematic flags, explicit signed filters, captured registration membership, active-only gravity changes, motion sync, teleport, reseat, stop, floor flags, joint collision references, limits, signed zeros, and spring equilibrium. Added cases observe each constructor before gravity changes, nontrivial body and joint rotations, rotated MMD motion sync and reseat, and nonidentity motion-offset read and write products. The rotated angular spring has positive stiffness and nonzero equilibrium. Public uninitialized constraint UIDs and native uninitialized temporary motor fields are excluded.

The rotated `T` records compare both initialized joint frames directly. `O` records compare graphics, offset, start, and readback motion transforms. The `B` records contain six transforms, four velocities, gravity acceleration, inverse local/world inertia, force/torque, inverse mass, damping, material values, processing threshold, collision flags, activation, filter, and disabled-constraint reference count. `J` records contain initialized limits, motor settings, springs, and the MMD UID. `W` records contain gravity and actual non-static registration indices. Creation, rejection, and foreign-handle statuses are separate records.

The native observer adds record-count observations without altering either shim. The Rust observer reads the same owned arrays. Both observer stdout comparisons and their count streams must match. Native and Rust raw stdout must match exactly. Unknown differences fail closed and retain the complete streams and diff. There are no approved numeric profiles or relaxed NaN comparisons.

Eleven named semantic mutants compile and execute as normal Rust programs. A mutant counts as caught only when its complete schema-valid trace differs. Build failures, crashes, incomplete streams, and survivors fail the checker. The default command runs every mutant. Use `--mutation NAME` to select a local check, or `--skip-mutations` for focused local capture. These modes return explicitly limited statuses.

The evidence directory retains source membership and raw hashes, generated-source membership and hashes, actual native include paths and hashes, compiler flags and effective macros, compiler/Rust versions, commands, stdout/stderr, normal/failure status, and start/end/finally receipts. Evidence directories must be new.

`harness.rs` also runs focused tests. The dispatcher/solver test passes the owner's borrowed arrays directly to existing consumers and observes their mutations through the owner. No mutable copies or native shadow state are used.

The workflow covers Windows x64, Apple Silicon macOS, Linux x64, and Linux ARM64 with actual architecture assertions and pinned Rust 1.95.0. A configured workflow is not an executed four-host result.

The public World and PhysicsScene remain native. Scheduler, `saveKinematicState`, broadphase integration, and complete World cutover remain required follow-on work.

The retained 206-record native trace is the schema regression fixture. Schema checks distinguish float words, booleans, signed metadata, creation statuses, record identities, counts, and membership indices. Every f32 bit word is valid syntax, including NaNs. Invalid mutant output fails before mutation credit. These checks remain active under Python `-O`.

Boundary cases execute the unchanged shims. Public construction rejects negative mass, infinite mass, NaN positions, and NaN friction without adding bodies. MMD raw construction accepts negative mass and nonfinite materials. Their raw fields remain exact comparisons.

The integrity probe executes the same complete `check.main` and changes a real source file after successful comparison, immediately before `finally`.

```sh
python3 tools/bullet-rust-world-objects-check/integrity_probe.py --out-dir /absolute/new/integrity-evidence
python3 tools/bullet-rust-world-objects-check/integrity_probe.py --legacy-finally --out-dir /absolute/new/legacy-integrity-evidence
```

The legacy option substitutes only the previous finally block to reproduce its contradictory PASS status with failed integrity. The normal probe requires FAIL status and a specific source-closure error. Both probes remove their injected marker after retaining the receipt.
