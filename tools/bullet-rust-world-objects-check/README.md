# Check registered world objects

Run from the repository root.

```sh
python3 tools/bullet-rust-world-objects-check/check.py --out-dir /absolute/new/evidence-directory
```

The checker builds both unchanged native shim constructors in separate translation units. Public construction retains DBVT. MMD construction retains AxisSweep32 and its ray accelerator. It compiles a native-free Rust replay separately. No Cargo build or native Rust dependency is required.

Each replay emits all 206 records in a fixed sequence. Thirty snapshots cover public and MMD body registration, sphere/box/capsule/plane shapes, static/dynamic/kinematic flags, explicit signed filters, captured registration membership, active-only gravity changes, motion sync, teleport, reseat, stop, floor flags, joint collision references, limits, signed zeros, and spring equilibrium. Public uninitialized constraint UIDs and native uninitialized temporary motor fields are excluded.

The `B` records contain six transforms, four velocities, gravity acceleration, inverse local/world inertia, force/torque, inverse mass, damping, material values, processing threshold, collision flags, activation, filter, and disabled-constraint reference count. `J` records contain initialized limits, motor settings, springs, and the MMD UID. `W` records contain gravity and actual non-static registration indices. Creation, rejection, and foreign-handle statuses are separate records.

The native observer adds record-count observations without altering either shim. The Rust observer reads the same owned arrays. Both observer stdout comparisons and their count streams must match. Native and Rust raw stdout must match exactly. Unknown differences fail closed and retain the complete streams and diff. There are no approved numeric profiles or relaxed NaN comparisons.

Eleven named semantic mutants compile and execute as normal Rust programs. A mutant counts as caught only when its complete schema-valid trace differs. Build failures, crashes, incomplete streams, and survivors fail the checker. The default command runs every mutant. Use `--mutation NAME` to select a local check, or `--skip-mutations` for focused local capture. These modes return explicitly limited statuses.

The evidence directory retains source membership and raw hashes, generated-source membership and hashes, actual native include paths and hashes, compiler flags and effective macros, compiler/Rust versions, commands, stdout/stderr, normal/failure status, and start/end/finally receipts. Evidence directories must be new.

`harness.rs` also runs focused tests. The dispatcher/solver test passes the owner's borrowed arrays directly to existing consumers and observes their mutations through the owner. No mutable copies or native shadow state are used.

The workflow covers Windows x64, Apple Silicon macOS, Linux x64, and Linux ARM64 with actual architecture assertions and pinned Rust 1.95.0. A configured workflow is not an executed four-host result.

The public World and PhysicsScene remain native. Scheduler, `saveKinematicState`, broadphase integration, and complete World cutover remain required follow-on work.
