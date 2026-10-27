# Bullet world motion passes

Run `python3 tools/bullet-rust-world-motion-check/check.py --out-dir /absolute/fresh/evidence`.
Use `python3 -O -m unittest discover -s tools/bullet-rust-world-motion-check -p 'test_*.py'` to check optimized Python acceptance boundaries.

The native oracle includes both unchanged shims in separate translation units. Protected world passes and local time are accessed through base-class member pointers, without a derived-object cast or native header modification. The Rust replay uses the actual `WorldObjects` owner and its captured registration order.

Each public/MMD replay has four transform variants and eighteen snapshots. It captures complete body, interpolation, motion, inertia, force, torque, activation, filter, hit fraction and registration state. The 1,368 records cover static and kinematic registration, later kinematic changes, active/sleeping/disabled bodies, zero and nonzero timesteps, damping, distinct interpolation velocities, all/default synchronization, three hit fractions, and teleport/reseat/stop interleaving. Rotations include nonunit quaternion input and all matrix extraction branches. One MMD variant uses finite invertible nonorthogonal matrices to distinguish matrix inverse from transpose.

Twelve controls compile and execute altered Rust implementations. They must emit schema-valid traces that differ from native. The checker records source membership/hashes, generated source membership/hashes, actual compiler include membership/hashes, commands, versions, flags, macros, raw traces, observer traces, and mutation results. Command and acceptance boundaries use explicit runtime errors under normal and optimized Python. Start/end/finally closure comparisons fail closed.

The four supported host jobs run native differential checks. Workflow configuration is not executed CI evidence. No numeric tolerance or host profile is approved by this checker. Public World/PhysicsScene cutover, the step scheduler, broadphase, islands, callbacks and GPU execution remain outside this unit.
