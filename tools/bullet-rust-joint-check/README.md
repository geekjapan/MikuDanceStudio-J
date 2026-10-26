# Bullet joint row oracle

Run from the repository root with an output directory outside the checkout.

```sh
python3 tools/bullet-rust-joint-check/check.py --out-dir /tmp/mds-bullet-joints
```

`--record` replaces `rust/crates/mds-bullet/tests/joint_data/native.tsv` with output from the actual vendored Bullet sources. The tool builds the deterministic CRT math library, native oracle and standalone Rust test. No Cargo build or Bullet World is needed. CXX may select the C++ compiler. The build flags follow the existing shape oracle.

The native adapter constructs real rigid bodies and `btGeneric6DofSpringConstraint` objects. It calls `buildJacobian`, `getInfo1`, then `getInfo2` only when rows exist. A subclass exports the coordinates produced by the native coordinate calculation. It never copies the native spring or row-generation algorithm. Local diagnostic dump environment variables are removed for the oracle process.

The 378 cases contain 63 sequences of six frames. They cover zero through six rows, both linear reference flags, free and locked limits, exact boundaries, low/high violations, motors approaching limits in both directions, zero motor targets, spring force and damping, zero-row spring preservation, disabled spring motors, angular wrap, stale angular error, and incoming/outgoing bounce. Every emitted row float and stored state word is compared, including signed zero. Rust state is carried across each sequence and checked against the next native prior state.

Each fixture line begins with a decimal case ID. All remaining columns are hexadecimal u32 words. Floats use their IEEE-754 bits. Integers and booleans use their numeric values.

1. Coordinates contain row-major basis A (9), pivot B (3), linear diff (3), angular diff (3) and angular axes (9).
2. Body A then B contain origin, linear velocity and angular velocity (9 each).
3. Step contains fps, erp and iteration count (3).
4. Prior state contains three linear motors (8 each), three angular motors (10 each), linear ERP (1) and six springs (4 each).
5. Row count (1) precedes zero through six rows. Each row contains axis index (1), J1 linear (3), J1 angular (3), J2 angular (3), positional rhs, cfm and lower/upper impulse (4).
6. Final state uses the same layout as prior state.

Motor words are lower, upper, enabled, target velocity, maximum motor force, current position, current limit and current limit error. Angular motors append ERP and bounce. Springs contain enabled, equilibrium, stiffness and damping. Axis indices are linear XYZ then angular XYZ. J2 linear is implicitly negative J1 linear.

This check covers pre-solver rows with already calculated coordinates. Coordinate calculation, solver finalization, masses/inertia, warm starts and end-to-end World behavior remain outside this unit. `joint_rows.rs` is an altered zlib-licensed translation of Bullet, including vendored local patches whose ancestry remains pending audit. It does not apply a blanket MIT license.
