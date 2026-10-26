# Compare the joint solver with Bullet 2.75

Run from the repository root:

```sh
python3 tools/bullet-rust-solver-check/check.py --out-dir /tmp/mds-joint-solver
```

The check compiles the vendored `btSequentialImpulseConstraintSolver.cpp`, captures
native output, checks the committed fixtures, and runs Rust tests and focused
Clippy with Rust 1.95.0. Native floating-point contraction and fast math are off.
`det_math.h` selects the same SSE path used by supported application targets.
Use `--record` only when deliberately updating the native fixtures.

The 512 solves cover 256 SIMD and 256 scalar solves. Each pair reuses the bodies
and joint state from its preceding solve. The native setup and iteration functions
run directly, with ten iterations throughout. Existing native `postnc` logging
provides every SIMD row impulse and both bodies' velocity deltas. Scalar mode
compares setup, final impulses, and final velocities; its existing native loop
has no per-row logger. The adapter does not implement solver arithmetic.

Fixtures include two joints sharing a body, dynamic and mass-zero bodies,
mass-zero and nonzero-mass kinematic bodies, zero-row joints, linear limit
boundaries, angular fixed-limit boundaries, free and locked axes, nonidentity
rotations and inertia, nonzero velocities, signed zero, and nonunit factors.
Springs include both constructor-zero equilibrium and the no-argument
`setEquilibriumPoint()` used by MMD. Seeded cases use a bounded xorshift stream.

A separate 64-case native fixture checks factor setters, central force, torque,
gravity, velocity integration, and force clearing. The focused harness also runs
the unchanged 5,247-row body fixture. Existing kernels compile as a support crate
so focused Clippy checks the changed body, solver, and tests without suppressing
lints in existing math and time code.

The core remains disconnected from the public World. Integration must register
`core::solver` and `pure_bullet::joint_solver` in the shared module files. Contacts,
friction, island assembly, activation, transform integration, hosted target checks,
and the complete workspace gate remain separate work.
